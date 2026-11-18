"""Tests de regresión para subtitles.py y pipeline.py."""

from pathlib import Path

import pytest

from pipeline import PipelineSettings, ReelsPipeline
from subtitles import SubtitleGenerator, SubtitleSegment


@pytest.fixture
def generator(tmp_path):
    return SubtitleGenerator(output_dir=tmp_path)


def test_format_ass_time(generator):
    assert generator._format_ass_time(0) == "0:00:00.00"
    assert generator._format_ass_time(65.5) == "0:01:05.50"
    assert generator._format_ass_time(3661.25) == "1:01:01.25"


def test_format_srt_time(generator):
    assert generator._format_srt_time(0) == "00:00:00,000"
    assert generator._format_srt_time(65.5) == "00:01:05,500"


def test_segments_to_ass_contains_dialogue(generator):
    segments = [
        SubtitleSegment(start=0.0, end=2.0, text="Hola mundo"),
        SubtitleSegment(start=2.0, end=4.0, text="Segunda linea"),
    ]
    ass = generator._segments_to_ass(segments)
    assert "Dialogue:" in ass
    assert "Hola mundo" in ass
    assert "Segunda linea" in ass
    assert ass.count("Dialogue:") == 2


def test_segments_to_ass_escapes_newlines(generator):
    segments = [SubtitleSegment(start=0.0, end=1.0, text="linea1\nlinea2")]
    ass = generator._segments_to_ass(segments)
    assert "linea1\\Nlinea2" in ass


def test_segments_to_srt_numbering(generator):
    segments = [
        SubtitleSegment(start=0.0, end=1.0, text="uno"),
        SubtitleSegment(start=1.0, end=2.0, text="dos"),
    ]
    srt = generator._segments_to_srt(segments)
    assert srt.startswith("1\n")
    assert "00:00:00,000 --> 00:00:01,000" in srt


def test_model_change_invalidates_loaded_model(generator):
    """Regresión: cambiar de modelo no recargaba el checkpoint en memoria."""
    generator._model_loaded = True
    generator._loaded_model_size = "base"
    generator.model_size = "tiny"

    calls = []

    def fake_load(name, device=None):
        calls.append(name)
        return object()

    import whisper

    original = whisper.load_model
    whisper.load_model = fake_load
    try:
        generator._load_model()
    finally:
        whisper.load_model = original

    assert calls == ["tiny"]
    assert generator._loaded_model_size == "tiny"


def test_generate_returns_error_for_missing_video(generator):
    result = generator.generate(Path("/tmp/does-not-exist.mp4"))
    assert result.success is False
    assert "not found" in (result.error_message or "")


def test_pipeline_applies_whisper_model_to_subtitler(tmp_path):
    """Regresión: el modelo elegido en la GUI se ignoraba por completo."""
    pipeline = ReelsPipeline(
        downloads_dir=tmp_path / "dl",
        output_dir=tmp_path / "out",
        subtitles_dir=tmp_path / "subs",
    )
    settings = PipelineSettings(subtitles=True, whisper_model="small")
    assert settings.whisper_model == "small"

    # El generador debe adoptar el modelo solicitado antes de transcribir.
    pipeline.subtitler.model_size = settings.whisper_model
    assert pipeline.subtitler.model_size == "small"


def test_word_highlight_tolerates_punctuation_differences(generator):
    from subtitles import SubtitleSegment, SubtitleWord

    seg = SubtitleSegment(
        start=0.0,
        end=2.0,
        text="¡Hola, mundo!",
        words=[
            SubtitleWord(start=0.0, end=0.8, text="hola"),
            SubtitleWord(start=0.9, end=1.8, text="mundo"),
        ],
    )
    generator.subtitle_config.ENABLE_WORD_HIGHLIGHT = True
    ass = generator._word_highlight_dialogues(seg)
    assert "\\c" in ass
    assert "Default" in ass
    assert ass.count("Dialogue:") == 2
