import csv
import json
import os
import time
from datetime import datetime

import cv2
import supervision as sv
from ultralytics import YOLO

from platform_services import initialize_database, record_count_snapshot, sync_config_to_database

MODEL_PATH = "yolov8n.pt"
ZONE_FILE = "zones.json"
CAMERA_SOURCE = 0
LOG_FILE = "people_counts.csv"
WINDOW_NAME = "People Counting System"


def load_zone_config(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Zone file not found: {path}")

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
        return {"camera_source": CAMERA_SOURCE, "zones": zones}

    raw_zones = raw_data.get("zones", [])
    zones = []
    for index, zone in enumerate(raw_zones, start=1):
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

    return {
        "camera_source": raw_data.get("camera_source", CAMERA_SOURCE),
        "zones": zones,
    }


def centroid_from_box(box):
    x1, y1, x2, y2 = box
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def point_inside_zone(point, zone):
    x, y = point
    return zone["x1"] <= x <= zone["x2"] and zone["y1"] <= y <= zone["y2"]


def ensure_log_file(path):
    if os.path.exists(path):
        return

    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["timestamp", "zone_id", "zone_name", "current_count", "threshold", "status"]
        )


def append_zone_metrics(path, zones, zone_counts):
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for zone in zones:
            current_count = zone_counts[zone["id"]]
            status = "ALERT" if current_count >= zone["threshold"] else "NORMAL"
            writer.writerow(
                [
                    timestamp,
                    zone["id"],
                    zone["name"],
                    current_count,
                    zone["threshold"],
                    status,
                ]
            )


def main():
    initialize_database()
    sync_config_to_database(ZONE_FILE)
    zone_config = load_zone_config(ZONE_FILE)
    zones = zone_config["zones"]
    camera_source = zone_config["camera_source"]

    if not zones:
        raise ValueError(
            "No zones configured. Run module1_video_input_zone_management.py first."
        )

    model = YOLO(MODEL_PATH)
    tracker = sv.ByteTrack()
    ensure_log_file(LOG_FILE)

    cap = cv2.VideoCapture(camera_source)
    if not cap.isOpened():
        raise RuntimeError(f"Camera source not accessible: {camera_source}")

    last_log_time = 0.0

    while True:
        success, frame = cap.read()
        if not success:
            break

        result = model(frame, verbose=False)[0]
        detections = sv.Detections.from_ultralytics(result)
        detections = detections[detections.class_id == 0]
        detections = tracker.update_with_detections(detections)

        zone_counts = {zone["id"]: 0 for zone in zones}
        active_ids = {zone["id"]: set() for zone in zones}
        total_people = 0

        for xyxy, track_id in zip(detections.xyxy, detections.tracker_id):
            if track_id is None:
                continue

            total_people += 1
            x1, y1, x2, y2 = map(int, xyxy)
            center = centroid_from_box((x1, y1, x2, y2))

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            cv2.circle(frame, center, 4, (0, 255, 255), -1)
            cv2.putText(
                frame,
                f"ID {track_id}",
                (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 200, 0),
                2,
            )

            for zone in zones:
                if point_inside_zone(center, zone):
                    active_ids[zone["id"]].add(int(track_id))

        for zone in zones:
            zone_counts[zone["id"]] = len(active_ids[zone["id"]])
            color = (0, 0, 255) if zone_counts[zone["id"]] >= zone["threshold"] else (255, 0, 0)

            cv2.rectangle(frame, (zone["x1"], zone["y1"]), (zone["x2"], zone["y2"]), color, 2)
            cv2.putText(
                frame,
                f"{zone['name']}: {zone_counts[zone['id']]} / {zone['threshold']}",
                (zone["x1"], max(25, zone["y1"] - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

        alert_zones = [
            zone["name"] for zone in zones if zone_counts[zone["id"]] >= zone["threshold"]
        ]

        cv2.putText(
            frame,
            f"Total People: {total_people}",
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        status_text = "Status: Normal"
        status_color = (0, 255, 0)
        if alert_zones:
            status_text = "Alert: " + ", ".join(alert_zones)
            status_color = (0, 0, 255)

        cv2.putText(
            frame,
            status_text,
            (20, 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            status_color,
            2,
        )

        current_time = time.time()
        if current_time - last_log_time >= 5:
            append_zone_metrics(LOG_FILE, zones, zone_counts)
            record_count_snapshot(
                zone_counts,
                zones,
                datetime.utcnow().isoformat(timespec="seconds"),
            )
            last_log_time = current_time

        cv2.imshow(WINDOW_NAME, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
