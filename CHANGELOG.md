# Changelog

Todas las versiones relevantes de ReelsFactoryPro.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el versionado sigue [SemVer](https://semver.org/lang/es/).

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
