"""
Reels Factory - Utilities Module
=================================
Common utilities and helper functions.
"""

import hashlib
import json
import logging
import re
import subprocess
import unicodedata
from datetime import datetime
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from deps import resolve_binaries


def setup_logger(
    name: str, log_file: Path | None = None, level: int = logging.INFO
) -> logging.Logger:
    """
    Set up a logger with console and optional file output.

    Args:
        name: Logger name
        log_file: Optional path to log file
        level: Logging level

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def validate_tiktok_url(url: str) -> bool:
    """
    Validate if the URL is a valid TikTok video URL.

    Args:
        url: URL to validate

    Returns:
        True if valid TikTok URL, False otherwise
    """
    return any(re.match(pattern, url) for pattern in TIKTOK_URL_PATTERNS)


#: Patrones de URL de TikTok soportados.
TIKTOK_URL_PATTERNS = (
    r"https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+",
    r"https?://(?:vm|vt)\.tiktok\.com/[\w]+",
    r"https?://(?:www\.)?tiktok\.com/t/[\w]+",
)

#: Patrones de URL de Instagram Reels.
INSTAGRAM_URL_PATTERNS = (
    r"https?://(?:www\.)?instagram\.com/reel/[\w-]+",
    r"https?://(?:www\.)?instagram\.com/reels/[\w-]+",
    r"https?://(?:www\.)?instagram\.com/p/[\w-]+",
    r"https?://(?:www\.)?instagram\.com/tv/[\w-]+",
)

#: Patrones de URL de YouTube Shorts.
YOUTUBE_URL_PATTERNS = (
    r"https?://(?:www\.|m\.)?youtube\.com/shorts/[\w-]+",
    r"https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+",
    r"https?://youtu\.be/[\w-]+",
)

#: Todos los patrones soportados, por plataforma.
SUPPORTED_URL_PATTERNS: dict[str, tuple[str, ...]] = {
    "tiktok": TIKTOK_URL_PATTERNS,
    "instagram": INSTAGRAM_URL_PATTERNS,
    "youtube": YOUTUBE_URL_PATTERNS,
}


def detect_platform(url: str) -> str | None:
    """
    Detecta la plataforma de una URL de vídeo.

    Args:
        url: URL a clasificar

    Returns:
        "tiktok", "instagram", "youtube" o None si no es soportada
    """
    for platform, patterns in SUPPORTED_URL_PATTERNS.items():
        if any(re.match(pattern, url) for pattern in patterns):
            return platform
    return None


def validate_video_url(url: str) -> bool:
    """
    Valida si la URL apunta a un vídeo de una plataforma soportada.

    Soporta TikTok, Instagram Reels y YouTube Shorts.

    Args:
        url: URL a validar

    Returns:
        True si la URL es válida y de una plataforma soportada
    """
    return detect_platform(url) is not None


def sanitize_filename(filename: str, max_length: int = 50) -> str:
    """
    Sanitize a filename by removing invalid characters.

    Accented characters are transliterated to their ASCII base letter
    (e.g. "ñ" -> "n") so Spanish titles keep their meaning instead of
    losing characters entirely.

    Args:
        filename: Original filename
        max_length: Maximum length for the filename

    Returns:
        Sanitized filename
    """
    # Remove problematic characters including apostrophes and quotes
    sanitized = re.sub(r'[<>:"/\\|?*#\[\],;=\n\r\t\'"`]', "", filename)
    # Replace spaces with underscores
    sanitized = re.sub(r"\s+", "_", sanitized)
    # Transliterate accented characters to their ASCII base letter
    sanitized = unicodedata.normalize("NFKD", sanitized)
    sanitized = sanitized.encode("ascii", "ignore").decode()
    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    # Remove trailing dots and spaces
    sanitized = sanitized.rstrip(". ")

    return sanitized or "video"


@lru_cache(maxsize=32)
def ffmpeg_has_filter(filter_name: str) -> bool:
    """Comprueba si el FFmpeg resuelto incluye un filtro concreto.

    El resultado se cachea: `ffmpeg -filters` tarda ~0.4s y se consulta en
    cada arranque y en cada inicio de proceso. La caché se invalida con
    `clear_ffmpeg_filter_cache()` cuando cambia el binario de FFmpeg.
    """
    try:
        bins = resolve_binaries()
        if not bins.ffmpeg:
            return False
        result = subprocess.run(
            [str(bins.ffmpeg), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        return re.search(rf"\b{re.escape(filter_name)}\b", result.stdout) is not None
    except Exception:
        return False


def clear_ffmpeg_filter_cache() -> None:
    """Invalida la caché de filtros de FFmpeg.

    Debe llamarse cuando el usuario selecciona o instala otro FFmpeg.
    """
    ffmpeg_has_filter.cache_clear()


def check_ffmpeg_subtitles_support() -> tuple[bool, str]:
    if not ffmpeg_has_filter("subtitles"):
        return (
            False,
            "FFmpeg sin soporte de subtítulos (falta filtro 'subtitles'). Instala ffmpeg-full y ejecútalo desde ./run.sh para usar su PATH.",
        )
    return True, "subtitles OK"


def generate_unique_filename(base_name: str, extension: str = "mp4") -> str:
    """
    Generate a unique filename with timestamp.

    Args:
        base_name: Base name for the file
        extension: File extension

    Returns:
        Unique filename
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized = sanitize_filename(base_name)
    return f"{sanitized}_{timestamp}.{extension}"


def get_video_hash(file_path: Path) -> str:
    """
    Generate a short hash for a video file (for deduplication).

    Args:
        file_path: Path to the video file

    Returns:
        Short hash string
    """
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        # Read first 1MB for quick hashing
        chunk = f.read(1024 * 1024)
        hasher.update(chunk)
    return hasher.hexdigest()[:12]


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to MM:SS format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string
    """
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in bytes to human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted size string
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def check_ffmpeg_installed() -> tuple[bool, str]:
    """
    Check if FFmpeg is installed and accessible.

    Returns:
        Tuple of (is_installed, version_or_error)
    """
    try:
        bins = resolve_binaries()
        if not bins.ffmpeg:
            return (
                False,
                "FFmpeg not found. Instala ffmpeg-full (macOS) o configura REELSFACTORYPRO_FFMPEG",
            )

        result = subprocess.run([str(bins.ffmpeg), "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            # Extract version from first line
            version_line = result.stdout.split("\n")[0]
            return True, version_line
        return False, "FFmpeg not working properly"
    except FileNotFoundError:
        return False, "FFmpeg not found. Please install with: brew install ffmpeg"


def check_yt_dlp_installed() -> tuple[bool, str]:
    """
    Check if yt-dlp is installed and accessible.

    Returns:
        Tuple of (is_installed, version_or_error)
    """
    try:
        import yt_dlp

        return True, f"yt-dlp {yt_dlp.version.__version__}"
    except Exception:
        return False, "yt-dlp no disponible. Instala con: pip install yt-dlp"


@lru_cache(maxsize=1)
def check_videotoolbox_support() -> bool:
    """Comprueba si el FFmpeg instalado soporta aceleración por hardware con h264_videotoolbox."""
    try:
        import sys

        if sys.platform != "darwin":
            return False
        bins = resolve_binaries()
        if not bins.ffmpeg:
            return False
        result = subprocess.run(
            [str(bins.ffmpeg), "-encoders"], capture_output=True, text=True, timeout=5
        )
        return "h264_videotoolbox" in (result.stdout or "")
    except Exception:
        return False


def get_video_info(file_path: Path) -> dict | None:
    """
    Get video information using FFprobe.

    Args:
        file_path: Path to the video file

    Returns:
        Dictionary with video info or None if error
    """
    try:
        bins = resolve_binaries()
        if not bins.ffprobe:
            return None

        result = subprocess.run(
            [
                str(bins.ffprobe),
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            data = json.loads(result.stdout)

            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if video_stream:
                format_info = data.get("format", {})
                duration = float(format_info.get("duration", 0))

                # Parse FPS
                fps_raw = str(video_stream.get("r_frame_rate", "30/1"))
                try:
                    fps = float(Fraction(fps_raw))
                    if fps <= 0 or fps > 120:  # Sanity check
                        fps = 30.0
                except (ValueError, ZeroDivisionError):
                    fps = 30.0

                return {
                    "width": int(video_stream.get("width", 0)),
                    "height": int(video_stream.get("height", 0)),
                    "duration": duration,
                    "duration_formatted": format_duration(duration),
                    "codec": video_stream.get("codec_name", "unknown"),
                    "fps": fps,
                    "size": int(format_info.get("size", 0)),
                    "size_formatted": format_file_size(int(format_info.get("size", 0))),
                }

        return None

    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


class ProgressCallback:
    """Progress callback handler for tracking operations."""

    def __init__(self, callback=None):
        self.callback = callback
        self.current = 0
        self.total = 100
        self.status = ""

    def update(self, current: int, total: int = 100, status: str = ""):
        """Update progress."""
        self.current = current
        self.total = total
        self.status = status

        if self.callback:
            self.callback(current, total, status)

    def increment(self, amount: int = 1, status: str = ""):
        """Increment progress by amount."""
        self.update(min(self.current + amount, self.total), self.total, status)
