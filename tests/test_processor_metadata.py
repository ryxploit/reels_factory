"""Tests de regresión para el procesado de video (processor.py).

Verifica el comportamiento observable del comando FFmpeg generado: no basta
con que el código contenga certain cadenas, el comando debe ser correcto.
"""

import pytest

from processor import VideoProcessor


@pytest.fixture
def processor(tmp_path):
    return VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")


def test_metadata_is_stripped(processor):
    """El video de salida no debe llevar metadatos del original."""
    opts = processor._add_metadata_settings()
    assert "-map_metadata" in opts
    assert "-map_chapters" in opts
    assert "-1" in opts


def test_encoding_is_facebook_compatible(processor):
    opts = processor._add_encoding_settings()
    assert any(c in opts for c in ("libx264", "h264_videotoolbox"))
    assert "yuv420p" in opts
    assert "+faststart" in opts


def test_output_is_vertical_1080x1920(processor):
    f = processor._build_video_filters(1080, 1920)
    assert "scale=1080:1920" in f
    assert "fps=30" in f


def test_variations_add_subtle_color_and_noise(processor):
    f = processor._build_video_filters(1080, 1920)
    assert "eq=brightness=" in f
    assert "noise=" in f


def test_command_caps_duration_at_55s(processor, monkeypatch):
    """Un video de 3 minutos debe recortarse a 55 segundos."""
    from deps import ResolvedBinaries

    fake_ffmpeg = processor.temp_dir / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "processor.resolve_binaries",
        lambda *a, **k: ResolvedBinaries(ffmpeg=fake_ffmpeg, ffprobe=None),
    )

    cmd = processor._build_ffmpeg_command(
        input_path=processor.temp_dir / "in.mp4",
        output_path=processor.temp_dir / "out.mp4",
        input_width=1080,
        input_height=1920,
        duration=180.0,
    )
    idx = cmd.index("-t")
    assert float(cmd[idx + 1]) == 55.0


def test_command_caps_duration_under_limit(processor, monkeypatch):
    from deps import ResolvedBinaries

    fake_ffmpeg = processor.temp_dir / "ffmpeg"
    fake_ffmpeg.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "processor.resolve_binaries",
        lambda *a, **k: ResolvedBinaries(ffmpeg=fake_ffmpeg, ffprobe=None),
    )

    cmd = processor._build_ffmpeg_command(
        input_path=processor.temp_dir / "in.mp4",
        output_path=processor.temp_dir / "out.mp4",
        input_width=1080,
        input_height=1920,
        duration=20.0,
    )
    idx = cmd.index("-t")
    assert float(cmd[idx + 1]) == 20.0
