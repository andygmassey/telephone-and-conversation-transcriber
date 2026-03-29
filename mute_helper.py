#!/usr/bin/env python3
"""Phone detector - detects phone activity, releases device for transcription"""
import subprocess
import time
import os
import json
import numpy as np
import threading

# Load config to get phone card number
CONFIG_PATH = os.path.expanduser('~/gramps-transcriber/config.json')
try:
    with open(CONFIG_PATH) as f:
        _config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    _config = {}

PHONE_CARD = _config.get('phone_card', 0)
STATUS_FILE = "/tmp/phone_muted"
ENERGY_THRESHOLD = 0.003
ACTIVE_SECONDS = 1

def card_exists(card_num):
    env = dict(os.environ, LC_ALL='C')
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True, env=env)
    return f"card {card_num}:" in result.stdout

def write_status(active):
    try:
        with open(STATUS_FILE, "w") as f:
            f.write("1" if active else "0")
    except:
        pass

def read_status():
    try:
        with open(STATUS_FILE, "r") as f:
            return f.read().strip() == "1"
    except:
        return False

# Watchdog notifier
def watchdog_thread():
    try:
        import systemd.daemon
        while True:
            systemd.daemon.notify("WATCHDOG=1")
            time.sleep(20)
    except:
        pass

def main():
    # Start watchdog thread
    threading.Thread(target=watchdog_thread, daemon=True).start()

    try:
        import systemd.daemon
        systemd.daemon.notify("READY=1")
    except:
        pass

    import sounddevice as sd

    while True:
        # Check if phone device exists
        if not card_exists(PHONE_CARD):
            print(f"Phone recorder (card {PHONE_CARD}) not found, waiting...", flush=True)
            write_status(False)
            time.sleep(10)
            continue

        # Phase 1: Monitor for phone activity
        print("Waiting for phone activity...", flush=True)
        write_status(False)
        active_count = 0
        phone_detected = False

        def detect_callback(indata, frames, time_info, status):
            nonlocal active_count, phone_detected
            energy = np.sqrt(np.mean(indata**2))
            if energy > ENERGY_THRESHOLD:
                active_count += 1
                if active_count >= ACTIVE_SECONDS * 10:
                    phone_detected = True
            else:
                active_count = max(0, active_count - 1)

        try:
            with sd.InputStream(device=PHONE_CARD, channels=1, samplerate=8000,
                               blocksize=800, callback=detect_callback):
                while not phone_detected:
                    time.sleep(0.1)
        except Exception as e:
            print(f"Detection error: {e}", flush=True)
            time.sleep(2)
            continue

        # Phase 2: Phone active - device is now released
        print("Phone ACTIVE - device released, waiting for ALSA...", flush=True)
        time.sleep(0.5)

        # Signal caption_app
        print("Signaling caption_app...", flush=True)
        write_status(True)

        # Phase 3: Wait for call to end
        wait_start = time.time()
        while read_status():
            time.sleep(1)
            if time.time() - wait_start > 300:
                print("Timeout waiting for call end, resetting", flush=True)
                break

        print("Phone ENDED - resuming monitor", flush=True)
        time.sleep(2)

if __name__ == "__main__":
    main()
