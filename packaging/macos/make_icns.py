#!/usr/bin/env python3
"""Generador de App.icns para macOS a partir de assets/icon.svg.

Crea PNGs en `assets/generated_icons/`, genera un `.iconset` y usa
`iconutil` para producir `App.icns`. Diseñado para ejecutarse en macOS.
"""
from pathlib import Path
import sys
import subprocess

project_root = Path(__file__).resolve().parents[2]
assets = project_root / "assets"
src = assets / "icon.svg"
out_dir = assets / "generated_icons"

out_dir.mkdir(parents=True, exist_ok=True)

try:
    import cairosvg
except Exception:
    print("cairosvg no instalado. Ejecuta: python -m pip install cairosvg")
    raise

sizes = [16, 32, 64, 128, 256, 512, 1024]
for s in sizes:
    out_file = out_dir / f"icon_{s}x{s}.png"
    print(f"Generando {out_file}")
    cairosvg.svg2png(url=str(src), write_to=str(out_file), output_width=s, output_height=s)

# Crear iconset
iconset = out_dir / 'App.iconset'
iconset.mkdir(parents=True, exist_ok=True)

shutil_map = [
    ('icon_16x16.png', 'icon_16x16.png'),
    ('icon_32x32.png', 'icon_16x16@2x.png'),
    ('icon_32x32.png', 'icon_32x32.png'),
    ('icon_64x64.png', 'icon_32x32@2x.png'),
    ('icon_128x128.png', 'icon_128x128.png'),
    ('icon_256x256.png', 'icon_128x128@2x.png'),
    ('icon_256x256.png', 'icon_256x256.png'),
    ('icon_512x512.png', 'icon_256x256@2x.png'),
    ('icon_512x512.png', 'icon_512x512.png'),
    ('icon_1024x1024.png', 'icon_512x512@2x.png'),
]

import shutil
for src_name, dst_name in shutil_map:
    s = out_dir / src_name
    d = iconset / dst_name
    if s.exists():
        shutil.copy2(str(s), str(d))

# Crear .icns (macOS)
icns_path = out_dir / 'App.icns'
if sys.platform == 'darwin':
    try:
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(icns_path)], check=True)
        print(f'ICNS creado: {icns_path}')
    except subprocess.CalledProcessError as e:
        print('iconutil falló:', e)
else:
    print('No estás en macOS: no se creará .icns automáticamente.')

print('Generación completada. Archivos en:', out_dir)
