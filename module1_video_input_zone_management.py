import json
import os

import cv2

CAMERA_SOURCE = 0
ZONE_FILE = "zones.json"
WINDOW_NAME = "Zone Manager"

zones = []
drawing = False
start_point = None
current_rect = None
zone_counter = 1


def normalize_rect(start, end):
    return min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1])


def load_config():
    global zones, zone_counter

    if not os.path.exists(ZONE_FILE):
        zones = []
        zone_counter = 1
        return

    with open(ZONE_FILE, "r", encoding="utf-8") as file:
        raw_data = json.load(file)

    if isinstance(raw_data, list):
        zones = []
        for index, rect in enumerate(raw_data, start=1):
            (x1, y1), (x2, y2) = rect
            nx1, ny1, nx2, ny2 = normalize_rect((x1, y1), (x2, y2))
            zones.append(
                {
                    "id": f"zone_{index}",
                    "name": f"Zone {index}",
                    "x1": nx1,
                    "y1": ny1,
                    "x2": nx2,
                    "y2": ny2,
                    "threshold": 5,
                }
            )
    else:
        zones = []
        for index, zone in enumerate(raw_data.get("zones", []), start=1):
            nx1, ny1, nx2, ny2 = normalize_rect(
                (zone["x1"], zone["y1"]), (zone["x2"], zone["y2"])
            )
            zones.append(
                {
                    "id": zone.get("id", f"zone_{index}"),
                    "name": zone.get("name", f"Zone {index}"),
                    "x1": nx1,
                    "y1": ny1,
                    "x2": nx2,
                    "y2": ny2,
                    "threshold": int(zone.get("threshold", 5)),
                }
            )

    zone_counter = len(zones) + 1
    print(f"Loaded {len(zones)} zones")


def save_config():
    payload = {"camera_source": CAMERA_SOURCE, "zones": zones}
    with open(ZONE_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
    print("Zones saved")


def remove_last_zone():
    global zone_counter
    if not zones:
        print("No zones to remove")
        return

    removed_zone = zones.pop()
    zone_counter = len(zones) + 1
    print(f"Removed {removed_zone['name']}")


def mouse_draw(event, x, y, flags, param):
    global drawing, start_point, current_rect, zone_counter

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        start_point = (x, y)

    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        current_rect = (start_point, (x, y))

    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        end_point = (x, y)
        x1, y1, x2, y2 = normalize_rect(start_point, end_point)

        if x2 - x1 < 10 or y2 - y1 < 10:
            current_rect = None
            print("Ignored very small zone")
            return

        new_zone = {
            "id": f"zone_{zone_counter}",
            "name": f"Zone {zone_counter}",
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "threshold": 5,
        }
        zones.append(new_zone)
        zone_counter += 1
        current_rect = None
        print(f"Zone added: {new_zone['name']} ({x1}, {y1}) -> ({x2}, {y2})")


def draw_zone(frame, zone, color):
    cv2.rectangle(frame, (zone["x1"], zone["y1"]), (zone["x2"], zone["y2"]), color, 2)
    cv2.putText(
        frame,
        f"{zone['name']} | limit {zone['threshold']}",
        (zone["x1"], max(25, zone["y1"] - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def main():
    global zone_counter
    cap = cv2.VideoCapture(CAMERA_SOURCE)
    if not cap.isOpened():
        raise RuntimeError("Camera not accessible")

    load_config()

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, mouse_draw)

    print("\nControls:")
    print("Draw zone: drag mouse")
    print("S: save zones")
    print("C: clear zones")
    print("U: undo last zone")
    print("Esc: quit\n")

    while True:
        success, frame = cap.read()
        if not success:
            break

        for zone in zones:
            draw_zone(frame, zone, (0, 255, 0))

        if current_rect:
            preview_zone = {
                "name": "New Zone",
                "x1": min(current_rect[0][0], current_rect[1][0]),
                "y1": min(current_rect[0][1], current_rect[1][1]),
                "x2": max(current_rect[0][0], current_rect[1][0]),
                "y2": max(current_rect[0][1], current_rect[1][1]),
                "threshold": 5,
            }
            draw_zone(frame, preview_zone, (0, 0, 255))

        cv2.imshow(WINDOW_NAME, frame)
        key = cv2.waitKey(1) & 0xFF

        if key == 27:
            break
        if key == ord("s"):
            save_config()
        if key == ord("c"):
            zones.clear()
            zone_counter = 1
            print("Zones cleared")
        if key == ord("u"):
            remove_last_zone()

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
