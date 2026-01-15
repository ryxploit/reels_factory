"""
Reels Factory - Utilities Module
=================================
Common utilities and helper functions.
"""

import logging
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
import subprocess
from fractions import Fraction

from deps import resolve_binaries


def setup_logger(
    name: str,
    log_file: Optional[Path] = None,
    level: int = logging.INFO
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
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
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
    patterns = [
        r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
        r'https?://(?:vm|vt)\.tiktok\.com/[\w]+',
        r'https?://(?:www\.)?tiktok\.com/t/[\w]+',
    ]
    
    return any(re.match(pattern, url) for pattern in patterns)


def sanitize_filename(filename: str, max_length: int = 50) -> str:
    """
    Sanitize a filename by removing invalid characters.
    
    Args:
        filename: Original filename
        max_length: Maximum length for the filename
    
    Returns:
        Sanitized filename
    """
    sanitized = re.sub(r'[<>:"/\\|?*#\[\],;=\n\r\t]', '', filename)
    # Replace spaces with underscores
    sanitized = re.sub(r'\s+', '_', sanitized)
    # Remove non-ASCII characters
    sanitized = sanitized.encode('ascii', 'ignore').decode()
    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    # Remove trailing dots and spaces
    sanitized = sanitized.rstrip('. ')
    
    return sanitized or 'video'


def ffmpeg_has_filter(filter_name: str) -> bool:
    try:
        bins = resolve_binaries()
        if not bins.ffmpeg:
            return False
        result = subprocess.run(
            [str(bins.ffmpeg), '-hide_banner', '-filters'],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False

        return re.search(rf"\b{re.escape(filter_name)}\b", result.stdout) is not None
    except Exception:
        return False


def check_ffmpeg_subtitles_support() -> Tuple[bool, str]:
    if not ffmpeg_has_filter('subtitles'):
        return (
            False,
            "FFmpeg sin soporte de subtítulos (falta filtro 'subtitles'). Instala ffmpeg-full y ejecútalo desde ./run.sh para usar su PATH.",
        )
    return True, "subtitles OK"


def generate_unique_filename(base_name: str, extension: str = 'mp4') -> str:
    """
    Generate a unique filename with timestamp.
    
    Args:
        base_name: Base name for the file
        extension: File extension
    
    Returns:
        Unique filename
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
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
    with open(file_path, 'rb') as f:
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
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def check_ffmpeg_installed() -> Tuple[bool, str]:
    """
    Check if FFmpeg is installed and accessible.
    
    Returns:
        Tuple of (is_installed, version_or_error)
    """
    try:
        bins = resolve_binaries()
        if not bins.ffmpeg:
            return False, "FFmpeg not found. Instala ffmpeg-full (macOS) o configura REELSFACTORYPRO_FFMPEG"

        result = subprocess.run(
            [str(bins.ffmpeg), '-version'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            # Extract version from first line
            version_line = result.stdout.split('\n')[0]
            return True, version_line
        return False, "FFmpeg not working properly"
    except FileNotFoundError:
        return False, "FFmpeg not found. Please install with: brew install ffmpeg"


def check_yt_dlp_installed() -> Tuple[bool, str]:
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


def get_video_info(file_path: Path) -> Optional[dict]:
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
        result = subprocess.run([
            str(bins.ffprobe),
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(file_path)
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            
            # Extract relevant info
            video_stream = next(
                (s for s in data.get('streams', []) if s['codec_type'] == 'video'),
                None
            )
            
            if video_stream:
                duration = float(data.get('format', {}).get('duration', 0))
                fps_raw = str(video_stream.get('r_frame_rate', '30/1'))
                fps = 30.0
                try:
                    fps = float(Fraction(fps_raw))
                    if fps <= 0:
                        fps = 30.0
                except Exception:
                    fps = 30.0
                return {
                    'width': int(video_stream.get('width', 0)),
                    'height': int(video_stream.get('height', 0)),
                    'duration': duration,
                    'duration_formatted': format_duration(duration),
                    'codec': video_stream.get('codec_name', 'unknown'),
                    'fps': fps,
                    'size': int(data.get('format', {}).get('size', 0)),
                    'size_formatted': format_file_size(
                        int(data.get('format', {}).get('size', 0))
                    )
                }
        return None
    except Exception:
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
