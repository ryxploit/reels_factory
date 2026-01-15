#!/usr/bin/env python3
"""ReelsFactoryPro - GUI macOS con PySide6."""

import os
import sys
import threading

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import config
from pipeline import CancelledError, PipelineSettings, ReelsPipeline
from utils import (
    check_ffmpeg_installed,
    check_ffmpeg_subtitles_support,
    check_yt_dlp_installed,
    setup_logger,
    validate_tiktok_url,
)


logger = setup_logger("app", config.paths.LOGS_PATH / "app.log")


@dataclass
class UiJob:
    url: str
    status: str = "Pendiente"
    progress: int = 0
    result: str = ""


class PipelineWorker(QObject):
    log = Signal(str)
    overall = Signal(int, str)
    job_update = Signal(int, str, int)
    job_done = Signal(int, bool, str)
    finished = Signal()

    def __init__(self, urls: list[str], settings: PipelineSettings):
        super().__init__()
        self._urls = urls
        self._settings = settings
        self._cancel_event = threading.Event()
        self._pipeline = ReelsPipeline()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        total = len(self._urls)
        try:
            for idx, url in enumerate(self._urls):
                if self._cancel_event.is_set():
                    self.job_done.emit(idx, False, "Cancelado")
                    break

                self.job_update.emit(idx, "En curso", 0)
                self.log.emit(f"Iniciando job {idx + 1}/{total}")

                def progress_cb(value: int, status: str):
                    self.job_update.emit(idx, status, value)
                    overall = int((((idx + (value / 100.0)) / max(total, 1)) * 100))
                    self.overall.emit(min(100, max(0, overall)), f"{idx + 1}/{total}: {status}")

                def log_cb(message: str):
                    self.log.emit(message)

                try:
                    result = self._pipeline.run_one(
                        url,
                        self._settings,
                        progress=progress_cb,
                        log=log_cb,
                        cancel_event=self._cancel_event,
                    )
                except CancelledError:
                    self.job_done.emit(idx, False, "Cancelado")
                    break
                except Exception as e:
                    self.job_done.emit(idx, False, str(e))
                    break

                if result.success and result.output_path:
                    self.job_done.emit(idx, True, str(result.output_path))
                else:
                    self.job_done.emit(idx, False, result.error_message or "Falló")

                if self._cancel_event.is_set():
                    break

            self.overall.emit(100, "Listo")
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.setMinimumSize(1050, 700)

        self._thread: Optional[QThread] = None
        self._worker: Optional[PipelineWorker] = None
        self._jobs: list[UiJob] = []

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("ReelsFactoryPro")
        if "SF Pro Display" in QFontDatabase.families():
            header.setFont(QFont("SF Pro Display", 22, QFont.Weight.Bold))
        else:
            header.setFont(QFont("", 22, QFont.Weight.Bold))
        layout.addWidget(header)

        deps = self._build_deps_row()
        layout.addWidget(deps)

        top_row = QHBoxLayout()
        layout.addLayout(top_row)

        left = QVBoxLayout()
        top_row.addLayout(left, 2)

        right = QVBoxLayout()
        top_row.addLayout(right, 3)

        left.addWidget(self._build_import_box())
        left.addWidget(self._build_settings_box())
        left.addStretch(1)

        right.addWidget(self._build_jobs_box())
        right.addWidget(self._build_logs_box())

        footer = self._build_footer()
        layout.addWidget(footer)

        self._refresh_deps()

    def _build_deps_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.deps_label = QLabel("Dependencias: verificando...")
        self.deps_label.setStyleSheet("color: #A1A1AA")

        self.open_output_btn = QPushButton("Abrir output")
        self.open_output_btn.clicked.connect(self._open_output)

        row.addWidget(self.deps_label)
        row.addStretch(1)
        row.addWidget(self.open_output_btn)

        return box

    def _build_import_box(self) -> QGroupBox:
        box = QGroupBox("Importar URLs de TikTok")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.urls_text = QTextEdit()
        self.urls_text.setPlaceholderText("Una URL por línea")
        self.urls_text.setMinimumHeight(160)
        layout.addWidget(self.urls_text)

        buttons = QHBoxLayout()
        self.import_file_btn = QPushButton("Importar .txt")
        self.import_file_btn.clicked.connect(self._import_urls_file)
        self.clear_urls_btn = QPushButton("Limpiar")
        self.clear_urls_btn.clicked.connect(self.urls_text.clear)

        buttons.addWidget(self.import_file_btn)
        buttons.addWidget(self.clear_urls_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        return box

    def _build_settings_box(self) -> QGroupBox:
        box = QGroupBox("Opciones")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        self.subtitles_cb = QCheckBox("Generar subtítulos (Whisper)")
        self.subtitles_cb.setChecked(True)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Modelo"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large"]) 
        self.model_combo.setCurrentText("base")
        model_row.addWidget(self.model_combo)
        model_row.addStretch(1)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Idioma"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("auto", userData=None)
        for code in ["es", "en", "pt", "fr", "de", "it"]:
            self.language_combo.addItem(code, userData=code)
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch(1)

        self.branding_cb = QCheckBox("Añadir overlay (logo)")
        self.branding_cb.setChecked(False)

        self.cleanup_cb = QCheckBox("Eliminar temporales al finalizar")
        self.cleanup_cb.setChecked(False)

        logo_row = QHBoxLayout()
        self.logo_path_edit = QLineEdit()
        self.logo_path_edit.setPlaceholderText("Selecciona un PNG con transparencia")
        self.logo_path_edit.setReadOnly(True)
        self.logo_btn = QPushButton("Elegir")
        self.logo_btn.clicked.connect(self._pick_logo)
        logo_row.addWidget(self.logo_path_edit, 1)
        logo_row.addWidget(self.logo_btn)

        layout.addWidget(self.subtitles_cb)
        layout.addLayout(model_row)
        layout.addLayout(lang_row)
        layout.addWidget(self.branding_cb)
        layout.addLayout(logo_row)
        layout.addWidget(self.cleanup_cb)

        self.subtitles_cb.toggled.connect(self._sync_option_states)
        self.branding_cb.toggled.connect(self._sync_option_states)
        self._sync_option_states()

        return box

    def _sync_option_states(self):
        subs_enabled = self.subtitles_cb.isChecked()
        self.model_combo.setEnabled(subs_enabled)
        self.language_combo.setEnabled(subs_enabled)

        branding_enabled = self.branding_cb.isChecked()
        self.logo_btn.setEnabled(branding_enabled)
        self.logo_path_edit.setEnabled(branding_enabled)

    def _build_jobs_box(self) -> QGroupBox:
        box = QGroupBox("Cola")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.jobs_table = QTableWidget(0, 5)
        self.jobs_table.setHorizontalHeaderLabels(["#", "URL", "Estado", "Progreso", "Resultado"])
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs_table.setMinimumHeight(220)
        layout.addWidget(self.jobs_table)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        layout.addWidget(self.overall_bar)

        return box

    def _build_logs_box(self) -> QGroupBox:
        box = QGroupBox("Logs")
        layout = QVBoxLayout(box)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMinimumHeight(180)
        layout.addWidget(self.logs)
        return box

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.start_btn = QPushButton("Iniciar descarga y procesamiento")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)

        row.addWidget(self.start_btn)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)

        return bar

    def _append_log(self, message: str):
        self.logs.append(message)
        logger.info(message)

    def _import_urls_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Importar URLs", str(config.paths.INPUT_PATH), "Text (*.txt)")
        if not file_path:
            return
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        current = self.urls_text.toPlainText().strip()
        merged = (current + "\n" + text).strip() if current else text.strip()
        self.urls_text.setPlainText(merged)

    def _pick_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar logo",
            str(config.paths.ASSETS_PATH),
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if not file_path:
            return
        self.logo_path_edit.setText(file_path)

    def _open_output(self):
        import subprocess

        out = str(config.paths.OUTPUT_PATH)
        if sys.platform.startswith("win"):
            os.startfile(out)
        elif sys.platform == "darwin":
            subprocess.run(["open", out])
        else:
            subprocess.run(["xdg-open", out])

    def _refresh_deps(self):
        ffmpeg_ok, ffmpeg_msg = check_ffmpeg_installed()
        subs_ok, _subs_msg = check_ffmpeg_subtitles_support()
        ytdlp_ok, ytdlp_msg = check_yt_dlp_installed()

        parts = []
        parts.append(f"FFmpeg: {'OK' if ffmpeg_ok else 'FALTA'}")
        parts.append(f"Subtítulos: {'OK' if subs_ok else 'NO'}")
        parts.append(f"yt-dlp: {'OK' if ytdlp_ok else 'FALTA'}")
        if not ffmpeg_ok:
            parts.append(ffmpeg_msg)
        if not ytdlp_ok:
            parts.append(ytdlp_msg)
        self.deps_label.setText(" | ".join(parts))

    def _read_urls(self) -> list[str]:
        raw = self.urls_text.toPlainText().splitlines()
        urls = []
        seen = set()
        for line in raw:
            u = line.strip()
            if not u:
                continue
            if u in seen:
                continue
            seen.add(u)
            urls.append(u)
        return urls

    def _populate_table(self, urls: list[str]):
        self._jobs = [UiJob(url=u) for u in urls]
        self.jobs_table.setRowCount(len(self._jobs))
        for i, job in enumerate(self._jobs):
            self.jobs_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.jobs_table.setItem(i, 1, QTableWidgetItem(job.url))
            self.jobs_table.setItem(i, 2, QTableWidgetItem(job.status))

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            self.jobs_table.setCellWidget(i, 3, bar)

            self.jobs_table.setItem(i, 4, QTableWidgetItem(job.result))

        self.jobs_table.resizeColumnsToContents()

    def _update_job_row(self, row: int, status: str, progress: int):
        if row < 0 or row >= len(self._jobs):
            return
        self._jobs[row].status = status
        self._jobs[row].progress = progress
        status_item = self.jobs_table.item(row, 2)
        if status_item:
            status_item.setText(status)
        bar = self.jobs_table.cellWidget(row, 3)
        if isinstance(bar, QProgressBar):
            bar.setValue(progress)

    def _finish_job_row(self, row: int, ok: bool, message: str):
        if row < 0 or row >= len(self._jobs):
            return
        self._jobs[row].result = message
        res_item = self.jobs_table.item(row, 4)
        if res_item:
            res_item.setText(message)
        self._update_job_row(row, "Listo" if ok else "Falló", 100 if ok else max(self._jobs[row].progress, 0))

    def _start(self):
        self._refresh_deps()
        ffmpeg_ok, _ = check_ffmpeg_installed()
        ytdlp_ok, _ = check_yt_dlp_installed()
        if not ffmpeg_ok or not ytdlp_ok:
            QMessageBox.warning(self, "Dependencias", "Instala FFmpeg y yt-dlp antes de iniciar. Revisa README.md")
            return

        if self.subtitles_cb.isChecked():
            subs_ok, subs_msg = check_ffmpeg_subtitles_support()
            if not subs_ok:
                QMessageBox.warning(self, "Subtítulos", subs_msg)
                return

        urls = self._read_urls()
        if not urls:
            QMessageBox.information(self, "URLs", "Añade al menos una URL")
            return

        invalid = [u for u in urls if not validate_tiktok_url(u)]
        if invalid:
            QMessageBox.warning(self, "URLs inválidas", "Hay URLs inválidas. Corrige y reintenta.")
            return

        logo_path = Path(self.logo_path_edit.text()) if self.logo_path_edit.text().strip() else None
        if self.branding_cb.isChecked() and not (logo_path and logo_path.exists()):
            QMessageBox.warning(self, "Logo", "Activa overlay pero no has seleccionado un archivo válido")
            return

        self._populate_table(urls)
        self.logs.clear()
        self.overall_bar.setValue(0)

        settings = PipelineSettings(
            subtitles=self.subtitles_cb.isChecked(),
            whisper_model=self.model_combo.currentText(),
            branding=self.branding_cb.isChecked(),
            logo_path=logo_path,
            language=self.language_combo.currentData(),
            cleanup_intermediates=self.cleanup_cb.isChecked(),
        )

        self._thread = QThread()
        self._worker = PipelineWorker(urls, settings)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.overall.connect(self._on_overall)
        self._worker.job_update.connect(self._update_job_row)
        self._worker.job_done.connect(self._finish_job_row)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)

        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(lambda: setattr(self, "_thread", None))
        self._thread.finished.connect(lambda: setattr(self, "_worker", None))

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.import_file_btn.setEnabled(False)
        self.clear_urls_btn.setEnabled(False)

        self._thread.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
            self._append_log("Cancelando...")
            self.cancel_btn.setEnabled(False)

    def _on_overall(self, value: int, status: str):
        self.overall_bar.setValue(value)
        self.statusBar().showMessage(status)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.import_file_btn.setEnabled(True)
        self.clear_urls_btn.setEnabled(True)
        self.statusBar().showMessage("Listo")


def main():
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
