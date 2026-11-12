"""Compat shim para el módulo requerido `subtitler.py`.

El código principal de subtítulos vive en `subtitles.py`.
"""

from subtitles import (
    SubtitleGenerator,
    SubtitleResult,
    SubtitleSegment,
    generate_subtitles,
)

__all__ = [
    "SubtitleGenerator",
    "SubtitleResult",
    "SubtitleSegment",
    "generate_subtitles",
]
