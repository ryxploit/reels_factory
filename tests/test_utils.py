"""Tests de regresión para los bugs corregidos en utils.py."""

import subprocess
from pathlib import Path

import pytest

from utils import (
    detect_platform,
    format_duration,
    format_file_size,
    generate_unique_filename,
    get_video_info,
    sanitize_filename,
    validate_tiktok_url,
    validate_video_url,
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


# ---------------------------------------------------------------------------
# Regresión: validación estricta de URLs (antes re.match sin anclar de fin)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        # Formatos usados por el propio repo (tests, README y GUI).
        ("https://www.tiktok.com/@user/video/1234567890", "tiktok"),
        ("https://www.tiktok.com/@u/video/1", "tiktok"),
        ("https://tiktok.com/@user/video/123", "tiktok"),
        ("https://vm.tiktok.com/ZMabc123/", "tiktok"),
        ("https://vt.tiktok.com/ZMabc123", "tiktok"),
        ("https://www.tiktok.com/t/ZMabc123", "tiktok"),
        ("https://www.instagram.com/reel/ABC123xyz/", "instagram"),
        ("https://www.instagram.com/reels/ABC123xyz/", "instagram"),
        ("https://www.instagram.com/p/ABC123xyz/", "instagram"),
        ("https://www.instagram.com/tv/ABC123xyz/", "instagram"),
        ("https://instagram.com/reel/123", "instagram"),
        ("https://www.youtube.com/shorts/ABC123xyz", "youtube"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
        ("https://m.youtube.com/shorts/ABC123xyz", "youtube"),
        ("https://youtu.be/ABC123xyz", "youtube"),
        ("https://www.youtube.com/watch?v=ABC123xyz", "youtube"),
        ("https://youtube.com/watch?v=abc", "youtube"),
    ],
)
def test_detect_platform_accepts_legitimate_urls(url, platform):
    """Las URLs legítimas de las 3 plataformas siguen siendo aceptadas."""
    assert detect_platform(url) == platform
    assert validate_video_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        # Casos auditados: antes devolvían True con re.match sin ancla de fin.
        "https://youtu.be/abc.evil.com/path",
        "https://www.youtube.com/shorts/abc\nevil.com",
        "https://tiktok.com/@user/video/123.attacker.tld",
        "https://youtu.be/abc;rm -rf /",
        "http://youtube.com/watch?v=abc",
        # Host lookalike (sufijo, no coincide con la allowlist exacta).
        "https://tiktok.com.evil.com/@user/video/123",
        "https://www.youtube.com.evil.com/shorts/abc",
        # Credenciales incrustadas (incluido el caso de usuario vacío).
        "https://user:pass@youtube.com/shorts/abc",
        "https://@youtu.be/abc",
        # Otros caracteres peligrosos y esquemas.
        "https://youtu.be/abc\tRM -rf /",
        "https://youtu.be/abc\x00evil",
        "https://youtu.be/abc{evil}",
        "https://youtu.be/abc|evil",
        "https://youtu.be/abc\\evil",
        # Query maliciosa: ID envenenado, meta-caracteres y parámetros sin valor.
        "https://www.youtube.com/watch?v=abc.evil.com",
        "https://www.youtube.com/watch?v=abc&x=|rm",
        "https://www.youtube.com/watch?v=abc&",
        "https://www.tiktok.com/@u/video/123?utm_source=x;rm -rf /",
        "https://youtu.be/abc?x=1\nevil.com",
        "https://youtu.be/abc#frag",
        "file:///etc/passwd",
        "no-es-una-url",
        None,
    ],
)
def test_validate_video_url_rejects_malicious_urls(url):
    """Ninguna URL maliciosa debe ser atribuida a una plataforma."""
    assert detect_platform(url) is None
    assert validate_video_url(url) is False


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        # TikTok copia enlaces con utm_* al compartirlos desde la app.
        (
            "https://www.tiktok.com/@user/video/123?utm_source=xxx&utm_campaign=yyy",
            "tiktok",
        ),
        ("https://vm.tiktok.com/ZMabc123/?utm_source=xxx", "tiktok"),
        (
            "https://www.instagram.com/reel/ABC123xyz/?igshid=MzRlODBiNWFlZA%3D%3D",
            "instagram",
        ),
        ("https://instagram.com/reel/123?utm_source=ig_web_copy_link", "instagram"),
        ("https://www.youtube.com/shorts/ABC123xyz?feature=share&utm_source=xxx", "youtube"),
        ("https://youtu.be/ABC123xyz?si=abc123-xyz&utm_source=xxx", "youtube"),
        # watch admite 'v' + parámetros extra (t=, utm_*).
        ("https://www.youtube.com/watch?v=ABC123xyz&t=30", "youtube"),
        (
            "https://www.youtube.com/watch?v=ABC123xyz&t=30&utm_source=xxx&utm_campaign=yyy",
            "youtube",
        ),
    ],
)
def test_detect_platform_accepts_tracking_query_params(url, platform):
    """Regresión: los parámetros de tracking reales no deben romper el flujo."""
    assert detect_platform(url) == platform
    assert validate_video_url(url) is True


@pytest.mark.parametrize(
    "url", ["http://www.tiktok.com/@user/video/123", "ftp://tiktok.com/@u/video/1"]
)
def test_validate_tiktok_url_rejects_non_https(url):
    """validate_tiktok_url comparte la misma política estricta."""
    assert validate_tiktok_url(url) is False
