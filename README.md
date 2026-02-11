# Telephone and Conversation Transcriber

My elderly father is extremely deaf and struggles to hear people, particularly on the landline phone. So I built this — a Raspberry Pi with a 10" touchscreen that sits next to his phone and transcribes conversations in near real-time, so he can read what people are saying.

It picks up both phone calls (via a USB telephone recorder tapped into the landline) and in-room conversation (via a USB conference microphone), and displays live captions in large, clear text. When nobody's talking it shows a nice flip-clock. The whole thing runs headless as a systemd service — plug it in and it just works.

![The transcriber in action — live captions on a 10" touchscreen while Dad's on the phone](photo.jpg)

## Features

- **Live Captions** - Real-time speech-to-text displayed on a touchscreen
- **Dual Audio Sources** - Transcribes both landline phone calls and in-room conversation
- **Online/Offline Modes** - Deepgram (cloud, high accuracy) with automatic Vosk/Whisper fallback (offline)
- **Flip-Clock Display** - Split-flap style clock when idle, auto-dims at night
- **Touch Controls** - Font size (S/M/L), colour schemes, drag-to-scroll history
- **Auto Phone Detection** - Automatically switches to phone audio when a call begins
- **Bulletproof Reliability** - Watchdog timers, auto-restart, health monitoring

## Hardware

| Component | Model | Purpose |
|-----------|-------|---------|
| Computer | Raspberry Pi 5 (8GB) | Main processor |
| Phone Recorder | Fi3001A USB (04d9:2832) | Captures landline calls via RJ-11 |
| Room Microphone | TONOR G11 (0d8c:0134) | Captures in-room conversation |
| Display | 10" Touchscreen (1280x800) | Shows live captions |

## Software Stack

Two speech recognition configurations available on separate branches:

| Branch | Engine | Accuracy | Latency | Offline |
|--------|--------|----------|---------|---------|
| **main** | Deepgram / faster-whisper / Vosk | ~90-95% / ~85% / ~75% | ~200ms / ~3s / ~300ms | No / Yes / Yes |
| **azure-test** | Azure Speech / Vosk | ~90-95% / ~75% | ~200ms / ~300ms | No / Yes |

### Dependencies

- Python 3.13
- PyQt6 (fullscreen display with touch scroll)
- Deepgram / Azure Cognitive Services Speech SDK / Vosk / faster-whisper
- systemd user services with watchdog

## Quick Start

### 1. Set up Python environment

```bash
python3 -m venv ~/gramps-env
source ~/gramps-env/bin/activate
pip install pyqt6 vosk websocket-client sounddevice numpy
# Optional: pip install faster-whisper scipy
# Optional: pip install azure-cognitiveservices-speech
```

### 2. Download Vosk model (offline fallback)

```bash
cd ~
wget https://alphacephei.com/vosk/models/vosk-model-small-en-gb-0.15.zip
unzip vosk-model-small-en-gb-0.15.zip
mv vosk-model-small-en-gb-0.15 vosk-uk
```

### 3. Configure credentials

```bash
cp credentials.py.example credentials.py
# Edit credentials.py with your API key (Deepgram or Azure depending on branch)
```

### 4. Install systemd services

```bash
mkdir -p ~/.config/systemd/user
cp systemd/caption.service ~/.config/systemd/user/
cp systemd/gramps-mute.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now caption gramps-mute
```

### 5. Install system watchdogs (optional, requires root)

```bash
sudo cp scripts/caption-watchdog.sh /usr/local/bin/
sudo cp scripts/display-watchdog.sh /usr/local/bin/
sudo cp scripts/network-watchdog.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/*-watchdog.sh
sudo cp systemd/caption-watchdog.service systemd/caption-watchdog.timer /etc/systemd/system/
sudo cp systemd/display-watchdog.service systemd/display-watchdog.timer /etc/systemd/system/
sudo cp systemd/network-watchdog.service systemd/network-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now caption-watchdog.timer display-watchdog.timer network-watchdog.timer
```

## Usage

### Display Modes

**Clock Mode (idle):** Split-flap style clock appears after 90 seconds of silence. Auto-dims between 22:00-07:00.

**Caption Mode (active):** Automatically switches when speech is detected.

### Touch Controls

- **S / M / L** - Change font size
- **Colour circles** - Switch colour scheme (white/black, black/white, yellow/black, green/black)
- **ONLINE / OFFLINE** - Toggle transcription engine
- **Drag** - Scroll through caption history
- **Escape** - Exit application

### Phone Calls

When a landline call is detected via the Fi3001A USB recorder, the system automatically:
1. Switches to phone audio input
2. Shows a phone icon in the caption bar
3. Switches back to room mic after 10 seconds of silence

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│ Fi3001A Phone   │     │ TONOR G11 Mic   │
│ (hw:0, 8kHz)    │     │ (hw:1, 16kHz)   │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
              ┌──────▼──────┐
              │  Deepgram   │  ← online (main)
              │     OR      │
              │faster-whisper│  ← offline fallback
              │     OR      │
              │    Vosk     │  ← offline fallback
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │   PyQt6     │
              │  Fullscreen │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │ 10" Touch   │
              │   Screen    │
              └─────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `caption_app.py` | Main application - UI, transcription, phone switching |
| `mute_helper.py` | Phone activity detector - monitors USB recorder |
| `credentials.py.example` | Template for API credentials |
| `scripts/` | System watchdog scripts |
| `systemd/` | Service files for auto-start and monitoring |

## Troubleshooting

### No captions appearing

1. Check microphone levels:
   ```bash
   amixer -c 0 sget Mic  # Phone mic
   amixer -c 1 sget Mic  # Room mic
   ```

2. Check service status:
   ```bash
   systemctl --user status caption.service
   ```

3. Check audio devices are connected:
   ```bash
   arecord -l
   ```

4. Restart service:
   ```bash
   systemctl --user restart caption.service
   ```

### Service keeps crashing

```bash
journalctl --user -u caption.service -f
```

### TONOR mic recording silence

Check the mute button LED on the microphone:
- **LED ON** = Microphone active (working)
- **LED OFF** = Microphone muted (no audio)

Try unplugging and replugging the USB cable.

## Reliability Features

### Application Level
- Thread-safe state management
- Automatic engine fallback (Deepgram -> faster-whisper -> Vosk)
- Health monitoring with auto-restart (max 5 attempts)
- Stale transcription detection (restarts after 2 min silence)
- Phone detection with device handoff

### System Level
- systemd watchdog integration (Type=notify)
- Caption service watchdog timer (checks every 60s)
- Display watchdog timer (restarts LightDM, reboots if needed)
- Network watchdog timer (pings gateway every 2 min, restarts WiFi)
- LightDM aggressive restart policy

## License

MIT License - see [LICENSE](LICENSE) for details.
