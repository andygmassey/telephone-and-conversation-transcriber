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
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
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
        os.makedirs(os.path.dirname(CREDENTIALS_PATH), exist_ok=True)
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


def find_capture_control(card):
    """Find the ALSA capture volume control name for a given card."""
    try:
        result = subprocess.run(
            ['amixer', '-c', str(card), 'scontrols'],
            capture_output=True, text=True, timeout=5
        )
        for name in ['Capture', 'Mic', 'Digital', 'Internal Mic', 'Headset']:
            if f"'{name}'" in result.stdout:
                return name
    except Exception:
        pass
    return None


def get_capture_level(card, control):
    """Get current capture level (0-100) for a card/control."""
    try:
        result = subprocess.run(
            ['amixer', '-c', str(card), 'sget', control],
            capture_output=True, text=True, timeout=5
        )
        match = re.search(r'\[(\d+)%\]', result.stdout)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return -1


def set_capture_level(card, control, level):
    """Set capture level (0-100) for a card/control."""
    try:
        subprocess.run(
            ['amixer', '-c', str(card), 'sset', control, f'{level}%'],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        return False


def calibrate_mic(hw_id, card, target_silence=2, duration=3, sample_rate=16000):
    """Auto-calibrate mic gain by reducing until silence reads below target energy.

    Returns dict with final_level, final_energy, steps taken.
    """
    control = find_capture_control(card)
    if not control:
        return {'ok': False, 'error': 'No capture control found for this device'}

    current_level = get_capture_level(card, control)
    if current_level < 0:
        return {'ok': False, 'error': 'Could not read current capture level'}

    steps = []
    # Start from current level and reduce until silence is quiet enough
    for attempt in range(10):
        energy = test_audio_device(hw_id, duration=duration, sample_rate=sample_rate)
        steps.append({'level': current_level, 'energy': energy})

        if energy <= target_silence:
            # Save to config
            config = load_config()
            config['mic_gain'] = current_level
            config['mic_gain_card'] = card
            config['mic_gain_control'] = control
            save_config(config)
            return {'ok': True, 'final_level': current_level, 'final_energy': energy, 'steps': steps}

        if current_level <= 10:
            # Don't go below 10%
            break

        # Reduce by 10%
        current_level = max(10, current_level - 10)
        set_capture_level(card, control, current_level)
        time.sleep(0.5)

    return {'ok': False, 'error': f'Could not get silence below threshold (energy={energy} at {current_level}%)', 'steps': steps}


def detect_hardware():
    """Detect hardware capabilities for auto-configuration."""
    info = {'ram_gb': 0, 'cpu_model': '', 'is_pi': False, 'recommended_model': 'small.en'}
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    kb = int(line.split()[1])
                    info['ram_gb'] = round(kb / 1024 / 1024, 1)
                    break
    except Exception:
        pass
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.startswith('Model') and ':' in line:
                    info['cpu_model'] = line.split(':', 1)[1].strip()
                    break
    except Exception:
        pass
    try:
        with open('/etc/os-release') as f:
            content = f.read()
            if 'raspbian' in content.lower() or 'raspberry' in content.lower():
                info['is_pi'] = True
    except Exception:
        pass
    # Recommend model based on RAM
    if info['ram_gb'] < 2:
        info['recommended_model'] = 'tiny.en'
    elif info['ram_gb'] < 4:
        info['recommended_model'] = 'tiny.en'
    elif info['ram_gb'] < 8:
        info['recommended_model'] = 'small.en'
    else:
        info['recommended_model'] = 'medium.en'
    return info


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


@app.route('/api/hardware')
def api_hardware():
    info = detect_hardware()
    return jsonify(info)


@app.route('/api/probe-lan', methods=['POST'])
def api_probe_lan():
    """Probe a LAN server URL to check if it's running and get available models."""
    import requests as req
    data = request.get_json() or {}
    url = data.get('url', '').rstrip('/')
    if not url:
        return jsonify({'ok': False, 'error': 'No URL provided'})

    result = {'ok': False, 'url': url}
    try:
        # Check health
        health = req.get(f'{url}/health', timeout=5)
        result['healthy'] = health.status_code == 200

        # Try to get available models
        try:
            models = req.get(f'{url}/v1/models', timeout=5)
            if models.status_code == 200:
                result['models'] = models.json()
        except Exception:
            pass

        result['ok'] = result.get('healthy', False)
    except req.ConnectionError:
        result['error'] = 'Could not connect. Is the server running?'
    except req.Timeout:
        result['error'] = 'Connection timed out'
    except Exception as e:
        result['error'] = str(e)

    return jsonify(result)


@app.route('/api/calibrate', methods=['POST'])
def api_calibrate():
    data = request.get_json() or {}
    hw_id = data.get('hw_id', 'hw:0,0')
    card = data.get('card', 0)
    result = calibrate_mic(hw_id, card)
    return jsonify(result)


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
        'speech_mode': data.get('speech_mode', 'online'),
        'stt_provider': data.get('stt_provider', 'deepgram'),
        'offline_model': data.get('offline_model', 'faster-whisper'),
        'whisper_model': data.get('whisper_model', 'small.en'),
        'deepgram_key': data.get('deepgram_key', ''),
        'assemblyai_key': data.get('assemblyai_key', ''),
        'azure_key': data.get('azure_key', ''),
        'azure_region': data.get('azure_region', 'uksouth'),
        'groq_key': data.get('groq_key', ''),
        'interfaze_key': data.get('interfaze_key', ''),
        'openai_key': data.get('openai_key', ''),
        'google_key': data.get('google_key', ''),
        'lan_url': data.get('lan_url', ''),
        'lan_model': data.get('lan_model', 'Systran/faster-whisper-small.en'),
        'gateway_ip': data.get('gateway_ip', ''),
    }

    save_config(config)

    # Also write credentials.py for backwards compatibility
    if config.get('deepgram_key'):
        save_credentials(deepgram_key=config['deepgram_key'])
    elif config.get('azure_key'):
        save_credentials(azure_key=config['azure_key'], azure_region=config['azure_region'])

    # Enable and restart the caption service so it starts on boot and picks up new config
    try:
        subprocess.run(
            ['systemctl', '--user', 'enable', '--now', 'caption'],
            capture_output=True, timeout=10
        )
    except Exception:
        pass

    # Enable lingering so user services start at boot without login
    try:
        subprocess.run(
            ['loginctl', 'enable-linger'],
            capture_output=True, timeout=5
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
