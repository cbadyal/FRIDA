import unittest

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


if __name__ == "__main__":
    unittest.main()
