# Matriz de compatibilidad — ReelsFactoryPro

## Soporte por sistema operativo

| SO | Versiones soportadas | Arquitecturas | Estado |
|---|---|---|---|
| macOS (Apple Silicon) | Estable actual y 2 anteriores (aprox. N, N-1, N-2) | ARM64 (M1+) | Soportado |
| Windows 10 | 21H2 o superior | x64 | Soportado |
| Windows 11 | 22H2 o superior | x64 | Soportado |

## Versiones de Python

| Python | Estado | Notas |
|---|---|---|
| 3.11 | Soportado | Mínimo requerido |
| 3.12 | Soportado | Probado en CI |
| 3.13 | Soportado | Probado en CI |
| < 3.11 | No soportado | `run.sh`/`run.ps1` lo rechazan |

## Nota importante sobre Windows x86 (32-bit)

La funcionalidad de subtítulos basada en Whisper + PyTorch no es viable en Windows 32-bit (el ecosistema moderno de PyTorch/Whisper se distribuye principalmente para x64). Para Windows x86 se recomienda:

- Distribución “Lite” sin subtítulos (descarga + procesado + overlay). 
- Alternativa: backend de transcripción externo (servicio) o migración a una implementación nativa (p.ej. whisper.cpp) con binarios x86.

## Dependencias por plataforma

| Componente | macOS | Windows |
|---|---|---|
| GUI | PySide6 | PySide6 |
| Descarga | `yt-dlp` (paquete Python) | `yt-dlp` (paquete Python) |
| Render video | FFmpeg con `libass` (recomendado: `ffmpeg-full`) | FFmpeg build “full” con `libass` |
| Subtítulos | Whisper + PyTorch (MPS/CPU) | Whisper + PyTorch (CPU; CUDA si instalas build GPU) |

## Requisitos mínimos de hardware

### macOS (M1+)
- RAM: 8 GB (recomendado 16 GB para modelos `small+`)
- Almacenamiento: 2–5 GB libres (cache de modelos + temporales)

### Windows x64
- RAM: 8 GB (recomendado 16 GB)
- CPU: 4 cores
- Almacenamiento: 2–5 GB libres

