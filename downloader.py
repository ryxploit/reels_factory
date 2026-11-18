"""
Reels Factory - Video Downloader Module
=========================================
Downloads TikTok videos without watermark using yt-dlp.
Optimized for reliability and quality.
"""

import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from config import config
from utils import (
    ProgressCallback,
    detect_platform,
    generate_unique_filename,
    get_video_info,
    setup_logger,
    validate_video_url,
)

logger = setup_logger("downloader", config.paths.LOGS_PATH / "downloader.log")

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
except ImportError:  # pragma: no cover - depende de entorno
    yt_dlp = None  # type: ignore[assignment]

    class DownloadCancelled(Exception):  # type: ignore[no-redef]
        """Fallback usado cuando yt-dlp no está instalado."""


@dataclass
class DownloadResult:
    """Result of a download operation."""

    success: bool
    file_path: Path | None
    video_info: dict | None
    error_message: str | None = None
    original_title: str | None = None
    hashtags: list[str] | None = None


class TikTokDownloader:
    """
    TikTok video downloader using yt-dlp.
    Downloads videos without watermark in the best available quality.
    """

    def __init__(self, output_dir: Path | None = None):
        """
        Initialize the downloader.

        Args:
            output_dir: Directory to save downloaded videos
        """
        self.output_dir = output_dir or config.paths.DOWNLOADS_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_yt_dlp_options(self, output_path: Path) -> dict:
        """
        Get yt-dlp options for downloading.

        Args:
            output_path: Path where to save the video

        Returns:
            Dictionary of yt-dlp options
        """
        opts = {
            "outtmpl": str(output_path),
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "retries": 3,
            "fragment_retries": 3,
            "sleep_interval": 1,
            "quiet": True,
            "no_warnings": True,
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }

        # Configuración opcional de cookies para evitar bloqueos por bot / 429
        dl_cfg = getattr(config, "download", None)
        if dl_cfg:
            if dl_cfg.COOKIES_FROM_BROWSER:
                opts["cookiesfrombrowser"] = (dl_cfg.COOKIES_FROM_BROWSER,)
            elif dl_cfg.COOKIES_FILE:
                opts["cookiefile"] = str(dl_cfg.COOKIES_FILE)

        return opts

    def _cleanup_partial_files(self, output_path: Path) -> None:
        """Elimina fragmentos temporales huérfanos generados por yt-dlp."""
        stem = output_path.stem
        for p in self.output_dir.glob(f"{stem}*.part*"):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        for p in self.output_dir.glob(f"{stem}*.ytdl*"):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def _get_video_metadata(self, url: str) -> dict | None:
        """
        Fetch video metadata without downloading.

        Args:
            url: TikTok video URL

        Returns:
            Video metadata dictionary or None
        """
        try:
            import yt_dlp

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.error(f"Error fetching metadata: {e}")
            return None

    def _extract_hashtags(self, text: str) -> list[str]:
        """
        Extract hashtags from a text string.

        Args:
            text: Raw text from title/description

        Returns:
            List of unique hashtags preserving order
        """
        if not text:
            return []
        tags = re.findall(r"#\w+", text, flags=re.UNICODE)
        seen = set()
        unique = []
        for tag in tags:
            if tag.lower() in seen:
                continue
            seen.add(tag.lower())
            unique.append(tag)
        return unique

    def download(
        self,
        url: str,
        progress_callback: Callable[[int, int, str], None] | None = None,
        custom_filename: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> DownloadResult:
        """
        Download a TikTok video without watermark.

        Args:
            url: TikTok video URL
            progress_callback: Optional callback for progress updates
            custom_filename: Optional custom filename for the output

        Returns:
            DownloadResult with success status and file info
        """
        # Validate URL
        if not validate_video_url(url):
            return DownloadResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message="Invalid video URL format",
            )

        progress = ProgressCallback(progress_callback)
        progress.update(5, 100, "Fetching video info...")

        # Get metadata first
        metadata = self._get_video_metadata(url)
        original_title = None
        hashtags: list[str] | None = None

        if metadata:
            original_title = (metadata.get("title") or metadata.get("description") or "")[:50]
            logger.info(f"Video found: {original_title}")
            raw_text = metadata.get("description") or metadata.get("title") or ""
            hashtags = self._extract_hashtags(raw_text)

        progress.update(10, 100, "Preparing download...")

        # Generate output filename
        platform = detect_platform(url) or "video"
        if custom_filename:
            from utils import sanitize_filename

            safe = sanitize_filename(custom_filename)
            output_filename = f"{safe}.mp4"
        else:
            base_name = original_title or f"{platform}_video"
            output_filename = generate_unique_filename(base_name, "mp4")

        output_path = self.output_dir / output_filename

        try:
            resolved = output_path.resolve()
            base = self.output_dir.resolve()
            if os.path.commonpath([str(resolved), str(base)]) != str(base):
                return DownloadResult(
                    success=False,
                    file_path=None,
                    video_info=None,
                    error_message="Invalid output filename",
                )
        except Exception:
            return DownloadResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message="Invalid output filename",
            )

        try:
            import yt_dlp
            from yt_dlp.utils import DownloadCancelled

            logger.info(f"Starting download: {url}")

            def hook(d):
                try:
                    if cancel_event and cancel_event.is_set():
                        raise DownloadCancelled("Cancelled")
                    status = d.get("status")
                    if status == "downloading":
                        total = d.get("total_bytes") or d.get("total_bytes_estimate")
                        downloaded = d.get("downloaded_bytes")
                        if total and downloaded is not None:
                            pct = (downloaded / total) * 100
                            mapped_progress = 10 + int(pct * 0.8)
                            progress.update(mapped_progress, 100, f"Downloading: {pct:.1f}%")
                    elif status == "finished":
                        progress.update(90, 100, "Download complete")
                except DownloadCancelled:
                    # La cancelación debe propagarse para abortar la descarga.
                    raise
                except Exception:
                    return

            ydl_opts = self._get_yt_dlp_options(output_path)
            ydl_opts["progress_hooks"] = [hook]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Verify file exists
            if not output_path.exists():
                # Check for alternative extensions
                for ext in [".mp4", ".webm", ".mkv"]:
                    alt_path = output_path.with_suffix(ext)
                    if alt_path.exists():
                        output_path = alt_path
                        break
                else:
                    return DownloadResult(
                        success=False,
                        file_path=None,
                        video_info=None,
                        error_message="Downloaded file not found",
                    )

            progress.update(95, 100, "Verifying download...")

            # Get video info
            video_info = get_video_info(output_path)

            progress.update(100, 100, "Download complete!")

            logger.info(f"Download successful: {output_path}")

            return DownloadResult(
                success=True,
                file_path=output_path,
                video_info=video_info,
                original_title=original_title,
                hashtags=hashtags,
            )

        except DownloadCancelled:
            self._cleanup_partial_files(output_path)
            return DownloadResult(
                success=False,
                file_path=None,
                video_info=None,
                error_message="Cancelado",
            )
        except Exception as e:
            self._cleanup_partial_files(output_path)
            logger.error(f"Download error: {e}")
            return DownloadResult(
                success=False, file_path=None, video_info=None, error_message=str(e)
            )


# Convenience function
def download_tiktok(
    url: str,
    output_dir: Path | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> DownloadResult:
    """
    Convenience function to download a TikTok video.

    Args:
        url: TikTok video URL
        output_dir: Optional output directory
        progress_callback: Optional progress callback

    Returns:
        DownloadResult
    """
    downloader = TikTokDownloader(output_dir)
    return downloader.download(url, progress_callback)


if __name__ == "__main__":
    # Test the downloader
    import sys

    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        print("Usage: python downloader.py <tiktok_url>")
        sys.exit(1)

    def print_progress(current, total, status):
        print(f"\r[{current:3d}%] {status}", end="", flush=True)

    print(f"Downloading: {test_url}")
    result = download_tiktok(test_url, progress_callback=print_progress)

    print()  # New line after progress

    if result.success:
        print(f"✓ Downloaded: {result.file_path}")
        if result.video_info:
            print(f"  Duration: {result.video_info['duration_formatted']}")
            print(f"  Size: {result.video_info['size_formatted']}")
    else:
        print(f"✗ Error: {result.error_message}")
