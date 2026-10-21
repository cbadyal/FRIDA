"""Camera-only face detection for FRIDA's Raspberry Pi Camera Module."""

from pathlib import Path

import cv2
from libcamera import controls
from picamera2 import Picamera2


def load_face_cascade():
    filename = 'haarcascade_frontalface_default.xml'
    directories = [
        Path('/usr/share/opencv4/haarcascades'),
        Path('/usr/share/opencv/haarcascades'),
    ]
    opencv_data = getattr(cv2, 'data', None)
    if opencv_data is not None:
        directories.insert(0, Path(opencv_data.haarcascades))

    for directory in directories:
        path = directory / filename
        if path.is_file():
            cascade = cv2.CascadeClassifier(str(path))
            if not cascade.empty():
                return cascade

    raise RuntimeError(
        'Could not load the face detection model. '
        'On Raspberry Pi OS, install it with: sudo apt install opencv-data'
    )


def main():
    face_cascade = load_face_cascade()
    camera = Picamera2()
    try:
        # Picamera2's RGB888 format supplies the BGR ordering OpenCV expects.
        config = camera.create_preview_configuration(
            main={'format': 'RGB888', 'size': (320, 240)},
            controls={'FrameRate': 30},
        )
        camera.configure(config)
        if 'AfMode' in camera.camera_controls:
            camera.set_controls({'AfMode': controls.AfModeEnum.Continuous})
        camera.start()

        print("Press 'q' in the camera window or Ctrl+C in the terminal to quit.")
        while True:
            frame = camera.capture_array('main')

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.3, minNeighbors=5, minSize=(30, 30)
            )

            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                cx = x + w // 2
                cy = y + h // 2

                cv2.circle(frame, (cx, cy), 4, (255, 0, 0), -1)

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

                print(f"Face center at x={cx}, y={cy}")

            cv2.imshow('Face Centers - 320x240', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
