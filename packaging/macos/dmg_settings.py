from __future__ import annotations

from pathlib import Path


def settings(project_root: Path):
    dist_dir = project_root / "dist" / "ReelsFactoryPro"
    app_name = "ReelsFactoryPro"

    return {
        "title": app_name,
        "icon_size": 128,
        "window": ((200, 200), (820, 520)),
        "background": None,
        "contents": [
            (str(dist_dir / f"{app_name}.app"), (180, 260)),
            ("/Applications", (640, 260)),
        ],
    }

