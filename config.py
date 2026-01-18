"""
Reels Factory - Configuration Module
=====================================
Central configuration for all project settings.
Optimized for macOS Apple Silicon (M1/M2/M3).
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


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
    
    # Frame rate
    FPS: int = 30
    
    # Undetectability variations (subtle random changes to avoid fingerprinting)
    ENABLE_VARIATIONS: bool = True
    BRIGHTNESS_VARIATION: float = 0.01  # ±1% brightness
    CONTRAST_VARIATION: float = 0.01    # ±1% contrast
    SATURATION_VARIATION: float = 0.01  # ±1% saturation
    NOISE_STRENGTH_MIN: int = 1
    NOISE_STRENGTH_MAX: int = 3


@dataclass
class SubtitleConfig:
    """Subtitle generation and styling configuration."""
    
    MODEL_SIZE: str = "base"  # tiny, base, small, medium, large-v2
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
    
    # Word highlighting
    HIGHLIGHT_COLOR: str = "&H00FFFF"  # Yellow (BGR format)


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
class PathConfig:
    """Project paths configuration."""
    
    def __init__(self, base_path: Optional[Path] = None):
        repo_root = Path(__file__).resolve().parent
        env_base = os.environ.get("REELSFACTORYPRO_BASE_DIR")
        self.BASE_PATH = Path(env_base).expanduser().resolve() if env_base else (base_path or repo_root)

        self.INPUT_PATH = self.BASE_PATH / "input"
        self.TEMP_PATH = self.BASE_PATH / "temp"
        self.OUTPUT_PATH = self.BASE_PATH / "output"
        self.ASSETS_PATH = self.BASE_PATH / "assets"
        self.LOGS_PATH = self.BASE_PATH / "logs"

        self.DOWNLOADS_PATH = self.TEMP_PATH / "downloads"
        self.PROCESSED_PATH = self.OUTPUT_PATH
        self.SUBTITLES_PATH = self.TEMP_PATH / "subtitles"
        
        # Create directories
        self._create_directories()
    
    def _create_directories(self):
        """Create all necessary directories."""
        for path in [
            self.TEMP_PATH,
            self.DOWNLOADS_PATH,
            self.SUBTITLES_PATH,
            self.INPUT_PATH,
            self.OUTPUT_PATH,
            self.ASSETS_PATH,
            self.LOGS_PATH
        ]:
            path.mkdir(parents=True, exist_ok=True)


class Config:
    """Main configuration class."""
    
    def __init__(self, base_path: Optional[Path] = None):
        self.video = VideoConfig()
        self.subtitle = SubtitleConfig()
        self.branding = BrandingConfig()
        self.paths = PathConfig(base_path)
        
        # App settings
        self.APP_NAME = "ReelsFactoryPro"
        self.APP_VERSION = "1.1.0"
        self.DEBUG = os.environ.get("REELS_FACTORY_DEBUG", "false").lower() == "true"


# Global config instance
config = Config()
