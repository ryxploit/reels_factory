from __future__ import annotations

from pathlib import Path

from cx_Freeze import Executable, setup

project_root = Path(__file__).resolve().parents[2]

build_exe_options = {
    "packages": [
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.downloader",
        "whisper",
        "whisper.audio",
        "whisper.decoding",
        "whisper.model",
        "whisper.transcribe",
    ],
    "excludes": [
        "matplotlib",
        "tkinter",
        "IPython",
        "jupyter",
        "notebook",
    ],
    "include_files": [
        (str(project_root / "assets"), "assets"),
        (str(project_root / "input"), "input"),
        (str(project_root / "docs"), "docs"),
        (str(project_root / "README.md"), "."),
    ],
}


setup(
    name="ReelsFactoryPro",
    version="1.3.0",
    description="ReelsFactoryPro",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": {
            "upgrade_code": "{B7B5D2B9-9E83-4A6B-9A8C-2D7B0E9F5D2D}",
            "add_to_path": False,
        },
    },
    executables=[
        Executable(
            script=str(project_root / "app.py"),
            base="Win32GUI",
            target_name="ReelsFactoryPro.exe",
            icon=None,
        )
    ],
)
