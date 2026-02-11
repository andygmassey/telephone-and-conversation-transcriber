#!/usr/bin/env python3
"""Auto-mute room mic when phone is active - releases device for caption_app"""
import subprocess
import time
import sys
import os

PHONE_CARD = 0
ROOM_CARD = 1
STATUS_FILE = "/tmp/phone_muted"
ENERGY_THRESHOLD = 0.01
ACTIVE_SECONDS = 2
SILENT_SECONDS = 5

def card_exists(card_num):
    """Check if an audio card exists"""
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    return f"card {card_num}:" in result.stdout

def set_room_mic(level):
    subprocess.run(["amixer", "-c", str(ROOM_CARD), "set", "Mic", level],
                   capture_output=True)

def write_status(muted):
    try:
        with open(STATUS_FILE, "w") as f:
            f.write("1" if muted else "0")
    except:
        pass

def read_status():
    try:
        with open(STATUS_FILE, "r") as f:
            return f.read().strip() == "1"
    except:
        return False

def cleanup():
    """Ensure mic is unmuted on exit"""
    print("Cleaning up - unmuting room mic", flush=True)
    set_room_mic("100%")
    write_status(False)

def main():
    # Check if phone recorder exists
    if not card_exists(PHONE_CARD):
        print(f"Phone recorder (card {PHONE_CARD}) not found - exiting gracefully", flush=True)
        write_status(False)
        try:
            import systemd.daemon
            systemd.daemon.notify("READY=1")
        except:
            pass
        while True:
            time.sleep(3600)

    # Check if room mic exists
    if not card_exists(ROOM_CARD):
        print(f"Room mic (card {ROOM_CARD}) not found - exiting gracefully", flush=True)
        while True:
            time.sleep(3600)

    print(f"Monitoring phone (card {PHONE_CARD}), controlling room mic (card {ROOM_CARD})", flush=True)

    try:
        import systemd.daemon
        systemd.daemon.notify("READY=1")
    except:
        pass

    import atexit
    atexit.register(cleanup)

    import signal
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    import sounddevice as sd
    import numpy as np

    while True:
        # Phase 1: Monitor for phone activity
        muted = False
        active_count = 0
        silent_count = 0
        phone_active = False

        def callback(indata, frames, time_info, status):
            nonlocal muted, active_count, silent_count, phone_active

            energy = np.sqrt(np.mean(indata**2))

            if energy > ENERGY_THRESHOLD:
                active_count += 1
                silent_count = 0
                if not muted and active_count >= ACTIVE_SECONDS * 10:
                    print("Phone active - muting room mic, releasing device for captions", flush=True)
                    set_room_mic("0%")
                    write_status(True)
                    muted = True
                    phone_active = True
            else:
                silent_count += 1
                active_count = 0

        try:
            print("Starting phone monitor...", flush=True)
            with sd.InputStream(device=PHONE_CARD, channels=1, samplerate=8000,
                               blocksize=800, callback=callback):
                while not phone_active:
                    time.sleep(0.1)

            # Phone became active - stream is now closed, device released
            print("Device released - waiting for call to end...", flush=True)

            # Phase 2: Wait for caption_app to signal call ended
            # (caption_app will write 0 to status file when it detects silence)
            while read_status():
                time.sleep(1)

            # Call ended - unmute room mic
            print("Call ended - unmuting room mic, resuming monitor", flush=True)
            set_room_mic("100%")
            time.sleep(2)  # Brief pause before resuming

        except Exception as e:
            print(f"Error monitoring phone: {e}", flush=True)
            cleanup()
            time.sleep(5)


if __name__ == "__main__":
    main()
