import pandas as pd
import streamlit as st

from platform_services import (
    authenticate_user,
    create_user,
    get_activity_logs,
    get_cameras,
    get_current_user,
    get_report_exports,
    get_setting,
    get_users,
    get_zones,
    import_csv_history,
    initialize_database,
    logout_user,
    sync_config_to_database,
    update_user_status,
    update_zone_file_from_rows,
    upsert_camera,
    upsert_setting,
)

st.set_page_config(page_title="People Counter Admin", layout="wide")

initialize_database()
sync_config_to_database()
import_csv_history()

if "auth_token" not in st.session_state:
    st.session_state.auth_token = None


def render_login():
    st.title("Module 4: Admin Panel and Settings")
    st.caption("JWT-style secured access for cameras, zones, users, logs, and reporting history.")
    with st.form("login_form"):
        email = st.text_input("Email", value="admin@peoplecounter.local")
        password = st.text_input("Password", type="password", value="admin123")
        submitted = st.form_submit_button("Sign in", use_container_width=True)

    if submitted:
        token = authenticate_user(email, password)
        if token:
            st.session_state.auth_token = token
            st.rerun()
        st.error("Invalid credentials or inactive user.")

    st.info("Default admin credentials: admin@peoplecounter.local / admin123")


current_user = None
if st.session_state.auth_token:
    current_user = get_current_user(st.session_state.auth_token)

if not current_user:
    render_login()
    raise SystemExit

header_columns = st.columns([4, 1])
header_columns[0].title("Module 4: Admin Panel and Settings")
header_columns[0].caption(f"Logged in as {current_user['full_name']} ({current_user['role']})")
if header_columns[1].button("Logout", use_container_width=True):
    logout_user(st.session_state.auth_token)
    st.session_state.auth_token = None
    st.rerun()

camera_tab, zone_tab, user_tab, log_tab, report_tab, settings_tab = st.tabs(
    ["Cameras", "Zones", "Users", "Logs", "Reports", "Settings"]
)

with camera_tab:
    st.subheader("Camera Registration")
    st.dataframe(get_cameras(), use_container_width=True, hide_index=True)

    with st.form("camera_form"):
        name = st.text_input("Camera name", value="Default Camera")
        source_url = st.text_input("Camera source", value="0")
        stream_type = st.selectbox("Stream type", options=["webcam", "ip", "rtsp"])
        location = st.text_input("Location", value="Primary feed")
        is_active = st.checkbox("Camera active", value=True)
        save_camera = st.form_submit_button("Save camera", use_container_width=True)

    if save_camera:
        upsert_camera(name, source_url, stream_type, location, is_active)
        st.success("Camera saved.")
        st.rerun()

with zone_tab:
    st.subheader("Zone Editor")
    zone_df = get_zones()
    if zone_df.empty:
        zone_df = pd.DataFrame(
            [
                {
                    "zone_code": "zone_1",
                    "zone_name": "Zone 1",
                    "x1": 50,
                    "y1": 50,
                    "x2": 300,
                    "y2": 250,
                    "threshold_limit": int(get_setting("default_threshold", "5")),
                }
            ]
        )
    else:
        zone_df = zone_df[
            ["zone_code", "zone_name", "x1", "y1", "x2", "y2", "threshold_limit"]
        ]

    edited_zones = st.data_editor(
        zone_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
    )
    if st.button("Save zones to config", use_container_width=True):
        update_zone_file_from_rows(edited_zones.to_dict("records"), camera_source=0)
        st.success("Zones saved to zones.json and synced to the database.")
        st.rerun()

with user_tab:
    st.subheader("User Management")
    st.dataframe(get_users(), use_container_width=True, hide_index=True)

    with st.form("user_form"):
        full_name = st.text_input("Full name")
        email = st.text_input("User email")
        password = st.text_input("Temporary password", type="password")
        role = st.selectbox("Role", options=["viewer", "admin"])
        active = st.checkbox("Active", value=True)
        create_user_action = st.form_submit_button("Create user", use_container_width=True)

    if create_user_action:
        if full_name and email and password:
            create_user(full_name, email, password, role, active)
            st.success("User created.")
            st.rerun()
        else:
            st.error("Name, email, and password are required.")

    existing_users = get_users()
    non_admin_users = existing_users[existing_users["email"] != "admin@peoplecounter.local"]
    if not non_admin_users.empty:
        selected_email = st.selectbox("Toggle user status", non_admin_users["email"].tolist())
        selected_row = non_admin_users[non_admin_users["email"] == selected_email].iloc[0]
        button_label = "Deactivate user" if int(selected_row["is_active"]) == 1 else "Activate user"
        if st.button(button_label, use_container_width=True):
            update_user_status(int(selected_row["id"]), int(selected_row["is_active"]) == 0)
            st.success("User status updated.")
            st.rerun()

with log_tab:
    st.subheader("Activity Logs")
    st.dataframe(get_activity_logs(), use_container_width=True, hide_index=True)

with report_tab:
    st.subheader("Report Export History")
    report_df = get_report_exports()
    if report_df.empty:
        st.info("No exports yet. Use the dashboard to create a CSV report.")
    else:
        st.dataframe(report_df, use_container_width=True, hide_index=True)

with settings_tab:
    st.subheader("System Settings")
    default_threshold = st.number_input(
        "Default zone threshold",
        min_value=1,
        max_value=500,
        value=int(get_setting("default_threshold", "5")),
    )
    alert_refresh = st.number_input(
        "Alert refresh interval (seconds)",
        min_value=1,
        max_value=60,
        value=int(get_setting("alert_refresh_seconds", "5")),
    )
    jwt_secret = st.text_input("JWT secret", value=get_setting("jwt_secret"))

    if st.button("Save settings", use_container_width=True):
        upsert_setting("default_threshold", str(default_threshold))
        upsert_setting("alert_refresh_seconds", str(alert_refresh))
        upsert_setting("jwt_secret", jwt_secret)
        st.success("Settings updated.")
