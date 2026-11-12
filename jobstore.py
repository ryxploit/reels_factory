"""
Reels Factory - Job Store Module
=================================
Persistencia de la cola de trabajos.

Guarda el estado de los lotes entre ejecuciones para que un cierre inesperado
de la aplicación no pierda el progreso, y para poder reintentar solo los
trabajos que fallaron.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import config

logger = logging.getLogger("jobstore")

#: Versión del formato del fichero. Se incrementa si cambia la estructura.
STORE_VERSION = 1


@dataclass
class StoredJob:
    """Estado persistido de un trabajo de la cola."""

    url: str
    status: str = "Pendiente"  # Pendiente | En curso | Listo | Falló | Cancelado
    result: str = ""
    title: str = ""
    hashtags: str = ""
    output_path: str = ""
    error_message: str = ""

    @property
    def is_failed(self) -> bool:
        """Indica si el trabajo terminó con error."""
        return self.status == "Falló"

    @property
    def is_done(self) -> bool:
        """Indica si el trabajo ya no necesita reprocesarse."""
        return self.status in ("Listo", "Falló", "Cancelado")


@dataclass
class JobStore:
    """Cola de trabajos persistida en disco.

    El estado se guarda como JSON en `temp/job_queue.json`. Las escrituras son
    atómicas (escritura en fichero temporal + `os.replace`) para evitar que un
    cierre abrupto deje el fichero corrupto.
    """

    path: Path = field(default_factory=lambda: config.paths.TEMP_PATH / "job_queue.json")
    jobs: list[StoredJob] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------
    # Carga / guardado
    # ------------------------------------------------------------------

    def load(self) -> list[StoredJob]:
        """Carga la cola desde disco.

        Returns:
            Lista de trabajos cargados (vacía si no hay fichero o está corrupto)
        """
        with self._lock:
            self.jobs = []
            if not self.path.exists():
                return self.jobs

            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read job store {self.path}: {e}")
                return self.jobs

            if not isinstance(raw, dict) or raw.get("version") != STORE_VERSION:
                logger.warning("Job store has an incompatible format; ignoring it.")
                return self.jobs

            for item in raw.get("jobs", []):
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                known = {f for f in StoredJob.__dataclass_fields__}
                self.jobs.append(StoredJob(**{k: v for k, v in item.items() if k in known}))

            logger.info(f"Loaded {len(self.jobs)} jobs from {self.path}")
            return self.jobs

    def save(self) -> bool:
        """Guarda la cola en disco de forma atómica.

        Returns:
            True si se guardó correctamente
        """
        with self._lock:
            payload = {
                "version": STORE_VERSION,
                "jobs": [asdict(job) for job in self.jobs],
            }

            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(self.path.parent), prefix=".job_queue_", suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(payload, fh, ensure_ascii=False, indent=2)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp_name, self.path)
                except Exception:
                    Path(tmp_name).unlink(missing_ok=True)
                    raise
            except OSError as e:
                logger.warning(f"Could not save job store {self.path}: {e}")
                return False

            return True

    # ------------------------------------------------------------------
    # Operaciones sobre la cola
    # ------------------------------------------------------------------

    def set_jobs(self, jobs: list[StoredJob]) -> None:
        """Reemplaza la cola completa."""
        with self._lock:
            self.jobs = list(jobs)

    def update_job(self, url: str, **fields: Any) -> None:
        """Actualiza los campos de un trabajo y persiste el cambio."""
        with self._lock:
            for job in self.jobs:
                if job.url == url:
                    for key, value in fields.items():
                        if hasattr(job, key):
                            setattr(job, key, value)
                    break
        self.save()

    def failed_jobs(self) -> list[StoredJob]:
        """Devuelve los trabajos que fallaron."""
        with self._lock:
            return [job for job in self.jobs if job.is_failed]

    def retryable_urls(self) -> list[str]:
        """Devuelve las URLs de los trabajos fallidos, listas para reintento."""
        with self._lock:
            return [job.url for job in self.jobs if job.is_failed]

    def pending_urls(self) -> list[str]:
        """Devuelve las URLs de los trabajos pendientes o interrumpidos."""
        with self._lock:
            return [
                job.url for job in self.jobs if job.status in ("Pendiente", "En curso", "Cancelado")
            ]

    def clear(self) -> None:
        """Vacía la cola y borra el fichero de estado."""
        with self._lock:
            self.jobs = []
        self.path.unlink(missing_ok=True)

    def __len__(self) -> int:
        return len(self.jobs)
