"""ReelsFactoryPro.

Aplicación de escritorio multiplataforma (macOS/Windows) para descargar vídeos
de TikTok, Instagram Reels y YouTube Shorts (yt-dlp), procesar a
1080x1920/<=55s (FFmpeg + overlay) y generar subtítulos con Whisper (MPS en
macOS cuando está disponible).

Los módulos se importan de forma absoluta (``from config import ...``) porque
el proyecto usa un layout plano: los módulos viven en la raíz del repositorio
y así se pueden usar tanto como script suelto (``python app.py``) como tras
``pip install -e .``.
"""

import os
import sys

__version__ = "1.5.0"
__author__ = "ReelsFactoryPro"

# Hace resolubles los imports absolutos internos cuando el paquete se importa
# desde otro directorio (por ejemplo, tras una instalación normal).
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

from config import Config, config  # noqa: E402
from downloader import TikTokDownloader, download_tiktok  # noqa: E402
from jobstore import JobStore, StoredJob  # noqa: E402
from pipeline import PipelineSettings, ReelsPipeline  # noqa: E402
from processor import ProcessingResult, VideoProcessor, process_for_reels  # noqa: E402
from settings import AppSettings, SettingsStore  # noqa: E402
from subtitles import (  # noqa: E402
    SubtitleGenerator,
    SubtitleResult,
    SubtitleSegment,
    SubtitleWord,
    generate_subtitles,
)

__all__ = [
    "AppSettings",
    "Config",
    "JobStore",
    "PipelineSettings",
    "ProcessingResult",
    "ReelsPipeline",
    "SettingsStore",
    "StoredJob",
    "SubtitleGenerator",
    "SubtitleResult",
    "SubtitleSegment",
    "SubtitleWord",
    "TikTokDownloader",
    "VideoProcessor",
    "config",
    "download_tiktok",
    "generate_subtitles",
    "process_for_reels",
]
