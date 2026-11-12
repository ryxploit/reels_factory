"""Tests de detección de zonas fijas / marcas de agua (watermark.py).

La detección se prueba con fotogramas sintéticos deterministas, donde se
conoce exactamente dónde está la capa fija. Los vídeos reales no sirven como
fixture porque sus estadísticas de textura no se pueden reproducir con
patrones de FFmpeg.
"""

import subprocess

import numpy as np
import pytest

from deps import resolve_binaries
from watermark import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    _edge_map,
    _scan_windows,
    _still_map,
    detect_watermark,
)

pytestmark = pytest.mark.skipif(resolve_binaries().ffmpeg is None, reason="FFmpeg no disponible")


def _make_frames(
    n: int = 12,
    still_box: tuple[int, int, int, int] | None = (10, 250, 40, 265),
    moving: bool = True,
) -> np.ndarray:
    """Construye una secuencia de fotogramas sintéticos.

    `still_box` marca una zona (x0, y0, x1, y1) que no cambia entre
    fotogramas, como haría un logo grabado. El resto de la imagen se mueve.
    """
    rng = np.random.default_rng(1234)
    frames = np.zeros((n, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.float32)

    base = rng.integers(0, 255, size=(FRAME_HEIGHT, FRAME_WIDTH)).astype(np.float32)

    for t in range(n):
        frame = base.copy()
        if moving:
            # Desplaza el contenido para simular movimiento.
            frame = np.roll(frame, t * 3, axis=1)
        if still_box:
            x0, y0, x1, y1 = still_box
            frame[y0:y1, x0:x1] = 240.0  # logo blanco fijo
        frames[t] = frame

    return frames


def test_still_map_marks_frozen_region():
    """El mapa de quietud debe marcar solo la zona congelada."""
    frames = _make_frames()
    still = _still_map(frames)

    assert still[255:262, 15:35].mean() > 0.9, "La zona fija no se detectó"
    assert still[0:40, 0:40].mean() < 0.3, "La zona en movimiento no se descartó"


def test_edge_map_detects_shape_borders():
    """El mapa de bordes debe responder a una forma con contorno."""
    frames = _make_frames()
    edges = _edge_map(frames)
    assert edges.max() > 5.0


def test_scan_finds_the_frozen_box():
    """El escaneo debe localizar la caja fija."""
    frames = _make_frames()
    still = _still_map(frames)
    edges = _edge_map(frames)

    results = _scan_windows(still, edges)
    assert results, "No se encontró ninguna ventana"

    best = max(results, key=lambda r: r[5])
    _, x, y, w, h, score, quiet, edge_density = best

    assert score > 0.3, f"Score demasiado bajo: {score}"
    # La ventana debe solaparse con la caja (10..40, 250..265).
    assert x < 40 and x + w > 10
    assert y < 265 and y + h > 250


def test_scan_ignores_fully_moving_content():
    """Un vídeo sin nada fijo no debe producir candidatos relevantes."""
    frames = _make_frames(still_box=None)
    still = _still_map(frames)
    edges = _edge_map(frames)

    results = _scan_windows(still, edges)
    best = max((r[5] for r in results), default=0.0)
    assert best < 0.65, f"Falso positivo en vídeo sin capa fija: {best}"


def test_scan_ignores_flat_static_area():
    """Una zona quieta y de degradado suave (un viñeteo, un fondo liso) no
    debe confundirse con un logo: un logo tiene bordes definidos, un
    degradado no."""
    n = 12
    rng = np.random.default_rng(7)
    frames = np.zeros((n, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.float32)

    # Viñeteo: oscurece progresivamente hacia los bordes, como un filtro
    # de lente. Es estático y suave, no un logo.
    vignette = np.linspace(0, 255, FRAME_WIDTH, dtype=np.float32)[None, :]
    vignette = np.repeat(vignette, FRAME_HEIGHT, axis=0)

    for t in range(n):
        frame = rng.integers(0, 255, size=(FRAME_HEIGHT, FRAME_WIDTH)).astype(np.float32)
        frame = (frame * 0.3 + vignette * 0.7).astype(np.float32)
        frames[t] = frame

    still = _still_map(frames)
    edges = _edge_map(frames)
    results = _scan_windows(still, edges)
    best = max((r[5] for r in results), default=0.0)
    assert best < 0.65, f"Una zona degradada se confundió con un logo: {best}"


def test_missing_file_returns_error():
    from pathlib import Path

    report = detect_watermark(Path("/tmp/does-not-exist-12345.mp4"))
    assert report.detected is False
    assert report.error is not None
    assert "no disponible" in report.summary


def test_report_fields_are_consistent(tmp_path):
    """Con un vídeo real cualquiera, el informe debe ser coherente."""
    from pathlib import Path

    video = tmp_path / "video.mp4"
    cmd = [
        str(resolve_binaries().ffmpeg),
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "gradients=size=320x568:rate=25:c0=black:c1=white:duration=2:speed=0.5",
        "-t",
        "2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(video),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        pytest.skip("No se pudo generar el vídeo de prueba")

    report = detect_watermark(video)
    assert report.error is None
    assert report.frames_analyzed > 0
    assert 0.0 <= report.confidence <= 1.0
    if report.detected:
        assert report.regions
        for region in report.regions:
            assert region.width > 0 and region.height > 0
            assert 0.0 <= region.score <= 1.0
