import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLabel,
    QScrollArea, QPushButton, QHBoxLayout, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from config import AppConfig, RadioMode, AudioConfig, DSPConfig
from pipeline import ProcessingPipeline
from ui.slider_row import SliderRow
from i18n import tr

_BLOCK_SIZES    = [240, 480, 960, 1920]
_FILTER_ORDERS  = [2, 4, 6, 8]

# Valores de fábrica: el "default" de cada SliderRow (menú click derecho) debe ser
# siempre el recomendado, NO el valor persistido de la sesión anterior.
# La posición inicial del slider se carga aparte en _load_values().
_DSP_DEF   = DSPConfig()
_AUDIO_DEF = AudioConfig()


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
    btn = QPushButton(tr("↺  Restaurar valores por defecto"))
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
        self.refresh_enabled_states()

    def refresh_enabled_states(self) -> None:
        """Habilita/deshabilita controles según el estado de los módulos en Módulos Activos."""
        dsp = self._config.dsp
        bp = dsp.bandpass_pre_enabled or dsp.bandpass_post_enabled
        for s in (self._s_am_lo, self._s_am_hi, self._s_ssb_lo, self._s_ssb_hi, self._s_order):
            s.set_enabled(bp)
        for s in (self._s_presence_freq, self._s_presence, self._s_presence_q,
                  self._s_body_freq, self._s_body):
            s.set_enabled(dsp.presence_enabled)
        for s in (self._s_exciter_drive, self._s_exciter_mix):
            s.set_enabled(dsp.exciter_enabled)
        custom = dsp.agc_preset == "custom"
        for s in (self._s_agc_target, self._s_agc_max_gain,
                  self._s_agc_attack, self._s_agc_release):
            s.set_enabled(custom)

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_audio_group())
        layout.addWidget(self._build_agc_group())
        layout.addWidget(self._build_dsp_group())
        layout.addWidget(self._build_voice_group())
        layout.addWidget(self._build_exciter_group())
        layout.addWidget(_reset_button_widget(self._reset_defaults))
        layout.addStretch()

    # ------------------------------------------------------------------
    # Grupos
    # ------------------------------------------------------------------

    def _build_audio_group(self) -> QGroupBox:
        group = QGroupBox(tr("Audio"))
        layout = QVBoxLayout(group)

        self._s_block = SliderRow(
            tr("Tamaño de bloque:"),
            min_val=0, max_val=len(_BLOCK_SIZES) - 1,
            default=_BLOCK_SIZES.index(_AUDIO_DEF.block_size),
            step=1, unit="", fmt="{}",
        )
        self._s_block._fmt = ""
        self._s_block._update_label = lambda v: self._s_block._val_lbl.setText(
            tr("{n} muestras ({ms:.0f} ms)").format(n=_BLOCK_SIZES[int(v)], ms=_BLOCK_SIZES[int(v)]/48)
        )
        self._s_block._val_lbl.setFixedWidth(130)
        self._s_block.valueChanged.connect(self._on_block_size)
        layout.addWidget(self._s_block)
        layout.addWidget(_note(tr("  ↳ Menor = menor latencia. Requiere reiniciar el procesamiento.")))
        return group

    def _build_agc_group(self) -> QGroupBox:
        group = QGroupBox(tr("AGC Personalizado  (activar con AGC: Custom en Principal)"))
        layout = QVBoxLayout(group)

        self._s_agc_target = SliderRow(
            tr("Nivel objetivo:"),
            min_val=-30.0, max_val=-6.0,
            default=_DSP_DEF.agc_target_dbfs,
            step=1.0, unit="dBFS", fmt="{:.0f}",
        )
        self._s_agc_target._update_label = lambda v: self._s_agc_target._val_lbl.setText(
            f"{v:.0f} dBFS  ({tr('bajo') if v < -24 else tr('normal') if v < -14 else tr('alto')})"
        )
        self._s_agc_target._val_lbl.setFixedWidth(110)
        self._s_agc_target.valueChanged.connect(self._pipeline.set_agc_target)
        layout.addWidget(self._s_agc_target)
        layout.addWidget(_note(tr("  ↳ Nivel RMS al que el AGC lleva la señal. -20 dBFS=default, más alto=más fuerte.")))

        self._s_agc_max_gain = SliderRow(
            tr("Ganancia máxima:"),
            min_val=0.0, max_val=60.0,
            default=_DSP_DEF.agc_max_gain_db,
            step=1.0, unit="dB", fmt="{:.0f}",
        )
        self._s_agc_max_gain._update_label = lambda v: self._s_agc_max_gain._val_lbl.setText(
            f"+{v:.0f} dB  ({tr('limitado') if v < 20 else tr('normal') if v < 45 else tr('máximo')})"
        )
        self._s_agc_max_gain._val_lbl.setFixedWidth(110)
        self._s_agc_max_gain.valueChanged.connect(self._pipeline.set_agc_max_gain)
        layout.addWidget(self._s_agc_max_gain)
        layout.addWidget(_note(tr("  ↳ Tope de amplificación en señales débiles. Bajo=no levanta el ruido de fondo.")))

        self._s_agc_attack = SliderRow(
            tr("Ataque:"),
            min_val=1.0, max_val=200.0,
            default=_DSP_DEF.agc_attack_ms,
            step=1.0, unit="ms", fmt="{:.0f}",
        )
        self._s_agc_attack._update_label = lambda v: self._s_agc_attack._val_lbl.setText(
            f"{v:.0f} ms  ({tr('rápido') if v < 15 else tr('normal') if v < 60 else tr('lento')})"
        )
        self._s_agc_attack._val_lbl.setFixedWidth(110)
        self._s_agc_attack.valueChanged.connect(self._pipeline.set_agc_attack)
        layout.addWidget(self._s_agc_attack)
        layout.addWidget(_note(tr("  ↳ Cuán rápido baja la ganancia ante señal fuerte. Rápido=protege, puede bombear.")))

        self._s_agc_release = SliderRow(
            tr("Release:"),
            min_val=100.0, max_val=8000.0,
            default=_DSP_DEF.agc_release_ms,
            step=100.0, unit="ms", fmt="{:.0f}",
        )
        self._s_agc_release._update_label = lambda v: self._s_agc_release._val_lbl.setText(
            f"{v:.0f} ms  ({tr('rápido') if v < 1000 else tr('normal') if v < 4000 else tr('lento')})"
        )
        self._s_agc_release._val_lbl.setFixedWidth(110)
        self._s_agc_release.valueChanged.connect(self._pipeline.set_agc_release)
        layout.addWidget(self._s_agc_release)
        layout.addWidget(_note(tr("  ↳ Cuán rápido recupera ganancia al caer la señal. Lento=estable en QSB, rápido=sigue el fading.")))
        return group

    def _build_dsp_group(self) -> QGroupBox:
        group = QGroupBox(tr("Filtros DSP  (se aplican en tiempo real)"))
        layout = QVBoxLayout(group)

        self._s_am_lo  = _freq_slider(tr("AM – Hz inferior:"),  _DSP_DEF.bandpass_limits[RadioMode.AM][0])
        self._s_am_hi  = _freq_slider(tr("AM – Hz superior:"),  _DSP_DEF.bandpass_limits[RadioMode.AM][1],  hi=10000)
        self._s_ssb_lo = _freq_slider(tr("SSB – Hz inferior:"), _DSP_DEF.bandpass_limits[RadioMode.SSB][0])
        self._s_ssb_hi = _freq_slider(tr("SSB – Hz superior:"), _DSP_DEF.bandpass_limits[RadioMode.SSB][1], hi=6000)

        self._s_am_lo.valueChanged.connect(lambda v: self._on_bp(RadioMode.AM,  lo=int(v)))
        self._s_am_hi.valueChanged.connect(lambda v: self._on_bp(RadioMode.AM,  hi=int(v)))
        self._s_ssb_lo.valueChanged.connect(lambda v: self._on_bp(RadioMode.SSB, lo=int(v)))
        self._s_ssb_hi.valueChanged.connect(lambda v: self._on_bp(RadioMode.SSB, hi=int(v)))

        for s in (self._s_am_lo, self._s_am_hi, self._s_ssb_lo, self._s_ssb_hi):
            layout.addWidget(s)

        self._s_order = SliderRow(
            tr("Orden del filtro:"),
            min_val=0, max_val=len(_FILTER_ORDERS) - 1,
            default=_FILTER_ORDERS.index(_DSP_DEF.filter_order),
            step=1,
        )
        self._s_order._update_label = lambda v: self._s_order._val_lbl.setText(
            tr("Orden {n}").format(n=_FILTER_ORDERS[int(v)])
        )
        self._s_order.valueChanged.connect(
            lambda v: self._pipeline.set_filter_order(_FILTER_ORDERS[int(v)])
        )
        layout.addWidget(self._s_order)
        return group

    def _build_voice_group(self) -> QGroupBox:
        group = QGroupBox(tr("Voz  (se aplica en tiempo real)"))
        layout = QVBoxLayout(group)

        self._s_body_freq = SliderRow(
            tr("Frecuencia de cuerpo:"),
            min_val=150, max_val=800,
            default=int(_DSP_DEF.body_freq),
            step=25, unit="Hz", fmt="{:.0f}",
        )
        self._s_body_freq._update_label = lambda v: self._s_body_freq._val_lbl.setText(
            f"{v:.0f} Hz  ({tr('grave') if v < 300 else tr('cuerpo') if v < 550 else tr('calidez')})"
        )
        self._s_body_freq._val_lbl.setFixedWidth(110)
        self._s_body_freq.valueChanged.connect(self._pipeline.set_body_freq)
        layout.addWidget(self._s_body_freq)

        self._s_body = SliderRow(
            tr("Cuerpo (ganancia):"),
            min_val=-3.0, max_val=10.0,
            default=0.0,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_body.valueChanged.connect(self._pipeline.set_body_db)
        layout.addWidget(self._s_body)
        layout.addWidget(_note(tr("  ↳ Refuerza los graves de la voz (fundamentales). 0 dB=apagado, +3–5 dB=voz con más cuerpo.")))

        sep_body = QFrame()
        sep_body.setFrameShape(QFrame.Shape.HLine)
        sep_body.setStyleSheet("color: #444;")
        layout.addWidget(sep_body)

        self._s_presence_freq = SliderRow(
            tr("Frecuencia de presencia:"),
            min_val=1000, max_val=2000,
            default=int(_DSP_DEF.presence_freq),
            step=25, unit="Hz", fmt="{:.0f}",
        )
        self._s_presence_freq._update_label = lambda v: self._s_presence_freq._val_lbl.setText(
            f"{v:.0f} Hz  ({tr('media-baja') if v < 1300 else tr('media') if v < 1700 else tr('presencia')})"
        )
        self._s_presence_freq._val_lbl.setFixedWidth(140)
        self._s_presence_freq.valueChanged.connect(self._pipeline.set_presence_freq)
        layout.addWidget(self._s_presence_freq)

        self._s_presence = SliderRow(
            tr("Presencia (ganancia):"),
            min_val=-3.0, max_val=10.0,
            default=0.0,
            step=0.5, unit="dB", fmt="{:+.1f}",
        )
        self._s_presence.valueChanged.connect(self._pipeline.set_presence_db)
        layout.addWidget(self._s_presence)
        layout.addWidget(_note(tr("  ↳ Frecuencia + ganancia del pico vocal. 0 dB=neutro, +4–6 dB=voz de radio.")))

        self._s_presence_q = SliderRow(
            tr("Ancho de presencia (Q):"),
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
        layout.addWidget(_note(tr("  ↳ Q bajo = boost ancho (más cálido), Q alto = pico estrecho (más nasal).")))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        layout.addWidget(sep)

        self._s_pitch = SliderRow(
            tr("Corrección de tono SSB:"),
            min_val=-500, max_val=500,
            default=int(_DSP_DEF.pitch_shift_hz),
            step=10, unit="Hz", fmt="{:+.0f}",
        )
        self._s_pitch._update_label = lambda v: self._s_pitch._val_lbl.setText(
            f"{v:+.0f} Hz  ({tr('neutro') if abs(v) < 5 else tr('agudo') if v > 0 else tr('grave')})"
        )
        self._s_pitch._val_lbl.setFixedWidth(110)
        self._s_pitch.valueChanged.connect(self._pipeline.set_pitch_shift)
        layout.addWidget(self._s_pitch)
        layout.addWidget(_note(tr("  ↳ Corrige offset de BFO en SSB. +100 Hz si la voz suena grave, -100 Hz si suena aguda.")))
        return group

    def _build_exciter_group(self) -> QGroupBox:
        group = QGroupBox(tr("Excitador Armónico  (se aplica en tiempo real)"))
        layout = QVBoxLayout(group)

        self._s_exciter_drive = SliderRow(
            tr("Drive:"),
            min_val=1.0, max_val=10.0,
            default=_DSP_DEF.exciter_drive,
            step=0.5, unit="", fmt="{:.1f}",
        )
        self._s_exciter_drive._update_label = lambda v: self._s_exciter_drive._val_lbl.setText(
            f"{v:.1f}×  ({tr('suave') if v < 3.0 else tr('normal') if v < 6.0 else tr('agresivo')})"
        )
        self._s_exciter_drive._val_lbl.setFixedWidth(110)
        self._s_exciter_drive.valueChanged.connect(self._on_exciter_drive)
        layout.addWidget(self._s_exciter_drive)
        layout.addWidget(_note(tr("  ↳ Saturación tanh: cuántos armónicos se generan. Bajo=sutil, alto=efecto notable.")))

        self._s_exciter_mix = SliderRow(
            tr("Mezcla:"),
            min_val=0.0, max_val=1.0,
            default=_DSP_DEF.exciter_mix,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_exciter_mix._update_label = lambda v: self._s_exciter_mix._val_lbl.setText(
            f"{v*100:.0f}%"
        )
        self._s_exciter_mix.valueChanged.connect(self._on_exciter_mix)
        layout.addWidget(self._s_exciter_mix)
        layout.addWidget(_note(tr("  ↳ Nivel de armónicos mezclados. 20–40% = zona útil sin sonar artificial.")))
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
        self._s_agc_target.set_value(cfg.agc_target_dbfs)
        self._s_agc_max_gain.set_value(cfg.agc_max_gain_db)
        self._s_agc_attack.set_value(cfg.agc_attack_ms)
        self._s_agc_release.set_value(cfg.agc_release_ms)
        self._s_presence_freq.set_value(cfg.presence_freq)
        self._s_presence.set_value(cfg.presence_db)
        self._s_presence_q.set_value(cfg.presence_q)
        self._s_body_freq.set_value(cfg.body_freq)
        self._s_body.set_value(cfg.body_db)
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
        self._config.dsp.body_freq       = defaults.body_freq
        self._config.dsp.body_db         = defaults.body_db
        self._config.dsp.pitch_shift_hz  = defaults.pitch_shift_hz
        self._pipeline.set_filter_order(defaults.filter_order)
        for mode, (lo, hi) in defaults.bandpass_limits.items():
            self._pipeline.set_bandpass_limits(mode, lo, hi)
        self._pipeline.set_presence_db(defaults.presence_db)
        self._pipeline.set_presence_freq(defaults.presence_freq)
        self._pipeline.set_presence_q(defaults.presence_q)
        self._pipeline.set_body_freq(defaults.body_freq)
        self._pipeline.set_body_db(defaults.body_db)
        self._pipeline.set_pitch_shift(defaults.pitch_shift_hz)
        self._config.dsp.exciter_drive = defaults.exciter_drive
        self._config.dsp.exciter_mix   = defaults.exciter_mix
        self._pipeline.set_exciter_drive(defaults.exciter_drive)
        self._pipeline.set_exciter_mix(defaults.exciter_mix)
        self._pipeline.set_agc_target(defaults.agc_target_dbfs)
        self._pipeline.set_agc_max_gain(defaults.agc_max_gain_db)
        self._pipeline.set_agc_attack(defaults.agc_attack_ms)
        self._pipeline.set_agc_release(defaults.agc_release_ms)
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
        self.refresh_enabled_states()

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
        self.refresh_enabled_states()

    def refresh_enabled_states(self) -> None:
        """Habilita/deshabilita controles según el estado de los módulos en Módulos Activos."""
        dsp = self._config.dsp
        for s in (self._s_blanker_frame, self._s_blanker_mini):
            s.set_enabled(dsp.blanker_enabled)
        for s in (self._s_anf_threshold, self._s_anf_depth):
            s.set_enabled(dsp.anf_enabled)

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
        group = QGroupBox(tr("Supresor de Impulsos  (se aplica en tiempo real)"))
        layout = QVBoxLayout(group)

        hits_row = QHBoxLayout()
        hits_row.addWidget(QLabel(tr("Actividad:")))
        self._lbl_blanker_hits = QLabel("—")
        self._lbl_blanker_hits.setStyleSheet("color: #888;")
        hits_row.addWidget(self._lbl_blanker_hits)
        hits_row.addStretch()
        layout.addLayout(hits_row)

        self._s_blanker_frame = SliderRow(
            tr("Umbral de trama (10 ms):"),
            min_val=5.0, max_val=100.0,
            default=_DSP_DEF.blanker_frame,
            step=1.0, unit="×", fmt="{:.0f}",
        )
        self._s_blanker_frame._update_label = lambda v: self._s_blanker_frame._val_lbl.setText(
            f"{int(v)}×  ({tr('agresivo') if v < 10 else tr('normal') if v < 35 else tr('suave')})"
        )
        self._s_blanker_frame._val_lbl.setFixedWidth(110)
        self._s_blanker_frame.valueChanged.connect(self._pipeline.set_blanker_frame)
        layout.addWidget(self._s_blanker_frame)
        layout.addWidget(_note(tr("  ↳ Bajo=captura más impulsos (QRN fuerte). Alto=solo blancos muy grandes.")))

        self._s_blanker_mini = SliderRow(
            tr("Umbral micro (0.67 ms):"),
            min_val=3.0, max_val=30.0,
            default=_DSP_DEF.blanker_mini,
            step=1.0, unit="×", fmt="{:.0f}",
        )
        self._s_blanker_mini._update_label = lambda v: self._s_blanker_mini._val_lbl.setText(
            f"{int(v)}×  ({tr('agresivo') if v < 5 else tr('normal') if v < 15 else tr('suave')})"
        )
        self._s_blanker_mini._val_lbl.setFixedWidth(110)
        self._s_blanker_mini.valueChanged.connect(self._pipeline.set_blanker_mini)
        layout.addWidget(self._s_blanker_mini)
        layout.addWidget(_note(tr("  ↳ Detecta frituras y crackles cortos. Bajo=elimina más, puede recortar consonantes.")))
        return group

    def _build_anf_group(self) -> QGroupBox:
        group = QGroupBox(tr("ANF — Filtro de Muesca Espectral  (parámetros técnicos)"))
        layout = QVBoxLayout(group)

        anf_row = QHBoxLayout()
        anf_row.addWidget(QLabel(tr("Actividad:")))
        self._lbl_anf_activity = QLabel("—")
        self._lbl_anf_activity.setStyleSheet("color: #888;")
        anf_row.addWidget(self._lbl_anf_activity)
        anf_row.addStretch()
        layout.addLayout(anf_row)

        self._s_anf_threshold = SliderRow(
            tr("Sensibilidad:"),
            min_val=1.5, max_val=10.0,
            default=_DSP_DEF.anf_threshold,
            step=0.1, unit="x", fmt="{:.1f}",
        )
        self._s_anf_threshold._update_label = lambda v: self._s_anf_threshold._val_lbl.setText(
            f"{v:.1f}×  ({tr('alta') if v < 2.5 else tr('media') if v < 5.0 else tr('baja')})"
        )
        self._s_anf_threshold._val_lbl.setFixedWidth(90)
        self._s_anf_threshold.valueChanged.connect(self._pipeline.set_anf_threshold)
        layout.addWidget(self._s_anf_threshold)
        layout.addWidget(_note(tr("  ↳ Ratio bin/baseline para detectar un tono. Bajar si hay tonos débiles.")))

        self._s_anf_depth = SliderRow(
            tr("Profundidad:"),
            min_val=0.0, max_val=1.0,
            default=_DSP_DEF.anf_depth,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_anf_depth._update_label = lambda v: self._s_anf_depth._val_lbl.setText(
            f"{v*100:.0f}%"
        )
        self._s_anf_depth.valueChanged.connect(self._pipeline.set_anf_depth)
        layout.addWidget(self._s_anf_depth)
        layout.addWidget(_note(tr("  ↳ Atenuación aplicada al tono detectado. 100%=silencia, 50%=reduce 6dB.")))
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
            self._lbl_anf_activity.setText(f"🔇 {bins} {tr('tono') if bins == 1 else tr('tonos')}")
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
        self.refresh_enabled_states()


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
        self.refresh_enabled_states()

    def refresh_enabled_states(self) -> None:
        """Habilita/deshabilita controles según el estado de los módulos en Módulos Activos.
        Los sub-módulos requieren además el cancelador activo (no corren sin él)."""
        dsp   = self._config.dsp
        noise = dsp.noise_enabled
        for s in (self._s_noise_floor, self._s_noise_smooth, self._s_noise_attack):
            s.set_enabled(noise)
        for s in (self._s_fading_change, self._s_fading_freeze):
            s.set_enabled(noise and dsp.noise_fading_comp)
        for s in (self._s_squelch_threshold, self._s_squelch_hold):
            s.set_enabled(noise and dsp.squelch_enabled)
        for s in (self._s_pf_boost, self._s_pf_center,
                  self._s_pf_rolloff_hz, self._s_pf_rolloff_depth):
            s.set_enabled(noise and dsp.perceptual_floor_enabled)
        self._s_post_filter.set_enabled(noise and dsp.post_filter_enabled)
        self._s_pitch_strength.set_enabled(noise and dsp.pitch_enhance_enabled)
        self._s_leveler_max.set_enabled(noise and dsp.voice_leveler_enabled)

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_canceller_group())
        layout.addWidget(self._build_squelch_group())
        layout.addWidget(self._build_perceptual_floor_group())
        layout.addWidget(self._build_post_filter_group())
        layout.addWidget(self._build_pitch_group())
        layout.addWidget(self._build_leveler_group())
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
        group = QGroupBox(tr("Cancelador de Ruido  (Wiener Log-MMSE)"))
        layout = QVBoxLayout(group)

        noise_row = QHBoxLayout()
        noise_row.addWidget(QLabel(tr("Reducción:")))
        self._lbl_noise_db = QLabel("—")
        self._lbl_noise_db.setStyleSheet("color: #888;")
        noise_row.addWidget(self._lbl_noise_db)
        noise_row.addSpacing(16)
        noise_row.addWidget(QLabel(tr("Voz:")))
        self._lbl_noise_vp = QLabel("—")
        self._lbl_noise_vp.setStyleSheet("color: #888;")
        noise_row.addWidget(self._lbl_noise_vp)
        noise_row.addStretch()
        layout.addLayout(noise_row)

        self._s_noise_floor = SliderRow(
            tr("Piso espectral:"),
            min_val=0.05, max_val=0.3,
            default=_DSP_DEF.noise_floor,
            step=0.01, unit="", fmt="{:.2f}",
        )
        self._s_noise_floor.valueChanged.connect(self._on_noise_floor)
        layout.addWidget(self._s_noise_floor)
        layout.addWidget(_note(tr("  ↳ Ganancia mínima por bin. 0.10=suprime 20dB (recomendado). Mínimo 0.05.")))

        self._s_noise_smooth = SliderRow(
            tr("Anti-gorgojeo (β):"),
            min_val=0.90, max_val=0.99,
            default=_DSP_DEF.noise_smooth,
            step=0.001, unit="", fmt="{:.3f}",
        )
        self._s_noise_smooth._update_label = lambda v: self._s_noise_smooth._val_lbl.setText(
            f"{v*100:.1f}%  ({tr('reactivo') if v < 0.95 else tr('normal') if v < 0.98 else tr('suave') if v < 0.985 else tr('máximo')})"
        )
        self._s_noise_smooth._val_lbl.setFixedWidth(110)
        self._s_noise_smooth.valueChanged.connect(self._pipeline.set_noise_smooth)
        layout.addWidget(self._s_noise_smooth)
        layout.addWidget(_note(tr("  ↳ Release (retorno al ruido), pasos de 0.1% para calibrar fino. 99%≈1s de release — puede dejar cola de ruido tras la voz.")))

        self._s_noise_attack = SliderRow(
            tr("Velocidad ataque:"),
            min_val=0.50, max_val=0.92,
            default=_DSP_DEF.noise_attack,
            step=0.02, unit="", fmt="{:.2f}",
        )
        self._s_noise_attack._update_label = lambda v: self._s_noise_attack._val_lbl.setText(
            f"{v*100:.0f}%  ({tr('rápido') if v < 0.68 else tr('normal') if v < 0.84 else tr('suave')})"
        )
        self._s_noise_attack._val_lbl.setFixedWidth(110)
        self._s_noise_attack.valueChanged.connect(self._on_noise_attack)
        layout.addWidget(self._s_noise_attack)
        layout.addWidget(_note(tr("  ↳ Attack (onset de voz): bajo=consonantes nítidas. Alto=transiciones suaves.")))

        fading_row = QHBoxLayout()
        fading_row.addWidget(QLabel(tr("Compensación fading HF:")))
        self._lbl_fading = QLabel("—")
        self._lbl_fading.setStyleSheet("color: #888;")
        fading_row.addWidget(self._lbl_fading)
        fading_row.addStretch()
        layout.addLayout(fading_row)
        layout.addWidget(_note(tr("  ↳ Activar en Módulos Activos (sub-módulo del cancelador). Solo modo Adaptativo.")))

        self._s_fading_change = SliderRow(
            tr("Sensibilidad fading:"),
            min_val=2.0, max_val=10.0,
            default=_DSP_DEF.noise_fading_change_db,
            step=0.5, unit="dB", fmt="{:.1f}",
        )
        self._s_fading_change._update_label = lambda v: self._s_fading_change._val_lbl.setText(
            f"{v:.1f} dB  ({tr('sensible') if v < 4 else tr('normal') if v < 7 else tr('selectivo')})"
        )
        self._s_fading_change._val_lbl.setFixedWidth(110)
        self._s_fading_change.valueChanged.connect(self._pipeline.set_fading_change_db)
        layout.addWidget(self._s_fading_change)
        layout.addWidget(_note(tr("  ↳ Cambio de energía que dispara el freeze. Bajo=detecta QSB suave, puede disparar con la voz. Alto=solo fades profundos.")))

        self._s_fading_freeze = SliderRow(
            tr("Duración del freeze:"),
            min_val=100.0, max_val=500.0,
            default=_DSP_DEF.noise_fading_freeze_ms,
            step=25.0, unit="ms", fmt="{:.0f}",
        )
        self._s_fading_freeze._update_label = lambda v: self._s_fading_freeze._val_lbl.setText(
            f"{v:.0f} ms  ({tr('corto') if v < 175 else tr('normal') if v < 325 else tr('largo')})"
        )
        self._s_fading_freeze._val_lbl.setFixedWidth(110)
        self._s_fading_freeze.valueChanged.connect(self._pipeline.set_fading_freeze_ms)
        layout.addWidget(self._s_fading_freeze)
        layout.addWidget(_note(tr("  ↳ Tiempo que MCRA queda congelado tras cada evento. Fades lentos necesitan más; muy largo desactualiza el piso.")))
        return group

    def _build_squelch_group(self) -> QGroupBox:
        group = QGroupBox(tr("Squelch de voz  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        sq_row = QHBoxLayout()
        sq_row.addWidget(QLabel(tr("Nivel de voz:")))
        self._lbl_sq_vp = QLabel("—")
        self._lbl_sq_vp.setStyleSheet("color: #888;")
        sq_row.addWidget(self._lbl_sq_vp)
        sq_row.addSpacing(20)
        sq_row.addWidget(QLabel(tr("Gate:")))
        self._lbl_sq_gate = QLabel("—")
        self._lbl_sq_gate.setStyleSheet("color: #888;")
        sq_row.addWidget(self._lbl_sq_gate)
        sq_row.addStretch()
        layout.addLayout(sq_row)
        layout.addWidget(_note(
            tr("  ↳ Ajustar Umbral (%) para que quede entre el nivel en silencio y con voz.")
        ))

        self._s_squelch_threshold = SliderRow(
            tr("Umbral:"),
            min_val=0.05, max_val=1.00,
            default=_DSP_DEF.squelch_threshold,
            step=0.05, unit="", fmt="{:.0f}",
        )
        self._s_squelch_threshold._update_label = lambda v: self._s_squelch_threshold._val_lbl.setText(
            f"{v*100:.0f}%  ({tr('sensible') if v < 0.15 else tr('normal') if v < 0.35 else tr('selectivo') if v < 0.75 else tr('máximo')})"
        )
        self._s_squelch_threshold._val_lbl.setFixedWidth(110)
        self._s_squelch_threshold.valueChanged.connect(self._on_squelch_threshold)
        layout.addWidget(self._s_squelch_threshold)
        layout.addWidget(_note(tr("  ↳ El ruido marca ~0% (el detector exige estructura de voz): 10–25% suele bastar. Subirlo solo si una interferencia tonal abre el gate.")))

        self._s_squelch_hold = SliderRow(
            tr("Retención:"),
            min_val=0.0, max_val=1000.0,
            default=_DSP_DEF.squelch_hold_ms,
            step=50.0, unit="ms", fmt="{:.0f}",
        )
        self._s_squelch_hold.valueChanged.connect(self._on_squelch_hold)
        layout.addWidget(self._s_squelch_hold)
        layout.addWidget(_note(tr("  ↳ Tiempo que el gate permanece abierto tras perder la voz. Default 300 ms.")))
        return group

    def _build_perceptual_floor_group(self) -> QGroupBox:
        group = QGroupBox(tr("Piso espectral perceptual  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        pf_row = QHBoxLayout()
        pf_row.addWidget(QLabel(tr("Piso vocal:")))
        self._lbl_pf_peak = QLabel("—")
        self._lbl_pf_peak.setStyleSheet("color: #888;")
        pf_row.addWidget(self._lbl_pf_peak)
        pf_row.addSpacing(20)
        pf_row.addWidget(QLabel(tr("Activo:")))
        self._lbl_pf_active = QLabel("—")
        self._lbl_pf_active.setStyleSheet("color: #888;")
        pf_row.addWidget(self._lbl_pf_active)
        pf_row.addStretch()
        layout.addLayout(pf_row)
        layout.addWidget(_note(
            tr("  ↳ 'Piso vocal': piso en la zona de mayor boost. 'Activo': % bins retenidos ahora.")
        ))

        self._s_pf_boost = SliderRow(
            tr("Amplitud boost vocal:"),
            min_val=0.0, max_val=2.5,
            default=_DSP_DEF.perceptual_floor_boost,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pf_boost._update_label = lambda v: self._s_pf_boost._val_lbl.setText(
            f"+{v*100:.0f}%  ({tr('sin boost') if v < 0.05 else tr('suave') if v < 0.5 else tr('normal') if v < 1.2 else tr('fuerte')})"
        )
        self._s_pf_boost._val_lbl.setFixedWidth(110)
        self._s_pf_boost.valueChanged.connect(self._on_pf_boost)
        layout.addWidget(self._s_pf_boost)
        layout.addWidget(_note(tr("  ↳ Cuánto se eleva el piso en la zona vocal. 75%=suave, 150%=normal, 250%=máximo.")))

        self._s_pf_center = SliderRow(
            tr("Centro del boost:"),
            min_val=200.0, max_val=1200.0,
            default=_DSP_DEF.perceptual_floor_center,
            step=25.0, unit="Hz", fmt="{:.0f}",
        )
        self._s_pf_center._update_label = lambda v: self._s_pf_center._val_lbl.setText(
            f"{v:.0f} Hz  ({tr('grave') if v < 350 else tr('vocal') if v < 700 else tr('medio')})"
        )
        self._s_pf_center._val_lbl.setFixedWidth(110)
        self._s_pf_center.valueChanged.connect(self._on_pf_center)
        layout.addWidget(self._s_pf_center)
        layout.addWidget(_note(tr("  ↳ Frecuencia de máximo boost. 500 Hz=AM/SSB típico. 350 Hz=SSB muy grave.")))

        self._s_pf_rolloff_hz = SliderRow(
            tr("Inicio del rolloff:"),
            min_val=1000.0, max_val=6000.0,
            default=_DSP_DEF.perceptual_floor_rolloff_hz,
            step=100.0, unit="Hz", fmt="{:.0f}",
        )
        self._s_pf_rolloff_hz._update_label = lambda v: self._s_pf_rolloff_hz._val_lbl.setText(
            f"{v:.0f} Hz  ({tr('pronto') if v < 2000 else tr('normal') if v < 4000 else tr('tarde')})"
        )
        self._s_pf_rolloff_hz._val_lbl.setFixedWidth(110)
        self._s_pf_rolloff_hz.valueChanged.connect(self._on_pf_rolloff_hz)
        layout.addWidget(self._s_pf_rolloff_hz)
        layout.addWidget(_note(tr("  ↳ A partir de qué frecuencia baja el piso. 3000 Hz=default.")))

        self._s_pf_rolloff_depth = SliderRow(
            tr("Profundidad del rolloff:"),
            min_val=0.0, max_val=0.70,
            default=_DSP_DEF.perceptual_floor_rolloff_depth,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pf_rolloff_depth._update_label = lambda v: self._s_pf_rolloff_depth._val_lbl.setText(
            f"-{v*100:.0f}%  ({tr('sin rolloff') if v < 0.05 else tr('suave') if v < 0.3 else tr('normal') if v < 0.55 else tr('fuerte')})"
        )
        self._s_pf_rolloff_depth._val_lbl.setFixedWidth(110)
        self._s_pf_rolloff_depth.valueChanged.connect(self._on_pf_rolloff_depth)
        layout.addWidget(self._s_pf_rolloff_depth)
        layout.addWidget(_note(tr("  ↳ Cuánto cae el piso en altas frecuencias. 55%=default.")))
        return group

    def _build_post_filter_group(self) -> QGroupBox:
        group = QGroupBox(tr("Post-filtro espectral  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        pf_row = QHBoxLayout()
        pf_row.addWidget(QLabel(tr("Reducción extra:")))
        self._lbl_pf_extra = QLabel("—")
        self._lbl_pf_extra.setStyleSheet("color: #888;")
        pf_row.addWidget(self._lbl_pf_extra)
        pf_row.addStretch()
        layout.addLayout(pf_row)
        layout.addWidget(_note(tr("  ↳ dB extra eliminados en bins de ruido vs cancelador base. 0 dB = sin efecto.")))

        self._s_post_filter = SliderRow(
            tr("Agresividad:"),
            min_val=0.0, max_val=10.0,
            default=_DSP_DEF.post_filter_strength,
            step=0.1, unit="", fmt="{:.1f}",
        )
        self._s_post_filter._update_label = lambda v: self._s_post_filter._val_lbl.setText(
            f"{v:.1f}  ({tr('desactivado') if v == 0 else tr('suave') if v < 0.8 else tr('normal') if v < 2.0 else tr('agresivo') if v < 3.5 else tr('muy agresivo') if v < 6.5 else tr('máximo')})"
        )
        self._s_post_filter._val_lbl.setFixedWidth(130)
        self._s_post_filter.valueChanged.connect(self._on_post_filter_strength)
        layout.addWidget(self._s_post_filter)
        layout.addWidget(_note(tr("  ↳ Supresión extra en bins de ruido para eliminar 'pitidos fantasma'. 1=moderado, 2=normal, 4+=muy agresivo (vigilar que la voz no se recorte).")))
        return group

    def _build_pitch_group(self) -> QGroupBox:
        group = QGroupBox(tr("Refuerzo de pitch SSB  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        f0_row = QHBoxLayout()
        f0_row.addWidget(QLabel(tr("Pitch detectado:")))
        self._lbl_pitch_f0 = QLabel("—")
        self._lbl_pitch_f0.setStyleSheet("color: #888;")
        f0_row.addWidget(self._lbl_pitch_f0)
        f0_row.addStretch()
        layout.addLayout(f0_row)
        layout.addWidget(_note(tr("  ↳ f0 de la voz en tiempo real. Con voz SSB clara debería marcar 80–400 Hz estable.")))

        self._s_pitch_strength = SliderRow(
            tr("Protección de armónicos:"),
            min_val=0.0, max_val=1.0,
            default=_DSP_DEF.pitch_enhance_strength,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pitch_strength._update_label = lambda v: self._s_pitch_strength._val_lbl.setText(
            f"{v*100:.0f}%  ({tr('suave') if v < 0.4 else tr('normal') if v < 0.75 else tr('fuerte')})"
        )
        self._s_pitch_strength._val_lbl.setFixedWidth(110)
        self._s_pitch_strength.valueChanged.connect(self._on_pitch_strength)
        layout.addWidget(self._s_pitch_strength)
        layout.addWidget(_note(tr("  ↳ Cuánto eleva la probabilidad de voz en bins de armónicos. 70%=recomendado.")))
        return group

    def _build_leveler_group(self) -> QGroupBox:
        group = QGroupBox(tr("Nivelador de voz  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        self._s_leveler_max = SliderRow(
            tr("Ganancia máxima:"),
            min_val=0.0, max_val=20.0,
            default=_DSP_DEF.voice_leveler_max_db,
            step=1.0, unit="dB", fmt="{:.0f}",
        )
        self._s_leveler_max._update_label = lambda v: self._s_leveler_max._val_lbl.setText(
            f"+{v:.0f} dB  ({tr('suave') if v < 7 else tr('normal') if v < 14 else tr('fuerte')})"
        )
        self._s_leveler_max._val_lbl.setFixedWidth(110)
        self._s_leveler_max.valueChanged.connect(self._pipeline.set_voice_leveler_max_db)
        layout.addWidget(self._s_leveler_max)
        layout.addWidget(_note(tr("  ↳ Tope de compensación para voz débil. Alto=iguala más las señales, pero levanta también el ruido que acompaña a la voz débil.")))
        return group

    # ------------------------------------------------------------------
    # Stats en tiempo real
    # ------------------------------------------------------------------

    def _update_stats(self) -> None:
        vp = self._pipeline.noise_voice_prob
        thr = self._config.dsp.squelch_threshold

        # Indicador squelch: usa voice_prob_sq (rápido), igual que el gate real
        sq_on = self._config.dsp.squelch_enabled and self._config.dsp.noise_enabled
        if sq_on:
            vp_sq = self._pipeline.noise_voice_prob_sq
            self._lbl_sq_vp.setText(f"{vp_sq*100:.0f}%")
            if vp_sq > thr:
                color_sq = "#4fc3f7"   # azul — por encima del umbral → gate abre
            elif vp_sq > thr * 0.5:
                color_sq = "#fff176"   # amarillo — zona marginal
            else:
                color_sq = "#888"      # gris — ruido claro
            self._lbl_sq_vp.setStyleSheet(f"color: {color_sq}; font-weight: bold;")

            gate_open = self._pipeline.squelch_gate_open
            self._lbl_sq_gate.setText(tr("ABIERTO") if gate_open else tr("CERRADO"))
            self._lbl_sq_gate.setStyleSheet(
                "color: #69f0ae; font-weight: bold;" if gate_open
                else "color: #888; font-weight: bold;"
            )
        else:
            self._lbl_sq_vp.setText(tr("—  (desactivado)"))
            self._lbl_sq_vp.setStyleSheet("color: #888;")
            self._lbl_sq_gate.setText("—")
            self._lbl_sq_gate.setStyleSheet("color: #888;")

        if not self._pipeline.noise_has_profile:
            self._lbl_noise_db.setText(tr("sin perfil"))
            self._lbl_noise_db.setStyleSheet("color: #888;")
            self._lbl_noise_vp.setText("—")
            self._lbl_noise_vp.setStyleSheet("color: #888;")
        else:
            db = self._pipeline.noise_reduction_db
            self._lbl_noise_db.setText(f"{db:.1f} dB")
            color_db = "#69f0ae" if db < -10 else "#fff176" if db < -3 else "#888"
            self._lbl_noise_db.setStyleSheet(f"color: {color_db}; font-weight: bold;")

            self._lbl_noise_vp.setText(f"{vp*100:.0f}%")
            color_vp = "#4fc3f7" if vp > 0.5 else "#fff176" if vp > 0.15 else "#888"
            self._lbl_noise_vp.setStyleSheet(f"color: {color_vp}; font-weight: bold;")

        # Fading compensation indicator
        if self._config.dsp.noise_fading_comp and self._pipeline.is_running():
            if self._pipeline.fading_active:
                self._lbl_fading.setText(tr("FADE"))
                self._lbl_fading.setStyleSheet("color: #ffb74d; font-weight: bold;")
            else:
                self._lbl_fading.setText(tr("ok"))
                self._lbl_fading.setStyleSheet("color: #888;")
        else:
            self._lbl_fading.setText("—")
            self._lbl_fading.setStyleSheet("color: #888;")

        # Post-filtro espectral
        post_enabled = self._config.dsp.post_filter_enabled
        if post_enabled:
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

        # Piso espectral perceptual
        pf_enabled = self._config.dsp.perceptual_floor_enabled
        if pf_enabled:
            peak = self._pipeline.pf_peak_pct
            base = max(self._config.dsp.noise_floor, 0.001)
            boost_db = 20.0 * math.log10(peak / base)
            self._lbl_pf_peak.setText(f"{peak*100:.0f}%  ({boost_db:+.1f} dB)")
            color_peak = "#a5d6a7" if boost_db > 2 else "#fff176" if boost_db > 0 else "#888"
            self._lbl_pf_peak.setStyleSheet(f"color: {color_peak}; font-weight: bold;")

            active = self._pipeline.pf_active_frac
            self._lbl_pf_active.setText(f"{active*100:.0f}% bins")
            color_act = "#69f0ae" if active > 0.25 else "#fff176" if active > 0.05 else "#888"
            self._lbl_pf_active.setStyleSheet(f"color: {color_act}; font-weight: bold;")
        else:
            self._lbl_pf_peak.setText(tr("—  (desactivado)"))
            self._lbl_pf_peak.setStyleSheet("color: #888;")
            self._lbl_pf_active.setText("—")
            self._lbl_pf_active.setStyleSheet("color: #888;")

        # Refuerzo de pitch SSB
        if self._config.dsp.pitch_enhance_enabled:
            f0 = self._pipeline.pitch_f0
            if f0 is not None:
                self._lbl_pitch_f0.setText(f"{f0:.0f} Hz")
                self._lbl_pitch_f0.setStyleSheet("color: #69f0ae; font-weight: bold;")
            else:
                self._lbl_pitch_f0.setText(tr("sin detección"))
                self._lbl_pitch_f0.setStyleSheet("color: #888;")
        else:
            self._lbl_pitch_f0.setText(tr("—  (desactivado)"))
            self._lbl_pitch_f0.setStyleSheet("color: #888;")

    # ------------------------------------------------------------------
    # Carga y reset
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        cfg = self._config.dsp
        self._s_noise_floor.set_value(cfg.noise_floor)
        self._s_noise_smooth.set_value(cfg.noise_smooth)
        self._s_noise_attack.set_value(cfg.noise_attack)
        self._s_fading_change.set_value(cfg.noise_fading_change_db)
        self._s_fading_freeze.set_value(cfg.noise_fading_freeze_ms)
        self._s_squelch_threshold.set_value(cfg.squelch_threshold)
        self._s_squelch_hold.set_value(cfg.squelch_hold_ms)
        self._s_pf_boost.set_value(cfg.perceptual_floor_boost)
        self._s_pf_center.set_value(cfg.perceptual_floor_center)
        self._s_pf_rolloff_hz.set_value(cfg.perceptual_floor_rolloff_hz)
        self._s_pf_rolloff_depth.set_value(cfg.perceptual_floor_rolloff_depth)
        self._s_post_filter.set_value(cfg.post_filter_strength)
        self._s_pitch_strength.set_value(cfg.pitch_enhance_strength)
        self._s_leveler_max.set_value(cfg.voice_leveler_max_db)

    def _reset_defaults(self) -> None:
        defaults = DSPConfig()
        self._config.dsp.noise_floor       = defaults.noise_floor
        self._config.dsp.noise_smooth      = defaults.noise_smooth
        self._config.dsp.noise_attack      = defaults.noise_attack
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
        self._pipeline.set_fading_change_db(defaults.noise_fading_change_db)
        self._pipeline.set_fading_freeze_ms(defaults.noise_fading_freeze_ms)
        self._pipeline.set_squelch_threshold(defaults.squelch_threshold)
        self._pipeline.set_squelch_hold_ms(defaults.squelch_hold_ms)
        self._pipeline.set_pf_boost(defaults.perceptual_floor_boost)
        self._pipeline.set_pf_center(defaults.perceptual_floor_center)
        self._pipeline.set_pf_rolloff_hz(defaults.perceptual_floor_rolloff_hz)
        self._pipeline.set_pf_rolloff_depth(defaults.perceptual_floor_rolloff_depth)
        self._pipeline.set_post_filter_strength(defaults.post_filter_strength)
        self._pipeline.set_pitch_enhance_strength(defaults.pitch_enhance_strength)
        self._pipeline.set_voice_leveler_max_db(defaults.voice_leveler_max_db)
        self._load_values()

    def reload(self) -> None:
        self._load_values()
        self.refresh_enabled_states()

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
