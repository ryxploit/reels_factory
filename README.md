# ReelsFactoryPro

App de escritorio macOS (Apple Silicon) para descargar TikTok (yt-dlp), procesar a Facebook Reels (1080x1920 / <=55s + overlay) y generar subtítulos con Whisper acelerado por MPS + FFmpeg.

Herramienta profesional y totalmente funcional para descargar videos de TikTok sin watermark, procesarlos al formato óptimo para Facebook Reels, y generar subtítulos automáticos con IA.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-macOS%20Apple%20Silicon-lightgrey.svg)
![Status](https://img.shields.io/badge/Status-Production%20Ready-success.svg)

---

## ✨ Características

- **📥 Descarga de TikTok** - Sin marca de agua usando yt-dlp  
- **🎬 Procesamiento Profesional**
  - Formato 9:16 (1080x1920) para Reels
  - Máximo 55 segundos de duración
  - Reencuadre centrado automático
  - Codec H.264 compatible con Facebook
- **🔤 Subtítulos Automáticos** - OpenAI Whisper con soporte multiidioma
- **🏷️ Branding** - Logo PNG en esquina inferior derecha
- **🖥️ Interfaz Gráfica (PySide6)** - Cola, progreso y logs
- **⚡ Optimizado para Apple Silicon** - M1/M2/M3 nativamente
- **🔧 Modular y escalable** - Código limpio, reutilizable

---

## Requisitos

- macOS (Apple Silicon) o Windows 10/11
- Python 3.11 o 3.12
- FFmpeg con soporte de subtítulos (libass)

---

## Instalación (macOS)

### 1) Homebrew + dependencias

```bash
brew install ffmpeg-full yt-dlp python@3.11
```

Importante:
- `ffmpeg-full` es **keg-only** y es el que incluye filtros para **quemar subtítulos** (libass).
- Ejecuta la app con `./run.sh` para que el PATH use automáticamente `ffmpeg-full`.

Si Homebrew muestra errores de permisos en `/opt/homebrew`, corrige ownership (requiere sudo):

```bash
sudo chown -R "$(whoami)" /opt/homebrew
```

## Instalación (Windows 10/11 x64)

1) Instala Python 3.11/3.12 **x64** desde python.org.

2) Instala FFmpeg “full” (con libass). Opciones:
- Chocolatey: `choco install ffmpeg`
- Winget (si disponible): `winget install Gyan.FFmpeg`

3) En PowerShell (recomendado):

```powershell
cd C:\ruta\a\reels_factory

# Si tu política bloquea scripts, usa esta sesión temporal:
Set-ExecutionPolicy -Scope Process Bypass -Force

.\run.ps1
```

Alternativa (WSL o Git Bash):

```bash
./run.sh
```

Notas:
- Si el botón de subtítulos muestra `Subtítulos: NO`, el FFmpeg instalado no trae `subtitles`/libass.
- Ver matriz de compatibilidad: `docs/COMPATIBILITY_MATRIX.md`.
- Configuración por variables de entorno: `docs/CONFIGURATION.md`.

Si usas Apple Silicon y `brew` no está en el PATH, añade esto a `~/.zprofile`:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
source ~/.zprofile
```

### 2) Entorno virtual + dependencias Python

```bash
cd /ruta/a/reels_factory
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Alternativa (recomendada): arranque con script que auto-crea el venv si falta:

```bash
./run.sh
```

Notas:
- `requirements.txt` incluye `PySide6`, `openai-whisper` y `torch`.
- Si `torch` falla en tu combinación exacta de macOS/Python, instala primero Python 3.11/3.12 por Homebrew y repite.

---

## Uso

### GUI (PySide6)

```bash
python app.py
```

Si prefieres el arranque “todo en uno” (crea `.venv` si falta):

```bash
./run.sh
```

Overlay (logo):
- Recomendado: PNG con transparencia.
- Hay un ejemplo en `assets/logo.svg` (puedes exportarlo a PNG con Preview antes de seleccionarlo en la app).

### Línea de Comandos

```bash
# Descargar TikTok
python downloader.py "https://www.tiktok.com/@user/video/123"

# Procesar para Reels
python processor.py video.mp4

# Procesar con logo
python processor.py video.mp4 logo.png

# Generar subtítulos (auto-detecta idioma)
python subtitles.py video.mp4

# Generar subtítulos en idioma específico
python subtitles.py video.mp4 es  # Español
python subtitles.py video.mp4 en  # Inglés
```

### Uso como Librería Python

```python
from reels_factory import download_tiktok, process_for_reels, generate_subtitles
from pathlib import Path

# Descargar
result = download_tiktok("https://www.tiktok.com/@user/video/123")
video = result.file_path

# Generar subtítulos
subs = generate_subtitles(video)
subtitle_file = subs.subtitle_path

# Procesar para Reels
final = process_for_reels(
    input_path=video,
    logo_path=Path("logo.png"),
    subtitle_path=subtitle_file
)

print(f"✓ Video listo: {final.file_path}")
```

---

## Estructura

```
reels_factory/
├── app.py
├── pipeline.py
├── downloader.py
├── video_processor.py
├── processor.py
├── subtitler.py
├── subtitles.py
├── config.py
├── utils.py
├── assets/
├── input/
├── temp/
├── output/
└── logs/
```

---

## ⚙️ Configuración

En `config.py`:

```python
# Video
VIDEO_CODEC = "libx264"        # Codec H.264
VIDEO_CRF = 23                 # Calidad (18-28)
MAX_DURATION_SECONDS = 55      # Máximo 55s

# Subtítulos  
MODEL_SIZE = "base"            # tiny|base|small|medium|large
FONT_SIZE = 24                 # Tamaño fuente
MARGIN_V = 50                  # Margen inferior

# Branding
LOGO_WIDTH = 150               # Ancho logo px
LOGO_OPACITY = 0.8             # Transparencia
```

---

## Whisper (MPS en Apple Silicon)

`openai-whisper` usa PyTorch. Si `torch.backends.mps.is_available()` devuelve `True`, la app cargará Whisper en `mps` automáticamente (si `USE_MPS=True` en `config.py`).

Comprobación rápida:

```bash
source .venv/bin/activate
python -c "import torch; print('mps:', hasattr(torch.backends,'mps') and torch.backends.mps.is_available())"
```

Descargar el modelo (se cachea la primera vez que se usa):

```bash
source .venv/bin/activate
python -c "import whisper; whisper.load_model('base')"
```

| Modelo | Tamaño | RAM | Velocidad | Precisión |
|--------|--------|-----|-----------|-----------|
| tiny | 39 MB | ~500 MB | ⚡⚡⚡⚡⚡ | ⭐⭐ |
| **base** | 74 MB | ~1 GB | ⚡⚡⚡⚡ | ⭐⭐⭐ |
| small | 244 MB | ~2 GB | ⚡⚡⚡ | ⭐⭐⭐⭐ |
| medium | 769 MB | ~5 GB | ⚡⚡ | ⭐⭐⭐⭐⭐ |
| large | 2.9 GB | ~10 GB | ⚡ | ⭐⭐⭐⭐⭐ |

**Recomendación:** `base` es óptimo (rápido + preciso).

---

## 📱 Facebook Reels Specs

| Parámetro | Valor |
|-----------|-------|
| Resolución | 1080 × 1920 px |
| Aspect Ratio | 9:16 |
| Duración | 3-90 segundos |
| Codec Video | H.264 |
| Codec Audio | AAC @ 192 kbps |
| Frame Rate | 30 fps |
| Formato archivo | MP4 |

---

## ⚖️ Consideraciones Legales

✓ **Siempre cumple con los términos de servicio** de TikTok y Facebook  
✓ **Respeta derechos de autor** - solo content que tengas derecho a usar  
✓ **Da crédito** a creadores originales cuando sea apropiado  
✓ **Diseñado para** uso personal, educativo y comercial responsable  
✓ **Evita prácticas** que causen strikes o violaciones de copyright  

---

## Troubleshooting (errores comunes)

### `ffmpeg` o `yt-dlp` no se encuentra
```bash
brew install ffmpeg-full yt-dlp
```

Si sigue fallando desde la GUI, comprueba el PATH:

```bash
which ffmpeg
which yt-dlp
```

### Descarga falla en TikTok
```bash
pip install --upgrade yt-dlp
```

TikTok cambia con frecuencia; mantener `yt-dlp` actualizado suele resolverlo.

### Whisper muy lento
- Usa un modelo menor (`tiny` o `base`).
- Verifica que MPS esté disponible con el comando de comprobación.

### "Virtual environment not found"
```bash
./run.sh
```

En Windows (PowerShell):

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\run.ps1
```

### Video no descarga
- Verifica URL (puede ser privado)
- Actualiza yt-dlp: `pip install --upgrade yt-dlp`
- Comprueba conexión a internet

---

## 🛠️ Desarrollo

```bash
# Setup
git clone <repo>
cd reels_factory
./run.sh --no-setup

# Tests
python -m pip install -r requirements-dev.txt
pytest -q
```

---

## 📊 Roadmap

- [ ] Soporte para más plataformas (Instagram, YouTube Shorts)
- [ ] Editor visual de subtítulos
- [ ] Watermark personalizado (no solo logo)
- [ ] Batch processing automático
- [ ] API REST para integración
- [ ] Docker image

---

## 📝 Licencia

MIT License - Uso libre para proyectos personales y comerciales.

```
Copyright (c) 2026 ReelsFactoryPro

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction...
```

---

## Créditos

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** - Descarga confiable de videos
- **[OpenAI Whisper](https://github.com/openai/whisper)** - Reconocimiento de voz
- **[FFmpeg](https://ffmpeg.org/)** - Procesamiento profesional de video
- **PySide6 (Qt)** - Interfaz gráfica nativa de escritorio

---

## 📧 Contacto & Soporte

Para bugs, sugerencias o preguntas:
- Abre un issue en GitHub
- Revisa la documentación en [README.md](README.md)
- Consulta los logs en `./logs/` (o `REELSFACTORYPRO_BASE_DIR/logs/` si lo cambias)

---

**Creado con ❤️ por ingenieros de software para creadores de contenido**

v1.0.0 - Production Ready
