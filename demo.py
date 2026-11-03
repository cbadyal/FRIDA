#!/usr/bin/env python3
"""FRIDA's camera, head tracking, greeting wave, and chatter in one demo.

Arms stay still outside greetings. Positions are commanded values, not feedback;
the default starting pose assumes head=0 and right arm=60 degrees.
"""

import argparse
from contextlib import ExitStack
from dataclasses import replace
from enum import Enum
import logging
import math
import queue
import threading
import time

from src.camera.detection import CameraDetector
from src.servo.controller import SERVOS, UPDATE_HZ, ServoController
from src.servo.wave import RIGHT_ARM, WaveGesture


LOGGER = logging.getLogger(__name__)
HEAD = 0
# Match resetHead.py, without changing the older scripts' servo configuration.
DEMO_SERVOS = {
    HEAD: replace(SERVOS[HEAD], min_deg=0, rest_deg=0),
    RIGHT_ARM: SERVOS[RIGHT_ARM],
}


class BehaviorState(str, Enum):
    """Observable demo states; greeting includes concurrent head tracking."""

    STARTING = "STARTING"
    WAITING = "WAITING"
    CONFIRMING_FACE = "CONFIRMING_FACE"
    GREETING = "GREETING"
    TRACKING = "TRACKING"
    RETURNING_HOME = "RETURNING_HOME"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class AudioWorker:
    """Play one phrase at a time with room for only one pending phrase."""

    def __init__(self, backend=None):
        self.backend = backend
        self._phrases = queue.Queue(maxsize=1)
        self._stopped = threading.Event()
        self._thread = None

    def start(self):
        if self.backend is None:
            from src.sound import soundTest

            self.backend = soundTest
        self.backend.init_audio()
        self._thread = threading.Thread(target=self._run, name="frida-audio", daemon=True)
        self._thread.start()

    def request(self, phrase):
        if self._thread is None or self._stopped.is_set():
            return False
        if phrase not in ("startup", "happy"):
            raise ValueError(f"Unknown demo phrase: {phrase}")
        try:
            self._phrases.put_nowait(phrase)
            return True
        except queue.Full:
            return False

    def _run(self):
        while not self._stopped.is_set():
            try:
                phrase = self._phrases.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if not self._stopped.is_set():
                    getattr(self.backend, f"phrase_{phrase}")()
            except self.backend.PlaybackStopped:
                pass
            except Exception:
                LOGGER.exception("Audio playback failed; continuing without sound.")
                self._stopped.set()
            finally:
                self._phrases.task_done()

    def close(self):
        self._stopped.set()
        if self.backend is None:
            return
        self.backend.stop_audio()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                raise RuntimeError("Audio worker did not stop")
        self.backend.close_audio()


class DemoBehavior:
    """Decide when to track, greet once, and return the head to its base."""

    def __init__(
        self, controller, audio=None, *, confirm_seconds=0.3,
        lost_seconds=1.5, wave_cycles=3, invert_head=False,
    ):
        if not math.isfinite(confirm_seconds) or confirm_seconds < 0:
            raise ValueError("Face confirmation time must be finite and nonnegative")
        if not math.isfinite(lost_seconds) or lost_seconds <= confirm_seconds:
            raise ValueError("Face loss time must be finite and exceed confirmation time")
        self.controller = controller
        self.audio = audio
        self.confirm_seconds = confirm_seconds
        self.lost_seconds = lost_seconds
        self.direction = -1 if invert_head else 1
        self.wave = WaveGesture(controller, cycles=wave_cycles)
        self._lock = threading.RLock()
        self._candidate_since = None
        self._last_seen = None
        self._primary = None
        self._starting = True
        self.present = False
        self.greeted = False
        self._state = BehaviorState.STARTING
        self.error = None
        LOGGER.info("FRIDA state: %s", self._state.value)

    @property
    def state(self):
        """Read the current state safely from the camera or motion thread."""
        with self._lock:
            return self._state

    def _set_state(self, state):
        # Callers hold _lock. Log transitions only, rather than every frame.
        if state != self._state:
            LOGGER.info("FRIDA state: %s -> %s", self._state.value, state.value)
            self._state = state

    def _refresh_state(self):
        if self._state in (BehaviorState.STOPPED, BehaviorState.ERROR):
            return
        if self.controller.cancelled:
            state = BehaviorState.STOPPED
        elif self._starting:
            state = BehaviorState.STARTING
        elif self.wave.active:
            state = BehaviorState.GREETING
        elif self.present:
            state = BehaviorState.TRACKING
        elif self._candidate_since is not None:
            state = BehaviorState.CONFIRMING_FACE
        elif self.controller.is_moving(HEAD):
            state = BehaviorState.RETURNING_HOME
        else:
            state = BehaviorState.WAITING
        self._set_state(state)

    def stop(self):
        with self._lock:
            # Preserve the failure state through resource cleanup.
            if self._state != BehaviorState.ERROR:
                self._set_state(BehaviorState.STOPPED)

    def fail(self, error):
        with self._lock:
            self.error = str(error)
            self._set_state(BehaviorState.ERROR)

    def start(self):
        # Only the head receives a startup command. No arm positioning or idle.
        with self._lock:
            if self._state in (BehaviorState.STOPPED, BehaviorState.ERROR):
                return
            self.controller.set_target(HEAD, self.controller.servos[HEAD].rest_deg)
            self._refresh_state()

    def _expire_face(self, now):
        if self._last_seen is None or now - self._last_seen < self.lost_seconds:
            return
        self.present = False
        self.greeted = False
        self._candidate_since = None
        self._last_seen = None
        self._primary = None
        self.controller.set_target(HEAD, self.controller.servos[HEAD].rest_deg)
        LOGGER.info("Face absent; returning head to its 0-degree base.")

    def observe(self, faces, frame_width, now):
        """Consume one camera observation; never wait for servo movement."""
        with self._lock:
            if self._state in (BehaviorState.STOPPED, BehaviorState.ERROR):
                return None
            try:
                return self._observe(faces, frame_width, now)
            finally:
                self._refresh_state()

    def _observe(self, faces, frame_width, now):
        # The public observe() owns the lock and updates state on every return.
        self._expire_face(now)
        if self.controller.cancelled:
            return None
        if not faces:
            if not self.present:
                self._candidate_since = None
            return None

        if self._starting:
            return max(faces, key=lambda face: face.area)

        if self._primary is None:
            primary = max(faces, key=lambda face: face.area)
        else:
            # Favor the previous location instead of switching to each
            # frame's largest face. This is continuity, not identification.
            px, py = self._primary.center
            primary = min(
                faces, key=lambda face: (face.center[0] - px) ** 2
                + (face.center[1] - py) ** 2,
            )
        self._primary = primary
        self._last_seen = now
        if not self.present:
            if self._candidate_since is None:
                self._candidate_since = now
            if now - self._candidate_since < self.confirm_seconds:
                return primary
            self.present = True

        offset = (primary.center[0] - frame_width / 2) / (frame_width / 2)
        current = self.controller.current_angles[HEAD]
        # Proportional correction for a camera that turns with the head.
        # A central deadband avoids chasing small detection fluctuations.
        target = current if abs(offset) <= 0.1 else current + self.direction * offset * 30
        config = self.controller.servos[HEAD]
        target = max(config.min_deg, min(config.max_deg, target))
        self.controller.set_target(HEAD, target)

        if not self.greeted and self.wave.start():
            self.greeted = True
            LOGGER.info("Face confirmed; greeting once and continuing to track.")
            if self.audio is not None:
                self.audio.request("happy")
        return primary

    def tick(self, now, elapsed):
        with self._lock:
            if self._state in (BehaviorState.STOPPED, BehaviorState.ERROR):
                return
            if self.controller.cancelled:
                self._refresh_state()
                return
            self._expire_face(now)
            self.wave.update(now)
            self.controller.update(elapsed)
            if self._starting and not self.controller.is_moving(HEAD):
                self._starting = False
            self._refresh_state()

    @property
    def status(self):
        with self._lock:
            return f"State: {self._state.value}"


class MotionWorker:
    """Keep servo updates independent of camera capture and audio playback."""

    def __init__(self, behavior):
        self.behavior = behavior
        self.error = None
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="frida-motion", daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        previous = time.monotonic()
        try:
            while not self._stopped.wait(1.0 / UPDATE_HZ):
                now = time.monotonic()
                self.behavior.tick(now, now - previous)
                previous = now
        except Exception as exc:
            self.error = exc
            self.behavior.fail(exc)
            try:
                self.behavior.controller.emergency_stop()
            except Exception:
                LOGGER.exception("Could not disable PWM after motion failed")

    def check(self):
        if self.error is not None:
            raise RuntimeError(f"Motion worker failed: {self.error}") from self.error

    def close(self):
        self._stopped.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                raise RuntimeError("Motion worker did not stop")


def run_demo(camera, controller, audio=None, *, preview=True, **behavior_options):
    """Own the resources so startup errors, Q, and Ctrl+C all clean up."""
    behavior = None
    try:
        with ExitStack() as cleanup:
            cleanup.callback(controller.close)
            cleanup.callback(camera.close)
            if audio is not None:
                cleanup.callback(audio.close)
            behavior = DemoBehavior(controller, audio, **behavior_options)
            motion = MotionWorker(behavior)
            cleanup.callback(motion.close)
            cleanup.callback(controller.emergency_stop)
            camera.start()
            if audio is not None:
                try:
                    audio.start()
                except Exception as exc:
                    LOGGER.warning("Audio unavailable (%s); continuing without sound.", exc)
            behavior.start()
            motion.start()
            if audio is not None:
                audio.request("startup")
            LOGGER.info("Demo running. Q quits, D toggles debug, Ctrl+C stops.")
            debug = True
            while True:
                motion.check()
                frame, faces = camera.read()
                motion.check()
                primary = behavior.observe(faces, frame.shape[1], time.monotonic())
                if preview:
                    key = camera.preview(frame, faces, primary, behavior.status, debug)
                    if key == ord("q"):
                        return
                    if key == ord("d"):
                        debug = not debug
    except Exception as exc:
        if behavior is not None:
            behavior.fail(exc)
        raise
    finally:
        if behavior is not None:
            behavior.stop()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-sound", action="store_true", help="Run without audio")
    parser.add_argument("--no-preview", action="store_true", help="Run without a camera window")
    parser.add_argument("--invert-head", action="store_true", help="Reverse head tracking direction")
    parser.add_argument("--wave-cycles", type=int, default=3)
    parser.add_argument("--confirm-seconds", type=float, default=0.3)
    parser.add_argument("--lost-seconds", type=float, default=1.5)
    parser.add_argument(
        "--head-start-angle", type=float, default=0,
        help="Known starting head command, 0-180 (default: assumes 0); not measured",
    )
    parser.add_argument(
        "--arm-start-angle", type=float, default=60,
        help="Known right-arm command, 60-120 (default: assumes 60); not measured",
    )
    args = parser.parse_args(argv)
    for name, channel in (("head_start_angle", HEAD), ("arm_start_angle", RIGHT_ARM)):
        value = getattr(args, name)
        config = DEMO_SERVOS[channel]
        if not math.isfinite(value) or not config.min_deg <= value <= config.max_deg:
            parser.error(f"--{name.replace('_', '-')} must be within {config.min_deg:g}-{config.max_deg:g}")
    if args.wave_cycles < 1:
        parser.error("--wave-cycles must be positive")
    if not math.isfinite(args.confirm_seconds) or args.confirm_seconds < 0:
        parser.error("--confirm-seconds must be finite and nonnegative")
    if not math.isfinite(args.lost_seconds) or args.lost_seconds <= args.confirm_seconds:
        parser.error("--lost-seconds must be finite and greater than --confirm-seconds")
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        controller = ServoController(servos=DEMO_SERVOS, motion_profile="smootherstep")
        controller.current_angles[HEAD] = args.head_start_angle
        controller.current_angles[RIGHT_ARM] = args.arm_start_angle
        run_demo(
            CameraDetector(), controller, None if args.no_sound else AudioWorker(),
            preview=not args.no_preview, confirm_seconds=args.confirm_seconds,
            lost_seconds=args.lost_seconds, wave_cycles=args.wave_cycles,
            invert_head=args.invert_head,
        )
    except KeyboardInterrupt:
        LOGGER.info("Stopped; PWM disabled.")
        return 130
    except Exception as exc:
        LOGGER.error("Demo stopped: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
