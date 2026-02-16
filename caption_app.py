#!/usr/bin/env python3
"""Gramps Captions - Online (Deepgram) / Offline (Vosk) hybrid - BULLETPROOF VERSION"""
import sys
import os
import subprocess
import threading
import re
import time
import queue
import json
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QLabel,
    QVBoxLayout, QHBoxLayout, QWidget, QScroller, QStackedWidget)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QFontDatabase, QTextCursor, QPainter, QColor, QLinearGradient, QPen

# Load config from setup wizard, or use defaults
CONFIG_PATH = os.path.expanduser('~/gramps-transcriber/config.json')

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

CONFIG = load_config()

# Paths
VOSK_MODEL = os.path.expanduser('~/vosk-uk')
FONT_PATH = os.path.expanduser('~/gramps-transcriber/fonts/DSEG14Classic-Bold.ttf')
PHONE_MUTED_FILE = '/tmp/phone_muted'
SILENCE_TIMEOUT = 90
PHONE_SILENCE_TIMEOUT = 10
MODE_FILE = '/tmp/gramps_mode'

# Try to load secrets — check credentials.py first, then config.json
try:
    from credentials import DEEPGRAM_KEY
except ImportError:
    DEEPGRAM_KEY = CONFIG.get('deepgram_key')

# Thread-safe state management
class TranscriptionState:
    def __init__(self):
        self._lock = threading.RLock()
        self._mode = 'offline'
        self._use_phone_audio = False
        self._last_phone_speech = 0
        self._stop_event = threading.Event()
        self._thread_alive = False
        self._last_text_time = 0
        self._restart_count = 0
        self._restarting = False
        self._max_restarts = 5
        self._current_proc = None
        self._generation = 0
        self._success_time = 0

    @property
    def mode(self):
        with self._lock:
            return self._mode

    @mode.setter
    def mode(self, value):
        with self._lock:
            self._mode = value

    @property
    def use_phone_audio(self):
        with self._lock:
            return self._use_phone_audio

    @use_phone_audio.setter
    def use_phone_audio(self, value):
        with self._lock:
            self._use_phone_audio = value

    @property
    def last_phone_speech(self):
        with self._lock:
            return self._last_phone_speech

    @last_phone_speech.setter
    def last_phone_speech(self, value):
        with self._lock:
            self._last_phone_speech = value

    @property
    def thread_alive(self):
        with self._lock:
            return self._thread_alive

    @thread_alive.setter
    def thread_alive(self, value):
        with self._lock:
            self._thread_alive = value

    @property
    def last_text_time(self):
        with self._lock:
            return self._last_text_time

    @last_text_time.setter
    def last_text_time(self, value):
        with self._lock:
            self._last_text_time = value

    @property
    def generation(self):
        with self._lock:
            return self._generation

    def next_generation(self):
        with self._lock:
            self._generation += 1
            return self._generation

    def stop(self):
        self._stop_event.set()

    def clear_stop(self):
        self._stop_event.clear()

    def is_stopped(self):
        return self._stop_event.is_set()

    def can_restart(self):
        with self._lock:
            return self._restart_count < self._max_restarts

    def increment_restart(self):
        with self._lock:
            self._restart_count += 1
            return self._restart_count

    def reset_restart_count(self):
        with self._lock:
            self._restart_count = 0
            self._restarting = False

    def mark_success(self):
        """Mark working transcription — resets restart count after 60s sustained"""
        with self._lock:
            now = time.time()
            self._last_text_time = now
            if self._success_time == 0:
                self._success_time = now
            elif now - self._success_time > 60 and self._restart_count > 0:
                print(f"Sustained success for 60s, resetting restart count (was {self._restart_count})", flush=True)
                self._restart_count = 0

    def reset_success_timer(self):
        with self._lock:
            self._success_time = 0

    def set_proc(self, proc):
        with self._lock:
            if self._current_proc:
                try:
                    self._current_proc.kill()
                except:
                    pass
                try:
                    self._current_proc.wait(timeout=1)
                except:
                    pass
            self._current_proc = proc

    def is_restarting(self):
        with self._lock:
            return self._restarting

    def set_restarting(self, value):
        with self._lock:
            self._restarting = value

    def kill_proc(self):
        with self._lock:
            if self._current_proc:
                try:
                    self._current_proc.kill()
                except:
                    pass
                try:
                    self._current_proc.wait(timeout=2)
                except:
                    pass
                self._current_proc = None

    def proc_alive(self):
        with self._lock:
            if self._current_proc is None:
                return False
            return self._current_proc.poll() is None


state = TranscriptionState()


class Emitter(QObject):
    new_text = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    mode_ready = pyqtSignal(str)
    thread_died = pyqtSignal(str)  # NEW: signal when thread dies

emitter = Emitter()



def write_phone_status(active):
    """Write phone status file"""
    try:
        with open(PHONE_MUTED_FILE, 'w') as f:
            f.write('1' if active else '0')
    except:
        pass

def find_audio_device(name_pattern):
    """Find ALSA device by name pattern, returns hw:X,0 or None"""
    try:
        result = subprocess.run(['arecord', '-l'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if name_pattern.lower() in line.lower():
                match = re.search(r'card (\d+):', line)
                if match:
                    return f"hw:{match.group(1)},0"
    except Exception as e:
        print(f"Device detection error: {e}", flush=True)
    return None


def get_audio_device():
    """Get appropriate audio device based on current state"""
    if state.use_phone_audio:
        configured = CONFIG.get('phone_device')
        if configured:
            return configured
        dev = find_audio_device('0x4d9') or find_audio_device('2832') or find_audio_device('phone') or 'hw:0,0'
    else:
        configured = CONFIG.get('room_device')
        if configured:
            return configured
        dev = find_audio_device('tonor') or find_audio_device('usb') or 'hw:1,0'
    return dev


def ensure_mic_volume():
    """Ensure microphone volume is set correctly"""
    try:
        # Try multiple cards
        for card in range(3):
            subprocess.run(['amixer', '-c', str(card), 'set', 'Mic', '100%'],
                         capture_output=True, timeout=5)
    except:
        pass


def cleanup_audio_processes():
    """Kill any stale audio processes"""
    try:
        subprocess.run(['pkill', '-9', '-f', 'arecord'], capture_output=True, timeout=5)
        time.sleep(0.5)
    except:
        pass



def faster_whisper_thread():
    """Run faster-whisper for high quality offline transcription"""
    print('Starting faster-whisper...', flush=True)
    emitter.status_changed.emit('whisper')
    # thread_alive already set by start_transcription
    arecord = None

    try:
        from faster_whisper import WhisperModel
        import numpy as np

        # Load model
        print('Loading Whisper model (small.en)...', flush=True)
        model = WhisperModel(
            "small.en",
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            num_workers=1
        )
        print('Whisper model loaded', flush=True)

        # Audio settings
        SAMPLE_RATE = 16000
        CHUNK_SECONDS = 3
        CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS

        # Get audio device
        audio_device = get_audio_device()
        print(f"Using audio device: {audio_device}", flush=True)

        # Start arecord with retry
        for attempt in range(4):
            arecord = subprocess.Popen(
                ['arecord', '-D', audio_device, '-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw', '-q'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            state.set_proc(arecord)
            time.sleep(0.3)
            if arecord.poll() is None:
                print(f'arecord ready (attempt {attempt+1})', flush=True)
                break
            else:
                arecord = None
                if attempt < 3:
                    time.sleep(1)

        if not arecord:
            raise RuntimeError('Could not start arecord after 4 attempts')


        print('faster-whisper ready', flush=True)
        emitter.mode_ready.emit('offline')


        buffer = b''

        while not state.is_stopped():
            # Read audio chunk
            data = arecord.stdout.read(3200)  # 100ms at 16kHz, 16-bit
            if not data:
                print('faster-whisper: No audio data', flush=True)
                break

            buffer += data

            # Process when we have enough audio
            if len(buffer) >= CHUNK_SAMPLES * 2:  # 2 bytes per sample
                # Convert to numpy float32
                audio = np.frombuffer(buffer[:CHUNK_SAMPLES * 2], dtype=np.int16).astype(np.float32) / 32768.0
                buffer = buffer[CHUNK_SAMPLES * 2:]

                # Check audio energy - skip if too quiet (reduces hallucinations)
                energy = np.sqrt(np.mean(audio**2))
                # Energy check - skip quiet chunks
                if energy < 0.005:  # Skip very quiet chunks (lowered threshold)
                    continue

                # Transcribe
                segments, info = model.transcribe(
                    audio,
                    language="en",
                    beam_size=1,
                    best_of=1,
                    temperature=0,
                    vad_filter=False,
                    vad_parameters={
                        "threshold": 0.5,
                        "min_speech_duration_ms": 250,
                        "min_silence_duration_ms": 500
                    },
                )

                # Emit text
                segments_list = list(segments)

                for segment in segments_list:
                    text = segment.text.strip()
                    if text:
                        print(f'>>> {text}', flush=True)
                        state.mark_success()
                        emitter.new_text.emit(text)

    except ImportError as e:
        print(f'faster-whisper not available: {e}', flush=True)
        print('Falling back to Vosk...', flush=True)
        state.thread_alive = False
        vosk_thread()
        return
    except Exception as e:
        print(f'faster-whisper error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        if arecord:
            try:
                arecord.terminate()
                arecord.wait(timeout=2)
            except:
                try:
                    arecord.kill()
                    arecord.wait(timeout=1)  # Reap zombie
                except:
                    pass
        state.kill_proc()
        print('faster-whisper stopped', flush=True)

        if not state.is_stopped():
            emitter.thread_died.emit('offline')


def vosk_thread():
    """Run Vosk streaming with robust error handling"""
    print('Starting Vosk...', flush=True)
    emitter.status_changed.emit('vosk')
    # thread_alive already set by start_transcription
    arecord = None

    try:
        import vosk
        import json

        vosk.SetLogLevel(-1)

        # Verify model exists
        if not os.path.exists(VOSK_MODEL):
            raise FileNotFoundError(f"Vosk model not found: {VOSK_MODEL}")

        model = vosk.Model(VOSK_MODEL)
        rec = vosk.KaldiRecognizer(model, 16000)
        rec.SetWords(False)

        # Get audio device with retry
        audio_device = None
        for attempt in range(3):
            audio_device = get_audio_device()
            print(f"Using audio device: {audio_device} (attempt {attempt+1})", flush=True)

            arecord = subprocess.Popen(
                ['arecord', '-D', audio_device, '-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw', '-q'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            state.set_proc(arecord)

            # Test if we get data
            time.sleep(0.3)
            if arecord.poll() is None:  # Still running
                break
            else:
                stderr = arecord.stderr.read().decode() if arecord.stderr else ""
                print(f"arecord failed: {stderr}", flush=True)
                arecord = None
                time.sleep(1)

        if not arecord:
            raise RuntimeError("Could not start arecord after 3 attempts")

        print('Vosk ready', flush=True)
        emitter.mode_ready.emit('offline')


        consecutive_empty = 0
        while not state.is_stopped():
            try:
                data = arecord.stdout.read(4000)
                if not data:
                    consecutive_empty += 1
                    if consecutive_empty > 10:
                        print("Vosk: No audio data, restarting...", flush=True)
                        break
                    time.sleep(0.1)
                    continue

                consecutive_empty = 0
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get('text', '').strip()
                    if text:
                        print(f'>>> {text}', flush=True)
                        state.mark_success()
                        emitter.new_text.emit(text)
            except Exception as e:
                print(f"Vosk read error: {e}", flush=True)
                break

    except FileNotFoundError as e:
        print(f'Vosk model error: {e}', flush=True)
        emitter.status_changed.emit('error')
    except Exception as e:
        print(f'Vosk error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        if arecord:
            try:
                arecord.terminate()
                arecord.wait(timeout=2)
            except:
                try:
                    arecord.kill()
                    arecord.wait(timeout=1)  # Reap zombie
                except:
                    pass
        state.kill_proc()
        print('Vosk stopped', flush=True)

        # Signal that thread died (for restart logic)
        if not state.is_stopped():
            emitter.thread_died.emit('offline')



def whisper_thread():
    """Run whisper.cpp streaming for better quality offline transcription"""
    print('Starting Whisper.cpp stream...', flush=True)
    emitter.status_changed.emit('whisper')
    # thread_alive already set by start_transcription
    proc = None

    try:
        WHISPER_BIN = os.path.expanduser('~/whisper.cpp/build/bin/whisper-stream')
        WHISPER_MODEL = os.path.expanduser('~/whisper.cpp/models/ggml-base.en-q5_0.bin')

        if not os.path.exists(WHISPER_BIN):
            raise FileNotFoundError(f"whisper-stream not found: {WHISPER_BIN}")
        if not os.path.exists(WHISPER_MODEL):
            raise FileNotFoundError(f"Whisper model not found: {WHISPER_MODEL}")

        # Determine audio device index for ALSA
        audio_device = "0" if state.use_phone_audio else "1"
        print(f"Using audio device index: {audio_device}", flush=True)

        cmd = [
            WHISPER_BIN,
            '-m', WHISPER_MODEL,
            '-c', audio_device,
            '--step', '3000',
            '--length', '5000',
            '-l', 'en',
        ]

        env = os.environ.copy()
        env['TERM'] = 'dumb'

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        state.set_proc(proc)

        print('Whisper ready', flush=True)
        emitter.mode_ready.emit('offline')


        for line in iter(proc.stdout.readline, ''):
            if state.is_stopped():
                break

            # Clean ANSI codes
            line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line)
            line = re.sub(r'\[2K', '', line)
            line = line.strip()

            if not line:
                continue
            if line.startswith('[') or line.startswith('init:') or line.startswith('whisper'):
                continue
            if line.startswith('main:'):
                continue
            if 'BLANK_AUDIO' in line or 'INAUDIBLE' in line:
                continue

            print(f'>>> {line}', flush=True)
            state.mark_success()
            emitter.new_text.emit(line)

    except FileNotFoundError as e:
        print(f'Whisper not available: {e}', flush=True)
        print('Falling back to Vosk...', flush=True)
        state.thread_alive = False
        vosk_thread()
        return
    except Exception as e:
        print(f'Whisper error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except:
                try:
                    proc.kill()
                    proc.wait(timeout=1)  # Reap zombie
                except:
                    pass
        state.kill_proc()
        print('Whisper stopped', flush=True)

        if not state.is_stopped():
            emitter.thread_died.emit('offline')


def deepgram_thread():
    """Run Deepgram streaming with robust error handling"""
    if not DEEPGRAM_KEY:
        print('No Deepgram API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    print('Starting Deepgram...', flush=True)
    emitter.status_changed.emit('deepgram')
    # thread_alive already set by start_transcription
    arecord = None

    try:
        import websocket
        import json

        # Get audio device with retry
        audio_device = get_audio_device()
        # Phone recorder is 8kHz, room mic is 16kHz
        sample_rate = 8000 if state.use_phone_audio else 16000
        print(f"Using audio device: {audio_device} @ {sample_rate}Hz", flush=True)

        test_data = b''
        for attempt in range(4):
            arecord = subprocess.Popen(
                ['arecord', '-D', audio_device, '-f', 'S16_LE', '-r', str(sample_rate), '-c', '1', '-t', 'raw'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            state.set_proc(arecord)
            time.sleep(0.3)
            test_data = arecord.stdout.read(3200)
            if len(test_data) > 0:
                print(f'arecord ready (attempt {attempt+1})', flush=True)
                break
            else:
                arecord.terminate()
                arecord = None
                if attempt < 3:
                    time.sleep(1)

        if not arecord:
            raise RuntimeError('Could not start arecord after 4 attempts')

        url = f'wss://api.deepgram.com/v1/listen?model=nova-2&language=en-GB&smart_format=true&encoding=linear16&sample_rate={sample_rate}'

        ws_connected = threading.Event()
        ws_error = threading.Event()

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if 'channel' in data:
                    t = data['channel']['alternatives'][0]['transcript']
                    if t and t.strip():
                        if data.get('speech_final', False):
                            t = t + '\n'
                        print(f'>>> {t.strip()}', flush=True)
                        state.mark_success()
                        emitter.new_text.emit(t)
            except Exception as e:
                print(f'Parse error: {e}', flush=True)

        def on_error(ws, error):
            print(f'WS error: {error}', flush=True)
            ws_error.set()

        def on_open(ws):
            print('Deepgram connected', flush=True)
            ws_connected.set()
            emitter.mode_ready.emit('online')

            ws.send(test_data, opcode=2)

            def send_audio():
                while not state.is_stopped() and not ws_error.is_set():
                    try:
                        chunk = arecord.stdout.read(3200)
                        if chunk:
                            ws.send(chunk, opcode=2)
                        else:
                            if arecord.poll() is not None:
                                print('Deepgram: arecord process died', flush=True)
                                break
                            print('send_audio: arecord returned empty data, stopping', flush=True); break
                    except Exception as e:
                        print(f"Send error: {e}", flush=True)
                        break
                try:
                    ws.close()
                except:
                    pass

            threading.Thread(target=send_audio, daemon=True).start()

        def on_close(ws, code, msg):
            print(f'Deepgram closed: {code} {msg}', flush=True)

        print('Connecting to Deepgram...', flush=True)
        ws = websocket.WebSocketApp(
            url,
            header={'Authorization': f'Token {DEEPGRAM_KEY}'},
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        # Run with timeout
        ws.run_forever(ping_interval=30, ping_timeout=10)

    except Exception as e:
        print(f'Deepgram error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        if arecord:
            try:
                arecord.terminate()
                arecord.wait(timeout=2)
            except:
                try:
                    arecord.kill()
                    arecord.wait(timeout=1)  # Reap zombie
                except:
                    pass
        state.kill_proc()
        print('Deepgram stopped', flush=True)

        if not state.is_stopped():
            emitter.thread_died.emit('online')


def assemblyai_thread():
    """Run AssemblyAI real-time streaming via WebSocket"""
    api_key = CONFIG.get('assemblyai_key')
    if not api_key:
        print('No AssemblyAI API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    print('Starting AssemblyAI...', flush=True)
    emitter.status_changed.emit('assemblyai')
    # thread_alive already set by start_transcription
    arecord = None

    try:
        import websocket
        import json
        import base64

        audio_device = get_audio_device()
        sample_rate = 8000 if state.use_phone_audio else 16000
        print(f"Using audio device: {audio_device} @ {sample_rate}Hz", flush=True)

        # Start arecord with retry
        for attempt in range(4):
            arecord = subprocess.Popen(
                ['arecord', '-D', audio_device, '-f', 'S16_LE', '-r', str(sample_rate), '-c', '1', '-t', 'raw'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            state.set_proc(arecord)
            time.sleep(0.3)
            test_data = arecord.stdout.read(3200)
            if len(test_data) > 0:
                print(f'arecord ready (attempt {attempt+1})', flush=True)
                break
            else:
                arecord.terminate()
                arecord = None
                if attempt < 3:
                    time.sleep(1)

        if not arecord:
            raise RuntimeError('Could not start arecord after 4 attempts')

        url = f'wss://api.assemblyai.com/v2/realtime/ws?sample_rate={sample_rate}'
        ws_error = threading.Event()

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get('message_type') == 'FinalTranscript':
                    text = data.get('text', '').strip()
                    if text:
                        print(f'>>> {text}', flush=True)
                        state.mark_success()
                        emitter.new_text.emit(text + '\n')
                elif data.get('message_type') == 'PartialTranscript':
                    text = data.get('text', '').strip()
                    if text:
                        state.mark_success()
            except Exception as e:
                print(f'AssemblyAI parse error: {e}', flush=True)

        def on_error(ws, error):
            print(f'AssemblyAI WS error: {error}', flush=True)
            ws_error.set()

        def on_open(ws):
            print('AssemblyAI connected', flush=True)
            emitter.mode_ready.emit('online')


            # Send initial audio
            ws.send(json.dumps({'audio_data': base64.b64encode(test_data).decode()}))

            def send_audio():
                while not state.is_stopped() and not ws_error.is_set():
                    try:
                        chunk = arecord.stdout.read(3200)
                        if chunk:
                            ws.send(json.dumps({'audio_data': base64.b64encode(chunk).decode()}))
                        else:
                            if arecord.poll() is not None:
                                print('AssemblyAI: arecord process died', flush=True)
                                break
                            print('send_audio: arecord returned empty data, stopping', flush=True); break
                    except Exception as e:
                        print(f"AssemblyAI send error: {e}", flush=True)
                        break
                try:
                    ws.send(json.dumps({'terminate_session': True}))
                    ws.close()
                except:
                    pass

            threading.Thread(target=send_audio, daemon=True).start()

        def on_close(ws, code, msg):
            print(f'AssemblyAI closed: {code} {msg}', flush=True)

        print('Connecting to AssemblyAI...', flush=True)
        ws = websocket.WebSocketApp(
            url,
            header={'Authorization': api_key},
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        ws.run_forever(ping_interval=30, ping_timeout=10)

    except Exception as e:
        print(f'AssemblyAI error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        if arecord:
            try:
                arecord.terminate()
                arecord.wait(timeout=2)
            except:
                try:
                    arecord.kill()
                    arecord.wait(timeout=1)  # Reap zombie
                except:
                    pass
        state.kill_proc()
        print('AssemblyAI stopped', flush=True)
        if not state.is_stopped():
            emitter.thread_died.emit('online')


def azure_thread():
    """Run Azure Speech Services with SDK streaming"""
    api_key = CONFIG.get('azure_key')
    region = CONFIG.get('azure_region', 'uksouth')
    if not api_key:
        print('No Azure API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    print('Starting Azure Speech...', flush=True)
    emitter.status_changed.emit('azure')
    # thread_alive already set by start_transcription

    try:
        import azure.cognitiveservices.speech as speechsdk

        speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
        speech_config.speech_recognition_language = 'en-GB'

        audio_device = get_audio_device()
        # Azure SDK can use ALSA device directly
        audio_config = speechsdk.audio.AudioConfig(device_name=audio_device)

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        def on_recognized(evt):
            text = evt.result.text.strip()
            if text:
                print(f'>>> {text}', flush=True)
                state.mark_success()
                emitter.new_text.emit(text + '\n')

        def on_recognizing(evt):
            if evt.result.text.strip():
                state.mark_success()

        def on_canceled(evt):
            print(f'Azure canceled: {evt.result.cancellation_details.reason}', flush=True)
            if evt.result.cancellation_details.error_details:
                print(f'Azure error: {evt.result.cancellation_details.error_details}', flush=True)

        def on_session_started(evt):
            print('Azure session started', flush=True)
            emitter.mode_ready.emit('online')


        recognizer.recognized.connect(on_recognized)
        recognizer.recognizing.connect(on_recognizing)
        recognizer.canceled.connect(on_canceled)
        recognizer.session_started.connect(on_session_started)

        print('Starting continuous recognition...', flush=True)
        recognizer.start_continuous_recognition()

        # Wait until stopped
        while not state.is_stopped():
            time.sleep(0.5)

        recognizer.stop_continuous_recognition()

    except ImportError:
        print('Azure Speech SDK not installed. Install with: pip install azure-cognitiveservices-speech', flush=True)
        emitter.status_changed.emit('error')
    except Exception as e:
        print(f'Azure error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        state.kill_proc()
        print('Azure stopped', flush=True)
        if not state.is_stopped():
            emitter.thread_died.emit('online')


def _chunked_api_thread(provider_name, transcribe_fn):
    """Shared logic for providers that use chunked batch transcription (Google, OpenAI, Groq).

    Records audio in chunks and sends each chunk to transcribe_fn(audio_bytes, sample_rate)
    which should return the transcribed text or empty string.
    """
    print(f'Starting {provider_name}...', flush=True)
    emitter.status_changed.emit(provider_name.lower())
    # thread_alive already set by start_transcription
    arecord = None

    try:
        audio_device = get_audio_device()
        sample_rate = 8000 if state.use_phone_audio else 16000
        chunk_seconds = 4
        chunk_bytes = sample_rate * 2 * chunk_seconds  # 16-bit mono
        print(f"Using audio device: {audio_device} @ {sample_rate}Hz", flush=True)

        # Start arecord with retry
        for attempt in range(4):
            arecord = subprocess.Popen(
                ['arecord', '-D', audio_device, '-f', 'S16_LE', '-r', str(sample_rate), '-c', '1', '-t', 'raw'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            state.set_proc(arecord)
            time.sleep(0.3)
            if arecord.poll() is None:
                print(f'arecord ready (attempt {attempt+1})', flush=True)
                break
            else:
                arecord = None
                if attempt < 3:
                    time.sleep(1)

        if not arecord:
            raise RuntimeError('Could not start arecord after 4 attempts')

        emitter.mode_ready.emit('online')


        buffer = b''
        while not state.is_stopped():
            data = arecord.stdout.read(3200)
            if not data:
                if arecord.poll() is not None:
                    print(f'{provider_name}: arecord process died', flush=True)
                    break
                print(f'{provider_name}: arecord returned empty data, stopping', flush=True); break
                continue

            buffer += data

            if len(buffer) >= chunk_bytes:
                audio_chunk = buffer[:chunk_bytes]
                buffer = buffer[chunk_bytes:]

                try:
                    text = transcribe_fn(audio_chunk, sample_rate)
                    if text and text.strip():
                        text = text.strip()
                        print(f'>>> {text}', flush=True)
                        state.mark_success()
                        emitter.new_text.emit(text + '\n')
                except Exception as e:
                    print(f'{provider_name} API error: {e}', flush=True)

    except Exception as e:
        print(f'{provider_name} error: {e}', flush=True)
        emitter.status_changed.emit('error')
        import traceback
        traceback.print_exc()
    finally:
        state.thread_alive = False
        if arecord:
            try:
                arecord.terminate()
                arecord.wait(timeout=2)
            except:
                try:
                    arecord.kill()
                    arecord.wait(timeout=1)  # Reap zombie
                except:
                    pass
        state.kill_proc()
        print(f'{provider_name} stopped', flush=True)
        if not state.is_stopped():
            emitter.thread_died.emit('online')


def _make_wav(raw_audio, sample_rate):
    """Wrap raw PCM bytes in a minimal WAV header."""
    import struct as st
    num_samples = len(raw_audio) // 2
    wav = bytearray()
    wav += b'RIFF'
    wav += st.pack('<I', 36 + len(raw_audio))
    wav += b'WAVE'
    wav += b'fmt '
    wav += st.pack('<I', 16)           # chunk size
    wav += st.pack('<H', 1)            # PCM format
    wav += st.pack('<H', 1)            # mono
    wav += st.pack('<I', sample_rate)
    wav += st.pack('<I', sample_rate * 2)  # byte rate
    wav += st.pack('<H', 2)            # block align
    wav += st.pack('<H', 16)           # bits per sample
    wav += b'data'
    wav += st.pack('<I', len(raw_audio))
    wav += raw_audio
    return bytes(wav)


def google_thread():
    """Google Cloud Speech-to-Text via REST API (chunked)"""
    api_key = CONFIG.get('google_key')
    if not api_key:
        print('No Google Cloud API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    import requests
    import base64

    def transcribe(audio_bytes, sample_rate):
        audio_b64 = base64.b64encode(audio_bytes).decode()
        resp = requests.post(
            f'https://speech.googleapis.com/v1/speech:recognize?key={api_key}',
            json={
                'config': {
                    'encoding': 'LINEAR16',
                    'sampleRateHertz': sample_rate,
                    'languageCode': 'en-GB',
                    'enableAutomaticPunctuation': True,
                },
                'audio': {'content': audio_b64},
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get('results', [])
        return ' '.join(
            r['alternatives'][0]['transcript']
            for r in results
            if r.get('alternatives')
        )

    _chunked_api_thread('Google', transcribe)


def openai_thread():
    """OpenAI Whisper API (chunked)"""
    api_key = CONFIG.get('openai_key')
    if not api_key:
        print('No OpenAI API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    import requests

    def transcribe(audio_bytes, sample_rate):
        wav_data = _make_wav(audio_bytes, sample_rate)
        resp = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': ('chunk.wav', wav_data, 'audio/wav')},
            data={'model': 'whisper-1', 'language': 'en'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get('text', '')

    _chunked_api_thread('OpenAI', transcribe)


def groq_thread():
    """Groq Whisper API (chunked) — free tier, very fast"""
    api_key = CONFIG.get('groq_key')
    if not api_key:
        print('No Groq API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    import requests

    def transcribe(audio_bytes, sample_rate):
        wav_data = _make_wav(audio_bytes, sample_rate)
        resp = requests.post(
            'https://api.groq.com/openai/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': ('chunk.wav', wav_data, 'audio/wav')},
            data={'model': 'whisper-large-v3', 'language': 'en'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get('text', '')

    _chunked_api_thread('Groq', transcribe)


def interfaze_thread():
    """Interfaze STT API (chunked, OpenAI-compatible)"""
    api_key = CONFIG.get('interfaze_key')
    if not api_key:
        print('No Interfaze API key', flush=True)
        emitter.status_changed.emit('no-key')
        state.thread_alive = False
        emitter.thread_died.emit('online')
        return

    import requests

    def transcribe(audio_bytes, sample_rate):
        wav_data = _make_wav(audio_bytes, sample_rate)
        resp = requests.post(
            'https://api.interfaze.ai/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': ('chunk.wav', wav_data, 'audio/wav')},
            data={'model': 'interfaze-beta', 'language': 'en'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get('text', '')

    _chunked_api_thread('Interfaze', transcribe)


def start_transcription(mode):
    """Start transcription with cleanup"""
    state.kill_proc()  # Targeted kill only — no blanket pkill
    time.sleep(0.3)
    ensure_mic_volume()
    state.clear_stop()
    state.last_text_time = 0
    state.mode = mode
    state.reset_success_timer()
    state.thread_alive = True
    gen = state.next_generation()
    print(f"Starting transcription gen={gen} mode={mode}", flush=True)

    if mode == 'online':
        provider = CONFIG.get('stt_provider', 'deepgram')
        provider_threads = {
            'deepgram': deepgram_thread,
            'assemblyai': assemblyai_thread,
            'azure': azure_thread,
            'groq': groq_thread,
            'interfaze': interfaze_thread,
            'openai': openai_thread,
            'google': google_thread,
        }
        target = provider_threads.get(provider, deepgram_thread)
        print(f'Starting online transcription with {provider}', flush=True)
        threading.Thread(target=target, daemon=True).start()
    else:
        offline_model = CONFIG.get('offline_model', 'faster-whisper')
        offline_threads = {
            'faster-whisper': faster_whisper_thread,
            'vosk': vosk_thread,
            'whisper-cpp': whisper_thread,
        }
        target = offline_threads.get(offline_model, faster_whisper_thread)
        print(f'Starting offline transcription with {offline_model}', flush=True)
        threading.Thread(target=target, daemon=True).start()



def stop_transcription():
    """Stop transcription cleanly"""
    state.stop()
    state.kill_proc()  # Targeted kill only — no blanket pkill
    time.sleep(0.5)



def switch_mode(new_mode):
    """Switch modes with proper cleanup"""
    if new_mode != state.mode:
        print(f'Switching from {state.mode} to {new_mode}', flush=True)
        emitter.status_changed.emit('switching')
        stop_transcription()
        time.sleep(0.5)
        start_transcription(new_mode)
        emitter.mode_changed.emit(new_mode)


class FlipFlap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 450)
        self._text = '00'
        self._dimmed = False
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id >= 0:
            self._font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
        else:
            self._font_family = 'Arial Narrow'

    def set_text(self, text):
        if text != self._text:
            self._text = text
            self.update()

    def set_dimmed(self, dimmed):
        self._dimmed = dimmed
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        gap = 8
        flap_h = (h - gap) // 2
        r = 15
        text_col = QColor('#555') if self._dimmed else QColor('#f0f0f0')
        painter.setPen(QPen(QColor('#444'), 2))
        top_g = QLinearGradient(0, 0, 0, flap_h)
        top_g.setColorAt(0, QColor('#3d3d3d'))
        top_g.setColorAt(0.9, QColor('#2a2a2a'))
        top_g.setColorAt(1, QColor('#222'))
        painter.setBrush(top_g)
        painter.drawRoundedRect(0, 0, w, flap_h, r, r)
        bot_g = QLinearGradient(0, flap_h + gap, 0, h)
        bot_g.setColorAt(0, QColor('#1a1a1a'))
        bot_g.setColorAt(0.1, QColor('#252525'))
        bot_g.setColorAt(1, QColor('#333'))
        painter.setBrush(bot_g)
        painter.drawRoundedRect(0, flap_h + gap, w, flap_h, r, r)
        font = QFont(self._font_family, 280, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(text_col)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(self._text)
        tx = (w - tw) // 2
        cap_h = fm.capHeight()
        ty = (h // 2) + (cap_h // 2)
        painter.setClipRect(0, 0, w, flap_h)
        painter.drawText(tx, ty, self._text)
        painter.setClipRect(0, flap_h + gap, w, flap_h)
        painter.drawText(tx, ty, self._text)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 2))
        painter.drawLine(r, 2, w - r, 2)


class ClockView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: black;')
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setSpacing(30)
        self.hours = FlipFlap()
        self.mins = FlipFlap()
        row_layout.addWidget(self.hours)
        row_layout.addWidget(self.mins)
        layout.addWidget(row)
        self.dimmed = False

    def update_time(self):
        now = datetime.now()
        self.hours.set_text(now.strftime('%H'))
        self.mins.set_text(now.strftime('%M'))
        h = now.hour
        night = h >= 22 or h < 7
        if night != self.dimmed:
            self.dimmed = night
            self.hours.set_dimmed(night)
            self.mins.set_dimmed(night)


class CaptionView(QWidget):
    def __init__(self):
        super().__init__()
        self.font_sizes = {'S': 28, 'M': 36, 'L': 48}
        self.current_size = 'M'
        self.color_schemes = [
            ('W/B', '#ffffff', '#000000'),
            ('B/W', '#000000', '#ffffff'),
            ('Y/B', '#ffff00', '#000000'),
            ('G/B', '#00ff00', '#000000'),
        ]
        self.current_scheme = 0
        self.current_mode = 'online'

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 15, 25, 15)
        top_bar = QHBoxLayout()

        self.size_buttons = {}
        for size in ['S', 'M', 'L']:
            btn = QLabel(size)
            btn.setFixedSize(50, 50)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.mousePressEvent = lambda e, s=size: self.set_size(s)
            self.size_buttons[size] = btn
            top_bar.addWidget(btn)

        spacer = QLabel('  ')
        spacer.setFixedWidth(30)
        top_bar.addWidget(spacer)

        self.color_buttons = []
        for i, (name, text_col, bg_col) in enumerate(self.color_schemes):
            btn = QLabel('A')
            btn.setFixedSize(50, 50)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.setStyleSheet(f'background: {bg_col}; color: {text_col}; border-radius: 25px; font-size: 24px; font-weight: bold; border: 2px solid #444;')
            btn.mousePressEvent = lambda e, idx=i: self.set_color(idx)
            self.color_buttons.append(btn)
            top_bar.addWidget(btn)

        top_bar.addStretch()

        self.phone_icon = QLabel('📞')
        self.phone_icon.setStyleSheet('color: #00ff00; background: transparent; font-size: 40px;')
        self.phone_icon.hide()
        top_bar.addWidget(self.phone_icon)

        self.mode_btn = QLabel('OFFLINE')
        self.mode_btn.setFixedSize(140, 50)
        self.mode_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_btn.mousePressEvent = self.toggle_mode
        self.update_mode_button()
        top_bar.addWidget(self.mode_btn)

        self.status_label = QLabel('')
        top_bar.addWidget(self.status_label)

        layout.addLayout(top_bar)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.text.setStyleSheet('background: black; color: white; border: none;')
        self.text.verticalScrollBar().setStyleSheet(
            'QScrollBar:vertical { background: #222; width: 30px; border-radius: 15px; }'
            'QScrollBar::handle:vertical { background: #666; min-height: 60px; border-radius: 15px; }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }'
        )
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        QScroller.grabGesture(self.text.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        layout.addWidget(self.text)

        self.update_size_buttons()
        self.update_color_buttons()
        self.set_size('M')
        self.set_color(0)
        self._waiting_for_ready = False
        self._last_text_time = 0

    def toggle_mode(self, event):
        new_mode = 'online' if self.current_mode == 'offline' else 'offline'
        self.mode_btn.setText('⏳ WAIT...')
        self.mode_btn.setStyleSheet(
            'background: #333300; color: #ffff00; border-radius: 10px; '
            'font-size: 20px; font-weight: bold; border: 3px solid #ffff00;'
        )
        self.mode_btn.repaint()
        QApplication.processEvents()
        self.current_mode = new_mode
        self._waiting_for_ready = True
        switch_mode(new_mode)

    def update_mode_button(self):
        if self.current_mode == 'online':
            self.mode_btn.setText('🌐 ONLINE')
            self.mode_btn.setStyleSheet(
                'background: #004400; color: #00ff00; border-radius: 10px; '
                'font-size: 20px; font-weight: bold; border: 3px solid #00ff00;'
            )
        else:
            self.mode_btn.setText('💾 OFFLINE')
            self.mode_btn.setStyleSheet(
                'background: #442200; color: #ffaa00; border-radius: 10px; '
                'font-size: 20px; font-weight: bold; border: 3px solid #ffaa00;'
            )

    def set_mode(self, mode):
        self.current_mode = mode
        self.update_mode_button()

    def set_size(self, size):
        self.current_size = size
        self.text.setFont(QFont('Helvetica', self.font_sizes[size], QFont.Weight.Bold))
        self.update_size_buttons()

    def set_color(self, idx):
        self.current_scheme = idx
        name, text_col, bg_col = self.color_schemes[idx]
        self.text.setStyleSheet(f'background: {bg_col}; color: {text_col}; border: none;')
        self.setStyleSheet(f'background: {bg_col};')
        self.update_color_buttons()

    def update_size_buttons(self):
        for size, btn in self.size_buttons.items():
            if size == self.current_size:
                btn.setStyleSheet('background: #444; color: white; border-radius: 25px; font-size: 24px; font-weight: bold;')
            else:
                btn.setStyleSheet('background: #222; color: #888; border-radius: 25px; font-size: 24px;')

    def update_color_buttons(self):
        for i, btn in enumerate(self.color_buttons):
            name, text_col, bg_col = self.color_schemes[i]
            if i == self.current_scheme:
                btn.setStyleSheet(f'background: {bg_col}; color: {text_col}; border-radius: 25px; font-size: 24px; font-weight: bold; border: 3px solid #0af;')
            else:
                btn.setStyleSheet(f'background: {bg_col}; color: {text_col}; border-radius: 25px; font-size: 24px; font-weight: bold; border: 2px solid #444;')

    def set_status(self, status):
        if status == 'switching':
            self.status_label.setText('⏳')
            self.status_label.setStyleSheet('font-size: 30px; background: transparent;')
        elif status in ('vosk', 'deepgram', 'assemblyai', 'azure', 'google', 'openai', 'groq', 'interfaze', 'whisper', 'faster-whisper'):
            self.status_label.setText('🎤')
            self.status_label.setStyleSheet('font-size: 30px; background: transparent;')
        elif status == 'no-key':
            self.status_label.setText('⚠️ NO KEY')
            self.status_label.setStyleSheet('color: #ff0000; background: #330000; padding: 8px 15px; border-radius: 10px; font-size: 18px; font-weight: bold;')
        elif status == 'error':
            self.status_label.setText('⚠️ ERROR')
            self.status_label.setStyleSheet('color: #ff0000; background: #330000; padding: 8px 15px; border-radius: 10px; font-size: 18px; font-weight: bold;')
        elif status == 'restarting':
            self.status_label.setText('🔄')
            self.status_label.setStyleSheet('font-size: 30px; background: transparent;')

    def add_text(self, t):
        if self._waiting_for_ready:
            self._waiting_for_ready = False
            self.update_mode_button()
        c = self.text.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        now = time.time()
        has_newline = t.endswith('\n')
        t = t.rstrip('\n')
        if self.text.toPlainText():
            if self._last_text_time > 0 and (now - self._last_text_time) > 2:
                c.insertText('\n\n')
            else:
                c.insertText(' ')
        c.insertText(t)
        if has_newline:
            c.insertText('\n')
        self._last_text_time = now
        self.text.setTextCursor(c)
        self.text.ensureCursorVisible()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Gramps')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.showFullScreen()

        self.stack = QStackedWidget()
        self.stack.setStyleSheet('background: black; border: none;')
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet('background: black; border: none;')
        self.setCentralWidget(self.stack)

        self.clock_view = ClockView()
        self.caption_view = CaptionView()

        self.stack.addWidget(self.clock_view)
        self.stack.addWidget(self.caption_view)

        self.last_activity = 0
        self.phone_was_active = False
        self._pending_restart = None

        # Main tick timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

        # Phone check timer
        self.mute_timer = QTimer()
        self.mute_timer.timeout.connect(self.check_muted)
        self.mute_timer.start(500)

        # Health check timer - monitors transcription thread
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self.health_check)
        self.health_timer.start(5000)

        # Connect signals
        emitter.new_text.connect(self.on_text)
        emitter.status_changed.connect(self.on_status_changed)
        emitter.mode_changed.connect(self.on_mode_changed)
        emitter.mode_ready.connect(self.on_mode_ready)
        emitter.thread_died.connect(self.on_thread_died)

        self.stack.setCurrentIndex(0)

    def signal_activity(self):
        self.last_activity = time.time()
        if self.stack.currentIndex() != 1:
            self.stack.setCurrentIndex(1)

    def tick(self):
        self.clock_view.update_time()
        if self.last_activity > 0:
            age = time.time() - self.last_activity
            if age > SILENCE_TIMEOUT and self.stack.currentIndex() == 1:
                self.stack.setCurrentIndex(0)

    def health_check(self):
        """Monitor transcription health and restart if needed"""
        if state.is_restarting() or state.is_stopped():
            return

        problem = None

        if not state.thread_alive:
            problem = "thread dead"
        elif not state.proc_alive():
            problem = "arecord subprocess dead"
        elif state.last_text_time > 0:
            stale_time = time.time() - state.last_text_time
            if stale_time > 120:
                problem = f"no transcription for {stale_time:.0f}s"

        if not problem:
            print(f"heartbeat: gen={state.generation} mode={state.mode} thread={state.thread_alive} proc={state.proc_alive()}", flush=True)
            return

        if problem:
            if state.can_restart():
                state.set_restarting(True)
                count = state.increment_restart()
                gen = state.generation
                print(f"Health check: {problem}, restarting (attempt {count}, gen={gen})...", flush=True)
                self.caption_view.set_status('restarting')
                mode = state.mode
                if state.thread_alive:
                    stop_transcription()
                def do_health_restart(expected_gen=gen):
                    if state.generation != expected_gen:
                        print(f"Health restart skipped: gen changed {expected_gen}->{state.generation}", flush=True)
                        state.set_restarting(False)
                        return
                    start_transcription(mode)
                    state.set_restarting(False)
                QTimer.singleShot(2000, do_health_restart)
            else:
                print(f"Health check: {problem}, max restarts exceeded, giving up", flush=True)
                self.caption_view.set_status('error')


    def on_thread_died(self, mode):
        """Handle thread death signal with automatic fallback"""
        if state.is_restarting():
            print("Restart already in progress, skipping thread_died signal", flush=True)
            return
        if state.is_stopped():
            return
        if state.can_restart():
            state.set_restarting(True)
            count = state.increment_restart()
            gen = state.generation

            if mode == 'online' and count >= 3 and not state.use_phone_audio:
                print(f"Online mode failed {count} times, falling back to offline (gen={gen})", flush=True)
                self.caption_view.set_status('fallback')
                def do_fallback(expected_gen=gen):
                    if state.generation != expected_gen:
                        state.set_restarting(False)
                        return
                    state.reset_restart_count()
                    start_transcription('offline')
                    self.caption_view.set_mode('offline')
                    state.set_restarting(False)
                QTimer.singleShot(2000, do_fallback)
            else:
                print(f"Thread died (gen={gen}), scheduling restart (attempt {count})...", flush=True)
                self.caption_view.set_status('restarting')
                def do_restart(expected_gen=gen):
                    if state.generation != expected_gen:
                        state.set_restarting(False)
                        return
                    start_transcription(mode)
                    state.set_restarting(False)
                QTimer.singleShot(3000, do_restart)
        else:
            print("Thread died but max restarts exceeded, giving up", flush=True)
            self.caption_view.set_status('error')


    def check_muted(self):
        """Check phone status and handle audio device switching"""
        try:
            phone_active = False
            if os.path.exists(PHONE_MUTED_FILE):
                with open(PHONE_MUTED_FILE, 'r') as f:
                    c = f.read().strip()
                    phone_active = c == '1'

            # If using phone audio, check for silence to end call
            if state.use_phone_audio and state.last_phone_speech > 0:
                silence_duration = time.time() - state.last_phone_speech
                if silence_duration > PHONE_SILENCE_TIMEOUT:
                    print(f'Phone silent for {silence_duration:.0f}s - ending call', flush=True)
                    write_phone_status(False)
                    phone_active = False

            if phone_active:
                self.caption_view.phone_icon.show()
                if not self.phone_was_active:
                    state.use_phone_audio = True
                    state.last_phone_speech = time.time()
                    state.last_text_time = time.time()
                    if not state.is_restarting():
                        print('Phone active - restarting with phone recorder', flush=True)
                        state.set_restarting(True)
                        stop_transcription()
                        def do_phone_start():
                            start_transcription('online')
                            state.set_restarting(False)
                        QTimer.singleShot(500, do_phone_start)
                    else:
                        print('Phone active - restart in progress, waiting', flush=True)
                self.phone_was_active = True
            else:
                self.caption_view.phone_icon.hide()
                if self.phone_was_active:
                    state.use_phone_audio = False
                    if not state.is_restarting():
                        print('Phone ended - restarting with room mic', flush=True)
                        state.set_restarting(True)
                        stop_transcription()
                        def do_room_start():
                            start_transcription('online')
                            state.set_restarting(False)
                        QTimer.singleShot(500, do_room_start)
                    else:
                        print('Phone ended - restart in progress, waiting', flush=True)
                self.phone_was_active = False

        except Exception as e:
            print(f'check_muted error: {e}', flush=True)


    def on_text(self, t):
        self.signal_activity()
        self.caption_view.add_text(t)
        if state.use_phone_audio:
            state.last_phone_speech = time.time()

    def on_status_changed(self, status):
        self.caption_view.set_status(status)

    def on_mode_changed(self, mode):
        self.caption_view.set_mode(mode)

    def on_mode_ready(self, mode):
        self.caption_view.update_mode_button()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            QApplication.quit()


def clear_stale_state():
    """Clear stale state files on startup"""
    print("Clearing stale state...", flush=True)
    try:
        # Clear phone muted state
        if os.path.exists(PHONE_MUTED_FILE):
            with open(PHONE_MUTED_FILE, 'w') as f:
                f.write('0')
            print(f"  Cleared {PHONE_MUTED_FILE}", flush=True)
    except Exception as e:
        print(f"  Error clearing state: {e}", flush=True)


def main():
    print('='*50, flush=True)
    print('Starting Gramps Captions (BULLETPROOF VERSION)', flush=True)
    print('='*50, flush=True)

    clear_stale_state()
    cleanup_audio_processes()
    ensure_mic_volume()

    # Create QApplication FIRST — Qt signals require this
    app = QApplication(sys.argv)

    try:
        import systemd.daemon
        systemd.daemon.notify('READY=1')
    except:
        pass

    start_transcription('online')

    def watchdog():
        try:
            import systemd.daemon
            while True:
                time.sleep(10)
                systemd.daemon.notify('WATCHDOG=1')
        except:
            pass
    threading.Thread(target=watchdog, daemon=True).start()

    win = MainWindow()
    win.show()
    sys.exit(app.exec())



if __name__ == '__main__':
    main()
