"""ReelsFactoryPro.

Aplicación de escritorio multiplataforma (macOS/Windows) para descargar TikTok
(yt-dlp), procesar a 1080x1920/<=55s (FFmpeg + overlay) y generar subtítulos
con Whisper (MPS en macOS cuando está disponible).
"""

__version__ = "1.1.0"
__author__ = "ReelsFactoryPro"

from config import config, Config
from downloader import TikTokDownloader, download_tiktok
from video_processor import VideoProcessor, process_for_reels
from subtitler import SubtitleGenerator, generate_subtitles

__all__ = [
    'config',
    'Config',
    'TikTokDownloader',
    'download_tiktok',
    'VideoProcessor', 
    'process_for_reels',
    'SubtitleGenerator',
    'generate_subtitles',
]
