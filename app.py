#!/usr/bin/env python3
"""ReelsFactoryPro - GUI macOS con PySide6."""

import os
import sys
import threading

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import config
from jobstore import JobStore, StoredJob
from pipeline import CancelledError, PipelineSettings, ReelsPipeline
from settings import AppSettings, SettingsStore
from subtitles import SubtitleGenerator
from utils import (
    check_ffmpeg_installed,
    check_ffmpeg_subtitles_support,
    check_yt_dlp_installed,
    clear_ffmpeg_filter_cache,
    detect_platform,
    setup_logger,
    validate_video_url,
)

logger = setup_logger("app", config.paths.LOGS_PATH / "app.log")


@dataclass
class UiJob:
    url: str
    status: str = "Pendiente"
    progress: int = 0
    result: str = ""
    title: str = ""
    hashtags: str = ""
    thumbnail_path: str = ""


class PipelineWorker(QObject):
    log = Signal(str)
    overall = Signal(int, str)
    job_update = Signal(int, str, int)
    job_done = Signal(int, bool, str)
    job_meta = Signal(int, str, str)
    job_warning = Signal(int, str)
    job_thumbnail = Signal(int, str)
    job_subtitles = Signal(int, str, list)
    finished = Signal()

    def __init__(
        self,
        urls: list[str],
        settings: PipelineSettings,
        job_store: JobStore | None = None,
    ):
        super().__init__()
        """Inicializa el worker de la pipeline.

        Este objeto se ejecuta en un hilo separado y coordina el procesamiento
        de las URLs recibidas usando `ReelsPipeline`.

        Parámetros:
        - urls: lista de URLs a procesar.
        - settings: instancia de `PipelineSettings` con las opciones.
        - job_store: cola persistente donde se refleja el estado de cada trabajo.
        """
        self._urls = urls
        self._settings = settings
        self._cancel_event = threading.Event()
        self._pipeline = ReelsPipeline()
        self._job_store = job_store

    def cancel(self):
        """Solicita la cancelación segura del proceso en curso.

        Marca un evento interno que la pipeline revisa y usa para abortar
        operaciones de forma ordenada.
        """
        self._cancel_event.set()

    def _persist(self, url: str, **fields) -> None:
        """Actualiza el estado persistido de un trabajo (si hay cola)."""
        if self._job_store is not None:
            self._job_store.update_job(url, **fields)

    def run(self):
        """Ejecuta la pipeline para cada URL.

        Emite señales (`job_update`, `overall`, `log`, `job_done`) que la
        interfaz usa para actualizar la tabla, barra de progreso y logs.
        """
        total = len(self._urls)
        try:
            for idx, url in enumerate(self._urls):
                if self._cancel_event.is_set():
                    self.job_done.emit(idx, False, "Cancelado")
                    self._persist(url, status="Cancelado")
                    break

                self.job_update.emit(idx, "En curso", 0)
                self.log.emit(f"Iniciando job {idx + 1}/{total}")
                self._persist(url, status="En curso")

                def progress_cb(value: int, status: str, idx: int = idx):
                    self.job_update.emit(idx, status, value)
                    overall = int(((idx + (value / 100.0)) / max(total, 1)) * 100)
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
                    self._persist(url, status="Cancelado")
                    break
                except Exception as e:
                    self.job_done.emit(idx, False, str(e))
                    self._persist(url, status="Falló", error_message=str(e))
                    break

                if result.success and result.output_path:
                    self.job_done.emit(idx, True, str(result.output_path))
                    self._persist(
                        url,
                        status="Listo",
                        result=str(result.output_path),
                        output_path=str(result.output_path),
                        error_message="",
                    )
                else:
                    message = result.error_message or "Falló"
                    self.job_done.emit(idx, False, message)
                    self._persist(url, status="Falló", error_message=message)

                for warning in result.warnings or []:
                    self.job_warning.emit(idx, warning)

                if result.thumbnail_path:
                    self.job_thumbnail.emit(idx, str(result.thumbnail_path))

                if result.subtitle_path:
                    self.job_subtitles.emit(idx, str(result.subtitle_path), result.segments or [])

                title = result.title or ""
                hashtags = " ".join(result.hashtags or [])
                if title or hashtags:
                    self.job_meta.emit(idx, title, hashtags)
                    self._persist(url, title=title, hashtags=hashtags)

                if self._cancel_event.is_set():
                    break

            self.overall.emit(100, "Listo")
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        """Construye la ventana principal y la interfaz de usuario.

        Crea todos los widgets, aplica el tema, carga icono/logo y conecta
        las señales necesarias. No inicia procesos hasta que el usuario
        pulse "Iniciar procesamiento".
        """
        self.setWindowTitle(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.setMinimumSize(1100, 780)
        self.setWindowIcon(QIcon(str(config.paths.ASSETS_PATH / "icon.svg")))
        self._apply_theme()

        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None
        self._jobs: list[UiJob] = []
        self._settings_store = SettingsStore()
        self._job_store = JobStore()
        # Segmentos del último trabajo con subtítulos, para exportarlos a SRT.
        self._last_segments: list = []

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = self._build_header()
        layout.addWidget(header)

        deps = self._build_deps_row()
        layout.addWidget(deps)

        # Splitter horizontal para columnas izquierda/derecha
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setChildrenCollapsible(False)

        # Panel izquierdo
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)
        left_layout.addWidget(self._build_import_box())
        left_layout.addWidget(self._build_settings_box())
        left_layout.addStretch(1)

        # Panel derecho
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.addWidget(self._build_jobs_box(), 1)
        right_layout.addWidget(self._build_logs_box(), 2)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([380, 620])

        layout.addWidget(main_splitter, 1)

        footer = self._build_footer()
        layout.addWidget(footer)

        self._load_settings()
        self._refresh_deps()

    def closeEvent(self, event):
        """Guarda las preferencias y la cola antes de cerrar la ventana."""
        self._save_settings()
        self._job_store.save()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Preferencias persistentes
    # ------------------------------------------------------------------

    def _load_settings(self):
        """Restaura las preferencias guardadas en los controles de la GUI."""
        saved = self._settings_store.load()

        self.subtitles_cb.setChecked(saved.subtitles)
        if saved.whisper_model in [
            self.model_combo.itemText(i) for i in range(self.model_combo.count())
        ]:
            self.model_combo.setCurrentText(saved.whisper_model)
        self.language_combo.setCurrentText(saved.language if saved.language else "auto")
        self.branding_cb.setChecked(saved.branding)
        self.cleanup_cb.setChecked(saved.cleanup_intermediates)
        self.word_highlight_cb.setChecked(saved.word_highlight)
        self.loudnorm_cb.setChecked(saved.loudnorm)
        self.evasion_cb.setChecked(saved.evasion)

        if saved.logo_path and Path(saved.logo_path).exists():
            self.logo_path_edit.setText(saved.logo_path)

        self._sync_option_states()

    def _save_settings(self):
        """Guarda el estado actual de los controles como preferencias."""
        settings = AppSettings(
            subtitles=self.subtitles_cb.isChecked(),
            whisper_model=self.model_combo.currentText(),
            language=self.language_combo.currentData() or "auto",
            branding=self.branding_cb.isChecked(),
            logo_path=self.logo_path_edit.text(),
            cleanup_intermediates=self.cleanup_cb.isChecked(),
            word_highlight=self.word_highlight_cb.isChecked(),
            loudnorm=self.loudnorm_cb.isChecked(),
            evasion=self.evasion_cb.isChecked(),
        )
        self._settings_store.save(settings)

    def _apply_theme(self):
        """Aplica el tema oscuro y las reglas de estilo visual.

        Centraliza las `setStyleSheet` para mantener la UI consistente
        sin tocar la disposición o comportamiento de los widgets.
        """
        self.setStyleSheet(
            """
            QWidget {
                background-color: #0A0F1E;
                color: #E5E7EB;
                font-size: 13px;
            }
            QMainWindow {
                background-color: #0A0F1E;
            }
            QLabel[role="muted"] {
                color: #A0AEC0;
            }
            QLabel[role="badge"] {
                background: #111827;
                color: #7DD3FC;
                border: 1px solid #23304A;
                border-radius: 8px;
                padding: 2px 8px;
                font-weight: 600;
            }
            QGroupBox {
                background: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 14px;
                margin-top: 14px;
                padding: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #7DD3FC;
                font-weight: 600;
            }
            QLineEdit, QTextEdit, QComboBox {
                background: #0B1224;
                border: 1px solid #22304A;
                border-radius: 12px;
                padding: 6px 8px;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 1px solid #38BDF8;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QPushButton {
                background: #2563EB;
                border: none;
                border-radius: 12px;
                padding: 8px 14px;
                color: white;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1E40AF;
            }
            QPushButton:disabled {
                background: #334155;
                color: #94A3B8;
            }
            QPushButton#ghost {
                background: #0B1224;
                border: 1px solid #22304A;
                color: #E5E7EB;
            }
            QPushButton#ghost:hover {
                border-color: #38BDF8;
                color: #7DD3FC;
            }
            QProgressBar {
                background: #0B1224;
                border: 1px solid #22304A;
                border-radius: 10px;
                height: 16px;
                text-align: center;
                color: #E5E7EB;
            }
            QProgressBar::chunk {
                background: #38BDF8;
                border-radius: 9px;
            }
            QTableWidget {
                background: #0B1224;
                border: 1px solid #22304A;
                border-radius: 12px;
                gridline-color: #1E293B;
                selection-background-color: #1E293B;
                selection-color: #E5E7EB;
            }
            QHeaderView::section {
                background: #0F172A;
                color: #A0AEC0;
                border: none;
                padding: 6px;
                font-weight: 600;
            }
            QTextEdit {
                background: #0B1224;
            }
            QScrollBar:vertical {
                background: #0B1224;
                width: 10px;
                margin: 2px 2px 2px 2px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #22304A;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #334155;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            """
        )

    def _build_header(self) -> QWidget:
        """Construye y devuelve el header con logo, título y versión.

        El widget resultante se inserta en la parte superior de la ventana.
        """
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        logo = QSvgWidget(str(config.paths.ASSETS_PATH / "logo.svg"))
        logo.setFixedSize(56, 56)

        title_col = QVBoxLayout()
        title = QLabel("ReelsFactoryPro")
        if "SF Pro Display" in QFontDatabase.families():
            title.setFont(QFont("SF Pro Display", 22, QFont.Weight.Bold))
        else:
            title.setFont(QFont("", 22, QFont.Weight.Bold))
        subtitle = QLabel("Descarga, subtitula y publica reels en minutos")
        subtitle.setProperty("role", "muted")

        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        title_col.setSpacing(2)

        badge = QLabel(f"v{config.APP_VERSION}")
        badge.setProperty("role", "badge")

        row.addWidget(logo)
        row.addLayout(title_col)
        row.addStretch(1)
        row.addWidget(badge)

        return bar

    def _build_deps_row(self) -> QWidget:
        """Construye la fila de verificación de dependencias y botón de salida.

        Muestra el estado de FFmpeg, subtítulos y yt-dlp y permite abrir
        la carpeta de `output`.
        """
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.deps_label = QLabel("Dependencias: verificando...")
        self.deps_label.setStyleSheet("color: #A1A1AA")
        self.deps_label.setToolTip("Estado de las dependencias necesarias.")

        self.open_output_btn = QPushButton("Abrir output")
        self.open_output_btn.setObjectName("ghost")
        self.open_output_btn.setToolTip("Abre la carpeta donde se guardan los resultados.")
        self.open_output_btn.clicked.connect(self._open_output)

        row.addWidget(self.deps_label)
        row.addStretch(1)
        row.addWidget(self.open_output_btn)

        return box

    def _build_import_box(self) -> QGroupBox:
        """Construye el área para importar o pegar URLs.

        Incluye el `QTextEdit` para pegar URLs y botones para importar
        desde archivo o limpiar el contenido.
        """
        box = QGroupBox("Importar URLs de TikTok")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.urls_text = QTextEdit()
        self.urls_text.setPlaceholderText("Una URL por línea")
        self.urls_text.setMinimumHeight(160)
        self.urls_text.setToolTip("Pega aquí las URLs que quieres procesar, una por línea.")
        layout.addWidget(self.urls_text)

        buttons = QHBoxLayout()
        self.import_file_btn = QPushButton("Importar .txt")
        self.import_file_btn.setObjectName("ghost")
        self.import_file_btn.setToolTip("Carga un archivo .txt con una URL por línea.")
        self.import_file_btn.clicked.connect(self._import_urls_file)
        self.clear_urls_btn = QPushButton("Limpiar")
        self.clear_urls_btn.setObjectName("ghost")
        self.clear_urls_btn.setToolTip("Borra todas las URLs del cuadro de texto.")
        self.clear_urls_btn.clicked.connect(self.urls_text.clear)

        buttons.addWidget(self.import_file_btn)
        buttons.addWidget(self.clear_urls_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        return box

    def _build_settings_box(self) -> QGroupBox:
        """Construye el panel de opciones de procesamiento.

        Aquí el usuario puede activar subtítulos, seleccionar modelo e idioma,
        añadir branding (logo) y decidir si limpiar temporales.
        """
        box = QGroupBox("Opciones")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        self.subtitles_cb = QCheckBox("Generar subtítulos (Whisper)")
        self.subtitles_cb.setChecked(True)
        self.subtitles_cb.setToolTip("Activa la generación automática de subtítulos con Whisper.")

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Modelo"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(list(config.subtitle.AVAILABLE_MODELS))
        self.model_combo.setCurrentText(config.subtitle.MODEL_SIZE)
        self.model_combo.setToolTip(
            "Tamaño del modelo de transcripción. "
            "'turbo' y 'large-v3-turbo' son tan precisos como 'large-v3' pero mucho más rápidos."
        )
        model_row.addWidget(self.model_combo)
        model_row.addStretch(1)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Idioma"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("auto", userData=None)
        for code in ["es", "en", "pt", "fr", "de", "it"]:
            self.language_combo.addItem(code, userData=code)
        self.language_combo.setToolTip("Define el idioma del audio o usa auto para detectar.")
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch(1)

        self.word_highlight_cb = QCheckBox("Resaltar palabra activa")
        self.word_highlight_cb.setChecked(config.subtitle.ENABLE_WORD_HIGHLIGHT)
        self.word_highlight_cb.setToolTip(
            "Estilo TikTok/Shorts: la palabra que se pronuncia se resalta y agranda."
        )

        self.loudnorm_cb = QCheckBox("Normalizar audio (-14 LUFS)")
        self.loudnorm_cb.setChecked(config.video.ENABLE_LOUDNORM)
        self.loudnorm_cb.setToolTip(
            "Iguala el volumen al estándar de Facebook/TikTok para evitar penalizaciones."
        )

        self.evasion_cb = QCheckBox("Evasión de huella digital")
        self.evasion_cb.setChecked(config.fingerprint.ENABLE_FRAME_SHIFT)
        self.evasion_cb.setToolTip(
            "Altera la huella perceptual del vídeo y del audio para que un "
            "reupload no coincida con el original. Úsalo al republicar tu "
            "propio contenido en varias plataformas."
        )

        self.analyze_btn = QPushButton("Analizar marca de agua")
        self.analyze_btn.setObjectName("ghost")
        self.analyze_btn.setToolTip(
            "Analiza el vídeo descargado en busca de marcas de agua incrustadas "
            "en los píxeles (no en los metadatos)."
        )
        self.analyze_btn.clicked.connect(self._analyze_watermark)
        analyze_row = QHBoxLayout()
        analyze_row.addWidget(self.evasion_cb)
        analyze_row.addStretch(1)
        analyze_row.addWidget(self.analyze_btn)

        self.branding_cb = QCheckBox("Añadir overlay (logo)")
        self.branding_cb.setChecked(False)
        self.branding_cb.setToolTip("Coloca tu logo como overlay en el video final.")

        self.cleanup_cb = QCheckBox("Eliminar temporales al finalizar")
        self.cleanup_cb.setChecked(False)
        self.cleanup_cb.setToolTip("Elimina archivos temporales al terminar para ahorrar espacio.")

        logo_row = QHBoxLayout()
        self.logo_path_edit = QLineEdit()
        self.logo_path_edit.setPlaceholderText("Selecciona un PNG con transparencia")
        self.logo_path_edit.setReadOnly(True)
        self.logo_path_edit.setToolTip("Ruta del logo que se usará como overlay.")
        self.logo_btn = QPushButton("Elegir")
        self.logo_btn.setToolTip("Selecciona el archivo de logo para el overlay.")
        self.logo_btn.clicked.connect(self._pick_logo)
        logo_row.addWidget(self.logo_path_edit, 1)
        logo_row.addWidget(self.logo_btn)

        layout.addWidget(self.subtitles_cb)
        layout.addLayout(model_row)
        layout.addLayout(lang_row)
        layout.addWidget(self.word_highlight_cb)
        layout.addWidget(self.loudnorm_cb)
        layout.addLayout(analyze_row)
        layout.addWidget(self.branding_cb)
        layout.addLayout(logo_row)
        layout.addWidget(self.cleanup_cb)

        self.subtitles_cb.toggled.connect(self._sync_option_states)
        self.branding_cb.toggled.connect(self._sync_option_states)
        self._sync_option_states()

        return box

    def _sync_option_states(self):
        """Sincroniza el estado de los controles dependientes.

        Habilita/deshabilita controles como selección de modelo o boton de logo
        según las casillas activadas para evitar entradas inválidas.
        """
        subs_enabled = self.subtitles_cb.isChecked()
        self.model_combo.setEnabled(subs_enabled)
        self.language_combo.setEnabled(subs_enabled)
        self.word_highlight_cb.setEnabled(subs_enabled)

        branding_enabled = self.branding_cb.isChecked()
        self.logo_btn.setEnabled(branding_enabled)
        self.logo_path_edit.setEnabled(branding_enabled)

    def _build_jobs_box(self) -> QGroupBox:
        """Construye la tabla que muestra la cola de trabajo y progreso global.

        La tabla contiene columnas para índice, URL, estado, progreso,
        miniatura y resultado.
        """
        box = QGroupBox("Cola")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.jobs_table = QTableWidget(0, 6)
        self.jobs_table.setHorizontalHeaderLabels(
            ["#", "URL", "Estado", "Progreso", "Vista", "Resultado"]
        )
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs_table.setAlternatingRowColors(True)
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setMinimumHeight(200)
        self.jobs_table.setMaximumHeight(300)
        self.jobs_table.setIconSize(QPixmap(54, 96).size())
        self.jobs_table.setShowGrid(True)
        self.jobs_table.setToolTip("Muestra la cola de trabajos con su estado y resultado.")
        self.jobs_table.itemSelectionChanged.connect(self._on_job_selected)
        self.jobs_table.cellDoubleClicked.connect(self._on_job_double_clicked)
        layout.addWidget(self.jobs_table)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setToolTip("Progreso global del procesamiento.")
        layout.addWidget(self.overall_bar)

        return box

    def _apply_column_widths(self):
        """Fija los anchos de columna.

        Debe llamarse DESPUÉS de poblar la tabla: `resizeColumnsToContents()`
        sobrescribe los anchos manuales.
        """
        self.jobs_table.setColumnWidth(0, 40)
        self.jobs_table.setColumnWidth(2, 120)
        self.jobs_table.setColumnWidth(3, 120)
        self.jobs_table.setColumnWidth(4, 70)

    def _build_logs_box(self) -> QGroupBox:
        """Construye el área de logs donde se muestran mensajes de proceso."""
        box = QGroupBox("Logs y Metadatos")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 20, 14, 14)

        # === METADATOS ===
        meta_header = QLabel("📋 Metadatos del Video")
        meta_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #7DD3FC;")
        layout.addWidget(meta_header)

        # Título - una fila simple
        title_container = QHBoxLayout()
        title_container.setSpacing(8)
        title_lbl = QLabel("Título:")
        title_lbl.setFixedWidth(60)
        title_lbl.setStyleSheet("color: #94A3B8;")
        self.title_edit = QLineEdit()
        self.title_edit.setReadOnly(True)
        self.title_edit.setPlaceholderText("Título del video")
        self.copy_title_btn = QPushButton("Copiar")
        self.copy_title_btn.setObjectName("ghost")
        self.copy_title_btn.setFixedSize(70, 32)
        self.copy_title_btn.clicked.connect(lambda: self._copy_to_clipboard(self.title_edit.text()))
        title_container.addWidget(title_lbl)
        title_container.addWidget(self.title_edit, 1)
        title_container.addWidget(self.copy_title_btn)
        layout.addLayout(title_container)

        # Hashtags - una fila simple
        tags_container = QHBoxLayout()
        tags_container.setSpacing(8)
        tags_lbl = QLabel("Tags:")
        tags_lbl.setFixedWidth(60)
        tags_lbl.setStyleSheet("color: #94A3B8;")
        self.hashtags_edit = QLineEdit()
        self.hashtags_edit.setReadOnly(True)
        self.hashtags_edit.setPlaceholderText("Hashtags del video")
        self.copy_tags_btn = QPushButton("Copiar")
        self.copy_tags_btn.setObjectName("ghost")
        self.copy_tags_btn.setFixedSize(70, 32)
        self.copy_tags_btn.clicked.connect(
            lambda: self._copy_to_clipboard(self.hashtags_edit.text())
        )
        self.copy_all_btn = QPushButton("Todo")
        self.copy_all_btn.setObjectName("ghost")
        self.copy_all_btn.setFixedSize(60, 32)
        self.copy_all_btn.clicked.connect(self._copy_all_metadata)
        tags_container.addWidget(tags_lbl)
        tags_container.addWidget(self.hashtags_edit, 1)
        tags_container.addWidget(self.copy_tags_btn)
        tags_container.addWidget(self.copy_all_btn)
        layout.addLayout(tags_container)

        # Subtítulos - exportar SRT del último trabajo procesado
        subs_container = QHBoxLayout()
        subs_container.setSpacing(8)
        subs_lbl = QLabel("Subtítulos:")
        subs_lbl.setFixedWidth(60)
        subs_lbl.setStyleSheet("color: #94A3B8;")
        self.subs_edit = QLineEdit()
        self.subs_edit.setReadOnly(True)
        self.subs_edit.setPlaceholderText("Ruta del archivo .ass")
        self.copy_subs_btn = QPushButton("Copiar")
        self.copy_subs_btn.setObjectName("ghost")
        self.copy_subs_btn.setFixedSize(70, 32)
        self.copy_subs_btn.setToolTip("Copia el texto de los subtítulos al portapapeles.")
        self.copy_subs_btn.clicked.connect(lambda: self._copy_to_clipboard(self.subs_edit.text()))
        self.export_srt_btn = QPushButton("Exportar SRT")
        self.export_srt_btn.setObjectName("ghost")
        self.export_srt_btn.setFixedSize(100, 32)
        self.export_srt_btn.setToolTip(
            "Exporta los subtítulos del último trabajo a formato SRT (para YouTube, etc.)."
        )
        self.export_srt_btn.clicked.connect(self._export_srt)
        subs_container.addWidget(subs_lbl)
        subs_container.addWidget(self.subs_edit, 1)
        subs_container.addWidget(self.copy_subs_btn)
        subs_container.addWidget(self.export_srt_btn)
        layout.addLayout(subs_container)

        # Separador
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #1E293B;")
        layout.addWidget(sep)

        # === LOGS ===
        logs_header = QLabel("📝 Registro de Actividad")
        logs_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #7DD3FC;")
        layout.addWidget(logs_header)

        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMinimumHeight(100)
        layout.addWidget(self.logs, 1)

        return box

    def _build_footer(self) -> QWidget:
        """Construye el footer con botones de iniciar, cancelar y reintentar.

        Contiene los controles principales para comenzar o detener la ejecución,
        además de la acción para reintentar solo los trabajos fallidos.
        """
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.start_btn = QPushButton("Iniciar procesamiento")
        self.start_btn.setToolTip("Inicia la descarga y el procesamiento de las URLs.")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.setToolTip("Detiene el proceso en curso de forma segura.")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)

        self.retry_btn = QPushButton("Reintentar fallidos")
        self.retry_btn.setObjectName("ghost")
        self.retry_btn.setToolTip("Vuelve a procesar únicamente los trabajos que fallaron.")
        self.retry_btn.clicked.connect(self._retry_failed)
        self.retry_btn.setEnabled(False)

        row.addWidget(self.start_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.retry_btn)
        row.addStretch(1)

        return bar

    def _retry_failed(self):
        """Reintenta únicamente los trabajos fallidos de la última cola."""
        self._job_store.load()
        urls = self._job_store.retryable_urls()
        if not urls:
            QMessageBox.information(self, "Reintentar", "No hay trabajos fallidos que reintentar.")
            return

        # Sustituye las URLs fallidas en el textarea y lanza el proceso.
        current = self._read_urls()
        merged = [u for u in current if u not in urls] + urls
        self.urls_text.setPlainText("\n".join(merged))
        self._append_log(f"Reintentando {len(urls)} trabajo(s) fallido(s)...")
        self._start()

    def _update_retry_button(self):
        """Habilita el botón de reintento si hay trabajos fallidos."""
        self._job_store.load()
        self.retry_btn.setEnabled(bool(self._job_store.failed_jobs()))

    def _append_log(self, message: str):
        """Añade una línea al registro y la escribe en el logger.

        Mensajes de estado y errores se registran aquí para diagnóstico.
        """
        self.logs.append(message)
        logger.info(message)

    def _analyze_watermark(self):
        """Analiza en busca de marcas de agua incrustadas en los píxeles.

        Solo analiza el vídeo ya descargado más reciente. Si no hay ninguno,
        avisa de que primero hay que procesar.
        """
        downloaded = sorted(
            config.paths.DOWNLOADS_PATH.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not downloaded:
            QMessageBox.information(
                self,
                "Analizar marca de agua",
                "No hay vídeos descargados todavía.\n\n"
                "Descarga primero un vídeo (procesa una URL) y vuelve a pulsar "
                "este botón para analizarlo.",
            )
            return

        video = downloaded[0]
        self._append_log(f"Analizando {video.name} en busca de marca de agua...")

        from watermark import detect_watermark

        report = detect_watermark(video, threshold=config.fingerprint.WATERMARK_THRESHOLD)

        if report.error:
            self._append_log(f"Análisis no disponible: {report.error}")
            QMessageBox.warning(self, "Analizar marca de agua", report.summary)
            return

        if report.detected:
            self._append_log(f"⚠️  {report.summary}")
            self._show_watermark_preview(report)
        else:
            self._append_log(f"✓ {report.summary}")
            QMessageBox.information(
                self,
                "Análisis completado",
                f"{report.summary}\n\n(Se analizaron {report.frames_analyzed} fotogramas)\n\n"
                "Recuerda revisar el primer fotograma: si el vídeo traía el logo "
                "de la plataforma original grabado, conviene cubrirlo con tu overlay.",
            )

    def _show_watermark_preview(self, report):
        """Muestra el fotograma con la zona sospechosa resaltada.

        La detección es heurística: una interfaz estática de una app o el
        borde de un filtro tienen la misma firma temporal que un logo
        grabado. Por eso se muestra la imagen para que el usuario confirme
        de un vistazo.
        """
        from PySide6.QtGui import QPixmap

        dialog = QDialog(self)
        dialog.setWindowTitle("Posible marca de agua")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        info = QLabel(
            f"{report.summary}\n\n"
            "Comprueba la zona marcada: si es el logo de la plataforma "
            "original, queda grabada en los píxeles y solo puedes cubrirla "
            "con tu propio overlay."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        if report.preview_path and Path(report.preview_path).exists():
            label = QLabel()
            pixmap = QPixmap(str(report.preview_path))
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        420,
                        720,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            layout.addWidget(label)

        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

    def _copy_to_clipboard(self, text: str):
        """Copia texto al portapapeles y muestra estado."""
        if text is None:
            text = ""
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copiado al portapapeles", 2000)

    def _copy_all_metadata(self):
        """Copia título y hashtags al portapapeles."""
        title = self.title_edit.text().strip()
        tags = self.hashtags_edit.text().strip()
        combined = "\n".join([p for p in [title, tags] if p])
        self._copy_to_clipboard(combined)

    def _export_srt(self):
        """Exporta los subtítulos del último trabajo a un fichero SRT.

        No requiere volver a transcribir: reutiliza los segmentos ya generados.
        """
        if not self._last_segments:
            QMessageBox.information(
                self,
                "Exportar SRT",
                "No hay subtítulos en memoria. Ejecuta primero un trabajo con subtítulos.",
            )
            return

        base = self.subs_edit.text().strip() or "subtitulos"
        stem = Path(base).stem or "subtitulos"

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar SRT", str(config.paths.OUTPUT_PATH / f"{stem}.srt"), "Subtitles (*.srt)"
        )
        if not file_path:
            return

        generator = SubtitleGenerator(config.paths.SUBTITLES_PATH)
        written = generator.export_srt(self._last_segments, Path(file_path).name)
        if written:
            self._append_log(f"SRT exportado: {written}")
            self.statusBar().showMessage(f"SRT exportado: {written.name}", 4000)
        else:
            QMessageBox.warning(self, "Exportar SRT", "No se pudo escribir el fichero SRT.")

    def _set_metadata_fields(self, title: str, hashtags: str):
        """Actualiza los campos de metadatos en la UI."""
        self.title_edit.setText(title or "")
        self.hashtags_edit.setText(hashtags or "")

    def _import_urls_file(self):
        """Permite seleccionar un archivo .txt y añade sus URLs al textarea.

        Leerá el contenido como texto plano y lo añadirá al campo existente.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Importar URLs", str(config.paths.INPUT_PATH), "Text (*.txt)"
        )
        if not file_path:
            return
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        current = self.urls_text.toPlainText().strip()
        merged = (current + "\n" + text).strip() if current else text.strip()
        self.urls_text.setPlainText(merged)

    def _pick_logo(self):
        """Abre un diálogo para seleccionar un archivo de imagen (logo).

        La ruta seleccionada se coloca en el `QLineEdit` correspondiente.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar logo",
            str(config.paths.ASSETS_PATH),
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not file_path:
            return
        self.logo_path_edit.setText(file_path)

    def _open_output(self):
        """Abre la carpeta `output` en el explorador del sistema.

        Usa el comando nativo según la plataforma (open, xdg-open, start).
        """
        import subprocess

        out = str(config.paths.OUTPUT_PATH)
        if sys.platform.startswith("win"):
            os.startfile(out)
        elif sys.platform == "darwin":
            subprocess.run(["open", out])
        else:
            subprocess.run(["xdg-open", out])

    def _refresh_deps(self, prompt_if_missing: bool = True):
        """Verifica si las dependencias externas están disponibles.

        Comprueba FFmpeg, soporte de subtítulos y yt-dlp y actualiza la etiqueta.

        Args:
            prompt_if_missing: Si es True, muestra el diálogo de resolución
                cuando faltan dependencias.
        """
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

        # Si faltan dependencias, ofrecer un diálogo UI para resolverlo
        if prompt_if_missing and (not ffmpeg_ok or not ytdlp_ok):
            from PySide6.QtCore import QTimer

            QTimer.singleShot(
                250,
                lambda: self._show_missing_deps_dialog(
                    ffmpeg_ok, ffmpeg_msg, subs_ok, ytdlp_ok, ytdlp_msg
                ),
            )

    def _show_missing_deps_dialog(
        self,
        ffmpeg_ok: bool,
        ffmpeg_msg: str,
        subs_ok: bool,
        ytdlp_ok: bool,
        ytdlp_msg: str,
        start_on_success: bool = False,
    ):
        """Muestra un diálogo modal para resolver dependencias sin terminal.

        Permite seleccionar un binario de FFmpeg o intentar instalar `yt-dlp`
        desde la interfaz. Las acciones se realizan en segundo plano y la
        interfaz se actualiza al terminar.
        """
        import subprocess
        import sys
        import threading
        import webbrowser

        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QGridLayout,
            QLabel,
            QProgressBar,
            QTextEdit,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Dependencias faltantes")
        dialog.setModal(True)
        layout = QGridLayout(dialog)

        info = QTextEdit()
        info.setReadOnly(True)
        msg_lines = []
        msg_lines.append(f"FFmpeg: {'OK' if ffmpeg_ok else 'FALTA'} - {ffmpeg_msg}")
        msg_lines.append(f"Subtítulos: {'OK' if subs_ok else 'NO'}")
        msg_lines.append(f"yt-dlp: {'OK' if ytdlp_ok else 'FALTA'} - {ytdlp_msg}")
        info.setPlainText("\n".join(msg_lines))

        lbl = QLabel("Selecciona una acción (no se necesita terminal):")

        buttons = QDialogButtonBox()
        select_ffmpeg_btn = buttons.addButton("Seleccionar FFmpeg...", QDialogButtonBox.ActionRole)
        install_ffmpeg_btn = buttons.addButton("Instalar ffmpeg-full", QDialogButtonBox.ActionRole)
        install_ytdlp_btn = buttons.addButton("Instalar yt-dlp", QDialogButtonBox.ActionRole)
        gen_icons_btn = buttons.addButton("Generar iconos", QDialogButtonBox.ActionRole)
        instructions_btn = buttons.addButton("Mostrar instrucciones", QDialogButtonBox.HelpRole)
        close_btn = buttons.addButton(QDialogButtonBox.Close)

        layout.addWidget(lbl, 0, 0)
        layout.addWidget(info, 1, 0)
        layout.addWidget(buttons, 2, 0)

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setVisible(False)
        layout.addWidget(progress, 3, 0)

        def select_ffmpeg():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Seleccionar ffmpeg",
                str(config.paths.BASE_PATH),
                "Executable (ffmpeg*);;All Files (*)",
            )
            if not path:
                return
            # Ofrecer copiar el binario a third_party para empaquetado
            from PySide6.QtWidgets import QMessageBox

            copy_choice = QMessageBox.question(
                self,
                "Copiar ffmpeg",
                "¿Copiar el binario seleccionado a third_party/ffmpeg/bin para uso interno y empaquetado?",
                QMessageBox.Yes | QMessageBox.No,
            )
            try:
                if copy_choice == QMessageBox.Yes:
                    import shutil

                    dest_dir = config.paths.BASE_PATH / "third_party" / "ffmpeg" / "bin"
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    # Nombre destino sin extensión en mac/linux
                    dest_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
                    dest_path = dest_dir / dest_name
                    shutil.copy2(path, str(dest_path))
                    # Asegurar permisos ejecutables
                    try:
                        os.chmod(dest_path, 0o755)
                    except Exception:
                        pass
                    os.environ["REELSFACTORYPRO_FFMPEG"] = str(dest_path)
                    self._append_log(f"FFmpeg copiado a: {dest_path}")
                else:
                    os.environ["REELSFACTORYPRO_FFMPEG"] = path
                    self._append_log(f"FFmpeg seleccionado: {path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo copiar el binario: {e}")
                os.environ["REELSFACTORYPRO_FFMPEG"] = path
                self._append_log(f"FFmpeg seleccionado: {path} (no copiado)")

            # El binario cambió: la caché de filtros debe invalidarse.
            clear_ffmpeg_filter_cache()
            self._refresh_deps()
            dialog.accept()

        def install_ytdlp():
            install_ytdlp_btn.setEnabled(False)
            progress.setVisible(True)
            info.append("Iniciando instalación de yt-dlp...\n")

            def run_install():
                try:
                    # Ejecutar pip e ir capturando salida en tiempo real
                    proc = subprocess.Popen(
                        [sys.executable, "-m", "pip", "install", "yt-dlp"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    if proc.stdout:
                        for line in proc.stdout:
                            stripped = line.rstrip("\n")

                            def append_line(text=stripped):
                                info.append(text)

                            from PySide6.QtCore import QTimer

                            QTimer.singleShot(0, append_line)
                    proc.wait()
                    ret = proc.returncode
                    self._append_log("Instalación yt-dlp: " + ("OK" if ret == 0 else "FALLÓ"))

                    def on_done():
                        progress.setVisible(False)
                        install_ytdlp_btn.setEnabled(True)
                        if ret == 0:
                            QMessageBox.information(
                                self, "Instalación", "yt-dlp instalado correctamente."
                            )
                        else:
                            QMessageBox.warning(
                                self,
                                "Instalación",
                                f"Error al instalar yt-dlp (código {ret}). Revisa el log arriba.",
                            )
                        self._refresh_deps()

                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(100, on_done)
                except Exception as e:
                    self._append_log(f"Error instalación yt-dlp: {e}")
                    from PySide6.QtCore import QTimer

                    # `e` se elimina al salir del bloque except: se captura el valor.
                    err_msg = str(e)
                    QTimer.singleShot(
                        100, lambda: QMessageBox.warning(self, "Instalación", err_msg)
                    )
                return

            t = threading.Thread(target=run_install, daemon=True)
            t.start()

        def install_ffmpeg_full():
            if sys.platform != "darwin":
                QMessageBox.information(
                    self, "FFmpeg", "La instalación automática solo está disponible en macOS."
                )
                return
            install_ffmpeg_btn.setEnabled(False)
            progress.setVisible(True)
            info.append("Instalando ffmpeg-full con Homebrew...\n")

            def run_install():
                try:
                    import shutil

                    brew = shutil.which("brew")
                    if not brew:
                        for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
                            if Path(candidate).exists():
                                brew = candidate
                                break
                    if not brew:
                        raise RuntimeError(
                            "Homebrew no encontrado. Instálalo desde https://brew.sh"
                        )

                    proc = subprocess.Popen(
                        [brew, "install", "ffmpeg-full"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    if proc.stdout:
                        for line in proc.stdout:
                            text = line.rstrip("\n")
                            from PySide6.QtCore import QTimer

                            QTimer.singleShot(0, lambda txt=text: info.append(txt))
                    proc.wait()

                    # Asegurar PATH del ffmpeg-full instalado
                    prefix = subprocess.run(
                        [brew, "--prefix", "ffmpeg-full"], capture_output=True, text=True
                    )
                    if prefix.returncode == 0:
                        pref = prefix.stdout.strip()
                        if pref:
                            os.environ["PATH"] = f"{pref}/bin:" + os.environ.get("PATH", "")

                    def on_done():
                        progress.setVisible(False)
                        install_ffmpeg_btn.setEnabled(True)
                        if proc.returncode == 0:
                            QMessageBox.information(
                                self, "FFmpeg", "ffmpeg-full instalado correctamente."
                            )
                        else:
                            QMessageBox.warning(
                                self, "FFmpeg", "Error al instalar ffmpeg-full. Revisa el log."
                            )
                        self._refresh_deps()

                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(100, on_done)
                except Exception as e:
                    from PySide6.QtCore import QTimer

                    err_msg = str(e)
                    QTimer.singleShot(
                        0, lambda: info.append(f"Error instalando ffmpeg-full: {err_msg}\n")
                    )
                    QTimer.singleShot(
                        100,
                        lambda: (progress.setVisible(False), install_ffmpeg_btn.setEnabled(True)),
                    )

            t = threading.Thread(target=run_install, daemon=True)
            t.start()

        def generate_icons():
            install_btn = gen_icons_btn
            install_btn.setEnabled(False)
            progress.setVisible(True)
            info.append("Iniciando generación de iconos desde assets/icon.svg...\n")

            def run_gen():
                try:
                    try:
                        import cairosvg
                    except Exception:
                        # intentar instalar cairosvg
                        info.append("cairosvg no encontrado, instalando...\n")
                        proc = subprocess.Popen(
                            [sys.executable, "-m", "pip", "install", "cairosvg"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                        if proc.stdout:
                            for line in proc.stdout:
                                text = line.rstrip("\n")
                                from PySide6.QtCore import QTimer

                                QTimer.singleShot(0, lambda txt=text: info.append(txt))
                        proc.wait()
                        if proc.returncode != 0:
                            raise RuntimeError("Fallo instalando cairosvg") from None
                        import importlib

                        cairosvg = importlib.import_module("cairosvg")

                    sizes = [16, 32, 64, 128, 256, 512, 1024]
                    src = config.paths.ASSETS_PATH / "icon.svg"
                    out_dir = config.paths.ASSETS_PATH / "generated_icons"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    for s in sizes:
                        out_file = out_dir / f"icon_{s}x{s}.png"
                        cairosvg.svg2png(
                            url=str(src), write_to=str(out_file), output_width=s, output_height=s
                        )
                        from PySide6.QtCore import QTimer

                        QTimer.singleShot(0, lambda txt=f"Generado: {out_file}": info.append(txt))

                    # Crear .iconset para macOS
                    iconset = out_dir / "App.iconset"
                    iconset.mkdir(parents=True, exist_ok=True)

                    def cp(srcp, dstp):
                        try:
                            import shutil

                            shutil.copy2(str(srcp), str(dstp))
                        except Exception:
                            pass

                    cp(out_dir / "icon_16x16.png", iconset / "icon_16x16.png")
                    cp(out_dir / "icon_32x32.png", iconset / "icon_16x16@2x.png")
                    cp(out_dir / "icon_32x32.png", iconset / "icon_32x32.png")
                    cp(out_dir / "icon_64x64.png", iconset / "icon_32x32@2x.png")
                    cp(out_dir / "icon_128x128.png", iconset / "icon_128x128.png")
                    cp(out_dir / "icon_256x256.png", iconset / "icon_128x128@2x.png")
                    cp(out_dir / "icon_256x256.png", iconset / "icon_256x256.png")
                    cp(out_dir / "icon_512x512.png", iconset / "icon_256x256@2x.png")
                    cp(out_dir / "icon_512x512.png", iconset / "icon_512x512.png")
                    cp(out_dir / "icon_1024x1024.png", iconset / "icon_512x512@2x.png")

                    # Intentar crear .icns con iconutil (solo mac)
                    icns_path = out_dir / "App.icns"
                    try:
                        if sys.platform == "darwin":
                            subprocess.run(
                                ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
                                check=True,
                            )
                            from PySide6.QtCore import QTimer

                            QTimer.singleShot(0, lambda: info.append(f"ICNS creado: {icns_path}\n"))
                    except Exception:
                        from PySide6.QtCore import QTimer

                        QTimer.singleShot(
                            0,
                            lambda: info.append(
                                "No se pudo generar .icns (iconutil no disponible).\n"
                            ),
                        )

                    # Intentar generar .ico para Windows usando Pillow
                    try:
                        try:
                            from PIL import Image
                        except Exception:
                            info.append("Pillow no encontrado, instalando...\n")
                            proc = subprocess.Popen(
                                [sys.executable, "-m", "pip", "install", "Pillow"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                            )
                            if proc.stdout:
                                for line in proc.stdout:
                                    text = line.rstrip("\n")
                                    from PySide6.QtCore import QTimer

                                    QTimer.singleShot(0, lambda txt=text: info.append(txt))
                            proc.wait()
                            if proc.returncode != 0:
                                raise RuntimeError("Fallo instalando Pillow") from None
                            from PIL import Image

                        # Cargar varias resoluciones y guardar .ico
                        ico_path = out_dir / "icon.ico"
                        sizes = [256, 128, 64, 32, 16]
                        images = []
                        for s in sizes:
                            p = out_dir / f"icon_{s}x{s}.png"
                            if p.exists():
                                images.append(Image.open(str(p)).convert("RGBA"))
                        if images:
                            # Guardar el mayor con tamaños adicionales
                            images[0].save(
                                str(ico_path), format="ICO", sizes=[(s, s) for s in sizes]
                            )
                            from PySide6.QtCore import QTimer

                            QTimer.singleShot(0, lambda: info.append(f"ICO creado: {ico_path}\n"))
                    except Exception:
                        from PySide6.QtCore import QTimer

                        QTimer.singleShot(0, lambda: info.append("No se pudo generar .ico.\n"))

                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(0, lambda: info.append("Generación de iconos finalizada.\n"))
                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(
                        100,
                        lambda: (
                            progress.setVisible(False),
                            install_btn.setEnabled(True),
                            self._append_log("Iconos generados"),
                        ),
                    )
                except Exception as e:
                    from PySide6.QtCore import QTimer

                    err_msg = str(e)
                    QTimer.singleShot(
                        0, lambda: info.append(f"Error generando iconos: {err_msg}\n")
                    )
                    QTimer.singleShot(
                        100, lambda: (progress.setVisible(False), install_btn.setEnabled(True))
                    )

            t = threading.Thread(target=run_gen, daemon=True)
            t.start()

        def show_instructions():
            # En un bundle de PyInstaller el README vive en `_MEIPASS`.
            base = getattr(sys, "_MEIPASS", None) or str(Path(__file__).resolve().parent)
            readme = str(Path(base) / "README.md")
            try:
                webbrowser.open(readme)
            except Exception:
                QMessageBox.information(self, "Instrucciones", f"Revisa {readme}")

        select_ffmpeg_btn.clicked.connect(select_ffmpeg)
        install_ffmpeg_btn.clicked.connect(install_ffmpeg_full)
        install_ytdlp_btn.clicked.connect(install_ytdlp)
        instructions_btn.clicked.connect(show_instructions)
        close_btn.clicked.connect(dialog.reject)

        dialog.exec()

        # Al cerrar el diálogo, si las dependencias ya están OK y se pidió
        # reintentar el inicio, lanzamos `_start` automáticamente.
        if start_on_success:
            ffmpeg_ok_after, _ = check_ffmpeg_installed()
            ytdlp_ok_after, _ = check_yt_dlp_installed()
            if ffmpeg_ok_after and ytdlp_ok_after:
                # Llamada asíncrona para evitar reentrar en diálogos
                from PySide6.QtCore import QTimer

                QTimer.singleShot(100, lambda: self._start())

    def _read_urls(self) -> list[str]:
        """Lee y normaliza la lista de URLs desde el `QTextEdit`.

        Elimina líneas vacías y duplicados, y devuelve la lista limpia.
        """
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

    def _platform_summary(self, urls: list[str]) -> str:
        """Resume cuántas URLs hay de cada plataforma.

        Se usa para informar al usuario de qué se va a procesar.
        """
        counts: dict[str, int] = {}
        for url in urls:
            platform = detect_platform(url) or "desconocida"
            counts[platform] = counts.get(platform, 0) + 1
        if not counts:
            return ""
        return ", ".join(f"{count} de {platform}" for platform, count in sorted(counts.items()))

    def _populate_table(self, urls: list[str]):
        """Rellena la tabla de trabajos con las URLs proporcionadas.

        Crea objetos `UiJob` internos y filas en la `QTableWidget`.
        """
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

            # Columna "Vista": miniatura del vídeo final (se rellena al terminar).
            self.jobs_table.setItem(i, 4, QTableWidgetItem(""))

            self.jobs_table.setItem(i, 5, QTableWidgetItem(job.result))

        self.jobs_table.resizeColumnsToContents()
        # Los anchos manuales deben fijarse DESPUÉS de resizeColumnsToContents().
        self._apply_column_widths()
        if self._jobs:
            self.jobs_table.selectRow(0)
            self._set_metadata_fields(self._jobs[0].title, self._jobs[0].hashtags)

    def _update_job_row(self, row: int, status: str, progress: int):
        """Actualiza el estado y progreso de una fila concreta en la tabla.

        Usada por el worker para reflejar el progreso por trabajo.
        """
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

    def _update_job_thumbnail(self, row: int, thumbnail_path: str):
        """Muestra la miniatura del vídeo final en la columna 'Vista'."""
        if row < 0 or row >= len(self._jobs):
            return
        self._jobs[row].thumbnail_path = thumbnail_path
        item = self.jobs_table.item(row, 4)
        if item is None:
            return
        pixmap = QPixmap(thumbnail_path)
        if pixmap.isNull():
            return
        item.setIcon(QIcon(pixmap.scaled(54, 96, Qt.AspectRatioMode.KeepAspectRatio)))
        item.setText("")

    def _update_job_meta(self, row: int, title: str, hashtags: str):
        """Actualiza los metadatos de un trabajo en memoria y UI."""
        if row < 0 or row >= len(self._jobs):
            return
        self._jobs[row].title = title or ""
        self._jobs[row].hashtags = hashtags or ""
        if self.jobs_table.currentRow() == row:
            self._set_metadata_fields(self._jobs[row].title, self._jobs[row].hashtags)

    def _on_job_selected(self):
        """Sincroniza los metadatos con la fila seleccionada."""
        row = self.jobs_table.currentRow()
        if row < 0 or row >= len(self._jobs):
            self._set_metadata_fields("", "")
            return
        self._set_metadata_fields(self._jobs[row].title, self._jobs[row].hashtags)

    def _on_job_double_clicked(self, row: int, column: int):
        """Abre el vídeo final con el reproductor del sistema.

        Permite revisar el resultado antes de subirlo a la plataforma.
        """
        if row < 0 or row >= len(self._jobs):
            return
        result = self._jobs[row].result
        path = Path(result) if result else None
        if not path or not path.exists():
            QMessageBox.information(
                self, "Vista previa", "Este trabajo todavía no tiene un vídeo de salida."
            )
            return

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.information(self, "Vista previa", f"No se pudo abrir {path}")

    def _finish_job_row(self, row: int, ok: bool, message: str):
        """Marca un trabajo como finalizado y escribe el resultado.

        Actualiza la columna "Resultado" y el estado final en la tabla.
        """
        if row < 0 or row >= len(self._jobs):
            return
        self._jobs[row].result = message
        res_item = self.jobs_table.item(row, 5)
        if res_item:
            res_item.setText(message)
        self._update_job_row(
            row, "Listo" if ok else "Falló", 100 if ok else max(self._jobs[row].progress, 0)
        )

    def _start(self):
        """Valida dependencias y entradas, y arranca el worker en hilo.

        Realiza validaciones (FFmpeg, yt-dlp, URLs válidas) antes de lanzar
        `PipelineWorker` en un `QThread`.
        """
        self._refresh_deps(prompt_if_missing=False)
        ffmpeg_ok, ffmpeg_msg = check_ffmpeg_installed()
        ytdlp_ok, ytdlp_msg = check_yt_dlp_installed()
        if not ffmpeg_ok or not ytdlp_ok:
            # Mostrar diálogo para resolver dependencias desde la UI
            self._show_missing_deps_dialog(
                ffmpeg_ok, ffmpeg_msg, True, ytdlp_ok, ytdlp_msg, start_on_success=True
            )
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

        invalid = [u for u in urls if not validate_video_url(u)]
        if invalid:
            detail = "\n".join(f"• {u}" for u in invalid[:5])
            QMessageBox.warning(
                self,
                "URLs inválidas",
                "Estas URLs no son de una plataforma soportada "
                "(TikTok, Instagram Reels o YouTube Shorts):\n\n" + detail,
            )
            return

        logo_path = Path(self.logo_path_edit.text()) if self.logo_path_edit.text().strip() else None
        if self.branding_cb.isChecked() and not (logo_path and logo_path.exists()):
            QMessageBox.warning(
                self, "Logo", "Activa overlay pero no has seleccionado un archivo válido"
            )
            return

        self._populate_table(urls)
        self.logs.clear()
        self.overall_bar.setValue(0)

        summary = self._platform_summary(urls)
        if summary:
            self._append_log(f"Procesando {len(urls)} URL(s): {summary}")

        # Persiste la cola para poder reanudar tras un cierre inesperado.
        self._job_store.set_jobs([StoredJob(url=u) for u in urls])
        self._job_store.save()

        settings = PipelineSettings(
            subtitles=self.subtitles_cb.isChecked(),
            whisper_model=self.model_combo.currentText(),
            branding=self.branding_cb.isChecked(),
            logo_path=logo_path,
            language=self.language_combo.currentData(),
            cleanup_intermediates=self.cleanup_cb.isChecked(),
            word_highlight=self.word_highlight_cb.isChecked(),
            loudnorm=self.loudnorm_cb.isChecked(),
            evasion=self.evasion_cb.isChecked(),
        )

        self._thread = QThread()
        self._worker = PipelineWorker(urls, settings, self._job_store)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.overall.connect(self._on_overall)
        self._worker.job_update.connect(self._update_job_row)
        self._worker.job_done.connect(self._finish_job_row)
        self._worker.job_meta.connect(self._update_job_meta)
        self._worker.job_warning.connect(self._on_job_warning)
        self._worker.job_thumbnail.connect(self._update_job_thumbnail)
        self._worker.job_subtitles.connect(self._on_job_subtitles)
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
        """Solicita la cancelación del worker en ejecución.

        Llama al método `cancel` del worker para detener el procesamiento.
        """
        if self._worker:
            self._worker.cancel()
            self._append_log("Cancelando...")
            self.cancel_btn.setEnabled(False)

    def _on_overall(self, value: int, status: str):
        """Actualiza la barra de progreso global y el mensaje de estado.

        Recibido como señal desde el worker para mostrar progreso agregado.
        """
        self.overall_bar.setValue(value)
        self.statusBar().showMessage(status)

    def _on_job_warning(self, row: int, message: str):
        """Muestra un aviso de validación del vídeo en los logs."""
        self._append_log(f"⚠️  {message}")

    def _on_job_subtitles(self, row: int, subtitle_path: str, segments: list):
        """Guarda la ruta y los segmentos de subtítulos del trabajo actual.

        Permite exportarlos a SRT más tarde sin volver a transcribir.
        """
        self._last_segments = segments or []
        if row == len(self._jobs) - 1 or self.jobs_table.currentRow() == row:
            self.subs_edit.setText(subtitle_path)

    def _on_finished(self):
        """Restablece la UI al terminar el procesamiento.

        Vuelve a habilitar botones y muestra "Listo" en la barra de estado.
        """
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.import_file_btn.setEnabled(True)
        self.clear_urls_btn.setEnabled(True)
        self.statusBar().showMessage("Listo")
        self._update_retry_button()


def main():
    """Punto de entrada de la aplicación GUI.

    Crea `QApplication`, la ventana principal y arranca el bucle de eventos.
    """
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
