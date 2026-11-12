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
| `VideoConfig` | `ENABLE_LOUDNORM` | `True` | Normaliza el audio a -14 LUFS |
| `VideoConfig` | `LOUDNORM_I` / `TP` / `LRA` | `-14` / `-1.5` / `11` | Parámetros de loudnorm |
| `VideoConfig` | `VALIDATE_OUTPUT` | `True` | Verifica las specs del vídeo final |
| `SubtitleConfig` | `MODEL_SIZE` | `base` | Modelo Whisper por defecto |
| `SubtitleConfig` | `USE_MPS` | `True` | Aceleración por Metal (MPS) en macOS |
| `SubtitleConfig` | `FONT_NAME` / `FONT_SIZE` | `Arial` / `24` | Tipografía de los subtítulos |
| `SubtitleConfig` | `ENABLE_WORD_HIGHLIGHT` | `True` | Resaltado de palabra activa |
| `SubtitleConfig` | `HIGHLIGHT_COLOR` | `&H00FFFF` | Color de la palabra activa |
| `SubtitleConfig` | `WORD_HIGHLIGHT_SCALE` | `120` | Escala de la palabra activa (ASS `\fsc`) |
| `SubtitleConfig` | `AVAILABLE_MODELS` | 7 modelos | Modelos ofrecidos en la GUI |
| `BrandingConfig` | `LOGO_WIDTH` / `LOGO_HEIGHT` | `150` | Tamaño del overlay |
| `BrandingConfig` | `LOGO_MARGIN_BOTTOM` | `100` | Separación inferior del overlay |

> Nota: el modelo Whisper seleccionado en la GUI tiene prioridad sobre
> `SubtitleConfig.MODEL_SIZE` para cada trabajo.

## Preferencias de la aplicación

Las opciones que se eligen en la GUI (subtítulos, modelo, idioma, logo,
branding, limpieza de temporales, resaltado y loudnorm) se guardan
automáticamente y se restauran al abrir la aplicación.

- macOS: `~/Library/Preferences/com.ReelsFactoryPro.ReelsFactoryPro.plist`
- Windows: registro de usuario (`HKCU\Software\ReelsFactoryPro\ReelsFactoryPro`)

Si `QSettings` no está disponible, se usa `temp/settings.json` como alternativa.

## Cola persistente

El estado de los trabajos se guarda en `temp/job_queue.json` con escritura
atómica. Contiene la URL, el estado (`Pendiente`, `En curso`, `Listo`, `Falló`,
`Cancelado`), el resultado y los metadatos de cada trabajo.

- Al arrancar, los trabajos pendientes o interrumpidos se pueden reintentar.
- El botón "Reintentar fallidos" reprocesa solo los que fallaron.
- El fichero se puede borrar sin efecto: se regenera en el siguiente lote.

## Empaquetado

- `third_party/ffmpeg/bin/` — si existen `ffmpeg`/`ffprobe` aquí, se usan con
  prioridad sobre el `PATH` (útil para builds autocontenidos).
- Alternativamente, define `REELSFACTORYPRO_FFMPEG` y `REELSFACTORYPRO_FFPROBE`.

