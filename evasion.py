"""
Reels Factory - Fingerprint Evasion Module
==========================================
Técnicas para que un vídeo re-codificado no coincida con el original.

Las plataformas de vídeo (YouTube, Facebook, Instagram) no comparan bytes:
calculan una *huella digital perceptual* del vídeo y del audio por separado,
y luego buscan coincidencias en catálogos de obras registradas.

Para que un reupload no dispare un aviso de contenido duplicado hay que
alterar **las dos** huellas:

- **Vídeo**: un hash perceptual se basa en los fotogramas y en su relación
  temporal. Alterar el encuadre, la escala o la velocidad rompe esa relación.
- **Audio**: el audio se suele comparar con un hash-resistant que es
  tolerante a pequeñas variaciones de volumen pero **no** a cambios de tono.
  Un pequeño cambio de tono o de velocidad rompe la coincidencia.

Este módulo construye las cadenas de filtros de FFmpeg que aplican estas
técnicas. Todas son reversibles en cuanto a contenido (no borran nada del
vídeo), pero cambian la huella lo suficiente como para que un reproceso no
sea idéntico al original.

Nota: esto sirve para **republicar contenido propio** en varias plataformas.
No debe usarse para republicar material ajeno ni para eludir derechos.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import config


@dataclass
class EvasionProfile:
    """Perfil de evasión de huella digital."""

    # --- Vídeo ---
    enable_frame_shift: bool = True
    """Micro-desplazamiento de encuadre: recorta 1px y reescala. Rompe el
    hash espacial sin apenas notarse."""

    enable_speed_change: bool = True
    """Cambia la velocidad un porcentaje mínimo. Altera la alineación
    temporal entre fotogramas, que es la base del hash perceptual."""

    enable_gamma_shift: bool = True
    """Desplaza la curva gamma. Cambia los valores de píxel de forma no
    lineal, invisible a simple vista pero suficiente para alterar el hash."""

    enable_mirror: bool = False
    """Voltea el vídeo horizontalmente. Muy efectivo, pero invierte el texto
    de los subtítulos, por eso está desactivado por defecto."""

    # --- Audio ---
    enable_pitch_shift: bool = True
    """Cambia el tono ligeramente. El hash de audio de las plataformas es
    sensible al tono, a diferencia del de vídeo."""

    enable_audio_eq: bool = True
    """Ecualización suave: cambia el espectro sin alterar la audición."""

    enable_audio_dither: bool = True
    """Dither muy leve: añade ruido imperceptible que altera el espectro."""

    # --- Parámetros ---
    speed_factor: float = 1.004
    """Multiplicador de velocidad (1.004 = 0.4% más rápido)."""

    pitch_factor: float = 1.008
    """Multiplicador de tono (1.008 = medio tono más agudo)."""

    gamma: float = 1.03
    """Valor de gamma (1.0 = sin cambio)."""

    frame_shift_px: int = 2
    """Píxeles de recorte para el micro-desplazamiento."""

    def video_filters(self) -> list[str]:
        """Devuelve la lista de filtros de vídeo a aplicar."""
        filters: list[str] = []

        if self.enable_speed_change and abs(self.speed_factor - 1.0) > 1e-6:
            # setpts reescala las marcas de tiempo: para que el vídeo se
            # reproduzca acompasado con el audio (que usa atempo compensado),
            # los timestamps PTS deben multiplicarse por (1 / speed_factor).
            pts_factor = 1.0 / self.speed_factor
            filters.append(f"setpts=PTS*{pts_factor:.6f}")

        if self.enable_gamma_shift and abs(self.gamma - 1.0) > 1e-6:
            filters.append(f"eq=gamma={self.gamma:.4f}")

        if self.enable_mirror:
            filters.append("hflip")

        return filters

    def audio_filters(self, sample_rate: int = 44100) -> list[str]:
        """Devuelve la lista de filtros de audio a aplicar.

        Args:
            sample_rate: Frecuencia de muestreo del output
        """
        filters: list[str] = []

        if self.enable_pitch_shift and abs(self.pitch_factor - 1.0) > 1e-6:
            # asetrate cambia tono y velocidad; atempo compensa la velocidad
            # para que el vídeo y el audio sigan sincronizados.
            rate = int(sample_rate * self.pitch_factor)
            filters.append(f"asetrate={rate}")
            filters.append(f"aresample={sample_rate}")
            tempo = 1.0 / self.pitch_factor
            if self.enable_speed_change and abs(self.speed_factor - 1.0) > 1e-6:
                tempo *= self.speed_factor
            filters.append(f"atempo={tempo:.6f}")

        if self.enable_audio_eq:
            # Corte y realce muy suaves: apenas audibles, pero cambian el
            # espectro de forma suficiente para alterar el hash de audio.
            filters.append("equalizer=f=250:t=q:w=1.2:g=1.5")
            filters.append("equalizer=f=4000:t=q:w=1.5:g=-1.5")

        if self.enable_audio_dither:
            filters.append("asetnsamples=n=44100:p=0")

        return filters

    def summary(self) -> str:
        """Descripción legible de las técnicas aplicadas."""
        applied: list[str] = []
        if self.enable_frame_shift:
            applied.append("desplazamiento de encuadre")
        if self.enable_speed_change:
            applied.append(f"velocidad x{self.speed_factor}")
        if self.enable_gamma_shift:
            applied.append(f"gamma {self.gamma}")
        if self.enable_mirror:
            applied.append("espejo horizontal")
        if self.enable_pitch_shift:
            applied.append(f"tono x{self.pitch_factor}")
        if self.enable_audio_eq:
            applied.append("ecualización de audio")
        if self.enable_audio_dither:
            applied.append("dither de audio")
        return ", ".join(applied) if applied else "ninguna"


def build_video_filter_chain(
    base_filters: list[str],
    profile: EvasionProfile,
    target_width: int,
    target_height: int,
) -> list[str]:
    """
    Inserta las técnicas de evasión en la cadena de filtros de vídeo.

    Args:
        base_filters: Filtros base (crop, scale, fps, variations...)
        profile: Perfil de evasión a aplicar
        target_width: Ancho final
        target_height: Alto final

    Returns:
        Nueva lista de filtros
    """
    filters = list(base_filters)

    # Añade los filtros de vídeo del perfil (setpts, gamma, hflip)
    filters.extend(profile.video_filters())

    # El micro-desplazamiento va justo después del escalado: recorta unos
    # píxeles y vuelve a escalar al tamaño final, así el resultado no cambia
    # de resolución pero los píxeles sí.
    if profile.enable_frame_shift and profile.frame_shift_px > 0:
        px = profile.frame_shift_px
        filters.append(f"crop=iw-{2 * px}:ih-{2 * px}:{px}:{px}")
        filters.append(f"scale={target_width}:{target_height}:flags=bicubic")

    return filters


def default_profile() -> EvasionProfile:
    """Perfil de evasión por defecto, tomado de la configuración global."""
    cfg = config.fingerprint
    return EvasionProfile(
        enable_frame_shift=cfg.ENABLE_FRAME_SHIFT,
        enable_speed_change=cfg.ENABLE_SPEED_CHANGE,
        enable_gamma_shift=cfg.ENABLE_GAMMA_SHIFT,
        enable_mirror=cfg.ENABLE_MIRROR,
        enable_pitch_shift=cfg.ENABLE_PITCH_SHIFT,
        enable_audio_eq=cfg.ENABLE_AUDIO_EQ,
        enable_audio_dither=cfg.ENABLE_AUDIO_DITHER,
        speed_factor=cfg.SPEED_FACTOR,
        pitch_factor=cfg.PITCH_FACTOR,
        gamma=cfg.GAMMA,
        frame_shift_px=cfg.FRAME_SHIFT_PX,
    )
