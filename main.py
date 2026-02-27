import cv2

def start_webcam():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Cannot access webcam")
        return

    print("Webcam started. Press ESC to exit.")

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Error: Failed to grab frame")
            break

        cv2.imshow("Webcam Feed", frame)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    start_webcam()