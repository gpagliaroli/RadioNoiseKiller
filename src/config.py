import json
from dataclasses import dataclass, field
from enum import Enum


class RadioMode(Enum):
    AM = "AM"
    SSB = "SSB"


@dataclass
class AudioConfig:
    sample_rate: int = 48000
    block_size: int = 480       # hop_size del modelo; 480 = 10ms @ 48kHz
    channels: int = 1           # (legado — el stream calcula los canales por dispositivo)
    dtype: str = "float32"
    input_device: int | None = None
    output_device: int | None = None
    input_channel: str = "left"  # "left" | "right" | "mix" — canal tomado de entradas estéreo
    record_raw_input: bool = False  # grabar también la entrada sin procesar (2do WAV)


@dataclass
class DSPConfig:
    mode: RadioMode = RadioMode.SSB
    agc_preset: str = "off"
    blanker_enabled:  bool  = True
    bandpass_pre_enabled:  bool = True
    bandpass_post_enabled: bool = True
    anf_enabled:      bool  = True
    noise_enabled:    bool  = True
    presence_enabled: bool  = True
    anf_threshold:   float = 3.0   # ratio bin/baseline para detectar un tono (1.5=sensible, 6=selectivo)
    anf_depth:       float = 0.5   # profundidad de atenuación del tono detectado (0=nada, 1=máximo; 50% = buen balance, valores altos opacan la voz)
    blanker_frame:   float = 15.0  # umbral frame 10ms (× piso de ruido). 5=agresivo, 50=suave, 100=muy suave
    blanker_mini:    float = 8.0   # umbral mini-frame 0.67ms (× piso de ruido). 3=agresivo, 15=suave
    noise_mode:   str   = "static"  # "static" = perfil manual | "mcra" = adaptativo continuo
    noise_alpha:  float = 0.7   # reducción Wiener en bins de ruido puro (0=off, 0.7=70%, 1.0=máximo)
    noise_floor:  float = 0.1   # ganancia mínima por bin (≥0.05 para evitar gorgojeo con floor bajo)
    noise_smooth:    float = 0.97   # beta_release DD asimétrico (0.94-0.98=sin gorgojeo, bajo=reactivo)
    noise_attack:    float = 0.80   # beta_fast DD asimétrico: bajo=ataque rápido en bins de voz (0.50-0.92)
    squelch_enabled:   bool  = False
    squelch_threshold: float = 0.15  # voice_prob mínimo para gain=1.0 (0.10=sensible, 0.40=selectivo)
    squelch_hold_ms:   float = 500.0 # ms que el gate permanece abierto tras perder la voz
    exciter_enabled:   bool  = False
    exciter_drive:     float = 2.0   # saturación tanh (1.0=suave, 10.0=fuerte)
    exciter_mix:       float = 0.3   # nivel de armónicos mezclados al original (0.0–1.0)
    presence_freq:   float = 2000.0 # Hz, centro del pico de presencia (1000-2000)
    presence_db:     float = 0.0    # dB, ganancia del pico de presencia
    presence_q:      float = 0.7    # Q del pico de presencia
    body_freq:       float = 350.0  # Hz, centro del pico de cuerpo de voz (150-800)
    body_db:         float = 0.0    # dB, ganancia del pico de cuerpo (0 = passthrough)
    pitch_shift_hz:  float = 0.0    # Hz, corrección de tono SSB (-500 a +500)
    perceptual_floor_enabled:       bool  = False  # piso espectral variable por curva de enmascaramiento auditivo
    perceptual_floor_boost:         float = 0.75   # amplitud del boost vocal (0–1.5)
    perceptual_floor_center:        float = 500.0  # Hz, centro del pico de boost
    perceptual_floor_rolloff_hz:    float = 3000.0 # Hz, inicio del rolloff de alta frecuencia
    perceptual_floor_rolloff_depth: float = 0.55   # profundidad máxima del rolloff (0–0.7)
    post_filter_enabled:    bool  = False  # post-filtro espectral contra ruido musical residual
    post_filter_strength:   float = 1.0   # agresividad del post-filtro (0=off, 1=moderado, 6=máximo)
    pitch_enhance_enabled:  bool  = False  # refuerzo de armónicos SSB via autocorrelación
    pitch_enhance_strength: float = 0.7    # qué tanto elevar p_speech en bins de armónicos (0-1)
    noise_fading_comp:      bool  = False  # compensación de fading HF: freeze MCRA + release rápido
    noise_fading_change_db: float = 5.0    # umbral de detección de fade (1-10 dB)
    noise_fading_freeze_ms: float = 200.0  # duración del freeze MCRA tras el evento (100-500 ms)
    voice_leveler_enabled:  bool  = False  # AGC de voz post-cancelador gateado por VAD
    voice_leveler_max_db:   float = 12.0   # ganancia máxima del nivelador (0-20 dB)
    voice_leveler_gate_voice: bool = True  # True: adapta solo con voz (VAD). False: continuo (música)
    bandpass_limits: dict = field(default_factory=lambda: {
        RadioMode.AM:  (300, 5000),
        RadioMode.SSB: (200, 3000),
    })
    bandpass_out_independent: bool = False  # False = la salida sigue a la entrada (legado)
    bandpass_out_limits: dict = field(default_factory=lambda: {
        RadioMode.AM:  (300, 5000),
        RadioMode.SSB: (200, 3000),
    })
    filter_order: int = 4



@dataclass
class GainConfig:
    input_gain_db: float = 0.0
    output_gain_db: float = 0.0
    peak_limit_db: float = -1.0


@dataclass
class WindowConfig:
    x: int | None = None
    y: int | None = None
    w: int | None = None   # ancho elegido por el usuario (None = default 960)
    spectrum_db_max:      int = 0
    spectrum_max_freq_hz: int = 12000
    spectrum_show_waterfall: bool = True        # cascada visible bajo el espectro
    waterfall_source:        str  = "input"     # "input" | "output"


@dataclass
class AppConfig:
    audio:  AudioConfig  = field(default_factory=AudioConfig)
    dsp:    DSPConfig    = field(default_factory=DSPConfig)
    gain:   GainConfig   = field(default_factory=GainConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    last_preset: str = ""   # nombre del último preset cargado/guardado (solo informativo)
    last_noise_profile: str = ""  # último perfil de ruido cargado/guardado (auto-recarga)
    language: str = "es"    # idioma de la UI ("es"/"en"); aplicar requiere reinicio

    def save(self, path: str) -> None:
        data = {
            "last_preset": self.last_preset,
            "last_noise_profile": self.last_noise_profile,
            "language": self.language,
            "audio": {
                "block_size": self.audio.block_size,
                "input_device": self.audio.input_device,
                "output_device": self.audio.output_device,
                "input_channel": self.audio.input_channel,
                "record_raw_input": self.audio.record_raw_input,
            },
            "dsp": {
                "mode": self.dsp.mode.value,
                "agc_preset": self.dsp.agc_preset,
                "blanker_enabled":  self.dsp.blanker_enabled,
                "bandpass_pre_enabled":  self.dsp.bandpass_pre_enabled,
                "bandpass_post_enabled": self.dsp.bandpass_post_enabled,
                "anf_enabled":      self.dsp.anf_enabled,
                "noise_enabled":    self.dsp.noise_enabled,
                "presence_enabled": self.dsp.presence_enabled,
                "anf_threshold": self.dsp.anf_threshold,
                "anf_depth":     self.dsp.anf_depth,
                "blanker_frame": self.dsp.blanker_frame,
                "blanker_mini":  self.dsp.blanker_mini,
                "noise_mode":    self.dsp.noise_mode,
                "noise_alpha":    self.dsp.noise_alpha,
                "noise_floor":   self.dsp.noise_floor,
                "noise_smooth":  self.dsp.noise_smooth,
                "noise_attack":  self.dsp.noise_attack,
                "squelch_enabled":   self.dsp.squelch_enabled,
                "squelch_threshold": self.dsp.squelch_threshold,
                "squelch_hold_ms":   self.dsp.squelch_hold_ms,
                "exciter_enabled":   self.dsp.exciter_enabled,
                "exciter_drive":     self.dsp.exciter_drive,
                "exciter_mix":       self.dsp.exciter_mix,
                "presence_freq":  self.dsp.presence_freq,
                "body_freq":      self.dsp.body_freq,
                "body_db":        self.dsp.body_db,
                "presence_db":    self.dsp.presence_db,
                "presence_q":     self.dsp.presence_q,
                "pitch_shift_hz": self.dsp.pitch_shift_hz,
                "perceptual_floor_enabled":        self.dsp.perceptual_floor_enabled,
                "perceptual_floor_boost":          self.dsp.perceptual_floor_boost,
                "perceptual_floor_center":         self.dsp.perceptual_floor_center,
                "perceptual_floor_rolloff_hz":     self.dsp.perceptual_floor_rolloff_hz,
                "perceptual_floor_rolloff_depth":  self.dsp.perceptual_floor_rolloff_depth,
                "post_filter_enabled":    self.dsp.post_filter_enabled,
                "post_filter_strength":   self.dsp.post_filter_strength,
                "pitch_enhance_enabled":  self.dsp.pitch_enhance_enabled,
                "pitch_enhance_strength": self.dsp.pitch_enhance_strength,
                "noise_fading_comp":      self.dsp.noise_fading_comp,
                "noise_fading_change_db": self.dsp.noise_fading_change_db,
                "noise_fading_freeze_ms": self.dsp.noise_fading_freeze_ms,
                "voice_leveler_enabled":  self.dsp.voice_leveler_enabled,
                "voice_leveler_max_db":   self.dsp.voice_leveler_max_db,
                "voice_leveler_gate_voice": self.dsp.voice_leveler_gate_voice,
                "filter_order": self.dsp.filter_order,
                "bandpass_limits": {
                    m.value: list(v)
                    for m, v in self.dsp.bandpass_limits.items()
                },
                "bandpass_out_independent": self.dsp.bandpass_out_independent,
                "bandpass_out_limits": {
                    m.value: list(v)
                    for m, v in self.dsp.bandpass_out_limits.items()
                },
            },
            "gain": {
                "input_gain_db": self.gain.input_gain_db,
                "output_gain_db": self.gain.output_gain_db,
                "peak_limit_db": self.gain.peak_limit_db,
            },
            "window": {
                "x": self.window.x,
                "y": self.window.y,
                "w": self.window.w,
                "spectrum_db_max":      self.window.spectrum_db_max,
                "spectrum_max_freq_hz": self.window.spectrum_max_freq_hz,
                "spectrum_show_waterfall": self.window.spectrum_show_waterfall,
                "waterfall_source":        self.window.waterfall_source,
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        self.last_preset = str(data.get("last_preset", ""))
        self.last_noise_profile = str(data.get("last_noise_profile", ""))
        _lang = data.get("language", self.language)
        self.language = _lang if _lang in ("es", "en") else "es"

        a = data.get("audio", {})
        self.audio.block_size = a.get("block_size", self.audio.block_size)
        self.audio.input_device = a.get("input_device", self.audio.input_device)
        self.audio.output_device = a.get("output_device", self.audio.output_device)
        _ic = a.get("input_channel", self.audio.input_channel)
        self.audio.input_channel = _ic if _ic in ("left", "right", "mix") else "left"
        self.audio.record_raw_input = bool(a.get("record_raw_input",
                                                 self.audio.record_raw_input))

        d = data.get("dsp", {})
        try:
            raw_mode = d.get("mode", self.dsp.mode.value)
            if raw_mode in ("SSB-USB", "SSB-LSB"):
                raw_mode = "SSB"
            self.dsp.mode = RadioMode(raw_mode)
        except ValueError:
            pass
        self.dsp.agc_preset       = d.get("agc_preset",       self.dsp.agc_preset)
        if self.dsp.agc_preset == "custom":   # AGC Custom eliminado → preset válido
            self.dsp.agc_preset = "medium"
        self.dsp.blanker_enabled  = bool(d.get("blanker_enabled",  self.dsp.blanker_enabled))
        # migración: settings viejos con "bandpass_enabled" aplican a ambos
        _bp_legacy = d.get("bandpass_enabled", None)
        self.dsp.bandpass_pre_enabled  = bool(d.get("bandpass_pre_enabled",  _bp_legacy if _bp_legacy is not None else self.dsp.bandpass_pre_enabled))
        self.dsp.bandpass_post_enabled = bool(d.get("bandpass_post_enabled", _bp_legacy if _bp_legacy is not None else self.dsp.bandpass_post_enabled))
        self.dsp.anf_enabled      = bool(d.get("anf_enabled",      self.dsp.anf_enabled))
        self.dsp.noise_enabled    = bool(d.get("noise_enabled",    self.dsp.noise_enabled))
        self.dsp.presence_enabled = bool(d.get("presence_enabled", self.dsp.presence_enabled))
        self.dsp.anf_threshold = float(d.get("anf_threshold", self.dsp.anf_threshold))
        self.dsp.anf_depth     = float(d.get("anf_depth",     self.dsp.anf_depth))
        self.dsp.blanker_frame = float(d.get("blanker_frame", self.dsp.blanker_frame))
        self.dsp.blanker_mini  = float(d.get("blanker_mini",  self.dsp.blanker_mini))
        _nm = d.get("noise_mode", self.dsp.noise_mode)
        self.dsp.noise_mode = _nm if _nm in ("static", "mcra") else "static"
        self.dsp.noise_alpha    = d.get("noise_alpha",    self.dsp.noise_alpha)
        self.dsp.noise_floor    = max(0.05, float(d.get("noise_floor", self.dsp.noise_floor)))
        self.dsp.noise_smooth   = d.get("noise_smooth",  self.dsp.noise_smooth)
        self.dsp.noise_attack      = d.get("noise_attack",      self.dsp.noise_attack)
        self.dsp.squelch_enabled   = bool(d.get("squelch_enabled",   self.dsp.squelch_enabled))
        self.dsp.squelch_threshold = float(d.get("squelch_threshold", self.dsp.squelch_threshold))
        self.dsp.squelch_hold_ms   = float(d.get("squelch_hold_ms",   self.dsp.squelch_hold_ms))
        self.dsp.exciter_enabled   = bool(d.get("exciter_enabled",   self.dsp.exciter_enabled))
        self.dsp.exciter_drive     = float(d.get("exciter_drive",    self.dsp.exciter_drive))
        self.dsp.exciter_mix       = float(d.get("exciter_mix",      self.dsp.exciter_mix))
        self.dsp.presence_freq  = d.get("presence_freq",  self.dsp.presence_freq)
        self.dsp.presence_db    = d.get("presence_db",    self.dsp.presence_db)
        self.dsp.presence_q     = d.get("presence_q",     self.dsp.presence_q)
        self.dsp.body_freq      = float(d.get("body_freq", self.dsp.body_freq))
        self.dsp.body_db        = float(d.get("body_db",   self.dsp.body_db))
        self.dsp.pitch_shift_hz = d.get("pitch_shift_hz", self.dsp.pitch_shift_hz)
        self.dsp.perceptual_floor_enabled       = bool(d.get("perceptual_floor_enabled",       self.dsp.perceptual_floor_enabled))
        self.dsp.perceptual_floor_boost         = float(d.get("perceptual_floor_boost",         self.dsp.perceptual_floor_boost))
        self.dsp.perceptual_floor_center        = float(d.get("perceptual_floor_center",        self.dsp.perceptual_floor_center))
        self.dsp.perceptual_floor_rolloff_hz    = float(d.get("perceptual_floor_rolloff_hz",    self.dsp.perceptual_floor_rolloff_hz))
        self.dsp.perceptual_floor_rolloff_depth = float(d.get("perceptual_floor_rolloff_depth", self.dsp.perceptual_floor_rolloff_depth))
        self.dsp.post_filter_enabled    = bool(d.get("post_filter_enabled",    self.dsp.post_filter_enabled))
        self.dsp.post_filter_strength   = float(d.get("post_filter_strength",   self.dsp.post_filter_strength))
        self.dsp.pitch_enhance_enabled  = bool(d.get("pitch_enhance_enabled",  self.dsp.pitch_enhance_enabled))
        self.dsp.pitch_enhance_strength = float(d.get("pitch_enhance_strength", self.dsp.pitch_enhance_strength))
        self.dsp.noise_fading_comp      = bool(d.get("noise_fading_comp",      self.dsp.noise_fading_comp))
        self.dsp.noise_fading_change_db = float(d.get("noise_fading_change_db", self.dsp.noise_fading_change_db))
        self.dsp.noise_fading_freeze_ms = float(d.get("noise_fading_freeze_ms", self.dsp.noise_fading_freeze_ms))
        self.dsp.voice_leveler_enabled  = bool(d.get("voice_leveler_enabled",  self.dsp.voice_leveler_enabled))
        self.dsp.voice_leveler_max_db   = float(d.get("voice_leveler_max_db",  self.dsp.voice_leveler_max_db))
        self.dsp.voice_leveler_gate_voice = bool(d.get("voice_leveler_gate_voice", self.dsp.voice_leveler_gate_voice))
        self.dsp.filter_order = d.get("filter_order", self.dsp.filter_order)
        for mode_str, limits in d.get("bandpass_limits", {}).items():
            if mode_str in ("SSB-USB", "SSB-LSB"):
                mode_str = "SSB"
            try:
                self.dsp.bandpass_limits[RadioMode(mode_str)] = tuple(limits)
            except ValueError:
                pass
        self.dsp.bandpass_out_independent = bool(d.get("bandpass_out_independent",
                                                       self.dsp.bandpass_out_independent))
        for mode_str, limits in d.get("bandpass_out_limits", {}).items():
            try:
                self.dsp.bandpass_out_limits[RadioMode(mode_str)] = tuple(limits)
            except ValueError:
                pass

        g = data.get("gain", {})
        self.gain.input_gain_db = g.get("input_gain_db", self.gain.input_gain_db)
        self.gain.output_gain_db = g.get("output_gain_db", self.gain.output_gain_db)
        self.gain.peak_limit_db = g.get("peak_limit_db", self.gain.peak_limit_db)

        w = data.get("window", {})
        if w.get("x") is not None:
            self.window.x = int(w["x"])
        if w.get("y") is not None:
            self.window.y = int(w["y"])
        if w.get("w") is not None:
            self.window.w = int(w["w"])
        self.window.spectrum_db_max      = int(w.get("spectrum_db_max",      self.window.spectrum_db_max))
        self.window.spectrum_max_freq_hz = int(w.get("spectrum_max_freq_hz", self.window.spectrum_max_freq_hz))
        self.window.spectrum_show_waterfall = bool(w.get("spectrum_show_waterfall", self.window.spectrum_show_waterfall))
        _wf_src = str(w.get("waterfall_source", self.window.waterfall_source))
        self.window.waterfall_source = _wf_src if _wf_src in ("input", "output") else "input"
