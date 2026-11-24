"""Tests de las mejoras añadidas: plataformas, loudnorm, resaltado y validación."""

import pytest

from config import config
from processor import VideoProcessor
from subtitles import SubtitleGenerator, SubtitleSegment, SubtitleWord
from utils import detect_platform, validate_video_url

# ----------------------------------------------------------------------
# Mejora 11: más plataformas
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.tiktok.com/@user/video/123", "tiktok"),
        ("https://vm.tiktok.com/ZMabc123/", "tiktok"),
        ("https://www.instagram.com/reel/ABC123xyz/", "instagram"),
        ("https://www.instagram.com/p/ABC123xyz/", "instagram"),
        ("https://www.youtube.com/shorts/ABC123xyz", "youtube"),
        ("https://youtu.be/ABC123xyz", "youtube"),
        ("https://www.youtube.com/watch?v=ABC123xyz", "youtube"),
    ],
)
def test_detect_platform(url, expected):
    assert detect_platform(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/1",
        "https://vimeo.com/12345",
        "no-es-una-url",
    ],
)
def test_detect_platform_rejects_unsupported(url):
    assert detect_platform(url) is None
    assert validate_video_url(url) is False


def test_validate_video_url_accepts_all_platforms():
    assert validate_video_url("https://www.tiktok.com/@u/video/1")
    assert validate_video_url("https://www.instagram.com/reel/ABC/")
    assert validate_video_url("https://youtu.be/ABC")


# ----------------------------------------------------------------------
# Mejora 4: normalización de audio (loudnorm)
# ----------------------------------------------------------------------


def test_loudnorm_enabled_by_default():
    assert config.video.ENABLE_LOUDNORM is True
    assert config.video.LOUDNORM_I == "-14"


def test_encoding_settings_include_loudnorm(tmp_path):
    processor = VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")
    opts = processor._add_encoding_settings()
    assert "-af" in opts
    idx = opts.index("-af")
    assert "loudnorm=I=-14" in opts[idx + 1]
    assert "TP=-1.5" in opts[idx + 1]
    assert "LRA=11" in opts[idx + 1]


def test_loudnorm_can_be_disabled(tmp_path, monkeypatch):
    """Al desactivar loudnorm, el filtro de audio ya no incluye la normalización.

    El filtro `-af` puede seguir presente por la evasión de audio, pero sin
    `loudnorm`.
    """
    processor = VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")
    monkeypatch.setattr(processor.video_config, "ENABLE_LOUDNORM", False)
    processor.evasion_enabled = False

    opts = processor._add_encoding_settings()
    assert "-af" not in opts


# ----------------------------------------------------------------------
# Mejora 1: validación del output
# ----------------------------------------------------------------------


def test_validate_output_accepts_compliant_video(tmp_path):
    processor = VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")
    info = {"width": 1080, "height": 1920, "duration": 30.0}
    assert processor._validate_output(info) == []


def test_validate_output_flags_wrong_dimensions(tmp_path):
    processor = VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")
    info = {"width": 720, "height": 1280, "duration": 30.0}
    warnings = processor._validate_output(info)
    assert any("720x1280" in w for w in warnings)


def test_validate_output_flags_too_long(tmp_path):
    processor = VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")
    info = {"width": 1080, "height": 1920, "duration": 90.0}
    warnings = processor._validate_output(info)
    assert any("90.0s" in w for w in warnings)


def test_validate_output_handles_missing_info(tmp_path):
    processor = VideoProcessor(output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp")
    warnings = processor._validate_output(None)
    assert len(warnings) == 1


# ----------------------------------------------------------------------
# Mejora 3: resaltado de palabra
# ----------------------------------------------------------------------


def test_word_highlight_generates_one_dialogue_per_word(tmp_path):
    generator = SubtitleGenerator(output_dir=tmp_path)
    segment = SubtitleSegment(
        start=0.0,
        end=2.0,
        text="Hola mundo",
        words=[
            SubtitleWord(start=0.0, end=1.0, text="Hola"),
            SubtitleWord(start=1.0, end=2.0, text="mundo"),
        ],
    )
    ass = generator._segments_to_ass([segment])
    assert ass.count("Dialogue:") == 2
    # La palabra activa debe llevar el color de destaque.
    assert config.subtitle.HIGHLIGHT_COLOR in ass


def test_word_highlight_disabled_falls_back_to_single_dialogue(tmp_path):
    generator = SubtitleGenerator(output_dir=tmp_path)
    generator.subtitle_config.ENABLE_WORD_HIGHLIGHT = False
    segment = SubtitleSegment(
        start=0.0,
        end=2.0,
        text="Hola mundo",
        words=[
            SubtitleWord(start=0.0, end=1.0, text="Hola"),
            SubtitleWord(start=1.0, end=2.0, text="mundo"),
        ],
    )
    ass = generator._segments_to_ass([segment])
    assert ass.count("Dialogue:") == 1
    assert "Hola mundo" in ass


def test_word_highlight_preserves_full_text(tmp_path):
    """Cada evento debe mostrar el texto completo, no solo la palabra."""
    generator = SubtitleGenerator(output_dir=tmp_path)
    segment = SubtitleSegment(
        start=0.0,
        end=2.0,
        text="Hola mundo cruel",
        words=[
            SubtitleWord(start=0.0, end=1.0, text="Hola"),
            SubtitleWord(start=1.0, end=1.5, text="mundo"),
            SubtitleWord(start=1.5, end=2.0, text="cruel"),
        ],
    )
    ass = generator._segments_to_ass([segment])
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            assert "Hola" in line and "mundo" in line and "cruel" in line


def test_segments_without_words_still_work(tmp_path):
    generator = SubtitleGenerator(output_dir=tmp_path)
    segment = SubtitleSegment(start=0.0, end=2.0, text="Sin palabras")
    ass = generator._segments_to_ass([segment])
    assert ass.count("Dialogue:") == 1
    assert "Sin palabras" in ass


# ----------------------------------------------------------------------
# Mejora 9: exportación de SRT
# ----------------------------------------------------------------------


def test_export_srt_creates_file(tmp_path):
    generator = SubtitleGenerator(output_dir=tmp_path)
    segments = [
        SubtitleSegment(start=0.0, end=1.5, text="Hola"),
        SubtitleSegment(start=1.5, end=3.0, text="Mundo"),
    ]
    written = generator.export_srt(segments, "exportado")
    assert written is not None
    assert written.exists()
    assert written.suffix == ".srt"
    content = written.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,500" in content
    assert "Hola" in content


def test_export_srt_without_segments_returns_none(tmp_path):
    generator = SubtitleGenerator(output_dir=tmp_path)
    assert generator.export_srt([], "vacio") is None


# ----------------------------------------------------------------------
# Mejora 5: modelos de Whisper disponibles
# ----------------------------------------------------------------------


def test_available_models_include_turbo_variants():
    models = config.subtitle.AVAILABLE_MODELS
    assert "turbo" in models
    assert "large-v3-turbo" in models
    assert "large-v3" in models
    # Todos deben existir en openai-whisper (si no está instalado, se omite).
    whisper = pytest.importorskip("whisper")

    available = set(whisper.available_models())
    assert set(models).issubset(available)
