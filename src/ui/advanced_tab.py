from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLabel,
    QScrollArea, QPushButton, QHBoxLayout, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from config import AppConfig, RadioMode, AudioConfig, DSPConfig
from pipeline import ProcessingPipeline
from ui.slider_row import SliderRow

_BLOCK_SIZES    = [240, 480, 960, 1920]
_FILTER_ORDERS  = [2, 4, 6, 8]


def _freq_slider(label: str, default: int, lo: int = 50, hi: int = 1000) -> SliderRow:
    return SliderRow(label, min_val=lo, max_val=hi, default=default, step=10, unit="Hz")


def _make_scroll_layout(parent: QWidget) -> QVBoxLayout:
    outer = QVBoxLayout(parent)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    outer.addWidget(scroll)
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setSpacing(10)
    layout.setContentsMargins(8, 8, 8, 8)
    scroll.setWidget(inner)
    return layout


def _reset_button_widget(callback) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 0)
    btn = QPushButton("↺  Restaurar valores por defecto")
    btn.clicked.connect(callback)
    layout.addStretch()
    layout.addWidget(btn)
    return row


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #888; font-size: 8pt;")
    return lbl


# ---------------------------------------------------------------------------
# Pestaña Avanzada Audio
# ---------------------------------------------------------------------------

class AdvancedAudioTab(QWidget):

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_audio_group())
        layout.addWidget(self._build_dsp_group())
        layout.addWidget(self._build_voice_group())
        layout.addWidget(self._build_exciter_group())
        layout.addWidget(_reset_button_widget(self._reset_defaults))
        layout.addStretch()

    # ------------------------------------------------------------------
    # Grupos
    # ------------------------------------------------------------------

    def _build_audio_group(self) -> QGroupBox:
        group = QGroupBox("Audio")
        layout = QVBoxLayout(group)

        self._s_block = SliderRow(
            "Tamaño de bloque:",
            min_val=0, max_val=len(_BLOCK_SIZES) - 1,
            default=_BLOCK_SIZES.index(self._config.audio.block_size)
                    if self._config.audio.block_size in _BLOCK_SIZES else 1,
            step=1, unit="", fmt="{}",
        )
        self._s_block._fmt = ""
        self._s_block._update_label = lambda v: self._s_block._val_lbl.setText(
            f"{_BLOCK_SIZES[int(v)]} muestras ({_BLOCK_SIZES[int(v)]/48:.0f} ms)"
        )
        self._s_block._val_lbl.setFixedWidth(130)
        self._s_block.valueChanged.connect(self._on_block_size)
        layout.addWidget(self._s_block)
        layout.addWidget(_note("  ↳ Menor = menor latencia. Requiere reiniciar el procesamiento."))
        return group

    def _build_dsp_group(self) -> QGroupBox:
        group = QGroupBox("Filtros DSP  (se aplican en tiempo real)")
        layout = QVBoxLayout(group)

        cfg = self._config.dsp
        self._s_am_lo  = _freq_slider("AM – Hz inferior:",  cfg.bandpass_limits[RadioMode.AM][0])
        self._s_am_hi  = _freq_slider("AM – Hz superior:",  cfg.bandpass_limits[RadioMode.AM][1],  hi=10000)
        self._s_ssb_lo = _freq_slider("SSB – Hz inferior:", cfg.bandpass_limits[RadioMode.SSB][0])
        self._s_ssb_hi = _freq_slider("SSB – Hz superior:", cfg.bandpass_limits[RadioMode.SSB][1], hi=6000)

        self._s_am_lo.valueChanged.connect(lambda v: self._on_bp(RadioMode.AM,  lo=int(v)))
        self._s_am_hi.valueChanged.connect(lambda v: self._on_bp(RadioMode.AM,  hi=int(v)))
        self._s_ssb_lo.valueChanged.connect(lambda v: self._on_bp(RadioMode.SSB, lo=int(v)))
        self._s_ssb_hi.valueChanged.connect(lambda v: self._on_bp(RadioMode.SSB, hi=int(v)))

        for s in (self._s_am_lo, self._s_am_hi, self._s_ssb_lo, self._s_ssb_hi):
            layout.addWidget(s)

        self._s_order = SliderRow(
            "Orden del filtro:",
            min_val=0, max_val=len(_FILTER_ORDERS) - 1,
            default=_FILTER_ORDERS.index(cfg.filter_order)
                    if cfg.filter_order in _FILTER_ORDERS else 1,
            step=1,
        )
        self._s_order._update_label = lambda v: self._s_order._val_lbl.setText(
            f"Orden {_FILTER_ORDERS[int(v)]}"
        )
        self._s_order.valueChanged.connect(
            lambda v: self._pipeline.set_filter_order(_FILTER_ORDERS[int(v)])
        )
        layout.addWidget(self._s_order)
        return group

    def _build_voice_group(self) -> QGroupBox:
        group = QGroupBox("Voz  (se aplica en tiempo real)")
        layout = QVBoxLayout(group)

        self._s_presence_freq = SliderRow(
            "Frecuencia de presencia:",
            min_val=1000, max_val=2000,
            default=int(self._config.dsp.presence_freq),
            step=25, unit="Hz", fmt="{:.0f}",
        )
        self._s_presence_freq._update_label = lambda v: self._s_presence_freq._val_lbl.setText(
            f"{v:.0f} Hz  ({'cuerpo' if v < 1300 else 'media' if v < 1700 else 'presencia'})"
        )
        self._s_presence_freq._val_lbl.setFixedWidth(110)
        self._s_presence_freq.valueChanged.connect(self._pipeline.set_presence_freq)
        layout.addWidget(self._s_presence_freq)

        self._s_presence = SliderRow(
            "Presencia (ganancia):",
            min_val=-3.0, max_val=10.0,
            default=0.0,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_presence.valueChanged.connect(self._pipeline.set_presence_db)
        layout.addWidget(self._s_presence)
        layout.addWidget(_note("  ↳ Frecuencia + ganancia del pico vocal. 0 dB=neutro, +4–6 dB=voz de radio."))

        self._s_presence_q = SliderRow(
            "Ancho de presencia (Q):",
            min_val=0.2, max_val=2.0,
            default=0.7,
            step=0.1, unit="", fmt="{:.1f}",
        )
        self._s_presence_q._update_label = lambda v: self._s_presence_q._val_lbl.setText(
            f"Q {v:.1f} ({'ancho' if v < 0.6 else 'medio' if v < 1.2 else 'angosto'})"
        )
        self._s_presence_q._val_lbl.setFixedWidth(90)
        self._s_presence_q.valueChanged.connect(self._pipeline.set_presence_q)
        layout.addWidget(self._s_presence_q)
        layout.addWidget(_note("  ↳ Q bajo = boost ancho (más cálido), Q alto = pico estrecho (más nasal)."))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        layout.addWidget(sep)

        self._s_pitch = SliderRow(
            "Corrección de tono SSB:",
            min_val=-500, max_val=500,
            default=int(self._config.dsp.pitch_shift_hz),
            step=10, unit="Hz", fmt="{:+.0f}",
        )
        self._s_pitch._update_label = lambda v: self._s_pitch._val_lbl.setText(
            f"{v:+.0f} Hz  ({'neutro' if abs(v) < 5 else 'agudo' if v > 0 else 'grave'})"
        )
        self._s_pitch._val_lbl.setFixedWidth(110)
        self._s_pitch.valueChanged.connect(self._pipeline.set_pitch_shift)
        layout.addWidget(self._s_pitch)
        layout.addWidget(_note("  ↳ Corrige offset de BFO en SSB. +100 Hz si la voz suena grave, -100 Hz si suena aguda."))
        return group

    def _build_exciter_group(self) -> QGroupBox:
        group = QGroupBox("Excitador Armónico  (se aplica en tiempo real)")
        layout = QVBoxLayout(group)

        self._s_exciter_drive = SliderRow(
            "Drive:",
            min_val=1.0, max_val=10.0,
            default=self._config.dsp.exciter_drive,
            step=0.5, unit="", fmt="{:.1f}",
        )
        self._s_exciter_drive._update_label = lambda v: self._s_exciter_drive._val_lbl.setText(
            f"{v:.1f}×  ({'suave' if v < 3.0 else 'normal' if v < 6.0 else 'agresivo'})"
        )
        self._s_exciter_drive._val_lbl.setFixedWidth(110)
        self._s_exciter_drive.valueChanged.connect(self._on_exciter_drive)
        layout.addWidget(self._s_exciter_drive)
        layout.addWidget(_note("  ↳ Saturación tanh: cuántos armónicos se generan. Bajo=sutil, alto=efecto notable."))

        self._s_exciter_mix = SliderRow(
            "Mezcla:",
            min_val=0.0, max_val=1.0,
            default=self._config.dsp.exciter_mix,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_exciter_mix._update_label = lambda v: self._s_exciter_mix._val_lbl.setText(
            f"{v*100:.0f}%"
        )
        self._s_exciter_mix.valueChanged.connect(self._on_exciter_mix)
        layout.addWidget(self._s_exciter_mix)
        layout.addWidget(_note("  ↳ Nivel de armónicos mezclados. 20–40% = zona útil sin sonar artificial."))
        return group

    # ------------------------------------------------------------------
    # Carga y reset
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        cfg = self._config.dsp
        self._s_am_lo.set_value(cfg.bandpass_limits[RadioMode.AM][0])
        self._s_am_hi.set_value(cfg.bandpass_limits[RadioMode.AM][1])
        self._s_ssb_lo.set_value(cfg.bandpass_limits[RadioMode.SSB][0])
        self._s_ssb_hi.set_value(cfg.bandpass_limits[RadioMode.SSB][1])
        self._s_order.set_value(
            _FILTER_ORDERS.index(cfg.filter_order)
            if cfg.filter_order in _FILTER_ORDERS else 1
        )
        self._s_block.set_value(
            _BLOCK_SIZES.index(self._config.audio.block_size)
            if self._config.audio.block_size in _BLOCK_SIZES else 1
        )
        self._s_presence_freq.set_value(cfg.presence_freq)
        self._s_presence.set_value(cfg.presence_db)
        self._s_presence_q.set_value(cfg.presence_q)
        self._s_pitch.set_value(cfg.pitch_shift_hz)
        self._s_exciter_drive.set_value(cfg.exciter_drive)
        self._s_exciter_mix.set_value(cfg.exciter_mix)

    def _reset_defaults(self) -> None:
        defaults = DSPConfig()
        self._config.dsp.bandpass_limits = defaults.bandpass_limits
        self._config.dsp.filter_order    = defaults.filter_order
        self._config.audio.block_size    = AudioConfig().block_size
        self._config.dsp.presence_db     = defaults.presence_db
        self._config.dsp.presence_freq   = defaults.presence_freq
        self._config.dsp.presence_q      = defaults.presence_q
        self._config.dsp.pitch_shift_hz  = defaults.pitch_shift_hz
        self._pipeline.set_filter_order(defaults.filter_order)
        for mode, (lo, hi) in defaults.bandpass_limits.items():
            self._pipeline.set_bandpass_limits(mode, lo, hi)
        self._pipeline.set_presence_db(defaults.presence_db)
        self._pipeline.set_presence_freq(defaults.presence_freq)
        self._pipeline.set_presence_q(defaults.presence_q)
        self._pipeline.set_pitch_shift(defaults.pitch_shift_hz)
        self._config.dsp.exciter_drive = defaults.exciter_drive
        self._config.dsp.exciter_mix   = defaults.exciter_mix
        self._pipeline.set_exciter_drive(defaults.exciter_drive)
        self._pipeline.set_exciter_mix(defaults.exciter_mix)
        self._load_values()

    # ------------------------------------------------------------------
    # Handlers y API pública
    # ------------------------------------------------------------------

    def _on_bp(self, mode: RadioMode, lo: int = None, hi: int = None) -> None:
        cur_lo, cur_hi = self._config.dsp.bandpass_limits[mode]
        lo = lo if lo is not None else cur_lo
        hi = hi if hi is not None else cur_hi
        if lo >= hi:
            return
        self._pipeline.set_bandpass_limits(mode, lo, hi)

    def _on_block_size(self, idx: float) -> None:
        self._config.audio.block_size = _BLOCK_SIZES[int(idx)]

    def _on_exciter_drive(self, val: float) -> None:
        self._config.dsp.exciter_drive = val
        self._pipeline.set_exciter_drive(val)

    def _on_exciter_mix(self, val: float) -> None:
        self._config.dsp.exciter_mix = val
        self._pipeline.set_exciter_mix(val)

    def reload(self) -> None:
        self._load_values()

    def set_processing_active(self, active: bool) -> None:
        self._s_block.set_enabled(not active)


# ---------------------------------------------------------------------------
# Pestaña Avanzada Impulsos  (Blanker + ANF)
# ---------------------------------------------------------------------------

class AdvancedImpulseTab(QWidget):

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_blanker_group())
        layout.addWidget(self._build_anf_group())
        layout.addWidget(_reset_button_widget(self._reset_defaults))
        layout.addStretch()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()

    # ------------------------------------------------------------------
    # Grupos
    # ------------------------------------------------------------------

    def _build_blanker_group(self) -> QGroupBox:
        group = QGroupBox("Supresor de Impulsos  (se aplica en tiempo real)")
        layout = QVBoxLayout(group)

        hits_row = QHBoxLayout()
        hits_row.addWidget(QLabel("Actividad:"))
        self._lbl_blanker_hits = QLabel("—")
        self._lbl_blanker_hits.setStyleSheet("color: #888;")
        hits_row.addWidget(self._lbl_blanker_hits)
        hits_row.addStretch()
        layout.addLayout(hits_row)

        self._s_blanker_frame = SliderRow(
            "Umbral de trama (10 ms):",
            min_val=5.0, max_val=100.0,
            default=self._config.dsp.blanker_frame,
            step=1.0, unit="×", fmt="{:.0f}",
        )
        self._s_blanker_frame._update_label = lambda v: self._s_blanker_frame._val_lbl.setText(
            f"{int(v)}×  ({'agresivo' if v < 10 else 'normal' if v < 35 else 'suave'})"
        )
        self._s_blanker_frame._val_lbl.setFixedWidth(110)
        self._s_blanker_frame.valueChanged.connect(self._pipeline.set_blanker_frame)
        layout.addWidget(self._s_blanker_frame)
        layout.addWidget(_note("  ↳ Bajo=captura más impulsos (QRN fuerte). Alto=solo blancos muy grandes."))

        self._s_blanker_mini = SliderRow(
            "Umbral micro (0.67 ms):",
            min_val=3.0, max_val=30.0,
            default=self._config.dsp.blanker_mini,
            step=1.0, unit="×", fmt="{:.0f}",
        )
        self._s_blanker_mini._update_label = lambda v: self._s_blanker_mini._val_lbl.setText(
            f"{int(v)}×  ({'agresivo' if v < 5 else 'normal' if v < 15 else 'suave'})"
        )
        self._s_blanker_mini._val_lbl.setFixedWidth(110)
        self._s_blanker_mini.valueChanged.connect(self._pipeline.set_blanker_mini)
        layout.addWidget(self._s_blanker_mini)
        layout.addWidget(_note("  ↳ Detecta frituras y crackles cortos. Bajo=elimina más, puede recortar consonantes."))
        return group

    def _build_anf_group(self) -> QGroupBox:
        group = QGroupBox("ANF — Filtro de Muesca Espectral  (parámetros técnicos)")
        layout = QVBoxLayout(group)

        anf_row = QHBoxLayout()
        anf_row.addWidget(QLabel("Actividad:"))
        self._lbl_anf_activity = QLabel("—")
        self._lbl_anf_activity.setStyleSheet("color: #888;")
        anf_row.addWidget(self._lbl_anf_activity)
        anf_row.addStretch()
        layout.addLayout(anf_row)

        self._s_anf_threshold = SliderRow(
            "Sensibilidad:",
            min_val=1.5, max_val=10.0,
            default=self._config.dsp.anf_threshold,
            step=0.1, unit="x", fmt="{:.1f}",
        )
        self._s_anf_threshold._update_label = lambda v: self._s_anf_threshold._val_lbl.setText(
            f"{v:.1f}×  ({'alta' if v < 2.5 else 'media' if v < 5.0 else 'baja'})"
        )
        self._s_anf_threshold._val_lbl.setFixedWidth(90)
        self._s_anf_threshold.valueChanged.connect(self._pipeline.set_anf_threshold)
        layout.addWidget(self._s_anf_threshold)
        layout.addWidget(_note("  ↳ Ratio bin/baseline para detectar un tono. Bajar si hay tonos débiles."))

        self._s_anf_depth = SliderRow(
            "Profundidad:",
            min_val=0.0, max_val=1.0,
            default=self._config.dsp.anf_depth,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_anf_depth._update_label = lambda v: self._s_anf_depth._val_lbl.setText(
            f"{v*100:.0f}%"
        )
        self._s_anf_depth.valueChanged.connect(self._pipeline.set_anf_depth)
        layout.addWidget(self._s_anf_depth)
        layout.addWidget(_note("  ↳ Atenuación aplicada al tono detectado. 100%=silencia, 50%=reduce 6dB."))
        return group

    # ------------------------------------------------------------------
    # Stats en tiempo real
    # ------------------------------------------------------------------

    def _update_stats(self) -> None:
        hits = self._pipeline.pop_blanker_hits()
        if hits == 0:
            self._lbl_blanker_hits.setText("—")
            self._lbl_blanker_hits.setStyleSheet("color: #888;")
        else:
            self._lbl_blanker_hits.setText(f"⚡ {hits * 2} /s")
            self._lbl_blanker_hits.setStyleSheet("color: #ff9800; font-weight: bold;")

        bins = self._pipeline.anf_notched_bins
        if bins == 0:
            self._lbl_anf_activity.setText("—")
            self._lbl_anf_activity.setStyleSheet("color: #888;")
        else:
            self._lbl_anf_activity.setText(f"🔇 {bins} {'tono' if bins == 1 else 'tonos'}")
            self._lbl_anf_activity.setStyleSheet("color: #4fc3f7; font-weight: bold;")

    # ------------------------------------------------------------------
    # Carga y reset
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        cfg = self._config.dsp
        self._s_blanker_frame.set_value(cfg.blanker_frame)
        self._s_blanker_mini.set_value(cfg.blanker_mini)
        self._s_anf_threshold.set_value(cfg.anf_threshold)
        self._s_anf_depth.set_value(cfg.anf_depth)

    def _reset_defaults(self) -> None:
        defaults = DSPConfig()
        self._config.dsp.blanker_frame = defaults.blanker_frame
        self._config.dsp.blanker_mini  = defaults.blanker_mini
        self._config.dsp.anf_threshold = defaults.anf_threshold
        self._config.dsp.anf_depth     = defaults.anf_depth
        self._pipeline.set_blanker_frame(defaults.blanker_frame)
        self._pipeline.set_blanker_mini(defaults.blanker_mini)
        self._pipeline.set_anf_threshold(defaults.anf_threshold)
        self._pipeline.set_anf_depth(defaults.anf_depth)
        self._load_values()

    def reload(self) -> None:
        self._load_values()


# ---------------------------------------------------------------------------
# Pestaña Avanzada Cancelador  (Wiener + Squelch + sub-módulos)
# ---------------------------------------------------------------------------

class AdvancedCancellerTab(QWidget):

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_canceller_group())
        layout.addWidget(self._build_squelch_group())
        layout.addWidget(self._build_perceptual_floor_group())
        layout.addWidget(self._build_post_filter_group())
        layout.addWidget(self._build_pitch_group())
        layout.addWidget(_reset_button_widget(self._reset_defaults))
        layout.addStretch()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()

    # ------------------------------------------------------------------
    # Grupos
    # ------------------------------------------------------------------

    def _build_canceller_group(self) -> QGroupBox:
        group = QGroupBox("Cancelador de Ruido  (Wiener Log-MMSE)")
        layout = QVBoxLayout(group)

        noise_row = QHBoxLayout()
        noise_row.addWidget(QLabel("Reducción:"))
        self._lbl_noise_db = QLabel("—")
        self._lbl_noise_db.setStyleSheet("color: #888;")
        noise_row.addWidget(self._lbl_noise_db)
        noise_row.addSpacing(16)
        noise_row.addWidget(QLabel("Voz:"))
        self._lbl_noise_vp = QLabel("—")
        self._lbl_noise_vp.setStyleSheet("color: #888;")
        noise_row.addWidget(self._lbl_noise_vp)
        noise_row.addStretch()
        layout.addLayout(noise_row)

        self._s_noise_floor = SliderRow(
            "Piso espectral:",
            min_val=0.05, max_val=0.3,
            default=self._config.dsp.noise_floor,
            step=0.01, unit="", fmt="{:.2f}",
        )
        self._s_noise_floor.valueChanged.connect(self._on_noise_floor)
        layout.addWidget(self._s_noise_floor)
        layout.addWidget(_note("  ↳ Ganancia mínima por bin. 0.10=suprime 20dB (recomendado). Mínimo 0.05."))

        self._s_noise_smooth = SliderRow(
            "Anti-gorgojeo (β):",
            min_val=0.0, max_val=0.98,
            default=self._config.dsp.noise_smooth,
            step=0.01, unit="", fmt="{:.2f}",
        )
        self._s_noise_smooth._update_label = lambda v: self._s_noise_smooth._val_lbl.setText(
            f"{'OFF' if v == 0 else f'{v*100:.0f}%'}  ({'reactivo' if v < 0.5 else 'normal' if v < 0.9 else 'suave'})"
        )
        self._s_noise_smooth._val_lbl.setFixedWidth(110)
        self._s_noise_smooth.valueChanged.connect(self._pipeline.set_noise_smooth)
        layout.addWidget(self._s_noise_smooth)
        layout.addWidget(_note("  ↳ Release (retorno al ruido): alto (97-98%)=sin gorgojeo. Bajo=más reactivo."))

        self._s_noise_attack = SliderRow(
            "Velocidad ataque:",
            min_val=0.50, max_val=0.92,
            default=self._config.dsp.noise_attack,
            step=0.02, unit="", fmt="{:.2f}",
        )
        self._s_noise_attack._update_label = lambda v: self._s_noise_attack._val_lbl.setText(
            f"{v*100:.0f}%  ({'rápido' if v < 0.68 else 'normal' if v < 0.84 else 'suave'})"
        )
        self._s_noise_attack._val_lbl.setFixedWidth(110)
        self._s_noise_attack.valueChanged.connect(self._on_noise_attack)
        layout.addWidget(self._s_noise_attack)
        layout.addWidget(_note("  ↳ Attack (onset de voz): bajo=consonantes nítidas. Alto=transiciones suaves."))
        return group

    def _build_squelch_group(self) -> QGroupBox:
        group = QGroupBox("Squelch de voz  (activar en Módulos Activos)")
        layout = QVBoxLayout(group)

        sq_row = QHBoxLayout()
        sq_row.addWidget(QLabel("Nivel de voz:"))
        self._lbl_sq_vp = QLabel("—")
        self._lbl_sq_vp.setStyleSheet("color: #888;")
        sq_row.addWidget(self._lbl_sq_vp)
        sq_row.addSpacing(20)
        sq_row.addWidget(QLabel("Gate:"))
        self._lbl_sq_gate = QLabel("—")
        self._lbl_sq_gate.setStyleSheet("color: #888;")
        sq_row.addWidget(self._lbl_sq_gate)
        sq_row.addStretch()
        layout.addLayout(sq_row)
        layout.addWidget(_note(
            "  ↳ Ajustar Umbral para que quede entre el nivel de voz en silencio (ruido) y con señal."
        ))

        self._s_squelch_threshold = SliderRow(
            "Umbral:",
            min_val=0.05, max_val=0.60,
            default=self._config.dsp.squelch_threshold,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_squelch_threshold._update_label = lambda v: self._s_squelch_threshold._val_lbl.setText(
            f"{v:.2f}  ({'sensible' if v < 0.15 else 'normal' if v < 0.35 else 'selectivo'})"
        )
        self._s_squelch_threshold._val_lbl.setFixedWidth(110)
        self._s_squelch_threshold.valueChanged.connect(self._on_squelch_threshold)
        layout.addWidget(self._s_squelch_threshold)
        layout.addWidget(_note("  ↳ Bajo=abre con señal débil. Alto=solo con voz fuerte. Default 0.20."))

        self._s_squelch_hold = SliderRow(
            "Retención:",
            min_val=0.0, max_val=1000.0,
            default=self._config.dsp.squelch_hold_ms,
            step=50.0, unit="ms", fmt="{:.0f}",
        )
        self._s_squelch_hold.valueChanged.connect(self._on_squelch_hold)
        layout.addWidget(self._s_squelch_hold)
        layout.addWidget(_note("  ↳ Tiempo que el gate permanece abierto tras perder la voz. Default 300 ms."))
        return group

    def _build_perceptual_floor_group(self) -> QGroupBox:
        group = QGroupBox("Piso espectral perceptual  (activar en Módulos Activos)")
        layout = QVBoxLayout(group)

        self._s_pf_boost = SliderRow(
            "Amplitud boost vocal:",
            min_val=0.0, max_val=1.5,
            default=self._config.dsp.perceptual_floor_boost,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pf_boost._update_label = lambda v: self._s_pf_boost._val_lbl.setText(
            f"+{v*100:.0f}%  ({'sin boost' if v < 0.05 else 'suave' if v < 0.5 else 'normal' if v < 1.0 else 'fuerte'})"
        )
        self._s_pf_boost._val_lbl.setFixedWidth(110)
        self._s_pf_boost.valueChanged.connect(self._on_pf_boost)
        layout.addWidget(self._s_pf_boost)
        layout.addWidget(_note("  ↳ Cuánto se eleva el piso en la zona vocal. 75%=default."))

        self._s_pf_center = SliderRow(
            "Centro del boost:",
            min_val=200.0, max_val=1200.0,
            default=self._config.dsp.perceptual_floor_center,
            step=25.0, unit="Hz", fmt="{:.0f}",
        )
        self._s_pf_center._update_label = lambda v: self._s_pf_center._val_lbl.setText(
            f"{v:.0f} Hz  ({'grave' if v < 350 else 'vocal' if v < 700 else 'medio'})"
        )
        self._s_pf_center._val_lbl.setFixedWidth(110)
        self._s_pf_center.valueChanged.connect(self._on_pf_center)
        layout.addWidget(self._s_pf_center)
        layout.addWidget(_note("  ↳ Frecuencia de máximo boost. 500 Hz=AM/SSB típico. 350 Hz=SSB muy grave."))

        self._s_pf_rolloff_hz = SliderRow(
            "Inicio del rolloff:",
            min_val=1000.0, max_val=6000.0,
            default=self._config.dsp.perceptual_floor_rolloff_hz,
            step=100.0, unit="Hz", fmt="{:.0f}",
        )
        self._s_pf_rolloff_hz._update_label = lambda v: self._s_pf_rolloff_hz._val_lbl.setText(
            f"{v:.0f} Hz  ({'pronto' if v < 2000 else 'normal' if v < 4000 else 'tarde'})"
        )
        self._s_pf_rolloff_hz._val_lbl.setFixedWidth(110)
        self._s_pf_rolloff_hz.valueChanged.connect(self._on_pf_rolloff_hz)
        layout.addWidget(self._s_pf_rolloff_hz)
        layout.addWidget(_note("  ↳ A partir de qué frecuencia baja el piso. 3000 Hz=default."))

        self._s_pf_rolloff_depth = SliderRow(
            "Profundidad del rolloff:",
            min_val=0.0, max_val=0.70,
            default=self._config.dsp.perceptual_floor_rolloff_depth,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pf_rolloff_depth._update_label = lambda v: self._s_pf_rolloff_depth._val_lbl.setText(
            f"-{v*100:.0f}%  ({'sin rolloff' if v < 0.05 else 'suave' if v < 0.3 else 'normal' if v < 0.55 else 'fuerte'})"
        )
        self._s_pf_rolloff_depth._val_lbl.setFixedWidth(110)
        self._s_pf_rolloff_depth.valueChanged.connect(self._on_pf_rolloff_depth)
        layout.addWidget(self._s_pf_rolloff_depth)
        layout.addWidget(_note("  ↳ Cuánto cae el piso en altas frecuencias. 55%=default."))
        return group

    def _build_post_filter_group(self) -> QGroupBox:
        group = QGroupBox("Post-filtro espectral  (activar en Módulos Activos)")
        layout = QVBoxLayout(group)

        self._s_post_filter = SliderRow(
            "Agresividad:",
            min_val=0.0, max_val=3.0,
            default=self._config.dsp.post_filter_strength,
            step=0.1, unit="", fmt="{:.1f}",
        )
        self._s_post_filter._update_label = lambda v: self._s_post_filter._val_lbl.setText(
            f"{v:.1f}  ({'desactivado' if v == 0 else 'suave' if v < 0.8 else 'normal' if v < 1.8 else 'agresivo'})"
        )
        self._s_post_filter._val_lbl.setFixedWidth(110)
        self._s_post_filter.valueChanged.connect(self._on_post_filter_strength)
        layout.addWidget(self._s_post_filter)
        layout.addWidget(_note("  ↳ Supresión extra en bins de ruido para eliminar 'pitidos fantasma'. 0=off, 1=moderado, 2=agresivo."))
        return group

    def _build_pitch_group(self) -> QGroupBox:
        group = QGroupBox("Refuerzo de pitch SSB  (activar en Módulos Activos)")
        layout = QVBoxLayout(group)

        self._s_pitch_strength = SliderRow(
            "Protección de armónicos:",
            min_val=0.0, max_val=1.0,
            default=self._config.dsp.pitch_enhance_strength,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pitch_strength._update_label = lambda v: self._s_pitch_strength._val_lbl.setText(
            f"{v*100:.0f}%  ({'suave' if v < 0.4 else 'normal' if v < 0.75 else 'fuerte'})"
        )
        self._s_pitch_strength._val_lbl.setFixedWidth(110)
        self._s_pitch_strength.valueChanged.connect(self._on_pitch_strength)
        layout.addWidget(self._s_pitch_strength)
        layout.addWidget(_note("  ↳ Cuánto eleva la probabilidad de voz en bins de armónicos. 70%=recomendado."))
        return group

    # ------------------------------------------------------------------
    # Stats en tiempo real
    # ------------------------------------------------------------------

    def _update_stats(self) -> None:
        vp = self._pipeline.noise_voice_prob
        thr = self._config.dsp.squelch_threshold

        # Indicador squelch (siempre visible aunque no haya perfil)
        self._lbl_sq_vp.setText(f"{vp*100:.0f}%")
        if vp > thr:
            color_sq = "#4fc3f7"   # azul — por encima del umbral → gate abre
        elif vp > thr * 0.5:
            color_sq = "#fff176"   # amarillo — zona marginal
        else:
            color_sq = "#888"      # gris — ruido claro
        self._lbl_sq_vp.setStyleSheet(f"color: {color_sq}; font-weight: bold;")

        gate_open = self._pipeline.squelch_gate_open
        self._lbl_sq_gate.setText("ABIERTO" if gate_open else "CERRADO")
        self._lbl_sq_gate.setStyleSheet(
            "color: #69f0ae; font-weight: bold;" if gate_open
            else "color: #888; font-weight: bold;"
        )

        if not self._pipeline.noise_has_profile:
            self._lbl_noise_db.setText("sin perfil")
            self._lbl_noise_db.setStyleSheet("color: #888;")
            self._lbl_noise_vp.setText("—")
            self._lbl_noise_vp.setStyleSheet("color: #888;")
            return
        db = self._pipeline.noise_reduction_db
        self._lbl_noise_db.setText(f"{db:.1f} dB")
        color_db = "#69f0ae" if db < -10 else "#fff176" if db < -3 else "#888"
        self._lbl_noise_db.setStyleSheet(f"color: {color_db}; font-weight: bold;")

        self._lbl_noise_vp.setText(f"{vp*100:.0f}%")
        color_vp = "#4fc3f7" if vp > 0.5 else "#fff176" if vp > 0.15 else "#888"
        self._lbl_noise_vp.setStyleSheet(f"color: {color_vp}; font-weight: bold;")

    # ------------------------------------------------------------------
    # Carga y reset
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        cfg = self._config.dsp
        self._s_noise_floor.set_value(cfg.noise_floor)
        self._s_noise_smooth.set_value(cfg.noise_smooth)
        self._s_noise_attack.set_value(cfg.noise_attack)
        self._s_squelch_threshold.set_value(cfg.squelch_threshold)
        self._s_squelch_hold.set_value(cfg.squelch_hold_ms)
        self._s_pf_boost.set_value(cfg.perceptual_floor_boost)
        self._s_pf_center.set_value(cfg.perceptual_floor_center)
        self._s_pf_rolloff_hz.set_value(cfg.perceptual_floor_rolloff_hz)
        self._s_pf_rolloff_depth.set_value(cfg.perceptual_floor_rolloff_depth)
        self._s_post_filter.set_value(cfg.post_filter_strength)
        self._s_pitch_strength.set_value(cfg.pitch_enhance_strength)

    def _reset_defaults(self) -> None:
        defaults = DSPConfig()
        self._config.dsp.noise_floor    = defaults.noise_floor
        self._config.dsp.noise_smooth   = defaults.noise_smooth
        self._config.dsp.noise_attack   = defaults.noise_attack
        self._config.dsp.squelch_threshold = defaults.squelch_threshold
        self._config.dsp.squelch_hold_ms   = defaults.squelch_hold_ms
        self._config.dsp.perceptual_floor_boost        = defaults.perceptual_floor_boost
        self._config.dsp.perceptual_floor_center       = defaults.perceptual_floor_center
        self._config.dsp.perceptual_floor_rolloff_hz   = defaults.perceptual_floor_rolloff_hz
        self._config.dsp.perceptual_floor_rolloff_depth = defaults.perceptual_floor_rolloff_depth
        self._config.dsp.post_filter_strength   = defaults.post_filter_strength
        self._config.dsp.pitch_enhance_strength = defaults.pitch_enhance_strength
        self._pipeline.set_noise_floor(defaults.noise_floor)
        self._pipeline.set_noise_smooth(defaults.noise_smooth)
        self._pipeline.set_noise_attack(defaults.noise_attack)
        self._pipeline.set_squelch_threshold(defaults.squelch_threshold)
        self._pipeline.set_squelch_hold_ms(defaults.squelch_hold_ms)
        self._pipeline.set_pf_boost(defaults.perceptual_floor_boost)
        self._pipeline.set_pf_center(defaults.perceptual_floor_center)
        self._pipeline.set_pf_rolloff_hz(defaults.perceptual_floor_rolloff_hz)
        self._pipeline.set_pf_rolloff_depth(defaults.perceptual_floor_rolloff_depth)
        self._pipeline.set_post_filter_strength(defaults.post_filter_strength)
        self._pipeline.set_pitch_enhance_strength(defaults.pitch_enhance_strength)
        self._load_values()

    def reload(self) -> None:
        self._load_values()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_noise_floor(self, val: float) -> None:
        self._config.dsp.noise_floor = val
        self._pipeline.set_noise_floor(val)

    def _on_noise_attack(self, val: float) -> None:
        self._config.dsp.noise_attack = val
        self._pipeline.set_noise_attack(val)

    def _on_squelch_threshold(self, val: float) -> None:
        self._config.dsp.squelch_threshold = val
        self._pipeline.set_squelch_threshold(val)

    def _on_squelch_hold(self, val: float) -> None:
        self._config.dsp.squelch_hold_ms = val
        self._pipeline.set_squelch_hold_ms(val)

    def _on_pf_boost(self, val: float) -> None:
        self._config.dsp.perceptual_floor_boost = val
        self._pipeline.set_pf_boost(val)

    def _on_pf_center(self, val: float) -> None:
        self._config.dsp.perceptual_floor_center = val
        self._pipeline.set_pf_center(val)

    def _on_pf_rolloff_hz(self, val: float) -> None:
        self._config.dsp.perceptual_floor_rolloff_hz = val
        self._pipeline.set_pf_rolloff_hz(val)

    def _on_pf_rolloff_depth(self, val: float) -> None:
        self._config.dsp.perceptual_floor_rolloff_depth = val
        self._pipeline.set_pf_rolloff_depth(val)

    def _on_post_filter_strength(self, val: float) -> None:
        self._config.dsp.post_filter_strength = val
        self._pipeline.set_post_filter_strength(val)

    def _on_pitch_strength(self, val: float) -> None:
        self._config.dsp.pitch_enhance_strength = val
        self._pipeline.set_pitch_enhance_strength(val)
