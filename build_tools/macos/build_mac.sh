#!/usr/bin/env bash
set -euo pipefail

# Script simple para generar App.icns y construir el .app con PyInstaller
# Ejecutar en macOS.

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}

echo "Generando iconos..."
$PYTHON "$ROOT/build_tools/macos/make_icns.py"

ICNS="$ROOT/assets/generated_icons/App.icns"
if [ ! -f "$ICNS" ]; then
  echo "Advertencia: no se encontró $ICNS. El .app no tendrá icono." >&2
fi

echo "Ejecutando PyInstaller..."
# Asegúrate de tener pyinstaller instalado: python3 -m pip install pyinstaller
cd "$ROOT"
$PYTHON -m PyInstaller build_tools/pyinstaller/ReelsFactoryPro.spec

echo "Creando DMG..."
$PYTHON build_tools/macos/build_dmg.py

echo "Build completado. Busca el DMG en dist/" 
