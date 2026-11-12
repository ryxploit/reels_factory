"""Tests de evasión de huella digital (evasion.py)."""

import pytest

from config import config
from evasion import EvasionProfile, build_video_filter_chain, default_profile


def test_default_profile_reads_config():
    profile = default_profile()
    assert profile.enable_frame_shift == config.fingerprint.ENABLE_FRAME_SHIFT
    assert profile.enable_speed_change == config.fingerprint.ENABLE_SPEED_CHANGE
    assert profile.enable_gamma_shift == config.fingerprint.ENABLE_GAMMA_SHIFT
    assert profile.enable_pitch_shift == config.fingerprint.ENABLE_PITCH_SHIFT
    assert profile.speed_factor == config.fingerprint.SPEED_FACTOR
    assert profile.pitch_factor == config.fingerprint.PITCH_FACTOR


def test_video_filters_include_techniques():
    profile = EvasionProfile()
    filters = profile.video_filters()
    joined = " ".join(filters)
    assert "setpts=" in joined
    assert "gamma=" in joined


def test_mirror_is_disabled_by_default():
    """El espejo invierte el texto de los subtítulos: desactivado por defecto."""
    profile = default_profile()
    assert profile.enable_mirror is False
    assert "hflip" not in " ".join(profile.video_filters())


def test_mirror_can_be_enabled():
    profile = EvasionProfile(enable_mirror=True)
    assert "hflip" in " ".join(profile.video_filters())


def test_audio_filters_include_pitch_shift():
    profile = EvasionProfile()
    filters = profile.audio_filters(44100)
    joined = " ".join(filters)
    assert "asetrate=" in joined
    assert "aresample=" in joined
    assert "atempo=" in joined


def test_audio_filters_include_eq_and_dither():
    profile = EvasionProfile()
    joined = " ".join(profile.audio_filters(44100))
    assert "equalizer=" in joined
    assert "asetnsamples=" in joined


def test_pitch_shift_is_audible_but_small():
    """El cambio de tono debe ser perceptible para el hash pero no al oído."""
    profile = default_profile()
    assert 1.001 < profile.pitch_factor < 1.05


def test_speed_change_is_small():
    profile = default_profile()
    assert 1.001 < profile.speed_factor < 1.02


def test_disabled_techniques_produce_no_filters():
    profile = EvasionProfile(
        enable_frame_shift=False,
        enable_speed_change=False,
        enable_gamma_shift=False,
        enable_mirror=False,
        enable_pitch_shift=False,
        enable_audio_eq=False,
        enable_audio_dither=False,
    )
    assert profile.video_filters() == []
    assert profile.audio_filters() == []
    assert profile.summary() == "ninguna"


def test_build_video_filter_chain_appends_shift():
    profile = EvasionProfile(enable_frame_shift=True, frame_shift_px=3)
    chain = build_video_filter_chain(["scale=1080:1920"], profile, 1080, 1920)
    joined = " ".join(chain)
    assert "crop=iw-6:ih-6:3:3" in joined
    assert "scale=1080:1920" in joined


def test_build_video_filter_chain_respects_target_size():
    profile = EvasionProfile(enable_frame_shift=True, frame_shift_px=2)
    chain = build_video_filter_chain([], profile, 1080, 1920)
    # El reescalado tras el recorte debe volver a las dimensiones finales.
    assert "scale=1080:1920" in chain[-1]


def test_summary_lists_applied_techniques():
    profile = default_profile()
    summary = profile.summary()
    assert "velocidad" in summary
    assert "tono" in summary
