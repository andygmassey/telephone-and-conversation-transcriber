#!/usr/bin/env python3
"""Gramps Transcriber — Setup Wizard (runs on port 8080)"""

import json
import os
import re
import subprocess
import time
import struct

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CONFIG_PATH = os.path.expanduser('~/gramps-transcriber/config.json')
CREDENTIALS_PATH = os.path.expanduser('~/gramps-transcriber/credentials.py')


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=4)


def save_credentials(deepgram_key=None, azure_key=None, azure_region=None):
    """Write credentials.py so caption_app.py can import it."""
    lines = []
    if deepgram_key:
        lines.append(f'DEEPGRAM_KEY = "{deepgram_key}"')
    if azure_key:
        lines.append(f'AZURE_KEY = "{azure_key}"')
        lines.append(f'AZURE_REGION = "{azure_region or "uksouth"}"')
    if lines:
        with open(CREDENTIALS_PATH, 'w') as f:
            f.write('\n'.join(lines) + '\n')


def detect_audio_devices():
    """Parse arecord -l into a friendly list of microphones."""
    devices = []
    try:
        result = subprocess.run(
            ['arecord', '-l'], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split('\n'):
            match = re.search(r'card (\d+):.*\[(.+?)\].*device (\d+):.*\[(.+?)\]', line)
            if match:
                card, card_name, device, device_name = match.groups()
                hw_id = f'hw:{card},{device}'
                # Build a friendly label
                label = device_name.strip()
                if card_name.strip().lower() != device_name.strip().lower():
                    label = f'{card_name.strip()} — {device_name.strip()}'
                devices.append({
                    'hw_id': hw_id,
                    'card': int(card),
                    'label': label,
                    'raw': line.strip(),
                })
    except Exception:
        pass
    return devices


def test_audio_device(hw_id, duration=3, sample_rate=16000):
    """Record a short clip from a device and return the audio energy level (0-100)."""
    try:
        proc = subprocess.run(
            ['arecord', '-D', hw_id, '-f', 'S16_LE', '-r', str(sample_rate),
             '-c', '1', '-t', 'raw', '-d', str(duration), '-q'],
            capture_output=True, timeout=duration + 5
        )
        raw = proc.stdout
        if not raw:
            return 0
        # Calculate RMS energy
        samples = struct.unpack(f'<{len(raw)//2}h', raw)
        if not samples:
            return 0
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        # Normalise to 0-100 (32768 is max for 16-bit)
        level = min(100, int(rms / 327.68 * 10))
        return level
    except Exception:
        return -1


def get_service_status(service_name):
    """Check if a systemd user service is running."""
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', service_name],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return 'unknown'


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    config = load_config()
    return render_template('index.html', config=config)


@app.route('/api/devices')
def api_devices():
    devices = detect_audio_devices()
    return jsonify(devices)


@app.route('/api/test-audio', methods=['POST'])
def api_test_audio():
    data = request.get_json() or {}
    hw_id = data.get('hw_id', 'hw:0,0')
    level = test_audio_device(hw_id)
    return jsonify({'level': level, 'hw_id': hw_id})


@app.route('/api/save', methods=['POST'])
def api_save():
    data = request.get_json() or {}

    config = {
        'room_device': data.get('room_device', ''),
        'phone_device': data.get('phone_device', ''),
        'stt_provider': data.get('stt_provider', 'deepgram'),
        'offline_model': data.get('offline_model', 'faster-whisper'),
        'deepgram_key': data.get('deepgram_key', ''),
        'assemblyai_key': data.get('assemblyai_key', ''),
        'azure_key': data.get('azure_key', ''),
        'azure_region': data.get('azure_region', 'uksouth'),
        'groq_key': data.get('groq_key', ''),
        'interfaze_key': data.get('interfaze_key', ''),
        'openai_key': data.get('openai_key', ''),
        'google_key': data.get('google_key', ''),
        'gateway_ip': data.get('gateway_ip', ''),
    }

    save_config(config)

    # Also write credentials.py for backwards compatibility
    if config.get('deepgram_key'):
        save_credentials(deepgram_key=config['deepgram_key'])
    elif config.get('azure_key'):
        save_credentials(azure_key=config['azure_key'], azure_region=config['azure_region'])

    # Restart the caption service so it picks up new config
    try:
        subprocess.run(
            ['systemctl', '--user', 'restart', 'caption'],
            capture_output=True, timeout=10
        )
    except Exception:
        pass

    return jsonify({'ok': True})


@app.route('/api/status')
def api_status():
    caption = get_service_status('caption')
    mute = get_service_status('gramps-mute')
    config = load_config()
    configured = bool(config.get('room_device') or config.get('deepgram_key'))
    return jsonify({
        'caption': caption,
        'mute': mute,
        'configured': configured,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
