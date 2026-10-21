#!/usr/bin/env python3
"""Wave FRIDA's right arm, then return it to its starting position."""

import argparse
import logging
import math

try:
    from .controller import SERVOS, ServoController
except ImportError:
    from controller import SERVOS, ServoController


RIGHT_ARM = 2
WAVE_LOW = 85
WAVE_HIGH = 105


def wave(controller: ServoController, cycles: int = 3) -> bool:
    """Perform a greeting using the controller's known right-arm position.

    Return False if cancelled, leaving the arm at the interrupted position.
    """
    if not isinstance(cycles, int) or cycles < 1:
        raise ValueError("cycles must be a positive integer")

    start_angle = controller.current_angles[RIGHT_ARM]
    for _ in range(cycles):
        for target in (WAVE_HIGH, WAVE_LOW):
            if not controller.move_smooth(RIGHT_ARM, target):
                return False
            if not controller.wait(0.25):
                return False

    if not controller.move_smooth(RIGHT_ARM, start_angle):
        return False
    return controller.wait(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-angle", type=float, required=True,
        help="Known starting right-arm angle (60-120 degrees); position is not measured",
    )
    parser.add_argument(
        "--cycles", type=int, default=3,
        help="Number of waves (default: 3)",
    )
    args = parser.parse_args()
    arm = SERVOS[RIGHT_ARM]
    if not math.isfinite(args.start_angle) or not (
        arm.min_deg <= args.start_angle <= arm.max_deg
    ):
        parser.error(
            f"--start-angle must be finite and within {arm.min_deg:g}-{arm.max_deg:g}"
        )
    if args.cycles < 1:
        parser.error("--cycles must be a positive integer")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        controller = ServoController(
            servos={RIGHT_ARM: arm}, motion_profile="smootherstep"
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    # The starting command is supplied by the operator, not read from the servo.
    controller.current_angles[RIGHT_ARM] = args.start_angle
    try:
        print(f"Waving right arm {args.cycles} time(s). Ctrl+C stops the gesture.")
        return 0 if wave(controller, args.cycles) else 1
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
        controller.emergency_stop()
        return 130
    finally:
        print("Disabling PWM on all channels and closing I2C bus.")
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
