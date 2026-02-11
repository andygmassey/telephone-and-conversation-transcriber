# Telephone and Conversation Transcriber (Azure Branch)

My elderly father is extremely deaf and struggles to hear people, particularly on the landline phone. So I built this — a Raspberry Pi with a 10" touchscreen that sits next to his phone and transcribes conversations in near real-time, so he can read what people are saying.

This branch uses **Azure Speech Services** (en-GB) with automatic **Vosk** offline fallback. See the `main` branch for the Deepgram/faster-whisper version.

## Features

- **Live Captions** - Real-time speech-to-text using Azure Speech (en-GB)
- **Offline Fallback** - Automatic fallback to Vosk if Azure is unavailable
- **Flip-Clock** - Split-flap style clock displays when idle, auto-dims at night
- **Auto-Mute** - Room mic automatically mutes when phone is in use
- **Touch Scroll** - Drag anywhere on captions to scroll through history
- **Bulletproof** - Works with or without phone recorder, with or without internet

## Hardware

| Component | Model | Required |
|-----------|-------|----------|
| Computer | Raspberry Pi 5 (8GB) | Yes |
| Room Microphone | TONOR G11 (0d8c:0134) | Yes |
| Display | 10" Touchscreen (1280x800) | Yes |
| Phone Recorder | Fi3001A (04d9:2832) | Optional |

### TONOR G11 Microphone

**IMPORTANT**: The mic has a mute button with an LED indicator.
- **LED ON** = Microphone ACTIVE (working)
- **LED OFF** = Microphone MUTED (no audio)

If captions stop appearing, check the LED is lit. Press the button on the mic to toggle.

## Speech Recognition

| Mode | Indicator | Accuracy | Latency | Requires |
|------|-----------|----------|---------|----------|
| Azure | Cloud icon (blue) | ~95% | ~200ms | Internet + Azure key |
| Vosk | Disk icon (orange) | ~75% | ~300ms | Nothing |

The system automatically falls back to Vosk if Azure is unavailable.

## Quick Start

### 1. Set up Python environment

```bash
python3 -m venv ~/gramps-env
source ~/gramps-env/bin/activate
pip install pyqt6 vosk azure-cognitiveservices-speech sounddevice numpy
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
# Edit credentials.py with your Azure Speech key and region
```

### 4. Install systemd services

```bash
mkdir -p ~/.config/systemd/user
cp caption.service ~/.config/systemd/user/
cp gramps-mute.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now caption gramps-mute
```

## Display Modes

### Flip-Clock (Idle)
When no speech for 90 seconds, displays split-flap clock:
- DSEG14 font, hours and minutes
- Auto-dims between 22:00-07:00
- Instantly switches to captions when speech detected

### Captions (Active)
- Large text with configurable size and colour
- Status indicator shows Azure or Offline mode
- Green phone icon when phone is active
- Drag anywhere to scroll through history

## Resilience Features

- **Auto-unmute** - Mic forced to 100% on every startup
- **Graceful degradation** - Works without phone recorder
- **Offline fallback** - Vosk if Azure unavailable
- **Clean shutdown** - Mic always unmuted on exit
- **Watchdog** - Auto-restart on crash

## Troubleshooting

### No captions appearing
1. Check TONOR mic LED is ON (not muted)
2. Check mic level: `amixer -c 1 sget Mic`
3. Restart: `systemctl --user restart caption.service`

### Mic recording silence
Try unplugging and replugging the TONOR USB cable.

### Azure not connecting
- Verify internet connection
- Check Azure key in `credentials.py`
- Confirm your Azure region endpoint is accessible

## Files

| File | Purpose |
|------|---------|
| `azure_stream.py` | Main app with Azure + Vosk fallback |
| `whisper_stream.py` | Alternative whisper.cpp streaming app |
| `mute_helper.py` | Auto-mute room mic when phone active |
| `credentials.py.example` | Template for Azure credentials |
| `fonts/` | DSEG14 font for flip-clock display |
| `daily_caption_automation.yaml` | Home Assistant usage reporting template |

## License

MIT License - see [LICENSE](LICENSE) for details.
