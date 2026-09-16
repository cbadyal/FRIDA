import cv2

# ========================
# Face Center Detection
# ========================
# (Sections marked with '# CHANGED' are new or modified)

def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)    # RESEARCH HOW TO KEEP SCALING ON WEBCAM BUT SMALLER PICTURE
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )

    print("Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.3, minNeighbors=5, minSize=(30, 30)
        )

        for (x, y, w, h) in faces:
            # draw the face rectangle
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # === CHANGED ===
            # compute the center point of the face
            cx = x + w // 2
            cy = y + h // 2

            # === CHANGED ===
            # draw a small circle at the center of the face
            cv2.circle(frame, (cx, cy), 4, (255, 0, 0), -1)

            # === CHANGED ===
            # overlay the center coordinates next to the face
            cv2.putText(
                frame,
                f"({cx},{cy})",
                (cx + 10, cy - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 0, 0),
                1,
                cv2.LINE_AA
            )

            # === CHANGED ===
            # also print to console
            print(f"Face center at x={cx}, y={cy}")

        cv2.imshow('Face Centers - 320x240', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
