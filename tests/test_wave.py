import unittest
from unittest.mock import patch

from src.servo.controller import SERVOS, ServoController
from src.servo.wave import RIGHT_ARM, WaveGesture, main, wave


class RecordingDriver:
    def __init__(self):
        self.writes = []

    def set_pulse_us(self, channel, pulse):
        self.writes.append((channel, pulse))


class WaveTests(unittest.TestCase):
    def make_controller(self):
        driver = RecordingDriver()
        controller = ServoController(driver=driver, wait_fn=lambda _seconds: False)
        controller.current_angles[RIGHT_ARM] = 72
        return controller, driver

    def test_wave_stays_in_range_and_restores_starting_pose(self):
        controller, driver = self.make_controller()
        starting_angles = dict(controller.current_angles)

        self.assertTrue(wave(controller, cycles=2))

        self.assertEqual(controller.current_angles, starting_angles)
        self.assertTrue(driver.writes)
        arm = SERVOS[RIGHT_ARM]
        for channel, pulse in driver.writes:
            self.assertEqual(channel, RIGHT_ARM)
            angle = (pulse - arm.pulse_min_us) * 180 / (
                arm.pulse_max_us - arm.pulse_min_us
            )
            self.assertGreaterEqual(angle, arm.min_deg)
            self.assertLessEqual(angle, arm.max_deg)

    def test_cancelled_controller_does_not_start_waving(self):
        controller, driver = self.make_controller()
        controller.cancel()

        self.assertFalse(wave(controller))
        self.assertEqual(driver.writes, [])

    def test_cancellation_during_motion_does_not_return_arm(self):
        controller, driver = self.make_controller()

        def cancel_during_wait(_seconds):
            controller.cancel()
            return True

        controller._wait_fn = cancel_during_wait
        self.assertFalse(wave(controller))
        self.assertEqual(len(driver.writes), 1)
        self.assertNotEqual(controller.current_angles[RIGHT_ARM], 72)

    def test_invalid_cycles_do_not_move_arm(self):
        for cycles in (0, -1, 1.5):
            with self.subTest(cycles=cycles):
                controller, driver = self.make_controller()
                with self.assertRaises(ValueError):
                    wave(controller, cycles=cycles)
                self.assertEqual(driver.writes, [])

    def test_scheduled_wave_returns_to_start_while_head_keeps_moving(self):
        controller, driver = self.make_controller()
        gesture = WaveGesture(controller, cycles=1)
        self.assertTrue(gesture.start())
        self.assertFalse(gesture.start())
        controller.set_target(0, 170)
        moved_together = False
        for tick in range(1500):
            gesture.update(tick / 50)
            controller.update()
            if controller.current_angles[0] > 150 and controller.current_angles[RIGHT_ARM] > 72:
                moved_together = True
            if not gesture.active:
                break
        self.assertFalse(gesture.active)
        self.assertTrue(moved_together)
        self.assertEqual(controller.current_angles[RIGHT_ARM], 72)
        self.assertEqual(controller.current_angles[0], 170)
        self.assertTrue(all(channel in (0, RIGHT_ARM) for channel, _ in driver.writes))

    def test_scheduled_wave_stops_without_returning_after_cancellation(self):
        controller, driver = self.make_controller()
        gesture = WaveGesture(controller, cycles=1)
        gesture.start()
        controller.update()
        controller.cancel()
        writes = list(driver.writes)
        gesture.update(1)
        controller.update()
        self.assertFalse(gesture.active)
        self.assertEqual(driver.writes, writes)
        self.assertNotEqual(controller.current_angles[RIGHT_ARM], 72)

    def test_cli_rejects_invalid_input_before_opening_hardware(self):
        for arguments in (
            ["--start-angle", "nan"],
            ["--start-angle", "59"],
            ["--start-angle", "121"],
            ["--start-angle", "60", "--cycles", "0"],
        ):
            with self.subTest(arguments=arguments):
                with patch("sys.argv", ["wave.py", *arguments]), patch(
                    "src.servo.wave.ServoController"
                ) as controller, patch("sys.stderr"):
                    with self.assertRaises(SystemExit) as exc:
                        main()
                    self.assertEqual(exc.exception.code, 2)
                    controller.assert_not_called()

    def test_cli_interrupt_disables_and_closes_controller(self):
        with patch("sys.argv", ["wave.py", "--start-angle", "60"]), patch(
            "src.servo.wave.ServoController"
        ) as factory, patch(
            "src.servo.wave.wave", side_effect=KeyboardInterrupt
        ), patch("builtins.print"):
            self.assertEqual(main(), 130)
            factory.return_value.emergency_stop.assert_called_once_with()
            factory.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
