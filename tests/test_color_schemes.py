"""
Unit tests for accessible high-contrast color scheme presets and configuration persistence.
Tests WCAG AAA contrast ratio compliance (>= 7:1), preset lookup, cycling, and config saving.
"""

import json
import os
import shutil
import tempfile
import unittest

import color_schemes
from color_schemes import (
    COLOR_SCHEMES,
    DEFAULT_COLOR_SCHEME,
    COLOR_SCHEME_KEYS,
    calculate_luminance,
    calculate_contrast_ratio,
    is_wcag_aaa,
    is_wcag_aa,
    get_color_scheme,
    get_next_scheme_key,
    normalize_hex,
)
import caption_app
from setup import app as setup_app


class DummyKeyEvent:
    """Mock Qt key event for testing keyboard handlers."""
    def __init__(self, key_code):
        self._key = key_code

    def key(self):
        return self._key


class TestColorContrastWCAG(unittest.TestCase):
    """Verify WCAG relative luminance and contrast ratio calculations against AAA standard."""

    def test_luminance_extremes(self):
        """Relative luminance of pure black is 0.0, pure white is 1.0."""
        self.assertAlmostEqual(calculate_luminance("#000000"), 0.0, places=4)
        self.assertAlmostEqual(calculate_luminance("#FFFFFF"), 1.0, places=4)

    def test_luminance_normalization(self):
        """Luminance supports 3-character hex and case insensitivity."""
        self.assertAlmostEqual(calculate_luminance("#fff"), 1.0, places=4)
        self.assertAlmostEqual(calculate_luminance("000"), 0.0, places=4)
        self.assertAlmostEqual(calculate_luminance("ffffff"), 1.0, places=4)

    def test_invalid_hex_raises_value_error(self):
        """Invalid hex strings raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_luminance("not-a-color")
        with self.assertRaises(ValueError):
            calculate_luminance("#12")
        with self.assertRaises(ValueError):
            calculate_luminance("#GGGGGG")

    def test_contrast_ratio_formula(self):
        """Black on white contrast ratio is 21:1; identical colors ratio is 1:1."""
        self.assertAlmostEqual(calculate_contrast_ratio("#FFFFFF", "#000000"), 21.0, places=2)
        self.assertAlmostEqual(calculate_contrast_ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(calculate_contrast_ratio("#123456", "#123456"), 1.0, places=2)

    def test_all_presets_meet_wcag_aaa(self):
        """
        WCAG AAA requires contrast ratio >= 7.0:1 for normal text.
        All defined accessible presets must meet or exceed this threshold.
        """
        for key, scheme in COLOR_SCHEMES.items():
            fg = scheme["text_color"]
            bg = scheme["background_color"]
            ratio = calculate_contrast_ratio(fg, bg)
            meets_aaa = is_wcag_aaa(fg, bg)
            self.assertTrue(
                meets_aaa,
                f"Preset '{key}' ({fg} on {bg}) has contrast ratio {ratio:.2f}:1, which is below 7.0:1",
            )
            self.assertGreaterEqual(ratio, 7.0)

    def test_recommended_presets_specific_contrast_values(self):
        """Verify contrast ratios for specific ADA / low vision presets."""
        # 1. High Contrast Light on Dark (White on Black)
        w_b = calculate_contrast_ratio("#FFFFFF", "#000000")
        self.assertAlmostEqual(w_b, 21.0, places=1)
        self.assertTrue(w_b >= 7.0)

        # 2. High Contrast Yellow on Blue (text #FFFF00, background #000080)
        y_b = calculate_contrast_ratio("#FFFF00", "#000080")
        self.assertGreaterEqual(y_b, 14.0)
        self.assertTrue(y_b >= 7.0)

        # Alternative Yellow on Blue #001F3F
        y_b_alt = calculate_contrast_ratio("#FFFF00", "#001F3F")
        self.assertGreaterEqual(y_b_alt, 14.0)

        # 3. High Contrast Green on Black (text #00FF66, background #000000)
        g_b = calculate_contrast_ratio("#00FF66", "#000000")
        self.assertGreaterEqual(g_b, 15.0)
        self.assertTrue(g_b >= 7.0)

        # 4. High Contrast Dark on Light (Black on White)
        b_w = calculate_contrast_ratio("#000000", "#FFFFFF")
        self.assertAlmostEqual(b_w, 21.0, places=1)
        self.assertTrue(b_w >= 7.0)

    def test_low_contrast_fails_aaa(self):
        """Verify is_wcag_aaa correctly identifies failing combinations."""
        # Gray on slightly darker gray
        self.assertFalse(is_wcag_aaa("#777777", "#888888"))
        # Navy on black
        self.assertFalse(is_wcag_aaa("#000080", "#000000"))


class TestPresetDefinitions(unittest.TestCase):
    """Verify structure and content of COLOR_SCHEMES."""

    def test_default_scheme(self):
        """Default color scheme is white_on_black."""
        self.assertEqual(DEFAULT_COLOR_SCHEME, "white_on_black")
        self.assertIn(DEFAULT_COLOR_SCHEME, COLOR_SCHEMES)

    def test_preset_keys(self):
        """Ensure all 4 requested presets are present."""
        expected_keys = [
            "white_on_black",
            "yellow_on_blue",
            "green_on_black",
            "black_on_white",
        ]
        for key in expected_keys:
            self.assertIn(key, COLOR_SCHEMES)

    def test_preset_fields(self):
        """Each preset must contain all required fields for display and styling."""
        for key, s in COLOR_SCHEMES.items():
            self.assertIn("name", s)
            self.assertIn("short_name", s)
            self.assertIn("button_label", s)
            self.assertIn("text_color", s)
            self.assertIn("background_color", s)
            self.assertIn("text", s)
            self.assertIn("background", s)
            self.assertIn("description", s)
            self.assertTrue(s["text_color"].startswith("#"))
            self.assertTrue(s["background_color"].startswith("#"))


class TestColorSchemeLookupAndCycling(unittest.TestCase):
    """Verify looking up schemes by key, index, or label, and cycling through presets."""

    def test_lookup_by_key(self):
        """Lookup by canonical key returns expected preset."""
        scheme = get_color_scheme("yellow_on_blue")
        self.assertEqual(scheme["key"], "yellow_on_blue")
        self.assertEqual(scheme["text_color"], "#FFFF00")
        self.assertEqual(scheme["background_color"], "#000080")

    def test_lookup_by_index(self):
        """Lookup by integer index 0-3."""
        s0 = get_color_scheme(0)
        self.assertEqual(s0["key"], "white_on_black")
        s1 = get_color_scheme(1)
        self.assertEqual(s1["key"], "yellow_on_blue")
        s2 = get_color_scheme(2)
        self.assertEqual(s2["key"], "green_on_black")
        s3 = get_color_scheme(3)
        self.assertEqual(s3["key"], "black_on_white")

    def test_lookup_index_wraparound(self):
        """Index beyond bounds wraps around using modulo."""
        s4 = get_color_scheme(4)
        self.assertEqual(s4["key"], "white_on_black")

    def test_lookup_by_button_label(self):
        """Lookup by button label (W/B, Y/B, G/B, B/W)."""
        self.assertEqual(get_color_scheme("W/B")["key"], "white_on_black")
        self.assertEqual(get_color_scheme("Y/B")["key"], "yellow_on_blue")
        self.assertEqual(get_color_scheme("G/B")["key"], "green_on_black")
        self.assertEqual(get_color_scheme("B/W")["key"], "black_on_white")

    def test_lookup_case_insensitive_and_fallback(self):
        """Case insensitive lookups and fallback for unknown keys."""
        self.assertEqual(get_color_scheme("YELLOW_ON_BLUE")["key"], "yellow_on_blue")
        self.assertEqual(get_color_scheme("  green on black  ")["key"], "green_on_black")
        self.assertEqual(get_color_scheme("unknown_scheme")["key"], DEFAULT_COLOR_SCHEME)

    def test_cycling_order(self):
        """Verify cycling forwards and backwards through presets."""
        self.assertEqual(get_next_scheme_key("white_on_black", 1), "yellow_on_blue")
        self.assertEqual(get_next_scheme_key("yellow_on_blue", 1), "green_on_black")
        self.assertEqual(get_next_scheme_key("green_on_black", 1), "black_on_white")
        # Wraps to start
        self.assertEqual(get_next_scheme_key("black_on_white", 1), "white_on_black")
        # Backwards cycling
        self.assertEqual(get_next_scheme_key("white_on_black", -1), "black_on_white")


class TestConfigPersistence(unittest.TestCase):
    """Verify reading and saving color schemes and font sizes to config.json."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_config_path = os.path.join(self.temp_dir, "config.json")
        self.orig_caption_config_path = caption_app.CONFIG_PATH
        self.orig_setup_config_path = setup_app.CONFIG_PATH

        caption_app.CONFIG_PATH = self.temp_config_path
        setup_app.CONFIG_PATH = self.temp_config_path

    def tearDown(self):
        caption_app.CONFIG_PATH = self.orig_caption_config_path
        setup_app.CONFIG_PATH = self.orig_setup_config_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load_config(self):
        """save_config writes valid JSON and load_config reads it back."""
        data = {"speech_mode": "online", "color_scheme": "yellow_on_blue"}
        saved = caption_app.save_config(data)
        self.assertTrue(saved)

        loaded = caption_app.load_config()
        self.assertEqual(loaded["color_scheme"], "yellow_on_blue")
        self.assertEqual(loaded["speech_mode"], "online")

    def test_save_color_scheme_preserves_other_settings(self):
        """Saving color scheme does not erase existing configuration options."""
        # Initial config with device settings
        initial_data = {
            "room_device": "hw:1,0",
            "phone_device": "hw:2,0",
            "speech_mode": "offline",
            "font_size": "L",
        }
        caption_app.save_config(initial_data)

        # Update color scheme
        caption_app.save_color_scheme("green_on_black", "#00FF66", "#000000")

        loaded = caption_app.load_config()
        self.assertEqual(loaded["color_scheme"], "green_on_black")
        self.assertEqual(loaded["text_color"], "#00FF66")
        self.assertEqual(loaded["background_color"], "#000000")
        # Unrelated settings preserved
        self.assertEqual(loaded["room_device"], "hw:1,0")
        self.assertEqual(loaded["font_size"], "L")

    def test_save_font_size(self):
        """Saving font size updates config."""
        caption_app.save_font_size("S")
        loaded = caption_app.load_config()
        self.assertEqual(loaded.get("font_size"), "S")


class TestCaptionViewIntegration(unittest.TestCase):
    """Test CaptionView UI methods, color switching, cycling, and font resizing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_config_path = os.path.join(self.temp_dir, "config.json")
        self.orig_caption_config_path = caption_app.CONFIG_PATH
        caption_app.CONFIG_PATH = self.temp_config_path
        caption_app.CONFIG = {}

    def tearDown(self):
        caption_app.CONFIG_PATH = self.orig_caption_config_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_caption_view_initialization_defaults(self):
        """CaptionView defaults to White on Black and Medium font."""
        view = caption_app.CaptionView()
        self.assertEqual(view.current_size, "M")
        self.assertEqual(view.current_scheme, 0)
        self.assertEqual(view.text_color, "#FFFFFF")
        self.assertEqual(view.background_color, "#000000")

    def test_caption_view_loads_saved_config(self):
        """CaptionView respects color_scheme and font_size saved in config."""
        caption_app.save_config({
            "color_scheme": "yellow_on_blue",
            "text_color": "#FFFF00",
            "background_color": "#000080",
            "font_size": "L",
        })
        caption_app.CONFIG = caption_app.load_config()

        view = caption_app.CaptionView()
        self.assertEqual(view.current_size, "L")
        self.assertEqual(view.current_scheme, 1)
        self.assertEqual(view.text_color, "#FFFF00")
        self.assertEqual(view.background_color, "#000080")

    def test_caption_view_set_color(self):
        """Setting color by index updates colors, stylesheets, and persists."""
        view = caption_app.CaptionView()
        view.set_color(2)  # green_on_black
        self.assertEqual(view.current_scheme, 2)
        self.assertEqual(view.text_color, "#00FF66")
        self.assertEqual(view.background_color, "#000000")

        # Verify stylesheet applied
        self.assertIn("#00FF66", view.text.styleSheet())
        self.assertIn("#000000", view.styleSheet())

        # Verify persisted
        loaded = caption_app.load_config()
        self.assertEqual(loaded["color_scheme"], "green_on_black")
        self.assertEqual(loaded["text_color"], "#00FF66")

    def test_caption_view_set_color_by_key(self):
        """Setting color by key string works identically."""
        view = caption_app.CaptionView()
        view.set_color("black_on_white")
        self.assertEqual(view.current_scheme, 3)
        self.assertEqual(view.text_color, "#000000")
        self.assertEqual(view.background_color, "#FFFFFF")

    def test_caption_view_cycle_color_scheme(self):
        """Cycling advances through all presets in order and wraps."""
        view = caption_app.CaptionView()
        self.assertEqual(view.current_scheme, 0)

        view.cycle_color_scheme()
        self.assertEqual(view.current_scheme, 1)
        self.assertEqual(view.text_color, "#FFFF00")

        view.cycle_color_scheme()
        self.assertEqual(view.current_scheme, 2)
        self.assertEqual(view.text_color, "#00FF66")

        view.cycle_color_scheme()
        self.assertEqual(view.current_scheme, 3)
        self.assertEqual(view.text_color, "#000000")

        view.cycle_color_scheme()
        self.assertEqual(view.current_scheme, 0)
        self.assertEqual(view.text_color, "#FFFFFF")

    def test_caption_view_custom_colors(self):
        """Custom colors can be set and persisted."""
        view = caption_app.CaptionView()
        view.set_custom_color("#00FFFF", "#000033")
        self.assertEqual(view.text_color, "#00FFFF")
        self.assertEqual(view.background_color, "#000033")

        loaded = caption_app.load_config()
        self.assertEqual(loaded["text_color"], "#00FFFF")
        self.assertEqual(loaded["background_color"], "#000033")
        self.assertEqual(loaded["color_scheme"], "custom")

    def test_caption_view_set_size_and_cycling(self):
        """Font sizing and cycling through S, M, L."""
        view = caption_app.CaptionView()
        view.set_size("S")
        self.assertEqual(view.current_size, "S")

        view.cycle_font_size(1)
        self.assertEqual(view.current_size, "M")

        view.cycle_font_size(1)
        self.assertEqual(view.current_size, "L")

        # Clamped at max
        view.cycle_font_size(1)
        self.assertEqual(view.current_size, "L")

        # Cycle down
        view.cycle_font_size(-1)
        self.assertEqual(view.current_size, "M")

    def test_keyboard_shortcuts(self):
        """Verify keyboard shortcuts for color cycling, preset selection, and font sizing."""
        view = caption_app.CaptionView()
        # 'C' cycles color scheme
        view.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_C))
        self.assertEqual(view.current_scheme, 1)

        # '3' selects Green on Black (index 2)
        view.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_3))
        self.assertEqual(view.current_scheme, 2)

        # '1' selects White on Black (index 0)
        view.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_1))
        self.assertEqual(view.current_scheme, 0)

        # 'L' selects Large font
        view.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_L))
        self.assertEqual(view.current_size, "L")

        # 'S' selects Small font
        view.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_S))
        self.assertEqual(view.current_size, "S")


class TestSetupAppWizardIntegration(unittest.TestCase):
    """Test setup/app.py wizard API integration with color schemes."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_config_path = os.path.join(self.temp_dir, "config.json")
        self.orig_setup_config_path = setup_app.CONFIG_PATH
        setup_app.CONFIG_PATH = self.temp_config_path

    def tearDown(self):
        setup_app.CONFIG_PATH = self.orig_setup_config_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_api_color_schemes_endpoint(self):
        """/api/color-schemes returns presets and default."""
        resp = setup_app.api_color_schemes()
        # If Flask is stubbed, resp is dict; if real, might be Response or dict
        data = resp.get_json() if hasattr(resp, "get_json") else resp
        self.assertIn("presets", data)
        self.assertIn("default", data)
        self.assertEqual(data["default"], "white_on_black")
        self.assertIn("yellow_on_blue", data["presets"])

    def test_api_save_persists_color_scheme_and_custom_colors(self):
        """/api/save updates config with chosen color scheme and colors."""
        class MockRequest:
            def __init__(self, data):
                self._data = data
            def get_json(self):
                return self._data

        setup_app.request = MockRequest({
            "room_device": "hw:0,0",
            "speech_mode": "online",
            "stt_provider": "deepgram",
            "color_scheme": "yellow_on_blue",
            "text_color": "#FFFF00",
            "background_color": "#000080",
            "font_size": "L",
        })

        setup_app.api_save()
        loaded = setup_app.load_config()
        self.assertEqual(loaded["color_scheme"], "yellow_on_blue")
        self.assertEqual(loaded["text_color"], "#FFFF00")
        self.assertEqual(loaded["background_color"], "#000080")
        self.assertEqual(loaded["font_size"], "L")
        self.assertEqual(loaded["room_device"], "hw:0,0")


class TestMainWindowKeyHandling(unittest.TestCase):
    """Test MainWindow keyboard shortcut routing to CaptionView."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_config_path = os.path.join(self.temp_dir, "config.json")
        self.orig_caption_config_path = caption_app.CONFIG_PATH
        caption_app.CONFIG_PATH = self.temp_config_path
        caption_app.CONFIG = {}

    def tearDown(self):
        caption_app.CONFIG_PATH = self.orig_caption_config_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mainwindow_key_shortcuts(self):
        """MainWindow keyPressEvent correctly routes shortcuts to CaptionView."""
        win = caption_app.MainWindow()
        # 'C' cycles color
        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_C))
        self.assertEqual(win.caption_view.current_scheme, 1)

        # '4' selects Black on White (index 3)
        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_4))
        self.assertEqual(win.caption_view.current_scheme, 3)

        # '2' selects Yellow on Blue (index 1)
        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_2))
        self.assertEqual(win.caption_view.current_scheme, 1)

        # 'S' selects small font
        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_S))
        self.assertEqual(win.caption_view.current_size, "S")

        # Plus cycles font up
        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_Plus))
        self.assertEqual(win.caption_view.current_size, "M")

        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_Plus))
        self.assertEqual(win.caption_view.current_size, "L")

        # Minus cycles font down
        win.keyPressEvent(DummyKeyEvent(caption_app.Qt.Key.Key_Minus))
        self.assertEqual(win.caption_view.current_size, "M")


if __name__ == "__main__":
    unittest.main()
