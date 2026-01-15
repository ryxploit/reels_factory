# Configuración

## Variables de entorno

- `REELSFACTORYPRO_BASE_DIR`
  - Cambia la carpeta base donde se crean `input/`, `temp/`, `output/`, `assets/`, `logs/`.
- `REELSFACTORYPRO_FFMPEG`
  - Ruta absoluta a `ffmpeg` (si no está en `PATH`).
- `REELSFACTORYPRO_FFPROBE`
  - Ruta absoluta a `ffprobe` (si no está en `PATH`).
- `REELS_FACTORY_DEBUG`
  - `true/false`. Habilita comportamiento de debug.

## Notas de FFmpeg

- Para quemar subtítulos `.ass` se requiere un build de FFmpeg con el filtro `subtitles` (libass).
- En macOS se recomienda `ffmpeg-full`.

