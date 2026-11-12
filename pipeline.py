"""Orquestación del pipeline: download → (whisper) → ffmpeg.

Este módulo no depende de UI.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    language: str | None = None
    branding: bool = False
    logo_path: Path | None = None
    cleanup_intermediates: bool = False
    word_highlight: bool = True
    loudnorm: bool = True
    evasion: bool = True


class CancelledError(Exception):
    pass


@dataclass
class JobResult:
    url: str
    success: bool
    downloaded_path: Path | None
    output_path: Path | None
    error_message: str | None = None
    title: str | None = None
    hashtags: list[str] | None = None
    warnings: list[str] | None = None
    thumbnail_path: Path | None = None
    subtitle_path: Path | None = None
    segments: list | None = None
    watermark_detected: bool = False
    watermark_summary: str | None = None
    evasion_summary: str | None = None


class ReelsPipeline:
    def __init__(
        self,
        downloads_dir: Path | None = None,
        output_dir: Path | None = None,
        subtitles_dir: Path | None = None,
    ):
        self.downloader = TikTokDownloader(downloads_dir or config.paths.DOWNLOADS_PATH)
        self.processor = VideoProcessor(output_dir or config.paths.PROCESSED_PATH)
        self.subtitler = SubtitleGenerator(
            subtitles_dir or config.paths.SUBTITLES_PATH,
            model_size=config.subtitle.MODEL_SIZE,
        )

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
        progress: ProgressFn | None = None,
        log: LogFn | None = None,
        cancel_event: threading.Event | None = None,
    ) -> JobResult:
        def p(value: int, status: str):
            if progress:
                progress(value, status)

        def emit_log(message: str):
            if log:
                log(message)

        def raise_if_cancelled():
            if cancel_event and cancel_event.is_set():
                raise CancelledError("Cancelado")

        if not validate_tiktok_url(url):
            return JobResult(
                url=url,
                success=False,
                downloaded_path=None,
                output_path=None,
                error_message="URL de TikTok inválida",
            )

        raise_if_cancelled()

        p(1, "Iniciando")
        emit_log(f"URL: {url}")

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
        emit_log(f"Descargado: {downloaded_path.name}")

        raise_if_cancelled()

        subtitle_path = None
        if settings.subtitles:
            # Respeta el modelo elegido por el usuario en la GUI.
            if settings.whisper_model:
                self.subtitler.model_size = settings.whisper_model
            # El resaltado por palabra se controla por trabajo.
            self.subtitler.subtitle_config.ENABLE_WORD_HIGHLIGHT = settings.word_highlight
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
            emit_log(f"Subtítulos: {subtitle_path.name}")

        raise_if_cancelled()

        logo_path = settings.logo_path if settings.branding else None
        # La normalización de audio se controla por trabajo.
        self.processor.video_config.ENABLE_LOUDNORM = settings.loudnorm
        # La evasión de huella digital se controla por trabajo.
        self.processor.evasion_enabled = settings.evasion
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
        emit_log(f"Salida: {out.file_path}")

        for warning in out.warnings or []:
            emit_log(f"⚠️  {warning}")

        if out.evasion_summary:
            emit_log(f"Evasión aplicada: {out.evasion_summary}")

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
            warnings=out.warnings,
            thumbnail_path=out.thumbnail_path,
            subtitle_path=subtitle_path,
            segments=self.subtitler.last_segments,
            watermark_detected=out.watermark_detected,
            watermark_summary=out.watermark_summary,
            evasion_summary=out.evasion_summary,
        )
