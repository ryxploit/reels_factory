"""
Reels Factory - Settings Module
================================
Persistencia de las preferencias de la aplicación.

Usa `QSettings` (que bajo macOS guarda en `~/Library/Preferences` y bajo
Windows en el registro) para que las opciones del usuario sobrevivan a los
reinicios: modelo de Whisper, idioma, logo, branding, etc.

La implementación cae a un fichero JSON si `QSettings` no está disponible
(por ejemplo al usar los módulos sin la GUI).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config import config

logger = logging.getLogger("settings")

#: Clave de la aplicación para QSettings.
ORG_NAME = "ReelsFactoryPro"
ORG_DOMAIN = "reelsfactorypro"


@dataclass
class AppSettings:
    """Preferencias persistentes de la aplicación."""

    subtitles: bool = True
    whisper_model: str = "base"
    language: str = "auto"
    branding: bool = False
    logo_path: str = ""
    cleanup_intermediates: bool = False
    word_highlight: bool = True
    loudnorm: bool = True
    output_dir: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        """Construye los ajustes ignorando claves desconocidas."""
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        """Convierte los ajustes a diccionario serializable."""
        return asdict(self)


class SettingsStore:
    """Guarda y recupera las preferencias de la aplicación.

    Usa `QSettings` cuando PySide6 está disponible y, si no, un fichero JSON
    en la carpeta de datos.
    """

    def __init__(self, fallback_path: Path | None = None):
        self._fallback_path = fallback_path or (config.paths.BASE_PATH / "temp" / "settings.json")
        self._settings = self._create_qsettings()

    @staticmethod
    def _create_qsettings():
        try:
            from PySide6.QtCore import QSettings

            return QSettings(ORG_NAME, ORG_NAME)
        except Exception as e:  # pragma: no cover - depende del entorno
            logger.info(f"QSettings unavailable ({e}); using JSON fallback.")
            return None

    # ------------------------------------------------------------------
    # Lectura / escritura
    # ------------------------------------------------------------------

    def load(self) -> AppSettings:
        """Carga las preferencias guardadas.

        Returns:
            AppSettings con los valores guardados (o los de por defecto)
        """
        if self._settings is not None:
            try:
                raw = {key: self._settings.value(key) for key in AppSettings.__dataclass_fields__}
                # QSettings devuelve cadenas en algunos backends.
                cleaned: dict[str, Any] = {}
                for key, value in raw.items():
                    if value is None:
                        continue
                    default = getattr(AppSettings(), key)
                    if isinstance(default, bool):
                        cleaned[key] = str(value).lower() in ("1", "true", "yes")
                    else:
                        cleaned[key] = value
                return AppSettings.from_dict(cleaned)
            except Exception as e:
                logger.warning(f"Could not load settings: {e}")
                return AppSettings()

        return self._load_json()

    def save(self, settings: AppSettings) -> bool:
        """Guarda las preferencias.

        Args:
            settings: Ajustes a persistir

        Returns:
            True si se guardaron correctamente
        """
        if self._settings is not None:
            try:
                for key, value in settings.to_dict().items():
                    self._settings.setValue(key, value)
                self._settings.sync()
                return True
            except Exception as e:
                logger.warning(f"Could not save settings: {e}")
                return False

        return self._save_json(settings)

    # ------------------------------------------------------------------
    # Fallback en JSON
    # ------------------------------------------------------------------

    def _load_json(self) -> AppSettings:
        try:
            if self._fallback_path.exists():
                data = json.loads(self._fallback_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return AppSettings.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read settings file: {e}")
        return AppSettings()

    def _save_json(self, settings: AppSettings) -> bool:
        try:
            self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
            self._fallback_path.write_text(
                json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as e:
            logger.warning(f"Could not write settings file: {e}")
            return False
