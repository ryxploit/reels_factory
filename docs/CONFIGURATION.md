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

## Configuración por archivo

Los valores por defecto viven en `config.py` y se pueden ajustar sin tocar la GUI:

| Clase | Opción | Default | Descripción |
|---|---|---|---|
| `VideoConfig` | `WIDTH` / `HEIGHT` | `1080` / `1920` | Resolución de salida (9:16) |
| `VideoConfig` | `MAX_DURATION_SECONDS` | `55` | Duración máxima del reel |
| `VideoConfig` | `VIDEO_CODEC` | `libx264` | Codec de video (H.264) |
| `VideoConfig` | `FPS` | `30` | Fotogramas por segundo |
| `VideoConfig` | `ENABLE_VARIATIONS` | `True` | Variaciones sutiles de color/ruido |
| `SubtitleConfig` | `MODEL_SIZE` | `base` | Modelo Whisper por defecto |
| `SubtitleConfig` | `USE_MPS` | `True` | Aceleración por Metal (MPS) en macOS |
| `SubtitleConfig` | `FONT_NAME` / `FONT_SIZE` | `Arial` / `24` | Tipografía de los subtítulos |
| `BrandingConfig` | `LOGO_WIDTH` / `LOGO_HEIGHT` | `150` | Tamaño del overlay |
| `BrandingConfig` | `LOGO_MARGIN_BOTTOM` | `100` | Separación inferior del overlay |

> Nota: el modelo Whisper seleccionado en la GUI tiene prioridad sobre
> `SubtitleConfig.MODEL_SIZE` para cada trabajo.

## Empaquetado

- `third_party/ffmpeg/bin/` — si existen `ffmpeg`/`ffprobe` aquí, se usan con
  prioridad sobre el `PATH` (útil para builds autocontenidos).
- Alternativamente, define `REELSFACTORYPRO_FFMPEG` y `REELSFACTORYPRO_FFPROBE`.

