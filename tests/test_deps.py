"""Tests de regresión para deps.py."""

import os
import stat
from pathlib import Path

from deps import ResolvedBinaries, resolve_binaries


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_env_vars_take_priority(tmp_path, monkeypatch):
    fake = _make_executable(tmp_path / "custom_ffmpeg")
    monkeypatch.setenv("REELSFACTORYPRO_FFMPEG", str(fake))
    monkeypatch.setenv("REELSFACTORYPRO_FFPROBE", str(fake))

    bins = resolve_binaries(base_dir=tmp_path)
    assert bins.ffmpeg == fake.resolve()
    assert bins.ffprobe == fake.resolve()


def test_third_party_is_searched_when_base_dir_given(tmp_path, monkeypatch):
    """Regresión: `base_dir` nunca se pasaba, así que `third_party/` no se
    buscaba nunca y los binarios empaquetados se ignoraban."""
    monkeypatch.delenv("REELSFACTORYPRO_FFMPEG", raising=False)
    monkeypatch.delenv("REELSFACTORYPRO_FFPROBE", raising=False)

    packaged = _make_executable(tmp_path / "third_party" / "ffmpeg" / "bin" / "ffmpeg")
    probe = _make_executable(tmp_path / "third_party" / "ffmpeg" / "bin" / "ffprobe")

    bins = resolve_binaries(base_dir=tmp_path)
    assert bins.ffmpeg == packaged.resolve()
    assert bins.ffprobe == probe.resolve()


def test_missing_binaries_return_none(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSFACTORYPRO_FFMPEG", raising=False)
    monkeypatch.delenv("REELSFACTORYPRO_FFPROBE", raising=False)
    monkeypatch.setattr("deps._which", lambda name: None)

    bins = resolve_binaries(base_dir=tmp_path)
    assert bins.ffmpeg is None
    assert bins.ffprobe is None


def test_non_executable_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSFACTORYPRO_FFMPEG", raising=False)
    monkeypatch.delenv("REELSFACTORYPRO_FFPROBE", raising=False)
    monkeypatch.setattr("deps._which", lambda name: None)

    not_exec = tmp_path / "third_party" / "ffmpeg" / "bin" / "ffmpeg"
    not_exec.parent.mkdir(parents=True, exist_ok=True)
    not_exec.write_text("no ejecutable", encoding="utf-8")
    not_exec.chmod(0o644)

    bins = resolve_binaries(base_dir=tmp_path)
    assert bins.ffmpeg is None
