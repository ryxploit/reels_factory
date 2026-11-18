"""Tests de regresión para config.py."""

import os
from pathlib import Path

import pytest

from config import Config, PathConfig


def test_default_paths_are_created_under_base(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSFACTORYPRO_BASE_DIR", raising=False)
    paths = PathConfig(tmp_path)

    assert paths.BASE_PATH == tmp_path
    for path in (
        paths.INPUT_PATH,
        paths.TEMP_PATH,
        paths.OUTPUT_PATH,
        paths.LOGS_PATH,
        paths.DOWNLOADS_PATH,
        paths.SUBTITLES_PATH,
    ):
        assert path.is_dir(), f"{path} no fue creado"


def test_assets_path_follows_program_not_base_dir(tmp_path, monkeypatch):
    """Regresión: los assets se buscaban en BASE_PATH, así que al definir
    REELSFACTORYPRO_BASE_DIR desaparecían el logo y el icono."""
    monkeypatch.setenv("REELSFACTORYPRO_BASE_DIR", str(tmp_path))
    paths = PathConfig()

    repo_root = Path(__file__).resolve().parent.parent
    assert paths.ASSETS_PATH == repo_root / "assets"
    assert paths.ASSETS_PATH.is_dir()
    assert (paths.ASSETS_PATH / "logo.svg").exists()
    # El directorio de datos sí sigue la variable de entorno.
    assert paths.OUTPUT_PATH == tmp_path / "output"


def test_config_version_is_consistent():
    cfg = Config()
    assert cfg.APP_VERSION == "1.5.0"
    assert cfg.APP_NAME == "ReelsFactoryPro"


def test_debug_flag_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REELSFACTORYPRO_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("REELS_FACTORY_DEBUG", "true")
    assert Config().DEBUG is True

    monkeypatch.setenv("REELS_FACTORY_DEBUG", "false")
    assert Config().DEBUG is False
