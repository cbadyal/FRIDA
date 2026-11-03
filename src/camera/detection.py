"""Reusable Picamera2 capture and OpenCV face detection; no servo control."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Face:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self):
        return (self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self):
        return self.width * self.height


def load_face_cascade(cv2=None):
    if cv2 is None:
        import cv2

    filename = "haarcascade_frontalface_default.xml"
    directories = [
        Path("/usr/share/opencv4/haarcascades"),
        Path("/usr/share/opencv/haarcascades"),
    ]
    opencv_data = getattr(cv2, "data", None)
    if opencv_data is not None:
        directories.insert(0, Path(opencv_data.haarcascades))
    for directory in directories:
        path = directory / filename
        if path.is_file():
            cascade = cv2.CascadeClassifier(str(path))
            if not cascade.empty():
                return cascade
    raise RuntimeError(
        "Could not load the face detection model. "
        "On Raspberry Pi OS, install it with: sudo apt install opencv-data"
    )


class CameraDetector:
    def __init__(self, size=(320, 240)):
        self.size = size
        self.camera = None
        self.cv2 = None
        self.cascade = None
        self._preview_open = False

    def start(self):
        # Lazy imports allow the demo's logic and --help to run without Pi packages.
        import cv2
        from libcamera import controls
        from picamera2 import Picamera2

        self.cv2 = cv2
        self.cascade = load_face_cascade(cv2)
        self.camera = Picamera2()
        try:
            # Preserve the newer camera script's OpenCV-compatible configuration.
            config = self.camera.create_preview_configuration(
                main={"format": "RGB888", "size": self.size},
                controls={"FrameRate": 30},
            )
            self.camera.configure(config)
            if "AfMode" in self.camera.camera_controls:
                self.camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
            self.camera.start()
        except BaseException:
            self.close()
            raise

    def read(self):
        frame = self.camera.capture_array("main")
        if frame is None or frame.size == 0:
            raise RuntimeError("Camera returned an empty frame")
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        boxes = self.cascade.detectMultiScale(
            gray, scaleFactor=1.3, minNeighbors=5, minSize=(30, 30)
        )
        faces = [Face(*(int(value) for value in box)) for box in boxes]
        return frame, faces

    def preview(self, frame, faces, primary=None, status="", debug=True):
        cv2 = self.cv2
        self._preview_open = True
        for face in faces:
            color = (0, 255, 0) if primary is None or face == primary else (120, 120, 120)
            cv2.rectangle(
                frame, (face.x, face.y),
                (face.x + face.width, face.y + face.height), color, 2,
            )
            cx, cy = (int(value) for value in face.center)
            cv2.circle(frame, (cx, cy), 4, (255, 0, 0), -1)
            if debug:
                cv2.putText(
                    frame, f"({cx},{cy})", (cx + 10, cy - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1,
                )
        if debug:
            cv2.putText(
                frame, status, (8, 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 1,
            )
        cv2.imshow("FRIDA camera | Q=quit D=debug", frame)
        return cv2.waitKey(1) & 0xFF

    def close(self):
        try:
            if self.camera is not None:
                camera, self.camera = self.camera, None
                camera.close()
        finally:
            if self._preview_open:
                self._preview_open = False
                self.cv2.destroyAllWindows()
