#!/usr/bin/env python3
"""Short demonstration using the shared safe-motion controller."""

import logging
from pathlib import Path
import sys

SOUND_DIR = Path(__file__).resolve().parents[1] / "sound"
if str(SOUND_DIR) not in sys.path:
    sys.path.insert(0, str(SOUND_DIR))

import soundTest

try:
    from .controller import ServoController
except ImportError:
    from controller import ServoController


def demo(controller: ServoController) -> None:
    controller.clear_cancel()
    soundTest.phrase_startup()

    if not controller.move_smooth(0, 143):
        return
    if not controller.wait(1.0):
        return
    if not controller.move_smooth(0, 157):
        return
    if not controller.wait(1.0):
        return
    if not controller.move_smooth(0, 150):
        return

    if not controller.move_many({1: 35, 2: 90}):
        return
    if not controller.wait(2.0):
        return
    controller.move_to_rest()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        controller = ServoController()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return

    try:
        demo(controller)
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
        controller.emergency_stop()
    finally:
        print("Disabling PWM and closing I2C bus.")
        controller.close()


if __name__ == "__main__":
    main()
