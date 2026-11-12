"""
Reels Factory - Watermark Detection Module
===========================================
Detecta marcas de agua incrustadas en los píxeles del vídeo.

Cuando alguien descarga un vídeo de TikTok desde la app (en vez de usar
yt-dlp), el logo queda *grabado en el vídeo* como una capa de píxeles. En ese
caso borrar los metadatos del contenedor no sirve de nada: la marca sigue ahí
y las plataformas la detectan visualmente.

El detector busca la firma de una **capa de overlay**, que tiene dos señales
simultáneas:

1. **Quietud temporal**: los píxeles de la marca apenas cambian entre
   fotogramas consecutivos, mientras que el contenido que la rodea se mueve.
2. **Bordes definidos**: un logo tiene formas y texto con contornos nítidos,
   a diferencia de una zona muerta de la escena (un fondo negro, una pared)
   que es completamente plana.

El producto de ambas señales discrimina los tres casos posibles:

============================  ==================  ==================
Caso                          Quietud             Bordes
============================  ==================  ==================
Marca de agua (overlay)       alta                altos
Zona muerta de la escena      alta                nulos
Contenido normal              baja                cualesquiera
============================  ==================  ==================

En lugar de mirar zonas fijas, se recorre una rejilla de ventanas sobre las
bandas donde las apps colocan su logo (esquinas y bordes superiores e
inferiores) y se reporta la ventana más sospechosa.

Este módulo es una **herramienta de aviso**, no un detector infalible: un
vídeo con poca movementación puede dar falsos negativos. Por eso el
resultado siempre se acompaña de una confianza y el usuario decide.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from deps import resolve_binaries


@dataclass
class WatermarkRegion:
    """Zona suspecta detectada en el vídeo.

    Las coordenadas están expresadas en píxeles del vídeo original, para
    poder dibujar el recuadro sobre un fotograma y que el usuario confirme
    visualmente si es una marca de agua o un elemento fijo de la escena.
    """

    name: str
    x: int
    y: int
    width: int
    height: int
    score: float  # 0.0 - 1.0, mayor = más sospechoso
    stillness: float  # proporción de píxeles quietos en la zona
    edge_density: float  # densidad de bordes en la zona

    @property
    def center(self) -> tuple[int, int]:
        """Centro de la zona."""
        return (self.x + self.width // 2, self.y + self.height // 2)


@dataclass
class WatermarkReport:
    """Resultado del análisis de un vídeo."""

    detected: bool = False
    confidence: float = 0.0  # 0.0 - 1.0
    regions: list[WatermarkRegion] = field(default_factory=list)
    frames_analyzed: int = 0
    error: str | None = None
    preview_path: Path | None = None
    """Ruta de una imagen con la zona sospechosa resaltada, para que el
    usuario pueda confirmarla de un vistazo."""

    @property
    def summary(self) -> str:
        """Resumen legible del análisis."""
        if self.error:
            return f"Análisis no disponible: {self.error}"
        if not self.detected:
            return "No se detectaron zonas fijas sospechosas."

        zones = ", ".join(
            f"{r.name} ({r.score:.0%})" for r in sorted(self.regions, key=lambda r: -r.score)[:3]
        )
        return (
            f"Posible marca de agua o elemento fijo (confianza {self.confidence:.0%}). "
            f"Zonas: {zones}"
        )


#: Tamaño de los fotogramas analizados (escalados para ir rápido).
FRAME_WIDTH = 160
FRAME_HEIGHT = 284

#: Bandas donde las apps sociales colocan su marca de agua (fracción Y).
SCAN_BANDS: tuple[tuple[str, float, float], ...] = (
    ("borde inferior", 0.72, 1.00),
    ("borde superior", 0.00, 0.28),
)

#: Tamaño de la ventana deslizante (fracciones del ancho/alto del fotograma).
#:
#: Se usa un único tamaño: uno mayor captura mejor el logo de las apps pero
#: genera menos falsos positivos. Con una ventana pequeña, una interfaz
#: estática de una app (botones de Google Maps, por ejemplo) se confunde
#: con un logo grabado.
WINDOW_W = 0.16
WINDOW_H = 0.10
WINDOW_STEP = 0.04

#: Umbral mínimo de diferencia (0-255) bajo el cual un píxel se considera quieto.
STILL_MIN_THRESHOLD = 3

#: Fracción del cambio global de la escena que se tolera como "quieto".
#:
#: Un overlay semitransparente (como el logo de TikTok) deja pasar parte del
#: contenido de fondo, así que sus píxeles no son idénticos: cambian una
#: fracción del cambio del fondo. Por eso el umbral debe escalar con el
#: movimiento de la escena en lugar de ser un valor absoluto.
STILL_RATIO = 0.25

#: Percentil de las diferencias entre fotogramas que se considera típico.
#: Evita que un destello puntual en la escena invalide la detección.
STILL_PERCENTILE = 75

#: Quietud por encima de la cual se considera anómala (un vídeo normal
#: tiene entre el 10% y el 25% de píxeles quietos en una esquina).
QUIET_BASELINE = 0.22

#: Rango de quietud anómala que se normaliza a 1.0.
QUIET_RANGE = 0.20

#: Densidad de bordes a partir de la cual se considera "con detalle".
EDGE_FULL = 8.0


def _run_ffmpeg(args: list[str], timeout: int = 120) -> tuple[int, bytes, str]:
    """Ejecuta ffmpeg y devuelve (código, stdout, stderr)."""
    bins = resolve_binaries()
    if not bins.ffmpeg:
        return 1, b"", "FFmpeg no encontrado"

    cmd = [str(bins.ffmpeg), "-hide_banner", "-loglevel", "error", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr.decode("utf-8", "ignore")
    except subprocess.TimeoutExpired:
        return 1, b"", "ffmpeg agotó el tiempo de espera"
    except Exception as e:  # pragma: no cover - depende del entorno
        return 1, b"", str(e)


def _get_duration(video_path: Path) -> float:
    """Obtiene la duración del vídeo en segundos."""
    from utils import get_video_info

    info = get_video_info(video_path)
    if not info:
        return 0.0
    try:
        return float(info.get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _extract_frames(video_path: Path, count: int = 14) -> np.ndarray:
    """Extrae `count` fotogramas en escala de grises como array numpy.

    Devuelve un array de forma (N, ALTO, ANCHO) con los valores en 0-255.
    """
    duration = _get_duration(video_path)
    if duration <= 0:
        return np.empty((0, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.float32)

    rate = max(count / duration, 0.01)

    code, stdout, _stderr = _run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-vf",
            f"fps={rate:.6f},scale={FRAME_WIDTH}:{FRAME_HEIGHT},format=gray",
            "-frames:v",
            str(count),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    )
    if code != 0 or not stdout:
        return np.empty((0, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.float32)

    frame_size = FRAME_WIDTH * FRAME_HEIGHT
    usable = len(stdout) // frame_size
    if usable < 3:
        return np.empty((0, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.float32)

    frames = np.frombuffer(stdout[: usable * frame_size], dtype=np.uint8)
    return frames.reshape(usable, FRAME_HEIGHT, FRAME_WIDTH).astype(np.float32)


def _still_map(frames: np.ndarray) -> np.ndarray:
    """Mapa de píxeles quietos (True = apenas cambia entre fotogramas).

    El umbral es **adaptativo**: se calcula a partir del cambio global de la
    escena. Un overlay semitransparente deja pasar parte del fondo, así que
    sus píxeles cambian una fracción del cambio del fondo, no cero. Con un
    umbral absoluto, un vídeo rápido hides la marca y uno lento la exagera.
    """
    if frames.shape[0] < 2:
        return np.zeros(frames.shape[1:], dtype=bool)

    diffs = np.abs(np.diff(frames, axis=0))  # (N-1, H, W)

    # Cambio global de la escena: la mediana de todas las diferencias.
    global_change = float(np.median(diffs))
    threshold = max(STILL_MIN_THRESHOLD, STILL_RATIO * global_change)

    # Un píxel es "quieto" si en la mayoría de los pares de fotogramas
    # consecutivos apenas cambia. Se usa un percentil en lugar del máximo
    # para que un destello puntual en la escena no invalide la detección.
    typical_diff = np.percentile(diffs, STILL_PERCENTILE, axis=0)
    return typical_diff <= threshold


def _edge_map(frames: np.ndarray) -> np.ndarray:
    """Mapa de densidad de bordes (gradiente espacial medio)."""
    if frames.shape[0] == 0:
        return np.zeros(frames.shape[1:], dtype=np.float32)

    gx = np.abs(np.diff(frames, axis=2))  # (N, H, W-1)
    gy = np.abs(np.diff(frames, axis=1))  # (N, H-1, W)

    h, w = frames.shape[1], frames.shape[2]
    edges = np.zeros((h, w), dtype=np.float32)

    edges[:, :-1] += gx.mean(axis=0)
    edges[:-1, :] += gy.mean(axis=0)
    return edges / 2.0


def _scan_windows(
    still: np.ndarray, edges: np.ndarray
) -> list[tuple[str, int, int, int, int, float, float, float]]:
    """Recorre una rejilla de ventanas y puntúa cada una.

    Para cada ventana se compara la quietud de su interior con la de un
    **anillo circundante**. Una marca de agua está congelada mientras el
    contenido que la rodea se mueve: el anillo es ruidoso. En cambio, una
    zona muerta de la escena (una pared lisa, un bloque de color) tiene un
    entorno igual de quieto, y así se descarta.

    Returns:
        Lista de (nombre, x, y, w, h, score, quiet, edge_density)
    """
    height, width = still.shape
    win_w = max(4, int(WINDOW_W * width))
    win_h = max(4, int(WINDOW_H * height))
    step_x = max(2, int(WINDOW_STEP * width))
    step_y = max(2, int(WINDOW_STEP * height))

    # El anillo se extiende un 50% más allá de la ventana en cada lado.
    ring_pad_x = max(2, win_w // 2)
    ring_pad_y = max(2, win_h // 2)

    results: list[tuple[str, int, int, int, int, float, float, float]] = []

    for band_name, y_start, y_end in SCAN_BANDS:
        y_from = int(y_start * height)
        y_to = int(y_end * height)

        for y0 in range(y_from, max(y_from + 1, y_to - win_h + 1), step_y):
            for x0 in range(0, max(1, width - win_w + 1), step_x):
                x1 = min(x0 + win_w, width)
                y1 = min(y0 + win_h, height)

                region_still = still[y0:y1, x0:x1]
                region_edges = edges[y0:y1, x0:x1]

                quiet = float(region_still.mean())
                edge_density = float(region_edges.mean())

                # Anillo circundante: el entorno inmediato de la ventana.
                ry0 = max(0, y0 - ring_pad_y)
                ry1 = min(height, y1 + ring_pad_y)
                rx0 = max(0, x0 - ring_pad_x)
                rx1 = min(width, x1 + ring_pad_x)

                ring = still[ry0:ry1, rx0:rx1]
                ring_quiet = float(ring.mean()) if ring.size else 0.0

                # Cuánto más quieta es la ventana que su entorno.
                excess = max(0.0, quiet - ring_quiet)

                # La quietud por encima de la línea base es anómala.
                quiet_score = max(0.0, min(1.0, (quiet - QUIET_BASELINE) / QUIET_RANGE))
                # Un logo tiene bordes definidos; una zona plana no.
                edge_score = max(0.0, min(1.0, edge_density / EDGE_FULL))

                # Si el entorno también está congelado, no es un overlay sino
                # una zona quieta de la escena.
                local_score = min(1.0, excess / 0.15)

                # Ambas señales son necesarias: quieto + con bordes = overlay.
                score = quiet_score * edge_score * local_score

                if score > 0:
                    results.append(
                        (band_name, x0, y0, x1 - x0, y1 - y0, score, quiet, edge_density)
                    )

    return results


def detect_watermark(video_path: Path, threshold: float = 0.55) -> WatermarkReport:
    """
    Analiza un vídeo en busca de marcas de agua incrustadas.

    Args:
        video_path: Ruta del vídeo a analizar
        threshold: Confianza mínima (0-1) para considerar que hay marca

    Returns:
        WatermarkReport con el resultado del análisis
    """
    if not video_path.exists():
        return WatermarkReport(error=f"No existe el vídeo: {video_path}")

    frames = _extract_frames(video_path, count=14)
    if frames.shape[0] < 3:
        return WatermarkReport(error="No se pudieron extraer fotogramas para analizar")

    still = _still_map(frames)
    edges = _edge_map(frames)

    candidates = _scan_windows(still, edges)
    candidates.sort(key=lambda item: -item[5])

    # Dimensiones del vídeo original, para escalar las coordenadas.
    info = _get_video_info(video_path)
    scale_x = (info["width"] / FRAME_WIDTH) if info else 1.0
    scale_y = (info["height"] / FRAME_HEIGHT) if info else 1.0

    # Descarta ventanas que se solapan: una sola marca de agua produce
    # varias ventanas contiguas con puntuación alta.
    regions: list[WatermarkRegion] = []
    for band, x, y, w, h, score, quiet, edge_density in candidates:
        if score < threshold:
            continue
        if any(
            r.x < x + w and x < r.x + r.width and r.y < y + h and y < r.y + r.height
            for r in regions
        ):
            continue
        regions.append(
            WatermarkRegion(
                name=f"{band} ({int(x * scale_x)},{int(y * scale_y)})",
                x=int(x * scale_x),
                y=int(y * scale_y),
                width=int(w * scale_x),
                height=int(h * scale_y),
                score=score,
                stillness=quiet,
                edge_density=edge_density,
            )
        )
        if len(regions) >= 3:
            break

    report = WatermarkReport(
        detected=bool(regions),
        confidence=max((r.score for r in regions), default=0.0),
        regions=regions,
        frames_analyzed=int(frames.shape[0]),
    )

    if report.detected:
        report.preview_path = _render_preview(video_path, report.regions)

    return report


def _get_video_info(video_path: Path) -> dict | None:
    """Metadatos del vídeo (dimensiones)."""
    from utils import get_video_info

    return get_video_info(video_path)


def _render_preview(video_path: Path, regions: list[WatermarkRegion]) -> Path | None:
    """Genera una imagen del primer fotograma con las zonas resaltadas.

    Permite al usuario confirmar visualmente si lo detectado es una marca de
    agua o simplemente un elemento fijo de la escena (un rótulo de una app,
    el borde de un filtro, etc.).
    """
    bins = resolve_binaries()
    if not bins.ffmpeg or not regions:
        return None

    out_path = Path(tempfile.mkdtemp(prefix="watermark_preview_")) / "preview.jpg"

    drawboxes = []
    for region in regions:
        drawboxes.append(
            f"drawbox=x={region.x}:y={region.y}:w={region.width}:h={region.height}:"
            f"color=red@0.9:t=4"
        )

    cmd = [
        str(bins.ffmpeg),
        "-y",
        "-v",
        "error",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        ",".join(drawboxes),
        "-q:v",
        "3",
        str(out_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode == 0 and out_path.exists():
            return out_path
    except Exception:  # pragma: no cover - no debe romper el análisis
        pass

    return None
