import base64
import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd

DB_PATH = "people_counter.db"
ZONE_FILE = "zones.json"
LOG_FILE = "people_counts.csv"
DEFAULT_ADMIN_EMAIL = "admin@peoplecounter.local"
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_JWT_SECRET = "people-counter-demo-secret"


def utc_now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def get_connection():
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            jwt_token_id TEXT NOT NULL,
            token TEXT NOT NULL,
            ip_address TEXT,
            login_at TEXT NOT NULL,
            logout_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS cameras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            source_url TEXT NOT NULL,
            stream_type TEXT NOT NULL,
            location TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            zone_code TEXT NOT NULL UNIQUE,
            zone_name TEXT NOT NULL,
            x1 INTEGER NOT NULL,
            y1 INTEGER NOT NULL,
            x2 INTEGER NOT NULL,
            y2 INTEGER NOT NULL,
            threshold_limit INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(camera_id) REFERENCES cameras(id)
        );
        CREATE TABLE IF NOT EXISTS count_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            zone_code TEXT NOT NULL,
            zone_name TEXT NOT NULL,
            people_count INTEGER NOT NULL,
            density_score REAL NOT NULL,
            threshold_value INTEGER NOT NULL,
            status TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            FOREIGN KEY(camera_id) REFERENCES cameras(id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            zone_code TEXT NOT NULL,
            zone_name TEXT NOT NULL,
            threshold_value INTEGER NOT NULL,
            observed_value INTEGER NOT NULL,
            status TEXT NOT NULL,
            triggered_at TEXT NOT NULL,
            resolved_at TEXT,
            FOREIGN KEY(camera_id) REFERENCES cameras(id)
        );
        CREATE TABLE IF NOT EXISTS report_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            report_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            from_time TEXT,
            to_time TEXT,
            exported_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.commit()
    connection.close()
    upsert_setting("jwt_secret", DEFAULT_JWT_SECRET)
    upsert_setting("default_threshold", "5")
    upsert_setting("alert_refresh_seconds", "5")
    ensure_default_admin()


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_default_admin():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (DEFAULT_ADMIN_EMAIL,))
    existing_user = cursor.fetchone()
    if not existing_user:
        now = utc_now_iso()
        cursor.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "System Administrator",
                DEFAULT_ADMIN_EMAIL,
                hash_password(DEFAULT_ADMIN_PASSWORD),
                "admin",
                1,
                now,
                now,
            ),
        )
        connection.commit()
    connection.close()


def log_activity(action, entity_type, entity_id="", details="", user_id=None):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, action, entity_type, str(entity_id), details, utc_now_iso()),
    )
    connection.commit()
    connection.close()


def get_setting(key, default_value=None):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    connection.close()
    return row["value"] if row else default_value


def upsert_setting(key, value):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, str(value), utc_now_iso()),
    )
    connection.commit()
    connection.close()


def load_zone_config(path=ZONE_FILE):
    if not os.path.exists(path):
        return {"camera_source": 0, "zones": []}

    with open(path, "r", encoding="utf-8") as file:
        raw_data = json.load(file)

    if isinstance(raw_data, list):
        zones = []
        for index, zone in enumerate(raw_data, start=1):
            (x1, y1), (x2, y2) = zone
            zones.append(
                {
                    "id": f"zone_{index}",
                    "name": f"Zone {index}",
                    "x1": min(x1, x2),
                    "y1": min(y1, y2),
                    "x2": max(x1, x2),
                    "y2": max(y1, y2),
                    "threshold": 5,
                }
            )
        return {"camera_source": 0, "zones": zones}

    zones = []
    for index, zone in enumerate(raw_data.get("zones", []), start=1):
        zones.append(
            {
                "id": zone.get("id", f"zone_{index}"),
                "name": zone.get("name", f"Zone {index}"),
                "x1": min(zone["x1"], zone["x2"]),
                "y1": min(zone["y1"], zone["y2"]),
                "x2": max(zone["x1"], zone["x2"]),
                "y2": max(zone["y1"], zone["y2"]),
                "threshold": int(zone.get("threshold", 5)),
            }
        )

    return {"camera_source": raw_data.get("camera_source", 0), "zones": zones}


def save_zone_config(camera_source, zones, path=ZONE_FILE):
    payload = {"camera_source": camera_source, "zones": zones}
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def sync_config_to_database(path=ZONE_FILE):
    initialize_database()
    config = load_zone_config(path)
    source_url = str(config.get("camera_source", 0))
    now = utc_now_iso()

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM cameras WHERE name = ?", ("Default Camera",))
    camera = cursor.fetchone()

    if camera:
        camera_id = camera["id"]
        cursor.execute(
            """
            UPDATE cameras
            SET source_url = ?, stream_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (source_url, "webcam" if source_url == "0" else "ip", now, camera_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO cameras (name, source_url, stream_type, location, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Default Camera", source_url, "webcam" if source_url == "0" else "ip", "Primary feed", 1, now, now),
        )
        camera_id = cursor.lastrowid

    existing_codes = set()
    for zone in config.get("zones", []):
        existing_codes.add(zone["id"])
        cursor.execute("SELECT id FROM zones WHERE zone_code = ?", (zone["id"],))
        stored_zone = cursor.fetchone()
        if stored_zone:
            cursor.execute(
                """
                UPDATE zones
                SET camera_id = ?, zone_name = ?, x1 = ?, y1 = ?, x2 = ?, y2 = ?, threshold_limit = ?, updated_at = ?
                WHERE zone_code = ?
                """,
                (
                    camera_id,
                    zone["name"],
                    int(zone["x1"]),
                    int(zone["y1"]),
                    int(zone["x2"]),
                    int(zone["y2"]),
                    int(zone["threshold"]),
                    now,
                    zone["id"],
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO zones (
                    camera_id, zone_code, zone_name, x1, y1, x2, y2, threshold_limit, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    camera_id,
                    zone["id"],
                    zone["name"],
                    int(zone["x1"]),
                    int(zone["y1"]),
                    int(zone["x2"]),
                    int(zone["y2"]),
                    int(zone["threshold"]),
                    now,
                    now,
                ),
            )

    if existing_codes:
        placeholders = ",".join("?" for _ in existing_codes)
        cursor.execute(
            f"DELETE FROM zones WHERE camera_id = ? AND zone_code NOT IN ({placeholders})",
            (camera_id, *existing_codes),
        )
    else:
        cursor.execute("DELETE FROM zones WHERE camera_id = ?", (camera_id,))

    connection.commit()
    connection.close()
    return camera_id


def record_count_snapshot(zone_counts, zones, captured_at=None):
    initialize_database()
    camera_id = sync_config_to_database(ZONE_FILE)
    captured_time = captured_at or utc_now_iso()
    connection = get_connection()
    cursor = connection.cursor()

    for zone in zones:
        count = int(zone_counts.get(zone["id"], 0))
        width = max(1, zone["x2"] - zone["x1"])
        height = max(1, zone["y2"] - zone["y1"])
        density = round(count / float(width * height), 6)
        status = "ALERT" if count >= int(zone["threshold"]) else "NORMAL"

        cursor.execute(
            """
            INSERT INTO count_events (
                camera_id, zone_code, zone_name, people_count, density_score,
                threshold_value, status, captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                zone["id"],
                zone["name"],
                count,
                density,
                int(zone["threshold"]),
                status,
                captured_time,
            ),
        )

        cursor.execute(
            """
            SELECT id FROM alerts
            WHERE camera_id = ? AND zone_code = ? AND resolved_at IS NULL
            ORDER BY triggered_at DESC
            LIMIT 1
            """,
            (camera_id, zone["id"]),
        )
        active_alert = cursor.fetchone()

        if status == "ALERT" and not active_alert:
            cursor.execute(
                """
                INSERT INTO alerts (
                    camera_id, zone_code, zone_name, threshold_value, observed_value,
                    status, triggered_at, resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    camera_id,
                    zone["id"],
                    zone["name"],
                    int(zone["threshold"]),
                    count,
                    "ACTIVE",
                    captured_time,
                ),
            )
        elif status == "ALERT" and active_alert:
            cursor.execute(
                "UPDATE alerts SET observed_value = ?, status = ? WHERE id = ?",
                (count, "ACTIVE", active_alert["id"]),
            )
        elif status == "NORMAL" and active_alert:
            cursor.execute(
                "UPDATE alerts SET status = ?, resolved_at = ? WHERE id = ?",
                ("RESOLVED", captured_time, active_alert["id"]),
            )

    connection.commit()
    connection.close()


def import_csv_history(csv_path=LOG_FILE):
    initialize_database()
    if not os.path.exists(csv_path):
        return

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM count_events")
    if cursor.fetchone()["total"] > 0:
        connection.close()
        return
    connection.close()

    config = load_zone_config(ZONE_FILE)
    zones_by_id = {zone["id"]: zone for zone in config.get("zones", [])}
    if not zones_by_id:
        return

    with open(csv_path, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        snapshots = {}
        for row in reader:
            snapshots.setdefault(row["timestamp"], {})
            snapshots[row["timestamp"]][row["zone_id"]] = int(row["current_count"])

    for timestamp, zone_counts in snapshots.items():
        record_count_snapshot(zone_counts, list(zones_by_id.values()), timestamp)


def get_latest_zone_snapshot():
    initialize_database()
    import_csv_history(LOG_FILE)
    connection = get_connection()
    dataframe = pd.read_sql_query(
        """
        SELECT ce.zone_code, ce.zone_name, ce.people_count, ce.threshold_value,
               ce.status, ce.captured_at, z.x1, z.y1, z.x2, z.y2
        FROM count_events ce
        JOIN (
            SELECT zone_code, MAX(captured_at) AS latest_time
            FROM count_events
            GROUP BY zone_code
        ) latest
        ON ce.zone_code = latest.zone_code AND ce.captured_at = latest.latest_time
        LEFT JOIN zones z ON z.zone_code = ce.zone_code
        ORDER BY ce.zone_name
        """,
        connection,
    )
    connection.close()
    return dataframe


def get_count_history(hours=24):
    initialize_database()
    import_csv_history(LOG_FILE)
    since_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat(timespec="seconds")
    connection = get_connection()
    dataframe = pd.read_sql_query(
        """
        SELECT captured_at, zone_code, zone_name, people_count, threshold_value, status
        FROM count_events
        WHERE captured_at >= ?
        ORDER BY captured_at
        """,
        connection,
        params=(since_time,),
    )
    connection.close()
    if not dataframe.empty:
        dataframe["captured_at"] = pd.to_datetime(dataframe["captured_at"])
    return dataframe


def get_alert_history(limit=50):
    initialize_database()
    connection = get_connection()
    dataframe = pd.read_sql_query(
        """
        SELECT zone_name, threshold_value, observed_value, status, triggered_at, resolved_at
        FROM alerts
        ORDER BY triggered_at DESC
        LIMIT ?
        """,
        connection,
        params=(limit,),
    )
    connection.close()
    return dataframe


def get_activity_logs(limit=100):
    initialize_database()
    connection = get_connection()
    dataframe = pd.read_sql_query(
        """
        SELECT created_at, action, entity_type, entity_id, details
        FROM activity_logs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        connection,
        params=(limit,),
    )
    connection.close()
    return dataframe


def get_cameras():
    initialize_database()
    connection = get_connection()
    dataframe = pd.read_sql_query(
        "SELECT id, name, source_url, stream_type, location, is_active, updated_at FROM cameras ORDER BY id",
        connection,
    )
    connection.close()
    return dataframe


def get_zones():
    initialize_database()
    connection = get_connection()
    dataframe = pd.read_sql_query(
        """
        SELECT z.id, z.zone_code, z.zone_name, z.x1, z.y1, z.x2, z.y2,
               z.threshold_limit, c.name AS camera_name
        FROM zones z
        JOIN cameras c ON c.id = z.camera_id
        ORDER BY z.id
        """,
        connection,
    )
    connection.close()
    return dataframe


def get_users():
    initialize_database()
    connection = get_connection()
    dataframe = pd.read_sql_query(
        "SELECT id, full_name, email, role, is_active, created_at FROM users ORDER BY id",
        connection,
    )
    connection.close()
    return dataframe


def upsert_camera(name, source_url, stream_type, location, is_active=True):
    initialize_database()
    now = utc_now_iso()
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM cameras WHERE name = ?", (name,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            """
            UPDATE cameras
            SET source_url = ?, stream_type = ?, location = ?, is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (source_url, stream_type, location, int(bool(is_active)), now, existing["id"]),
        )
        camera_id = existing["id"]
    else:
        cursor.execute(
            """
            INSERT INTO cameras (name, source_url, stream_type, location, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, source_url, stream_type, location, int(bool(is_active)), now, now),
        )
        camera_id = cursor.lastrowid

    connection.commit()
    connection.close()
    log_activity("UPSERT", "camera", camera_id, f"{name} -> {source_url}")
    return camera_id


def update_zone_file_from_rows(rows, camera_source=0):
    zones = []
    for index, row in enumerate(rows, start=1):
        zone_code = str(row.get("zone_code") or f"zone_{index}").strip()
        zones.append(
            {
                "id": zone_code,
                "name": str(row.get("zone_name") or f"Zone {index}").strip(),
                "x1": int(row.get("x1", 0)),
                "y1": int(row.get("y1", 0)),
                "x2": int(row.get("x2", 100)),
                "y2": int(row.get("y2", 100)),
                "threshold": int(row.get("threshold_limit", 5)),
            }
        )

    save_zone_config(camera_source, zones, ZONE_FILE)
    sync_config_to_database(ZONE_FILE)
    log_activity("UPSERT", "zones", "", f"Saved {len(zones)} zones")


def create_user(full_name, email, password, role="viewer", is_active=True):
    initialize_database()
    now = utc_now_iso()
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO users (full_name, email, password_hash, role, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (full_name, email, hash_password(password), role, int(bool(is_active)), now, now),
    )
    user_id = cursor.lastrowid
    connection.commit()
    connection.close()
    log_activity("CREATE", "user", user_id, email, user_id)
    return user_id


def update_user_status(user_id, is_active):
    initialize_database()
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
        (int(bool(is_active)), utc_now_iso(), user_id),
    )
    connection.commit()
    connection.close()
    log_activity("UPDATE", "user", user_id, f"is_active={is_active}")


def get_jwt_secret():
    return get_setting("jwt_secret", DEFAULT_JWT_SECRET)


def _base64url_encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("utf-8")


def _base64url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_token(payload, expires_minutes=120):
    header = {"alg": "HS256", "typ": "JWT"}
    body = payload.copy()
    body["exp"] = int((datetime.utcnow() + timedelta(minutes=expires_minutes)).timestamp())
    body["jti"] = secrets.token_hex(8)
    header_segment = _base64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_segment = _base64url_encode(
        json.dumps(body, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
    signature = hmac.new(get_jwt_secret().encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_base64url_encode(signature)}"


def verify_token(token):
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
        signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
        expected_signature = hmac.new(
            get_jwt_secret().encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_base64url_encode(expected_signature), signature_segment):
            return None

        payload = json.loads(_base64url_decode(payload_segment))
        if int(payload["exp"]) < int(datetime.utcnow().timestamp()):
            return None
        return payload
    except Exception:
        return None


def authenticate_user(email, password):
    initialize_database()
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, full_name, email, role, is_active, password_hash
        FROM users
        WHERE email = ?
        """,
        (email,),
    )
    user = cursor.fetchone()
    connection.close()
    if not user or not user["is_active"]:
        return None
    if user["password_hash"] != hash_password(password):
        return None

    token = create_token(
        {
            "sub": str(user["id"]),
            "email": user["email"],
            "role": user["role"],
            "name": user["full_name"],
        }
    )
    session_payload = verify_token(token)

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO user_sessions (user_id, jwt_token_id, token, ip_address, login_at, logout_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (user["id"], session_payload["jti"], token, "local", utc_now_iso()),
    )
    connection.commit()
    connection.close()
    log_activity("LOGIN", "user_session", user["id"], user["email"], user["id"])
    return token


def get_current_user(token):
    payload = verify_token(token)
    if not payload:
        return None
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, full_name, email, role, is_active FROM users WHERE id = ?",
        (int(payload["sub"]),),
    )
    user = cursor.fetchone()
    connection.close()
    if not user or not user["is_active"]:
        return None
    return dict(user)


def logout_user(token):
    payload = verify_token(token)
    if not payload:
        return
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE user_sessions
        SET logout_at = ?
        WHERE jwt_token_id = ? AND logout_at IS NULL
        """,
        (utc_now_iso(), payload["jti"]),
    )
    connection.commit()
    connection.close()
    log_activity("LOGOUT", "user_session", payload["sub"], payload["email"], payload["sub"])


def export_history_to_csv(dataframe, export_type, user_id=None):
    initialize_database()
    os.makedirs("exports", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join("exports", f"{export_type}_{timestamp}.csv")
    dataframe.to_csv(file_path, index=False)

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO report_exports (user_id, report_type, file_path, from_time, to_time, exported_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            export_type,
            file_path,
            str(dataframe["captured_at"].min()) if "captured_at" in dataframe.columns and not dataframe.empty else None,
            str(dataframe["captured_at"].max()) if "captured_at" in dataframe.columns and not dataframe.empty else None,
            utc_now_iso(),
        ),
    )
    connection.commit()
    connection.close()
    log_activity("EXPORT", "report", "", file_path, user_id)
    return file_path


def get_report_exports():
    initialize_database()
    connection = get_connection()
    dataframe = pd.read_sql_query(
        """
        SELECT exported_at, report_type, file_path, from_time, to_time, user_id
        FROM report_exports
        ORDER BY exported_at DESC
        """,
        connection,
    )
    connection.close()
    return dataframe


def build_heatmap_figure(snapshot_df):
    figure, axis = plt.subplots(figsize=(8, 4.5))
    axis.set_facecolor("#081a24")

    if snapshot_df.empty:
        axis.text(0.5, 0.5, "No zone data available", color="white", ha="center", va="center")
        axis.set_xticks([])
        axis.set_yticks([])
        return figure

    max_x = int(snapshot_df["x2"].max()) + 40
    max_y = int(snapshot_df["y2"].max()) + 40

    for _, row in snapshot_df.iterrows():
        threshold = max(1, int(row["threshold_value"]))
        intensity = min(1.0, float(row["people_count"]) / threshold)
        color = (1.0, 0.2, 0.2, 0.25 + (0.55 * intensity))
        width = int(row["x2"]) - int(row["x1"])
        height = int(row["y2"]) - int(row["y1"])
        axis.add_patch(plt.Rectangle((row["x1"], row["y1"]), width, height, color=color))
        axis.add_patch(
            plt.Rectangle(
                (row["x1"], row["y1"]),
                width,
                height,
                fill=False,
                edgecolor="#f8fafc",
                linewidth=2,
            )
        )
        axis.text(
            row["x1"] + 8,
            row["y1"] + 22,
            f"{row['zone_name']} ({row['people_count']})",
            color="white",
            fontsize=10,
        )

    axis.set_xlim(0, max_x)
    axis.set_ylim(max_y, 0)
    axis.set_title("Zone Density Heatmap", color="white", fontsize=14)
    axis.tick_params(colors="white")
    for spine in axis.spines.values():
        spine.set_color("#94a3b8")
    figure.patch.set_facecolor("#081a24")
    figure.tight_layout()
    return figure
