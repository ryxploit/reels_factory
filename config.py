"""
Reels Factory - Configuration Module
=====================================
Central configuration for all project settings.
Optimized for macOS Apple Silicon (M1/M2/M3).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoConfig:
    """Video processing configuration for Facebook Reels."""

    # Output dimensions (9:16 aspect ratio)
    WIDTH: int = 1080
    HEIGHT: int = 1920

    # Duration limits
    MAX_DURATION_SECONDS: int = 55

    # Video codec settings optimized for Facebook
    VIDEO_CODEC: str = "libx264"
    VIDEO_PRESET: str = "medium"
    VIDEO_BITRATE: str = "4500k"
    VIDEO_MAXRATE: str = "5500k"
    VIDEO_BUFSIZE: str = "11000k"
    VIDEO_PROFILE: str = "high"
    VIDEO_LEVEL: str = "4.0"
    PIXEL_FORMAT: str = "yuv420p"

    # Audio codec settings
    AUDIO_CODEC: str = "aac"
    AUDIO_BITRATE: str = "192k"
    AUDIO_SAMPLE_RATE: int = 44100
    AUDIO_CHANNELS: int = 2

    # Audio normalization (loudnorm) - Facebook/TikTok normalizan a -14 LUFS.
    ENABLE_LOUDNORM: bool = True
    LOUDNORM_I: str = "-14"  # Integrated loudness (LUFS)
    LOUDNORM_TP: str = "-1.5"  # True peak (dBTP)
    LOUDNORM_LRA: str = "11"  # Loudness range

    # Frame rate
    FPS: int = 30

    # Undetectability variations (subtle random changes to avoid fingerprinting)
    ENABLE_VARIATIONS: bool = True
    BRIGHTNESS_VARIATION: float = 0.01  # ±1% brightness
    CONTRAST_VARIATION: float = 0.01  # ±1% contrast
    SATURATION_VARIATION: float = 0.01  # ±1% saturation
    NOISE_STRENGTH_MIN: int = 1
    NOISE_STRENGTH_MAX: int = 3

    # Verificación del archivo final contra las especificaciones de la plataforma.
    VALIDATE_OUTPUT: bool = True

    # Nombre de archivo de salida neutro, sin el título del vídeo original.
    # El nombre del archivo acaba visible en la plataforma al subirlo, así
    # que los hashtags del creator original no deben travelling con él.
    NEUTRAL_FILENAMES: bool = True


@dataclass
class SubtitleConfig:
    """Subtitle generation and styling configuration."""

    MODEL_SIZE: str = "base"  # tiny, base, small, medium, large-v3, turbo, ...
    USE_MPS: bool = True

    # Subtitle styling (ASS format)
    FONT_NAME: str = "Arial"
    FONT_SIZE: int = 24
    PRIMARY_COLOR: str = "&HFFFFFF"  # White
    OUTLINE_COLOR: str = "&H000000"  # Black
    BACK_COLOR: str = "&H80000000"  # Semi-transparent black
    OUTLINE_WIDTH: int = 2
    SHADOW_DEPTH: int = 1
    MARGIN_V: int = 50  # Vertical margin from bottom

    # Word highlighting (estilo TikTok/Shorts)
    HIGHLIGHT_COLOR: str = "&H00FFFF"  # Yellow (BGR format)
    ENABLE_WORD_HIGHLIGHT: bool = True
    WORD_HIGHLIGHT_SCALE: int = 120  # Escala de la palabra activa (ASS \fsc)

    # Modelos disponibles en la interfaz (los que soporta openai-whisper).
    AVAILABLE_MODELS: tuple[str, ...] = (
        "tiny",
        "base",
        "small",
        "medium",
        "large-v3",
        "large-v3-turbo",
        "turbo",
    )


@dataclass
class BrandingConfig:
    """Branding overlay configuration."""

    # Logo settings
    LOGO_WIDTH: int = 150
    LOGO_HEIGHT: int = 150
    LOGO_MARGIN_RIGHT: int = 30
    LOGO_MARGIN_BOTTOM: int = 100
    LOGO_OPACITY: float = 0.8


@dataclass
class FingerprintConfig:
    """Evasión de huella digital perceptual.

    Las plataformas comparan vídeos y audios re-codificados contra catálogos
    de obras registradas mediante hashes perceptuales. Estas técnicas alteran
    la huella del resultado para que un reupload no coincida exactamente con
    el original.

    Pensado para republicar contenido propio en varias plataformas.
    """

    # Vídeo
    ENABLE_FRAME_SHIFT: bool = True
    ENABLE_SPEED_CHANGE: bool = True
    ENABLE_GAMMA_SHIFT: bool = True
    ENABLE_MIRROR: bool = False

    # Audio
    ENABLE_PITCH_SHIFT: bool = True
    ENABLE_AUDIO_EQ: bool = True
    ENABLE_AUDIO_DITHER: bool = True

    # Parámetros
    SPEED_FACTOR: float = 1.004
    PITCH_FACTOR: float = 1.008
    GAMMA: float = 1.03
    FRAME_SHIFT_PX: int = 2

    # Detección de marca de agua incrustada
    DETECT_WATERMARK: bool = True
    # Calibrado con vídeos reales: por debajo de 0.4 no hay nada fijo
    # sospechoso; por encima de 0.8 la detección es concluyente.
    WATERMARK_THRESHOLD: float = 0.55


@dataclass
class PathConfig:
    """Project paths configuration."""

    def __init__(self, base_path: Path | None = None):
        repo_root = Path(__file__).resolve().parent
        env_base = os.environ.get("REELSFACTORYPRO_BASE_DIR")
        self.BASE_PATH = (
            Path(env_base).expanduser().resolve() if env_base else (base_path or repo_root)
        )

        self.INPUT_PATH = self.BASE_PATH / "input"
        self.TEMP_PATH = self.BASE_PATH / "temp"
        self.OUTPUT_PATH = self.BASE_PATH / "output"
        self.LOGS_PATH = self.BASE_PATH / "logs"

        # Los assets (logo, icono) pertenecen a la instalación del programa, no
        # a la carpeta de datos: deben resolverse junto al ejecutable.
        self.ASSETS_PATH = self._resolve_assets_path(repo_root)

        self.DOWNLOADS_PATH = self.TEMP_PATH / "downloads"
        self.PROCESSED_PATH = self.OUTPUT_PATH
        self.SUBTITLES_PATH = self.TEMP_PATH / "subtitles"
        self.THUMBNAILS_PATH = self.OUTPUT_PATH / "thumbnails"

        # Create directories
        self._create_directories()

    @staticmethod
    def _resolve_assets_path(repo_root: Path) -> Path:
        """Localiza la carpeta `assets/` del programa.

        Prioridad: bundle de PyInstaller (`_MEIPASS`) > carpeta del repo.
        """
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = Path(meipass) / "assets"
            if bundled.is_dir():
                return bundled
        return repo_root / "assets"

    def _create_directories(self):
        """Create all necessary directories."""
        for path in [
            self.TEMP_PATH,
            self.DOWNLOADS_PATH,
            self.SUBTITLES_PATH,
            self.INPUT_PATH,
            self.OUTPUT_PATH,
            self.LOGS_PATH,
            self.THUMBNAILS_PATH,
        ]:
            path.mkdir(parents=True, exist_ok=True)


class Config:
    """Main configuration class."""

    def __init__(self, base_path: Path | None = None):
        self.video = VideoConfig()
        self.subtitle = SubtitleConfig()
        self.branding = BrandingConfig()
        self.fingerprint = FingerprintConfig()
        self.paths = PathConfig(base_path)

        # App settings
        self.APP_NAME = "ReelsFactoryPro"
        self.APP_VERSION = "1.4.1"
        self.DEBUG = os.environ.get("REELS_FACTORY_DEBUG", "false").lower() == "true"


# Global config instance
config = Config()
