import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from demo import AudioWorker, BehaviorState, DEMO_SERVOS, DemoBehavior, main, run_demo
from src.camera.detection import CameraDetector, Face
from src.servo.controller import ServoController


class RecordingDriver:
    def __init__(self):
        self.writes = []
        self.disabled = False
        self.closed = False

    def set_pulse_us(self, channel, pulse):
        if self.disabled:
            raise AssertionError("Write after shutdown")
        self.writes.append((channel, pulse))

    def disable_all(self):
        self.disabled = True

    def close(self, disable=True):
        self.disabled = disable
        self.closed = True


class DemoBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.driver = RecordingDriver()
        self.controller = ServoController(driver=self.driver, servos=DEMO_SERVOS)
        self.audio = Mock()
        self.behavior = DemoBehavior(self.controller, self.audio, wave_cycles=1)
        self.now = 0.0
        self.behavior.start()
        self.behavior.tick(self.now, 0.02)
        self.face = Face(240, 80, 60, 60)

    def advance(self, seconds, faces=None):
        for _ in range(round(seconds * 50)):
            self.now += 0.02
            if faces is not None:
                self.behavior.observe(faces, 320, self.now)
            self.behavior.tick(self.now, 0.02)

    def test_waiting_commands_only_head_at_reset_base(self):
        self.advance(10, [])
        self.assertEqual(self.controller.current_angles[0], 0)
        self.assertEqual(self.driver.writes, [(0, 500)])
        self.audio.request.assert_not_called()

    def test_starting_away_from_base_returns_head_before_greeting(self):
        self.controller.current_angles[0] = 30
        self.behavior = DemoBehavior(self.controller, self.audio, wave_cycles=1)
        self.assertEqual(self.behavior.state, BehaviorState.STARTING)
        self.behavior.start()
        self.advance(0.5, [self.face])
        self.assertEqual(self.behavior.state, BehaviorState.STARTING)
        self.assertGreater(self.controller.current_angles[0], 0)
        self.audio.request.assert_not_called()
        self.assertTrue(all(channel == 0 for channel, _ in self.driver.writes))
        self.advance(3, [])
        self.assertEqual(self.behavior.state, BehaviorState.WAITING)

    def test_brief_detection_does_not_wave_or_move_arms(self):
        self.advance(0.2, [self.face])
        self.assertEqual(self.behavior.state, BehaviorState.CONFIRMING_FACE)
        self.advance(2, [])
        self.assertEqual(self.behavior.state, BehaviorState.WAITING)
        self.audio.request.assert_not_called()
        self.assertFalse(self.behavior.present)
        self.assertTrue(all(channel == 0 for channel, _ in self.driver.writes))

    def test_continuous_face_triggers_one_wave_and_arms_then_stay_still(self):
        self.advance(25, [self.face])
        self.audio.request.assert_called_once_with("happy")
        self.assertFalse(self.behavior.wave.active)
        self.assertEqual(self.controller.current_angles[2], 60)
        arm_writes = [write for write in self.driver.writes if write[0] == 2]
        self.assertTrue(arm_writes)
        self.advance(5, [self.face])
        self.assertEqual(arm_writes, [write for write in self.driver.writes if write[0] == 2])
        self.assertTrue(all(channel in (0, 2) for channel, _ in self.driver.writes))

    def test_brief_occlusion_does_not_repeat_greeting(self):
        self.advance(1, [self.face])
        self.advance(0.5, [])
        self.assertTrue(self.behavior.present)
        self.advance(20, [self.face])
        self.audio.request.assert_called_once_with("happy")

    def test_face_loss_returns_head_and_allows_another_greeting(self):
        self.advance(20, [self.face])
        self.assertGreater(self.controller.current_angles[0], 0)
        arm_count = len([write for write in self.driver.writes if write[0] == 2])
        self.advance(12, [])
        self.assertFalse(self.behavior.present)
        self.assertEqual(self.controller.current_angles[0], 0)
        self.assertEqual(arm_count, len([write for write in self.driver.writes if write[0] == 2]))
        self.advance(1, [self.face])
        self.assertEqual(self.audio.request.call_count, 2)

    def test_face_timeout_also_runs_when_camera_observations_stall(self):
        self.advance(1, [self.face])
        self.advance(12)  # Motion loop keeps running while no new frames arrive.
        self.assertFalse(self.behavior.present)
        self.assertEqual(self.controller.current_angles[0], 0)
        self.assertEqual(self.behavior.state, BehaviorState.WAITING)

    def test_states_and_logs_follow_a_visit_without_repeating_each_frame(self):
        self.assertEqual(self.behavior.state, BehaviorState.WAITING)
        with self.assertLogs("demo", level="INFO") as logs:
            self.advance(1, [])
            self.advance(0.2, [self.face])
            self.assertEqual(self.behavior.state, BehaviorState.CONFIRMING_FACE)
            self.advance(0.2, [self.face])
            self.assertEqual(self.behavior.state, BehaviorState.GREETING)
            self.advance(12, [self.face])
            self.assertEqual(self.behavior.state, BehaviorState.TRACKING)
            self.advance(1.6, [])
            self.assertEqual(self.behavior.state, BehaviorState.RETURNING_HOME)
            self.assertEqual(self.behavior.status, "State: RETURNING_HOME")
            self.advance(12, [])
            self.assertEqual(self.behavior.state, BehaviorState.WAITING)
        transitions = [
            record.getMessage() for record in logs.records
            if record.getMessage().startswith("FRIDA state:")
        ]
        self.assertEqual(transitions, [
            "FRIDA state: WAITING -> CONFIRMING_FACE",
            "FRIDA state: CONFIRMING_FACE -> GREETING",
            "FRIDA state: GREETING -> TRACKING",
            "FRIDA state: TRACKING -> RETURNING_HOME",
            "FRIDA state: RETURNING_HOME -> WAITING",
        ])

    def test_face_loss_during_wave_keeps_greeting_state_until_gesture_finishes(self):
        self.advance(1, [self.face])
        self.advance(1.6, [])
        self.assertFalse(self.behavior.present)
        self.assertTrue(self.behavior.wave.active)
        self.assertEqual(self.behavior.state, BehaviorState.GREETING)
        self.advance(12, [])
        self.assertEqual(self.behavior.state, BehaviorState.WAITING)

    def test_cancellation_reports_stopped_and_does_not_resume_for_faces(self):
        self.advance(1, [self.face])
        writes = list(self.driver.writes)
        self.controller.cancel()
        self.advance(1, [self.face])
        self.assertEqual(self.behavior.state, BehaviorState.STOPPED)
        self.assertEqual(self.driver.writes, writes)

    def test_error_is_preserved_through_stop_and_later_observations(self):
        self.advance(1, [self.face])
        writes = list(self.driver.writes)
        self.behavior.fail(RuntimeError("Camera disconnected"))
        self.behavior.stop()
        self.advance(1, [self.face])
        self.assertEqual(self.behavior.state, BehaviorState.ERROR)
        self.assertEqual(self.behavior.error, "Camera disconnected")
        self.assertEqual(self.driver.writes, writes)

    def test_primary_face_favors_previous_location_when_group_changes(self):
        first = self.behavior.observe([self.face], 320, self.now)
        other = Face(0, 0, 150, 150)
        selected = self.behavior.observe([other, self.face], 320, self.now + 0.1)
        self.assertEqual(first, selected)

    def test_deadband_holds_head_and_tracking_direction_can_be_reversed(self):
        self.advance(20, [Face(130, 80, 60, 60)])
        self.assertEqual(self.controller.current_angles[0], 0)
        self.controller.current_angles[0] = 90
        self.behavior.direction = -1
        self.advance(1, [self.face])
        self.assertLess(self.controller.current_angles[0], 90)


class DemoLifecycleTests(unittest.TestCase):
    def make_resources(self):
        driver = RecordingDriver()
        controller = ServoController(driver=driver, servos=DEMO_SERVOS)
        camera = Mock()
        camera.read.return_value = (SimpleNamespace(shape=(240, 320, 3)), [])
        camera.preview.return_value = ord("q")
        return driver, controller, camera

    def test_quit_and_camera_errors_close_every_resource(self):
        for failure in (None, RuntimeError("Camera disconnected"), KeyboardInterrupt()):
            with self.subTest(failure=failure):
                driver, controller, camera = self.make_resources()
                camera.read.side_effect = failure
                audio = Mock()
                behavior = DemoBehavior(controller, audio)
                with patch("demo.DemoBehavior", return_value=behavior):
                    if failure is None:
                        run_demo(camera, controller, audio)
                    else:
                        with self.assertRaises(type(failure)):
                            run_demo(camera, controller, audio)
                expected_state = (
                    BehaviorState.ERROR if isinstance(failure, Exception)
                    else BehaviorState.STOPPED
                )
                self.assertEqual(behavior.state, expected_state)
                camera.close.assert_called_once_with()
                audio.close.assert_called_once_with()
                self.assertTrue(controller.cancelled)
                self.assertTrue(driver.disabled)
                self.assertTrue(driver.closed)

    def test_camera_start_failure_also_closes_controller(self):
        driver, controller, camera = self.make_resources()
        camera.start.side_effect = RuntimeError("No camera")
        behavior = DemoBehavior(controller)
        with patch("demo.DemoBehavior", return_value=behavior), self.assertRaises(RuntimeError):
            run_demo(camera, controller)
        self.assertEqual(behavior.state, BehaviorState.ERROR)
        self.assertEqual(behavior.error, "No camera")
        camera.close.assert_called_once_with()
        self.assertTrue(driver.closed)

    def test_cleanup_failure_reports_error_instead_of_stopped(self):
        driver, controller, camera = self.make_resources()
        camera.close.side_effect = RuntimeError("Camera cleanup failed")
        behavior = DemoBehavior(controller)
        with patch("demo.DemoBehavior", return_value=behavior), self.assertRaises(RuntimeError):
            run_demo(camera, controller)
        self.assertEqual(behavior.state, BehaviorState.ERROR)
        self.assertEqual(behavior.error, "Camera cleanup failed")
        self.assertTrue(driver.closed)

    def test_camera_continues_during_a_wave_with_the_real_motion_worker(self):
        driver, controller, camera = self.make_resources()
        head_written = threading.Event()
        arm_written = threading.Event()
        original_write = driver.set_pulse_us

        def record_write(channel, pulse):
            original_write(channel, pulse)
            (head_written if channel == 0 else arm_written).set()

        driver.set_pulse_us = record_write
        reads = [head_written, arm_written]

        def read():
            self.assertTrue(reads.pop(0).wait(1), "Motion worker did not advance")
            return SimpleNamespace(shape=(240, 320, 3)), [Face(240, 80, 60, 60)]

        camera.read.side_effect = read
        camera.preview.side_effect = [-1, ord("q")]
        run_demo(camera, controller, confirm_seconds=0)
        self.assertEqual(camera.read.call_count, 2)
        self.assertGreater(controller.current_angles[0], 0)
        self.assertGreater(controller.current_angles[2], 60)
        self.assertLess(controller.current_angles[2], 105)
        self.assertTrue(driver.closed)

    def test_motion_worker_failure_is_reported_and_resources_are_closed(self):
        driver, controller, camera = self.make_resources()
        stopped = threading.Event()

        def fail_write(_channel, _pulse):
            raise OSError("Servo disconnected")

        def disable():
            driver.disabled = True
            stopped.set()

        def read():
            self.assertTrue(stopped.wait(1), "Motion error was not handled")
            return SimpleNamespace(shape=(240, 320, 3)), []

        driver.set_pulse_us = fail_write
        driver.disable_all = disable
        camera.read.side_effect = read
        behavior = DemoBehavior(controller)
        with patch("demo.DemoBehavior", return_value=behavior), self.assertRaisesRegex(
            RuntimeError, "Motion worker failed: Servo disconnected"
        ):
            run_demo(camera, controller)
        self.assertEqual(behavior.state, BehaviorState.ERROR)
        self.assertIn("Servo disconnected", behavior.error)
        camera.close.assert_called_once_with()
        self.assertTrue(driver.closed)

    def test_invalid_cli_arguments_do_not_open_hardware(self):
        for args in (
            ["--head-start-angle", "nan"], ["--arm-start-angle", "0"],
            ["--confirm-seconds", "-1"], ["--lost-seconds", "0.1"],
            ["--wave-cycles", "0"],
        ):
            with self.subTest(args=args), patch("demo.ServoController") as factory:
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    main(args)
                factory.assert_not_called()

    def test_camera_configuration_failure_closes_picamera(self):
        camera = Mock()
        camera.configure.side_effect = RuntimeError("Bad configuration")
        modules = {
            "cv2": Mock(), "picamera2": SimpleNamespace(Picamera2=Mock(return_value=camera)),
            "libcamera": SimpleNamespace(controls=Mock()),
        }
        detector = CameraDetector()
        with patch.dict("sys.modules", modules), patch("src.camera.detection.load_face_cascade"):
            with self.assertRaises(RuntimeError):
                detector.start()
        camera.close.assert_called_once_with()


class AudioTests(unittest.TestCase):
    def test_one_audio_thread_bounds_queue_and_stops_current_phrase(self):
        started = threading.Event()
        stopped = threading.Event()
        calls = []

        class Backend:
            class PlaybackStopped(Exception):
                pass

            def init_audio(self):
                calls.append("init")

            def phrase_startup(self):
                calls.append("startup")
                started.set()
                if not stopped.wait(2):
                    raise RuntimeError("Test audio did not receive stop")

            def phrase_happy(self):
                calls.append("happy")

            def stop_audio(self):
                stopped.set()

            def close_audio(self):
                calls.append("close")

        worker = AudioWorker(Backend())
        worker.start()
        try:
            self.assertTrue(worker.request("startup"))
            self.assertTrue(started.wait(1))
            self.assertTrue(worker.request("happy"))
            self.assertFalse(worker.request("happy"))
        finally:
            worker.close()
        self.assertEqual(calls, ["init", "startup", "close"])
        self.assertFalse(worker._thread.is_alive())

    def test_sound_module_import_does_not_initialize_mixer_and_stop_interrupts_phrase(self):
        pygame = Mock()
        pygame.mixer.get_init.return_value = None
        path = Path(__file__).resolve().parents[1] / "src" / "sound" / "soundTest.py"
        spec = importlib.util.spec_from_file_location("frida_test_audio", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"pygame": pygame, "numpy": Mock()}):
            spec.loader.exec_module(module)
        pygame.mixer.init.assert_not_called()
        module.init_audio()
        pygame.mixer.init.assert_called_once()
        pygame.mixer.get_init.return_value = (44100, -16, 1)
        module.stop_audio()
        pygame.mixer.stop.assert_called_once()
        with self.assertRaises(module.PlaybackStopped):
            module.pause(1000)
        module.close_audio()
        pygame.mixer.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
