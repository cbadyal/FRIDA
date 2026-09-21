#!/usr/bin/env python3
"""
Face Tracker - Raspberry Pi 5 + Camera Module 3
Tracks faces and pans Servo 0 (head) to follow. Plays a sound on first detection.
Raises Servo 2 (arm) when a face is detected, lowers it when face is lost.

Usage:
  Terminal 1: rpicam-vid --codec mjpeg --width 640 --height 480 --framerate 30 --timeout 0 --nopreview -o udp://127.0.0.1:5000
  Terminal 2: python3 face_tracker.py

Controls:
  Q : quit
  D : toggle debug overlay
"""

import cv2
import numpy as np
import subprocess
import os
import sys
import time
import threading
import smbus2

sys.path.append("/home/fridapi/Desktop/Sound Scripts")
import soundTest

# ── Configuration ─────────────────────────────────────────────────────────────

FRAME_WIDTH  = 640
FRAME_HEIGHT = 480
CONFIDENCE_THRESHOLD = 0.6
PREVIEW_WINDOW = "Face Tracker"

CROSSHAIR_SIZE   = 20
CROSSHAIR_COLOR  = (0, 255, 255)
BOX_COLOR        = (0, 200, 0)
TEXT_COLOR       = (255, 255, 255)
CENTER_DOT_COLOR = (0, 0, 255)

# How many frames a face must be absent before we consider it "lost"
FACE_LOST_FRAMES = 20

# How often (in frames) to update the servo position while tracking
SERVO_UPDATE_EVERY = 5

# ── Model paths ───────────────────────────────────────────────────────────────

MODEL_DIR  = os.path.expanduser("~/face_tracker_models")
PROTOTXT   = os.path.join(MODEL_DIR, "deploy.prototxt")
CAFFEMODEL = os.path.join(MODEL_DIR, "res10_300x300_ssd_iter_140000.caffemodel")

PROTOTXT_URL   = "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
CAFFEMODEL_URL = "https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"

# ── PCA9685 Setup ─────────────────────────────────────────────────────────────

PCA9685_ADDR = 0x40
I2C_BUS      = 1
PWM_FREQ     = 50
OSC_CLOCK    = 25_000_000
PULSE_MIN_US = 500
PULSE_MAX_US = 2500

HEAD_CHANNEL = 0
HEAD_MIN_DEG = 120
HEAD_MAX_DEG = 180
HEAD_CENTER  = 120

ARM_CHANNEL  = 2
ARM_DOWN_DEG = 60    # Resting position
ARM_UP_DEG   = 120   # Raised position (face detected)

# Arm uses the same slow downswing speed as your existing servo script
# up_step/up_delay match Servo 2 in SERVOS config; down is slower
ARM_UP_STEP   = 2
ARM_UP_DELAY  = 0.015   # seconds between steps going up
ARM_DOWN_STEP = 1
ARM_DOWN_DELAY = 0.025  # seconds between steps going down (slower, less jerk)

# ── PCA9685 Driver ────────────────────────────────────────────────────────────

class PCA9685:
    def __init__(self):
        try:
            self.bus = smbus2.SMBus(I2C_BUS)
        except Exception as e:
            print(f"[ERROR] Cannot open I2C bus: {e}")
            sys.exit(1)
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0x00)
        time.sleep(0.005)
        prescale = round(OSC_CLOCK / (4096 * PWM_FREQ)) - 1
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0x10)
        self.bus.write_byte_data(PCA9685_ADDR, 0xFE, prescale)
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0x00)
        time.sleep(0.005)
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0xA0)

    def set_angle(self, channel, angle):
        pulse_us = PULSE_MIN_US + (PULSE_MAX_US - PULSE_MIN_US) * angle / 180
        off_tick = round(pulse_us / (1_000_000 / PWM_FREQ) * 4096)
        base = 0x06 + 4 * channel
        self.bus.write_i2c_block_data(PCA9685_ADDR, base,
            [0, 0, off_tick & 0xFF, off_tick >> 8])

    def close(self):
        self.bus.close()

# ── Head Tracking ─────────────────────────────────────────────────────────────

class HeadTracker:
    """
    Maps horizontal face position in the frame to a servo angle and moves
    the head to follow. Runs servo updates in a background thread so the
    camera loop never blocks waiting for a slow I2C write.
    """

    def __init__(self, pca):
        self.pca         = pca
        self.current_deg = float(HEAD_CENTER)
        self.target_deg  = float(HEAD_CENTER)
        self._lock       = threading.Lock()
        self._running    = True

        # Move to centre on startup
        self.pca.set_angle(HEAD_CHANNEL, HEAD_CENTER)

        self._thread = threading.Thread(target=self._servo_loop, daemon=True)
        self._thread.start()

    def update_target(self, face_cx):
        """
        Convert horizontal pixel position to a servo angle.
        face_cx=0 (left edge)  → HEAD_MAX_DEG
        face_cx=FRAME_WIDTH    → HEAD_MIN_DEG
        (inverted so the head turns toward the face)
        """
        ratio = face_cx / FRAME_WIDTH                          # 0.0 – 1.0
        angle = HEAD_MIN_DEG + ratio * (HEAD_MAX_DEG - HEAD_MIN_DEG)
        angle = max(HEAD_MIN_DEG, min(HEAD_MAX_DEG, angle))
        with self._lock:
            self.target_deg = angle

    def _servo_loop(self):
        """Smoothly nudge the servo toward the target at a fixed rate."""
        STEP      = 2.0   # max degrees per tick
        TICK_SEC  = 0.02  # 50 Hz update rate

        while self._running:
            with self._lock:
                diff = self.target_deg - self.current_deg

            if abs(diff) > 0.5:
                move = max(-STEP, min(STEP, diff))
                with self._lock:
                    self.current_deg += move
                    angle = self.current_deg
                self.pca.set_angle(HEAD_CHANNEL, round(angle))

            time.sleep(TICK_SEC)

    def stop(self):
        self._running = False
        self._thread.join()

# ── Arm Control ───────────────────────────────────────────────────────────────

def move_arm(pca, target_deg, current_deg):
    """
    Smoothly move Servo 2 (arm) to target_deg from current_deg.
    Uses slower downswing speed to reduce momentum jerk, matching
    the existing servo script's Servo 2 config.
    Returns the final angle reached.
    """
    going_up = target_deg > current_deg
    step      = ARM_UP_STEP   if going_up else ARM_DOWN_STEP
    delay     = ARM_UP_DELAY  if going_up else ARM_DOWN_DELAY
    direction = 1 if going_up else -1

    angle = int(current_deg)
    while (going_up and angle < target_deg) or (not going_up and angle > target_deg):
        angle += direction * step
        angle  = max(ARM_DOWN_DEG, min(ARM_UP_DEG, angle))
        pca.set_angle(ARM_CHANNEL, angle)
        time.sleep(delay)

    pca.set_angle(ARM_CHANNEL, target_deg)
    return target_deg

# ── Model setup ───────────────────────────────────────────────────────────────

def download_models():
    os.makedirs(MODEL_DIR, exist_ok=True)
    if not os.path.exists(PROTOTXT):
        print("Downloading prototxt...")
        subprocess.run(["wget", "-q", "-O", PROTOTXT, PROTOTXT_URL], check=True)
        print("  Done.")
    if not os.path.exists(CAFFEMODEL):
        print("Downloading caffemodel (~2.7MB)...")
        subprocess.run(["wget", "-q", "-O", CAFFEMODEL, CAFFEMODEL_URL], check=True)
        print("  Done.")

def load_model():
    if not os.path.exists(PROTOTXT) or not os.path.exists(CAFFEMODEL):
        download_models()
    net = cv2.dnn.readNetFromCaffe(PROTOTXT, CAFFEMODEL)
    print("Model loaded.")
    return net

# ── Camera ────────────────────────────────────────────────────────────────────

def open_camera():
    pipeline = "udpsrc port=5000 ! jpegdec ! videoconvert ! appsink"
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("ERROR: Could not open camera stream.")
        print("Make sure Terminal 1 is running:")
        print("  rpicam-vid --codec mjpeg --width 640 --height 480 --framerate 30 --timeout 0 --nopreview -o udp://127.0.0.1:5000")
        sys.exit(1)
    return cap

# ── Detection ─────────────────────────────────────────────────────────────────

def detect_faces(net, frame):
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)), 1.0,
        (300, 300), (104.0, 177.0, 123.0)
    )
    net.setInput(blob)
    detections = net.forward()

    faces = []
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < CONFIDENCE_THRESHOLD:
            continue
        box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
        x1, y1, x2, y2 = box.astype(int)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        faces.append(((x1, y1, x2, y2), confidence))
    return faces

def best_face(faces):
    if not faces:
        return None
    return max(faces, key=lambda f: f[1])

def face_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) // 2, (y1 + y2) // 2)

# ── Drawing ───────────────────────────────────────────────────────────────────

def draw_crosshair(frame, cx, cy):
    cv2.line(frame, (cx - CROSSHAIR_SIZE, cy), (cx + CROSSHAIR_SIZE, cy), CROSSHAIR_COLOR, 2)
    cv2.line(frame, (cx, cy - CROSSHAIR_SIZE), (cx, cy + CROSSHAIR_SIZE), CROSSHAIR_COLOR, 2)
    cv2.circle(frame, (cx, cy), 4, CROSSHAIR_COLOR, -1)

def draw_frame_center(frame):
    cx, cy = FRAME_WIDTH // 2, FRAME_HEIGHT // 2
    cv2.circle(frame, (cx, cy), 5, CENTER_DOT_COLOR, -1)

def annotate_frame(frame, faces, primary, show_debug, face_state):
    draw_frame_center(frame)

    for (box, conf) in faces:
        x1, y1, x2, y2 = box
        is_primary = (primary is not None and box == primary[0])
        color     = BOX_COLOR if is_primary else (100, 100, 100)
        thickness = 2 if is_primary else 1
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        if show_debug:
            cv2.putText(frame, f"{conf:.2f}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    if primary:
        box, conf = primary
        cx, cy = face_center(box)
        draw_crosshair(frame, cx, cy)
        off_x = cx - FRAME_WIDTH  // 2
        off_y = cy - FRAME_HEIGHT // 2
        cv2.putText(frame, f"({cx}, {cy})", (10, FRAME_HEIGHT - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2)
        cv2.putText(frame, f"offset ({off_x:+d}, {off_y:+d})", (10, FRAME_HEIGHT - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2)

    if show_debug:
        status = f"Tracking ({len(faces)} face{'s' if len(faces) != 1 else ''})" if faces else "Searching..."
        cv2.putText(frame, status, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2)
        cv2.putText(frame, "Q=quit  D=debug", (FRAME_WIDTH - 180, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT_COLOR, 1)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading face detection model...")
    net = load_model()

    print("Initialising servos...")
    pca     = PCA9685()
    tracker = HeadTracker(pca)

    # Start arm in resting position
    arm_deg = ARM_DOWN_DEG
    pca.set_angle(ARM_CHANNEL, arm_deg)

    print("Opening camera stream...")
    cap = open_camera()

    cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(PREVIEW_WINDOW, FRAME_WIDTH, FRAME_HEIGHT)

    show_debug        = True
    frame_count       = 0
    face_visible      = False
    frames_since_face = 0
    sound_thread      = None
    arm_thread        = None   # So arm moves never block the camera loop

    print("Running — press Q to quit, D to toggle debug overlay.\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Lost camera stream.")
                break

            frame_count += 1
            faces   = detect_faces(net, frame)
            primary = best_face(faces)

            # ── Face presence logic ───────────────────────────────────────────

            if primary:
                cx, cy = face_center(primary[0])

                if not face_visible:
                    face_visible      = True
                    frames_since_face = 0
                    print(f"Face detected at ({cx}, {cy}) — raising arm and playing sound.")

                    # Sound in background thread
                    sound_thread = threading.Thread(
                        target=soundTest.phrase_random, daemon=True)
                    sound_thread.start()

                    # Arm raise in background thread so camera loop keeps running
                    def raise_arm():
                        nonlocal arm_deg
                        arm_deg = move_arm(pca, ARM_UP_DEG, arm_deg)
                    arm_thread = threading.Thread(target=raise_arm, daemon=True)
                    arm_thread.start()

                frames_since_face = 0

                # Update head servo every N frames
                if frame_count % SERVO_UPDATE_EVERY == 0:
                    tracker.update_target(cx)

            else:
                frames_since_face += 1
                if face_visible and frames_since_face >= FACE_LOST_FRAMES:
                    face_visible = False
                    print("Face lost — lowering arm and holding head position.")

                    # Lower arm in background thread
                    def lower_arm():
                        nonlocal arm_deg
                        arm_deg = move_arm(pca, ARM_DOWN_DEG, arm_deg)
                    arm_thread = threading.Thread(target=lower_arm, daemon=True)
                    arm_thread.start()

            # ── Draw & display ────────────────────────────────────────────────

            annotate_frame(frame, faces, primary, show_debug, face_visible)
            cv2.imshow(PREVIEW_WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("d"):
                show_debug = not show_debug

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        tracker.stop()
        cap.release()
        pca.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
