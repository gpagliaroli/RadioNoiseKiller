from collections import deque

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QAbstractItemView, QMenu, QApplication,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import QTimer, Signal, Qt
from config import AppConfig
from pipeline import ProcessingPipeline
from translate_client import TranslateClient
from i18n import tr
from ui.slider_row import SliderRow
from ui.tooltips import apply_tooltips

# Idiomas que cubre faster-whisper razonablemente bien (lista corta a
# propósito — el combo completo de Whisper tiene 80+ y abruma sin agregar
# nada para el caso de uso de onda corta).
_SRC_LANGS = [
    ("auto", "Auto"), ("en", "English"), ("es", "Español"), ("zh", "中文"),
    ("ja", "日本語"), ("ko", "한국어"), ("ru", "Русский"), ("de", "Deutsch"),
    ("fr", "Français"), ("pt", "Português"), ("it", "Italiano"), ("ar", "العربية"),
]
_DST_LANGS = [
    ("es", "Español"), ("en", "English"), ("pt", "Português"),
    ("fr", "Français"), ("de", "Deutsch"),
]

_CHUNK_SECONDS = 8.0
_POLL_MS = 500

_SHOW_MODES = [
    ("both", "Origen y traducción"),
    ("src",  "Solo origen"),
    ("dst",  "Solo traducción"),
]


class TranslateTab(QWidget):
    """Transcripción + traducción en vivo del audio post-cancelador, vía un
    proceso separado (ver translate_client.py / translate_worker/). Nunca
    importa nada de ese proceso — solo habla por stdin/stdout.

    Advertencia de confiabilidad: NO es opcional, el usuario la pidió
    explícita y permanente, no un tooltip (ver plan de esta feature)."""

    state_changed = Signal()  # cambió una ruta de config -> MainWindow agenda guardado

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline,
                 client: TranslateClient, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._client = client
        self._active = False
        self._last_shown_state = None
        # Historial corto para el indicador de idioma detectado + latencia
        # promedio (reemplaza el timestamp por línea que pedía el usuario).
        self._recent: deque = deque(maxlen=5)
        self._build_ui()
        self._load_values()
        apply_tooltips(self)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        warn = QLabel(tr(
            "⚠ Transcripción aproximada: con señal débil, fading o ruido de "
            "banda el resultado puede ser impreciso o directamente incorrecto. "
            "Es una ayuda para hacerse una idea de un idioma que no se conoce, "
            "no un subtítulo confiable."))
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "background-color: #3a2f00; color: #ffd600; padding: 8px; "
            "border: 1px solid #665200; border-radius: 4px; font-size: 8pt;")
        root.addWidget(warn)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("Origen:")))
        self._combo_src = QComboBox()
        for code, name in _SRC_LANGS:
            self._combo_src.addItem(name, code)
        lang_row.addWidget(self._combo_src)
        lang_row.addSpacing(12)
        lang_row.addWidget(QLabel(tr("Destino:")))
        self._combo_dst = QComboBox()
        for code, name in _DST_LANGS:
            self._combo_dst.addItem(name, code)
        lang_row.addWidget(self._combo_dst)
        lang_row.addSpacing(12)
        lang_row.addWidget(QLabel(tr("Mostrar:")))
        self._combo_show = QComboBox()
        for code, name in _SHOW_MODES:
            self._combo_show.addItem(tr(name), code)
        lang_row.addWidget(self._combo_show)
        lang_row.addStretch()
        self._btn_toggle = QPushButton(tr("▶  Iniciar"))
        self._btn_toggle.setCheckable(True)
        self._btn_toggle.toggled.connect(self._on_toggle)
        lang_row.addWidget(self._btn_toggle)
        root.addLayout(lang_row)

        self._combo_src.currentIndexChanged.connect(self._on_lang_changed)
        self._combo_dst.currentIndexChanged.connect(self._on_lang_changed)
        self._combo_show.currentIndexChanged.connect(self._on_show_mode_changed)

        self._slider_min_confidence = SliderRow(
            tr("Confianza mínima:"),
            min_val=0.0, max_val=100.0,
            default=50.0,
            step=5.0, unit="%", fmt="{:.0f}",
        )
        self._slider_min_confidence.valueChanged.connect(self._on_min_confidence_changed)
        root.addWidget(self._slider_min_confidence)

        self._lbl_stats = QLabel(tr("Idioma detectado: —  ·  Promedio: —"))
        self._lbl_stats.setStyleSheet("color: #69f0ae; font-size: 8pt; font-weight: bold;")
        root.addWidget(self._lbl_stats)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #888; font-size: 8pt;")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)

        btn_row2 = QHBoxLayout()
        self._btn_configure = QPushButton(tr("Configurar módulo de traducción..."))
        self._btn_configure.clicked.connect(self._on_configure)
        btn_row2.addWidget(self._btn_configure)
        self._btn_clear = QPushButton(tr("🗑  Borrar"))
        self._btn_clear.setToolTip(tr("Borra los subtítulos acumulados en la lista de abajo."))
        self._btn_clear.clicked.connect(self._on_clear)
        btn_row2.addWidget(self._btn_clear)
        root.addLayout(btn_row2)

        self._list = QListWidget()
        # Selección múltiple + Ctrl+C + menú contextual: el usuario pidió
        # poder copiar lo traducido, y un QListWidget no copia nada al
        # portapapeles por sí solo (no es un QTextEdit).
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        QShortcut(QKeySequence.StandardKey.Copy, self._list, activated=self._copy_selected)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        root.addWidget(self._list, 1)

    # ------------------------------------------------------------------
    # Carga / configuración
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        t = self._config.translate
        for i in range(self._combo_src.count()):
            if self._combo_src.itemData(i) == t.lang_src:
                self._combo_src.setCurrentIndex(i)
                break
        for i in range(self._combo_dst.count()):
            if self._combo_dst.itemData(i) == t.lang_dst:
                self._combo_dst.setCurrentIndex(i)
                break
        for i in range(self._combo_show.count()):
            if self._combo_show.itemData(i) == t.show_mode:
                self._combo_show.setCurrentIndex(i)
                break
        self._slider_min_confidence.set_value(t.min_confidence * 100.0)

    def _on_lang_changed(self, *_) -> None:
        self._config.translate.lang_src = self._combo_src.currentData()
        self._config.translate.lang_dst = self._combo_dst.currentData()
        self.state_changed.emit()

    def _on_show_mode_changed(self, *_) -> None:
        self._config.translate.show_mode = self._combo_show.currentData()
        self.state_changed.emit()

    def _on_min_confidence_changed(self, value: float) -> None:
        self._config.translate.min_confidence = value / 100.0
        self.state_changed.emit()

    def _on_configure(self) -> None:
        t = self._config.translate
        py, _ = QFileDialog.getOpenFileName(
            self, tr("Python del worker de traducción"),
            t.worker_python_path or "", "python.exe (python.exe);;Todos (*)")
        if not py:
            return
        script, _ = QFileDialog.getOpenFileName(
            self, tr("Script worker.py"),
            t.worker_script_path or "", "Python (*.py)")
        if not script:
            return
        t.worker_python_path = py
        t.worker_script_path = script
        self.state_changed.emit()
        QMessageBox.information(self, tr("Configurado"), tr(
            "Rutas guardadas. Presioná Iniciar para probar la conexión."))

    def _on_clear(self) -> None:
        """Borra solo los subtítulos acumulados — no toca el estado de la
        traducción (si está activa, sigue; si está detenida, sigue así)."""
        self._list.clear()

    def _copy_selected(self) -> None:
        """Ctrl+C (o el menú contextual): copia las líneas seleccionadas al
        portapapeles, una por renglón. Sin selección, copia TODO lo que
        hay en la lista — más útil que no copiar nada."""
        items = self._list.selectedItems() or [
            self._list.item(i) for i in range(self._list.count())]
        texto = "\n".join(it.text() for it in items)
        if texto:
            QApplication.clipboard().setText(texto)

    def _on_list_context_menu(self, pos) -> None:
        menu = QMenu(self)
        tiene_seleccion = bool(self._list.selectedItems())
        accion = menu.addAction(
            tr("Copiar selección") if tiene_seleccion else tr("Copiar todo"))
        accion.triggered.connect(self._copy_selected)
        menu.addAction(tr("Borrar"), self._on_clear)
        menu.exec(self._list.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Iniciar/detener
    # ------------------------------------------------------------------

    def stop_if_active(self) -> None:
        """Detiene la traducción si estaba corriendo — para cuando se para
        el procesamiento de audio general (DETENER en Principal): sin audio
        entrando al buffer, el worker queda prendido esperando chunks que
        nunca van a llegar, gastando RAM/CPU sin avisar nada en la UI."""
        if self._active:
            self._btn_toggle.setChecked(False)   # dispara _on_toggle(False)

    def _on_toggle(self, checked: bool) -> None:
        self._active = checked
        if checked:
            self._btn_toggle.setText(tr("⏹  Detener"))
            t = self._config.translate
            self._client.start(t.worker_python_path, t.worker_script_path)
            self._pipeline.set_translate_enabled(True)
        else:
            self._btn_toggle.setText(tr("▶  Iniciar"))
            self._pipeline.set_translate_enabled(False)
            self._client.stop()
            self._recent.clear()
            self._lbl_stats.setText(tr("Idioma detectado: —  ·  Promedio: —"))

    # ------------------------------------------------------------------
    # Polling (estado del cliente, chunks de audio, resultados)
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        state = self._client.state
        if state != self._last_shown_state:
            self._last_shown_state = state
            self._refresh_status_label(state)

        if not self._active or state != TranslateClient.READY:
            return

        chunk = self._pipeline.pop_translate_chunk(_CHUNK_SECONDS)
        if chunk is not None:
            self._client.send_chunk(
                chunk, self._config.audio.sample_rate,
                self._config.translate.lang_src, self._config.translate.lang_dst,
                self._config.translate.min_confidence)

        for msg in self._client.pop_results():
            if msg.get("ok") and msg.get("low_confidence"):
                # El worker ya se salteó la traducción (ver worker.py): no
                # hay "translated" confiable que mostrar, pero sin esta
                # línea el usuario no tiene forma de saber que esos
                # segundos de audio existieron y se descartaron.
                pct = msg.get("detected_lang_prob") or 0.0
                self._list.addItem(QListWidgetItem(
                    tr("⚠ Confianza baja ({pct:.0f}%) — se omite la traducción")
                    .format(pct=pct * 100.0)))
            elif msg.get("ok"):
                self._recent.append((msg.get("detected_lang"), msg.get("latency_s")))
                self._refresh_stats_label()
                for seg in msg.get("segments", []):
                    texto = self._format_segment(seg)
                    # Red de seguridad contra repeticiones (también cubre un
                    # worker viejo que siga corriendo sin el filtro).
                    n = self._list.count()
                    if n and self._list.item(n - 1).text() == texto:
                        continue
                    self._list.addItem(QListWidgetItem(texto))
            else:
                self._list.addItem(QListWidgetItem(
                    tr("⚠ Error: {detail}").format(detail=msg.get("detail") or msg.get("error", ""))))
            self._list.scrollToBottom()

    def _format_segment(self, seg: dict) -> str:
        """Formatea una línea de subtítulo según 'Mostrar' (both/src/dst).
        Sin marca de tiempo por línea (quedó como indicador agregado —
        ver _refresh_stats_label). La línea ya agregada a la lista NO se
        reformatea retroactivamente si el usuario cambia el modo después —
        es una lista de subtítulos que van quedando, no un documento editable."""
        mode = self._config.translate.show_mode
        text = seg.get("text", "")
        # .get() con default, no seg["translated"]: un worker viejo (proceso
        # que quedó corriendo de antes de agregar low_confidence) puede
        # mandar un segmento sin "translated" por otro motivo que no sea el
        # que ya cubre el chequeo de low_confidence en _tick — mejor
        # degradar mostrando el original que crashear toda la pestaña
        # (pasó: KeyError acá tumbaba _tick hasta reiniciar la app).
        translated = seg.get("translated", text)
        if mode == "src":
            return text
        if mode == "dst":
            return translated
        return f"{text}  →  {translated}"

    def _refresh_stats_label(self) -> None:
        """Idioma detectado (el más reciente) + latencia promedio de las
        últimas traducciones (hasta 5) — reemplaza el timestamp por línea
        que pedía el usuario."""
        if not self._recent:
            return
        lang = next((l for l, _ in reversed(self._recent) if l), None)
        lang_name = dict(_SRC_LANGS).get(lang, lang) if lang else "—"
        lat_values = [lat for _, lat in self._recent if lat is not None]
        avg_txt = f"{sum(lat_values) / len(lat_values):.1f}s" if lat_values else "—"
        self._lbl_stats.setText(tr(
            "Idioma detectado: {lang} ({code})  ·  Promedio: {avg}").format(
                lang=lang_name, code=lang or "—", avg=avg_txt)
            if lang else tr("Idioma detectado: —  ·  Promedio: {avg}").format(avg=avg_txt))

    def _refresh_status_label(self, state: str) -> None:
        textos = {
            TranslateClient.NOT_INSTALLED: tr(
                "Módulo no instalado o rutas no configuradas. Ver "
                "translate_worker/README.md y usar 'Configurar...' arriba."),
            TranslateClient.STARTING: tr("Iniciando el módulo de traducción..."),
            TranslateClient.READY: tr("Listo — traduciendo."),
            TranslateClient.CRASHED: tr("El proceso de traducción se cerró inesperadamente. "
                                        "Detener y volver a Iniciar para reintentar."),
            TranslateClient.STOPPED: tr("Detenido."),
        }
        self._lbl_status.setText(textos.get(state, state))
