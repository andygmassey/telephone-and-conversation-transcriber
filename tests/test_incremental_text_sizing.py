"""
Unit tests for incremental text sizing, accessible scrollbar styling,
keyboard shortcuts, gesture controls, and configuration persistence.
"""

import json
import os
import pytest

import caption_app
from caption_app import (
    CaptionView,
    MainWindow,
    DEFAULT_FONT_SIZE,
    FONT_PRESETS,
    FONT_SIZE_STEP,
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    Qt,
    clamp_font_size,
    get_caption_scrollbar_style,
    get_next_font_size,
    get_prev_font_size,
    load_config,
    save_config,
    save_font_size,
)
from setup import app as setup_app


class MockKeyEvent:
    """Mock Qt QKeyEvent for testing keyboard shortcuts."""

    def __init__(self, key_code, modifiers=0):
        self._key = key_code
        self._modifiers = modifiers
        self.accepted = False

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


class MockAngleDelta:
    def __init__(self, y):
        self._y = y

    def y(self):
        return self._y


class MockWheelEvent:
    """Mock Qt QWheelEvent for testing Ctrl+mousewheel zooming."""

    def __init__(self, delta_y, modifiers=0):
        self._delta = MockAngleDelta(delta_y)
        self._modifiers = modifiers
        self.accepted = False

    def angleDelta(self):
        return self._delta

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


class MockPinchGesture:
    def __init__(self, scale_factor):
        self._scale_factor = scale_factor

    def scaleFactor(self):
        return self._scale_factor


class MockGestureEvent:
    """Mock Qt QGestureEvent for testing pinch-to-zoom gestures."""

    def __init__(self, pinch_gesture=None):
        self._pinch = pinch_gesture

    def gesture(self, gesture_type):
        if hasattr(Qt, 'GestureType') and gesture_type == Qt.GestureType.PinchGesture:
            return self._pinch
        return None


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Fixture providing isolated temporary config.json for caption_app."""
    config_file = str(tmp_path / 'config.json')
    monkeypatch.setattr(caption_app, 'CONFIG_PATH', config_file)
    monkeypatch.setattr(caption_app, 'CONFIG', {})
    return config_file


@pytest.fixture
def temp_setup_config(tmp_path, monkeypatch):
    """Fixture providing isolated temporary config.json for setup_app."""
    config_file = str(tmp_path / 'config.json')
    monkeypatch.setattr(setup_app, 'CONFIG_PATH', config_file)
    return config_file


# ==============================================================================
# 1. Font Size Bounds and Clamping Tests
# ==============================================================================

class TestFontSizeBounds:
    def test_constants_and_accessible_range(self):
        assert MIN_FONT_SIZE <= 12
        assert MAX_FONT_SIZE >= 72
        assert MIN_FONT_SIZE < DEFAULT_FONT_SIZE < MAX_FONT_SIZE
        assert FONT_SIZE_STEP in (2, 4)

    def test_clamp_font_size_within_bounds(self):
        assert clamp_font_size(12) == 12
        assert clamp_font_size(24) == 24
        assert clamp_font_size(36) == 36
        assert clamp_font_size(48) == 48
        assert clamp_font_size(72) == 72
        assert clamp_font_size(MAX_FONT_SIZE) == MAX_FONT_SIZE

    def test_clamp_font_size_lower_bound(self):
        assert clamp_font_size(MIN_FONT_SIZE) == MIN_FONT_SIZE
        assert clamp_font_size(MIN_FONT_SIZE - 1) == MIN_FONT_SIZE
        assert clamp_font_size(0) == MIN_FONT_SIZE
        assert clamp_font_size(-10) == MIN_FONT_SIZE

    def test_clamp_font_size_upper_bound(self):
        assert clamp_font_size(MAX_FONT_SIZE) == MAX_FONT_SIZE
        assert clamp_font_size(MAX_FONT_SIZE + 1) == MAX_FONT_SIZE
        assert clamp_font_size(100) == MAX_FONT_SIZE
        assert clamp_font_size(999) == MAX_FONT_SIZE

    def test_clamp_font_size_presets(self):
        assert clamp_font_size('S') == FONT_PRESETS['S']
        assert clamp_font_size('s') == FONT_PRESETS['S']
        assert clamp_font_size('M') == FONT_PRESETS['M']
        assert clamp_font_size('m') == FONT_PRESETS['M']
        assert clamp_font_size('L') == FONT_PRESETS['L']
        assert clamp_font_size('l') == FONT_PRESETS['L']

    def test_clamp_font_size_numeric_strings_and_floats(self):
        assert clamp_font_size('40') == 40
        assert clamp_font_size('8') == MIN_FONT_SIZE
        assert clamp_font_size('200') == MAX_FONT_SIZE
        assert clamp_font_size(36.4) == 36
        assert clamp_font_size(36.6) == 37

    def test_clamp_font_size_invalid_inputs(self):
        assert clamp_font_size(None) == DEFAULT_FONT_SIZE
        assert clamp_font_size('invalid') == DEFAULT_FONT_SIZE
        assert clamp_font_size('') == DEFAULT_FONT_SIZE
        assert clamp_font_size([]) == DEFAULT_FONT_SIZE
        assert clamp_font_size({}) == DEFAULT_FONT_SIZE


# ==============================================================================
# 2. Incremental and Decremental Scaling Tests
# ==============================================================================

class TestIncrementalScaling:
    def test_increment_by_step(self):
        start = DEFAULT_FONT_SIZE
        next_size = get_next_font_size(start)
        assert next_size == start + FONT_SIZE_STEP

    def test_decrement_by_step(self):
        start = DEFAULT_FONT_SIZE
        prev_size = get_prev_font_size(start)
        assert prev_size == start - FONT_SIZE_STEP

    def test_increment_boundary_guard(self):
        assert get_next_font_size(MAX_FONT_SIZE) == MAX_FONT_SIZE
        near_max = MAX_FONT_SIZE - (FONT_SIZE_STEP - 1)
        assert get_next_font_size(near_max) == MAX_FONT_SIZE

    def test_decrement_boundary_guard(self):
        assert get_prev_font_size(MIN_FONT_SIZE) == MIN_FONT_SIZE
        near_min = MIN_FONT_SIZE + (FONT_SIZE_STEP - 1)
        assert get_prev_font_size(near_min) == MIN_FONT_SIZE

    def test_custom_step(self):
        assert get_next_font_size(30, step=8) == 38
        assert get_prev_font_size(30, step=8) == 22


# ==============================================================================
# 3. Font Size and Configuration Persistence Tests
# ==============================================================================

class TestFontSizePersistence:
    def test_save_config_creates_file_and_updates_dict(self, temp_config):
        success = save_config({'font_size': 44, 'custom_key': 'value'})
        assert success is True
        assert os.path.exists(temp_config)

        with open(temp_config) as f:
            data = json.load(f)
        assert data['font_size'] == 44
        assert data['custom_key'] == 'value'
        assert caption_app.CONFIG['font_size'] == 44

    def test_save_config_preserves_existing_keys(self, temp_config):
        save_config({'speech_mode': 'online', 'stt_provider': 'deepgram'})
        save_font_size(48)

        loaded = load_config()
        assert loaded['speech_mode'] == 'online'
        assert loaded['stt_provider'] == 'deepgram'
        assert loaded['font_size'] == 48

    def test_save_font_size_clamps_before_saving(self, temp_config):
        save_font_size(200)
        loaded = load_config()
        assert loaded['font_size'] == MAX_FONT_SIZE

        save_font_size(5)
        loaded = load_config()
        assert loaded['font_size'] == MIN_FONT_SIZE

    def test_save_config_handles_io_errors_gracefully(self, monkeypatch):
        def bad_open(*args, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr('builtins.open', bad_open)
        result = save_config({'font_size': 40})
        assert result is False


# ==============================================================================
# 4. CaptionView Controls and Behavior Tests
# ==============================================================================

class TestCaptionViewFontSizing:
    def test_initialization_with_default(self, temp_config):
        view = CaptionView()
        assert view.font_size == DEFAULT_FONT_SIZE
        assert view.current_size == DEFAULT_FONT_SIZE
        assert view.text.font().pointSize() == DEFAULT_FONT_SIZE

    def test_initialization_with_saved_config(self, temp_config, monkeypatch):
        monkeypatch.setattr(caption_app, 'CONFIG', {'font_size': 44})
        view = CaptionView()
        assert view.font_size == 44
        assert view.text.font().pointSize() == 44

    def test_size_buttons_present(self, temp_config):
        view = CaptionView()
        assert '-' in view.size_buttons
        assert '+' in view.size_buttons
        assert '0' in view.size_buttons

    def test_increase_font_size(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        view.increase_font_size()
        expected = initial + FONT_SIZE_STEP
        assert view.font_size == expected
        assert view.text.font().pointSize() == expected
        assert view.text.document().defaultFont().pointSize() == expected
        assert load_config().get('font_size') == expected

    def test_decrease_font_size(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        view.decrease_font_size()
        expected = initial - FONT_SIZE_STEP
        assert view.font_size == expected
        assert view.text.font().pointSize() == expected
        assert view.text.document().defaultFont().pointSize() == expected
        assert load_config().get('font_size') == expected

    def test_reset_font_size(self, temp_config):
        view = CaptionView()
        view.increase_font_size()
        view.increase_font_size()
        assert view.font_size != DEFAULT_FONT_SIZE
        view.reset_font_size()
        assert view.font_size == DEFAULT_FONT_SIZE
        assert load_config().get('font_size') == DEFAULT_FONT_SIZE

    def test_upper_boundary_guard_in_view(self, temp_config):
        view = CaptionView()
        view.set_font_size(MAX_FONT_SIZE)
        view.increase_font_size()
        assert view.font_size == MAX_FONT_SIZE
        assert '#181818' in view.size_buttons['+'].styleSheet()

    def test_lower_boundary_guard_in_view(self, temp_config):
        view = CaptionView()
        view.set_font_size(MIN_FONT_SIZE)
        view.decrease_font_size()
        assert view.font_size == MIN_FONT_SIZE
        assert '#181818' in view.size_buttons['-'].styleSheet()

    def test_backwards_compatibility_set_size(self, temp_config):
        view = CaptionView()
        view.set_size('S')
        assert view.font_size == FONT_PRESETS['S']
        view.set_size('L')
        assert view.font_size == FONT_PRESETS['L']
        view.set_size('M')
        assert view.font_size == FONT_PRESETS['M']
        view.set_size(52)
        assert view.font_size == 52

    def test_button_mouse_press_events(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        view.size_buttons['+'].mousePressEvent(None)
        assert view.font_size == initial + FONT_SIZE_STEP
        view.size_buttons['-'].mousePressEvent(None)
        assert view.font_size == initial
        view.set_font_size(48)
        view.size_buttons['0'].mousePressEvent(None)
        assert view.font_size == DEFAULT_FONT_SIZE

    def test_reset_button_styling_states(self, temp_config):
        view = CaptionView()
        # Default state: '0' button highlighted
        assert '#444' in view.size_buttons['0'].styleSheet()
        view.increase_font_size()
        # Non-default state: '0' button standard
        assert '#222' in view.size_buttons['0'].styleSheet()


# ==============================================================================
# 5. Keyboard Shortcuts and Gesture Tests
# ==============================================================================

class TestKeyboardAndGestures:
    def test_keyboard_shortcut_plus_and_equal(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        view.keyPressEvent(MockKeyEvent(Qt.Key.Key_Plus))
        assert view.font_size == initial + FONT_SIZE_STEP
        view.keyPressEvent(MockKeyEvent(Qt.Key.Key_Equal))
        assert view.font_size == initial + 2 * FONT_SIZE_STEP

    def test_keyboard_shortcut_minus_and_underscore(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        view.keyPressEvent(MockKeyEvent(Qt.Key.Key_Minus))
        assert view.font_size == initial - FONT_SIZE_STEP
        view.keyPressEvent(MockKeyEvent(Qt.Key.Key_Underscore))
        assert view.font_size == initial - 2 * FONT_SIZE_STEP

    def test_keyboard_shortcut_zero(self, temp_config):
        view = CaptionView()
        view.set_font_size(48)
        view.keyPressEvent(MockKeyEvent(Qt.Key.Key_0))
        assert view.font_size == DEFAULT_FONT_SIZE

    def test_keyboard_shortcuts_with_ctrl_modifier(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        ctrl_plus = MockKeyEvent(Qt.Key.Key_Plus, modifiers=Qt.KeyboardModifier.ControlModifier)
        view.keyPressEvent(ctrl_plus)
        assert view.font_size == initial + FONT_SIZE_STEP

        cmd_minus = MockKeyEvent(Qt.Key.Key_Minus, modifiers=Qt.KeyboardModifier.MetaModifier)
        view.keyPressEvent(cmd_minus)
        assert view.font_size == initial

        view.set_font_size(52)
        ctrl_zero = MockKeyEvent(Qt.Key.Key_0, modifiers=Qt.KeyboardModifier.ControlModifier)
        view.keyPressEvent(ctrl_zero)
        assert view.font_size == DEFAULT_FONT_SIZE

    def test_main_window_key_press_delegation(self, temp_config):
        win = MainWindow()
        caption_view = win.caption_view
        initial = caption_view.font_size
        win.keyPressEvent(MockKeyEvent(Qt.Key.Key_Plus))
        assert caption_view.font_size == initial + FONT_SIZE_STEP
        win.keyPressEvent(MockKeyEvent(Qt.Key.Key_Minus))
        assert caption_view.font_size == initial
        caption_view.set_font_size(48)
        win.keyPressEvent(MockKeyEvent(Qt.Key.Key_0))
        assert caption_view.font_size == DEFAULT_FONT_SIZE

    def test_mouse_wheel_zoom_with_ctrl(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        wheel_up = MockWheelEvent(delta_y=120, modifiers=Qt.KeyboardModifier.ControlModifier)
        view.wheelEvent(wheel_up)
        assert view.font_size == initial + FONT_SIZE_STEP
        assert wheel_up.accepted is True

        wheel_down = MockWheelEvent(delta_y=-120, modifiers=Qt.KeyboardModifier.ControlModifier)
        view.wheelEvent(wheel_down)
        assert view.font_size == initial
        assert wheel_down.accepted is True

    def test_mouse_wheel_without_ctrl_does_not_zoom(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        wheel_event = MockWheelEvent(delta_y=120, modifiers=0)
        view.wheelEvent(wheel_event)
        assert view.font_size == initial

    def test_pinch_gesture_zooming(self, temp_config):
        view = CaptionView()
        initial = view.font_size
        # Zoom in
        pinch_in = MockGestureEvent(MockPinchGesture(scale_factor=1.3))
        view.event(pinch_in)
        assert view.font_size == initial + FONT_SIZE_STEP

        # Zoom out
        pinch_out = MockGestureEvent(MockPinchGesture(scale_factor=0.7))
        view.event(pinch_out)
        assert view.font_size == initial


# ==============================================================================
# 6. Scrollbar Styling and Contrast Configuration Tests
# ==============================================================================

class TestScrollbarConfiguration:
    def test_scrollbar_policy_always_on(self, temp_config):
        view = CaptionView()
        assert view.text.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn

    def test_scrollbar_styling_dark_theme(self):
        style = get_caption_scrollbar_style('#000000')
        assert 'width: 32px;' in style
        assert 'background: #262626;' in style
        assert 'border: 2px solid #404040;' in style
        assert 'background: #5b82a6;' in style  # Distinct visible alternate handle color
        assert 'background: #7da8d0;' in style  # Hover/pressed handle color
        assert 'min-height: 60px;' in style

    def test_scrollbar_styling_light_theme(self):
        style = get_caption_scrollbar_style('#ffffff')
        assert 'width: 32px;' in style
        assert 'background: #e2e8f0;' in style
        assert 'border: 2px solid #cbd5e1;' in style
        assert 'background: #475569;' in style
        assert 'min-height: 60px;' in style

    def test_scrollbar_styling_updated_on_color_scheme_change(self, temp_config):
        view = CaptionView()
        # Initial scheme is W/B (dark theme)
        scroll_sheet_dark = view.text.verticalScrollBar().styleSheet()
        assert '#5b82a6' in scroll_sheet_dark

        # Change scheme to B/W (light theme, index 1)
        view.set_color(1)
        scroll_sheet_light = view.text.verticalScrollBar().styleSheet()
        assert '#475569' in scroll_sheet_light
        assert '#e2e8f0' in scroll_sheet_light

        # Change back to yellow on black (index 2)
        view.set_color(2)
        scroll_sheet_dark_2 = view.text.verticalScrollBar().styleSheet()
        assert '#5b82a6' in scroll_sheet_dark_2


# ==============================================================================
# 7. Setup Wizard Persistence Integration Tests
# ==============================================================================

class TestSetupWizardConfig:
    def test_api_save_preserves_font_size(self, temp_setup_config):
        with open(temp_setup_config, 'w') as f:
            json.dump({'font_size': 44, 'speech_mode': 'offline'}, f)

        client = setup_app.app.test_client()
        payload = {'speech_mode': 'online', 'stt_provider': 'deepgram'}
        res = client.post('/api/save', json=payload)
        assert res.status_code == 200

        with open(temp_setup_config) as f:
            saved = json.load(f)

        assert saved['speech_mode'] == 'online'
        assert saved['stt_provider'] == 'deepgram'
        assert saved['font_size'] == 44

    def test_api_save_allows_updating_font_size(self, temp_setup_config):
        with open(temp_setup_config, 'w') as f:
            json.dump({'font_size': 36}, f)

        client = setup_app.app.test_client()
        res = client.post('/api/save', json={'font_size': 52})
        assert res.status_code == 200

        with open(temp_setup_config) as f:
            saved = json.load(f)

        assert saved['font_size'] == 52
