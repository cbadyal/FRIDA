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


def wave_steps(start_angle: float, cycles: int = 3):
    """Return shared (target angle, hold seconds) steps for either wave API."""
    if not isinstance(cycles, int) or cycles < 1:
        raise ValueError("cycles must be a positive integer")
    return ((WAVE_HIGH, 0.25), (WAVE_LOW, 0.25)) * cycles + ((start_angle, 1.0),)


class WaveGesture:
    """A wave advanced by the demo's motion loop, alongside head tracking."""

    def __init__(self, controller: ServoController, cycles: int = 3):
        wave_steps(0, cycles)  # Validate before scheduling any movement.
        self.controller = controller
        self.cycles = cycles
        self.active = False
        self._steps = iter(())
        self._hold_until = None
        self._hold_seconds = 0.0

    def start(self) -> bool:
        if self.active or self.controller.cancelled:
            return False
        start_angle = self.controller.current_angles[RIGHT_ARM]
        self._steps = iter(wave_steps(start_angle, self.cycles))
        self.active = True
        self._advance()
        return True

    def _advance(self) -> None:
        step = next(self._steps, None)
        if step is None:
            self.active = False
            return
        target, self._hold_seconds = step
        self._hold_until = None
        if not self.controller.set_target(RIGHT_ARM, target):
            self.active = False

    def update(self, now: float) -> None:
        if self.controller.cancelled:
            self.active = False
        if not self.active or self.controller.is_moving(RIGHT_ARM):
            return
        if self._hold_until is None:
            self._hold_until = now + self._hold_seconds
        if now >= self._hold_until:
            self._advance()


def wave(controller: ServoController, cycles: int = 3) -> bool:
    """Perform a greeting using the controller's known right-arm position.

    Return False if cancelled, leaving the arm at the interrupted position.
    """
    start_angle = controller.current_angles[RIGHT_ARM]
    for target, hold in wave_steps(start_angle, cycles):
        if not controller.move_smooth(RIGHT_ARM, target):
            return False
        if not controller.wait(hold):
            return False
    return True


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
