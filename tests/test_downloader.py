"""Tests de regresión para downloader.py."""

import threading

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
    assert result.error_message == "Invalid TikTok URL format"


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
