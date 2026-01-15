from __future__ import annotations

from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    dist_dir = project_root / "dist" / "ReelsFactoryPro"
    app_path = dist_dir / "ReelsFactoryPro.app"
    out_path = project_root / "dist" / "ReelsFactoryPro.dmg"

    if not app_path.exists():
        raise SystemExit(f"No existe {app_path}. Primero ejecuta PyInstaller.")

    import dmgbuild
    from packaging.macos.dmg_settings import settings

    dmgbuild.build_dmg(
        filename=str(out_path),
        volume_name="ReelsFactoryPro",
        settings=settings(project_root),
    )

    print(f"DMG creado: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

