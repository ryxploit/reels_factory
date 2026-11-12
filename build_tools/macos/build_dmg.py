from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    dist_dir = project_root / "dist" / "ReelsFactoryPro"
    app_path = dist_dir / "ReelsFactoryPro.app"
    out_path = project_root / "dist" / "ReelsFactoryPro.dmg"

    if not app_path.exists():
        raise SystemExit(f"No existe {app_path}. Primero ejecuta PyInstaller.")

    import dmgbuild

    # Permite ejecutar el script directamente (`python build_tools/macos/build_dmg.py`).
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from build_tools.macos.dmg_settings import settings

    dmgbuild.build_dmg(
        filename=str(out_path),
        volume_name="ReelsFactoryPro",
        settings=settings(project_root),
    )

    print(f"DMG creado: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
