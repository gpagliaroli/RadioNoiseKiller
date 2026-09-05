import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QSlider, QPushButton, QStatusBar,
    QGroupBox, QCheckBox, QTabWidget, QApplication,
    QScrollArea, QFrame, QInputDialog, QMessageBox, QSplitter, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, QPoint, QUrl
from PySide6.QtGui import QFont, QDesktopServices

from audio.devices import (
    list_devices, rescan_devices, AudioDevice,
    IncompatibleDevicesError, duplex_hostapi_mismatch,
)
from config import (AppConfig, GainConfig, DSPConfig, UI_SCALES,
                    BANDPASS_PRESETS, BANDPASS_CUSTOM)
from i18n import tr, set_language
from pipeline import ProcessingPipeline
from ui.vu_meter import VuMeter
from ui.advanced_tab import AdvancedAudioTab, AdvancedImpulseTab, AdvancedCancellerTab
from ui.presets_tab import PresetsTab
from ui.slider_row import SliderRow
from ui.tooltips import apply_tooltips
from ui.spectrum_widget import SpectrumWidget
from ui.waterfall_widget import WaterfallWidget
from presets import PresetManager
from noise_profiles import NoiseProfileManager
from utils import settings_path, presets_dir, noise_profiles_dir, seed_factory_presets

# Borde de aviso para los combos de dispositivo cuando la combinación de APIs
# es incompatible (entrada y salida en APIs de host distintas → -9993).
# Ancho comun de los botones de accion de la fila de escucha (Grabar / Bypass /
# Mute). Uniforme a proposito: son tres controles del mismo tipo, uno al lado
# del otro. 140 y no menos porque el texto mas largo que muestran ('Detener')
# pide 134 px, y el ancho de los emoji varia con la fuente del sistema — sin
# holgura, en otra maquina el texto sale recortado con '...'.
_ACTION_BTN_W = 140
_COMBO_WARN_STYLE = "QComboBox { border: 1px solid #ef5350; }"

# Ancho común de los combos de la pestaña Principal (Entrada/Salida/Canal/Modo/AGC/
# Modo ruido) y de los VU meters, para que terminen donde termina la barra del slider.
# La barra del SliderRow termina en label(150) + spacing(8) + slider(400) = 558.
_ROW_LABEL_W = 70       # ancho de la etiqueta de la fila (columna izquierda)
_FIELD_W = 558          # fin de la barra del slider (ancho de los VU, que arrancan en x=0)
_COMBO_W = _FIELD_W - _ROW_LABEL_W - 8   # ancho del combo para que termine en _FIELD_W
_WINDOW_W = 770         # ancho FIJO de la ventana (alto flexible)
# Ticks del timer de 500 ms antes de dejar de decir "calibrando" en MCRA.
# El warmup real son ~200 ms; 6 ticks (3 s) es holgado y no da falsos avisos.
_MCRA_WAIT_TICKS = 6
_SCALE_MARGEN = 40      # px reales de holgura para el marco de la ventana

# URL de donación que abre el botón del diálogo "Acerca de".
# VACÍA = el botón NO aparece. Es a propósito: así un placeholder no puede
# viajar en un release y mandar a la gente a una página rota o ajena.
#
# Plataforma elegida: Cafecito → https://cafecito.app/USUARIO
# (Cafecito cobra ~5% local; los pagos del exterior son OPT-IN desde el panel
# de la cuenta y suman ~4,8% + USD 0,35, liquidando en pesos al oficial.)
#
# Si alguna vez se cambia de plataforma, acá sólo se toca la URL. Único cuidado
# si se volviera a PayPal: NO usar la forma `donate/?business=` con el email —
# este repo es público y el correo quedaría expuesto a los rastreadores de spam;
# el "ID de comerciante" cumple la misma función sin publicarlo.
_DONATE_URL = "https://cafecito.app/gpagliaroli"


def ui_scales_that_fit(ancho_pantalla_real: float, aplicada: float) -> tuple:
    """Escalas de UI que entran en una pantalla de `ancho_pantalla_real` px REALES.

    A cualquier escala la ventana mide `_WINDOW_W` píxeles LÓGICOS, pero la
    pantalla mide menos píxeles lógicos cuanto mayor es la escala — por eso la
    comparación va en píxeles reales, no en los que reporta Qt.

    Sin este filtro, elegir una escala grande en un monitor chico deja la ventana
    más ancha que la pantalla; y como el ancho es FIJO, Qt no la puede achicar:
    la barra de estado (donde vive el combo para deshacerlo) queda fuera de la
    pantalla. La escala ya aplicada se incluye siempre, para que el combo pueda
    mostrar lo que se está viendo aunque no entre.
    """
    entran = [s for s in UI_SCALES if _WINDOW_W * s + _SCALE_MARGEN <= ancho_pantalla_real]
    return tuple(sorted(set(entran) | {aplicada}))


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._config = AppConfig()
        self._config.load(settings_path())
        set_language(self._config.language)  # antes de construir cualquier widget
        # Escala REALMENTE en efecto: main.py la exporta a QT_SCALE_FACTOR desde
        # la config antes de crear el QApplication. Se lee del entorno y no de la
        # config porque el usuario (o un lanzador) puede haberla exportado a mano,
        # y el combo tiene que mostrar lo que se está viendo, no lo que se guardó.
        try:
            self._applied_ui_scale = float(os.environ.get(
                "QT_SCALE_FACTOR", self._config.window.ui_scale))
        except ValueError:
            self._applied_ui_scale = 1.0

        self._pipeline = ProcessingPipeline(self._config)
        # Primer arranque de un bundle: los presets de fábrica viven en los recursos
        # empaquetados y hay que copiarlos a la carpeta escribible (ver utils).
        seed_factory_presets()
        self._preset_manager = PresetManager(presets_dir())
        self._noise_profile_manager = NoiseProfileManager(noise_profiles_dir())
        # Nombre del perfil de ruido nombrado actualmente cargado (para mostrarlo en la UI).
        # Se limpia (None) al Aprender un perfil nuevo o Borrar, porque el perfil activo ya no
        # corresponde a ese archivo. NO es lo mismo que config.last_noise_profile (que persiste
        # el nombre para la auto-recarga aunque después se aprenda uno nuevo).
        self._active_noise_profile_name: "str | None" = None
        # Ganancia de salida recordada por modo bypass (memoria de sesión, NO se
        # persiste): {False: procesando, True: bypass}. Al alternar Bypass el slider
        # de Salida salta al valor guardado del modo destino → A/B a nivel parejo sin
        # reajustar. Arranca con ambos slots en el valor de config (sin salto hasta
        # que el usuario ajuste en un modo). Ver _on_bypass_toggled / _on_gain_out_changed.
        self._out_gain_by_bypass = {
            False: self._config.gain.output_gain_db,
            True:  self._config.gain.output_gain_db_bypass,
        }
        # Snapshot en memoria del preset activo (dsp, gain) para chequear "(modificado)"
        # sin re-leer el JSON en cada actualización del título.
        self._preset_saved_snapshot = None
        self._snapshot_for = None

        self._level_timer = QTimer()
        self._level_timer.setInterval(33)
        self._level_timer.timeout.connect(self._tick_levels)

        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_settings)

        self._setup_pipeline_callbacks()
        self._build_ui()
        self._saved_input_device  = self._config.audio.input_device
        self._saved_output_device = self._config.audio.output_device
        self._populate_devices()
        self._apply_loaded_config()
        loaded_profile = self._auto_load_noise_profile()

        self._btn_start.setEnabled(True)
        ready = tr("Listo. Presiona ACTIVAR para iniciar.")
        if loaded_profile:
            ready = tr("Perfil de ruido \"{name}\" cargado. Listo para ACTIVAR.").format(
                name=loaded_profile)
        self._status_bar.showMessage(ready)
        # Si la selección inicial cruza APIs incompatibles, deshabilita ACTIVAR
        # y avisa (reemplaza el mensaje "Listo" recién puesto).
        self._check_device_compatibility()
        self._restore_or_center()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._update_window_title()
        self.setFixedWidth(_WINDOW_W)   # ancho fijo (alto flexible)

        self._spectrum_widget = SpectrumWidget()
        self._spectrum_widget.pre_frames  = self._pipeline.spectrum_pre_frames
        self._spectrum_widget.post_frames = self._pipeline.spectrum_post_frames

        self._waterfall_widget = WaterfallWidget()
        self._spectrum_widget.waterfall = self._waterfall_widget
        self._spectrum_widget.set_waterfall_source(self._config.window.waterfall_source)
        self._spectrum_widget.set_waterfall_enabled(self._config.window.spectrum_show_waterfall)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_main_tab(), tr("Principal"))
        self._tabs.addTab(self._build_modules_tab(), tr("Módulos"))

        self._adv_audio_tab     = AdvancedAudioTab(self._config, self._pipeline)
        self._adv_impulse_tab   = AdvancedImpulseTab(self._config, self._pipeline)
        self._adv_canceller_tab = AdvancedCancellerTab(self._config, self._pipeline)
        # Los sliders de Avanzadas conectan directo al pipeline; sin esto sus
        # cambios no marcan "(modificado)" ni agendan el guardado.
        self._adv_audio_tab.changed.connect(self._schedule_save)
        self._adv_audio_tab.bandpass_changed.connect(self._refresh_bandpass_combo)
        self._adv_impulse_tab.changed.connect(self._schedule_save)
        self._adv_canceller_tab.changed.connect(self._schedule_save)
        self._tabs.addTab(self._adv_audio_tab,     tr("Avanzada Audio"))
        self._tabs.addTab(self._adv_impulse_tab,   tr("Avanzada Impulsos"))
        self._tabs.addTab(self._adv_canceller_tab, tr("Avanzada Cancelador"))
        self._tabs.addTab(self._build_spectrum_tab(), tr("Espectro"))
        self._presets_tab = PresetsTab(
            self._config, self._pipeline, self._preset_manager
        )
        self._presets_tab.preset_loaded.connect(self.refresh_from_config)
        self._presets_tab.preset_loaded.connect(self._refresh_title)
        self._presets_tab.state_changed.connect(self._schedule_save)
        self._presets_tab.state_changed.connect(self._refresh_title)
        self._tabs.addTab(self._presets_tab, tr("Presets"))
        self._tabs.currentChanged.connect(self._on_tab_changed)

        root.addWidget(self._tabs)
        root.addSpacing(10)   # separa Grabar/Mute del botón ACTIVAR
        root.addWidget(self._build_start_button())

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        # Selector de idioma: preferencia de aplicación (se cambia una vez) —
        # vive en la barra de estado, no entre los controles de operación
        self._combo_lang = QComboBox()
        self._combo_lang.addItem("🌐 Español", "es")
        self._combo_lang.addItem("🌐 English", "en")
        for i in range(self._combo_lang.count()):
            if self._combo_lang.itemData(i) == self._config.language:
                self._combo_lang.setCurrentIndex(i)
                break
        self._combo_lang.setToolTip(tr("Idioma de la interfaz — requiere reiniciar la aplicación"))
        self._combo_lang.currentIndexChanged.connect(self._on_language_changed)
        self._status_bar.addPermanentWidget(self._combo_lang)

        # Escala de la interfaz: misma naturaleza que el idioma (preferencia de
        # aplicación que se elige una vez y necesita reinicio), así que va al lado.
        self._combo_ui_scale = QComboBox()
        for s in self._available_ui_scales():
            self._combo_ui_scale.addItem(f"🔍 {round(s * 100)} %", s)
            if s == self._applied_ui_scale:
                self._combo_ui_scale.setCurrentIndex(self._combo_ui_scale.count() - 1)
        self._combo_ui_scale.setToolTip(tr(
            "Tamaño de la interfaz: agranda todos los textos y controles a la vez\n"
            "(útil en monitores donde la letra queda chica). No cambia el audio ni\n"
            "el procesamiento. Requiere reiniciar la aplicación."))
        self._combo_ui_scale.currentIndexChanged.connect(self._on_ui_scale_changed)
        self._status_bar.addPermanentWidget(self._combo_ui_scale)

        self._btn_about = QPushButton("ℹ")
        self._btn_about.setFixedWidth(28)
        self._btn_about.setToolTip(tr("Acerca de RadioNoiseKiller"))
        self._btn_about.clicked.connect(self._show_about)
        self._status_bar.addPermanentWidget(self._btn_about)

        apply_tooltips(self)
        self._apply_dark_style()

    def _build_main_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self._build_device_group())
        layout.addWidget(self._build_control_group())
        layout.addWidget(self._build_noise_group())
        layout.addWidget(self._build_level_group())
        # Scroll para pantallas bajas (notebooks 1366x768): sin esto la pestaña
        # fija la altura mínima de la ventana y no entra completa en el monitor
        self._main_tab_inner = tab   # para calcular la altura deseada en _restore_or_center
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(tab)
        return scroll

    def _build_device_group(self) -> QGroupBox:
        group = QGroupBox(tr("Dispositivos de Audio"))
        layout = QVBoxLayout(group)
        self._combo_in  = QComboBox()
        self._combo_out = QComboBox()
        in_row = self._labeled_row(tr("Entrada:"), self._combo_in)
        in_row.addStretch()
        layout.addLayout(in_row)

        out_row = self._labeled_row(tr("Salida:"), self._combo_out)
        self._btn_refresh_devices = QPushButton("⟳")
        self._btn_refresh_devices.setFixedWidth(34)
        self._btn_refresh_devices.setToolTip(
            tr("Volver a buscar dispositivos de audio (hardware conectado o\n"
            "desconectado con la aplicación abierta). Requiere procesamiento detenido.")
        )
        self._btn_refresh_devices.clicked.connect(self._on_refresh_devices)
        out_row.addWidget(self._btn_refresh_devices)
        out_row.addStretch()
        layout.addLayout(out_row)

        chan_row = QHBoxLayout()
        chan_lbl = QLabel(tr("Canal:"))
        chan_lbl.setFixedWidth(_ROW_LABEL_W)
        chan_row.addWidget(chan_lbl)
        self._combo_channel = QComboBox()
        self._combo_channel.setFixedWidth(_COMBO_W)
        for label, mode in [
            (tr("Izquierdo"),   "left"),
            (tr("Derecho"),     "right"),
            (tr("Mezcla L+R"),  "mix"),
        ]:
            self._combo_channel.addItem(label, mode)
        self._combo_channel.setToolTip(tr(
            "Canal tomado de entradas estéreo. Útil si la radio entrega el audio\n"
            "por el canal derecho, o para elegir receptor en radios con doble RX\n"
            "(principal=izquierdo, sub=derecho). Se aplica en vivo."
        ))
        self._combo_channel.currentIndexChanged.connect(self._on_input_channel_changed)
        chan_row.addWidget(self._combo_channel)
        chan_row.addStretch()
        layout.addLayout(chan_row)
        return group

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox(tr("Control"))
        layout = QVBoxLayout(group)

        # Reemplaza al viejo selector de modo AM/SSB: con los presets de la app,
        # elegir el modo y despues el ancho era redundante. Lo que se elige es el
        # ANCHO; "Personalizado" son los limites de Avanzada Audio.
        self._combo_bandpass = QComboBox()
        for nombre in BANDPASS_PRESETS:
            self._combo_bandpass.addItem(tr(nombre), nombre)
        self._combo_bandpass.addItem(tr(BANDPASS_CUSTOM), BANDPASS_CUSTOM)
        self._combo_bandpass.setToolTip(tr(
            "Ancho del filtro de entrada. Elegilo por lo que estás escuchando:\n"
            "los SSB son para fonía de banda lateral y los AM para emisoras.\n"
            "Al mover los límites en Avanzada Audio pasa solo a Personalizado."))
        self._combo_bandpass.currentIndexChanged.connect(self._on_bandpass_preset)
        bp_row = self._labeled_row(tr("Pasabanda:"), self._combo_bandpass)
        bp_row.addStretch()
        layout.addLayout(bp_row)

        agc_row = QHBoxLayout()
        agc_lbl = QLabel(tr("AGC:"))
        agc_lbl.setFixedWidth(_ROW_LABEL_W)
        agc_row.addWidget(agc_lbl)
        self._combo_agc = QComboBox()
        self._combo_agc.setFixedWidth(_COMBO_W)
        for label, preset in [
            (tr("Desactivado"), "off"),
            (tr("Rápido"),      "fast"),
            (tr("Medio"),       "medium"),
            (tr("Lento"),       "slow"),
        ]:
            self._combo_agc.addItem(label, preset)
        self._combo_agc.setCurrentIndex(0)
        self._combo_agc.currentIndexChanged.connect(self._on_agc_changed)
        agc_row.addWidget(self._combo_agc)
        self._label_agc_gain = QLabel("")
        self._label_agc_gain.setFixedWidth(60)
        self._label_agc_gain.setStyleSheet("color: #69f0ae; font-size: 8pt; font-weight: bold;")
        agc_row.addWidget(self._label_agc_gain)
        agc_row.addStretch()
        layout.addLayout(agc_row)

        # "Nivelar en continuo" y el techo de ruido viven acá y no en Avanzada
        # Audio: los dos son ajustes del comportamiento del AGC y se deciden
        # escuchando, así que van junto al combo que lo activa.
        cont_row = QHBoxLayout()
        cont_lbl = QLabel("")
        cont_lbl.setFixedWidth(_ROW_LABEL_W)
        cont_row.addWidget(cont_lbl)
        self._chk_leveler_continuous = QCheckBox(
            tr("Nivelar en continuo (música / sin detección de voz)"))
        self._chk_leveler_continuous.setToolTip(tr(
            "Desactivado (default): el nivelador adapta solo cuando el detector\n"
            "de voz confirma voz presente — evita amplificar el ruido en las\n"
            "pausas entre palabras (ideal para voz en banda ruidosa).\n"
            "Activado: adapta en continuo, sin esperar voz — usar para música o\n"
            "audio continuo, donde no hay estructura de voz que detectar."))
        # Checkbox marcado = nivelar continuo = SIN gate por voz
        self._chk_leveler_continuous.toggled.connect(self._on_leveler_continuous)
        cont_row.addWidget(self._chk_leveler_continuous)
        cont_row.addStretch()
        layout.addLayout(cont_row)

        ceil_row = QHBoxLayout()
        ceil_lbl = QLabel("")
        ceil_lbl.setFixedWidth(_ROW_LABEL_W)
        ceil_row.addWidget(ceil_lbl)
        self._chk_agc_ceiling = QCheckBox(tr("Techo de ruido"))
        self._chk_agc_ceiling.setToolTip(tr(
            "El AGC lleva la señal a su nivel objetivo sin distinguir voz de ruido:\n"
            "con señal débil sube el ruido de banda hasta +36 dB y queda un siseo\n"
            "molesto. Con esto, su ganancia se topea para que el ruido no pase del\n"
            "nivel elegido. El AGC sigue adaptando (no se congela), así que no puede\n"
            "quedar trabado, y la voz la termina de levantar el Nivelador de voz."))
        self._chk_agc_ceiling.toggled.connect(self._on_agc_ceiling_toggled)
        ceil_row.addWidget(self._chk_agc_ceiling)
        self._lbl_agc_ceiling = QLabel("—")
        self._lbl_agc_ceiling.setStyleSheet("color: #555; font-size: 8pt;")
        ceil_row.addWidget(self._lbl_agc_ceiling)
        ceil_row.addStretch()
        layout.addLayout(ceil_row)

        self._s_agc_ceiling = SliderRow(
            tr("El ruido no pasa de:"),
            min_val=-70.0, max_val=-25.0,
            default=DSPConfig().agc_noise_ceiling_db,
            step=1.0, unit="dBFS", fmt="{:.0f}",
        )
        self._s_agc_ceiling.valueChanged.connect(self._on_agc_ceiling_db)
        layout.addWidget(self._s_agc_ceiling)
        self._chk_leveler_continuous.setChecked(not self._config.dsp.voice_leveler_gate_voice)
        self._refresh_control_gating()
        self._chk_agc_ceiling.setChecked(self._config.dsp.agc_noise_ceiling_enabled)
        self._s_agc_ceiling.set_value(self._config.dsp.agc_noise_ceiling_db)
        self._s_agc_ceiling.set_enabled(self._config.dsp.agc_noise_ceiling_enabled)

        return group

    def _on_leveler_continuous(self, on: bool) -> None:
        # Marcado = nivelar en continuo = SIN gate por voz
        self._pipeline.set_voice_leveler_gate_voice(not on)
        self._schedule_save()

    def _on_agc_ceiling_toggled(self, v: bool) -> None:
        self._config.dsp.agc_noise_ceiling_enabled = bool(v)
        self._pipeline.set_agc_noise_ceiling_enabled(v)
        self._s_agc_ceiling.set_enabled(v)
        self._schedule_save()

    def _on_agc_ceiling_db(self, val: float) -> None:
        self._pipeline.set_agc_noise_ceiling_db(val)
        self._schedule_save()

    def _build_modules_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self._build_modules_group())
        layout.addStretch()
        # Scroll para pantallas bajas — misma razón que la pestaña Principal
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(tab)
        return scroll

    def _build_modules_group(self) -> QGroupBox:
        group = QGroupBox(tr("Módulos activos"))
        layout = QVBoxLayout(group)

        def _chk(label: str, tooltip: str) -> QCheckBox:
            cb = QCheckBox(label)
            cb.setToolTip(tooltip)
            layout.addWidget(cb)
            return cb

        def _chk_sub(label: str, tooltip: str) -> QCheckBox:
            """Checkbox indentado — sub-módulo del ítem anterior."""
            cb = QCheckBox(label)
            cb.setToolTip(tooltip)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(22, 0, 0, 0)
            row_layout.setSpacing(0)
            row_layout.addWidget(cb)
            layout.addWidget(row)
            return cb

        self._chk_blanker = _chk(
            tr("Supresor de impulsos"),
            tr("Elimina QRN, frituras y descargas atmosféricas cortas."),
        )
        self._chk_bandpass_pre = _chk(
            tr("Filtro de paso de banda  (pre)"),
            tr("Butterworth IIR antes del cancelador de ruido — limita el espectro que aprende el perfil."),
        )
        self._chk_anf = _chk(
            tr("ANF — Cancela heterodinos y tonos interferentes"),
            tr("Detecta bins espectrales que sobresalen sobre el ruido vecino y los atenúa."),
        )
        self._chk_noise = _chk(
            tr("Cancelador de ruido estacionario"),
            tr("Filtro de Wiener espectral. Requiere perfil aprendido."),
        )
        self._chk_perceptual_floor = _chk_sub(
            tr("Piso espectral perceptual  (curva de enmascaramiento auditivo)"),
            tr("Reemplaza el floor fijo por una curva que varía por frecuencia:\n"
            "  · +75% en ~500 Hz (fundamentales vocales, preserva la calidez)\n"
            "  · Neutro en 1000–3000 Hz (formantes, sin cambio)\n"
            "  · –55% sobre 3 kHz (ruido de alta frecuencia, suprime más)\n"
            "El slider 'Piso espectral' de Avanzada Ruido controla el nivel global.\n"
            "Requiere cancelador activo."),
        )
        self._chk_post_filter = _chk_sub(
            tr("Post-filtro espectral  (ruido musical residual)"),
            tr("Segunda pasada sobre bins de ruido para eliminar el 'ruido musical'\n"
            "(pitidos intermitentes) que deja el Wiener. Requiere cancelador activo.\n"
            "Agresividad configurable en pestaña Avanzada Ruido."),
        )
        self._chk_pitch_enhance = _chk_sub(
            tr("Refuerzo de pitch de voz  (detección por autocorrelación)"),
            tr("Detecta el tono fundamental de la voz y protege sus armónicos\n"
            "del cancelador de ruido. Mejora la inteligibilidad de señales de voz\n"
            "débiles enterradas en ruido, tanto en AM como en SSB.\n"
            "Sensibilidad configurable en pestaña Avanzada Ruido."),
        )
        self._chk_voice_leveler = _chk_sub(
            tr("Nivelador de voz  (compensa condiciones de banda)"),
            tr("AGC de voz después del cancelador: mantiene la voz limpia a nivel\n"
            "constante aunque el ruido (y por ende la cancelación) varíe.\n"
            "Solo adapta cuando detecta voz — el ruido residual entre\n"
            "transmisiones no se re-amplifica. Requiere cancelador activo."),
        )
        # (post) va aquí — refleja el orden real del pipeline:
        # cancelador → bandpass POST → EQ voz → excitador → gate de ruido
        self._chk_bandpass_post = _chk(
            tr("Filtro de paso de banda  (post)"),
            tr("Butterworth IIR después del cancelador de ruido — elimina fugas espectrales del STFT."),
        )
        self._chk_presence = _chk(
            tr("EQ Voz  (presencia + cuerpo)"),
            tr("Dos picos de realce vocal configurables en pestaña Avanzada Audio:\n"
            "  · Presencia (1000–2000 Hz): claridad e inteligibilidad\n"
            "  · Cuerpo (150–800 Hz): calidez y graves de la voz\n"
            "Cada banda con ganancia 0 dB queda en passthrough."),
        )
        self._chk_exciter = _chk(
            tr("Excitador armónico"),
            tr("Genera armónicos en 1–4 kHz para recuperar presencia y ataque de consonantes."),
        )
        # Modulo de primer nivel, NO sub-modulo del cancelador: el gate decide con
        # el nivel de entrada, que se mide siempre. El squelch que reemplaza si
        # dependia del cancelador (usaba su VAD) y por eso vivia indentado.
        self._chk_gate = _chk(
            tr("Gate de ruido  (baja el fondo entre transmisiones)"),
            tr("Atenúa la salida cuando el nivel de entrada no llega al umbral.\n"
               "Se calibra mirando el indicador de nivel, no a ciegas como el\n"
               "squelch que reemplaza. Ajustes en Avanzada Cancelador."),
        )
        self._chk_bass = _chk(
            tr("Recuperar graves"),
            tr("Devuelve el fundamental de la voz cuando el filtro de la radio ya lo cortó\n"
               "(un pasa-altos de 300 Hz deja un f0 de 120 Hz unos 32 dB abajo: no hay\n"
               "energía que una EQ pueda levantar). Lo DERIVA de los armónicos que sí\n"
               "pasaron, así que suena como parte de la voz y no como un tono agregado.\n"
               "Nivel ajustable en Avanzada Audio."),
        )

        self._chk_blanker.toggled.connect(lambda v: self._on_module_toggled("blanker_enabled", self._pipeline.set_blanker_enabled, v))
        self._chk_bandpass_pre.toggled.connect(lambda v: self._on_module_toggled("bandpass_pre_enabled", self._pipeline.set_bandpass_pre_enabled, v))
        self._chk_bandpass_post.toggled.connect(lambda v: self._on_module_toggled("bandpass_post_enabled", self._pipeline.set_bandpass_post_enabled, v))
        self._chk_anf.toggled.connect(lambda v: self._on_module_toggled("anf_enabled", self._pipeline.set_anf_enabled, v))
        self._chk_noise.toggled.connect(lambda v: self._on_module_toggled("noise_enabled", self._pipeline.set_noise_enabled, v))
        self._chk_perceptual_floor.toggled.connect(lambda v: self._on_module_toggled("perceptual_floor_enabled", self._pipeline.set_perceptual_floor_enabled, v))
        self._chk_post_filter.toggled.connect(lambda v: self._on_module_toggled("post_filter_enabled", self._pipeline.set_post_filter_enabled, v))
        self._chk_pitch_enhance.toggled.connect(lambda v: self._on_module_toggled("pitch_enhance_enabled", self._pipeline.set_pitch_enhance_enabled, v))
        self._chk_presence.toggled.connect(lambda v: self._on_module_toggled("presence_enabled", self._pipeline.set_presence_enabled, v))
        self._chk_gate.toggled.connect(lambda v: self._on_module_toggled("gate_enabled", self._pipeline.set_gate_enabled, v))
        self._chk_voice_leveler.toggled.connect(lambda v: self._on_module_toggled("voice_leveler_enabled", self._pipeline.set_voice_leveler_enabled, v))
        self._chk_exciter.toggled.connect(lambda v: self._on_module_toggled("exciter_enabled", self._pipeline.set_exciter_enabled, v))
        self._chk_bass.toggled.connect(lambda v: self._on_module_toggled("bass_enabled", self._pipeline.set_bass_enabled, v))

        return group

    def _build_noise_group(self) -> QGroupBox:
        group = QGroupBox(tr("Cancelación de Ruido Estacionario"))
        layout = QVBoxLayout(group)

        # Selector de modo de estimación de ruido
        mode_row = QHBoxLayout()
        mode_lbl = QLabel(tr("Modo:"))
        mode_lbl.setFixedWidth(_ROW_LABEL_W)
        self._combo_noise_mode = QComboBox()
        self._combo_noise_mode.setFixedWidth(_COMBO_W)
        self._combo_noise_mode.addItem(tr("Perfil estático"),   "static")
        self._combo_noise_mode.addItem(tr("Adaptativo (MCRA)"), "mcra")
        self._combo_noise_mode.setToolTip(
            tr("Perfil estático: aprendizaje manual de 5s.\n"
            "Adaptativo (MCRA): estima el ruido automáticamente en tiempo real,\n"
            "  se adapta a cambios de banda sin intervención del usuario.")
        )
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._combo_noise_mode)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Todos los botones del perfil en UNA fila compacta (ancho fijo + stretch).
        btn_row = QHBoxLayout()
        self._btn_learn = QPushButton(tr("⏺  Aprender ruido"))
        self._btn_learn.setCheckable(True)
        self._btn_learn.setEnabled(False)
        self._btn_learn.setFixedWidth(150)
        self._btn_learn.toggled.connect(self._on_learn_toggled)
        btn_row.addWidget(self._btn_learn)

        self._btn_clear_noise = QPushButton(tr("Borrar perfil"))
        self._btn_clear_noise.setEnabled(False)
        self._btn_clear_noise.setFixedWidth(110)
        self._btn_clear_noise.clicked.connect(self._on_clear_noise_profile)
        btn_row.addWidget(self._btn_clear_noise)

        self._btn_save_profile = QPushButton(tr("💾  Guardar perfil..."))
        self._btn_save_profile.setFixedWidth(150)
        self._btn_save_profile.setToolTip(
            tr("Guarda el perfil de ruido actual con un nombre, para reutilizarlo\n"
               "sin volver a aprenderlo (p. ej. \"40m casa\", \"20m campo\").")
        )
        self._btn_save_profile.clicked.connect(self._on_save_noise_profile)
        btn_row.addWidget(self._btn_save_profile)

        self._btn_load_profile = QPushButton(tr("📁  Perfiles..."))
        self._btn_load_profile.setFixedWidth(120)
        self._btn_load_profile.setToolTip(tr("Cargar, renombrar o eliminar perfiles de ruido guardados."))
        self._btn_load_profile.clicked.connect(self._on_manage_noise_profiles)
        btn_row.addWidget(self._btn_load_profile)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Nombre del perfil nombrado cargado (oculto si el perfil es aprendido a mano o no hay)
        self._label_profile_name = QLabel("")
        self._label_profile_name.setStyleSheet("color: #69f0ae; font-size: 8pt;")
        self._label_profile_name.setVisible(False)
        layout.addWidget(self._label_profile_name)

        self._combo_noise_mode.currentIndexChanged.connect(self._on_noise_mode_changed)

        layout.addSpacing(28)  # separa los botones de perfiles del slider Intensidad

        # SliderRow (largo fijo) para que alinee con Post-Filtro y el resto
        self._slider_noise = SliderRow(
            tr("Intensidad:"),
            min_val=0.0, max_val=100.0,
            default=DSPConfig().noise_alpha * 100.0,
            step=1.0, unit="%", fmt="{:.0f}",
        )
        self._slider_noise.valueChanged.connect(self._on_noise_intensity_changed)
        layout.addWidget(self._slider_noise)
        self._slider_noise.set_value(self._config.dsp.noise_alpha * 100.0)

        self._learn_countdown: int = 0
        self._learn_timer = QTimer()
        self._learn_timer.setInterval(1000)
        self._learn_timer.timeout.connect(self._on_learn_tick)

        db_row = QHBoxLayout()
        db_row.addWidget(QLabel(tr("Reducción activa:")))
        self._lbl_noise_db = QLabel("—")
        self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
        db_row.addWidget(self._lbl_noise_db)
        db_row.addStretch()
        layout.addLayout(db_row)

        # Post-filtro espectral: 2do control más impactante tras Intensidad. Movido
        # de Avanzada a Principal para el usuario casual. El slider AUTO-ACTIVA el
        # post-filtro al pasar de 0 (y lo apaga en 0) — ver _on_post_filter_strength.
        self._slider_post = SliderRow(
            tr("Post-Filtro:"),
            min_val=0.0, max_val=10.0,
            default=DSPConfig().post_filter_strength,
            step=0.1, unit="", fmt="{:.1f}",
        )
        self._slider_post._update_label = lambda v: self._slider_post._val_lbl.setText(
            f"{v:.1f}  ({tr('desactivado') if v == 0 else tr('suave') if v < 0.8 else tr('normal') if v < 2.0 else tr('agresivo') if v < 3.5 else tr('muy agresivo') if v < 6.5 else tr('máximo')})"
        )
        self._slider_post._val_lbl.setFixedWidth(130)
        self._slider_post.setToolTip(tr(
            "Hunde el piso de los bins de ruido: cada punto son ~4.5 dB más abajo\n"
            "(el fondo queda más silencioso y parejo, sin 'gorgojeo').\n"
            "0 = apagado. No toca los bins de voz. Se enciende solo al pasar de 0."))
        self._slider_post.valueChanged.connect(self._on_post_filter_strength)
        layout.addWidget(self._slider_post)
        self._slider_post.set_value(self._config.dsp.post_filter_strength)

        # "Reducción extra" a la izquierda y "Preview" centrado en la MISMA línea
        # (el preview refleja la reducción total = Intensidad + Post-Filtro, así que
        # va junto al indicador del post-filtro). Ambos en la misma celda del grid
        # con alineaciones distintas (izq / centro).
        extra_grid = QGridLayout()
        extra_grid.setContentsMargins(0, 0, 0, 0)
        extra_row = QHBoxLayout()
        extra_row.setContentsMargins(0, 0, 0, 0)
        extra_row.addWidget(QLabel(tr("Reducción extra:")))
        self._lbl_pf_extra = QLabel("—")
        self._lbl_pf_extra.setStyleSheet("color: #888; font-weight: bold;")
        extra_row.addWidget(self._lbl_pf_extra)
        extra_row.addStretch()
        extra_grid.addLayout(extra_row, 0, 0)

        self._chk_noise_preview = QCheckBox(tr("Preview: escuchar ruido eliminado"))
        self._chk_noise_preview.setToolTip(
            tr("Emite el ruido que está siendo restado (Intensidad + Post-Filtro).\n"
            "Si suena como voz, algo está de más: bajar la Intensidad (o el Post-Filtro).")
        )
        self._chk_noise_preview.toggled.connect(self._pipeline.set_noise_preview)
        extra_grid.addWidget(self._chk_noise_preview, 0, 0, alignment=Qt.AlignHCenter)
        layout.addLayout(extra_grid)

        self._label_noise = QLabel(tr("Sin perfil — activar procesamiento y presionar Aprender"))
        self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
        layout.addWidget(self._label_noise)

        self._noise_db_timer = QTimer(self)
        self._noise_db_timer.setInterval(500)
        self._noise_db_timer.timeout.connect(self._update_noise_db)
        self._noise_db_timer.start()

        return group

    def _build_level_group(self) -> QGroupBox:
        group = QGroupBox(tr("Niveles y Ganancia"))
        layout = QVBoxLayout(group)
        self._vu_in  = VuMeter(tr("IN "))
        self._vu_out = VuMeter(tr("OUT"))
        self._vu_in.setFixedWidth(_FIELD_W)
        self._vu_out.setFixedWidth(_FIELD_W)
        layout.addWidget(self._vu_in,  alignment=Qt.AlignLeft)
        layout.addWidget(self._vu_out, alignment=Qt.AlignLeft)
        self._label_latency = QLabel(tr("Latencia: --"))
        self._label_latency.setAlignment(Qt.AlignLeft)
        layout.addWidget(self._label_latency)

        # default = valor de fábrica (menú click derecho); la posición inicial
        # se carga aparte con set_value() desde la config persistida.
        _gain_def = GainConfig()
        self._s_gain_in = SliderRow(
            tr("Entrada:"),
            min_val=-20.0, max_val=20.0,
            default=_gain_def.input_gain_db,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_gain_out = SliderRow(
            tr("Salida:"),
            min_val=-20.0, max_val=20.0,
            default=_gain_def.output_gain_db,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_peak = SliderRow(
            tr("Límite de picos:"),
            min_val=-20.0, max_val=0.0,
            default=_gain_def.peak_limit_db,
            step=0.5, unit="dBFS", fmt="{:+.1f}",
        )
        self._s_gain_in.set_value(self._config.gain.input_gain_db)
        self._s_gain_out.set_value(self._config.gain.output_gain_db)
        self._s_peak.set_value(self._config.gain.peak_limit_db)
        self._s_gain_in.valueChanged.connect(self._on_gain_in_changed)
        self._s_gain_out.valueChanged.connect(self._on_gain_out_changed)
        self._s_peak.valueChanged.connect(self._on_peak_changed)
        layout.addWidget(self._s_gain_in)
        layout.addWidget(self._s_gain_out)
        layout.addWidget(self._s_peak)

        # Nivelador a la izquierda, Limitador a la derecha (más intuitivo). Las
        # etiquetas de valor tienen ancho fijo: al pasar a valores mayores (p. ej.
        # "ACTIVO  -12.3 dB") no empujan la etiqueta vecina de lugar.
        peak_row = QHBoxLayout()
        peak_row.setContentsMargins(0, 0, 0, 0)

        lbl_lev_title = QLabel(tr("Nivelador de voz:"))
        lbl_lev_title.setStyleSheet("color: #607d8b; font-size: 8pt;")
        lbl_lev_title.setFixedWidth(120)
        self._lbl_leveler = QLabel("—")
        self._lbl_leveler.setFixedWidth(70)
        self._lbl_leveler.setStyleSheet("color: #555; font-size: 8pt; font-weight: bold;")

        lbl_peak_title = QLabel(tr("Limitador de picos:"))
        lbl_peak_title.setStyleSheet("color: #607d8b; font-size: 8pt;")
        lbl_peak_title.setFixedWidth(120)
        self._lbl_peak_active = QLabel("—")
        self._lbl_peak_active.setFixedWidth(120)
        self._lbl_peak_active.setStyleSheet("color: #555; font-size: 8pt; font-weight: bold;")

        peak_row.addWidget(lbl_lev_title)
        peak_row.addWidget(self._lbl_leveler)
        peak_row.addSpacing(48)
        peak_row.addWidget(lbl_peak_title)
        peak_row.addWidget(self._lbl_peak_active)
        peak_row.addStretch()
        layout.addLayout(peak_row)

        # --- Grabación a WAV ---
        rec_row = QHBoxLayout()
        self._btn_record = QPushButton(tr("⏺  Grabar"))
        self._btn_record.setCheckable(True)
        self._btn_record.setEnabled(False)   # requiere procesamiento activo
        self._btn_record.setFixedWidth(_ACTION_BTN_W)
        self._btn_record.setToolTip(tr(
            "Graba la salida procesada a un archivo WAV (16-bit, 48 kHz)\n"
            "en la carpeta Grabaciones/, junto al ejecutable.\n"
            "Disponible con el procesamiento activo."
        ))
        self._btn_record.clicked.connect(self._on_record_toggled)
        rec_row.addWidget(self._btn_record)
        self._chk_record_raw = QCheckBox(tr("incluir entrada sin procesar"))
        self._chk_record_raw.setToolTip(tr(
            "Graba además un segundo WAV con la señal de entrada tal como\n"
            "llega de la radio — para comparar el antes/después.\n"
            "Se aplica al iniciar la próxima grabación."
        ))
        self._chk_record_raw.setChecked(self._config.audio.record_raw_input)
        self._chk_record_raw.toggled.connect(self._on_record_raw_toggled)
        rec_row.addWidget(self._chk_record_raw)   # pegado al botón Grabar
        self._lbl_rec_time = QLabel("")
        self._lbl_rec_time.setStyleSheet("color: #ef5350; font-weight: bold;")
        self._lbl_rec_time.setFixedWidth(80)
        rec_row.addWidget(self._lbl_rec_time)
        rec_row.addStretch()   # empuja el Mute a la derecha

        # --- Bypass (comparar crudo vs procesado) ---
        # Era una casilla en el grupo Control. Pasa a boton y se junta con Grabar y
        # Mute porque los tres son acciones de escucha que se aprietan y se sueltan
        # mientras se opera, no ajustes que se dejan puestos.
        # A diferencia de Grabar y Mute, NO se deshabilita con el proceso detenido:
        # dejarlo preparado antes de activar es util, y ademas la ganancia de salida
        # se recuerda por modo (ver _out_gain_by_bypass), asi que se puede calibrar
        # cada lado por separado sin audio.
        self._btn_bypass = QPushButton(tr("⇄  Bypass"))
        self._btn_bypass.setCheckable(True)
        self._btn_bypass.setFixedWidth(_ACTION_BTN_W)
        self._btn_bypass.setToolTip(tr(
            "Pasa la señal cruda de la radio, sin ningún procesamiento.\n"
            "Para comparar el antes y el después sin detener nada.\n"
            "La ganancia de salida se recuerda por separado en cada modo, así\n"
            "que se puede comparar a volumen parejo."
        ))
        self._btn_bypass.toggled.connect(self._on_bypass_toggled)
        rec_row.addWidget(self._btn_bypass)

        # --- Mute de salida (silencia los parlantes sin detener el proceso) ---
        self._btn_mute = QPushButton(tr("🔇  Mute"))
        self._btn_mute.setCheckable(True)
        self._btn_mute.setEnabled(False)   # requiere procesamiento activo
        self._btn_mute.setFixedWidth(_ACTION_BTN_W)
        self._btn_mute.setToolTip(tr(
            "Silencia la salida a los parlantes sin detener el procesamiento.\n"
            "Útil para una prueba corta: el proceso, la grabación y los\n"
            "medidores siguen corriendo — solo se corta el audio que se escucha."
        ))
        self._btn_mute.toggled.connect(self._on_mute_toggled)
        rec_row.addWidget(self._btn_mute)
        layout.addLayout(rec_row)

        return group

    def _build_spectrum_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()

        self._chk_spec_pre = QCheckBox(tr("Entrada"))
        self._chk_spec_pre.setChecked(True)
        self._chk_spec_pre.setStyleSheet("color: #42a5f5; font-weight: bold;")
        self._chk_spec_pre.toggled.connect(self._spectrum_widget.set_show_pre)

        self._chk_spec_post = QCheckBox(tr("Salida"))
        self._chk_spec_post.setChecked(True)
        self._chk_spec_post.setStyleSheet("color: #69f0ae; font-weight: bold;")
        self._chk_spec_post.toggled.connect(self._spectrum_widget.set_show_post)

        self._chk_spec_cancelled = QCheckBox(tr("Lo cancelado"))
        self._chk_spec_cancelled.setChecked(True)
        self._chk_spec_cancelled.setStyleSheet("color: #ff7043; font-weight: bold;")
        self._chk_spec_cancelled.toggled.connect(self._spectrum_widget.set_show_cancelled)

        self._chk_spec_floor = QCheckBox(tr("Piso de ruido"))
        self._chk_spec_floor.setChecked(True)
        self._chk_spec_floor.setStyleSheet("color: #ffd54f; font-weight: bold;")
        self._chk_spec_floor.toggled.connect(self._spectrum_widget.set_show_floor)

        # Cascada (waterfall) + selector de fuente Entrada/Salida
        self._chk_waterfall = QCheckBox(tr("Cascada"))
        self._chk_waterfall.setChecked(self._config.window.spectrum_show_waterfall)
        self._chk_waterfall.setStyleSheet("color: #b0bec5; font-weight: bold;")
        self._chk_waterfall.toggled.connect(self._on_waterfall_toggled)

        self._combo_waterfall_src = QComboBox()
        for label, data in ((tr("Entrada"), "input"),
                            (tr("Salida"), "output"),
                            (tr("Diferencia"), "diff")):
            self._combo_waterfall_src.addItem(label, data)
        _wf_idx = self._combo_waterfall_src.findData(self._config.window.waterfall_source)
        self._combo_waterfall_src.setCurrentIndex(max(0, _wf_idx))
        self._combo_waterfall_src.setEnabled(self._config.window.spectrum_show_waterfall)
        self._combo_waterfall_src.setToolTip(tr(
            "Qué se pinta en la cascada.\n"
            "Entrada / Salida: nivel de la señal, con la escala del slider Máx Y.\n"
            "Diferencia: cuánto QUITA el procesamiento en cada frecuencia\n"
            "(entrada − salida, escala fija ±30 dB). Cálido = se quitó señal;\n"
            "violeta = se amplificó; fondo = sin cambio. Un tinte violeta parejo\n"
            "en toda la banda es la ganancia de salida, no cancelación."))
        self._waterfall_widget.set_source_label(self._combo_waterfall_src.currentText())
        self._waterfall_widget.set_diff_mode(
            self._config.window.waterfall_source == "diff")
        self._combo_waterfall_src.currentIndexChanged.connect(self._on_waterfall_source_changed)

        self._combo_waterfall_hist = QComboBox()
        for secs in (15, 30, 60, 120):
            self._combo_waterfall_hist.addItem(f"{secs}s", secs)
        _wh = self._combo_waterfall_hist.findData(self._config.window.waterfall_history_sec)
        self._combo_waterfall_hist.setCurrentIndex(max(0, _wh))
        self._combo_waterfall_hist.setEnabled(self._config.window.spectrum_show_waterfall)
        self._combo_waterfall_hist.setToolTip(tr(
            "Profundidad de la cascada. Más historia = se ve el QSB y los\n"
            "heterodinos intermitentes a lo largo del tiempo; menos historia =\n"
            "más detalle temporal. No descarta lo ya capturado: es un zoom."))
        self._waterfall_widget.set_history_sec(self._config.window.waterfall_history_sec)
        self._combo_waterfall_hist.currentIndexChanged.connect(self._on_waterfall_hist_changed)

        ctrl.addWidget(self._chk_spec_pre)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._chk_spec_post)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._chk_spec_cancelled)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._chk_spec_floor)
        ctrl.addSpacing(18)
        ctrl.addWidget(self._chk_waterfall)
        ctrl.addWidget(self._combo_waterfall_src)
        ctrl.addWidget(self._combo_waterfall_hist)
        ctrl.addStretch()

        self._lbl_snr = QLabel(tr("S/N: —"))
        self._lbl_snr.setStyleSheet("color: #888; font-weight: bold;")
        self._lbl_snr.setToolTip(
            tr("Relación señal/ruido de banda completa (suavizada ~1s):\n"
            "señal actual vs piso de ruido estimado por el cancelador.\n"
            "Con solo ruido marca ~0 dB.")
        )
        ctrl.addWidget(self._lbl_snr)
        ctrl.addSpacing(16)

        lbl_hint = QLabel(tr("dBFS"))
        lbl_hint.setStyleSheet("color: #607d8b; font-size: 7pt;")
        ctrl.addWidget(lbl_hint)

        layout.addLayout(ctrl)

        # Espectro arriba, cascada abajo, con divisor arrastrable y ejes X
        # alineados (mismos márgenes/max_bin). La casilla "Cascada" la muestra/oculta.
        self._spectrum_splitter = QSplitter(Qt.Vertical)
        self._spectrum_splitter.addWidget(self._spectrum_widget)
        self._spectrum_splitter.addWidget(self._waterfall_widget)
        self._spectrum_splitter.setStretchFactor(0, 3)
        self._spectrum_splitter.setStretchFactor(1, 2)
        self._spectrum_splitter.setCollapsible(0, False)
        self._spectrum_splitter.setCollapsible(1, False)
        # Reparto inicial 50/50 (setStretchFactor solo actúa al redimensionar; sin
        # esto el splitter le da a la cascada su altura mínima en vez de su mitad).
        self._spectrum_splitter.setSizes([500, 500])
        self._waterfall_widget.setVisible(self._config.window.spectrum_show_waterfall)
        layout.addWidget(self._spectrum_splitter, 1)

        # Controles de zoom — widget compacto sin espacio extra
        zoom_widget = QWidget()
        zoom_widget.setFixedHeight(44)
        zoom_layout = QVBoxLayout(zoom_widget)
        zoom_layout.setContentsMargins(0, 2, 0, 2)
        zoom_layout.setSpacing(2)

        def _slider_row(label_text, lbl_attr, sld_attr, mn, mx, step, page, val, lbl_text, lbl_w, handler):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #607d8b; font-size: 8pt;")
            lbl.setFixedWidth(40)
            val_lbl = QLabel(lbl_text)
            val_lbl.setStyleSheet("color: #90a4ae; font-size: 8pt;")
            val_lbl.setFixedWidth(lbl_w)
            sld = QSlider(Qt.Horizontal)
            sld.setMinimum(mn); sld.setMaximum(mx)
            sld.setSingleStep(step); sld.setPageStep(page)
            sld.setValue(val)
            sld.setMaximumHeight(18)
            sld.valueChanged.connect(handler)
            row.addWidget(lbl)
            row.addWidget(sld)
            row.addWidget(val_lbl)
            setattr(self, lbl_attr, val_lbl)
            setattr(self, sld_attr, sld)
            return row

        zoom_layout.addLayout(_slider_row(
            tr("Máx Y:"), "_lbl_db_range", "_sld_db_range",
            -60, 0, 5, 10, self._config.window.spectrum_db_max,
            f"{self._config.window.spectrum_db_max} dBFS", 52,
            self._on_db_range_changed,
        ))
        zoom_layout.addLayout(_slider_row(
            tr("Máx X:"), "_lbl_freq_range", "_sld_freq_range",
            1, 12, 1, 2, self._config.window.spectrum_max_freq_hz // 1000,
            f"{self._config.window.spectrum_max_freq_hz // 1000} kHz", 40,
            self._on_freq_range_changed,
        ))

        # Aplicar el zoom persistido al widget: setValue() en _slider_row corre
        # ANTES del connect(), así que el valor restaurado no dispara el handler
        # y el gráfico quedaba con los defaults hasta tocar los sliders.
        self._spectrum_widget.set_db_max(self._config.window.spectrum_db_max)
        self._spectrum_widget.set_max_freq_hz(self._config.window.spectrum_max_freq_hz)
        self._waterfall_widget.set_db_max(self._config.window.spectrum_db_max)
        self._waterfall_widget.set_max_freq_hz(self._config.window.spectrum_max_freq_hz)

        layout.addWidget(zoom_widget)
        return tab

    def _build_start_button(self) -> QPushButton:
        self._btn_start = QPushButton(tr("▶  ACTIVAR"))
        self._btn_start.setMinimumHeight(44)
        self._btn_start.setEnabled(False)
        self._btn_start.setCheckable(True)
        self._btn_start.clicked.connect(self._on_toggle_processing)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self._btn_start.setFont(font)
        return self._btn_start

    # ------------------------------------------------------------------
    # Dispositivos y config guardada
    # ------------------------------------------------------------------

    def _populate_devices(self) -> None:
        self._fill_device_combos(list_devices())
        self._combo_in.currentIndexChanged.connect(self._on_input_device_changed)
        self._combo_out.currentIndexChanged.connect(self._on_output_device_changed)
        self._on_input_device_changed(0)
        self._on_output_device_changed(0)

    def _fill_device_combos(self, devices: list[AudioDevice]) -> None:
        """Limpia y repuebla ambos combos. El caller maneja las señales
        (en el primer populate aún no están conectadas; en el refresh van
        bloqueadas para no disparar handlers por cada addItem)."""
        for combo in (self._combo_in, self._combo_out):
            combo.clear()
        for dev in devices:
            if dev.supports_input():
                self._combo_in.addItem(dev.display_name(), dev)
            if dev.supports_output():
                self._combo_out.addItem(dev.display_name(), dev)

    def _on_refresh_devices(self) -> None:
        if self._pipeline.is_running():
            return  # el botón se deshabilita al activar; guard por las dudas
        prev_in:  AudioDevice | None = self._combo_in.currentData()
        prev_out: AudioDevice | None = self._combo_out.currentData()
        try:
            devices = rescan_devices()
        except Exception as e:
            self._status_bar.showMessage(tr("Error al re-enumerar dispositivos: {e}").format(e=e))
            return

        for combo in (self._combo_in, self._combo_out):
            combo.blockSignals(True)
        self._fill_device_combos(devices)
        # Restaurar la selección por nombre — el índice PortAudio puede
        # cambiar tras la reinicialización (hardware agregado/quitado).
        self._select_device_by_name(self._combo_in, prev_in)
        self._select_device_by_name(self._combo_out, prev_out)
        for combo in (self._combo_in, self._combo_out):
            combo.blockSignals(False)

        # Empujar la selección al pipeline (los índices pueden ser nuevos)
        self._on_input_device_changed(self._combo_in.currentIndex())
        self._on_output_device_changed(self._combo_out.currentIndex())
        self._status_bar.showMessage(
            tr("Dispositivos actualizados: {n} de entrada, {m} de salida.").format(
                n=self._combo_in.count(), m=self._combo_out.count())
        )

    @staticmethod
    def _select_device_by_name(combo: QComboBox, prev: "AudioDevice | None") -> None:
        if prev is None:
            return
        for i in range(combo.count()):
            dev: AudioDevice = combo.itemData(i)
            if dev and dev.name == prev.name:
                combo.setCurrentIndex(i)
                return

    def _apply_loaded_config(self) -> None:
        for cb, key, setter in [
            (self._chk_blanker,  "blanker_enabled",  self._pipeline.set_blanker_enabled),
            (self._chk_bandpass_pre,  "bandpass_pre_enabled",  self._pipeline.set_bandpass_pre_enabled),
            (self._chk_bandpass_post, "bandpass_post_enabled", self._pipeline.set_bandpass_post_enabled),
            (self._chk_anf,      "anf_enabled",      self._pipeline.set_anf_enabled),
            (self._chk_noise,        "noise_enabled",        self._pipeline.set_noise_enabled),
            (self._chk_perceptual_floor, "perceptual_floor_enabled", self._pipeline.set_perceptual_floor_enabled),
            (self._chk_post_filter,      "post_filter_enabled",      self._pipeline.set_post_filter_enabled),
            (self._chk_pitch_enhance, "pitch_enhance_enabled", self._pipeline.set_pitch_enhance_enabled),
            (self._chk_presence,      "presence_enabled",      self._pipeline.set_presence_enabled),
            (self._chk_gate,     "gate_enabled",      self._pipeline.set_gate_enabled),
            (self._chk_voice_leveler, "voice_leveler_enabled", self._pipeline.set_voice_leveler_enabled),
            (self._chk_exciter,  "exciter_enabled",   self._pipeline.set_exciter_enabled),
            (self._chk_bass,     "bass_enabled",      self._pipeline.set_bass_enabled),
        ]:
            val = getattr(self._config.dsp, key)
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
            setter(val)

        self._refresh_bandpass_combo()

        for i in range(self._combo_agc.count()):
            if self._combo_agc.itemData(i) == self._config.dsp.agc_preset:
                self._combo_agc.setCurrentIndex(i)
                break

        # Restaurar modo de ruido y visibilidad de controles
        for i in range(self._combo_noise_mode.count()):
            if self._combo_noise_mode.itemData(i) == self._config.dsp.noise_mode:
                self._combo_noise_mode.blockSignals(True)
                self._combo_noise_mode.setCurrentIndex(i)
                self._combo_noise_mode.blockSignals(False)
                break
        self._pipeline.set_noise_mode(self._config.dsp.noise_mode)
        self._refresh_noise_profile_ui()
        if self._config.dsp.noise_mode != "static":
            self._label_noise.setText(tr("Adaptativo (MCRA) — activar procesamiento para calibrar"))

        for i in range(self._combo_channel.count()):
            if self._combo_channel.itemData(i) == self._config.audio.input_channel:
                self._combo_channel.blockSignals(True)
                self._combo_channel.setCurrentIndex(i)
                self._combo_channel.blockSignals(False)
                break

        if self._saved_input_device is not None:
            for i in range(self._combo_in.count()):
                dev: AudioDevice = self._combo_in.itemData(i)
                if dev and dev.index == self._saved_input_device:
                    self._combo_in.setCurrentIndex(i)
                    break
        if self._saved_output_device is not None:
            for i in range(self._combo_out.count()):
                dev: AudioDevice = self._combo_out.itemData(i)
                if dev and dev.index == self._saved_output_device:
                    self._combo_out.setCurrentIndex(i)
                    break

    def refresh_from_config(self) -> None:
        """Actualiza toda la UI con los valores actuales de self._config.
        Llamado tras cargar un preset en caliente. No toca los combos de dispositivos."""
        cfg = self._config.dsp

        # --- Checkboxes de módulos ---
        for cb, key, setter in [
            (self._chk_blanker,           "blanker_enabled",           self._pipeline.set_blanker_enabled),
            (self._chk_bandpass_pre,      "bandpass_pre_enabled",      self._pipeline.set_bandpass_pre_enabled),
            (self._chk_bandpass_post,     "bandpass_post_enabled",     self._pipeline.set_bandpass_post_enabled),
            (self._chk_anf,               "anf_enabled",               self._pipeline.set_anf_enabled),
            (self._chk_noise,             "noise_enabled",             self._pipeline.set_noise_enabled),
            (self._chk_perceptual_floor,  "perceptual_floor_enabled",  self._pipeline.set_perceptual_floor_enabled),
            (self._chk_post_filter,       "post_filter_enabled",       self._pipeline.set_post_filter_enabled),
            (self._chk_pitch_enhance,     "pitch_enhance_enabled",     self._pipeline.set_pitch_enhance_enabled),
            (self._chk_presence,          "presence_enabled",          self._pipeline.set_presence_enabled),
            (self._chk_gate,              "gate_enabled",              self._pipeline.set_gate_enabled),
            (self._chk_voice_leveler,     "voice_leveler_enabled",     self._pipeline.set_voice_leveler_enabled),
            (self._chk_exciter,           "exciter_enabled",           self._pipeline.set_exciter_enabled),
            (self._chk_bass,              "bass_enabled",              self._pipeline.set_bass_enabled),
        ]:
            val = getattr(cfg, key)
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
            setter(val)

        # --- Pasabanda ---
        # Los limites ya los aplico apply_config(); aca solo se sincroniza el combo.
        self._refresh_bandpass_combo()

        # --- AGC ---
        for i in range(self._combo_agc.count()):
            if self._combo_agc.itemData(i) == cfg.agc_preset:
                self._combo_agc.blockSignals(True)
                self._combo_agc.setCurrentIndex(i)
                self._combo_agc.blockSignals(False)
                break

        # --- Modo de ruido ---
        for i in range(self._combo_noise_mode.count()):
            if self._combo_noise_mode.itemData(i) == cfg.noise_mode:
                self._combo_noise_mode.blockSignals(True)
                self._combo_noise_mode.setCurrentIndex(i)
                self._combo_noise_mode.blockSignals(False)
                break
        self._refresh_noise_profile_ui()
        if cfg.noise_mode != "static":
            self._label_noise.setText(tr("Adaptativo (MCRA) — estimando en tiempo real"))

        # --- Sliders Intensidad + Post-Filtro (sin emitir: no re-disparar handlers) ---
        self._slider_noise.set_value(cfg.noise_alpha * 100.0)
        self._slider_post.set_value(cfg.post_filter_strength)
        self._chk_leveler_continuous.blockSignals(True)
        self._chk_leveler_continuous.setChecked(not cfg.voice_leveler_gate_voice)
        self._chk_leveler_continuous.blockSignals(False)
        self._refresh_control_gating()
        self._chk_agc_ceiling.blockSignals(True)
        self._chk_agc_ceiling.setChecked(cfg.agc_noise_ceiling_enabled)
        self._chk_agc_ceiling.blockSignals(False)
        self._s_agc_ceiling.set_value(cfg.agc_noise_ceiling_db)
        self._s_agc_ceiling.set_enabled(cfg.agc_noise_ceiling_enabled)

        # --- Sliders de ganancia ---
        self._s_gain_in.set_value(self._config.gain.input_gain_db)
        self._s_gain_out.set_value(self._config.gain.output_gain_db)
        self._s_peak.set_value(self._config.gain.peak_limit_db)
        # Cargar un preset resetea el slot de PROCESADO (el preset lo trae),
        # pero conserva el de bypass: un preset describe como procesas, no a que
        # volumen escuchas la senal cruda.
        self._out_gain_by_bypass[False] = self._config.gain.output_gain_db

        # --- Pestanas avanzadas ---
        self._adv_audio_tab.reload()
        self._adv_impulse_tab.reload()
        self._adv_canceller_tab.reload()

        self._schedule_save()

    # ------------------------------------------------------------------
    # Eventos de la UI
    # ------------------------------------------------------------------

    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            if not self._pipeline.is_running():
                self._btn_record.setChecked(False)
                return
            try:
                self._pipeline.start_recording()
            except OSError as e:
                self._btn_record.setChecked(False)
                self._status_bar.showMessage(
                    tr("Error al iniciar la grabación: {e}").format(e=e))
                return
            self._btn_record.setText(tr("⏹  Detener"))
            self._status_bar.showMessage(tr("Grabando en Grabaciones/ ..."))
        else:
            self._finish_recording()

    def _finish_recording(self) -> None:
        """Cierra la grabación y resetea la UI. Seguro de llamar siempre."""
        secs = self._pipeline.stop_recording()
        self._btn_record.setChecked(False)
        self._btn_record.setText(tr("⏺  Grabar"))
        self._lbl_rec_time.setText("")
        if secs > 0:
            self._status_bar.showMessage(
                tr("Grabación guardada en Grabaciones/  ({s:.0f} s)").format(s=secs))

    def _on_record_raw_toggled(self, checked: bool) -> None:
        self._config.audio.record_raw_input = bool(checked)
        self._schedule_save()

    def _on_input_channel_changed(self, idx: int) -> None:
        mode = self._combo_channel.itemData(idx)
        self._pipeline.set_input_channel(mode)
        self._schedule_save()

    def _on_input_device_changed(self, idx: int) -> None:
        dev: AudioDevice | None = self._combo_in.itemData(idx)
        self._pipeline.set_input_device(dev)
        self._check_device_compatibility()
        self._schedule_save()

    def _on_output_device_changed(self, idx: int) -> None:
        dev: AudioDevice | None = self._combo_out.itemData(idx)
        self._pipeline.set_output_device(dev)
        self._check_device_compatibility()
        self._schedule_save()

    def _check_device_compatibility(self) -> None:
        """Aviso proactivo de combinación de APIs incompatibles (-9993).

        Si la entrada y la salida están en APIs de host distintas — combinación
        que PortAudio rechaza en un stream full-duplex — deshabilita ACTIVAR,
        marca ambos combos y muestra el motivo en la barra de estado, antes de
        que el usuario intente arrancar. Se re-evalúa al cambiar cualquiera de
        los dos dispositivos. Solo consulta PortAudio (query_devices), no abre
        nada. No corre con el stream ya abierto (los combos están deshabilitados).
        """
        if self._pipeline.is_running():
            return
        in_dev: AudioDevice | None = self._combo_in.currentData()
        out_dev: AudioDevice | None = self._combo_out.currentData()
        mismatch = (duplex_hostapi_mismatch(in_dev.index, out_dev.index)
                    if in_dev is not None and out_dev is not None else None)
        if mismatch is not None:
            in_api, out_api = mismatch
            msg = tr(
                "La entrada ({in_api}) y la salida ({out_api}) usan APIs de audio "
                "distintas y no se pueden combinar en un mismo stream. Elegí ambos "
                "dispositivos de la misma API (por ejemplo, los dos [WASAPI])."
            ).format(in_api=in_api, out_api=out_api)
            self._btn_start.setEnabled(False)
            self._btn_start.setToolTip(msg)
            self._combo_in.setStyleSheet(_COMBO_WARN_STYLE)
            self._combo_out.setStyleSheet(_COMBO_WARN_STYLE)
            self._status_bar.showMessage(msg)
            self._devices_incompatible = True
        else:
            self._btn_start.setEnabled(True)
            self._btn_start.setToolTip("")
            self._combo_in.setStyleSheet("")
            self._combo_out.setStyleSheet("")
            # Solo limpiar el aviso si veníamos de un estado incompatible —
            # no pisar otros mensajes (p. ej. "Perfil cargado") en el arranque.
            if getattr(self, "_devices_incompatible", False):
                self._status_bar.showMessage(tr("Dispositivos compatibles. Listo para ACTIVAR."))
            self._devices_incompatible = False

    def _on_language_changed(self, idx: int) -> None:
        lang = self._combo_lang.itemData(idx)
        if lang == self._config.language:
            return
        self._config.language = lang
        self._schedule_save()
        self._status_bar.showMessage(
            tr("Idioma guardado — reiniciar la aplicación para aplicarlo.")
            if lang == "es" else
            "Language saved — restart the application to apply it."
        )

    def _on_ui_scale_changed(self, idx: int) -> None:
        scale = self._combo_ui_scale.itemData(idx)
        if scale is None or scale == self._config.window.ui_scale:
            return
        self._config.window.ui_scale = float(scale)
        self._schedule_save()
        self._status_bar.showMessage(tr(
            "Tamaño de la interfaz guardado ({pct} %) — reiniciar la aplicación "
            "para aplicarlo.").format(pct=round(scale * 100)))

    def _available_ui_scales(self) -> tuple:
        """Escalas ofrecidas en el combo, según el ancho real de la pantalla."""
        scr = QApplication.primaryScreen()
        if scr is None:
            return UI_SCALES
        ancho_real = scr.availableGeometry().width() * self._applied_ui_scale
        return ui_scales_that_fit(ancho_real, self._applied_ui_scale)

    def _show_about(self) -> None:
        from buildinfo import BUILD_ID
        ver = QApplication.instance().applicationVersion()
        html = (
            "<b>RadioNoiseKiller</b><br>"
            + tr("Versión {ver} · build {build}").format(ver=ver, build=BUILD_ID)
            + "<br><br>"
            + tr("Reductor de ruido para radio AM/SSB (ham radio).") + "<br>"
            + tr("DSP puro numpy/scipy — sin IA ni modelos externos.") + "<br><br>"
            + tr("Autor: Germán Pagliaroli") + " — LU6APA<br>"
            + "<a href='https://github.com/gpagliaroli/RadioNoiseKiller'>"
              "github.com/gpagliaroli/RadioNoiseKiller</a>"
        )
        box = QMessageBox(self)
        box.setWindowTitle(tr("Acerca de"))
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        pix = self.windowIcon().pixmap(64, 64)
        if not pix.isNull():
            box.setIconPixmap(pix)
        else:
            box.setIcon(QMessageBox.Icon.Information)

        # Botón de donación. Sin URL configurada no se agrega (ver _DONATE_URL):
        # más vale que no esté a que lleve a una página rota.
        btn_donar = None
        if _DONATE_URL:
            btn_donar = box.addButton(tr("☕ Invitame un café"),
                                      QMessageBox.ButtonRole.ActionRole)
            # La URL va en el tooltip a propósito: si openUrl falla (xdg-open mal
            # configurado en algún Linux) el botón no haría NADA visible. Así al
            # menos se puede leer y copiar a mano.
            btn_donar.setToolTip(
                tr("Abre la página de donación en el navegador") + "\n" + _DONATE_URL)
        box.addButton(QMessageBox.StandardButton.Ok)

        box.exec()
        # Los botones ActionRole cierran el diálogo, así que el navegador se abre
        # después de exec(); QDesktopServices lo lanza sin bloquear la UI.
        if btn_donar is not None and box.clickedButton() is btn_donar:
            QDesktopServices.openUrl(QUrl(_DONATE_URL))

    def _on_bandpass_preset(self, idx: int) -> None:
        nombre = self._combo_bandpass.itemData(idx)
        if nombre == BANDPASS_CUSTOM:
            # "Personalizado" no cambia nada: los limites los manda Avanzada Audio.
            self._config.dsp.bandpass_preset = BANDPASS_CUSTOM
        else:
            self._pipeline.set_bandpass_preset(nombre)
            if hasattr(self, "_adv_audio_tab"):
                self._adv_audio_tab.reload()
        self._schedule_save()

    def _refresh_bandpass_combo(self) -> None:
        """Pone el combo en el preset que corresponde a los limites actuales.

        Con señales bloqueadas: se llama al cargar un preset y cuando los sliders
        de Avanzada Audio cambian los limites, y sin el bloqueo el propio combo
        volveria a aplicar el preset (bucle).
        """
        objetivo = self._config.dsp.bandpass_preset
        self._combo_bandpass.blockSignals(True)
        for i in range(self._combo_bandpass.count()):
            if self._combo_bandpass.itemData(i) == objetivo:
                self._combo_bandpass.setCurrentIndex(i)
                break
        self._combo_bandpass.blockSignals(False)

    def _on_post_filter_strength(self, val: float) -> None:
        self._config.dsp.post_filter_strength = val
        self._pipeline.set_post_filter_strength(val)
        # Auto-activar: subir de 0 enciende el post-filtro; en 0 lo apaga. Sincroniza
        # el checkbox de Módulos (sigue siendo el enable "oficial" del sub-módulo).
        want = val > 0.0
        if want != self._config.dsp.post_filter_enabled:
            self._chk_post_filter.setChecked(want)   # dispara _on_module_toggled
        self._schedule_save()

    def _on_agc_changed(self, idx: int) -> None:
        preset = self._combo_agc.itemData(idx)
        self._config.dsp.agc_preset = preset
        self._pipeline.set_agc_preset(preset)
        if preset == "off":
            self._label_agc_gain.setText("—")
        self._schedule_save()

    def _on_module_toggled(self, key: str, setter, checked: bool) -> None:
        setattr(self._config.dsp, key, checked)
        setter(checked)
        # Reflejar el estado en los controles de las pestañas Avanzadas
        # (guard: los checkboxes pueden inicializarse antes de crear las tabs)
        if hasattr(self, "_adv_canceller_tab"):
            self._adv_audio_tab.refresh_enabled_states()
            self._adv_impulse_tab.refresh_enabled_states()
            self._adv_canceller_tab.refresh_enabled_states()
        self._refresh_control_gating()
        self._schedule_save()

    def _refresh_control_gating(self) -> None:
        """Gating de los controles del grupo Control que dependen de un módulo.
        'Nivelar en continuo' solo aplica con el nivelador activo, que a su vez
        necesita el cancelador (su VAD vive ahí — invariante 2)."""
        if not hasattr(self, "_chk_leveler_continuous"):
            return
        d = self._config.dsp
        self._chk_leveler_continuous.setEnabled(
            d.noise_enabled and d.voice_leveler_enabled)

    def _on_gain_in_changed(self, val: float) -> None:
        self._config.gain.input_gain_db = val
        self._pipeline.set_input_gain_db(val)
        self._schedule_save()

    def _on_gain_out_changed(self, val: float) -> None:
        self._config.gain.output_gain_db = val
        self._pipeline.set_output_gain_db(val)
        # Recordar el valor para el modo bypass actual (A/B a nivel parejo).
        self._out_gain_by_bypass[self._btn_bypass.isChecked()] = val
        self._schedule_save()

    def _on_bypass_toggled(self, checked: bool) -> None:
        # Guardar la ganancia de salida del modo que dejamos y restaurar la del
        # modo destino, para comparar bypass ON/OFF a nivel parejo sin reajustar.
        # set_value(emit=False) mueve el slider sin disparar _on_gain_out_changed;
        # empujamos config/pipeline a mano.
        self._out_gain_by_bypass[not checked] = self._s_gain_out.value()
        self._pipeline.set_bypass(checked)
        self._refresh_bypass_button(checked)
        if checked:
            self._status_bar.showMessage(
                tr("Bypass activo — se escucha la señal cruda, sin procesar."))
        target = self._out_gain_by_bypass[checked]
        if target != self._s_gain_out.value():
            self._s_gain_out.set_value(target)
            self._config.gain.output_gain_db = target
            self._pipeline.set_output_gain_db(target)
            self._schedule_save()

    def _on_peak_changed(self, val: float) -> None:
        self._config.gain.peak_limit_db = val
        self._pipeline.set_peak_limit_db(val)
        self._schedule_save()

    def _on_noise_intensity_changed(self, value: float) -> None:
        alpha = value / 100.0
        self._config.dsp.noise_alpha = alpha
        self._pipeline.set_noise_alpha(alpha)
        self._schedule_save()

    # ------------------------------------------------------------------
    # UI del perfil de ruido — fuente única de verdad
    # ------------------------------------------------------------------

    def _refresh_noise_profile_ui(self) -> None:
        """Sincroniza label + botones de perfil con el estado real del pipeline.
        Idempotente; se puede llamar desde cualquier lugar."""
        is_static  = self._config.dsp.noise_mode == "static"
        is_running = self._pipeline.is_running()
        learning   = self._pipeline.noise_is_learning
        has_prof   = self._pipeline.noise_has_profile

        self._btn_learn.setVisible(is_static)
        self._btn_clear_noise.setVisible(is_static)
        self._btn_save_profile.setVisible(is_static)
        self._btn_load_profile.setVisible(is_static)
        # Guardar: solo con perfil presente. Cargar: siempre (fuerza modo estático).
        self._btn_save_profile.setEnabled(is_static and has_prof and not learning)
        self._btn_load_profile.setEnabled(is_static and not learning
                                          and bool(self._noise_profile_manager.list_names()))

        # Nombre del perfil cargado: solo con perfil nombrado activo (no aprendido a mano)
        show_name = (is_static and has_prof and not learning
                     and bool(self._active_noise_profile_name))
        self._label_profile_name.setVisible(show_name)
        if show_name:
            self._label_profile_name.setText(
                tr("📁  Perfil cargado:  «{name}»").format(name=self._active_noise_profile_name))

        if not is_static:
            return

        # Aprender habilitado mientras corre (checked/unchecked controla start/stop)
        self._btn_learn.setEnabled(is_running)
        # Borrar habilitado solo si hay perfil y no estamos aprendiendo
        self._btn_clear_noise.setEnabled(has_prof and not learning)

        if learning:
            return  # _on_learn_toggled gestiona el texto durante el conteo

        if has_prof:
            dur = self._pipeline.noise_duration_ms / 1000.0
            self._label_noise.setText(tr("Perfil activo: {dur:.1f}s aprendidos — sustracción ON").format(dur=dur))
            self._label_noise.setStyleSheet("color: #69f0ae; font-size: 8pt;")
        elif is_running:
            self._label_noise.setText(tr("Sin perfil — presionar Aprender para calibrar"))
            self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
        else:
            self._label_noise.setText(tr("Sin perfil — activar procesamiento y presionar Aprender"))
            self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")

    # ------------------------------------------------------------------
    # Handlers de ruido
    # ------------------------------------------------------------------

    def _on_noise_mode_changed(self, idx: int) -> None:
        mode = self._combo_noise_mode.itemData(idx)
        self._pipeline.set_noise_mode(mode)
        self._spectrum_widget.clear_floor()
        # Tres sliders de Avanzada Cancelador sólo actúan en Adaptativo (tocan λ_d),
        # así que el cambio de modo tiene que re-evaluar el gating — si no, quedan
        # habilitados y sin efecto. Guard por si el combo se inicializa antes de las tabs.
        if hasattr(self, "_adv_canceller_tab"):
            self._adv_canceller_tab.refresh_enabled_states()
        if mode != "static":
            self._btn_learn.setVisible(False)
            self._btn_clear_noise.setVisible(False)
            self._btn_save_profile.setVisible(False)
            self._btn_load_profile.setVisible(False)
            self._label_profile_name.setVisible(False)
            self._label_noise.setText(tr("Adaptativo (MCRA) — activar procesamiento para calibrar"))
            self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
        else:
            self._refresh_noise_profile_ui()
        self._schedule_save()

    def _on_learn_toggled(self, checked: bool) -> None:
        if checked:
            # El perfil activo pasa a ser uno aprendido a mano: ya no es el nombrado cargado
            self._active_noise_profile_name = None
            self._learn_countdown = 5
            self._pipeline.start_noise_learning()
            self._spectrum_widget.start_floor_learning()
            self._btn_learn.setText(tr("⏹  Aprendiendo... {s}s").format(s=self._learn_countdown))
            self._label_noise.setText(tr("Aprendiendo ruido — mantener silencio en la banda"))
            self._label_noise.setStyleSheet("color: #ffd600; font-size: 8pt;")
            self._btn_clear_noise.setEnabled(False)
            self._learn_timer.start()
        else:
            self._learn_timer.stop()
            self._pipeline.stop_noise_learning()
            self._spectrum_widget.stop_floor_learning()
            self._btn_learn.setText(tr("⏺  Aprender ruido"))
            self._refresh_noise_profile_ui()

    def _on_learn_tick(self) -> None:
        self._learn_countdown -= 1
        if self._learn_countdown > 0:
            self._btn_learn.setText(tr("⏹  Aprendiendo... {s}s").format(s=self._learn_countdown))
        else:
            self._btn_learn.setChecked(False)

    def _update_pf_extra(self) -> None:
        """Indicador Reducción extra del post-filtro (movido de Avanzada a Principal)."""
        if self._config.dsp.post_filter_enabled and self._pipeline.is_running():
            extra_db = self._pipeline.post_filter_extra_db
            if extra_db < -0.5:
                self._lbl_pf_extra.setText(f"{extra_db:.1f} dB")
                color_ex = "#69f0ae" if extra_db < -5 else "#fff176"
                self._lbl_pf_extra.setStyleSheet(f"color: {color_ex}; font-weight: bold;")
            else:
                self._lbl_pf_extra.setText(tr("0 dB  (sin ruido activo)"))
                self._lbl_pf_extra.setStyleSheet("color: #888;")
        else:
            self._lbl_pf_extra.setText(tr("—  (desactivado)"))
            self._lbl_pf_extra.setStyleSheet("color: #888;")

    def _update_noise_db(self) -> None:
        self._update_pf_extra()
        # Mientras el aviso de error del DSP esté vigente no se pisa el cartel
        # (ver _check_dsp_errors): decir "calibrando" cuando en realidad está
        # fallando es exactamente lo que hizo el bug indescifrable.
        if self._dsp_error_hold > 0:
            self._dsp_error_hold -= 1
            return
        mode = self._pipeline.noise_mode

        if not self._pipeline.is_running():
            self._lbl_noise_db.setText("—")
            self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
            if mode == "mcra":
                self._label_noise.setText(tr("Adaptativo (MCRA) — activar procesamiento para calibrar"))
                self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
            return

        if mode == "mcra":
            if self._pipeline.noise_has_profile:
                self._mcra_wait = 0
                self._mcra_stall_logged = False
                db = self._pipeline.noise_reduction_db
                if db >= -0.5:
                    self._lbl_noise_db.setText(tr("~0 dB"))
                    self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
                elif db >= -3.0:
                    self._lbl_noise_db.setText(f"{db:.1f} dB")
                    self._lbl_noise_db.setStyleSheet("color: #fff176; font-weight: bold;")
                else:
                    self._lbl_noise_db.setText(f"{db:.1f} dB")
                    self._lbl_noise_db.setStyleSheet("color: #69f0ae; font-weight: bold;")
                self._label_noise.setText(tr("Adaptativo (MCRA) — estimando en tiempo real"))
                self._label_noise.setStyleSheet("color: #69f0ae; font-size: 8pt;")
                # Actualizar piso de ruido en el espectro con el estimado MCRA actual
                floor_data = self._pipeline.get_noise_floor_data()
                if floor_data is not None:
                    self._spectrum_widget.set_noise_floor_from_hz(*floor_data)
            else:
                self._lbl_noise_db.setText("—")
                self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
                if self._pipeline.bypass:
                    # En Bypass el audio no entra al hilo procesador, asi que el
                    # cancelador no corre y el estimador NO PUEDE calibrar: es
                    # correcto, no una falla. Faltaba este caso y el aviso rojo
                    # salia cada vez que se dejaba el bypass puesto unos segundos
                    # para comparar — con la firma exacta de un fallo real
                    # (frames=0, quar=0, lambda_d=None, con audio y sin errores).
                    # Tampoco se cuentan ticks: al salir del bypass tiene que
                    # empezar de cero, no arrancar ya en rojo.
                    self._mcra_wait = 0
                    self._label_noise.setText(
                        tr("Adaptativo (MCRA) — en Bypass no calibra (el cancelador no corre)"))
                    self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
                    return
                self._mcra_wait += 1
                # El warmup son ~200 ms. Pasados unos segundos, seguir diciendo
                # "calibrando" es mentir: hay que decir POR QUÉ no calibra. Sin
                # esto el usuario ve el cancelador inerte y el cartel tranquilo
                # (fue justo el síntoma que costó diagnosticar en el aire).
                if self._mcra_wait < _MCRA_WAIT_TICKS:
                    self._label_noise.setText(tr("Adaptativo (MCRA) — calibrando (~200ms)..."))
                    self._label_noise.setStyleSheet("color: #ffd600; font-size: 8pt;")
                else:
                    self._label_noise.setText(self._mcra_stall_reason())
                    self._label_noise.setStyleSheet("color: #ef5350; font-size: 8pt; font-weight: bold;")
            return

        # Modo estático — auto-corrige label/botones cada 500ms
        self._refresh_noise_profile_ui()
        if not self._pipeline.noise_has_profile:
            self._lbl_noise_db.setText("—")
            self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
            return
        # Mostrar curva de piso en el espectro (se actualiza solo cuando cambia o al reiniciar)
        if not self._spectrum_widget.has_floor:
            floor_data = self._pipeline.get_noise_floor_data()
            if floor_data is not None:
                self._spectrum_widget.set_noise_floor_from_hz(*floor_data)
        db = self._pipeline.noise_reduction_db
        if db >= -0.5:
            self._lbl_noise_db.setText(tr("~0 dB  (sin ruido detectable)"))
            self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
        elif db >= -3.0:
            self._lbl_noise_db.setText(f"{db:.1f} dB")
            self._lbl_noise_db.setStyleSheet("color: #fff176; font-weight: bold;")
        else:
            self._lbl_noise_db.setText(f"{db:.1f} dB")
            self._lbl_noise_db.setStyleSheet("color: #69f0ae; font-weight: bold;")

    def _on_db_range_changed(self, value: int) -> None:
        snapped = round(value / 5) * 5
        self._lbl_db_range.setText(f"{snapped} dBFS")
        self._spectrum_widget.set_db_max(snapped)
        self._waterfall_widget.set_db_max(snapped)
        self._config.window.spectrum_db_max = snapped
        self._schedule_save()

    def _on_freq_range_changed(self, value: int) -> None:
        self._lbl_freq_range.setText(f"{value} kHz")
        self._spectrum_widget.set_max_freq_hz(value * 1000)
        self._waterfall_widget.set_max_freq_hz(value * 1000)
        self._config.window.spectrum_max_freq_hz = value * 1000
        self._schedule_save()

    def _on_waterfall_toggled(self, on: bool) -> None:
        self._waterfall_widget.setVisible(on)
        self._combo_waterfall_src.setEnabled(on)
        self._combo_waterfall_hist.setEnabled(on)
        self._spectrum_widget.set_waterfall_enabled(on)
        if on:
            self._waterfall_widget.clear()
            # Recuperar el reparto 50/50 (al re-mostrarse, el splitter le daría
            # solo su altura mínima en vez de su mitad del alto disponible).
            total = self._spectrum_splitter.height() or sum(self._spectrum_splitter.sizes())
            if total > 0:
                self._spectrum_splitter.setSizes([total // 2, total - total // 2])
        self._config.window.spectrum_show_waterfall = bool(on)
        self._schedule_save()

    def _on_waterfall_hist_changed(self, _idx: int) -> None:
        secs = int(self._combo_waterfall_hist.currentData())
        self._waterfall_widget.set_history_sec(float(secs))
        self._config.window.waterfall_history_sec = secs
        self._schedule_save()

    def _on_waterfall_source_changed(self, _idx: int) -> None:
        source = self._combo_waterfall_src.currentData()
        self._spectrum_widget.set_waterfall_source(source)
        self._waterfall_widget.set_source_label(self._combo_waterfall_src.currentText())
        # El modo cambia la escala (nivel dBFS vs diferencia): antes del clear,
        # porque set_diff_mode también rellena el buffer con su propio vacío.
        self._waterfall_widget.set_diff_mode(source == "diff")
        self._waterfall_widget.clear()   # la fuente cambió: no mezclar historia
        self._config.window.waterfall_source = source
        self._schedule_save()

    def _on_clear_noise_profile(self) -> None:
        self._pipeline.clear_noise_profile()
        self._active_noise_profile_name = None
        self._spectrum_widget.clear_floor()
        self._refresh_noise_profile_ui()

    # ------------------------------------------------------------------
    # Perfiles de ruido nombrados
    # ------------------------------------------------------------------

    def _auto_load_noise_profile(self) -> "str | None":
        """Al arrancar: recargar el último perfil usado si sigue existiendo.
        Devuelve el nombre cargado (para el mensaje de inicio), o None.

        Respeta el modo guardado: si el usuario cerró en Adaptativo (MCRA),
        la app abre en MCRA. Cargar un perfil nombrado fuerza estático, así que
        solo auto-cargamos cuando el modo guardado ya era estático (el perfil
        estaba en uso). Sin esto, un `last_noise_profile` viejo pisaba el modo
        Adaptativo elegido por el usuario en cada arranque."""
        if self._config.dsp.noise_mode != "static":
            return None
        name = self._config.last_noise_profile
        if not name or not self._noise_profile_manager.exists(name):
            return None
        try:
            data = self._noise_profile_manager.load(name)
            self._pipeline.set_noise_profile_data(data)
        except Exception:
            return None
        self._active_noise_profile_name = name
        for i in range(self._combo_noise_mode.count()):
            if self._combo_noise_mode.itemData(i) == "static":
                self._combo_noise_mode.blockSignals(True)
                self._combo_noise_mode.setCurrentIndex(i)
                self._combo_noise_mode.blockSignals(False)
                break
        self._config.dsp.noise_mode = "static"
        self._refresh_noise_profile_ui()
        return name

    def _on_save_noise_profile(self) -> None:
        data = self._pipeline.get_noise_profile_data()
        if data is None:
            return
        suggested = self._config.last_noise_profile or ""
        name, ok = QInputDialog.getText(
            self, tr("Guardar perfil de ruido"), tr("Nombre del perfil:"), text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        if self._noise_profile_manager.exists(name):
            ans = QMessageBox.question(
                self, tr("Confirmar reemplazo"),
                tr("Ya existe un perfil llamado '{name}'.\n\nDeseas reemplazarlo?").format(name=name))
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._noise_profile_manager.save(name, data)
        self._config.last_noise_profile = name
        self._active_noise_profile_name = name
        self._schedule_save()
        self._refresh_noise_profile_ui()
        self._status_bar.showMessage(
            tr("Perfil de ruido \"{name}\" guardado.").format(name=name))

    def _on_manage_noise_profiles(self) -> None:
        names = self._noise_profile_manager.list_names()
        if not names:
            return
        current = self._config.last_noise_profile
        idx = names.index(current) if current in names else 0
        name, ok = QInputDialog.getItem(
            self, tr("Perfiles de ruido"), tr("Cargar perfil:"), names, idx, False)
        if not ok or not name:
            return
        try:
            data = self._noise_profile_manager.load(name)
            self._pipeline.set_noise_profile_data(data)
        except Exception as e:
            QMessageBox.warning(self, tr("Error al cargar el perfil"), str(e))
            return
        # Forzar modo estático en la UI (set_noise_profile_data ya lo hizo en el pipeline)
        for i in range(self._combo_noise_mode.count()):
            if self._combo_noise_mode.itemData(i) == "static":
                self._combo_noise_mode.blockSignals(True)
                self._combo_noise_mode.setCurrentIndex(i)
                self._combo_noise_mode.blockSignals(False)
                break
        self._config.dsp.noise_mode = "static"
        self._config.last_noise_profile = name
        self._active_noise_profile_name = name
        self._spectrum_widget.clear_floor()
        self._refresh_noise_profile_ui()
        self._schedule_save()
        self._status_bar.showMessage(
            tr("Perfil de ruido \"{name}\" cargado.").format(name=name))

    def _refresh_bypass_button(self, checked: bool) -> None:
        """Estado visual del boton de Bypass (mismo patron que el Mute)."""
        if checked:
            self._btn_bypass.setText(tr("⇄  Crudo"))
        else:
            self._btn_bypass.setText(tr("⇄  Bypass"))

    def _on_mute_toggled(self, checked: bool) -> None:
        """Silencia la salida a los parlantes sin detener el proceso."""
        self._pipeline.set_output_mute(checked)
        if checked:
            self._btn_mute.setText(tr("🔇  Silenciado"))
            self._status_bar.showMessage(
                tr("Salida silenciada — el procesamiento sigue activo."))
        else:
            self._btn_mute.setText(tr("🔇  Mute"))

    def _on_toggle_processing(self, checked: bool) -> None:
        if checked:
            try:
                self._pipeline.start()
                self._btn_start.setText(tr("⏹  DETENER"))
                self._level_timer.start()
                self._spectrum_widget.start()
                self._waterfall_widget.start()
                self._status_bar.showMessage(tr("Procesando..."))
                self._btn_record.setEnabled(True)
                self._btn_mute.setEnabled(True)
                self._btn_refresh_devices.setEnabled(False)
                # Cambiar de dispositivo requiere reiniciar el procesamiento:
                # deshabilitados para que no parezca que aplica en vivo.
                # (El combo Canal sí aplica en vivo — queda habilitado.)
                self._combo_in.setEnabled(False)
                self._combo_out.setEnabled(False)
                self._adv_audio_tab.set_processing_active(True)
                self._adv_canceller_tab._update_stats()
                self._refresh_noise_profile_ui()
            except IncompatibleDevicesError as e:
                self._btn_start.setChecked(False)
                msg = tr(
                    "La entrada ({in_api}) y la salida ({out_api}) usan APIs de audio "
                    "distintas y no se pueden combinar en un mismo stream. Elegí ambos "
                    "dispositivos de la misma API (por ejemplo, los dos [WASAPI])."
                ).format(in_api=e.input_api, out_api=e.output_api)
                self._status_bar.showMessage(msg)
                QMessageBox.warning(self, tr("Dispositivos incompatibles"), msg)
            except Exception as e:
                self._btn_start.setChecked(False)
                self._status_bar.showMessage(tr("Error: {msg}").format(msg=e))
        else:
            if self._pipeline.noise_is_learning:
                self._btn_learn.setChecked(False)
            if self._pipeline.is_recording:
                self._finish_recording()   # antes de stop(): conserva la duración
            self._btn_record.setEnabled(False)
            self._btn_mute.setChecked(False)   # dispara _on_mute_toggled: quita mute + restaura texto
            self._btn_mute.setEnabled(False)
            self._pipeline.stop()
            self._refresh_noise_profile_ui()
            self._level_timer.stop()
            self._spectrum_widget.stop()
            self._waterfall_widget.stop()
            self._btn_start.setText(tr("▶  ACTIVAR"))
            self._reset_live_indicators()
            self._status_bar.showMessage(tr("Detenido."))
            self._btn_refresh_devices.setEnabled(True)
            self._combo_in.setEnabled(True)
            self._combo_out.setEnabled(True)
            self._adv_audio_tab.set_processing_active(False)

    def _on_tab_changed(self, idx: int) -> None:
        if idx >= 1:
            self._schedule_save()

    # ------------------------------------------------------------------
    # Niveles y settings
    # ------------------------------------------------------------------

    def _setup_pipeline_callbacks(self) -> None:
        # OJO: este callback lo invoca el HILO PROCESADOR, no el de la GUI. Tocar
        # un widget desde ahí es comportamiento indefinido en Qt — antes llamaba
        # directo a showMessage(). Ahora solo guarda el texto (asignación de un
        # str, atómica) y el aviso lo pinta _tick_levels, que sí corre en la GUI.
        self._pipeline.set_error_callback(self._remember_dsp_error)
        self._dsp_error_msg: str = ""
        self._dsp_errors_seen: int = 0
        self._dsp_error_hold: int = 0   # ticks de 500 ms que el aviso retiene el cartel
        self._mcra_wait: int = 0        # ticks que MCRA lleva sin completar el warmup
        self._mcra_stall_logged: bool = False   # un volcado por episodio

    def _mcra_stall_reason(self) -> str:
        """Por qué el estimador adaptativo no termina de calibrar.

        Son varias causas distintas y hasta ahora todas se veían igual
        ('calibrando…' para siempre). Se ordenan de la más concreta a la más
        genérica; la última manda a mirar el log, que es donde está el detalle."""
        if self._pipeline.dsp_error_count:
            return tr("⚠ El procesador DSP está fallando — ver errores_dsp.log")
        if not self._config.dsp.noise_enabled:
            return tr("⚠ No calibra: el cancelador de ruido está desactivado")
        if self._pipeline.db_in < -55.0:
            return tr("⚠ No calibra: no llega audio de entrada (revisar dispositivo y Canal)")
        # Ninguna causa conocida: volcar el estado interno al log UNA vez por
        # episodio. Este mensaje ya se reportó y las tres causas conocidas
        # quedaron descartadas, así que sin este volcado no hay forma de saber
        # qué contador está quieto.
        if not self._mcra_stall_logged:
            self._mcra_stall_logged = True
            self._pipeline.log_diagnostic("MCRA no calibra", self._pipeline.mcra_diag)
        return tr("⚠ El estimador adaptativo no completa la calibración — "
                  "probar Perfil estático y volver, y mandar errores_dsp.log")

    def _remember_dsp_error(self, msg: str) -> None:
        """Llamado desde el HILO PROCESADOR: solo guardar, nunca tocar widgets."""
        self._dsp_error_msg = msg

    def _check_dsp_errors(self) -> None:
        """Avisa si el hilo procesador está fallando. Corre en el hilo de la GUI.

        Un fallo ahí se repite cada frame y el manejador resetea el profiler, así
        que en MCRA el estimador nunca sale del warmup: no calibra, no hay
        reducción y no aparece el piso en el espectro — todo junto y sin ningún
        mensaje (invariante 9). Cambiar de modo lo 'arregla' porque `set_mode`
        rearma el estado, que es justo lo que lo hace parecer un misterio.
        Se compara contra el conteo del tick anterior para distinguir un error
        aislado (ya superado) de una tormenta en curso."""
        n = self._pipeline.dsp_error_count
        if n == self._dsp_errors_seen:
            return
        nuevos = n - self._dsp_errors_seen
        self._dsp_errors_seen = n
        self._status_bar.showMessage(tr(
            "⚠ Error en el procesador DSP ({n} en total) — el cancelador no puede "
            "calibrar. Detalle en errores_dsp.log. Último: {msg}"
        ).format(n=n, msg=self._pipeline.dsp_last_error))
        self._label_noise.setText(tr("⚠ El procesador DSP está fallando — ver errores_dsp.log"))
        self._label_noise.setStyleSheet("color: #ef5350; font-size: 8pt; font-weight: bold;")
        # Reservar el cartel unos segundos: si no, el timer de 500 ms lo pisa con
        # "calibrando (~200 ms)..." y el aviso no se llega a leer.
        self._dsp_error_hold = 10

    # Estado en reposo de los indicadores que sólo pinta _tick_levels.
    _IDLE_LBL_STYLE = "color: #555; font-size: 8pt; font-weight: bold;"

    def _reset_live_indicators(self) -> None:
        """Deja en reposo TODO lo que sólo se actualiza en `_tick_levels`.

        Ese timer se detiene junto con el procesamiento, así que cualquier
        indicador que se pinte únicamente ahí se queda congelado con el último
        valor medido — mostrando actividad de un proceso que ya no corre
        (invariante 5). Reportado con el indicador del AGC de entrada, pero le
        pasaba lo mismo al del limitador, al S/N y a los marcadores de heterodino.

        Va en un método propio y no como una lista de líneas dentro del `else` de
        _on_toggle_processing para que agregar un indicador nuevo tenga UN lugar
        evidente donde declarar su reposo.
        """
        self._vu_in.set_level(-60)
        self._vu_out.set_level(-60)
        self._label_latency.setText(tr("Latencia: --"))
        self._label_agc_gain.setText("—")
        self._lbl_peak_active.setText("—")
        self._lbl_peak_active.setStyleSheet(self._IDLE_LBL_STYLE)
        self._lbl_leveler.setText("—")
        self._lbl_leveler.setStyleSheet(self._IDLE_LBL_STYLE)
        self._adv_audio_tab._lbl_leveler_act.setText("—")
        self._adv_audio_tab._lbl_leveler_act.setStyleSheet("color: #555;")
        self._lbl_agc_ceiling.setText("—")
        self._lbl_agc_ceiling.setStyleSheet("color: #555; font-size: 8pt;")
        self._lbl_snr.setText(tr("S/N: —"))
        self._lbl_snr.setStyleSheet("color: #888; font-weight: bold;")
        self._waterfall_widget.set_tone_freqs(None)

    def _tick_levels(self) -> None:
        self._check_dsp_errors()
        self._vu_in.set_level(self._pipeline.db_in)
        self._vu_out.set_level(self._pipeline.db_out)
        lat = self._pipeline.latency_ms
        self._label_latency.setText(tr("Latencia: {ms:.0f} ms").format(ms=lat) if lat > 0 else tr("Latencia: --"))
        # Con if/else y no sólo if: sin el else, apagar el AGC dejaba el último
        # valor pegado en pantalla (invariante 5, el mismo caso que el reposo).
        if self._combo_agc.currentData() != "off":
            self._label_agc_gain.setText(f"{self._pipeline.agc_gain_db:+.0f} dB")
        else:
            self._label_agc_gain.setText("—")

        red = self._pipeline.peak_reduction_db
        if red < -0.1:
            self._lbl_peak_active.setText(tr("ACTIVO  {db:.1f} dB").format(db=red))
            color = "#ef5350" if red < -3.0 else "#ffa726"
            self._lbl_peak_active.setStyleSheet(f"color: {color}; font-size: 8pt; font-weight: bold;")
        else:
            self._lbl_peak_active.setText("—")
            self._lbl_peak_active.setStyleSheet("color: #555; font-size: 8pt; font-weight: bold;")

        # Indicador del nivelador de voz — en la pestaña Principal (junto al
        # limitador) y en el grupo Nivelador de Avanzada Audio (mismo dato,
        # para verlo mientras se ajusta la Ganancia máxima)
        if (self._config.dsp.voice_leveler_enabled and self._config.dsp.noise_enabled
                and self._pipeline.is_running()):
            lev = self._pipeline.voice_leveler_gain_db
            if lev > 0.5:
                lev_text, lev_color = f"+{lev:.1f} dB", "#69f0ae"
            else:
                lev_text, lev_color = tr("0 dB"), "#888"
        else:
            lev_text, lev_color = "—", "#555"
        self._lbl_leveler.setText(lev_text)
        self._lbl_leveler.setStyleSheet(f"color: {lev_color}; font-size: 8pt; font-weight: bold;")
        self._adv_audio_tab._lbl_leveler_act.setText(lev_text)
        self._adv_audio_tab._lbl_leveler_act.setStyleSheet(f"color: {lev_color}; font-weight: bold;")

        # Techo de ruido del AGC: cuánto puede amplificar ahora mismo. En 0 dB el
        # techo quedó por debajo del piso real de entrada y está ahogando la señal
        # (invariante 5: el indicador se actualiza siempre, no detrás de un return).
        ceil  = self._pipeline.agc_gain_ceiling_db
        floor = self._pipeline.input_noise_db
        if ceil is None or floor is None:
            self._lbl_agc_ceiling.setText("—")
            self._lbl_agc_ceiling.setStyleSheet("color: #555; font-size: 8pt;")
        elif self._pipeline.agc_ceiling_limiting:
            # Está mordiendo: el AGC quiere más ganancia de la permitida
            self._lbl_agc_ceiling.setText(
                tr("piso {fl:.0f} dBFS · limitando a +{db:.0f} dB").format(fl=floor, db=ceil))
            col = "#ff5252" if ceil < 1.0 else "#ffb74d"
            self._lbl_agc_ceiling.setStyleSheet(f"color: {col}; font-size: 8pt; font-weight: bold;")
        else:
            # El tope existe pero el AGC no lo alcanza: no está limitando nada
            self._lbl_agc_ceiling.setText(
                tr("piso {fl:.0f} dBFS · sin efecto").format(fl=floor))
            self._lbl_agc_ceiling.setStyleSheet("color: #888; font-size: 8pt;")

        # Grabación: tiempo transcurrido, y detección de muerte por error de
        # disco (el writer marca recording=False solo; el botón queda checked)
        if self._btn_record.isChecked():
            if self._pipeline.is_recording:
                s = int(self._pipeline.recording_seconds)
                self._lbl_rec_time.setText(f"REC {s // 60:02d}:{s % 60:02d}")
            else:
                err = self._pipeline.recording_error
                self._finish_recording()
                if err:
                    self._status_bar.showMessage(
                        tr("Error de grabación: {e}").format(e=err))

        # Indicador S/N (pestaña Espectro) — requiere cancelador ACTIVO: el
        # profiler solo actualiza snr_db cuando procesa (desactivado = congelado)
        if (self._pipeline.is_running() and self._pipeline.noise_has_profile
                and self._config.dsp.noise_enabled):
            snr = self._pipeline.snr_db
            color_snr = "#69f0ae" if snr > 15 else "#fff176" if snr > 6 else "#90a4ae"
            self._lbl_snr.setText(f"S/N: {snr:+.0f} dB")
            self._lbl_snr.setStyleSheet(f"color: {color_snr}; font-weight: bold;")
        else:
            self._lbl_snr.setText(tr("S/N: —"))
            self._lbl_snr.setStyleSheet("color: #888; font-weight: bold;")

        # Marcadores de heterodino en la cascada: los tonos que el ANF cancela.
        # Solo si la cascada está visible (si no, es trabajo tirado).
        if self._config.window.spectrum_show_waterfall and self._pipeline.is_running():
            self._waterfall_widget.set_tone_freqs(self._pipeline.anf_tone_freqs)
        else:
            self._waterfall_widget.set_tone_freqs(None)

    def _restore_or_center(self) -> None:
        # Pantalla de referencia: la que contiene la posición guardada (setups
        # multi-monitor — clampear contra la primaria mandaba la ventana al
        # monitor principal). Si ese monitor ya no existe, cae a la primaria.
        screen = None
        if self._config.window.x is not None:
            s = QApplication.screenAt(QPoint(self._config.window.x,
                                             self._config.window.y))
            if s is not None:
                screen = s.availableGeometry()
        if screen is None:
            screen = QApplication.primaryScreen().availableGeometry()
        # Altura deseada: el contenido completo de la pestaña Principal (que
        # ahora vive en un scroll y ya no fuerza la altura de la ventana) más
        # tabs/botón/status. Si el monitor es más bajo, se recorta y aparece
        # el scroll — la app siempre entra en pantalla.
        # +145: tabs + botón ACTIVAR + separación (addSpacing 10) + status bar + margen
        desired_h = self._main_tab_inner.sizeHint().height() + 145
        # Ancho FIJO (_WINDOW_W); solo se ajusta el alto al contenido.
        self.resize(_WINDOW_W, min(desired_h, screen.height() - 60))
        # Red de seguridad de la escala de UI: si el usuario se mudo a un monitor
        # mas chico, la ventana ya no entra y su ancho es fijo, asi que Qt no la
        # puede achicar. Se vuelve a 100% para el proximo arranque (esta sesion
        # ya arranco escalada) y se avisa — sin esto la barra de estado, con el
        # combo para deshacerlo, puede quedar fuera de la pantalla.
        if _WINDOW_W > screen.width() and self._config.window.ui_scale != 1.0:
            self._config.window.ui_scale = 1.0
            self._config.save(settings_path())
            self._status_bar.showMessage(tr(
                "La escala de la interfaz no entra en esta pantalla — se volvio "
                "a 100 %. Reiniciar la aplicacion."))
        if self._config.window.x is not None:
            # Clamp dentro de la pantalla de referencia: la ventana COMPLETA
            # debe quedar visible (clampear solo el borde superior dejaba el
            # inferior colgando fuera del monitor — el fondo de la app quedaba
            # cortado y el scroll de la pestaña nunca aparecía porque para Qt
            # la ventana no era chica, era el monitor el que la recortaba).
            # Márgenes de 20/50 px estimando el marco de la ventana (antes de
            # show() frameGeometry aún no lo incluye).
            x = max(screen.x(), min(self._config.window.x,
                                    screen.x() + screen.width() - self.width() - 20))
            y = max(screen.y(), min(self._config.window.y,
                                    screen.y() + screen.height() - self.height() - 50))
            self.move(x, y)
        else:
            self.move(
                screen.x() + (screen.width()  - self.width())  // 2,
                screen.y() + (screen.height() - self.height()) // 2,
            )

    def _schedule_save(self) -> None:
        self._save_timer.start()
        # Refrescar "(modificado)" al instante en cada cambio (comparación en
        # memoria, sin disco) — no esperar el debounce de 800 ms del guardado.
        self._update_window_title()

    def _save_settings(self) -> None:
        # Los dos slots son la fuente de verdad de la ganancia de salida.
        # `config.gain.output_gain_db` lo pisa el pipeline con el valor del modo
        # ACTUAL (set_output_gain_db escribe config), asi que guardar sin esta
        # sincronizacion mezclaria el nivel de bypass con el de procesado.
        self._config.gain.output_gain_db        = self._out_gain_by_bypass[False]
        self._config.gain.output_gain_db_bypass = self._out_gain_by_bypass[True]
        try:
            self._config.save(settings_path())
        except Exception:
            pass
        # Refrescar el "(modificado)" del título tras la ráfaga de ediciones
        self._update_window_title()

    def _refresh_preset_snapshot(self, force: bool = False) -> None:
        """Cachea (dsp, gain) del preset activo desde disco. Solo re-lee si cambió
        el preset (o force=True tras guardar/sobrescribir/renombrar)."""
        name = self._config.last_preset
        if not force and self._snapshot_for == name:
            return
        self._snapshot_for = name
        if name and self._preset_manager.exists(name):
            try:
                snap = self._preset_manager.snapshot(name)
                self._preset_saved_snapshot = (snap["dsp"], snap["gain"])
            except Exception:
                self._preset_saved_snapshot = None
        else:
            self._preset_saved_snapshot = None

    def _refresh_title(self) -> None:
        """Fuerza el refresco del snapshot y el título — para load/overwrite/rename."""
        self._refresh_preset_snapshot(force=True)
        self._update_window_title()

    def _update_window_title(self) -> None:
        """Título = app + versión + preset activo (con '(modificado)' si los
        valores actuales difieren del preset guardado) + build ID. Compara contra
        el snapshot en memoria — sin disco — para poder llamarse en cada cambio."""
        from buildinfo import BUILD_ID
        title = "RadioNoiseKiller  v2.4.1  by LU6APA"
        name = self._config.last_preset
        if name:
            self._refresh_preset_snapshot(force=False)
            cur = PresetManager._capture(name, self._config)
            modified = self._preset_saved_snapshot != (cur["dsp"], cur["gain"])
            if modified:
                title += "  ·  " + tr("{name}  (modificado)").format(name=name)
            else:
                title += f"  ·  {name}"
        title += f"  ·  build {BUILD_ID}"
        self.setWindowTitle(title)

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._config.window.x = self.pos().x()
        self._config.window.y = self.pos().y()
        self._config.window.w = self.width()
        self._pipeline.stop()
        self._save_settings()
        event.accept()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _labeled_row(label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(_ROW_LABEL_W)
        row.addWidget(lbl)
        if isinstance(widget, QComboBox):
            widget.setFixedWidth(_COMBO_W)
        row.addWidget(widget)
        return row

    def _apply_dark_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1a1a2e;
                color: #e0e0e0;
                font-size: 9pt;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #16213e;
                color: #aaa;
                padding: 6px 18px;
                border: 1px solid #444;
                border-bottom: none;
                border-radius: 4px 4px 0 0;
            }
            QTabBar::tab:selected {
                background: #1a1a2e;
                color: #90caf9;
                font-weight: bold;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 8px;
                font-weight: bold;
                color: #90caf9;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }
            QComboBox, QSlider {
                background-color: #16213e;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 2px 6px;
                color: #e0e0e0;
            }
            QComboBox::drop-down { border: none; }
            QSlider::groove:horizontal {
                height: 4px;
                background: #333;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #90caf9;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #1565c0;
                border-radius: 2px;
            }
            QSlider::handle:horizontal:disabled {
                background: #555;
            }
            QSlider::sub-page:horizontal:disabled {
                background: #4a4a4a;
            }
            QPushButton {
                background-color: #0f3460;
                color: #e0e0e0;
                border: 1px solid #1a6ba8;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover  { background-color: #1a4a7a; }
            /* Cualquier boton activado se pone rojo: la letra va en amarillo y
               negrita para que se lea. Va aca y no como estilo inline de cada
               boton para que valga igual en los tres de la fila de escucha, en
               ACTIVAR/DETENER y en cualquier boton checkable que se agregue. */
            QPushButton:checked {
                background-color: #c62828; border-color: #ef5350;
                color: #ffd600; font-weight: bold;
            }
            QPushButton:disabled { background-color: #333; color: #666; }
            QScrollArea { border: none; }
            QStatusBar { background-color: #111; color: #aaa; font-size: 8pt; }
        """)
