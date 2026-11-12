# Changelog

Todas las versiones relevantes de ReelsFactoryPro.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el versionado sigue [SemVer](https://semver.org/lang/es/).

## [1.3.0] - 2026-11-12

### Corregido

- **El editable install no funcionaba**: con el layout anterior
  (`package-dir = {"reels_factory" = "."}`) `pip install -e .` no resolvía
  ningún módulo, así que `from downloader import ...` fallaba con
  `ModuleNotFoundError`. Ahora el proyecto usa un layout plano con
  `py-modules`, y tanto la instalación por wheel como la editable exponen los
  módulos con los nombres que usa el propio código. Cubierto por tests de
  empaquetado.

### Añadido

- **Verificación del vídeo final**: tras el render se comprueba que el resultado
  cumple 1080x1920 y ≤55s. Si no, se muestra un aviso en los logs en lugar de
  fallar en silencio.
- **Normalización de audio (loudnorm)**: el audio se normaliza a -14 LUFS
  (estándar de Facebook/TikTok) para evitar penalizaciones por volumen
  inconsistente. Se puede desactivar desde la GUI.
- **Resaltado de palabra activa**: efecto de subtítulos estilo TikTok/Shorts
  usando las marcas de tiempo por palabra de Whisper. La palabra en curso se
  resalta y agranda. Desactivable desde la GUI.
- **Preferencias persistentes**: modelo, idioma, logo, branding y nuevas
  opciones se guardan con `QSettings` y se restauran al abrir la aplicación.
- **Cola persistente**: el estado de los trabajos se guarda en
  `temp/job_queue.json` (escritura atómica). Si la app se cierra a mitad de un
  lote, se puede continuar.
- **Reintentar fallidos**: botón que reprocesa únicamente los trabajos que
  fallaron.
- **Miniaturas**: se genera una miniatura del vídeo final y se muestra en la
  columna "Vista" de la cola. Doble clic abre el vídeo con el reproductor del
  sistema.
- **Exportar SRT**: exporta los subtítulos del último trabajo a `.srt` sin
  volver a transcribir.
- **Más plataformas**: Instagram Reels y YouTube Shorts, además de TikTok.
  La arquitectura ya lo soportaba; solo faltaba la validación de URLs.
- **Modelos de Whisper completos**: la GUI ofrece `large-v3`, `large-v3-turbo`
  y `turbo`. Los modelos turbo tienen calidad de `large-v3` pero son ~4x más
  rápidos.
- **Caché de filtros de FFmpeg**: `ffmpeg -filters` tarda ~0.4s y se cachea el
  resultado. La caché se invalida al cambiar el binario de FFmpeg.

### Cambiado

- `run.sh` y `run.ps1` solo reinstalan las dependencias cuando cambia
  `requirements.txt` (hash SHA-256). Antes se descargaba torch (~2 GB) en cada
  arranque.
- El directorio `packaging/` se renombró a `build_tools/` para no sombrear el
  paquete `packaging` de PyPI.
- La tabla de trabajos tiene una columna más ("Vista") y los anchos manuales se
  aplican después de `resizeColumnsToContents()` (antes se perdían).
- Los assets (logo, icono) se resuelven junto al ejecutable, no en la carpeta
  de datos, para que funcionen con `REELSFACTORYPRO_BASE_DIR`.

### Añadido (infraestructura)

- `jobstore.py`: cola persistente con escrituras atómicas.
- `settings.py`: persistencia de preferencias con `QSettings` y fallback JSON.
- 37 tests nuevos (80 en total) que cubren las mejoras anteriores.

## [1.2.0] - 2026-11-12

### Corregido

- **Cancelación de descargas ignorada**: el hook de progreso de `yt-dlp` capturaba
  `DownloadCancelled` con un `except Exception` genérico, por lo que la descarga
  continuaba hasta el final aunque el usuario pulsara "Cancelar".
- **`NameError` al leer metadatos del vídeo**: `json` se importaba dentro del bloque
  `try` de `get_video_info()`, así que el `except` lanzaba `NameError` en lugar de
  devolver `None` cuando `ffprobe` expiraba.
- **Crash con títulos vacíos**: `metadata.get('title', ...)` devolvía `None` cuando
  TikTok no enviaba título, provocando `TypeError` al recortar la cadena.
- **El modelo de Whisper de la GUI se ignoraba**: la selección de modelo (tiny/base/
  small/medium/large) nunca llegaba al generador de subtítulos.
- **`NameError` en los diálogos de dependencias**: tres lambdas capturaban la
  variable `e` de un bloque `except`, que Python elimina al salir de dicho bloque.
- **Doble diálogo de dependencias**: al pulsar "Iniciar" se abría la ventana de
  dependencias faltantes dos veces y se perdían los mensajes de error.
- **Assets invisibles con `REELSFACTORYPRO_BASE_DIR`**: el logo y el icono se
  buscaban en la carpeta de datos en lugar de la instalación del programa.
- **`third_party/ffmpeg` nunca se buscaba**: `resolve_binaries()` recibía un
  parámetro `base_dir` que ningún llamador pasaba.
- **Fuga de temporales**: los ficheros `.ass` copiados para el render nunca se
  eliminaban.
- **RNG global alterado**: `processor.py` sembraba `random.seed()` global, lo que
  afectaba al resto del proceso.
- **Import como librería roto**: `import reels_factory` fallaba por imports absolutos.
- **Conflicto con el paquete `packaging` de PyPI**: el directorio `packaging/` del
  repositorio lo sombreaba y rompía `pytest`. Renombrado a `build_tools/`.
- **`pytest` invocado sin `python -m`**: fallaba con `ModuleNotFoundError` al no
  estar el directorio raíz en `sys.path`.

### Añadido

- `pyproject.toml` con metadatos del proyecto, configuración de `pytest` y de `ruff`.
- Workflow `ci.yml`: tests en Python 3.11/3.12/3.13 y verificación de lint/formato.
- 43 tests de regresión que cubren cada uno de los fallos corregidos.
- Transliteración de acentos en los nombres de fichero (`"año"` → `"ano"`).

### Cambiado

- Dependencias actualizadas: `yt-dlp` 2026.10.26, `PySide6` 6.12.0,
  `openai-whisper` 20250625, `torch` 2.15.0, `numpy` 2.x (`<2.6` por `numba`).
- GitHub Actions actualizadas a `actions/checkout@v7`, `actions/setup-python@v7` y
  `actions/upload-artifact@v7`.
- `ffmpeg-full` sigue siendo el paquete recomendado en macOS: es el único que
  incluye `libass` (necesario para quemar subtítulos).
- Código formateado con `ruff format` y lint limpio con `ruff check`.

## [1.1.0]

- Cola de trabajos con progreso, logs y metadatos en la GUI.
- Resolución de dependencias desde la interfaz (seleccionar/instalar FFmpeg y yt-dlp).
- Generación de iconos para macOS y Windows desde la GUI.

## [1.0.0]

- Versión inicial: descarga con `yt-dlp`, procesado a 1080x1920 (<=55s), overlay de
  marca y subtítulos automáticos con Whisper.
