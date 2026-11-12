"""Tests de empaquetado e instalación.

Comprueban que el proyecto es instalable y que los módulos quedan
accesibles con los nombres que usa el propio código (layout plano).
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_pyproject_declares_version_and_dependencies():
    data = _load_pyproject()
    project = data["project"]
    assert project["name"] == "reels-factory"
    assert project["version"] == "1.3.0"
    assert project["requires-python"] == ">=3.11"

    deps = " ".join(project["dependencies"])
    for package in ["yt-dlp", "PySide6", "openai-whisper", "torch"]:
        assert package in deps


def test_pyproject_exposes_all_modules():
    """Todos los módulos del proyecto deben quedar empaquetados.

    Regresión: en v1.2.0 `jobstore` y `settings` no existían y el layout
    anterior (`package-dir`) hacía que el editable install no resolviera
    ningún módulo, rompiendo `pip install -e .`.
    """
    data = _load_pyproject()
    modules = set(data["tool"]["setuptools"]["py-modules"])

    expected = {
        "app",
        "config",
        "deps",
        "downloader",
        "jobstore",
        "pipeline",
        "processor",
        "settings",
        "subtitler",
        "subtitles",
        "utils",
        "video_processor",
    }
    assert expected <= modules, f"Faltan módulos: {expected - modules}"


def test_every_module_file_is_declared():
    """Cada .py de la raíz (salvo __init__) debe estar en py-modules."""
    data = _load_pyproject()
    modules = set(data["tool"]["setuptools"]["py-modules"])

    on_disk = {p.stem for p in REPO_ROOT.glob("*.py") if p.stem not in ("__init__", "setup")}
    assert on_disk == modules, f"Discrepancia: {on_disk ^ modules}"


def test_modules_are_importable_by_their_flat_names():
    """Los imports absolutos que usa el propio código deben resolverse."""
    code = (
        "import config, deps, downloader, jobstore, pipeline, processor, "
        "settings, subtitler, subtitles, utils, video_processor; "
        "print(config.config.APP_VERSION)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.3.0"


@pytest.mark.parametrize(
    "module",
    [
        "app",
        "config",
        "deps",
        "downloader",
        "jobstore",
        "pipeline",
        "processor",
        "settings",
        "subtitler",
        "subtitles",
        "utils",
        "video_processor",
    ],
)
def test_each_module_compiles(module):
    """Cada módulo debe ser sintácticamente válido."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", f"{module}.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
