#!/usr/bin/env python3
"""Test smooth arm motion within FRIDA's original command ranges."""

import argparse
from dataclasses import replace
import logging
import math
from typing import Sequence

try:
    from .controller import SERVOS, ServoController
except ImportError:
    from controller import SERVOS, ServoController


def test_arm(
    controller: ServoController,
    channel: int,
    start_angle: float,
    targets: Sequence[float],
) -> bool:
    controller.clear_cancel()
    # This is a supplied command position, not servo feedback.
    controller.current_angles[channel] = start_angle
    sequence = " -> ".join(f"{angle:g}" for angle in (start_angle, *targets))
    print(
        f"Testing {controller.servos[channel].name} on channel {channel}: "
        f"{sequence} degrees."
    )
    for index, target in enumerate(targets):
        returning = index == len(targets) - 1
        if returning:
            print(f"Returning channel {channel} to {start_angle:g} degrees.")
        if not controller.move_smooth(channel, target):
            return False
        if not controller.wait(2.0 if returning else 1.0):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Use only with a positional servo and a known starting command angle. "
            "The script cannot measure position; original ranges are not a "
            "physical safety guarantee. Ctrl+C stops without returning. "
            "Shutdown disables PWM on all channels."
        ),
    )
    parser.add_argument(
        "--channel", type=int, choices=(1, 2), required=True,
        help="PCA9685 channel: 1 = left arm, 2 = right arm / elbow",
    )
    parser.add_argument(
        "--start-angle", type=float, required=True,
        help="Known starting angle in the calibrated command scale",
    )
    movement = parser.add_mutually_exclusive_group()
    movement.add_argument(
        "--offset", type=float, default=10.0,
        help="Signed test movement within the channel range (default: 10 degrees)",
    )
    movement.add_argument(
        "--full-range", action="store_true",
        help="Sweep original minimum to maximum, then return to the starting angle",
    )
    args = parser.parse_args()
    config = SERVOS[args.channel]
    if not math.isfinite(args.start_angle) or not (
        config.min_deg <= args.start_angle <= config.max_deg
    ):
        parser.error(
            f"--start-angle must be finite and within "
            f"{config.min_deg:g}-{config.max_deg:g} for channel {args.channel}"
        )
    if args.full_range:
        targets = [config.min_deg, config.max_deg, args.start_angle]
    else:
        if not math.isfinite(args.offset) or args.offset == 0:
            parser.error("--offset must be finite and nonzero")
        target_angle = args.start_angle + args.offset
        if not config.min_deg <= target_angle <= config.max_deg:
            parser.error(
                f"The target ({target_angle:g}) must stay within "
                f"{config.min_deg:g}-{config.max_deg:g}; choose a smaller or opposite offset"
            )
        targets = [target_angle, args.start_angle]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    arm_config = replace(config, max_speed_dps=config.max_speed_dps * 1.4)
    try:
        controller = ServoController(
            servos={args.channel: arm_config}, motion_profile="smootherstep"
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    try:
        completed = test_arm(controller, args.channel, args.start_angle, targets)
        return 0 if completed else 1
    except KeyboardInterrupt:
        print("\nEmergency stop requested; not returning the servo.")
        controller.emergency_stop()
        return 130
    finally:
        print("Disabling PWM on all channels and closing I2C bus.")
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
