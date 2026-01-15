from __future__ import annotations

from pathlib import Path

from cx_Freeze import Executable, setup


project_root = Path(__file__).resolve().parents[2]

build_exe_options = {
    "packages": [],
    "include_files": [
        (str(project_root / "assets"), "assets"),
        (str(project_root / "input"), "input"),
        (str(project_root / "docs"), "docs"),
    ],
}


setup(
    name="ReelsFactoryPro",
    version="1.1.0",
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

