# Build & Release (macOS + Windows)

## Objetivo

Generar binarios distribuibles y verificables:

- macOS: `.app` + `.dmg` (firmado y notarizado)
- Windows: `.exe`/carpeta + `.msi` (firmado)

Este repositorio incluye automatización vía CI, pero la firma/notarización requieren credenciales de desarrollador.

## Build local (sin firmar)

### macOS
```bash
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller dmgbuild

python -m PyInstaller packaging/pyinstaller/ReelsFactoryPro.spec
python packaging/macos/build_dmg.py
```

### Windows (PowerShell)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller packaging\pyinstaller\ReelsFactoryPro.spec
```

## Firma y notarización

### macOS (Gatekeeper)

- Firma: `codesign` con Developer ID Application
- Notarización: `xcrun notarytool submit` con Apple ID + App Specific Password o App Store Connect API key
- Staple: `xcrun stapler staple`

### Windows (UAC / SmartScreen)

- Firma de binarios e instalador: `signtool.exe` con certificado de Code Signing

## Checksums

En CI se genera un `SHA256SUMS.txt` para validar artefactos.

