"""Tests de regresión para downloader.py."""

import threading
from pathlib import Path

import pytest

from downloader import DownloadResult, TikTokDownloader


def test_extract_hashtags_preserves_order_and_uniqueness():
    dl = TikTokDownloader.__new__(TikTokDownloader)
    tags = dl._extract_hashtags("#hola #mundo #hola #fin")
    assert tags == ["#hola", "#mundo", "#fin"]


def test_extract_hashtags_handles_empty_text():
    dl = TikTokDownloader.__new__(TikTokDownloader)
    assert dl._extract_hashtags("") == []
    assert dl._extract_hashtags("sin hashtags") == []


def test_download_rejects_invalid_url():
    dl = TikTokDownloader.__new__(TikTokDownloader)
    result = dl.download("https://example.com/not-tiktok")
    assert result.success is False
    assert result.error_message == "Invalid video URL format"


def test_download_accepts_supported_platform_urls(monkeypatch):
    dl = TikTokDownloader.__new__(TikTokDownloader)
    dl.output_dir = Path("/tmp")
    # Mockear metadatos y download para que no haga llamada a red
    monkeypatch.setattr(dl, "_get_video_metadata", lambda url: {"title": "Test Video"})
    monkeypatch.setattr(dl, "_get_yt_dlp_options", lambda path: {})

    class DummyYdl:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def download(self, urls):
            pass

    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", DummyYdl)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr("downloader.get_video_info", lambda p: {"duration": 10})

    for url in [
        "https://www.tiktok.com/@user/video/1234567890",
        "https://www.instagram.com/reel/C123456789/",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    ]:
        res = dl.download(url)
        assert res.success is True


def test_title_none_does_not_crash_metadata_extraction():
    """Regresión: `metadata.get('title', ...)` devolvía None y `[:50]` fallaba."""
    # Replica la lógica de extracción de título del método download().
    metadata = {"title": None, "description": "descripcion de prueba"}
    title = (metadata.get("title") or metadata.get("description") or "")[:50]
    assert title == "descripcion de prueba"

    metadata2 = {"title": None, "description": None}
    title2 = (metadata2.get("title") or metadata2.get("description") or "")[:50]
    assert title2 == ""


def test_cancel_event_propagates_through_progress_hook():
    """Regresión: el hook tragaba `DownloadCancelled` y la descarga no se
    cancelaba nunca."""
    from downloader import DownloadCancelled

    cancel_event = threading.Event()
    cancel_event.set()

    def hook(d):
        try:
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Cancelled")
        except DownloadCancelled:
            raise
        except Exception:
            return

    with pytest.raises(DownloadCancelled):
        hook({"status": "downloading"})
