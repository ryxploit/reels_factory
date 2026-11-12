from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolvedBinaries:
    ffmpeg: Path | None
    ffprobe: Path | None


def _is_executable_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and os.access(path, os.X_OK)
    except Exception:
        return False


def _which(name: str) -> Path | None:
    p = shutil.which(name)
    return Path(p).resolve() if p else None


def _meipass_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base).resolve() if base else None


def resolve_binaries(base_dir: Path | None = None) -> ResolvedBinaries:
    """Localiza los binarios de FFmpeg/ffprobe.

    Orden de resolución:
    1. Variables de entorno `REELSFACTORYPRO_FFMPEG` / `REELSFACTORYPRO_FFPROBE`.
    2. `<base_dir>/third_party/ffmpeg/bin/` (binarios empaquetados).
    3. Bundle de PyInstaller (`_MEIPASS`).
    4. `PATH` del sistema.

    Args:
        base_dir: Carpeta base donde buscar `third_party/`. Si es None se usa
            la carpeta base configurada en `config.paths.BASE_PATH`.

    Returns:
        ResolvedBinaries con las rutas encontradas (None si no existen).
    """
    if base_dir is None:
        # Import perezoso para evitar ciclos de importación.
        from config import config

        base_dir = config.paths.BASE_PATH

    env_ffmpeg = os.environ.get("REELSFACTORYPRO_FFMPEG")
    env_ffprobe = os.environ.get("REELSFACTORYPRO_FFPROBE")

    candidates_ffmpeg: list[Path] = []
    candidates_ffprobe: list[Path] = []

    if env_ffmpeg:
        candidates_ffmpeg.append(Path(env_ffmpeg).expanduser())
    if env_ffprobe:
        candidates_ffprobe.append(Path(env_ffprobe).expanduser())

    if base_dir:
        for rel in [
            Path("third_party/ffmpeg/bin/ffmpeg"),
            Path("third_party/ffmpeg/bin/ffmpeg.exe"),
        ]:
            candidates_ffmpeg.append((base_dir / rel).resolve())
        for rel in [
            Path("third_party/ffmpeg/bin/ffprobe"),
            Path("third_party/ffmpeg/bin/ffprobe.exe"),
        ]:
            candidates_ffprobe.append((base_dir / rel).resolve())

    meipass = _meipass_dir()
    if meipass:
        candidates_ffmpeg.append(
            (
                meipass / "ffmpeg" / ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
            ).resolve()
        )
        candidates_ffprobe.append(
            (
                meipass
                / "ffmpeg"
                / ("ffprobe.exe" if sys.platform.startswith("win") else "ffprobe")
            ).resolve()
        )

    sys_ffmpeg = _which("ffmpeg")
    sys_ffprobe = _which("ffprobe")
    if sys_ffmpeg:
        candidates_ffmpeg.append(sys_ffmpeg)
    if sys_ffprobe:
        candidates_ffprobe.append(sys_ffprobe)

    ffmpeg = next((p for p in candidates_ffmpeg if _is_executable_file(p)), None)
    ffprobe = next((p for p in candidates_ffprobe if _is_executable_file(p)), None)

    return ResolvedBinaries(ffmpeg=ffmpeg, ffprobe=ffprobe)
