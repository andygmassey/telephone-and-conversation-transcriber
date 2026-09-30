#!/usr/bin/env python3
"""Configuration and validation for Whisper models."""

DEFAULT_WHISPER_MODEL = 'tiny'
ALLOWED_WHISPER_MODELS = ('tiny', 'base', 'small', 'medium', 'large')


def validate_whisper_model(model_name):
    """
    Validate and return an allowed Whisper model name.
    Allowed options: tiny, base, small, medium, large.
    Defaults to 'tiny' (recommended for Raspberry Pi) if invalid, empty, or omitted.
    """
    if not model_name or not isinstance(model_name, str):
        return DEFAULT_WHISPER_MODEL
    cleaned = model_name.strip().lower()
    if cleaned in ALLOWED_WHISPER_MODELS:
        return cleaned
    # Normalize .en English-specific model names to their base size
    if cleaned.endswith('.en') and cleaned[:-3] in ALLOWED_WHISPER_MODELS:
        return cleaned[:-3]
    return DEFAULT_WHISPER_MODEL
