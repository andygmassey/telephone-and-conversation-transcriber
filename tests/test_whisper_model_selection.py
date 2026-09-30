"""Unit tests for Whisper model selection, validation, and configuration persistence."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import whisper_config
from whisper_config import (
    DEFAULT_WHISPER_MODEL,
    ALLOWED_WHISPER_MODELS,
    validate_whisper_model,
)
from setup import app as setup_app
import caption_app


class TestWhisperModelValidation(unittest.TestCase):
    """Test validation and normalization of Whisper model names."""

    def test_default_model_is_tiny(self):
        """Default Whisper model must be 'tiny' for Raspberry Pi compatibility."""
        self.assertEqual(DEFAULT_WHISPER_MODEL, 'tiny')

    def test_allowed_models_list(self):
        """Allowed models must include tiny, base, small, medium, and large."""
        expected = ('tiny', 'base', 'small', 'medium', 'large')
        self.assertEqual(ALLOWED_WHISPER_MODELS, expected)

    def test_valid_models(self):
        """All allowed model names should be accepted as-is."""
        for model in ALLOWED_WHISPER_MODELS:
            self.assertEqual(validate_whisper_model(model), model)

    def test_case_insensitivity(self):
        """Model validation should be case-insensitive."""
        self.assertEqual(validate_whisper_model('TINY'), 'tiny')
        self.assertEqual(validate_whisper_model('Base'), 'base')
        self.assertEqual(validate_whisper_model('SMALL'), 'small')
        self.assertEqual(validate_whisper_model('MeDiUm'), 'medium')
        self.assertEqual(validate_whisper_model('LARGE'), 'large')

    def test_whitespace_stripping(self):
        """Leading and trailing whitespace should be stripped."""
        self.assertEqual(validate_whisper_model('  tiny  '), 'tiny')
        self.assertEqual(validate_whisper_model('\tbase\n'), 'base')
        self.assertEqual(validate_whisper_model('  large  '), 'large')

    def test_english_variant_normalization(self):
        """.en model variants should normalize to their base model size."""
        self.assertEqual(validate_whisper_model('tiny.en'), 'tiny')
        self.assertEqual(validate_whisper_model('base.en'), 'base')
        self.assertEqual(validate_whisper_model('small.en'), 'small')
        self.assertEqual(validate_whisper_model('medium.en'), 'medium')
        self.assertEqual(validate_whisper_model('TINY.EN'), 'tiny')

    def test_invalid_models_fallback_to_default(self):
        """Unknown or disallowed model names should fall back to 'tiny'."""
        self.assertEqual(validate_whisper_model('ultra'), 'tiny')
        self.assertEqual(validate_whisper_model('huge'), 'tiny')
        self.assertEqual(validate_whisper_model('whisper-v3'), 'tiny')
        self.assertEqual(validate_whisper_model('turbo'), 'tiny')
        self.assertEqual(validate_whisper_model('invalid_model'), 'tiny')

    def test_empty_and_non_string_fallback(self):
        """Empty string, None, and non-string inputs should fall back to 'tiny'."""
        self.assertEqual(validate_whisper_model(''), 'tiny')
        self.assertEqual(validate_whisper_model('   '), 'tiny')
        self.assertEqual(validate_whisper_model(None), 'tiny')
        self.assertEqual(validate_whisper_model(123), 'tiny')
        self.assertEqual(validate_whisper_model([]), 'tiny')
        self.assertEqual(validate_whisper_model({}), 'tiny')


class TestSetupAppPersistence(unittest.TestCase):
    """Test configuration saving and loading via setup/app.py."""

    def setUp(self):
        self.app = setup_app.app
        self.client = self.app.test_client()
        self.test_dir = f"/tmp/transcriber_test_{os.getpid()}_{id(self)}"
        os.makedirs(self.test_dir, exist_ok=True)
        self.config_path = os.path.join(self.test_dir, "config.json")
        self.credentials_path = os.path.join(self.test_dir, "credentials.py")

        self.orig_config_path = setup_app.CONFIG_PATH
        self.orig_credentials_path = setup_app.CREDENTIALS_PATH
        setup_app.CONFIG_PATH = self.config_path
        setup_app.CREDENTIALS_PATH = self.credentials_path

    def tearDown(self):
        setup_app.CONFIG_PATH = self.orig_config_path
        setup_app.CREDENTIALS_PATH = self.orig_credentials_path

    def test_save_and_load_config_with_whisper_model(self):
        """save_config persists whisper_model and load_config retrieves it."""
        data = {'whisper_model': 'medium', 'offline_model': 'faster-whisper'}
        setup_app.save_config(data)

        loaded = setup_app.load_config()
        self.assertEqual(loaded.get('whisper_model'), 'medium')

    def test_save_credentials_with_whisper_model(self):
        """save_credentials writes WHISPER_MODEL to credentials.py."""
        setup_app.save_credentials(whisper_model='large')
        self.assertTrue(os.path.exists(self.credentials_path))

        with open(self.credentials_path) as f:
            content = f.read()
        self.assertIn('WHISPER_MODEL = "large"', content)

    def test_save_credentials_combined(self):
        """save_credentials writes both DEEPGRAM_KEY and WHISPER_MODEL."""
        setup_app.save_credentials(deepgram_key='test-key-123', whisper_model='small')
        with open(self.credentials_path) as f:
            content = f.read()
        self.assertIn('DEEPGRAM_KEY = "test-key-123"', content)
        self.assertIn('WHISPER_MODEL = "small"', content)

    def test_api_save_persists_valid_whisper_model(self):
        """POST /api/save validates and saves chosen whisper_model to config and credentials."""
        payload = {
            'room_device': 'hw:0,0',
            'speech_mode': 'offline',
            'offline_model': 'faster-whisper',
            'whisper_model': 'base',
        }
        resp = self.client.post('/api/save', json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('ok'))

        # Check config.json
        loaded = setup_app.load_config()
        self.assertEqual(loaded.get('whisper_model'), 'base')

        # Check credentials.py
        with open(self.credentials_path) as f:
            content = f.read()
        self.assertIn('WHISPER_MODEL = "base"', content)

    def test_api_save_invalid_model_falls_back_to_tiny(self):
        """POST /api/save with invalid whisper_model falls back to 'tiny'."""
        payload = {
            'room_device': 'hw:0,0',
            'speech_mode': 'offline',
            'offline_model': 'faster-whisper',
            'whisper_model': 'nonexistent_model',
        }
        resp = self.client.post('/api/save', json=payload)
        self.assertEqual(resp.status_code, 200)

        loaded = setup_app.load_config()
        self.assertEqual(loaded.get('whisper_model'), 'tiny')

        with open(self.credentials_path) as f:
            content = f.read()
        self.assertIn('WHISPER_MODEL = "tiny"', content)

    def test_api_save_omitted_model_defaults_to_tiny(self):
        """POST /api/save without whisper_model defaults to 'tiny'."""
        payload = {
            'room_device': 'hw:0,0',
            'speech_mode': 'offline',
            'offline_model': 'faster-whisper',
        }
        resp = self.client.post('/api/save', json=payload)
        self.assertEqual(resp.status_code, 200)

        loaded = setup_app.load_config()
        self.assertEqual(loaded.get('whisper_model'), 'tiny')

    def test_api_save_normalizes_case_and_variants(self):
        """POST /api/save normalizes uppercase and .en variants."""
        payload = {
            'room_device': 'hw:0,0',
            'speech_mode': 'offline',
            'offline_model': 'faster-whisper',
            'whisper_model': 'SMALL.EN',
        }
        resp = self.client.post('/api/save', json=payload)
        self.assertEqual(resp.status_code, 200)

        loaded = setup_app.load_config()
        self.assertEqual(loaded.get('whisper_model'), 'small')

    def test_index_page_contains_whisper_model_options(self):
        """GET / renders index.html containing the whisper-model selector with all options."""
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('id="whisper-model"', html)
        self.assertIn('value="tiny"', html)
        self.assertIn('value="base"', html)
        self.assertIn('value="small"', html)
        self.assertIn('value="medium"', html)
        self.assertIn('value="large"', html)
        self.assertIn('recommended for Raspberry Pi', html)


class TestCaptionAppModelResolution(unittest.TestCase):
    """Test Whisper model resolution hierarchy in caption_app.py."""

    def setUp(self):
        self.test_dir = f"/tmp/caption_test_{os.getpid()}_{id(self)}"
        os.makedirs(self.test_dir, exist_ok=True)
        self.config_path = os.path.join(self.test_dir, "config.json")
        self.orig_config_path = caption_app.CONFIG_PATH
        caption_app.CONFIG_PATH = self.config_path

    def tearDown(self):
        caption_app.CONFIG_PATH = self.orig_config_path
        if 'WHISPER_MODEL' in os.environ:
            del os.environ['WHISPER_MODEL']

    def test_get_whisper_model_default(self):
        """get_whisper_model defaults to 'tiny' when no configuration exists."""
        with patch.dict(sys.modules, {'credentials': None}):
            model = caption_app.get_whisper_model()
            self.assertEqual(model, 'tiny')

    def test_get_whisper_model_from_config(self):
        """get_whisper_model reads model from config.json."""
        with open(self.config_path, 'w') as f:
            json.dump({'whisper_model': 'medium'}, f)

        with patch.dict(sys.modules, {'credentials': None}):
            model = caption_app.get_whisper_model()
            self.assertEqual(model, 'medium')

    def test_get_whisper_model_from_credentials(self):
        """get_whisper_model prefers credentials.WHISPER_MODEL when present."""
        with open(self.config_path, 'w') as f:
            json.dump({'whisper_model': 'small'}, f)

        mock_creds = MagicMock()
        mock_creds.WHISPER_MODEL = 'large'
        with patch.dict(sys.modules, {'credentials': mock_creds}):
            model = caption_app.get_whisper_model()
            self.assertEqual(model, 'large')

    def test_get_whisper_model_from_env(self):
        """get_whisper_model falls back to WHISPER_MODEL environment variable."""
        os.environ['WHISPER_MODEL'] = 'base'
        with patch.dict(sys.modules, {'credentials': None}):
            model = caption_app.get_whisper_model()
            self.assertEqual(model, 'base')

    def test_get_whisper_model_en_variant_normalized(self):
        """get_whisper_model normalizes .en variant from config."""
        with open(self.config_path, 'w') as f:
            json.dump({'whisper_model': 'medium.en'}, f)

        with patch.dict(sys.modules, {'credentials': None}):
            model = caption_app.get_whisper_model()
            self.assertEqual(model, 'medium')

    def test_faster_whisper_thread_instantiates_selected_model(self):
        """faster_whisper_thread initializes WhisperModel with get_whisper_model()."""
        with open(self.config_path, 'w') as f:
            json.dump({'whisper_model': 'base'}, f)

        mock_whisper_cls = MagicMock()
        mock_whisper_module = MagicMock(WhisperModel=mock_whisper_cls)
        mock_np = MagicMock()

        # Stop immediately when arecord would start
        caption_app.state.stop()

        with patch.dict(sys.modules, {
            'credentials': None,
            'faster_whisper': mock_whisper_module,
            'numpy': mock_np,
        }):
            try:
                caption_app.faster_whisper_thread()
            except Exception:
                pass

        mock_whisper_cls.assert_called_once_with(
            'base',
            device='cpu',
            compute_type='int8',
            cpu_threads=4,
            num_workers=1
        )

    def test_whisper_cpp_candidates_include_selected_model(self):
        """Verify model candidate paths for whisper.cpp prioritize the configured model."""
        with open(self.config_path, 'w') as f:
            json.dump({'whisper_model': 'large'}, f)

        with patch.dict(sys.modules, {'credentials': None}):
            selected_model = caption_app.get_whisper_model()
            candidates = [
                os.path.expanduser(f'~/whisper.cpp/models/ggml-{selected_model}.en-q5_0.bin'),
                os.path.expanduser(f'~/whisper.cpp/models/ggml-{selected_model}.en.bin'),
                os.path.expanduser(f'~/whisper.cpp/models/ggml-{selected_model}.bin'),
                os.path.expanduser(f'~/whisper.cpp/models/ggml-{selected_model}-q5_0.bin'),
                os.path.expanduser('~/whisper.cpp/models/ggml-base.en-q5_0.bin'),
            ]
            self.assertEqual(selected_model, 'large')
            self.assertTrue(any('ggml-large' in c for c in candidates))


if __name__ == '__main__':
    unittest.main()

