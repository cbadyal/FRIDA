#!/usr/bin/env python3
"""
Robot Chatter Sound Engine — R2-D2 style beeps and warbles
Designed to play alongside servo arm movements on a Raspberry Pi.

Install: pip install pygame numpy --break-system-packages
"""

import pygame
import numpy as np
import random
import time

# ── Audio Setup ───────────────────────────────────────────────────────────────

SAMPLE_RATE = 44100
pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1, buffer=512)

# ── Sound Primitives ──────────────────────────────────────────────────────────

def make_beep(freq=440, duration_ms=120, volume=0.6, wave_type="sine"):
    """Generate a single tone. wave_type: sine, square, sawtooth."""
    n = int(SAMPLE_RATE * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, False)

    if wave_type == "sine":
        wave = np.sin(2 * np.pi * freq * t)
    elif wave_type == "square":
        wave = np.sign(np.sin(2 * np.pi * freq * t))
    elif wave_type == "sawtooth":
        wave = 2 * (t * freq - np.floor(t * freq + 0.5))

    # Soft attack/release envelope to avoid clicks
    fade = int(SAMPLE_RATE * 0.008)
    envelope = np.ones(n)
    envelope[:fade]  = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)

    samples = (wave * envelope * volume * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(samples)

def make_sweep(freq_start, freq_end, duration_ms=200, volume=0.6):
    """Glide between two frequencies — gives that classic R2 warble."""
    n = int(SAMPLE_RATE * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, False)
    freq  = np.linspace(freq_start, freq_end, n)
    phase = np.cumsum(2 * np.pi * freq / SAMPLE_RATE)
    wave  = np.sin(phase)

    fade = int(SAMPLE_RATE * 0.008)
    envelope = np.ones(n)
    envelope[:fade]  = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)

    samples = (wave * envelope * volume * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(samples)

def make_warble(freq=800, rate=18, duration_ms=300, depth=0.3, volume=0.6):
    """Rapid frequency modulation — the wobbly excited R2 sound."""
    n = int(SAMPLE_RATE * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, False)
    mod   = 1 + depth * np.sin(2 * np.pi * rate * t)
    phase = np.cumsum(2 * np.pi * freq * mod / SAMPLE_RATE)
    wave  = np.sin(phase)

    fade = int(SAMPLE_RATE * 0.008)
    envelope = np.ones(n)
    envelope[:fade]  = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)

    samples = (wave * envelope * volume * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(samples)

# ── Play Helpers ──────────────────────────────────────────────────────────────

def play(sound, gap_ms=30):
    sound.play()
    pygame.time.wait(int(sound.get_length() * 1000) + gap_ms)

def pause(ms):
    time.sleep(ms / 1000)

# ── Named Phrases ─────────────────────────────────────────────────────────────
# Each function is a distinct "voice line" — mix and match alongside
# your servo movements.

def phrase_happy():
    """Excited rising chirps — agreement or enthusiasm."""
    play(make_sweep(400, 900, 120))
    play(make_beep(900, 80))
    play(make_beep(1100, 100))
    play(make_sweep(800, 1400, 150))

def phrase_question():
    """Rising tone at the end — inquisitive."""
    play(make_beep(500, 100))
    play(make_beep(520, 80))
    pause(60)
    play(make_sweep(400, 1200, 250))

def phrase_grumpy():
    """Low descending tones — protest or complaint."""
    play(make_sweep(700, 300, 200))
    pause(40)
    play(make_beep(280, 180, wave_type="square"))
    play(make_sweep(400, 200, 150))

def phrase_excited():
    """Rapid warbling burst — can't contain the excitement."""
    play(make_warble(900,  rate=22, duration_ms=180, depth=0.4))
    play(make_beep(1200, 60))
    play(make_beep(1000, 60))
    play(make_warble(1100, rate=28, duration_ms=200, depth=0.5))
    play(make_beep(1300, 80))

def phrase_thinking():
    """Slow measured tones — processing something."""
    play(make_beep(600, 200))
    pause(120)
    play(make_beep(620, 160))
    pause(120)
    play(make_sweep(600, 750, 300))

def phrase_affirmative():
    """Two clean rising beeps — yes / confirmed."""
    play(make_beep(700, 100))
    pause(50)
    play(make_beep(1000, 150))

def phrase_negative():
    """Descending buzz — no / error."""
    play(make_sweep(600, 250, 300))
    play(make_beep(220, 200, wave_type="square"))

def phrase_startup():
    """Full boot sequence — good for script initialisation."""
    play(make_sweep(200, 600, 200))
    play(make_beep(600, 80))
    play(make_beep(800, 80))
    play(make_sweep(600, 1200, 250))
    pause(80)
    play(make_warble(1000, rate=15, duration_ms=300, depth=0.3))
    play(make_beep(1200, 120))
    play(make_beep(1400, 180))

def phrase_random():
    """Spontaneous chatter — good to sprinkle during arm movement."""
    random.choice([phrase_happy, phrase_question, phrase_negative, phrase_excited, phrase_thinking, phrase_grumpy])()

# ── Demo Sequence ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Robot chatter demo — Ctrl+C to stop\n")

    print("Startup...")
    phrase_startup()
    pause(400)

    print("Happy...")
    phrase_happy()
    pause(300)

    print("Question...")
    phrase_question()
    pause(300)

    print("Thinking...")
    phrase_thinking()
    pause(300)

    print("Excited!")
    phrase_excited()
    pause(300)

    print("Grumpy...")
    phrase_grumpy()
    pause(300)

    print("Affirmative.")
    phrase_affirmative()
    pause(300)

    print("Random chatter x4...")
    for _ in range(4):
        phrase_random()
        pause(random.randint(200, 500))

    print("\nDone.")
    pygame.mixer.quit()
