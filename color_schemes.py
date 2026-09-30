"""
Accessible high-contrast color schemes for Gramps Transcriber.

Presets are based on ADA / low vision research and designed to meet
WCAG 2.1 AAA contrast requirements (minimum 7:1 contrast ratio for normal text).
"""

COLOR_SCHEMES = {
    'white_on_black': {
        'name': 'High Contrast Light on Dark',
        'short_name': 'White on Black',
        'button_label': 'W/B',
        'text_color': '#FFFFFF',
        'background_color': '#000000',
        'text': '#FFFFFF',
        'background': '#000000',
        'description': 'High contrast white text on pure black background (default)',
    },
    'yellow_on_blue': {
        'name': 'High Contrast Yellow on Blue',
        'short_name': 'Yellow on Blue',
        'button_label': 'Y/B',
        'text_color': '#FFFF00',
        'background_color': '#000080',
        'text': '#FFFF00',
        'background': '#000080',
        'description': 'High contrast yellow text on navy blue background (optimal for low vision/cataracts)',
    },
    'green_on_black': {
        'name': 'High Contrast Green on Black',
        'short_name': 'Green on Black',
        'button_label': 'G/B',
        'text_color': '#00FF66',
        'background_color': '#000000',
        'text': '#00FF66',
        'background': '#000000',
        'description': 'High contrast light green text on pure black background',
    },
    'black_on_white': {
        'name': 'High Contrast Dark on Light',
        'short_name': 'Black on White',
        'button_label': 'B/W',
        'text_color': '#000000',
        'background_color': '#FFFFFF',
        'text': '#000000',
        'background': '#FFFFFF',
        'description': 'High contrast black text on white background',
    },
}

DEFAULT_COLOR_SCHEME = 'white_on_black'
COLOR_SCHEME_KEYS = list(COLOR_SCHEMES.keys())


def normalize_hex(hex_code):
    """Normalize hex color string to uppercase 6-character hex with leading #."""
    if not isinstance(hex_code, str):
        raise ValueError(f"Invalid color value: {hex_code}")
    hex_clean = hex_code.strip().lstrip('#')
    if len(hex_clean) == 3:
        hex_clean = ''.join(c * 2 for c in hex_clean)
    if len(hex_clean) != 6 or not all(c in '0123456789abcdefABCDEF' for c in hex_clean):
        raise ValueError(f"Invalid hex color format: {hex_code}")
    return f"#{hex_clean.upper()}"


def calculate_luminance(hex_color):
    """
    Calculate WCAG 2.1 relative luminance for a given hex color.
    Returns a float in [0.0, 1.0].
    """
    norm = normalize_hex(hex_color).lstrip('#')
    r = int(norm[0:2], 16) / 255.0
    g = int(norm[2:4], 16) / 255.0
    b = int(norm[4:6], 16) / 255.0

    def adjust(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)


def calculate_contrast_ratio(fg_hex, bg_hex):
    """
    Calculate WCAG contrast ratio between foreground and background hex colors.
    Returns float in range [1.0, 21.0].
    """
    l1 = calculate_luminance(fg_hex)
    l2 = calculate_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def is_wcag_aaa(fg_hex, bg_hex):
    """Check if color combination meets WCAG AAA standard (contrast ratio >= 7.0:1)."""
    return calculate_contrast_ratio(fg_hex, bg_hex) >= 7.0


def is_wcag_aa(fg_hex, bg_hex):
    """Check if color combination meets WCAG AA standard (contrast ratio >= 4.5:1)."""
    return calculate_contrast_ratio(fg_hex, bg_hex) >= 4.5


def get_color_scheme(key_or_idx):
    """
    Retrieve color scheme dictionary by key, button label, name, or integer index.
    Returns a dictionary with scheme details including key and index.
    Falls back to DEFAULT_COLOR_SCHEME if not found.
    """
    if isinstance(key_or_idx, int):
        idx = key_or_idx % len(COLOR_SCHEME_KEYS)
        key = COLOR_SCHEME_KEYS[idx]
        scheme = dict(COLOR_SCHEMES[key])
        scheme['key'] = key
        scheme['index'] = idx
        return scheme

    if isinstance(key_or_idx, str):
        key_clean = key_or_idx.strip().lower()
        if key_clean in COLOR_SCHEMES:
            scheme = dict(COLOR_SCHEMES[key_clean])
            scheme['key'] = key_clean
            scheme['index'] = COLOR_SCHEME_KEYS.index(key_clean)
            return scheme

        for i, (k, s) in enumerate(COLOR_SCHEMES.items()):
            if (s['button_label'].lower() == key_clean or
                s['short_name'].lower() == key_clean or
                s['name'].lower() == key_clean or
                k.replace('_', ' ') == key_clean or
                k.replace('_', '') == key_clean.replace(' ', '')):
                scheme = dict(s)
                scheme['key'] = k
                scheme['index'] = i
                return scheme

    # Default fallback
    scheme = dict(COLOR_SCHEMES[DEFAULT_COLOR_SCHEME])
    scheme['key'] = DEFAULT_COLOR_SCHEME
    scheme['index'] = 0
    return scheme


def get_next_scheme_key(current_key_or_idx, step=1):
    """Return the next color scheme key when cycling by step (default +1)."""
    current = get_color_scheme(current_key_or_idx)
    next_idx = (current['index'] + step) % len(COLOR_SCHEME_KEYS)
    return COLOR_SCHEME_KEYS[next_idx]
