"""Shared, safety-limited motion control for FRIDA's PCA9685 servos."""

from dataclasses import dataclass
import logging
import math
import threading
import time
from typing import Callable, Mapping, Optional


PCA9685_ADDR = 0x40
I2C_BUS = 1
PWM_FREQ = 50
OSC_CLOCK = 25_000_000
UPDATE_HZ = 50

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServoConfig:
    name: str
    min_deg: float
    max_deg: float
    rest_deg: float
    max_speed_dps: float
    pulse_min_us: int = 500
    pulse_max_us: int = 2500


# These angle limits preserve the most conservative ranges already used by the
# robot scripts. Pulse widths should be narrowed after physical calibration.
SERVOS = {
    0: ServoConfig("head", 120, 180, 150, 25),
    1: ServoConfig("left arm", 0, 90, 0, 25),
    2: ServoConfig("right arm", 60, 120, 60, 20),
    3: ServoConfig("claw", 0, 90, 0, 30),
}


def clamp_angle(config: ServoConfig, angle: float) -> float:
    return max(config.min_deg, min(config.max_deg, float(angle)))


def angle_to_pulse_us(config: ServoConfig, angle: float) -> float:
    safe_angle = clamp_angle(config, angle)
    return config.pulse_min_us + (
        (config.pulse_max_us - config.pulse_min_us) * safe_angle / 180.0
    )


def pulse_us_to_tick(pulse_us: float, frequency: int = PWM_FREQ) -> int:
    return round(pulse_us / (1_000_000 / frequency) * 4096)


class PCA9685:
    """Small thread-safe PCA9685 driver with an injectable bus for tests."""

    def __init__(self, bus=None, address: int = PCA9685_ADDR):
        self.address = address
        self._lock = threading.RLock()
        self._closed = False
        self._outputs_disabled = False

        if bus is None:
            try:
                import smbus2

                bus = smbus2.SMBus(I2C_BUS)
            except Exception as exc:
                raise RuntimeError(f"Cannot open I2C bus {I2C_BUS}: {exc}") from exc

        self.bus = bus
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self.bus.write_byte_data(self.address, 0x00, 0x00)
            time.sleep(0.005)
            prescale = round(OSC_CLOCK / (4096 * PWM_FREQ)) - 1
            self.bus.write_byte_data(self.address, 0x00, 0x10)
            self.bus.write_byte_data(self.address, 0xFE, prescale)
            self.bus.write_byte_data(self.address, 0x00, 0x00)
            time.sleep(0.005)
            self.bus.write_byte_data(self.address, 0x00, 0xA0)

    def set_pulse_us(self, channel: int, pulse_us: float) -> None:
        off_tick = pulse_us_to_tick(pulse_us)
        base = 0x06 + 4 * channel
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot write to a closed PCA9685")
            if self._outputs_disabled:
                return
            self.bus.write_i2c_block_data(
                self.address,
                base,
                [0, 0, off_tick & 0xFF, (off_tick >> 8) & 0x0F],
            )

    def disable_all(self) -> None:
        """Disable PWM output on every channel immediately."""
        with self._lock:
            if not self._closed:
                self._outputs_disabled = True
                self.bus.write_i2c_block_data(
                    self.address, 0xFA, [0, 0, 0, 0x10]
                )

    def close(self, disable: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            if disable:
                self.disable_all()
            self.bus.close()
            self._closed = True


class ServoController:
    """Owns servo state and executes serialized, eased movements."""

    def __init__(
        self,
        driver: Optional[PCA9685] = None,
        servos: Mapping[int, ServoConfig] = SERVOS,
        wait_fn: Optional[Callable[[float], bool]] = None,
    ):
        self.driver = driver or PCA9685()
        self.servos = dict(servos)
        self.current_angles = {
            channel: config.rest_deg for channel, config in self.servos.items()
        }
        self._movement_lock = threading.RLock()
        self._cancelled = threading.Event()
        self._wait_fn = wait_fn or self._cancelled.wait

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def clear_cancel(self) -> None:
        self._cancelled.clear()

    def cancel(self) -> None:
        self._cancelled.set()

    def _safe_target(self, channel: int, target: float) -> float:
        if channel not in self.servos:
            raise ValueError(f"No servo configuration for channel {channel}")
        config = self.servos[channel]
        safe_target = clamp_angle(config, target)
        if not math.isclose(safe_target, float(target)):
            LOGGER.warning(
                "Clamped %s target from %.1f to %.1f degrees",
                config.name,
                target,
                safe_target,
            )
        return safe_target

    def _write_angle(self, channel: int, angle: float) -> None:
        config = self.servos[channel]
        safe_angle = clamp_angle(config, angle)
        self.driver.set_pulse_us(channel, angle_to_pulse_us(config, safe_angle))
        self.current_angles[channel] = safe_angle

    def move_smooth(
        self, channel: int, target: float, duration: Optional[float] = None
    ) -> bool:
        return self.move_many({channel: target}, duration=duration)

    def move_many(
        self, targets: Mapping[int, float], duration: Optional[float] = None
    ) -> bool:
        """Move one or more servos together with smooth acceleration/deceleration.

        Returns False when cancellation interrupts the movement.
        """
        with self._movement_lock:
            if self.cancelled:
                return False

            safe_targets = {
                channel: self._safe_target(channel, target)
                for channel, target in targets.items()
            }
            starts = {
                channel: self.current_angles[channel] for channel in safe_targets
            }

            # Smoothstep's peak velocity is 1.5 times its average velocity.
            minimum_duration = max(
                [
                    1.5
                    * abs(safe_targets[channel] - starts[channel])
                    / self.servos[channel].max_speed_dps
                    for channel in safe_targets
                ]
                + [0.0]
            )
            if duration is None:
                duration = minimum_duration
            else:
                duration = max(minimum_duration, float(duration))
            duration = max(0.0, duration)
            steps = max(1, math.ceil(duration * UPDATE_HZ))
            interval = duration / steps

            for step in range(1, steps + 1):
                if self.cancelled:
                    return False
                progress = step / steps
                eased = progress * progress * (3.0 - 2.0 * progress)
                for channel, target in safe_targets.items():
                    angle = starts[channel] + (target - starts[channel]) * eased
                    self._write_angle(channel, angle)
                if step < steps and interval and self._wait_fn(interval):
                    return False

            return True

    def wait(self, seconds: float) -> bool:
        """Wait responsively; return False if the sequence was cancelled."""
        return not self._wait_fn(max(0.0, seconds))

    def move_to_rest(self, duration: Optional[float] = None) -> bool:
        return self.move_many(
            {channel: config.rest_deg for channel, config in self.servos.items()},
            duration=duration,
        )

    def emergency_stop(self) -> None:
        self.cancel()
        self.driver.disable_all()

    def close(self) -> None:
        self.cancel()
        self.driver.close(disable=True)


def test_servo(controller: ServoController, channel: int) -> None:
    config = controller.servos[channel]
    print(
        f"Testing {config.name} | range: "
        f"{config.min_deg:g} - {config.max_deg:g} degrees"
    )
    for label, angle in (
        ("Minimum", config.min_deg),
        ("Maximum", config.max_deg),
        ("Rest", config.rest_deg),
    ):
        print(f"  {label} ({angle:g} degrees)")
        if not controller.move_smooth(channel, angle):
            return
        if not controller.wait(1.0):
            return
