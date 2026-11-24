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
from urllib.parse import ParseResult, urlparse

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


# ---------------------------------------------------------------------------
# Validación estricta de URLs
# ---------------------------------------------------------------------------
# Las URLs llegan desde el portapapeles y desde archivos .txt arrastrados a la
# GUI, y se pasan directamente a yt-dlp (con cookies del navegador activadas).
# Por eso se validan con urlparse + allowlist de hosts exactos + fullmatch:
# un re.match sin anclar de fin aceptaba sufijos como ".evil.com" o ";rm -rf /".

#: Caracteres prohibidos en CUALQUIER parte de la URL cruda:
#: \x00-\x20 cubre NUL, \n, \r, \t y el espacio; el resto son meta-caracteres
#: de shell, comillas y backslash que nunca aparecen en una URL legítima.
#: "&" NO está aquí: es el separador legítimo de parámetros de tracking. La
#: query se valida aparte con _SAFE_QUERY_RE.
_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f{}|;\\`$\"'<>()]")

#: Caracteres permitidos en la query (sin '?', '#', ':', '/', ';' ni meta-caracteres).
#: Cubre utm_*, t=..., y la mayoría de parámetros genéricos de las plataformas.
_SAFE_QUERY_RE = re.compile(r"\A[A-Za-z0-9._~%+=&,-]*\Z")

#: Nombre de parámetro de query permitido (claves de tracking tipo utm_source).
_SAFE_QUERY_KEY_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.-]*\Z")

#: Patrones anclados para el PATH (urlparse separa la query). Se aplican con
#: re.fullmatch para que no haya sufijos maliciosos en la ruta.
_TIKTOK_VIDEO_PATH = r"/@[\w.-]+/video/\d+/?"
_TIKTOK_SHORT_PATH = r"/t/[\w-]+/?"
_TIKTOK_CODE_PATH = r"/[\w-]+/?"
_YT_SHORTS_PATH = r"/shorts/[\w-]+/?"
_YT_WATCH_PATH = r"/watch"  # la query (v=ID) se valida en _valid_watch_query
_YT_CODE_PATH = r"/[\w-]+/?"

#: Patrones de URL de TikTok soportados (se mantienen los nombres públicos).
TIKTOK_URL_PATTERNS = (_TIKTOK_VIDEO_PATH, _TIKTOK_SHORT_PATH, _TIKTOK_CODE_PATH)

#: Patrones de URL de Instagram Reels.
INSTAGRAM_URL_PATTERNS = (r"/(?:reel|reels|p|tv)/[\w-]+/?",)

#: Patrones de URL de YouTube Shorts.
YOUTUBE_URL_PATTERNS = (_YT_SHORTS_PATH, _YT_WATCH_PATH, _YT_CODE_PATH)

#: Todos los patrones soportados, por plataforma (compatibilidad pública).
SUPPORTED_URL_PATTERNS: dict[str, tuple[str, ...]] = {
    "tiktok": TIKTOK_URL_PATTERNS,
    "instagram": INSTAGRAM_URL_PATTERNS,
    "youtube": YOUTUBE_URL_PATTERNS,
}

#: Allowlist de hosts EXACTOS por plataforma. Nunca sufijos ni comodines:
#: "tiktok.com.evil.com" no es "tiktok.com".
ALLOWED_HOSTS: dict[str, frozenset[str]] = {
    "tiktok": frozenset({"tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}),
    "instagram": frozenset({"instagram.com", "www.instagram.com"}),
    "youtube": frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}),
}

#: Mapa inverso host -> plataforma, derivado de la allowlist.
_HOST_PLATFORM = {host: platform for platform, hosts in ALLOWED_HOSTS.items() for host in hosts}

#: Patrones permitidos por host: evita mezclar formatos entre dominios (p. ej.
#: un código tipo vm.tiktok.com bajo www.tiktok.com o un /watch en youtu.be).
_HOST_PATTERNS: dict[str, tuple[str, ...]] = {
    "tiktok.com": (_TIKTOK_VIDEO_PATH, _TIKTOK_SHORT_PATH),
    "www.tiktok.com": (_TIKTOK_VIDEO_PATH, _TIKTOK_SHORT_PATH),
    "vm.tiktok.com": (_TIKTOK_CODE_PATH,),
    "vt.tiktok.com": (_TIKTOK_CODE_PATH,),
    "instagram.com": INSTAGRAM_URL_PATTERNS,
    "www.instagram.com": INSTAGRAM_URL_PATTERNS,
    "youtube.com": (_YT_SHORTS_PATH, _YT_WATCH_PATH),
    "www.youtube.com": (_YT_SHORTS_PATH, _YT_WATCH_PATH),
    "m.youtube.com": (_YT_SHORTS_PATH, _YT_WATCH_PATH),
    "youtu.be": (_YT_CODE_PATH,),
}


def _parse_strict_url(url: str) -> ParseResult | None:
    """Parsea una URL exigiendo HTTPS y rechazando contenido peligroso.

    Returns:
        El resultado de urlparse, o None si la URL no es apta para yt-dlp.
    """
    if not isinstance(url, str) or not url:
        return None
    # Rechazar caracteres de control, espacios, meta-caracteres de shell y
    # backslashes antes de cualquier otro procesamiento.
    if _UNSAFE_URL_CHARS.search(url):
        return None
    try:
        parsed = urlparse(url)
        # Sin credenciales incrustadas ("user:pass@host", también "@host") y
        # sin fragmentos: el fragmento nunca debe llegar a yt-dlp.
        if "@" in parsed.netloc or parsed.fragment:
            return None
        # Esquema SOLO https (urlparse ya normaliza a minúsculas).
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        # Un puerto explícito no es necesario y permitiría apuntar a otros
        # servicios; la allowlist es de hosts, no de host:puerto.
        if parsed.port is not None:
            return None
    except ValueError:
        # Puertos mal formados, IPv6 inválido, etc.
        return None
    return parsed


def _valid_watch_query(query: str) -> bool:
    """Valida la query de /watch: exige un único 'v' con formato de ID.

    Se permiten parámetros extra benignos (t=30, utm_source=..., si=...),
    siempre que sus claves y valores usen solo caracteres seguros.
    """
    if not query:
        return False

    video_ids: list[str] = []
    for param in query.split("&"):
        if "=" not in param:
            return False  # parámetro sin valor: rechazar
        key, value = param.split("=", 1)
        if _SAFE_QUERY_KEY_RE.fullmatch(key) is None or _SAFE_QUERY_RE.fullmatch(value) is None:
            return False
        if key == "v":
            video_ids.append(value)

    # "v" debe aparecer una sola vez y ser un ID limpio (sin puntos ni rutas).
    return len(video_ids) == 1 and re.fullmatch(r"[\w-]+", video_ids[0]) is not None


def validate_tiktok_url(url: str) -> bool:
    """
    Valida si la URL es un vídeo de TikTok con la política estricta.

    Args:
        url: URL a validar

    Returns:
        True si es una URL de TikTok válida, False en caso contrario
    """
    return detect_platform(url) == "tiktok"


def detect_platform(url: str) -> str | None:
    """
    Detecta la plataforma de una URL de vídeo.

    Args:
        url: URL a clasificar

    Returns:
        "tiktok", "instagram", "youtube" o None si no es soportada
    """
    parsed = _parse_strict_url(url)
    if parsed is None:
        return None

    host = parsed.hostname
    platform = _HOST_PLATFORM.get(host)
    patterns = _HOST_PATTERNS.get(host, ())
    if platform is None or not patterns:
        return None

    # El PATH se valida con fullmatch: los sufijos maliciosos van aquí y se
    # rechazan aunque la query sea legítima (p. ej. youtu.be/abc.evil.com/path).
    if not any(re.fullmatch(pattern, parsed.path) for pattern in patterns):
        return None

    # La query se valida por separado: se admiten parámetros de tracking, pero
    # nunca caracteres de control, espacios ni meta-caracteres de shell.
    if parsed.query and _SAFE_QUERY_RE.fullmatch(parsed.query) is None:
        return None

    # En /watch?v=ID se exige además un "v" único y bien formado.
    if parsed.path == "/watch" and not _valid_watch_query(parsed.query):
        return None

    return platform


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
