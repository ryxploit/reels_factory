# Build & Release (macOS + Windows)

## Objetivo

Generar binarios distribuibles y verificables:

- macOS: `.app` + `.dmg` (firmado y notarizado)
- Windows: `.exe`/carpeta + `.msi` (firmado)

Este repositorio incluye automatización vía CI, pero la firma/notarización requieren credenciales de desarrollador.

## Build local (sin firmar)

### macOS
```bash
python3.13 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller dmgbuild

python -m PyInstaller build_tools/pyinstaller/ReelsFactoryPro.spec
python build_tools/macos/build_dmg.py
```

### Windows (PowerShell)
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller build_tools\pyinstaller\ReelsFactoryPro.spec
```

## Automatización CI

- `.github/workflows/ci.yml` — tests (Python 3.11/3.12/3.13) + lint/formato en cada PR a `main`.
- `.github/workflows/release.yml` — build de `.dmg` (macOS) y `.msi` (Windows) al hacer push de un tag `v*`.

## Firma y notarización

### macOS (Gatekeeper)

- Firma: `codesign` con Developer ID Application
- Notarización: `xcrun notarytool submit` con Apple ID + App Specific Password o App Store Connect API key
- Staple: `xcrun stapler staple`

### Windows (UAC / SmartScreen)

- Firma de binarios e instalador: `signtool.exe` con certificado de Code Signing

## Checksums

En CI se genera un `SHA256SUMS.txt` para validar artefactos.

