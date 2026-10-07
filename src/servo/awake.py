#!/usr/bin/env python3
"""A restrained startup gesture for FRIDA."""

import logging
from dataclasses import replace
from pathlib import Path
import sys

SOUND_DIR = Path(__file__).resolve().parents[1] / "sound"
if str(SOUND_DIR) not in sys.path:
    sys.path.insert(0, str(SOUND_DIR))

import soundTest

try:
    from .controller import SERVOS, ServoController
except ImportError:
    from controller import SERVOS, ServoController


def awake(controller: ServoController) -> None:
    controller.clear_cancel()
    soundTest.phrase_startup()

    head = controller.servos[0]
    head_base = head.rest_deg
    if not controller.move_smooth(0, min(head.max_deg, head_base + 30)):
        return
    if not controller.wait(0.8):
        return
    if not controller.move_smooth(0, head_base):
        return
    if not controller.wait(0.8):
        return

    if not controller.move_many({1: 40, 2: 88}):
        return
    if not controller.wait(1.5):
        return
    print(f"Returning head to base ({head_base:g} degrees).")
    if not controller.move_to_rest():
        return
    controller.wait(2.0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    servos = dict(SERVOS)
    # Use the original startup's head base without changing other scripts' limits.
    servos[0] = replace(servos[0], min_deg=0, rest_deg=0)
    try:
        controller = ServoController(servos=servos)
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
