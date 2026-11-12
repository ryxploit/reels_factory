"""
Reels Factory - Watermark Detection Module
===========================================
Detecta marcas de agua incrustadas en los píxeles del vídeo.

Cuando alguien descarga un vídeo de TikTok desde la app (en vez de usar
yt-dlp), el logo queda *grabado en el vídeo* como una capa de píxeles. En ese
caso borrar los metadatos del contenedor no sirve de nada: la marca sigue ahí
y las plataformas la detectan visualmente.

El detector busca la firma de una **capa de overlay**: una zona rectangular
pequeña que permanece idéntica durante todo el vídeo mientras el contenido
que la rodea se mueve.

Para no confundirse con zonas simplemente inactivas (un fondo negro, una
pared lisa), cada zona candidata se compara con una **franja de referencia**
contigua:

- Si la zona está quieta **y** su vecina se mueve mucho → hay una capa fija
  encima de una escena en movimiento. Es la firma de una marca de agua.
- Si la zona y su vecina están igual de quietas → es una zona muerta de la
  escena, no un overlay.

Este módulo es una **herramienta de aviso**, no un detector infalible: un
vídeo con poca movementación puede dar falsos negativos. Por eso el
resultado siempre se acompaña de una confianza y el usuario decide.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from deps import resolve_binaries


@dataclass
class WatermarkRegion:
    """Zona suspecta detectada en el vídeo."""

    name: str  # "esquina inferior izquierda", "borde superior", ...
    x: int
    y: int
    width: int
    height: int
    score: float  # 0.0 - 1.0, mayor = más sospechoso
    stability: float  # cuánto más quieta está la zona que su entorno
    edge_density: float


@dataclass
class WatermarkReport:
    """Resultado del análisis de un vídeo."""

    detected: bool = False
    confidence: float = 0.0  # 0.0 - 1.0
    regions: list[WatermarkRegion] = field(default_factory=list)
    frames_analyzed: int = 0
    error: str | None = None

    @property
    def summary(self) -> str:
        """Resumen legible del análisis."""
        if self.error:
            return f"Análisis no disponible: {self.error}"
        if not self.detected:
            return "No se detectaron marcas de agua incrustadas."

        zones = ", ".join(
            f"{r.name} ({r.score:.0%})" for r in sorted(self.regions, key=lambda r: -r.score)[:3]
        )
        return f"Marca de agua detectada (confianza {self.confidence:.0%}). Zonas: {zones}"


#: Zonas donde las apps sociales suelen colocar su marca de agua.
#: Formato: (nombre, x_rel, y_rel, ancho_rel, alto_rel) en fracciones 0-1.
#: Las zonas pequeñas son las más frecuentes para el logo.
CANDIDATE_ZONES: tuple[tuple[str, float, float, float, float], ...] = (
    ("esquina inferior izquierda (media)", 0.00, 0.88, 0.13, 0.11),
    ("esquina inferior derecha (media)", 0.87, 0.88, 0.13, 0.11),
    ("esquina inferior izquierda", 0.00, 0.86, 0.22, 0.14),
    ("esquina inferior derecha", 0.78, 0.86, 0.22, 0.14),
    ("esquina superior izquierda (media)", 0.00, 0.00, 0.13, 0.10),
    ("esquina superior derecha (media)", 0.87, 0.00, 0.13, 0.10),
    ("esquina superior izquierda", 0.00, 0.00, 0.22, 0.12),
    ("esquina superior derecha", 0.78, 0.00, 0.22, 0.12),
    ("borde inferior centro", 0.38, 0.90, 0.24, 0.10),
    ("borde superior centro", 0.38, 0.00, 0.24, 0.10),
)

#: Ancho y alto de los fotogramas analizados (escalados para ir rápido).
FRAME_WIDTH = 160
FRAME_HEIGHT = 284


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


def _extract_gray_frames(video_path: Path, count: int = 14) -> list[bytes]:
    """Extrae `count` fotogramas en escala de grises del vídeo.

    Los fotogramas se reparten uniformemente a lo largo del vídeo usando el
    filtro `fps`, que necesita conocer la duración.
    """
    duration = _get_duration(video_path)
    if duration <= 0:
        return []

    # `fps=N/duración` reparte los fotogramas por todo el vídeo.
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
        return []

    frame_size = FRAME_WIDTH * FRAME_HEIGHT
    frames = []
    for i in range(0, len(stdout) - frame_size + 1, frame_size):
        frames.append(stdout[i : i + frame_size])
    return frames


def _zone_activity(frames: list[bytes], x0: int, y0: int, x1: int, y1: int) -> float:
    """Devuelve el cambio medio entre fotogramas dentro de una zona.

    Una marca de agua fija mantiene esta zona prácticamente quieta, mientras
    que el contenido circundante se mueve.
    """
    if len(frames) < 2:
        return 0.0

    diffs = []
    for i in range(len(frames) - 1):
        a = frames[i]
        b = frames[i + 1]
        total = 0
        count = 0
        for y in range(y0, y1):
            row_a = a[y * FRAME_WIDTH + x0 : y * FRAME_WIDTH + x1]
            row_b = b[y * FRAME_WIDTH + x0 : y * FRAME_WIDTH + x1]
            total += sum(abs(p - q) for p, q in zip(row_a, row_b, strict=False))
            count += len(row_a)
        if count:
            diffs.append(total / count)

    return sum(diffs) / len(diffs) if diffs else 0.0


def _reference_zone(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int] | None:
    """Devuelve una franja contigua a la zona para usarla como referencia.

    Se elige la banda lateral más cercana que no se solape con la zona.
    """
    width = FRAME_WIDTH

    # Banda a la derecha.
    ref_x0 = min(x1 + 3, width - 1)
    ref_x1 = min(ref_x0 + (x1 - x0), width)
    if ref_x1 - ref_x0 >= 6:
        return (ref_x0, y0, ref_x1, y1)

    # Banda a la izquierda.
    ref_x1 = max(x0 - 3, 0)
    ref_x0 = max(ref_x1 - (x1 - x0), 0)
    if ref_x1 - ref_x0 >= 6:
        return (ref_x0, y0, ref_x1, y1)

    return None


def _edge_density(frames: list[bytes], x0: int, y0: int, x1: int, y1: int) -> float:
    """Calcula la densidad de bordes (gradientes) en una zona.

    Un logo incrustado produce bordes nítidos en una superficie pequeña; el
    ruido de fondo produce muchos bordes suaves.
    """
    if len(frames) < 2:
        return 0.0

    total_edges = 0
    samples = 0

    for frame in frames:
        for y in range(y0, max(y0 + 1, y1 - 1)):
            for x in range(x0, max(x0 + 1, x1 - 1)):
                idx = y * FRAME_WIDTH + x
                if idx + 1 >= len(frame) or idx + FRAME_WIDTH >= len(frame):
                    continue
                gx = abs(frame[idx] - frame[idx + 1])
                gy = abs(frame[idx] - frame[idx + FRAME_WIDTH])
                total_edges += gx + gy
                samples += 1

    if not samples:
        return 0.0
    return total_edges / samples


def _analyze_zone(
    frames: list[bytes], zone: tuple[str, float, float, float, float]
) -> WatermarkRegion:
    """Analiza una zona concreta a lo largo de los fotogramas.

    El criterio es directo: los píxeles de una capa de overlay **nunca**
    cambian, mientras que los de la escena sí. Se mide la desviación
    temporal de cada píxel y se cuenta qué proporción de la zona es
    completamente estática.

    Para descartar zonas muertas de la escena (un fondo negro, una pared),
    se compara con una franja de referencia contigua: si ambas tienen la
    misma proporción de píxeles estáticos, no hay overlay sino una zona
    inactiva.
    """
    name, x_rel, y_rel, w_rel, h_rel = zone
    width, height = FRAME_WIDTH, FRAME_HEIGHT

    x0 = int(x_rel * width)
    y0 = int(y_rel * height)
    x1 = min(int((x_rel + w_rel) * width), width)
    y1 = min(int((y_rel + h_rel) * height), height)

    if x1 <= x0 or y1 <= y0:
        return WatermarkRegion(name, x0, y0, 0, 0, 0.0, 0.0, 0.0)

    static = _static_pixel_map(frames)

    zone_static = _static_fraction(static, x0, y0, x1, y1)

    ref = _reference_zone(x0, y0, x1, y1)
    ref_static = _static_fraction(static, *ref) if ref else 0.0

    if ref is None:
        return WatermarkRegion(name, x0, y0, x1 - x0, y1 - y0, 0.0, 0.0, 0.0)

    # Cuánto más "congelada" está la zona que su entorno inmediato.
    # Una marca de agua deja entre un 10% y un 30% de píxeles estáticos
    # frente a un 0% en el entorno; se normaliza ese rango a 0-1.
    contrast = max(0.0, min(1.0, (zone_static - ref_static) / 0.20))

    # La escena debe moverse de verdad alrededor: si todo está quieto, no
    # hay overlay, solo una escena estática.
    scene_motion = min(1.0, max(0.0, 1.0 - ref_static))

    edges = _edge_density(frames, x0, y0, x1, y1)
    edge_score = max(0.0, 1.0 - edges / 12.0)

    # Score: contraste de píxeles congelados (principal) x movimiento de la
    # escena (condición necesaria), refinado por la densidad de bordes.
    score = max(0.0, min(1.0, contrast * scene_motion * 0.85 + edge_score * scene_motion * 0.15))

    return WatermarkRegion(
        name=name,
        x=x0,
        y=y0,
        width=x1 - x0,
        height=y1 - y0,
        score=score,
        stability=contrast,
        edge_density=edges,
    )


def _static_pixel_map(frames: list[bytes]) -> list[list[bool]]:
    """Marca los píxeles que no cambian entre fotogramas.

    Devuelve una matriz (alto x ancho) de booleanos: True si el píxel es
    prácticamente estático a lo largo de toda la secuencia.

    Una marca de agua incrustada hace que sus píxeles salgan estáticos
    (salvo que el contenido de detrás se mueva mucho), mientras que el
    contenido real de la escena cambia.
    """
    if len(frames) < 2:
        return []

    width = FRAME_WIDTH
    height = FRAME_HEIGHT

    # Primer fotograma como base.
    first = frames[0]
    static = [[True] * width for _ in range(height)]

    for frame in frames[1:]:
        for y in range(height):
            row_static = static[y]
            base = y * width
            for x in range(width):
                if row_static[x] and abs(first[base + x] - frame[base + x]) > 2:
                    row_static[x] = False

    return static


def _static_fraction(static: list[list[bool]], x0: int, y0: int, x1: int, y1: int) -> float:
    """Proporción de píxeles estáticos dentro de una región."""
    if not static or x1 <= x0 or y1 <= y0:
        return 0.0

    total = 0
    static_count = 0
    for y in range(y0, y1):
        row = static[y]
        for x in range(x0, x1):
            total += 1
            if row[x]:
                static_count += 1

    return static_count / total if total else 0.0


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

    frames = _extract_gray_frames(video_path, count=14)
    if len(frames) < 3:
        return WatermarkReport(error="No se pudieron extraer fotogramas para analizar")

    regions = [_analyze_zone(frames, zone) for zone in CANDIDATE_ZONES]
    regions = [r for r in regions if r.width > 0 and r.height > 0]

    if not regions:
        return WatermarkReport(frames_analyzed=len(frames), error="No se pudieron analizar zonas")

    candidates = [r for r in regions if r.stability > 0.30 and r.score >= threshold]
    candidates.sort(key=lambda r: -r.score)

    report = WatermarkReport(
        detected=bool(candidates),
        confidence=max((r.score for r in candidates), default=0.0),
        regions=candidates,
        frames_analyzed=len(frames),
    )
    return report
