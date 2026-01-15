"""Compat shim para el módulo requerido `video_processor.py`.

El código principal de procesamiento vive en `processor.py`.
"""

from processor import ProcessingResult, VideoProcessor, process_for_reels

__all__ = [
    "VideoProcessor",
    "ProcessingResult",
    "process_for_reels",
]

