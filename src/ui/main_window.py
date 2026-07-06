from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QSlider, QPushButton, QStatusBar,
    QGroupBox, QCheckBox, QTabWidget, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from audio.devices import list_devices, AudioDevice
from config import AppConfig, RadioMode, GainConfig
from pipeline import ProcessingPipeline
from ui.vu_meter import VuMeter
from ui.advanced_tab import AdvancedAudioTab, AdvancedImpulseTab, AdvancedCancellerTab
from ui.presets_tab import PresetsTab
from ui.slider_row import SliderRow
from ui.spectrum_widget import SpectrumWidget
from presets import PresetManager
from utils import settings_path, presets_dir


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._config = AppConfig()
        self._config.load(settings_path())

        self._pipeline = ProcessingPipeline(self._config)
        self._preset_manager = PresetManager(presets_dir())

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

        self._btn_start.setEnabled(True)
        self._status_bar.showMessage("Listo. Presiona ACTIVAR para iniciar.")
        self._restore_or_center()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("RadioNoiseKiller  v1.3")
        self.setMinimumWidth(800)
        self.setMaximumWidth(1100)

        self._spectrum_widget = SpectrumWidget()
        self._spectrum_widget.pre_frames  = self._pipeline.spectrum_pre_frames
        self._spectrum_widget.post_frames = self._pipeline.spectrum_post_frames

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_main_tab(), "Principal")

        self._adv_audio_tab     = AdvancedAudioTab(self._config, self._pipeline)
        self._adv_impulse_tab   = AdvancedImpulseTab(self._config, self._pipeline)
        self._adv_canceller_tab = AdvancedCancellerTab(self._config, self._pipeline)
        self._tabs.addTab(self._adv_audio_tab,     "Avanzada Audio")
        self._tabs.addTab(self._adv_impulse_tab,   "Avanzada Impulsos")
        self._tabs.addTab(self._adv_canceller_tab, "Avanzada Cancelador")
        self._tabs.addTab(self._build_spectrum_tab(), "Espectro")
        self._presets_tab = PresetsTab(
            self._config, self._pipeline, self._preset_manager
        )
        self._presets_tab.preset_loaded.connect(self.refresh_from_config)
        self._presets_tab.state_changed.connect(self._schedule_save)
        self._tabs.addTab(self._presets_tab, "Presets")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        root.addWidget(self._tabs)
        root.addWidget(self._build_start_button())

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._apply_dark_style()

    def _build_main_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self._build_device_group())
        layout.addWidget(self._build_control_group())
        layout.addWidget(self._build_modules_group())
        layout.addWidget(self._build_noise_group())
        layout.addWidget(self._build_level_group())
        return tab

    def _build_device_group(self) -> QGroupBox:
        group = QGroupBox("Dispositivos de Audio")
        layout = QVBoxLayout(group)
        self._combo_in  = QComboBox()
        self._combo_out = QComboBox()
        layout.addLayout(self._labeled_row("Entrada:", self._combo_in))
        layout.addLayout(self._labeled_row("Salida:", self._combo_out))
        return group

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("Control")
        layout = QVBoxLayout(group)

        self._combo_mode = QComboBox()
        for mode in RadioMode:
            self._combo_mode.addItem(mode.value, mode)
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        mode_row = self._labeled_row("Modo:", self._combo_mode)
        mode_spacer = QLabel("")
        mode_spacer.setFixedWidth(60)
        mode_row.addWidget(mode_spacer)
        layout.addLayout(mode_row)

        agc_row = QHBoxLayout()
        agc_lbl = QLabel("AGC:")
        agc_lbl.setFixedWidth(70)
        agc_row.addWidget(agc_lbl)
        self._combo_agc = QComboBox()
        for label, preset in [
            ("Desactivado", "off"),
            ("Rápido",      "fast"),
            ("Medio",       "medium"),
            ("Lento",       "slow"),
            ("Custom",      "custom"),
        ]:
            self._combo_agc.addItem(label, preset)
        self._combo_agc.setCurrentIndex(0)
        self._combo_agc.currentIndexChanged.connect(self._on_agc_changed)
        agc_row.addWidget(self._combo_agc)
        self._label_agc_gain = QLabel("")
        self._label_agc_gain.setFixedWidth(60)
        self._label_agc_gain.setStyleSheet("color: #90caf9; font-size: 8pt;")
        agc_row.addWidget(self._label_agc_gain)
        layout.addLayout(agc_row)

        self._check_bypass = QCheckBox("Bypass (sin procesamiento)")
        self._check_bypass.toggled.connect(self._pipeline.set_bypass)
        layout.addWidget(self._check_bypass)
        return group

    def _build_modules_group(self) -> QGroupBox:
        group = QGroupBox("Módulos activos")
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
            "Supresor de impulsos",
            "Elimina QRN, frituras y descargas atmosféricas cortas.",
        )
        self._chk_bandpass_pre = _chk(
            "Filtro de paso de banda  (pre)",
            "Butterworth IIR antes del cancelador de ruido — limita el espectro que aprende el perfil.",
        )
        self._chk_bandpass_post = _chk(
            "Filtro de paso de banda  (post)",
            "Butterworth IIR después del cancelador de ruido — elimina fugas espectrales del STFT.",
        )
        self._chk_anf = _chk(
            "ANF — Cancela heterodinos y tonos interferentes",
            "Detecta bins espectrales que sobresalen sobre el ruido vecino y los atenúa.",
        )
        self._chk_noise = _chk(
            "Cancelador de ruido estacionario",
            "Filtro de Wiener espectral. Requiere perfil aprendido.",
        )
        self._chk_perceptual_floor = _chk_sub(
            "Piso espectral perceptual  (curva de enmascaramiento auditivo)",
            "Reemplaza el floor fijo por una curva que varía por frecuencia:\n"
            "  · +75% en ~500 Hz (fundamentales vocales, preserva la calidez)\n"
            "  · Neutro en 1000–3000 Hz (formantes, sin cambio)\n"
            "  · –55% sobre 3 kHz (ruido de alta frecuencia, suprime más)\n"
            "El slider 'Piso espectral' de Avanzada Ruido controla el nivel global.\n"
            "Requiere cancelador activo.",
        )
        self._chk_post_filter = _chk_sub(
            "Post-filtro espectral  (ruido musical residual)",
            "Segunda pasada sobre bins de ruido para eliminar el 'ruido musical'\n"
            "(pitidos intermitentes) que deja el Wiener. Requiere cancelador activo.\n"
            "Agresividad configurable en pestaña Avanzada Ruido.",
        )
        self._chk_pitch_enhance = _chk_sub(
            "Refuerzo de pitch SSB  (detección por autocorrelación)",
            "Detecta el tono fundamental de la voz SSB y protege sus armónicos\n"
            "del cancelador de ruido. Útil para señales SSB débiles enterradas en ruido.\n"
            "Sensibilidad configurable en pestaña Avanzada Ruido.",
        )
        self._chk_squelch = _chk_sub(
            "Squelch de voz  (con música no utilizar!)",
            "Silencia la salida cuando no hay voz detectada. Requiere perfil de ruido aprendido.",
        )
        self._chk_fading_comp = _chk_sub(
            "Compensación fading HF  (onda corta con QSB)",
            "Congela el estimador de ruido durante fades ionosféricos y acelera\n"
            "la recuperación al volver la señal. Solo tiene efecto en modo Adaptativo (MCRA).\n"
            "Sensibilidad y duración del freeze configurables en Avanzada Cancelador.",
        )
        self._chk_presence = _chk(
            "EQ Voz  (presencia + cuerpo)",
            "Dos picos de realce vocal configurables en pestaña Avanzada Audio:\n"
            "  · Presencia (1000–2000 Hz): claridad e inteligibilidad\n"
            "  · Cuerpo (150–800 Hz): calidez y graves de la voz\n"
            "Cada banda con ganancia 0 dB queda en passthrough.",
        )
        self._chk_exciter = _chk(
            "Excitador armónico",
            "Genera armónicos en 1–4 kHz para recuperar presencia y ataque de consonantes.",
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
        self._chk_squelch.toggled.connect(lambda v: self._on_module_toggled("squelch_enabled", self._pipeline.set_squelch_enabled, v))
        self._chk_fading_comp.toggled.connect(lambda v: self._on_module_toggled("noise_fading_comp", self._pipeline.set_fading_comp, v))
        self._chk_exciter.toggled.connect(lambda v: self._on_module_toggled("exciter_enabled", self._pipeline.set_exciter_enabled, v))

        return group

    def _build_noise_group(self) -> QGroupBox:
        group = QGroupBox("Cancelación de Ruido Estacionario")
        layout = QVBoxLayout(group)

        # Selector de modo de estimación de ruido
        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Modo:")
        mode_lbl.setFixedWidth(70)
        self._combo_noise_mode = QComboBox()
        self._combo_noise_mode.addItem("Perfil estático",   "static")
        self._combo_noise_mode.addItem("Adaptativo (MCRA)", "mcra")
        self._combo_noise_mode.setToolTip(
            "Perfil estático: aprendizaje manual de 5s.\n"
            "Adaptativo (MCRA): estima el ruido automáticamente en tiempo real,\n"
            "  se adapta a cambios de banda sin intervención del usuario."
        )
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._combo_noise_mode)
        layout.addLayout(mode_row)

        btn_row = QHBoxLayout()
        self._btn_learn = QPushButton("⏺  Aprender ruido")
        self._btn_learn.setCheckable(True)
        self._btn_learn.setEnabled(False)
        self._btn_learn.toggled.connect(self._on_learn_toggled)
        btn_row.addWidget(self._btn_learn)

        self._btn_clear_noise = QPushButton("Borrar perfil")
        self._btn_clear_noise.setEnabled(False)
        self._btn_clear_noise.clicked.connect(self._on_clear_noise_profile)
        btn_row.addWidget(self._btn_clear_noise)
        layout.addLayout(btn_row)

        self._combo_noise_mode.currentIndexChanged.connect(self._on_noise_mode_changed)

        intensity_row = QHBoxLayout()
        intensity_lbl = QLabel("Intensidad:")
        intensity_lbl.setMinimumWidth(80)
        intensity_row.addWidget(intensity_lbl)
        self._slider_noise = QSlider(Qt.Horizontal)
        self._slider_noise.setRange(0, 100)
        init_pct = round(self._config.dsp.noise_alpha * 100)
        self._slider_noise.setValue(init_pct)
        self._slider_noise.valueChanged.connect(self._on_noise_intensity_changed)
        intensity_row.addWidget(self._slider_noise)
        self._label_noise_pct = QLabel(f"{init_pct}%")
        self._label_noise_pct.setMinimumWidth(36)
        intensity_row.addWidget(self._label_noise_pct)
        layout.addLayout(intensity_row)

        self._learn_countdown: int = 0
        self._learn_timer = QTimer()
        self._learn_timer.setInterval(1000)
        self._learn_timer.timeout.connect(self._on_learn_tick)

        db_row = QHBoxLayout()
        db_row.addWidget(QLabel("Reducción activa:"))
        self._lbl_noise_db = QLabel("—")
        self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
        db_row.addWidget(self._lbl_noise_db)
        db_row.addStretch()
        self._chk_noise_preview = QCheckBox("Preview: escuchar ruido eliminado")
        self._chk_noise_preview.setToolTip(
            "Emite el ruido que está siendo restado.\n"
            "Si suena como voz, bajar la Intensidad."
        )
        self._chk_noise_preview.toggled.connect(self._pipeline.set_noise_preview)
        db_row.addWidget(self._chk_noise_preview)
        layout.addLayout(db_row)

        self._label_noise = QLabel("Sin perfil — activar procesamiento y presionar Aprender")
        self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
        layout.addWidget(self._label_noise)

        self._noise_db_timer = QTimer(self)
        self._noise_db_timer.setInterval(500)
        self._noise_db_timer.timeout.connect(self._update_noise_db)
        self._noise_db_timer.start()

        return group

    def _build_level_group(self) -> QGroupBox:
        group = QGroupBox("Niveles y Ganancia")
        layout = QVBoxLayout(group)
        self._vu_in  = VuMeter("IN ")
        self._vu_out = VuMeter("OUT")
        layout.addWidget(self._vu_in)
        layout.addWidget(self._vu_out)
        self._label_latency = QLabel("Latencia: --")
        self._label_latency.setAlignment(Qt.AlignRight)
        layout.addWidget(self._label_latency)

        # default = valor de fábrica (menú click derecho); la posición inicial
        # se carga aparte con set_value() desde la config persistida.
        _gain_def = GainConfig()
        self._s_gain_in = SliderRow(
            "Entrada:",
            min_val=-20.0, max_val=20.0,
            default=_gain_def.input_gain_db,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_gain_out = SliderRow(
            "Salida:",
            min_val=-20.0, max_val=20.0,
            default=_gain_def.output_gain_db,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_peak = SliderRow(
            "Límite de picos:",
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

        peak_row = QHBoxLayout()
        peak_row.setContentsMargins(0, 0, 0, 0)
        lbl_peak_title = QLabel("Limitador de picos:")
        lbl_peak_title.setStyleSheet("color: #607d8b; font-size: 8pt;")
        lbl_peak_title.setFixedWidth(120)
        self._lbl_peak_active = QLabel("—")
        self._lbl_peak_active.setStyleSheet("color: #555; font-size: 8pt; font-weight: bold;")
        peak_row.addWidget(lbl_peak_title)
        peak_row.addWidget(self._lbl_peak_active)
        peak_row.addStretch()
        layout.addLayout(peak_row)

        return group

    def _build_spectrum_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()

        self._chk_spec_pre = QCheckBox("Entrada")
        self._chk_spec_pre.setChecked(True)
        self._chk_spec_pre.setStyleSheet("color: #42a5f5; font-weight: bold;")
        self._chk_spec_pre.toggled.connect(self._spectrum_widget.set_show_pre)

        self._chk_spec_post = QCheckBox("Salida")
        self._chk_spec_post.setChecked(True)
        self._chk_spec_post.setStyleSheet("color: #69f0ae; font-weight: bold;")
        self._chk_spec_post.toggled.connect(self._spectrum_widget.set_show_post)

        self._chk_spec_cancelled = QCheckBox("Lo cancelado")
        self._chk_spec_cancelled.setChecked(True)
        self._chk_spec_cancelled.setStyleSheet("color: #ff7043; font-weight: bold;")
        self._chk_spec_cancelled.toggled.connect(self._spectrum_widget.set_show_cancelled)

        self._chk_spec_floor = QCheckBox("Piso de ruido")
        self._chk_spec_floor.setChecked(True)
        self._chk_spec_floor.setStyleSheet("color: #ffd54f; font-weight: bold;")
        self._chk_spec_floor.toggled.connect(self._spectrum_widget.set_show_floor)

        ctrl.addWidget(self._chk_spec_pre)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._chk_spec_post)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._chk_spec_cancelled)
        ctrl.addSpacing(12)
        ctrl.addWidget(self._chk_spec_floor)
        ctrl.addStretch()

        lbl_hint = QLabel("dBFS")
        lbl_hint.setStyleSheet("color: #607d8b; font-size: 7pt;")
        ctrl.addWidget(lbl_hint)

        layout.addLayout(ctrl)
        layout.addWidget(self._spectrum_widget, 1)   # stretch: el gráfico toma todo el espacio libre

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
            "Máx Y:", "_lbl_db_range", "_sld_db_range",
            -60, 0, 5, 10, self._config.window.spectrum_db_max,
            f"{self._config.window.spectrum_db_max} dBFS", 52,
            self._on_db_range_changed,
        ))
        zoom_layout.addLayout(_slider_row(
            "Máx X:", "_lbl_freq_range", "_sld_freq_range",
            1, 12, 1, 2, self._config.window.spectrum_max_freq_hz // 1000,
            f"{self._config.window.spectrum_max_freq_hz // 1000} kHz", 40,
            self._on_freq_range_changed,
        ))

        # Aplicar el zoom persistido al widget: setValue() en _slider_row corre
        # ANTES del connect(), así que el valor restaurado no dispara el handler
        # y el gráfico quedaba con los defaults hasta tocar los sliders.
        self._spectrum_widget.set_db_max(self._config.window.spectrum_db_max)
        self._spectrum_widget.set_max_freq_hz(self._config.window.spectrum_max_freq_hz)

        layout.addWidget(zoom_widget)
        return tab

    def _build_start_button(self) -> QPushButton:
        self._btn_start = QPushButton("▶  ACTIVAR")
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
        devices = list_devices()
        for combo in (self._combo_in, self._combo_out):
            combo.clear()
        for dev in devices:
            if dev.supports_input():
                self._combo_in.addItem(dev.display_name(), dev)
            if dev.supports_output():
                self._combo_out.addItem(dev.display_name(), dev)

        self._combo_in.currentIndexChanged.connect(self._on_input_device_changed)
        self._combo_out.currentIndexChanged.connect(self._on_output_device_changed)
        self._on_input_device_changed(0)
        self._on_output_device_changed(0)

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
            (self._chk_squelch,  "squelch_enabled",   self._pipeline.set_squelch_enabled),
            (self._chk_fading_comp, "noise_fading_comp", self._pipeline.set_fading_comp),
            (self._chk_exciter,  "exciter_enabled",   self._pipeline.set_exciter_enabled),
        ]:
            val = getattr(self._config.dsp, key)
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
            setter(val)

        for i in range(self._combo_mode.count()):
            if self._combo_mode.itemData(i) == self._config.dsp.mode:
                self._combo_mode.setCurrentIndex(i)
                break

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
            self._label_noise.setText("Adaptativo (MCRA) — activar procesamiento para calibrar")

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
            (self._chk_squelch,           "squelch_enabled",           self._pipeline.set_squelch_enabled),
            (self._chk_fading_comp,       "noise_fading_comp",         self._pipeline.set_fading_comp),
            (self._chk_exciter,           "exciter_enabled",           self._pipeline.set_exciter_enabled),
        ]:
            val = getattr(cfg, key)
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
            setter(val)

        # --- Modo AM/SSB ---
        for i in range(self._combo_mode.count()):
            if self._combo_mode.itemData(i) == cfg.mode:
                self._combo_mode.blockSignals(True)
                self._combo_mode.setCurrentIndex(i)
                self._combo_mode.blockSignals(False)
                self._pipeline.set_mode(cfg.mode)
                break

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
            self._label_noise.setText("Adaptativo (MCRA) — estimando en tiempo real")

        # --- Slider de intensidad de ruido ---
        pct = round(cfg.noise_alpha * 100)
        self._slider_noise.blockSignals(True)
        self._slider_noise.setValue(pct)
        self._slider_noise.blockSignals(False)
        self._label_noise_pct.setText(f"{pct}%")

        # --- Sliders de ganancia ---
        self._s_gain_in.set_value(self._config.gain.input_gain_db)
        self._s_gain_out.set_value(self._config.gain.output_gain_db)
        self._s_peak.set_value(self._config.gain.peak_limit_db)

        # --- Pestanas avanzadas ---
        self._adv_audio_tab.reload()
        self._adv_impulse_tab.reload()
        self._adv_canceller_tab.reload()

        self._schedule_save()

    # ------------------------------------------------------------------
    # Eventos de la UI
    # ------------------------------------------------------------------

    def _on_input_device_changed(self, idx: int) -> None:
        dev: AudioDevice | None = self._combo_in.itemData(idx)
        self._pipeline.set_input_device(dev)
        self._schedule_save()

    def _on_output_device_changed(self, idx: int) -> None:
        dev: AudioDevice | None = self._combo_out.itemData(idx)
        self._pipeline.set_output_device(dev)
        self._schedule_save()

    def _on_mode_changed(self, idx: int) -> None:
        mode: RadioMode = self._combo_mode.itemData(idx)
        self._pipeline.set_mode(mode)
        self._schedule_save()

    def _on_agc_changed(self, idx: int) -> None:
        preset = self._combo_agc.itemData(idx)
        self._config.dsp.agc_preset = preset
        self._pipeline.set_agc_preset(preset)
        if preset == "off":
            self._label_agc_gain.setText("")
        # Los sliders de AGC Custom solo se habilitan con el preset "custom"
        if hasattr(self, "_adv_audio_tab"):
            self._adv_audio_tab.refresh_enabled_states()
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
        self._schedule_save()

    def _on_gain_in_changed(self, val: float) -> None:
        self._config.gain.input_gain_db = val
        self._pipeline.set_input_gain_db(val)
        self._schedule_save()

    def _on_gain_out_changed(self, val: float) -> None:
        self._config.gain.output_gain_db = val
        self._pipeline.set_output_gain_db(val)
        self._schedule_save()

    def _on_peak_changed(self, val: float) -> None:
        self._config.gain.peak_limit_db = val
        self._pipeline.set_peak_limit_db(val)
        self._schedule_save()

    def _on_noise_intensity_changed(self, value: int) -> None:
        alpha = value / 100.0
        self._label_noise_pct.setText(f"{value}%")
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
            self._label_noise.setText(f"Perfil activo: {dur:.1f}s aprendidos — sustracción ON")
            self._label_noise.setStyleSheet("color: #69f0ae; font-size: 8pt;")
        elif is_running:
            self._label_noise.setText("Sin perfil — presionar Aprender para calibrar")
            self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
        else:
            self._label_noise.setText("Sin perfil — activar procesamiento y presionar Aprender")
            self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")

    # ------------------------------------------------------------------
    # Handlers de ruido
    # ------------------------------------------------------------------

    def _on_noise_mode_changed(self, idx: int) -> None:
        mode = self._combo_noise_mode.itemData(idx)
        self._pipeline.set_noise_mode(mode)
        self._spectrum_widget.clear_floor()
        if mode != "static":
            self._btn_learn.setVisible(False)
            self._btn_clear_noise.setVisible(False)
            self._label_noise.setText("Adaptativo (MCRA) — activar procesamiento para calibrar")
            self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
        else:
            self._refresh_noise_profile_ui()
        self._schedule_save()

    def _on_learn_toggled(self, checked: bool) -> None:
        if checked:
            self._learn_countdown = 5
            self._pipeline.start_noise_learning()
            self._spectrum_widget.start_floor_learning()
            self._btn_learn.setText(f"⏹  Aprendiendo... {self._learn_countdown}s")
            self._label_noise.setText("Aprendiendo ruido — mantener silencio en la banda")
            self._label_noise.setStyleSheet("color: #ffd600; font-size: 8pt;")
            self._btn_clear_noise.setEnabled(False)
            self._learn_timer.start()
        else:
            self._learn_timer.stop()
            self._pipeline.stop_noise_learning()
            self._spectrum_widget.stop_floor_learning()
            self._btn_learn.setText("⏺  Aprender ruido")
            self._refresh_noise_profile_ui()

    def _on_learn_tick(self) -> None:
        self._learn_countdown -= 1
        if self._learn_countdown > 0:
            self._btn_learn.setText(f"⏹  Aprendiendo... {self._learn_countdown}s")
        else:
            self._btn_learn.setChecked(False)

    def _update_noise_db(self) -> None:
        mode = self._pipeline.noise_mode

        if not self._pipeline.is_running():
            self._lbl_noise_db.setText("—")
            self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
            if mode == "mcra":
                self._label_noise.setText("Adaptativo (MCRA) — activar procesamiento para calibrar")
                self._label_noise.setStyleSheet("color: #888; font-size: 8pt;")
            return

        if mode == "mcra":
            if self._pipeline.noise_has_profile:
                db = self._pipeline.noise_reduction_db
                if db >= -0.5:
                    self._lbl_noise_db.setText("~0 dB")
                    self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
                elif db >= -3.0:
                    self._lbl_noise_db.setText(f"{db:.1f} dB")
                    self._lbl_noise_db.setStyleSheet("color: #fff176; font-weight: bold;")
                else:
                    self._lbl_noise_db.setText(f"{db:.1f} dB")
                    self._lbl_noise_db.setStyleSheet("color: #69f0ae; font-weight: bold;")
                self._label_noise.setText("Adaptativo (MCRA) — estimando en tiempo real")
                self._label_noise.setStyleSheet("color: #69f0ae; font-size: 8pt;")
                # Actualizar piso de ruido en el espectro con el estimado MCRA actual
                floor_data = self._pipeline.get_noise_floor_data()
                if floor_data is not None:
                    self._spectrum_widget.set_noise_floor_from_hz(*floor_data)
            else:
                self._lbl_noise_db.setText("—")
                self._lbl_noise_db.setStyleSheet("color: #888; font-weight: bold;")
                self._label_noise.setText("Adaptativo (MCRA) — calibrando (~200ms)...")
                self._label_noise.setStyleSheet("color: #ffd600; font-size: 8pt;")
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
            self._lbl_noise_db.setText("~0 dB  (sin ruido detectable)")
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
        self._config.window.spectrum_db_max = snapped
        self._schedule_save()

    def _on_freq_range_changed(self, value: int) -> None:
        self._lbl_freq_range.setText(f"{value} kHz")
        self._spectrum_widget.set_max_freq_hz(value * 1000)
        self._config.window.spectrum_max_freq_hz = value * 1000
        self._schedule_save()

    def _on_clear_noise_profile(self) -> None:
        self._pipeline.clear_noise_profile()
        self._spectrum_widget.clear_floor()
        self._refresh_noise_profile_ui()

    def _on_toggle_processing(self, checked: bool) -> None:
        if checked:
            try:
                self._pipeline.start()
                self._btn_start.setText("⏹  DETENER")
                self._level_timer.start()
                self._spectrum_widget.start()
                self._status_bar.showMessage("Procesando...")
                self._adv_audio_tab.set_processing_active(True)
                self._adv_canceller_tab._update_stats()
                self._refresh_noise_profile_ui()
            except Exception as e:
                self._btn_start.setChecked(False)
                self._status_bar.showMessage(f"Error: {e}")
        else:
            if self._pipeline.noise_is_learning:
                self._btn_learn.setChecked(False)
            self._pipeline.stop()
            self._refresh_noise_profile_ui()
            self._level_timer.stop()
            self._spectrum_widget.stop()
            self._btn_start.setText("▶  ACTIVAR")
            self._vu_in.set_level(-60)
            self._vu_out.set_level(-60)
            self._label_latency.setText("Latencia: --")
            self._status_bar.showMessage("Detenido.")
            self._adv_audio_tab.set_processing_active(False)

    def _on_tab_changed(self, idx: int) -> None:
        if idx >= 1:
            self._schedule_save()

    # ------------------------------------------------------------------
    # Niveles y settings
    # ------------------------------------------------------------------

    def _setup_pipeline_callbacks(self) -> None:
        self._pipeline.set_error_callback(
            lambda msg: self._status_bar.showMessage(f"Error: {msg}") if hasattr(self, '_status_bar') else None
        )

    def _tick_levels(self) -> None:
        self._vu_in.set_level(self._pipeline.db_in)
        self._vu_out.set_level(self._pipeline.db_out)
        lat = self._pipeline.latency_ms
        self._label_latency.setText(f"Latencia: {lat:.0f} ms" if lat > 0 else "Latencia: --")
        if self._combo_agc.currentData() != "off":
            self._label_agc_gain.setText(f"{self._pipeline.agc_gain_db:+.0f} dB")

        red = self._pipeline.peak_reduction_db
        if red < -0.1:
            self._lbl_peak_active.setText(f"ACTIVO  {red:.1f} dB")
            color = "#ef5350" if red < -3.0 else "#ffa726"
            self._lbl_peak_active.setStyleSheet(f"color: {color}; font-size: 8pt; font-weight: bold;")
        else:
            self._lbl_peak_active.setText("—")
            self._lbl_peak_active.setStyleSheet("color: #555; font-size: 8pt; font-weight: bold;")

    def _restore_or_center(self) -> None:
        if self._config.window.x is not None:
            self.move(self._config.window.x, self._config.window.y)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                screen.x() + (screen.width()  - self.sizeHint().width())  // 2,
                screen.y() + (screen.height() - self.sizeHint().height()) // 2,
            )

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_settings(self) -> None:
        try:
            self._config.save(settings_path())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._config.window.x = self.pos().x()
        self._config.window.y = self.pos().y()
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
        lbl.setFixedWidth(70)
        row.addWidget(lbl)
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
            QPushButton {
                background-color: #0f3460;
                color: #e0e0e0;
                border: 1px solid #1a6ba8;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover  { background-color: #1a4a7a; }
            QPushButton:checked { background-color: #c62828; border-color: #ef5350; }
            QPushButton:disabled { background-color: #333; color: #666; }
            QScrollArea { border: none; }
            QStatusBar { background-color: #111; color: #aaa; font-size: 8pt; }
        """)
