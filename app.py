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
from PySide6.QtGui import QFont, QFontDatabase, QIcon
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
from PySide6.QtSvgWidgets import QSvgWidget

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
    title: str = ""
    hashtags: str = ""


class PipelineWorker(QObject):
    log = Signal(str)
    overall = Signal(int, str)
    job_update = Signal(int, str, int)
    job_done = Signal(int, bool, str)
    job_meta = Signal(int, str, str)
    finished = Signal()

    def __init__(self, urls: list[str], settings: PipelineSettings):
        super().__init__()
        """Inicializa el worker de la pipeline.

        Este objeto se ejecuta en un hilo separado y coordina el procesamiento
        de las URLs recibidas usando `ReelsPipeline`.

        Parámetros:
        - urls: lista de URLs a procesar.
        - settings: instancia de `PipelineSettings` con las opciones.
        """
        self._urls = urls
        self._settings = settings
        self._cancel_event = threading.Event()
        self._pipeline = ReelsPipeline()

    def cancel(self):
        """Solicita la cancelación segura del proceso en curso.

        Marca un evento interno que la pipeline revisa y usa para abortar
        operaciones de forma ordenada.
        """
        self._cancel_event.set()

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

                title = result.title or ""
                hashtags = " ".join(result.hashtags or [])
                if title or hashtags:
                    self.job_meta.emit(idx, title, hashtags)

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

        self._thread: Optional[QThread] = None
        self._worker: Optional[PipelineWorker] = None
        self._jobs: list[UiJob] = []

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
        from PySide6.QtWidgets import QSplitter
        from PySide6.QtCore import Qt as QtCore_Qt
        
        main_splitter = QSplitter(QtCore_Qt.Horizontal)
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

        self._refresh_deps()

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
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large"]) 
        self.model_combo.setCurrentText("base")
        self.model_combo.setToolTip("Selecciona el tamaño del modelo de transcripción.")
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

        branding_enabled = self.branding_cb.isChecked()
        self.logo_btn.setEnabled(branding_enabled)
        self.logo_path_edit.setEnabled(branding_enabled)

    def _build_jobs_box(self) -> QGroupBox:
        """Construye la tabla que muestra la cola de trabajo y progreso global.

        La tabla contiene columnas para índice, URL, estado, progreso y resultado.
        """
        box = QGroupBox("Cola")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self.jobs_table = QTableWidget(0, 5)
        self.jobs_table.setHorizontalHeaderLabels(["#", "URL", "Estado", "Progreso", "Resultado"])
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs_table.setAlternatingRowColors(True)
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.setMinimumHeight(200)
        self.jobs_table.setMaximumHeight(280)
        # Ajustar ancho de columnas
        self.jobs_table.setColumnWidth(0, 40)
        self.jobs_table.setColumnWidth(2, 120)
        self.jobs_table.setColumnWidth(3, 120)
        self.jobs_table.setToolTip("Muestra la cola de trabajos con su estado y resultado.")
        self.jobs_table.itemSelectionChanged.connect(self._on_job_selected)
        layout.addWidget(self.jobs_table)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setToolTip("Progreso global del procesamiento.")
        layout.addWidget(self.overall_bar)

        return box

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
        self.copy_tags_btn.clicked.connect(lambda: self._copy_to_clipboard(self.hashtags_edit.text()))
        self.copy_all_btn = QPushButton("Todo")
        self.copy_all_btn.setObjectName("ghost")
        self.copy_all_btn.setFixedSize(60, 32)
        self.copy_all_btn.clicked.connect(self._copy_all_metadata)
        tags_container.addWidget(tags_lbl)
        tags_container.addWidget(self.hashtags_edit, 1)
        tags_container.addWidget(self.copy_tags_btn)
        tags_container.addWidget(self.copy_all_btn)
        layout.addLayout(tags_container)

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
        """Construye el footer con botones de iniciar y cancelar.

        Contiene los controles principales para comenzar o detener la ejecución.
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

        row.addWidget(self.start_btn)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)

        return bar

    def _append_log(self, message: str):
        """Añade una línea al registro y la escribe en el logger.

        Mensajes de estado y errores se registran aquí para diagnóstico.
        """
        self.logs.append(message)
        logger.info(message)

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

    def _set_metadata_fields(self, title: str, hashtags: str):
        """Actualiza los campos de metadatos en la UI."""
        self.title_edit.setText(title or "")
        self.hashtags_edit.setText(hashtags or "")

    def _import_urls_file(self):
        """Permite seleccionar un archivo .txt y añade sus URLs al textarea.

        Leerá el contenido como texto plano y lo añadirá al campo existente.
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "Importar URLs", str(config.paths.INPUT_PATH), "Text (*.txt)")
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
            "Images (*.png *.jpg *.jpeg *.webp)"
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

    def _refresh_deps(self):
        """Verifica si las dependencias externas están disponibles.

        Comprueba FFmpeg, soporte de subtítulos y yt-dlp y actualiza la etiqueta.
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
        if not ffmpeg_ok or not ytdlp_ok:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, lambda: self._show_missing_deps_dialog(ffmpeg_ok, ffmpeg_msg, subs_ok, ytdlp_ok, ytdlp_msg))

    def _show_missing_deps_dialog(self, ffmpeg_ok: bool, ffmpeg_msg: str, subs_ok: bool, ytdlp_ok: bool, ytdlp_msg: str, start_on_success: bool = False):
        """Muestra un diálogo modal para resolver dependencias sin terminal.

        Permite seleccionar un binario de FFmpeg o intentar instalar `yt-dlp`
        desde la interfaz. Las acciones se realizan en segundo plano y la
        interfaz se actualiza al terminar.
        """
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QTextEdit, QProgressBar, QLabel
        import subprocess
        import threading
        import sys
        import webbrowser

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
        info.setPlainText('\n'.join(msg_lines))

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
            path, _ = QFileDialog.getOpenFileName(self, "Seleccionar ffmpeg", str(config.paths.BASE_PATH), "Executable (ffmpeg*);;All Files (*)")
            if not path:
                return
            # Ofrecer copiar el binario a third_party para empaquetado
            from PySide6.QtWidgets import QMessageBox
            copy_choice = QMessageBox.question(self, "Copiar ffmpeg", "¿Copiar el binario seleccionado a third_party/ffmpeg/bin para uso interno y empaquetado?", QMessageBox.Yes | QMessageBox.No)
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

            self._refresh_deps()
            dialog.accept()

        def install_ytdlp():
            install_ytdlp_btn.setEnabled(False)
            progress.setVisible(True)
            info.append("Iniciando instalación de yt-dlp...\n")

            def run_install():
                try:
                    # Ejecutar pip e ir capturando salida en tiempo real
                    proc = subprocess.Popen([sys.executable, "-m", "pip", "install", "yt-dlp"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    if proc.stdout:
                        for line in proc.stdout:
                            stripped = line.rstrip('\n')
                            def append_line(l=stripped):
                                info.append(l)
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(0, append_line)
                    proc.wait()
                    ret = proc.returncode
                    self._append_log("Instalación yt-dlp: " + ("OK" if ret == 0 else "FALLÓ"))

                    def on_done():
                        progress.setVisible(False)
                        install_ytdlp_btn.setEnabled(True)
                        if ret == 0:
                            QMessageBox.information(self, "Instalación", "yt-dlp instalado correctamente.")
                        else:
                            QMessageBox.warning(self, "Instalación", f"Error al instalar yt-dlp (código {ret}). Revisa el log arriba.")
                        self._refresh_deps()

                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, on_done)
                except Exception as e:
                    self._append_log(f"Error instalación yt-dlp: {e}")
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, lambda: QMessageBox.warning(self, "Instalación", str(e)))
                return

            t = threading.Thread(target=run_install, daemon=True)
            t.start()

        def install_ffmpeg_full():
            if sys.platform != "darwin":
                QMessageBox.information(self, "FFmpeg", "La instalación automática solo está disponible en macOS.")
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
                        raise RuntimeError("Homebrew no encontrado. Instálalo desde https://brew.sh")

                    proc = subprocess.Popen([brew, "install", "ffmpeg-full"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    if proc.stdout:
                        for line in proc.stdout:
                            l = line.rstrip("\n")
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(0, lambda txt=l: info.append(txt))
                    proc.wait()

                    # Asegurar PATH del ffmpeg-full instalado
                    prefix = subprocess.run([brew, "--prefix", "ffmpeg-full"], capture_output=True, text=True)
                    if prefix.returncode == 0:
                        pref = prefix.stdout.strip()
                        if pref:
                            os.environ["PATH"] = f"{pref}/bin:" + os.environ.get("PATH", "")

                    def on_done():
                        progress.setVisible(False)
                        install_ffmpeg_btn.setEnabled(True)
                        if proc.returncode == 0:
                            QMessageBox.information(self, "FFmpeg", "ffmpeg-full instalado correctamente.")
                        else:
                            QMessageBox.warning(self, "FFmpeg", "Error al instalar ffmpeg-full. Revisa el log.")
                        self._refresh_deps()

                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, on_done)
                except Exception as e:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: info.append(f"Error instalando ffmpeg-full: {e}\n"))
                    QTimer.singleShot(100, lambda: (progress.setVisible(False), install_ffmpeg_btn.setEnabled(True)))

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
                        proc = subprocess.Popen([sys.executable, "-m", "pip", "install", "cairosvg"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        if proc.stdout:
                            for line in proc.stdout:
                                l = line.rstrip('\n')
                                from PySide6.QtCore import QTimer
                                QTimer.singleShot(0, lambda txt=l: info.append(txt))
                        proc.wait()
                        if proc.returncode != 0:
                            raise RuntimeError("Fallo instalando cairosvg")
                        import importlib
                        cairosvg = importlib.import_module('cairosvg')

                    sizes = [16, 32, 64, 128, 256, 512, 1024]
                    src = config.paths.ASSETS_PATH / 'icon.svg'
                    out_dir = config.paths.ASSETS_PATH / 'generated_icons'
                    out_dir.mkdir(parents=True, exist_ok=True)
                    from pathlib import Path as _Path
                    for s in sizes:
                        out_file = out_dir / f'icon_{s}x{s}.png'
                        cairosvg.svg2png(url=str(src), write_to=str(out_file), output_width=s, output_height=s)
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda txt=f'Generado: {out_file}': info.append(txt))

                    # Crear .iconset para macOS
                    iconset = out_dir / 'App.iconset'
                    iconset.mkdir(parents=True, exist_ok=True)
                    def cp(srcp, dstp):
                        try:
                            import shutil
                            shutil.copy2(str(srcp), str(dstp))
                        except Exception:
                            pass

                    cp(out_dir / 'icon_16x16.png', iconset / 'icon_16x16.png')
                    cp(out_dir / 'icon_32x32.png', iconset / 'icon_16x16@2x.png')
                    cp(out_dir / 'icon_32x32.png', iconset / 'icon_32x32.png')
                    cp(out_dir / 'icon_64x64.png', iconset / 'icon_32x32@2x.png')
                    cp(out_dir / 'icon_128x128.png', iconset / 'icon_128x128.png')
                    cp(out_dir / 'icon_256x256.png', iconset / 'icon_128x128@2x.png')
                    cp(out_dir / 'icon_256x256.png', iconset / 'icon_256x256.png')
                    cp(out_dir / 'icon_512x512.png', iconset / 'icon_256x256@2x.png')
                    cp(out_dir / 'icon_512x512.png', iconset / 'icon_512x512.png')
                    cp(out_dir / 'icon_1024x1024.png', iconset / 'icon_512x512@2x.png')

                    # Intentar crear .icns con iconutil (solo mac)
                    icns_path = out_dir / 'App.icns'
                    try:
                        if sys.platform == 'darwin':
                            subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(icns_path)], check=True)
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(0, lambda: info.append(f'ICNS creado: {icns_path}\n'))
                    except Exception:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda: info.append('No se pudo generar .icns (iconutil no disponible).\n'))

                    # Intentar generar .ico para Windows usando Pillow
                    try:
                        try:
                            from PIL import Image
                        except Exception:
                            info.append('Pillow no encontrado, instalando...\n')
                            proc = subprocess.Popen([sys.executable, "-m", "pip", "install", "Pillow"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                            if proc.stdout:
                                for line in proc.stdout:
                                    l = line.rstrip('\n')
                                    from PySide6.QtCore import QTimer
                                    QTimer.singleShot(0, lambda txt=l: info.append(txt))
                            proc.wait()
                            if proc.returncode != 0:
                                raise RuntimeError('Fallo instalando Pillow')
                            from PIL import Image

                        # Cargar varias resoluciones y guardar .ico
                        ico_path = out_dir / 'icon.ico'
                        sizes = [256, 128, 64, 32, 16]
                        images = []
                        for s in sizes:
                            p = out_dir / f'icon_{s}x{s}.png'
                            if p.exists():
                                images.append(Image.open(str(p)).convert('RGBA'))
                        if images:
                            # Guardar el mayor con tamaños adicionales
                            images[0].save(str(ico_path), format='ICO', sizes=[(s, s) for s in sizes])
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(0, lambda: info.append(f'ICO creado: {ico_path}\n'))
                    except Exception:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda: info.append('No se pudo generar .ico.\n'))

                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: info.append('Generación de iconos finalizada.\n'))
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, lambda: (progress.setVisible(False), install_btn.setEnabled(True), self._append_log('Iconos generados')))
                except Exception as e:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: info.append(f'Error generando iconos: {e}\n'))
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, lambda: (progress.setVisible(False), install_btn.setEnabled(True)))

            t = threading.Thread(target=run_gen, daemon=True)
            t.start()


        def show_instructions():
            readme = str(Path(__file__).resolve().parent / "README.md")
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

            self.jobs_table.setItem(i, 4, QTableWidgetItem(job.result))

        self.jobs_table.resizeColumnsToContents()
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

    def _finish_job_row(self, row: int, ok: bool, message: str):
        """Marca un trabajo como finalizado y escribe el resultado.

        Actualiza la columna "Resultado" y el estado final en la tabla.
        """
        if row < 0 or row >= len(self._jobs):
            return
        self._jobs[row].result = message
        res_item = self.jobs_table.item(row, 4)
        if res_item:
            res_item.setText(message)
        self._update_job_row(row, "Listo" if ok else "Falló", 100 if ok else max(self._jobs[row].progress, 0))

    def _start(self):
        """Valida dependencias y entradas, y arranca el worker en hilo.

        Realiza validaciones (FFmpeg, yt-dlp, URLs válidas) antes de lanzar
        `PipelineWorker` en un `QThread`.
        """
        self._refresh_deps()
        ffmpeg_ok, _ = check_ffmpeg_installed()
        ytdlp_ok, _ = check_yt_dlp_installed()
        if not ffmpeg_ok or not ytdlp_ok:
            # Mostrar diálogo para resolver dependencias desde la UI
            self._show_missing_deps_dialog(ffmpeg_ok, "", True, ytdlp_ok, "", start_on_success=True)
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
        self._worker.job_meta.connect(self._update_job_meta)
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

    def _on_finished(self):
        """Restablece la UI al terminar el procesamiento.

        Vuelve a habilitar botones y muestra "Listo" en la barra de estado.
        """
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.import_file_btn.setEnabled(True)
        self.clear_urls_btn.setEnabled(True)
        self.statusBar().showMessage("Listo")


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
