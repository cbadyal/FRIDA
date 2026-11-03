"""Camera-only face detection for FRIDA's Raspberry Pi Camera Module."""

from src.camera.detection import CameraDetector, load_face_cascade


def main():
    camera = CameraDetector()
    try:
        camera.start()

        print("Press 'q' in the camera window or Ctrl+C in the terminal to quit.")
        while True:
            frame, faces = camera.read()
            for face in faces:
                cx, cy = (int(value) for value in face.center)
                print(f"Face center at x={cx}, y={cy}")
            if camera.preview(frame, faces, status="Camera-only detection") == ord('q'):
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()


if __name__ == '__main__':
    main()
