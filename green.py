from ultralytics import YOLO
import cv2

# Load YOLOv8 model
model = YOLO("yolov8n.pt")

# Open webcam
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Cannot access webcam")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Run YOLO detection
    results = model(frame)

    # Draw green boxes + labels
    annotated_frame = results[0].plot()

    cv2.imshow("YOLO Webcam Detection", annotated_frame)

    # ESC to exit
    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()