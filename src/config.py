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
    channels: int = 1
    dtype: str = "float32"
    input_device: int | None = None
    output_device: int | None = None


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
    anf_depth:       float = 0.9   # profundidad de atenuación del tono detectado (0=nada, 1=máximo)
    blanker_frame:   float = 15.0  # umbral frame 10ms (× piso de ruido). 5=agresivo, 50=suave, 100=muy suave
    blanker_mini:    float = 8.0   # umbral mini-frame 0.67ms (× piso de ruido). 3=agresivo, 15=suave
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
    pitch_shift_hz:  float = 0.0    # Hz, corrección de tono SSB (-500 a +500)
    bandpass_limits: dict = field(default_factory=lambda: {
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


@dataclass
class AppConfig:
    audio:  AudioConfig  = field(default_factory=AudioConfig)
    dsp:    DSPConfig    = field(default_factory=DSPConfig)
    gain:   GainConfig   = field(default_factory=GainConfig)
    window: WindowConfig = field(default_factory=WindowConfig)

    def save(self, path: str) -> None:
        data = {
            "audio": {
                "block_size": self.audio.block_size,
                "input_device": self.audio.input_device,
                "output_device": self.audio.output_device,
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
                "presence_db":    self.dsp.presence_db,
                "presence_q":     self.dsp.presence_q,
                "pitch_shift_hz": self.dsp.pitch_shift_hz,
                "filter_order": self.dsp.filter_order,
                "bandpass_limits": {
                    m.value: list(v)
                    for m, v in self.dsp.bandpass_limits.items()
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

        a = data.get("audio", {})
        self.audio.block_size = a.get("block_size", self.audio.block_size)
        self.audio.input_device = a.get("input_device", self.audio.input_device)
        self.audio.output_device = a.get("output_device", self.audio.output_device)

        d = data.get("dsp", {})
        try:
            raw_mode = d.get("mode", self.dsp.mode.value)
            if raw_mode in ("SSB-USB", "SSB-LSB"):
                raw_mode = "SSB"
            self.dsp.mode = RadioMode(raw_mode)
        except ValueError:
            pass
        self.dsp.agc_preset       = d.get("agc_preset",       self.dsp.agc_preset)
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
        self.dsp.pitch_shift_hz = d.get("pitch_shift_hz", self.dsp.pitch_shift_hz)
        self.dsp.filter_order = d.get("filter_order", self.dsp.filter_order)
        for mode_str, limits in d.get("bandpass_limits", {}).items():
            if mode_str in ("SSB-USB", "SSB-LSB"):
                mode_str = "SSB"
            try:
                self.dsp.bandpass_limits[RadioMode(mode_str)] = tuple(limits)
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
