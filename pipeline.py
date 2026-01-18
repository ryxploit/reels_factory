"""Orquestación del pipeline: download → (whisper) → ffmpeg.

Este módulo no depende de UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable, Optional

from config import config
from downloader import TikTokDownloader
from processor import VideoProcessor
from subtitles import SubtitleGenerator
from utils import validate_tiktok_url


ProgressFn = Callable[[int, str], None]
LogFn = Callable[[str], None]


@dataclass
class PipelineSettings:
    subtitles: bool = True
    whisper_model: str = "base"
    language: Optional[str] = None
    branding: bool = False
    logo_path: Optional[Path] = None
    cleanup_intermediates: bool = False


class CancelledError(Exception):
    pass


@dataclass
class JobResult:
    url: str
    success: bool
    downloaded_path: Optional[Path]
    output_path: Optional[Path]
    error_message: Optional[str] = None
    title: Optional[str] = None
    hashtags: Optional[list[str]] = None


class ReelsPipeline:
    def __init__(
        self,
        downloads_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        subtitles_dir: Optional[Path] = None,
    ):
        self.downloader = TikTokDownloader(downloads_dir or config.paths.DOWNLOADS_PATH)
        self.processor = VideoProcessor(output_dir or config.paths.PROCESSED_PATH)
        self.subtitler = SubtitleGenerator(subtitles_dir or config.paths.SUBTITLES_PATH)

    def _calculate_progress(self, stage_start: int, stage_end: int, sub_progress: float) -> int:
        """
        Calculate overall progress based on current stage and sub-progress.
        
        Args:
            stage_start: Start percentage of the current stage
            stage_end: End percentage of the current stage
            sub_progress: Progress within the stage (0-100)
        
        Returns:
            Overall progress percentage
        """
        stage_range = stage_end - stage_start
        return stage_start + int((sub_progress / 100) * stage_range)

    def run_one(
        self,
        url: str,
        settings: PipelineSettings,
        progress: Optional[ProgressFn] = None,
        log: Optional[LogFn] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> JobResult:
        def p(value: int, status: str):
            if progress:
                progress(value, status)

        def l(message: str):
            if log:
                log(message)

        def raise_if_cancelled():
            if cancel_event and cancel_event.is_set():
                raise CancelledError("Cancelado")

        if not validate_tiktok_url(url):
            return JobResult(url=url, success=False, downloaded_path=None, output_path=None, error_message="URL de TikTok inválida")

        raise_if_cancelled()

        p(1, "Iniciando")
        l(f"URL: {url}")

        raise_if_cancelled()

        dl = self.downloader.download(
            url,
            progress_callback=lambda c, _t, s: p(self._calculate_progress(1, 35, c), s),
            cancel_event=cancel_event,
        )
        if not dl.success or not dl.file_path:
            return JobResult(
                url=url,
                success=False,
                downloaded_path=None,
                output_path=None,
                    error_message=dl.error_message or "Falló la descarga",
                    title=dl.original_title,
                    hashtags=dl.hashtags,
            )

        downloaded_path = dl.file_path
        l(f"Descargado: {downloaded_path.name}")

        raise_if_cancelled()

        subtitle_path = None
        if settings.subtitles:
            sub = self.subtitler.generate(
                downloaded_path,
                language=settings.language,
                progress_callback=lambda c, _t, s: p(self._calculate_progress(35, 70, c), s),
                cancel_event=cancel_event,
            )
            if not sub.success or not sub.subtitle_path:
                return JobResult(
                    url=url,
                    success=False,
                    downloaded_path=downloaded_path,
                    output_path=None,
                        error_message=sub.error_message or "Falló la transcripción",
                        title=dl.original_title,
                        hashtags=dl.hashtags,
                )
            subtitle_path = sub.subtitle_path
            l(f"Subtítulos: {subtitle_path.name}")

        raise_if_cancelled()

        logo_path = settings.logo_path if settings.branding else None
        out = self.processor.process(
            input_path=downloaded_path,
            logo_path=logo_path,
            subtitle_path=subtitle_path,
            progress_callback=lambda c, _t, s: p(self._calculate_progress(70, 100, c), s),
            cancel_event=cancel_event,
        )
        if not out.success or not out.file_path:
            return JobResult(
                url=url,
                success=False,
                downloaded_path=downloaded_path,
                output_path=None,
                    error_message=out.error_message or "Falló el procesamiento",
                    title=dl.original_title,
                    hashtags=dl.hashtags,
            )

        p(100, "Listo")
        l(f"Salida: {out.file_path}")

        if settings.cleanup_intermediates:
            try:
                downloaded_path.unlink(missing_ok=True)
            except Exception:
                pass
            if subtitle_path:
                try:
                    subtitle_path.unlink(missing_ok=True)
                except Exception:
                    pass

        return JobResult(
            url=url,
            success=True,
            downloaded_path=downloaded_path,
            output_path=out.file_path,
                title=dl.original_title,
                hashtags=dl.hashtags,
        )
