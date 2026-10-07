#!/usr/bin/env python3
"""Return FRIDA's head to the original startup script's 0-degree base."""

import argparse
from dataclasses import replace
import logging
import math

try:
    from .controller import SERVOS, ServoController
except ImportError:
    from controller import SERVOS, ServoController


def reset_head(controller: ServoController) -> None:
    controller.clear_cancel()
    rest_angle = controller.servos[0].rest_deg
    print(f"Returning head to base ({rest_angle:g} degrees).")

    if not controller.move_smooth(0, rest_angle):
        return
    # Keep PWM active after the final target so the servo can settle.
    controller.wait(2.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-angle", type=float, required=True,
        help="Known current head angle in the calibrated 0-180 command scale",
    )
    args = parser.parse_args()
    if not math.isfinite(args.start_angle) or not 0 <= args.start_angle <= 180:
        parser.error("--start-angle must be a finite angle from 0 to 180")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    head_config = replace(SERVOS[0], min_deg=0, rest_deg=0)
    try:
        controller = ServoController(servos={0: head_config})
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return

    try:
        controller.current_angles[0] = args.start_angle
        reset_head(controller)
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
        controller.emergency_stop()
    finally:
        print("Disabling PWM and closing I2C bus.")
        controller.close()


if __name__ == "__main__":
    main()
