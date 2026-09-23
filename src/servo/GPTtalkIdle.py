#!/usr/bin/env python3
"""Quiet idle motion intended to run while FRIDA is speaking."""

import logging
import random

try:
    from .controller import ServoController
except ImportError:
    from controller import ServoController


def servo_idle(controller: ServoController) -> None:
    controller.clear_cancel()

    while not controller.cancelled:
        head_target = random.choice((144, 150, 156))
        arm_targets = random.choice(
            (
                {1: 12, 2: 70},
                {1: 20, 2: 76},
                {1: 8, 2: 68},
            )
        )

        if not controller.move_smooth(0, head_target):
            return
        if not controller.move_many(arm_targets):
            return
        if not controller.wait(random.uniform(2.0, 4.0)):
            return

        if not controller.move_many({0: 150, 1: 0, 2: 60}):
            return
        if not controller.wait(random.uniform(3.0, 6.0)):
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
