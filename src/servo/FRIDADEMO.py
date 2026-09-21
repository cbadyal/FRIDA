import sys
sys.path.append("/home/fridapi/Desktop/Sound Scripts")   # wherever robot_chatter.py lives
import soundTest

import time
import sys
import smbus2

# ── PCA9685 Setup ─────────────────────────────────────────────────────────────

PCA9685_ADDR = 0x40
I2C_BUS      = 1
PWM_FREQ     = 50
OSC_CLOCK    = 25_000_000

PULSE_MIN_US = 500    # µs at 0°
PULSE_MAX_US = 2500   # µs at 180°

# ── Per-Servo Configuration ───────────────────────────────────────────────────
# min_deg / max_deg     — safe range for this servo
# up_step, up_delay     — speed moving up   (increasing angle)
# down_step, down_delay — speed moving down (decreasing angle)
# Smaller step OR larger delay = slower movement.
# Servos 1 & 2 are arm servos — downswing is slower to reduce momentum jerk.

SERVOS = {
    0: {"name": "Servo 0", "min_deg": 0, "max_deg": 180,
        "up_step": 2, "up_delay": 10, "down_step": 2, "down_delay": 10},
    1: {"name": "Servo 1", "min_deg": 0, "max_deg": 90,
        "up_step": 2, "up_delay": 15, "down_step": 1, "down_delay": 25},
    2: {"name": "Servo 2", "min_deg": 60, "max_deg": 120,
        "up_step": 2, "up_delay": 15, "down_step": 1, "down_delay": 25},
    3: {"name": "Servo 3", "min_deg": 0, "max_deg": 90,
        "up_step": 2, "up_delay": 10, "down_step": 2, "down_delay": 10},
}

# ── PCA9685 Driver ────────────────────────────────────────────────────────────

class PCA9685:
    def __init__(self):
        try:
            self.bus = smbus2.SMBus(I2C_BUS)
        except Exception as e:
            print(f"[ERROR] Cannot open I2C bus: {e}")
            sys.exit(1)
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0x00)
        time.sleep(0.005)
        prescale = round(OSC_CLOCK / (4096 * PWM_FREQ)) - 1
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0x10)
        self.bus.write_byte_data(PCA9685_ADDR, 0xFE, prescale)
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0x00)
        time.sleep(0.005)
        self.bus.write_byte_data(PCA9685_ADDR, 0x00, 0xA0)

    def set_angle(self, channel, angle):
        pulse_us = PULSE_MIN_US + (PULSE_MAX_US - PULSE_MIN_US) * angle / 180
        off_tick = round(pulse_us / (1_000_000 / PWM_FREQ) * 4096)
        base = 0x06 + 4 * channel
        self.bus.write_i2c_block_data(PCA9685_ADDR, base,
            [0, 0, off_tick & 0xFF, off_tick >> 8])

    def close(self):
        self.bus.close()

# ── Smooth Movement ───────────────────────────────────────────────────────────

current_angle = {}     # Tracks last known angle per channel

def move_slow(pca, ch, target):
    """Move a servo smoothly using per-servo directional speed settings."""
    cfg      = SERVOS[ch]
    start    = current_angle.get(ch, target)
    going_up = target > start

    step_deg = cfg["up_step"]  if going_up else cfg["down_step"]
    delay_ms = cfg["up_delay"] if going_up else cfg["down_delay"]
    step     = step_deg if going_up else -step_deg

    for angle in range(int(start), int(target), step):
        pca.set_angle(ch, angle)
        time.sleep(delay_ms / 1000)
    pca.set_angle(ch, target)   # Land exactly on target
    current_angle[ch] = target

# ── Test Functions ────────────────────────────────────────────────────────────

def test_servo(pca, ch):
    cfg = SERVOS[ch]
    lo  = cfg["min_deg"]
    hi  = cfg["max_deg"]
    mid = (lo + hi) // 2

    print(f"\nTesting {cfg['name']} | range: {lo}° - {hi}°")

    print(f"  Minimum ({lo}°)")
    move_slow(pca, ch, lo);   time.sleep(1.0)

    print(f"  Maximum ({hi}°)")
    move_slow(pca, ch, hi);   time.sleep(1.0)

    print(f"  Centre ({mid}°)")
    move_slow(pca, ch, mid);  time.sleep(1)
    
    print(f" Back to minimum ({lo}°)")
    move_slow(pca, ch, lo); time.sleep(0.5)

    print(f"  Done")
    
def demo(pca):
	try:
		
		soundTest.phrase_startup()
		
		# head jitter
		move_slow(pca, 0, 30); time.sleep(0.5)
		move_slow(pca, 0, 0); time.sleep(0.5)
		move_slow(pca, 0, 30); time.sleep(0.5)
		move_slow(pca, 0, 0); time.sleep(0.5)
		
		# arms rise
		#move_slow(pca, 1, 90); time.sleep(0.5)
		move_slow(pca, 2, 120); time.sleep(3)
		
		# move arm and head jitter again
		#move_slow(pca, 0, 90); time.sleep(0.5)
		#move_slow(pca, 0, 180); time.sleep(0.5)
		
		# lower arms
		#move_slow(pca, 1, 0); time.sleep(0.5)
		move_slow(pca, 0, 0); time.sleep(0.5)
		move_slow(pca, 2, 60); time.sleep(3)
	except KeyboardInterrupt:
		print("\nAborted")
    

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pca = PCA9685()

    try:
       demo(pca) 

    except KeyboardInterrupt:
        print("\nAborted.")

    finally:
        print("Closing I2C bus.")
        pca.close()

if __name__ == "__main__":
    main()
