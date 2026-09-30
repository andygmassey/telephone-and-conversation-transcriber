"""Unit tests for Remote / Custom OpenAI-compatible Whisper STT endpoint support.

Verifies:
- URL validation and normalization
- Payload and file construction
- Authorization header handling
- Mock HTTP transcription handling (OpenAI JSON, alternative keys, raw text)
- Error resilience (HTTP errors, timeouts, connection errors)
- Integration with caption_app threads, state, and UI status
- Integration with setup wizard (config persistence, credentials, status endpoint)
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure repository root is on sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for path in [repo_root, '/workspace/build_transcriber_6']:
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

import caption_app
from caption_app import (
    normalize_remote_url,
    validate_remote_url,
    build_remote_headers,
    build_remote_payload,
    build_remote_files,
    transcribe_remote,
    remote_thread,
    _make_wav,
)
from setup import app as setup_app


class TestRemoteSTTUrlHandling(unittest.TestCase):
    """Test URL normalization and validation logic."""

    def test_normalize_bare_host_port(self):
        url = "http://192.168.1.100:8000"
        expected = "http://192.168.1.100:8000/v1/audio/transcriptions"
        self.assertEqual(normalize_remote_url(url), expected)

    def test_normalize_trailing_slash(self):
        url = "http://192.168.1.100:8000/"
        expected = "http://192.168.1.100:8000/v1/audio/transcriptions"
        self.assertEqual(normalize_remote_url(url), expected)

    def test_normalize_v1_suffix(self):
        url = "http://192.168.1.100:8000/v1"
        expected = "http://192.168.1.100:8000/v1/audio/transcriptions"
        self.assertEqual(normalize_remote_url(url), expected)

    def test_normalize_full_endpoint(self):
        url = "http://192.168.1.100:8000/v1/audio/transcriptions"
        self.assertEqual(normalize_remote_url(url), url)

    def test_normalize_missing_scheme(self):
        url = "192.168.1.50:11434"
        expected = "http://192.168.1.50:11434/v1/audio/transcriptions"
        self.assertEqual(normalize_remote_url(url), expected)

    def test_normalize_custom_path_with_audio_transcriptions(self):
        url = "https://ai.example.lan:8443/custom/v1/audio/transcriptions"
        self.assertEqual(normalize_remote_url(url), url)

    def test_normalize_empty_and_whitespace(self):
        self.assertEqual(normalize_remote_url(""), "")
        self.assertEqual(normalize_remote_url("   "), "")
        self.assertEqual(normalize_remote_url(None), "")

    def test_validate_valid_urls(self):
        valid, msg = validate_remote_url("http://192.168.1.100:8000/v1/audio/transcriptions")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

        valid, msg = validate_remote_url("https://remote-whisper.example.com")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_validate_empty_url(self):
        valid, msg = validate_remote_url("")
        self.assertFalse(valid)
        self.assertIn("empty", msg.lower())

        valid, msg = validate_remote_url("   ")
        self.assertFalse(valid)

    def test_validate_invalid_scheme(self):
        valid, msg = validate_remote_url("ftp://example.com/v1/audio/transcriptions")
        self.assertFalse(valid)
        self.assertIn("scheme", msg.lower())


class TestRemoteSTTHeadersAndPayload(unittest.TestCase):
    """Test header generation and payload construction."""

    def test_headers_without_api_key(self):
        self.assertEqual(build_remote_headers(None), {})
        self.assertEqual(build_remote_headers(""), {})
        self.assertEqual(build_remote_headers("   "), {})

    def test_headers_with_api_key(self):
        headers = build_remote_headers("secret-key-123")
        self.assertEqual(headers, {"Authorization": "Bearer secret-key-123"})

    def test_headers_with_whitespace_key(self):
        headers = build_remote_headers("  secret-key-123  ")
        self.assertEqual(headers, {"Authorization": "Bearer secret-key-123"})

    def test_payload_default_model(self):
        payload = build_remote_payload()
        self.assertEqual(payload, {"model": "whisper-1", "language": "en"})

    def test_payload_custom_model_and_language(self):
        payload = build_remote_payload(model="whisper-large-v3", language="es")
        self.assertEqual(payload, {"model": "whisper-large-v3", "language": "es"})

    def test_payload_empty_model_falls_back_to_default(self):
        payload = build_remote_payload(model="")
        self.assertEqual(payload["model"], "whisper-1")

    def test_build_files_produces_wav(self):
        dummy_audio = b"\x00\x00" * 800  # 800 samples = 1600 bytes
        files = build_remote_files(dummy_audio, 16000)
        self.assertIn("file", files)
        filename, data, mime = files["file"]
        self.assertEqual(filename, "chunk.wav")
        self.assertEqual(mime, "audio/wav")
        self.assertTrue(data.startswith(b"RIFF"))
        self.assertIn(b"WAVE", data[:12])
        self.assertIn(b"fmt ", data[:20])


class TestRemoteSTTTranscription(unittest.TestCase):
    """Test mock HTTP transcription posting, parsing, and resilience."""

    @patch("requests.post")
    def test_transcribe_successful_openai_json(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"text": "Hello world from remote AI"}'
        mock_resp.json.return_value = {"text": "Hello world from remote AI"}
        mock_post.return_value = mock_resp

        audio_bytes = b"\x00\x00" * 1600
        result = transcribe_remote(
            audio_bytes,
            sample_rate=16000,
            endpoint_url="http://192.168.1.50:8000",
            model="whisper-1",
            api_key="sk-test",
        )

        self.assertEqual(result, "Hello world from remote AI")
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], "http://192.168.1.50:8000/v1/audio/transcriptions")
        self.assertEqual(call_kwargs["headers"], {"Authorization": "Bearer sk-test"})
        self.assertEqual(call_kwargs["data"], {"model": "whisper-1", "language": "en"})
        self.assertIn("file", call_kwargs["files"])

    @patch("requests.post")
    def test_transcribe_alternative_json_key(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"transcription": "Alternative transcription format"}'
        mock_resp.json.return_value = {"transcription": "Alternative transcription format"}
        mock_post.return_value = mock_resp

        audio_bytes = b"\x00\x00" * 800
        result = transcribe_remote(
            audio_bytes,
            sample_rate=16000,
            endpoint_url="http://192.168.1.50:8000/v1/audio/transcriptions",
        )
        self.assertEqual(result, "Alternative transcription format")

    @patch("requests.post")
    def test_transcribe_raw_text_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "Raw text transcription\n"
        mock_resp.json.side_effect = ValueError("Not JSON")
        mock_post.return_value = mock_resp

        audio_bytes = b"\x00\x00" * 800
        result = transcribe_remote(
            audio_bytes,
            sample_rate=16000,
            endpoint_url="http://192.168.1.50:8000",
        )
        self.assertEqual(result, "Raw text transcription")

    def test_transcribe_missing_url_raises(self):
        with self.assertRaises(ValueError):
            transcribe_remote(b"\x00\x00", 16000, endpoint_url="")

    @patch("requests.post")
    def test_transcribe_http_error(self, mock_post):
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_resp

        with self.assertRaises(requests.exceptions.HTTPError):
            transcribe_remote(
                b"\x00\x00",
                16000,
                endpoint_url="http://192.168.1.50:8000",
                api_key="bad-key",
            )

    @patch("requests.post")
    def test_transcribe_connection_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(requests.exceptions.ConnectionError):
            transcribe_remote(
                b"\x00\x00",
                16000,
                endpoint_url="http://192.168.1.50:8000",
            )

    @patch("requests.post")
    def test_transcribe_timeout_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.Timeout("Read timeout")

        with self.assertRaises(requests.exceptions.Timeout):
            transcribe_remote(
                b"\x00\x00",
                16000,
                endpoint_url="http://192.168.1.50:8000",
            )


class TestRemoteSTTAppIntegration(unittest.TestCase):
    """Test remote thread handling and UI status wiring in caption_app."""

    def test_remote_thread_missing_url_signals_no_url(self):
        with patch.dict(caption_app.CONFIG, {"remote_stt_url": "", "remote_url": ""}, clear=False), \
             patch("caption_app.REMOTE_STT_URL", None), \
             patch.object(caption_app.emitter.status_changed, "emit") as mock_emit:
            remote_thread()
            mock_emit.assert_called_with("no-url")
            self.assertFalse(caption_app.state.thread_alive)

    @patch("caption_app._chunked_api_thread")
    def test_remote_thread_invokes_chunked_api(self, mock_chunked):
        with patch.dict(caption_app.CONFIG, {
            "remote_stt_url": "http://192.168.1.100:8000",
            "remote_stt_model": "whisper-large-v3",
            "remote_stt_key": "my-secret",
        }, clear=False):
            remote_thread()
            mock_chunked.assert_called_once()
            args, _ = mock_chunked.call_args
            self.assertEqual(args[0], "Remote")
            self.assertTrue(callable(args[1]))

    def test_caption_view_status_handler(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""
                self.style = ""
            def setText(self, t):
                self.text = t
            def setStyleSheet(self, s):
                self.style = s

        label = DummyLabel()
        view = caption_app.CaptionView.__new__(caption_app.CaptionView)
        view.status_label = label

        # Status 'remote' sets active transcription indicator
        view.set_status("remote")
        self.assertTrue(len(label.text) > 0)
        self.assertNotEqual(label.text, "NO URL")

        # Status 'no-url' sets NO URL warning
        view.set_status("no-url")
        self.assertEqual(label.text, "NO URL")
        self.assertIn("#ff0000", label.style)

    @patch("threading.Thread")
    @patch("caption_app.ensure_mic_volume")
    def test_start_transcription_selects_remote_thread(self, mock_volume, mock_thread):
        with patch.dict(caption_app.CONFIG, {"stt_provider": "remote"}, clear=False):
            caption_app.start_transcription("online")
            mock_thread.assert_called_once()
            _, kwargs = mock_thread.call_args
            self.assertEqual(kwargs["target"], caption_app.remote_thread)

    @patch("threading.Thread")
    @patch("caption_app.ensure_mic_volume")
    def test_start_transcription_with_remote_mode(self, mock_volume, mock_thread):
        with patch.dict(caption_app.CONFIG, {}, clear=False):
            caption_app.start_transcription("remote")
            mock_thread.assert_called_once()
            _, kwargs = mock_thread.call_args
            self.assertEqual(kwargs["target"], caption_app.remote_thread)


class TestSetupWizardConfigPersistence(unittest.TestCase):
    """Test configuration saving, loading, and status in setup wizard."""

    def setUp(self):
        self.client = setup_app.app.test_client()
        setup_app.app.testing = True

    @patch("setup.app.save_config")
    @patch("setup.app.save_credentials")
    @patch("subprocess.run")
    def test_api_save_persists_remote_stt_settings(self, mock_subproc, mock_creds, mock_save):
        payload = {
            "speech_mode": "online",
            "stt_provider": "remote",
            "remote_stt_url": "http://192.168.1.100:8000/v1/audio/transcriptions",
            "remote_stt_model": "whisper-large-v3",
            "remote_stt_key": "custom-token-xyz",
            "room_device": "hw:1,0",
            "phone_device": "",
            "gateway_ip": "",
        }

        resp = self.client.post("/api/save", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))

        mock_save.assert_called_once()
        saved_config = mock_save.call_args[0][0]
        self.assertEqual(saved_config["stt_provider"], "remote")
        self.assertEqual(saved_config["remote_stt_url"], "http://192.168.1.100:8000/v1/audio/transcriptions")
        self.assertEqual(saved_config["remote_stt_model"], "whisper-large-v3")
        self.assertEqual(saved_config["remote_stt_key"], "custom-token-xyz")

        mock_creds.assert_called_once_with(
            remote_stt_url="http://192.168.1.100:8000/v1/audio/transcriptions",
            remote_stt_key="custom-token-xyz",
            remote_stt_model="whisper-large-v3",
        )

    @patch("setup.app.load_config")
    @patch("setup.app.get_service_status")
    def test_api_status_configured_with_remote_stt(self, mock_status, mock_load):
        mock_status.return_value = "active"
        mock_load.return_value = {
            "remote_stt_url": "http://192.168.1.100:8000",
            "stt_provider": "remote",
        }

        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["configured"])

    def test_save_credentials_file_content(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            test_creds_path = os.path.join(tmpdir, "credentials.py")
            with patch("setup.app.CREDENTIALS_PATH", test_creds_path):
                setup_app.save_credentials(
                    remote_stt_url="http://10.0.0.5:8000/v1/audio/transcriptions",
                    remote_stt_key="my-key-abc",
                    remote_stt_model="whisper-base",
                )
                self.assertTrue(os.path.exists(test_creds_path))
                with open(test_creds_path) as f:
                    content = f.read()
                self.assertIn('REMOTE_STT_URL = "http://10.0.0.5:8000/v1/audio/transcriptions"', content)
                self.assertIn('REMOTE_STT_KEY = "my-key-abc"', content)
                self.assertIn('REMOTE_STT_MODEL = "whisper-base"', content)

    @patch("setup.app.load_config")
    def test_index_route_renders_with_remote_config(self, mock_load):
        mock_load.return_value = {
            "stt_provider": "remote",
            "remote_stt_url": "http://192.168.1.50:8000/v1/audio/transcriptions",
        }
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("provider-remote", html)
        self.assertIn("remote-stt-url", html)


if __name__ == "__main__":
    unittest.main()
