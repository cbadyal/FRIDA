# F.R.I.D.A.

F.R.I.D.A. is the animatronic mascot for Cal Poly's Liberal Arts and Engineering Studies (LAES) program. She is a student-built interactive droid designed to welcome visitors, represent the creative technical spirit of LAES, and support demonstrations in the Expressive Technology Studio.

FRIDA is currently an active student development project. The long-term goal is to make her a reliable, expressive, and original LAES character who can notice visitors, move in response, play sounds, answer questions about the department, and participate smoothly in demos without manual resets.

## Project Goals

- Build a memorable interactive mascot for the LAES classroom, lab, and ETS demo.
- Improve FRIDA's responsiveness so she can interact with visitors in a timely way.
- Coordinate head movement, arm gestures, lighting, audio, camera tracking, and conversational behavior.
- Increase reliability and power efficiency on the Raspberry Pi-based control system.
- Continue developing FRIDA as an original LAES character separate from outside intellectual property.
- Leave the system understandable for future LAES students to maintain and extend.

## Current State

FRIDA is partially operational and under active improvement.

Current capabilities include:

- Raspberry Pi control computer
- PCA9685 servo driver over I2C
- Four servo channels for head, arms, and claw movement
- Generated robot chatter through speakers
- Camera-based face detection and head tracking prototype
- Idle and demo motion scripts
- Shared safety-limited servo controller for smoother motion
- A consolidated `demo.py` combining Picamera2 face detection, head tracking, greeting waves, and chatter

Known limitations from the current project brief:

- The consolidated face-tracking demo still needs validation on FRIDA's Raspberry Pi and hardware.
- Face detection can become unreliable with large groups or brief occlusions.
- The camera currently needs a better physical housing and cable protection.
- Power limits can cause lag during high-stress behavior, especially conversational responses.
- The claw is currently being redesigned and is not used by the consolidated demo.
- Hardware and software still need tighter integration before FRIDA can run reliably in demos.

## Hardware Overview

FRIDA's current hardware includes:

- Raspberry Pi brain
- PCA9685 PWM servo controller at I2C address `0x40`
- Four configured servo channels, with the following use in the current `demo.py`:

| Channel | Function | Demo command range | Base / default start | Demo behavior |
| --- | --- | --- | --- | --- |
| `0` | Head swivel | `0-180 deg` | `0 deg` | Tracks faces; returns to base when no face is present |
| `1` | Left arm | Not commanded | Not commanded | Stays still |
| `2` | Right arm / elbow | `60-120 deg` | `60 deg` | Waves between `85-105 deg`, then returns to its starting angle |
| `3` | Claw | Not commanded | Not commanded | Under redesign; stays still |

These are the current demo's configured command angles, not measured positions. Its head profile matches `resetHead.py`, with a **0-degree base**. Only the head (`0`) and right arm (`2`) receive movement commands.

The controller address is a default in `src/servo/controller.py`: `PCA9685_ADDR = 0x40`, on `I2C_BUS = 1`. The Raspberry Pi sends commands to that board address, then selects an output channel for the desired servo. The board address and servo channel numbers are different settings. The address is not automatically detected; the driver also accepts an explicit address through `PCA9685(address=...)`.

Additional hardware described in the brief:

- Microphone
- Bluetooth speaker or speaker output
- Head lights
- Camera module
- Westinghouse iGen160s portable power station, connected through an AC outlet and FRIDA's wall-plug power adapter
- Rolling base

Before running motion scripts, make sure FRIDA is physically supported, clear of people and objects, and powered from the Westinghouse iGen160s AC outlet through FRIDA's existing power adapter.

The [iGen160s specifications](https://westinghouse.com/products/igen160s-portable-power-station) list 120 V AC outlets. The wall-plug adapter converts that to the DC voltage used by the connected electronics. The adapter's output voltage and current rating still need to be recorded; `5 V` has not yet been confirmed as FRIDA's adapter output. The station's other USB and DC output ratings do not establish the voltage supplied through this AC-adapter connection.

## Repository Layout

```text
demo.py                 Main interactive demo: camera, tracking, greeting, and sound
face_detection.py       Standalone camera-only preview using the shared detector
src/
  camera/
    detection.py       Reusable Picamera2 capture and OpenCV face detection
    faceTrack.py       Face detection, head tracking, and arm reaction prototype
  servo/
    controller.py      Shared PCA9685 and safe servo motion controller
    awake.py           Startup gesture
    wave.py            Right-arm greeting that returns to the starting position
    resetHead.py       Return the head to its base position
    FRIDADEMO.py       Older standalone short demo sequence
    slowIdle.py        Repeating head, arm, claw, and chatter routine (unused by demo.py)
    servoIdle.py       Runs slowIdle.py under the older filename
    GPTtalkIdle.py     Preexisting quiet motion loop; no GPT or speech integration
  sound/
    soundTest.py       Generated robot chatter sound engine
    soundStartup.py    Legacy startup-sound helper; unused and needs repair
```

## Raspberry Pi Setup

These scripts are intended to run on FRIDA's Raspberry Pi with I2C enabled.

1. Enable I2C on the Pi:

```bash
sudo raspi-config
```

Use `Interface Options` -> `I2C` -> enable.

2. Install system packages commonly needed for the current scripts:

```bash
sudo apt update
sudo apt install python3-pip python3-picamera2 python3-opencv opencv-data python3-numpy python3-pygame python3-smbus2 i2c-tools rpicam-apps gstreamer1.0-tools
```

3. Install Python packages if they are not already available:

```bash
python3 -m pip install smbus2 numpy pygame opencv-python
```

4. Confirm the PCA9685 is visible:

```bash
i2cdetect -y 1
```

Look for address `40`.

## Running FRIDA

Run commands from the repository root on the Raspberry Pi.

### Consolidated interactive demo

```bash
python3 demo.py
```

This command opens the camera directly through Picamera2; it does not need a separate `rpicam-vid` process or another sound script.

Behavior:

- Play the startup phrase and return the head to the **0-degree base**.
- Wait at the base with no idle gestures or startup arm raise.
- Confirm a face for `0.3` seconds, then wave the right arm and play a greeting phrase once.
- Continue tracking the selected face while the arm waves, then return the arm to its starting angle.
- Wait through brief missed detections. After `1.5` seconds with no detected face, return the head to its base and allow another greeting when a face appears.
- Keep both arms still outside the greeting wave and its return. The left arm and claw are never moved by this demo.

Greetings are once per continuous face-presence period, not once per recognized person. The detector initially selects the largest face and then favors the previous face location. It does not identify people. A short disappearance or a new face entering an occupied scene does not trigger another wave.

Starting positions are **supplied command angles, not measured positions**. The default command assumes the head is already at `0` degrees and the right arm at `60`. If their known starting positions differ, supply them, for example:

```bash
python3 demo.py --head-start-angle 150 --arm-start-angle 60
```

The head returns to zero before tracking begins. The demo does not reposition the arm at startup; each wave returns it to the supplied starting angle. Use the actual known values so the first commanded movement starts from the correct position.

Useful options:

- `--no-sound`: run without audio or importing the audio packages.
- `--no-preview`: run without a camera window; stop with `Ctrl+C`.
- `--invert-head`: reverse the tracking direction if required by the camera/servo mounting.
- `--wave-cycles 2`: change the number of waves (default: `3`).
- `--confirm-seconds 0.3` and `--lost-seconds 1.5`: adjust face-presence timing. Loss time must exceed confirmation time.

In the camera window, `Q` quits and `D` toggles debug text. `Ctrl+C`, quitting, and errors disable PWM and close the motion worker, audio worker, camera, and I2C bus. Stopping interrupts movement immediately; it does not force a return gesture. If audio cannot initialize, the demo logs a warning and continues without sound.

The demo exposes its current behavior as `behavior.state`, a `BehaviorState` enum. Read `behavior.state.value` for the state name or compare it with, for example, `BehaviorState.TRACKING`. The camera debug overlay displays the same state, and the terminal logs timestamped transitions once per change, including with `--no-preview`:

```text
14:30:00 INFO: FRIDA state: STARTING
14:30:00 INFO: FRIDA state: STARTING -> WAITING
14:30:04 INFO: FRIDA state: WAITING -> CONFIRMING_FACE
14:30:04 INFO: FRIDA state: CONFIRMING_FACE -> GREETING
14:30:17 INFO: FRIDA state: GREETING -> TRACKING
```

| State | Meaning |
| --- | --- |
| `STARTING` | Initializing the demo and returning the head to base |
| `WAITING` | No confirmed face; the head has reached base |
| `CONFIRMING_FACE` | Checking that a face remains present long enough to greet |
| `GREETING` | The wave is in progress, including the arm's return and final hold |
| `TRACKING` | A confirmed face is present and the greeting has finished |
| `RETURNING_HOME` | The face has been lost and the head is moving back to base |
| `STOPPED` | The behavior was cancelled or the demo exited normally |
| `ERROR` | A camera, motion, or other fatal demo error occurred |

These states describe the existing behavior. Head tracking continues during `GREETING`; if a face disappears during the wave, that state remains until the gesture finishes. Brief missed detections retain the current presence state until the face-loss timeout. Audio unavailability is logged separately while the demo continues. Fatal errors are retained in `behavior.error`, and cleanup preserves `ERROR` instead of replacing it with `STOPPED`. Read the state for debugging; changing motion still goes through the behavior and servo controller.

Camera-only check:

```bash
python3 face_detection.py
```

### Existing standalone scripts

The following scripts retain their previous behavior. `FRIDADEMO.py` remains the older demo; it does not forward to `demo.py`.

Startup gesture:

```bash
python3 src/servo/awake.py
```

Wave the right arm three times, then return it to its starting position:

```bash
python3 src/servo/wave.py --start-angle 60
```

Supply the arm's actual known starting angle (60-120 degrees); the script cannot measure it. Use `--cycles 2` to change the number of waves. `Ctrl+C` stops the gesture and disables PWM on all channels.

Return the head to the older startup script's base command (0 deg), ramping from a supplied known starting angle and allowing two seconds to settle before disabling PWM. For a known starting angle of 150 in the calibrated command scale:

```bash
python3 src/servo/resetHead.py --start-angle 150
```

The script does not measure the starting angle; supply the actual known value.

Older short demo (includes its original arm raise):

```bash
python3 src/servo/FRIDADEMO.py
```

Calm idle motion (includes arm and claw movement; not used by `demo.py`):

```bash
python3 src/servo/slowIdle.py
```

`servoIdle.py` is a compatibility launcher for `slowIdle.py`; both commands run the same routine.

Quiet motion intended to accompany speaking:

```bash
python3 src/servo/GPTtalkIdle.py
```

`GPTtalkIdle.py` already existed in the old `fridapi` code. It moves the head and arms without generating chatter. It does not call GPT, listen to a microphone, or generate speech, and it is not used by the consolidated demo.

Sound test:

```bash
python3 src/sound/soundTest.py
```

The old `soundStartup.py` was intended to play only `soundTest.phrase_startup()`. It still contains a hardcoded Pi desktop path and calls `phrase_startup()` without the module prefix, so it needs repair before standalone use. The consolidated demo calls the startup phrase through its audio worker and does not use this helper.

Face tracking prototype uses two terminals.

Terminal 1 starts the camera stream:

```bash
rpicam-vid --codec mjpeg --width 640 --height 480 --framerate 30 --timeout 0 --nopreview -o udp://127.0.0.1:5000
```

Terminal 2 starts tracking:

```bash
python3 src/camera/faceTrack.py
```

Controls:

- `Q` quits the face tracker.
- `D` toggles the debug overlay.
- `Ctrl+C` stops servo scripts and triggers shutdown handling.

## Safety Notes

- Keep hands, cables, and loose clothing away from the head, arms, and claw while scripts are running.
- Start with low-risk scripts such as `awake.py` before running longer idle or tracking behavior.
- Watch the first full motion cycle after any hardware adjustment.
- If movement looks unsafe, press `Ctrl+C` immediately.
- The shared servo controller disables PWM and closes the I2C bus when scripts exit normally.
- Recalibrate servo limits after replacing motors, linkages, power hardware, or the servo driver.

## Development Priorities

Near-term work called out by the brief:

- Improve power reliability and reduce lag during conversation.
- Integrate face tracking into normal FRIDA behavior.
- Test the face tracker with the new camera.
- Design a camera housing that looks intentional and protects the cable.
- Redesign the claw and recalibrate it before enabling claw motion.
- Coordinate speech, sound effects, lights, head turns, arm gestures, and claw motion.
- Build a dependable ETS demo mode that runs without restarts.
- Continue shaping FRIDA's original personality and backstory as the LAES mascot.

## Character Direction

FRIDA began as a student-built droid project inspired by science fiction and has grown into an LAES mascot with her own identity. Her current story positions her as an unusual machine discovered abroad, rebuilt in the LAES lab, and inhabited by a curious consciousness that now treats the program as home.

Her personality should feel:

- Welcoming
- Curious
- Playful
- Helpful
- Knowledgeable about LAES
- A little surreal in a way that fits the lab

She especially enjoys older robot and science fiction films, libraries, databases, Japanese mythology, soil chemistry, worms, and quantum physics puzzles.

## Contributing

Run the automated checks without connecting the robot:

```bash
python3 -m unittest discover -s tests -v
```

These checks use simulated servo hardware, face observations, and time. They cover greeting timing, face loss, stationary arms while waiting, concurrent tracking and waving, audio shutdown, and resource cleanup. They do not replace camera and motion validation on the Pi.

FRIDA is meant to be carried forward by generations of LAES students. When adding to the project:

- Keep scripts readable for the next student group.
- Document hardware changes and calibration values.
- Prefer shared control code over one-off servo logic.
- Test motion with the robot physically supervised.
- Avoid hardcoding paths that only work on one user's desktop when possible.
- Preserve FRIDA's goal: a joyful, memorable, technically impressive LAES mascot.
