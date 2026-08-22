import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLabel,
    QScrollArea, QPushButton, QHBoxLayout, QFrame, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from config import AppConfig, RadioMode, AudioConfig, DSPConfig
from pipeline import ProcessingPipeline
from ui.slider_row import SliderRow
from ui.tooltips import apply_tooltips
from i18n import tr

_BLOCK_SIZES    = [240, 480, 960, 1920]
_FILTER_ORDERS  = [2, 4, 6, 8]


def _wire_change_notifications(widget) -> None:
    """Conecta todos los SliderRow y checkboxes del widget a widget.changed,
    para que MainWindow marque el preset como '(modificado)' y agende el guardado
    cuando se toca un control de una pestaña Avanzada (esos sliders conectan
    directo al pipeline, sin pasar por _schedule_save)."""
    for sr in widget.findChildren(SliderRow):
        sr.valueChanged.connect(lambda *_: widget.changed.emit())
    for cb in widget.findChildren(QCheckBox):
        cb.toggled.connect(lambda *_: widget.changed.emit())

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
    # Envolver a segundo renglón en vez de forzar el ancho de la columna (una nota
    # larga estiraba la fila y recortaba el final del slider). Con el scroll en
    # setWidgetResizable(True), la nota fluye al ancho del viewport.
    lbl.setWordWrap(True)
    return lbl


# ---------------------------------------------------------------------------
# Pestaña Avanzada Audio
# ---------------------------------------------------------------------------

class AdvancedAudioTab(QWidget):

    changed = Signal()  # un control cambió → MainWindow marca "(modificado)" y guarda

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._build_ui()
        self._load_values()
        self.refresh_enabled_states()
        apply_tooltips(self)
        _wire_change_notifications(self)

    def refresh_enabled_states(self) -> None:
        """Habilita/deshabilita controles según el estado de los módulos en Módulos Activos."""
        dsp = self._config.dsp
        bp = dsp.bandpass_pre_enabled or dsp.bandpass_post_enabled
        # Los límites AM/SSB se habilitan solo para el modo activo (ayuda de UX:
        # se ve de un vistazo cuáles aplican). El orden del filtro es común a ambos.
        is_am  = dsp.mode == RadioMode.AM
        is_ssb = dsp.mode == RadioMode.SSB
        self._s_order.set_enabled(bp)
        for s in (self._s_am_lo, self._s_am_hi):
            s.set_enabled(bp and is_am)
        for s in (self._s_ssb_lo, self._s_ssb_hi):
            s.set_enabled(bp and is_ssb)
        self._chk_bp_out.setEnabled(dsp.bandpass_post_enabled)
        out_on = dsp.bandpass_post_enabled and dsp.bandpass_out_independent
        for s in (self._s_out_am_lo, self._s_out_am_hi):
            s.set_enabled(out_on and is_am)
        for s in (self._s_out_ssb_lo, self._s_out_ssb_hi):
            s.set_enabled(out_on and is_ssb)
        for s in (self._s_presence_freq, self._s_presence, self._s_presence_q,
                  self._s_body_freq, self._s_body):
            s.set_enabled(dsp.presence_enabled)
        for s in (self._s_exciter_drive, self._s_exciter_mix, self._s_exciter_char):
            s.set_enabled(dsp.exciter_enabled)
        self._s_bass.set_enabled(dsp.bass_enabled)
        # El nivelador requiere el cancelador activo (su VAD vive ahí — invariante 2)
        leveler_on = dsp.noise_enabled and dsp.voice_leveler_enabled
        self._s_leveler_max.set_enabled(leveler_on)
        self._s_leveler_release.set_enabled(leveler_on)

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_audio_group())
        layout.addWidget(self._build_leveler_group())
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

    def _build_leveler_group(self) -> QGroupBox:
        group = QGroupBox(tr("Nivelador de voz  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        act_row = QHBoxLayout()
        act_row.addWidget(QLabel(tr("Actividad:")))
        self._lbl_leveler_act = QLabel("—")
        self._lbl_leveler_act.setStyleSheet("color: #888;")
        act_row.addWidget(self._lbl_leveler_act)
        act_row.addStretch()
        layout.addLayout(act_row)

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
        layout.addWidget(_note(tr("  ↳ Tope de compensación para voz débil. Fuerte = iguala más las señales, pero levanta también el ruido que acompaña a la voz débil.")))

        self._s_leveler_release = SliderRow(
            tr("Velocidad de respuesta:"),
            min_val=200.0, max_val=3000.0,
            default=_DSP_DEF.voice_leveler_release_ms,
            step=100.0, unit="ms", fmt="{:.0f}",
        )
        self._s_leveler_release._update_label = lambda v: self._s_leveler_release._val_lbl.setText(
            f"{v:.0f} ms  ({tr('rápido') if v < 700 else tr('normal') if v < 1800 else tr('suave')})"
        )
        self._s_leveler_release._val_lbl.setFixedWidth(120)
        self._s_leveler_release.valueChanged.connect(self._pipeline.set_voice_leveler_release_ms)
        layout.addWidget(self._s_leveler_release)
        layout.addWidget(_note(tr("  ↳ Qué tan rápido sigue el nivelador los cambios de nivel. Rápido = sigue el fading cíclico y rápido; suave = más estable, menos bombeo.")))

        return group

    def _build_dsp_group(self) -> QGroupBox:
        group = QGroupBox(tr("Filtro de paso de banda  (pre y post — en tiempo real)"))
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

        self._chk_bp_out = QCheckBox(tr("Salida independiente de la entrada"))
        self._chk_bp_out.setToolTip(tr(
            "Con la casilla apagada, el filtro de salida usa los mismos límites que\n"
            "el de entrada (comportamiento clásico). Activada, la salida tiene sus\n"
            "propios límites: permite entrada angosta (menos soplido al cancelador)\n"
            "con salida más ancha (la voz no se recorta dos veces en el borde)."
        ))
        self._chk_bp_out.toggled.connect(self._on_bp_out_independent)
        layout.addWidget(self._chk_bp_out)

        self._s_out_am_lo  = _freq_slider(tr("AM salida – Hz inferior:"),  _DSP_DEF.bandpass_out_limits[RadioMode.AM][0])
        self._s_out_am_hi  = _freq_slider(tr("AM salida – Hz superior:"),  _DSP_DEF.bandpass_out_limits[RadioMode.AM][1],  hi=10000)
        self._s_out_ssb_lo = _freq_slider(tr("SSB salida – Hz inferior:"), _DSP_DEF.bandpass_out_limits[RadioMode.SSB][0])
        self._s_out_ssb_hi = _freq_slider(tr("SSB salida – Hz superior:"), _DSP_DEF.bandpass_out_limits[RadioMode.SSB][1], hi=6000)

        self._s_out_am_lo.valueChanged.connect(lambda v: self._on_bp_out(RadioMode.AM,  lo=int(v)))
        self._s_out_am_hi.valueChanged.connect(lambda v: self._on_bp_out(RadioMode.AM,  hi=int(v)))
        self._s_out_ssb_lo.valueChanged.connect(lambda v: self._on_bp_out(RadioMode.SSB, lo=int(v)))
        self._s_out_ssb_hi.valueChanged.connect(lambda v: self._on_bp_out(RadioMode.SSB, hi=int(v)))

        for s in (self._s_out_am_lo, self._s_out_am_hi, self._s_out_ssb_lo, self._s_out_ssb_hi):
            layout.addWidget(s)
        layout.addWidget(_note(tr("  ↳ Consejo: entrada angosta (p. ej. SSB hasta 2700 Hz) + salida más ancha "
                                  "(3500–4000 Hz) conserva el borde superior de la voz y el brillo del excitador.")))
        return group

    def _build_voice_group(self) -> QGroupBox:
        group = QGroupBox(tr("EQ Voz  (presencia + cuerpo)"))
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
            f"Q {v:.1f} ({tr('ancho') if v < 0.6 else tr('medio') if v < 1.2 else tr('angosto')})"
        )
        self._s_presence_q._val_lbl.setFixedWidth(90)
        self._s_presence_q.valueChanged.connect(self._pipeline.set_presence_q)
        layout.addWidget(self._s_presence_q)
        layout.addWidget(_note(tr("  ↳ Q bajo = boost ancho (más cálido), Q alto = pico angosto (más nasal).")))

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
        group = QGroupBox(tr("Excitador armónico  (se aplica en tiempo real)"))
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
        layout.addWidget(_note(tr("  ↳ Saturación tanh: cuántos armónicos se generan y de qué orden. Suave = sutil, agresivo = efecto notable. No cambia el nivel de la banda: solo agrega armónicos nuevos.")))

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
        layout.addWidget(_note(tr("  ↳ Nivel de armónicos mezclados. 20–40% = zona útil sin sonar artificial. Con el cancelador activo solo actúa cuando hay voz, así no le agrega brillo al ruido de fondo.")))

        self._s_exciter_char = SliderRow(
            tr("Carácter:"),
            min_val=0.0, max_val=1.0,
            default=_DSP_DEF.exciter_character,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_exciter_char._update_label = lambda v: self._s_exciter_char._val_lbl.setText(
            f"{v*100:.0f}%  ({tr('impar') if v < 0.25 else tr('mixto') if v < 0.75 else tr('par')})"
        )
        self._s_exciter_char._val_lbl.setFixedWidth(110)
        self._s_exciter_char.valueChanged.connect(self._on_exciter_char)
        layout.addWidget(self._s_exciter_char)
        layout.addWidget(_note(tr("  ↳ Qué armónicos se generan. Impar (tanh pura) = brillante y algo hueco, es el timbre metálico clásico. Par = más cálido y pleno, pero agrega productos de diferencia en los graves: subirlo mucho puede enturbiar. Mixto suele ser el mejor compromiso.")))

        self._s_bass = SliderRow(
            tr("Recuperar graves:"),
            min_val=0.0, max_val=1.0,
            default=_DSP_DEF.bass_amount,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_bass._update_label = lambda v: self._s_bass._val_lbl.setText(f"{v*100:.0f}%")
        self._s_bass.valueChanged.connect(self._on_bass_amount)
        layout.addWidget(self._s_bass)
        layout.addWidget(_note(tr("  ↳ Nivel del fundamental recuperado (100% ≈ el que tendría una voz natural). Se deriva de los armónicos de la propia voz: sin voz no hay de dónde derivarlo y se calla solo. Requiere el módulo «Recuperar graves» activo.")))
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
        self._chk_bp_out.blockSignals(True)
        self._chk_bp_out.setChecked(cfg.bandpass_out_independent)
        self._chk_bp_out.blockSignals(False)
        self._s_out_am_lo.set_value(cfg.bandpass_out_limits[RadioMode.AM][0])
        self._s_out_am_hi.set_value(cfg.bandpass_out_limits[RadioMode.AM][1])
        self._s_out_ssb_lo.set_value(cfg.bandpass_out_limits[RadioMode.SSB][0])
        self._s_out_ssb_hi.set_value(cfg.bandpass_out_limits[RadioMode.SSB][1])
        self._s_order.set_value(
            _FILTER_ORDERS.index(cfg.filter_order)
            if cfg.filter_order in _FILTER_ORDERS else 1
        )
        self._s_block.set_value(
            _BLOCK_SIZES.index(self._config.audio.block_size)
            if self._config.audio.block_size in _BLOCK_SIZES else 1
        )
        self._s_leveler_max.set_value(cfg.voice_leveler_max_db)
        self._s_leveler_release.set_value(cfg.voice_leveler_release_ms)
        self._s_presence_freq.set_value(cfg.presence_freq)
        self._s_presence.set_value(cfg.presence_db)
        self._s_presence_q.set_value(cfg.presence_q)
        self._s_body_freq.set_value(cfg.body_freq)
        self._s_body.set_value(cfg.body_db)
        self._s_pitch.set_value(cfg.pitch_shift_hz)
        self._s_exciter_drive.set_value(cfg.exciter_drive)
        self._s_exciter_mix.set_value(cfg.exciter_mix)
        self._s_exciter_char.set_value(cfg.exciter_character)
        self._s_bass.set_value(cfg.bass_amount)

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
        self._pipeline.set_exciter_character(defaults.exciter_character)
        self._pipeline.set_bass_amount(defaults.bass_amount)
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

    def _on_bp_out_independent(self, checked: bool) -> None:
        self._pipeline.set_bandpass_out_independent(checked)
        self.refresh_enabled_states()

    def _on_bp_out(self, mode: RadioMode, lo: int = None, hi: int = None) -> None:
        cur_lo, cur_hi = self._config.dsp.bandpass_out_limits[mode]
        lo = lo if lo is not None else cur_lo
        hi = hi if hi is not None else cur_hi
        if lo >= hi:
            return
        self._pipeline.set_bandpass_out_limits(mode, lo, hi)

    def _on_block_size(self, idx: float) -> None:
        self._config.audio.block_size = _BLOCK_SIZES[int(idx)]

    def _on_exciter_drive(self, val: float) -> None:
        self._config.dsp.exciter_drive = val
        self._pipeline.set_exciter_drive(val)

    def _on_exciter_mix(self, val: float) -> None:
        self._config.dsp.exciter_mix = val
        self._pipeline.set_exciter_mix(val)

    def _on_exciter_char(self, val: float) -> None:
        self._pipeline.set_exciter_character(val)

    def _on_bass_amount(self, val: float) -> None:
        self._pipeline.set_bass_amount(val)

    def reload(self) -> None:
        self._load_values()
        self.refresh_enabled_states()

    def set_processing_active(self, active: bool) -> None:
        self._s_block.set_enabled(not active)


# ---------------------------------------------------------------------------
# Pestaña Avanzada Impulsos  (Blanker + ANF)
# ---------------------------------------------------------------------------

class AdvancedImpulseTab(QWidget):

    changed = Signal()  # un control cambió → MainWindow marca "(modificado)" y guarda

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._build_ui()
        self._load_values()
        self.refresh_enabled_states()
        apply_tooltips(self)
        _wire_change_notifications(self)

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
        group = QGroupBox(tr("Supresor de impulsos  (se aplica en tiempo real)"))
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
        layout.addWidget(_note(tr("  ↳ Agresivo = captura más impulsos (QRN fuerte). Suave = solo blancos muy grandes.")))

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
        layout.addWidget(_note(tr("  ↳ Detecta frituras y crackles cortos. Agresivo = elimina más, puede recortar consonantes.")))
        return group

    def _build_anf_group(self) -> QGroupBox:
        group = QGroupBox(tr("ANF — Cancela heterodinos y tonos interferentes"))
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
        layout.addWidget(_note(tr("  ↳ Atenuación aplicada al tono detectado. 100%=silencia, 50%=reduce 6dB. Se puede subir sin opacar la voz: el ANF solo actúa sobre tonos sostenidos.")))
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

    changed = Signal()  # un control cambió → MainWindow marca "(modificado)" y guarda

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline, parent=None):
        super().__init__(parent)
        self._config = config
        self._pipeline = pipeline
        self._build_ui()
        self._load_values()
        self.refresh_enabled_states()
        apply_tooltips(self)
        _wire_change_notifications(self)

    def refresh_enabled_states(self) -> None:
        """Habilita/deshabilita controles según el estado de los módulos en Módulos Activos.
        Los sub-módulos requieren además el cancelador activo (no corren sin él)."""
        dsp   = self._config.dsp
        noise = dsp.noise_enabled
        for s in (self._s_noise_floor, self._s_noise_smooth, self._s_noise_attack,
                  self._s_mcra_window, self._s_hf_boost):
            s.set_enabled(noise)
        for s in (self._s_fading_change, self._s_fading_freeze):
            s.set_enabled(noise and dsp.noise_fading_comp)
        for s in (self._s_squelch_threshold, self._s_squelch_hold):
            s.set_enabled(noise and dsp.squelch_enabled)
        for s in (self._s_pf_boost, self._s_pf_center,
                  self._s_pf_rolloff_hz, self._s_pf_rolloff_depth):
            s.set_enabled(noise and dsp.perceptual_floor_enabled)
        self._s_pitch_strength.set_enabled(noise and dsp.pitch_enhance_enabled)

    def _build_ui(self) -> None:
        layout = _make_scroll_layout(self)
        layout.addWidget(self._build_canceller_group())
        layout.addWidget(self._build_squelch_group())
        layout.addWidget(self._build_perceptual_floor_group())
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
        group = QGroupBox(tr("Cancelador de ruido estacionario  (Wiener Log-MMSE)"))
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
        layout.addWidget(_note(tr("  ↳ Estabiliza la clasificación voz/ruido por bin (menos ruido musical de fondo) y el release del cancelador. Subir si se escucha 'gorgojeo'/pitidos de fondo; 99% deja una cola de ruido tras la voz.")))

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
        layout.addWidget(_note(tr("  ↳ Ataque del onset de voz. Rápido = consonantes más nítidas. Suave = transiciones sin artefactos.")))

        self._s_mcra_window = SliderRow(
            tr("Reactividad del piso:"),
            min_val=250.0, max_val=800.0,
            default=_DSP_DEF.noise_mcra_window_ms,
            step=50.0, unit="ms", fmt="{:.0f}",
        )
        self._s_mcra_window._update_label = lambda v: self._s_mcra_window._val_lbl.setText(
            f"{v:.0f} ms  ({tr('reactivo') if v < 400 else tr('normal') if v < 650 else tr('estable')})"
        )
        self._s_mcra_window._val_lbl.setFixedWidth(120)
        self._s_mcra_window.valueChanged.connect(self._pipeline.set_mcra_window_ms)
        layout.addWidget(self._s_mcra_window)
        layout.addWidget(_note(tr("  ↳ Ventana de seguimiento del ruido (solo Adaptativo). Reactivo (corto) = el piso sigue subidas rápidas de ruido cíclico, menos vaivén; estable (largo) = mejor con ruido parejo. Con valores reactivos, tener activo el Refuerzo de pitch de voz.")))

        self._s_hf_boost = SliderRow(
            tr("Refuerzo en agudos:"),
            min_val=0.0, max_val=150.0,
            default=_DSP_DEF.noise_hf_boost * 100.0,
            step=10.0, unit="%", fmt="{:.0f}",
        )
        self._s_hf_boost._update_label = lambda v: self._s_hf_boost._val_lbl.setText(
            f"+{v:.0f}%  ({tr('desactivado') if v < 5 else tr('suave') if v < 60 else tr('normal') if v < 110 else tr('fuerte')})"
        )
        self._s_hf_boost._val_lbl.setFixedWidth(120)
        self._s_hf_boost.valueChanged.connect(lambda v: self._pipeline.set_hf_boost(v / 100.0))
        layout.addWidget(self._s_hf_boost)
        layout.addWidget(_note(tr("  ↳ Sube el piso de ruido por encima de ~2.5 kHz (donde la energía del ruido es baja y el estimador reacciona tarde). Suprime mejor el siseo de agudos que se cuela con el fading, a costa de algo de brillo de la voz — combinar con Excitador/Presencia para reponerlo.")))

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
            min_val=1.0, max_val=10.0,
            default=_DSP_DEF.noise_fading_change_db,
            step=0.5, unit="dB", fmt="{:.1f}",
        )
        self._s_fading_change._update_label = lambda v: self._s_fading_change._val_lbl.setText(
            f"{v:.1f} dB  ({tr('sensible') if v < 4 else tr('normal') if v < 7 else tr('selectivo')})"
        )
        self._s_fading_change._val_lbl.setFixedWidth(110)
        self._s_fading_change.valueChanged.connect(self._pipeline.set_fading_change_db)
        layout.addWidget(self._s_fading_change)
        layout.addWidget(_note(tr("  ↳ Cambio de energía que dispara el freeze. Sensible = detecta QSB suave (puede disparar con la voz). Selectivo = solo fades profundos.")))

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
        layout.addWidget(_note(tr("  ↳ Cuánto se eleva el piso en la zona vocal. 75%=suave, 150%=normal, 250%=fuerte.")))

        self._s_pf_center = SliderRow(
            tr("Centro del boost:"),
            min_val=200.0, max_val=1200.0,
            default=_DSP_DEF.perceptual_floor_center,
            step=25.0, unit="Hz", fmt="{:.0f}",
        )
        self._s_pf_center._update_label = lambda v: self._s_pf_center._val_lbl.setText(
            f"{v:.0f} Hz  ({tr('grave') if v < 350 else tr('vocal') if v < 700 else tr('medios')})"
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
            min_val=0.0, max_val=0.95,
            default=_DSP_DEF.perceptual_floor_rolloff_depth,
            step=0.05, unit="", fmt="{:.2f}",
        )
        self._s_pf_rolloff_depth._update_label = lambda v: self._s_pf_rolloff_depth._val_lbl.setText(
            f"-{v*100:.0f}%  ({tr('sin rolloff') if v < 0.05 else tr('suave') if v < 0.3 else tr('normal') if v < 0.55 else tr('fuerte') if v < 0.78 else tr('muy fuerte')})"
        )
        self._s_pf_rolloff_depth._val_lbl.setFixedWidth(110)
        self._s_pf_rolloff_depth.valueChanged.connect(self._on_pf_rolloff_depth)
        layout.addWidget(self._s_pf_rolloff_depth)
        layout.addWidget(_note(tr("  ↳ Cuánto baja el piso arriba del 'Inicio' → más supresión del siseo agudo. 55% ≈ −7 dB. En banda angosta (SSB), bajá el 'Inicio' para oírlo.")))
        return group


    def _build_pitch_group(self) -> QGroupBox:
        group = QGroupBox(tr("Refuerzo de pitch de voz  (activar en Módulos Activos)"))
        layout = QVBoxLayout(group)

        f0_row = QHBoxLayout()
        f0_row.addWidget(QLabel(tr("Pitch detectado:")))
        self._lbl_pitch_f0 = QLabel("—")
        self._lbl_pitch_f0.setStyleSheet("color: #888;")
        f0_row.addWidget(self._lbl_pitch_f0)
        f0_row.addStretch()
        layout.addLayout(f0_row)
        layout.addWidget(_note(tr("  ↳ f0 de la voz en tiempo real. Con voz clara debería marcar 80–400 Hz estable.")))

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

        if not self._config.dsp.noise_enabled:
            # Cancelador desactivado: reduction_db/voice_prob quedan congelados
            # en el profiler — mostrar el estado real, no el último valor medido
            self._lbl_noise_db.setText(tr("—  (desactivado)"))
            self._lbl_noise_db.setStyleSheet("color: #888;")
            self._lbl_noise_vp.setText("—")
            self._lbl_noise_vp.setStyleSheet("color: #888;")
        elif not self._pipeline.noise_has_profile:
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

        # Fading compensation indicator — pop con latch: enciende FADE si hubo freeze
        # desde el último poll (el freeze de ~200ms se perdía entre polls de 500ms).
        if self._config.dsp.noise_fading_comp and self._pipeline.is_running():
            if self._pipeline.pop_fading_active():
                self._lbl_fading.setText(tr("FADE"))
                self._lbl_fading.setStyleSheet("color: #ffb74d; font-weight: bold;")
            else:
                self._lbl_fading.setText(tr("ok"))
                self._lbl_fading.setStyleSheet("color: #888;")
        else:
            self._lbl_fading.setText("—")
            self._lbl_fading.setStyleSheet("color: #888;")

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

        # Refuerzo de pitch de voz
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
        self._s_mcra_window.set_value(cfg.noise_mcra_window_ms)
        self._s_hf_boost.set_value(cfg.noise_hf_boost * 100.0)
        self._s_fading_change.set_value(cfg.noise_fading_change_db)
        self._s_fading_freeze.set_value(cfg.noise_fading_freeze_ms)
        self._s_squelch_threshold.set_value(cfg.squelch_threshold)
        self._s_squelch_hold.set_value(cfg.squelch_hold_ms)
        self._s_pf_boost.set_value(cfg.perceptual_floor_boost)
        self._s_pf_center.set_value(cfg.perceptual_floor_center)
        self._s_pf_rolloff_hz.set_value(cfg.perceptual_floor_rolloff_hz)
        self._s_pf_rolloff_depth.set_value(cfg.perceptual_floor_rolloff_depth)
        self._s_pitch_strength.set_value(cfg.pitch_enhance_strength)

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

    def _on_pitch_strength(self, val: float) -> None:
        self._config.dsp.pitch_enhance_strength = val
        self._pipeline.set_pitch_enhance_strength(val)
