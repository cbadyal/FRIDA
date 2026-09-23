#!/usr/bin/env python3
"""Calm idle choreography for FRIDA."""

import logging
from pathlib import Path
import random
import sys

SOUND_DIR = Path(__file__).resolve().parents[1] / "sound"
if str(SOUND_DIR) not in sys.path:
    sys.path.insert(0, str(SOUND_DIR))

import soundTest

try:
    from .controller import ServoController, test_servo
except ImportError:
    from controller import ServoController, test_servo


HEAD_LEFT = 142
HEAD_CENTER = 150
HEAD_RIGHT = 158
LEFT_ARM_PARTIAL = 30
RIGHT_ARM_PARTIAL = 82
CLAW_SOFT_FLEX = 25


def servo_idle(controller: ServoController) -> None:
    """Run small, slow gestures with long rests between movement groups."""
    controller.clear_cancel()

    while not controller.cancelled:
        soundTest.phrase_happy()

        if not controller.move_smooth(0, HEAD_LEFT):
            return
        if not controller.wait(1.2):
            return
        if not controller.move_smooth(0, HEAD_CENTER):
            return
        if not controller.wait(random.uniform(2.5, 4.0)):
            return

        if not controller.move_many({1: LEFT_ARM_PARTIAL, 2: RIGHT_ARM_PARTIAL}):
            return
        if not controller.wait(1.5):
            return
        if not controller.move_smooth(3, CLAW_SOFT_FLEX):
            return
        if not controller.wait(0.8):
            return
        if not controller.move_smooth(3, 0):
            return
        if not controller.wait(1.5):
            return

        if not controller.move_smooth(0, HEAD_RIGHT):
            return
        if not controller.wait(1.0):
            return
        if not controller.move_smooth(0, HEAD_CENTER):
            return
        if not controller.move_many({1: 0, 2: 60}):
            return

        if not controller.wait(random.uniform(5.0, 8.0)):
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        controller = ServoController()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return

    try:
        servo_idle(controller)
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
        controller.emergency_stop()
    finally:
        print("Disabling PWM and closing I2C bus.")
        controller.close()


if __name__ == "__main__":
    main()
