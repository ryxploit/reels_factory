# Seguridad por plataforma

## macOS

- Gatekeeper: distribuir `.app` firmado y notarizado.
- Permisos: evitar accesos innecesarios (cámara/micrófono). Whisper trabaja con audio extraído de archivos locales.
- Hardening runtime: habilitarlo para builds de distribución.

## Windows

- UAC: instaladores `.msi` deben ejecutar elevación sólo cuando sea necesario.
- Defender/SmartScreen: minimizar falsos positivos firmando binarios.

## Riesgos comunes y mitigación

- Dependencias externas (FFmpeg): usar fuentes confiables, checksums y rutas explícitas.
- URLs no confiables: validar formato y no ejecutar comandos con interpolación insegura.
- Archivos temporales: limpiar `temp/` y no escribir en directorios protegidos.

