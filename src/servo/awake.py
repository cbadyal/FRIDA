#!/usr/bin/env python3
"""A restrained startup gesture for FRIDA."""

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


def awake(controller: ServoController) -> None:
    controller.clear_cancel()
    soundTest.phrase_startup()

    if not controller.move_smooth(0, 142):
        return
    if not controller.wait(0.8):
        return
    if not controller.move_smooth(0, 158):
        return
    if not controller.wait(0.8):
        return
    if not controller.move_smooth(0, 150):
        return

    if not controller.move_many({1: 40, 2: 88}):
        return
    if not controller.wait(1.5):
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
        awake(controller)
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
        controller.emergency_stop()
    finally:
        print("Disabling PWM and closing I2C bus.")
        controller.close()


if __name__ == "__main__":
    main()
