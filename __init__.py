"""ReelsFactoryPro.

Aplicación de escritorio multiplataforma (macOS/Windows) para descargar TikTok
(yt-dlp), procesar a 1080x1920/<=55s (FFmpeg + overlay) y generar subtítulos
con Whisper (MPS en macOS cuando está disponible).

Los módulos internos se importan de forma absoluta (``from config import ...``)
para funcionar igual como script suelto (``python app.py``) y como paquete
instalado (``pip install reels-factory``). Para que ambos casos funcionen sin
duplicar módulos, el directorio del paquete se registra en ``sys.path`` antes
de importarlos.
"""

import os
import sys

__version__ = "1.2.0"
__author__ = "ReelsFactoryPro"

# Hace resolubles los imports absolutos internos cuando se importa como paquete.
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

from config import Config, config  # noqa: E402
from downloader import TikTokDownloader, download_tiktok  # noqa: E402
from processor import ProcessingResult, VideoProcessor, process_for_reels  # noqa: E402
from subtitles import (  # noqa: E402
    SubtitleGenerator,
    SubtitleResult,
    SubtitleSegment,
    generate_subtitles,
)

__all__ = [
    "Config",
    "ProcessingResult",
    "SubtitleGenerator",
    "SubtitleResult",
    "SubtitleSegment",
    "TikTokDownloader",
    "VideoProcessor",
    "config",
    "download_tiktok",
    "generate_subtitles",
    "process_for_reels",
]
