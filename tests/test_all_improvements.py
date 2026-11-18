"""Tests para las nuevas mejoras implementadas:
- Soporte multiplataforma (TikTok, Instagram Reels, YouTube Shorts) en downloader y pipeline.
- Evasión de huella de vídeo (setpts, gamma, microdesplazamiento) y sincronía A/V.
- Aceleración por hardware con fallback VideoToolbox / libx264.
- Pre-fetching en el pipeline.
- Exportación de reporte de lote.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from downloader import DownloadResult, TikTokDownloader
from evasion import EvasionProfile, build_video_filter_chain
from jobstore import JobStore, StoredJob
from pipeline import PipelineSettings, ReelsPipeline
from processor import VideoProcessor
from utils import detect_platform, validate_video_url


def test_validate_video_url_platforms():
    tiktok_url = "https://www.tiktok.com/@creator/video/1234567890123456789"
    insta_url = "https://www.instagram.com/reel/DC123456789/"
    yt_shorts_url = "https://www.youtube.com/shorts/abcdef12345"
    invalid_url = "https://example.com/video/123"

    assert validate_video_url(tiktok_url) is True
    assert validate_video_url(insta_url) is True
    assert validate_video_url(yt_shorts_url) is True
    assert validate_video_url(invalid_url) is False

    assert detect_platform(tiktok_url) == "tiktok"
    assert detect_platform(insta_url) == "instagram"
    assert detect_platform(yt_shorts_url) == "youtube"


def test_pipeline_accepts_instagram_and_youtube(tmp_path, monkeypatch):
    pipeline = ReelsPipeline(
        downloads_dir=tmp_path / "dl",
        output_dir=tmp_path / "out",
        subtitles_dir=tmp_path / "subs",
    )

    fake_file = tmp_path / "dl" / "video.mp4"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"dummy")

    # Mockear descarga y procesador para simular éxito
    dummy_dl = DownloadResult(
        success=True,
        file_path=fake_file,
        video_info={"duration": 15, "width": 1080, "height": 1920},
        original_title="Reel de Instagram",
    )
    monkeypatch.setattr(pipeline.downloader, "download", lambda *a, **k: dummy_dl)

    fake_out = tmp_path / "out" / "reel_test.mp4"
    fake_out.parent.mkdir(parents=True, exist_ok=True)
    fake_out.write_bytes(b"dummy out")

    mock_process = MagicMock()
    mock_process.success = True
    mock_process.file_path = fake_out
    mock_process.warnings = []
    mock_process.watermark_detected = False
    mock_process.watermark_summary = None
    mock_process.thumbnail_path = None
    mock_process.evasion_summary = "setpts, gamma"

    monkeypatch.setattr(pipeline.processor, "process", lambda *a, **k: mock_process)

    settings = PipelineSettings(subtitles=False)
    res_insta = pipeline.run_one("https://www.instagram.com/reel/DC123456789/", settings)
    assert res_insta.success is True
    assert res_insta.output_path == fake_out

    res_yt = pipeline.run_one("https://www.youtube.com/shorts/abcdef12345", settings)
    assert res_yt.success is True


def test_pipeline_uses_prefetched_download(tmp_path, monkeypatch):
    pipeline = ReelsPipeline(
        downloads_dir=tmp_path / "dl",
        output_dir=tmp_path / "out",
        subtitles_dir=tmp_path / "subs",
    )

    prefetched_file = tmp_path / "dl" / "prefetched.mp4"
    prefetched_file.parent.mkdir(parents=True, exist_ok=True)
    prefetched_file.write_bytes(b"prefetched content")

    prefetched = DownloadResult(
        success=True,
        file_path=prefetched_file,
        video_info={"duration": 10, "width": 1080, "height": 1920},
        original_title="Pre-descargado",
    )

    # Si se usa el prefetched, pipeline.downloader.download NO debe ser llamado
    def fail_if_called(*a, **k):
        raise AssertionError("downloader.download no debía llamarse al existir prefetched_download")

    monkeypatch.setattr(pipeline.downloader, "download", fail_if_called)

    fake_out = tmp_path / "out" / "reel_prefetched.mp4"
    fake_out.parent.mkdir(parents=True, exist_ok=True)
    fake_out.write_bytes(b"out")

    mock_process = MagicMock()
    mock_process.success = True
    mock_process.file_path = fake_out
    mock_process.warnings = []
    mock_process.watermark_detected = False
    mock_process.watermark_summary = None
    mock_process.thumbnail_path = None
    mock_process.evasion_summary = None

    monkeypatch.setattr(pipeline.processor, "process", lambda *a, **k: mock_process)

    progress_stages = []
    settings = PipelineSettings(subtitles=False)
    res = pipeline.run_one(
        "https://www.tiktok.com/@user/video/1234567890",
        settings,
        progress=lambda val, msg: progress_stages.append(msg),
        prefetched_download=prefetched,
    )
    assert res.success is True
    assert any("anticipada" in msg for msg in progress_stages)


def test_evasion_speed_and_pts_synchronization():
    profile = EvasionProfile(enable_speed_change=True, speed_factor=1.004)
    v_filters = profile.video_filters()
    a_filters = profile.audio_filters(44100)

    # El filtro de video setpts debe multiplicar por 1 / speed_factor para adelantar timestamps
    pts_filter = [f for f in v_filters if "setpts=" in f][0]
    expected_pts_factor = 1.0 / 1.004
    assert f"{expected_pts_factor:.6f}" in pts_filter

    # El filtro de audio atempo debe acelerar el audio con speed_factor
    atempo_filter = [f for f in a_filters if "atempo=" in f][0]
    assert "atempo=" in atempo_filter


def test_downloader_cleanup_partial_files(tmp_path):
    dl = TikTokDownloader(output_dir=tmp_path)
    part_file = tmp_path / "test_video.mp4.part"
    ytdl_file = tmp_path / "test_video.mp4.ytdl"
    part_file.write_bytes(b"partial")
    ytdl_file.write_bytes(b"ytdl data")

    assert part_file.exists()
    assert ytdl_file.exists()

    dl._cleanup_partial_files(tmp_path / "test_video.mp4")

    assert not part_file.exists()
    assert not ytdl_file.exists()


def test_jobstore_export_report_preserves_fields(tmp_path):
    store = JobStore(path=tmp_path / "store.json")
    store.set_jobs(
        [
            StoredJob(
                url="https://instagram.com/reel/123",
                status="Listo",
                title="Mi Reel",
                hashtags="#reels #viral",
                output_path="/tmp/reel.mp4",
                result="/tmp/reel.mp4",
            )
        ]
    )

    out_csv = tmp_path / "report.csv"
    store.export_report(out_csv, fmt="csv")
    csv_text = out_csv.read_text(encoding="utf-8")
    assert "https://instagram.com/reel/123" in csv_text
    assert "Mi Reel" in csv_text
    assert "#reels #viral" in csv_text

    out_json = tmp_path / "report.json"
    store.export_report(out_json, fmt="json")
    json_text = out_json.read_text(encoding="utf-8")
    assert "https://instagram.com/reel/123" in json_text
