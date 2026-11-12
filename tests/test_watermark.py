"""Tests de detección de marcas de agua (watermark.py).

Se generan vídeos sintéticos con y sin marca de agua incrustada para
comprobar que el detector distingue ambos casos.
"""

import subprocess

import pytest

from deps import resolve_binaries
from watermark import detect_watermark

pytestmark = pytest.mark.skipif(resolve_binaries().ffmpeg is None, reason="FFmpeg no disponible")


def _has_ffmpeg() -> bool:
    return resolve_binaries().ffmpeg is not None


def _make_video(path, with_watermark: bool) -> None:
    """Genera un vídeo con movimiento y, opcionalmente, una marca de agua."""
    bins = resolve_binaries()
    cmd = [
        str(bins.ffmpeg),
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "gradients=size=1080x1920:rate=30:c0=black:c1=white:x0=0:y0=0:x1=1080:y1=1920:duration=3:nb_colors=4:speed=0.3",
    ]

    if with_watermark:
        cmd += [
            "-f",
            "lavfi",
            "-i",
            "color=c=white@0.85:s=190x70:d=3",
            "-filter_complex",
            "[1:v]format=rgba[wm];[0:v][wm]overlay=25:1690",
        ]

    cmd += ["-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    assert result.returncode == 0, result.stderr.decode("utf-8", "ignore")


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    """Genera un vídeo con marca de agua y otro sin ella."""
    if not _has_ffmpeg():
        pytest.skip("FFmpeg no disponible")

    base = tmp_path_factory.mktemp("watermark")
    with_wm = base / "con_marca.mp4"
    without_wm = base / "sin_marca.mp4"

    _make_video(with_wm, True)
    _make_video(without_wm, False)

    return with_wm, without_wm


def test_detects_watermark(videos):
    """Un vídeo con logo fijo debe detectarse."""
    with_wm, _ = videos
    report = detect_watermark(with_wm)
    assert report.detected is True
    assert report.confidence > 0.5
    assert report.frames_analyzed > 0
    assert "detectada" in report.summary


def test_no_false_positive_without_watermark(videos):
    """Un vídeo limpio no debe generar avisos."""
    _, without_wm = videos
    report = detect_watermark(without_wm)
    assert report.detected is False
    assert report.confidence < 0.55
    assert "No se detectaron" in report.summary


def test_detected_zone_is_in_a_corner(videos):
    """La zona detectada debe estar en una esquina o borde."""
    with_wm, _ = videos
    report = detect_watermark(with_wm)
    assert report.regions
    name = report.regions[0].name
    assert any(keyword in name for keyword in ("esquina", "borde"))


def test_missing_file_returns_error():
    from pathlib import Path

    report = detect_watermark(Path("/tmp/does-not-exist-12345.mp4"))
    assert report.detected is False
    assert report.error is not None
    assert "no disponible" in report.summary


def test_report_has_no_error_on_success(videos):
    with_wm, without_wm = videos
    assert detect_watermark(with_wm).error is None
    assert detect_watermark(without_wm).error is None
