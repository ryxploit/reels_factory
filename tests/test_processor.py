"""Tests de regresión para processor.py."""

from pathlib import Path

import pytest

from processor import VideoProcessor


@pytest.fixture
def processor(tmp_path):
    return VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")


def test_crop_filter_widescreen_crops_sides(processor):
    """1920x1080 -> 1080x1920 recorta por los lados."""
    f = processor._calculate_crop_filter(1920, 1080, 1080, 1920)
    assert f.startswith("crop=")
    # Ancho recortado = 1080 * (1080/1920) = 607
    assert "607" in f


def test_crop_filter_tall_crops_top_bottom(processor):
    """1080x1920 -> 1080x1920 no necesita recorte."""
    f = processor._calculate_crop_filter(1080, 1920, 1080, 1920)
    assert f == "crop=1080:1920:0:0"


def test_build_video_filters_scales_and_sets_fps(processor):
    f = processor._build_video_filters(1080, 1920)
    assert "scale=1080:1920" in f
    assert f"fps={processor.video_config.FPS}" in f


def test_build_video_filters_uses_local_rng_not_global(processor):
    """Regresión: se sembraba `random.seed()` global, alterando el RNG del proceso."""
    import random

    random.seed(1234)
    expected = [random.random() for _ in range(3)]

    random.seed(1234)
    processor._build_video_filters(1080, 1920)
    after = [random.random() for _ in range(3)]

    assert after == expected


def test_escape_filter_value_escapes_specials(processor):
    escaped = processor._escape_filter_value("/tmp/a b:c#d[e].ass")
    assert "\\:" in escaped
    assert "\\#" in escaped
    assert "\\[" in escaped
    assert "\\]" in escaped


def test_temp_artifact_cleanup_removes_files(processor):
    artifact = processor.temp_dir / "subs_test.ass"
    artifact.write_text("x", encoding="utf-8")
    processor._temp_artifacts.append(artifact)

    processor._cleanup_temp_artifacts()

    assert not artifact.exists()
    assert processor._temp_artifacts == []


def test_build_ffmpeg_command_requires_ffmpeg(processor, monkeypatch):
    from deps import ResolvedBinaries

    monkeypatch.setattr(
        "processor.resolve_binaries", lambda *a, **k: ResolvedBinaries(ffmpeg=None, ffprobe=None)
    )
    with pytest.raises(RuntimeError, match="FFmpeg not found"):
        processor._build_ffmpeg_command(
            input_path=Path("/tmp/in.mp4"),
            output_path=Path("/tmp/out.mp4"),
            input_width=1080,
            input_height=1920,
            duration=10.0,
        )


def test_encoding_settings_uses_videotoolbox_when_available(processor, monkeypatch):
    monkeypatch.setattr("processor.check_videotoolbox_support", lambda: True)
    monkeypatch.setattr("sys.platform", "darwin")
    processor.hw_accel_enabled = True

    settings = processor._add_encoding_settings()
    assert "-c:v" in settings
    codec_idx = settings.index("-c:v") + 1
    assert settings[codec_idx] == "h264_videotoolbox"


def test_encoding_settings_falls_back_to_libx264(processor, monkeypatch):
    monkeypatch.setattr("processor.check_videotoolbox_support", lambda: False)
    processor.hw_accel_enabled = True

    settings = processor._add_encoding_settings()
    assert "-c:v" in settings
    codec_idx = settings.index("-c:v") + 1
    assert settings[codec_idx] == "libx264"
    assert "-preset" in settings
