"""Tests de regresión para los bugs corregidos en utils.py."""

import subprocess
from pathlib import Path

import pytest

from utils import (
    format_duration,
    format_file_size,
    generate_unique_filename,
    get_video_info,
    sanitize_filename,
    validate_tiktok_url,
)


def test_sanitize_filename_removes_hash_and_weird_chars():
    assert sanitize_filename("#monkey#funny?.mp4").startswith("monkeyfunny")
    assert "#" not in sanitize_filename("a#b")


def test_validate_tiktok_url_basic():
    assert validate_tiktok_url("https://www.tiktok.com/@user/video/1234567890")
    assert not validate_tiktok_url("https://example.com/video/123")


def test_sanitize_filename_transliterates_accents():
    """Los acentos no deben borrarse: 'ñ' -> 'n' conserva el significado."""
    assert sanitize_filename("año nuevo") == "ano_nuevo"
    assert sanitize_filename("Corazón") == "Corazon"


def test_sanitize_filename_returns_video_for_empty_input():
    assert sanitize_filename("") == "video"
    assert sanitize_filename("###") == "video"


def test_get_video_info_returns_none_on_timeout(monkeypatch):
    """Regresión: `json` se importaba dentro del `try`, así que el `except`
    lanzaba NameError en lugar de devolver None."""

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)

    monkeypatch.setattr(subprocess, "run", boom)
    assert get_video_info(Path("/tmp/does-not-matter.mp4")) is None


def test_get_video_info_returns_none_on_invalid_json(monkeypatch):
    class Result:
        returncode = 0
        stdout = "not-json"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    assert get_video_info(Path("/tmp/does-not-matter.mp4")) is None


def test_format_duration():
    assert format_duration(0) == "00:00"
    assert format_duration(65) == "01:05"
    assert format_duration(3599) == "59:59"


def test_format_file_size():
    assert format_file_size(512) == "512.0 B"
    assert format_file_size(2048) == "2.0 KB"


def test_generate_unique_filename_is_sanitized_and_timestamped():
    name = generate_unique_filename("Mi Video #1")
    assert name.startswith("Mi_Video_1_")
    assert name.endswith(".mp4")
