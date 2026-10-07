import unittest
from unittest.mock import patch

from src.servo.controller import (
    PCA9685,
    SERVOS,
    ServoController,
    angle_to_pulse_us,
    clamp_angle,
    pulse_us_to_tick,
)


class FakeBus:
    def __init__(self):
        self.byte_writes = []
        self.block_writes = []
        self.closed = False

    def write_byte_data(self, address, register, value):
        self.byte_writes.append((address, register, value))

    def write_i2c_block_data(self, address, register, values):
        self.block_writes.append((address, register, values))

    def close(self):
        self.closed = True


class ServoControllerTests(unittest.TestCase):
    def make_controller(self):
        bus = FakeBus()
        driver = PCA9685(bus=bus)
        controller = ServoController(driver=driver, wait_fn=lambda _seconds: False)
        return controller, bus

    def test_clamps_to_configured_range(self):
        head = SERVOS[0]
        self.assertEqual(clamp_angle(head, 20), 120)
        self.assertEqual(clamp_angle(head, 200), 180)

    def test_angle_conversion_uses_safe_angle(self):
        head = SERVOS[0]
        self.assertEqual(angle_to_pulse_us(head, 0), angle_to_pulse_us(head, 120))
        self.assertEqual(pulse_us_to_tick(1500), 307)

    def test_move_starts_from_seeded_rest_and_lands_on_target(self):
        controller, bus = self.make_controller()
        controller.move_smooth(0, 160, duration=0.1)

        self.assertEqual(controller.current_angles[0], 160)
        self.assertGreater(len(bus.block_writes), 1)

    def test_out_of_range_target_is_clamped(self):
        controller, _bus = self.make_controller()
        controller.move_smooth(0, 0, duration=0)
        self.assertEqual(controller.current_angles[0], 120)

    def test_cancel_stops_future_movements(self):
        controller, bus = self.make_controller()
        writes_before_cancel = len(bus.block_writes)
        controller.cancel()

        self.assertFalse(controller.move_smooth(0, 160))
        self.assertEqual(len(bus.block_writes), writes_before_cancel)

    def test_emergency_stop_disables_all_outputs(self):
        controller, bus = self.make_controller()
        controller.emergency_stop()
        self.assertEqual(bus.block_writes[-1][1:], (0xFA, [0, 0, 0, 0x10]))

        writes_after_stop = len(bus.block_writes)
        controller.driver.set_pulse_us(0, 1500)
        self.assertEqual(len(bus.block_writes), writes_after_stop)


class SmootherMotionTests(unittest.TestCase):
    def make_controller(self, write_delay=0.0, oversleep=0.0):
        clock = [0.0]
        writes = []
        waits = []
        driver = PCA9685(bus=FakeBus())
        original_write = driver.set_pulse_us

        def write(channel, pulse):
            writes.append((clock[0], channel, pulse))
            original_write(channel, pulse)
            clock[0] += write_delay

        def wait(seconds):
            waits.append(seconds)
            clock[0] += seconds + oversleep
            return False

        driver.set_pulse_us = write
        controller = ServoController(
            driver=driver, wait_fn=wait, motion_profile="smootherstep"
        )
        return controller, clock, writes, waits

    def test_quintic_profile_is_eased_and_speed_limited(self):
        controller, clock, writes, _waits = self.make_controller()
        with patch("src.servo.controller.time.monotonic", side_effect=lambda: clock[0]):
            self.assertTrue(controller.move_smooth(1, 90))

        self.assertEqual(controller.current_angles[1], 90)
        positions = [0.0] + [(pulse - 500) * 180 / 2000 for _, _, pulse in writes]
        times = [0.0] + [timestamp for timestamp, _, _ in writes]
        velocities = [
            (end - start) / (end_time - start_time)
            for start, end, start_time, end_time in zip(
                positions, positions[1:], times, times[1:]
            )
        ]
        self.assertGreater(len(writes), 100)
        self.assertLessEqual(max(velocities), SERVOS[1].max_speed_dps + 1e-8)
        self.assertLess(velocities[0], max(velocities) / 100)
        self.assertLess(velocities[-1], max(velocities) / 100)
        self.assertAlmostEqual(times[-1], 1.875 * 90 / SERVOS[1].max_speed_dps)

    def test_write_time_is_subtracted_from_frame_wait(self):
        controller, clock, writes, waits = self.make_controller(write_delay=0.004)
        with patch("src.servo.controller.time.monotonic", side_effect=lambda: clock[0]):
            self.assertTrue(controller.move_smooth(0, 160, duration=1.0))

        self.assertEqual(len(writes), 50)
        self.assertAlmostEqual(waits[0], 0.02)
        self.assertAlmostEqual(waits[1], 0.016)
        self.assertAlmostEqual(writes[-1][0], 1.0)
        for before, after in zip(writes, writes[1:]):
            self.assertAlmostEqual(after[0] - before[0], 0.02)

    def test_late_frames_do_not_create_catch_up_bursts(self):
        controller, clock, writes, _waits = self.make_controller(oversleep=0.03)
        with patch("src.servo.controller.time.monotonic", side_effect=lambda: clock[0]):
            self.assertTrue(controller.move_smooth(0, 160, duration=1.0))

        for before, after in zip(writes, writes[1:]):
            self.assertGreaterEqual(after[0] - before[0], 0.02 - 1e-9)
        self.assertEqual(controller.current_angles[0], 160)

    def test_cancellation_during_wait_prevents_writes(self):
        controller, clock, writes, _waits = self.make_controller()

        def cancel_during_wait(_seconds):
            controller.cancel()
            return False

        controller._wait_fn = cancel_during_wait
        with patch("src.servo.controller.time.monotonic", side_effect=lambda: clock[0]):
            self.assertFalse(controller.move_smooth(1, 90))
        self.assertEqual(writes, [])

    def test_invalid_profile_is_rejected_before_opening_hardware(self):
        with patch("src.servo.controller.PCA9685") as driver:
            with self.assertRaises(ValueError):
                ServoController(motion_profile="unknown")
            driver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
