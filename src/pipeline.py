import threading
import queue
from collections import deque
import numpy as np
from config import AppConfig, RadioMode
from audio.stream import AudioStream
from audio.devices import AudioDevice
from audio.recorder import WavRecorder
from dsp.agc import AGC
from dsp.anf import AdaptiveNotchFilter
from dsp.exciter import AuralExciter
from dsp.filters import BandpassFilter, PresenceFilter
from dsp.freq_shift import FrequencyShifter
from dsp.gain import GainLimiter
from dsp.level import LevelMeter
from dsp.noise_profiler import NoiseProfiler


class ProcessingPipeline:
    """
    Orquesta el flujo DSP en tiempo real:
    AudioStream callback → blanker → AGC → BandpassFilter
                        → ANF → NoiseProfiler
                        → BandpassFilter out → Presencia → FrequencyShifter
                        → GainLimiter → salida

    El DSP corre en un thread separado para no bloquear el callback de audio.
    _in_queue:  callback  →  processor thread  (chunks de block_size muestras)
    _out_queue: processor thread  →  callback  (chunks procesados)
    """

    _LEARN_DUCK_GAIN: float = 0.25   # monitoreo a -12 dB durante "Aprender ruido"
    _LEVELER_VP_THR:  float = 0.30   # voice_prob mínimo para que el nivelador adapte

    def __init__(self, config: AppConfig):
        self._config = config
        self._lock   = threading.Lock()
        self._running = False
        self._bypass  = False
        self._input_gain: float = 10 ** (config.gain.input_gain_db / 20.0)

        self._blanker_frame: float = config.dsp.blanker_frame
        self._blanker_mini:  float = config.dsp.blanker_mini
        self._blanker_hits:  int   = 0

        self._blanker_enabled:       bool = config.dsp.blanker_enabled
        self._bandpass_pre_enabled:  bool = config.dsp.bandpass_pre_enabled
        self._bandpass_post_enabled: bool = config.dsp.bandpass_post_enabled
        self._noise_enabled:         bool = config.dsp.noise_enabled
        self._presence_enabled:      bool = config.dsp.presence_enabled

        self._agc = AGC(config.audio.sample_rate, config.audio.block_size)
        self._agc.set_preset(config.dsp.agc_preset)
        # Nivelador de voz: AGC post-cancelador gateado por el VAD. Compensa la
        # atenuación de voz del Wiener a SNR bajo sin re-amplificar el ruido
        # residual (con ruido/silencio la ganancia queda congelada via set_hold).
        self._agc_voice = AGC(config.audio.sample_rate, config.audio.block_size)
        self._agc_voice.set_custom_target(-20.0)
        self._agc_voice.set_custom_max_gain(config.dsp.voice_leveler_max_db)
        self._agc_voice.set_custom_attack(80.0)     # lento — nivelar, no comprimir
        self._agc_voice.set_custom_release(1500.0)
        self._agc_voice.set_preset("custom")
        self._voice_leveler_enabled: bool = config.dsp.voice_leveler_enabled
        self._bandpass     = BandpassFilter(config.dsp, config.audio.sample_rate)
        self._bandpass_out = BandpassFilter(config.dsp, config.audio.sample_rate)
        if config.dsp.bandpass_out_independent:
            for _m, (_lo, _hi) in config.dsp.bandpass_out_limits.items():
                self._bandpass_out.set_limits(_m, int(_lo), int(_hi))
        self._anf = AdaptiveNotchFilter(
            sample_rate=config.audio.sample_rate,
            threshold=config.dsp.anf_threshold,
            depth=config.dsp.anf_depth,
        )
        self._anf.set_enabled(config.dsp.anf_enabled)
        self._noise_profiler = NoiseProfiler(config.audio.block_size)
        self._noise_profiler.set_smooth(config.dsp.noise_smooth)
        self._noise_profiler.set_attack(config.dsp.noise_attack)
        self._noise_profiler.set_perceptual_floor_enabled(config.dsp.perceptual_floor_enabled)
        self._noise_profiler.set_pf_boost(config.dsp.perceptual_floor_boost)
        self._noise_profiler.set_pf_center(config.dsp.perceptual_floor_center)
        self._noise_profiler.set_pf_rolloff_hz(config.dsp.perceptual_floor_rolloff_hz)
        self._noise_profiler.set_pf_rolloff_depth(config.dsp.perceptual_floor_rolloff_depth)
        self._noise_profiler.set_post_filter_enabled(config.dsp.post_filter_enabled)
        self._noise_profiler.set_post_filter_strength(config.dsp.post_filter_strength)
        self._noise_profiler.set_pitch_enabled(config.dsp.pitch_enhance_enabled)
        self._noise_profiler.set_pitch_strength(config.dsp.pitch_enhance_strength)
        self._noise_profiler.set_fading_comp(config.dsp.noise_fading_comp)
        self._noise_profiler.set_fading_change_db(config.dsp.noise_fading_change_db)
        self._noise_profiler.set_fading_freeze_ms(config.dsp.noise_fading_freeze_ms)
        self._noise_profiler.set_mode(config.dsp.noise_mode)
        self._noise_profiler.set_alpha(config.dsp.noise_alpha)
        self._noise_profiler.set_floor(config.dsp.noise_floor)
        self._squelch_enabled:   bool  = config.dsp.squelch_enabled
        self._squelch_threshold: float = config.dsp.squelch_threshold
        self._squelch_hold_ms:   float = config.dsp.squelch_hold_ms
        self._squelch_hold_frames: int = 0   # se calcula en start()
        self._squelch_hold_count:  int = 0
        self._sq_gain_prev:        float = 1.0   # ganancia del gate en el frame anterior (rampa)
        self._learn_gain_prev:     float = 1.0   # ganancia del duck de aprendizaje (rampa)
        self._exciter = AuralExciter(config.audio.sample_rate)
        self._exciter.set_drive(config.dsp.exciter_drive)
        self._exciter.set_mix(config.dsp.exciter_mix)
        self._exciter.set_enabled(config.dsp.exciter_enabled)
        self._presence = PresenceFilter(config.audio.sample_rate)
        self._presence.set_freq(config.dsp.presence_freq)
        self._presence.set_gain_db(config.dsp.presence_db)
        self._presence.set_q(config.dsp.presence_q)
        # Segunda banda paramétrica: cuerpo de la voz (150-800 Hz), Q fijo ancho
        self._body = PresenceFilter(config.audio.sample_rate, freq_hz=350.0, q=0.9)
        self._body.set_freq(config.dsp.body_freq)
        self._body.set_gain_db(config.dsp.body_db)
        self._freq_shifter = FrequencyShifter(config.audio.sample_rate)
        self._freq_shifter.set_shift_hz(config.dsp.pitch_shift_hz)
        self._limiter = GainLimiter(
            gain_db=config.gain.output_gain_db,
            limit_db=config.gain.peak_limit_db,
        )
        self._level_in  = LevelMeter(sample_rate=config.audio.sample_rate)
        self._level_out = LevelMeter(sample_rate=config.audio.sample_rate)
        self._recorder  = WavRecorder(config.audio.sample_rate)
        self._stream: AudioStream | None = None

        self._db_in:      float = -60.0
        self._db_out:     float = -60.0
        self._latency_ms: float = 0.0

        self._on_level_update = None
        self._on_error        = None

        self._in_acc:  np.ndarray = np.zeros(0, dtype=np.float32)
        self._out_acc: np.ndarray = np.zeros(0, dtype=np.float32)

        self._in_queue:    queue.Queue = queue.Queue(maxsize=30)
        self._out_queue:   queue.Queue = queue.Queue(maxsize=60)
        self._proc_thread: threading.Thread | None = None

        # Buffers para el visualizador de espectro (leídos desde el hilo UI)
        self._spec_pre_frames:  deque = deque(maxlen=8)
        self._spec_post_frames: deque = deque(maxlen=8)

    # ------------------------------------------------------------------
    # API pública — configuración general
    # ------------------------------------------------------------------

    def set_level_callback(self, cb) -> None:
        self._on_level_update = cb

    def set_error_callback(self, cb) -> None:
        self._on_error = cb

    def set_mode(self, mode: RadioMode) -> None:
        with self._lock:
            self._config.dsp.mode = mode
            self._bandpass.set_mode(mode)
            self._bandpass_out.set_mode(mode)

    def set_agc_preset(self, preset: str) -> None:
        self._config.dsp.agc_preset = preset
        self._agc.set_preset(preset)

    def set_voice_leveler_enabled(self, enabled: bool) -> None:
        self._config.dsp.voice_leveler_enabled = bool(enabled)
        self._voice_leveler_enabled = bool(enabled)

    def set_voice_leveler_max_db(self, db: float) -> None:
        # clamp == rango del slider (el clamp interno del AGC es 0-60, más ancho)
        db = float(np.clip(db, 0.0, 20.0))
        self._config.dsp.voice_leveler_max_db = db
        self._agc_voice.set_custom_max_gain(db)

    @property
    def voice_leveler_gain_db(self) -> float:
        return self._agc_voice.gain_db

    @property
    def snr_db(self) -> float:
        """S/N banda completa (dB, suavizado ~1s) estimado por el cancelador."""
        return self._noise_profiler.snr_db

    def set_presence_db(self, db: float) -> None:
        self._config.dsp.presence_db = float(db)
        self._presence.set_gain_db(db)

    def set_presence_q(self, q: float) -> None:
        self._config.dsp.presence_q = float(q)
        self._presence.set_q(q)

    def set_presence_freq(self, hz: float) -> None:
        self._config.dsp.presence_freq = float(hz)
        self._presence.set_freq(hz)

    def set_body_freq(self, hz: float) -> None:
        self._config.dsp.body_freq = float(hz)
        with self._lock:
            self._body.set_freq(hz)

    def set_body_db(self, db: float) -> None:
        self._config.dsp.body_db = float(db)
        with self._lock:
            self._body.set_gain_db(db)

    def set_pitch_shift(self, hz: float) -> None:
        self._config.dsp.pitch_shift_hz = float(hz)
        self._freq_shifter.set_shift_hz(hz)

    @property
    def agc_gain_db(self) -> float:
        return self._agc.gain_db

    def set_bypass(self, bypass: bool) -> None:
        with self._lock:
            self._bypass = bypass

    def set_input_device(self, device: AudioDevice | None) -> None:
        self._config.audio.input_device = device.index if device else None

    def set_output_device(self, device: AudioDevice | None) -> None:
        self._config.audio.output_device = device.index if device else None

    def set_input_channel(self, mode: str) -> None:
        """Canal tomado de entradas estéreo: "left"/"right"/"mix". Aplica en
        vivo — el callback del stream lee config.audio.input_channel por bloque."""
        if mode in ("left", "right", "mix"):
            self._config.audio.input_channel = mode

    # ------------------------------------------------------------------
    # API pública — ajustes live (pestaña Avanzada)
    # ------------------------------------------------------------------

    def set_input_gain_db(self, db: float) -> None:
        self._config.gain.input_gain_db = db
        self._input_gain = 10 ** (db / 20.0)

    def set_output_gain_db(self, db: float) -> None:
        self._config.gain.output_gain_db = db
        with self._lock:
            self._limiter.set_gain_db(db)

    def set_peak_limit_db(self, db: float) -> None:
        self._config.gain.peak_limit_db = db
        with self._lock:
            self._limiter._limit = 10 ** (db / 20.0)

    def set_bandpass_limits(self, mode: RadioMode, lo: int, hi: int) -> None:
        self._config.dsp.bandpass_limits[mode] = (lo, hi)
        with self._lock:
            self._bandpass.set_limits(mode, lo, hi)
            if not self._config.dsp.bandpass_out_independent:
                self._bandpass_out.set_limits(mode, lo, hi)

    def set_bandpass_out_independent(self, v: bool) -> None:
        """Salida independiente de la entrada. Al cambiar, re-empuja al filtro
        de salida los límites de la fuente que corresponde (ambos modos)."""
        self._config.dsp.bandpass_out_independent = bool(v)
        src = (self._config.dsp.bandpass_out_limits if v
               else self._config.dsp.bandpass_limits)
        with self._lock:
            for m, (lo, hi) in src.items():
                self._bandpass_out.set_limits(m, int(lo), int(hi))

    def set_bandpass_out_limits(self, mode: RadioMode, lo: int, hi: int) -> None:
        self._config.dsp.bandpass_out_limits[mode] = (lo, hi)
        if self._config.dsp.bandpass_out_independent:
            with self._lock:
                self._bandpass_out.set_limits(mode, lo, hi)

    def set_filter_order(self, order: int) -> None:
        self._config.dsp.filter_order = order
        with self._lock:
            self._bandpass.set_order(order)
            self._bandpass_out.set_order(order)

    # ------------------------------------------------------------------
    # API pública — carga de preset completo en caliente
    # ------------------------------------------------------------------

    def apply_config(self, config: AppConfig) -> None:
        """Aplica todos los parametros DSP+Gain en caliente.
        Thread-safe: delega en los mismos setters publicos que usan los sliders."""
        dsp  = config.dsp
        gain = config.gain

        self.set_mode(dsp.mode)
        self.set_agc_preset(dsp.agc_preset)

        self.set_blanker_enabled(dsp.blanker_enabled)
        self.set_blanker_frame(dsp.blanker_frame)
        self.set_blanker_mini(dsp.blanker_mini)

        self.set_bandpass_pre_enabled(dsp.bandpass_pre_enabled)
        self.set_bandpass_post_enabled(dsp.bandpass_post_enabled)
        for mode, (lo, hi) in dsp.bandpass_limits.items():
            self.set_bandpass_limits(mode, int(lo), int(hi))
        for mode, (lo, hi) in dsp.bandpass_out_limits.items():
            self.set_bandpass_out_limits(mode, int(lo), int(hi))
        # último: re-empuja los límites de la fuente correcta al filtro de salida
        self.set_bandpass_out_independent(dsp.bandpass_out_independent)
        self.set_filter_order(dsp.filter_order)

        self.set_anf_enabled(dsp.anf_enabled)
        self.set_anf_threshold(dsp.anf_threshold)
        self.set_anf_depth(dsp.anf_depth)

        self.set_noise_enabled(dsp.noise_enabled)
        self.set_noise_mode(dsp.noise_mode)
        self.set_noise_alpha(dsp.noise_alpha)
        self.set_noise_floor(dsp.noise_floor)
        self.set_noise_smooth(dsp.noise_smooth)
        self.set_noise_attack(dsp.noise_attack)

        self.set_squelch_enabled(dsp.squelch_enabled)
        self.set_squelch_threshold(dsp.squelch_threshold)
        self.set_squelch_hold_ms(dsp.squelch_hold_ms)

        self.set_exciter_enabled(dsp.exciter_enabled)
        self.set_exciter_drive(dsp.exciter_drive)
        self.set_exciter_mix(dsp.exciter_mix)

        self.set_presence_enabled(dsp.presence_enabled)
        self.set_presence_freq(dsp.presence_freq)
        self.set_presence_db(dsp.presence_db)
        self.set_presence_q(dsp.presence_q)
        self.set_body_freq(dsp.body_freq)
        self.set_body_db(dsp.body_db)

        self.set_pitch_shift(dsp.pitch_shift_hz)

        self.set_perceptual_floor_enabled(dsp.perceptual_floor_enabled)
        self.set_pf_boost(dsp.perceptual_floor_boost)
        self.set_pf_center(dsp.perceptual_floor_center)
        self.set_pf_rolloff_hz(dsp.perceptual_floor_rolloff_hz)
        self.set_pf_rolloff_depth(dsp.perceptual_floor_rolloff_depth)

        self.set_post_filter_enabled(dsp.post_filter_enabled)
        self.set_post_filter_strength(dsp.post_filter_strength)

        self.set_pitch_enhance_enabled(dsp.pitch_enhance_enabled)
        self.set_pitch_enhance_strength(dsp.pitch_enhance_strength)
        self.set_fading_comp(dsp.noise_fading_comp)
        self.set_fading_change_db(dsp.noise_fading_change_db)
        self.set_fading_freeze_ms(dsp.noise_fading_freeze_ms)
        self.set_voice_leveler_enabled(dsp.voice_leveler_enabled)
        self.set_voice_leveler_max_db(dsp.voice_leveler_max_db)

        self.set_input_gain_db(gain.input_gain_db)
        self.set_output_gain_db(gain.output_gain_db)
        self.set_peak_limit_db(gain.peak_limit_db)

    # ------------------------------------------------------------------
    # API pública — grabación a WAV
    # ------------------------------------------------------------------

    def start_recording(self, directory: "str | None" = None) -> str:
        """Empieza a grabar la salida procesada (y la entrada cruda si
        config.audio.record_raw_input). Devuelve la ruta base de los archivos.
        Requiere el procesamiento activo (sin audio fluyendo no hay qué grabar)."""
        import datetime
        import os
        from utils import recordings_dir
        base_dir = directory if directory else recordings_dir()
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base = os.path.join(base_dir, f"RNK_{stamp}")
        # Dos grabaciones en el mismo segundo no deben pisarse
        n = 2
        while os.path.exists(base + "_procesado.wav"):
            base = os.path.join(base_dir, f"RNK_{stamp}_{n}")
            n += 1
        raw_path = (base + "_entrada.wav"
                    if self._config.audio.record_raw_input else None)
        self._recorder.start(base + "_procesado.wav", raw_path)
        return base

    def stop_recording(self) -> float:
        """Detiene la grabación. Devuelve los segundos grabados."""
        return self._recorder.stop()

    @property
    def is_recording(self) -> bool:
        return self._recorder.recording

    @property
    def recording_seconds(self) -> float:
        return self._recorder.seconds

    @property
    def recording_error(self) -> "str | None":
        return self._recorder.error

    # ------------------------------------------------------------------
    # API pública — cancelación de ruido estacionario
    # ------------------------------------------------------------------

    def start_noise_learning(self) -> None:
        self._noise_profiler.start_learning()

    def stop_noise_learning(self) -> int:
        return self._noise_profiler.stop_learning()

    def clear_noise_profile(self) -> None:
        self._noise_profiler.clear_profile()

    def get_noise_profile_data(self) -> "dict | None":
        """Perfil estático actual serializable (para NoiseProfileManager)."""
        return self._noise_profiler.get_profile()

    def set_noise_profile_data(self, data: dict) -> None:
        """Aplica un perfil guardado (interpola si cambió el block size) y
        pasa el cancelador a modo estático — un perfil con nombre solo tiene
        sentido ahí."""
        self.set_noise_mode("static")
        self._noise_profiler.set_profile(data)

    def set_noise_alpha(self, alpha: float) -> None:
        self._config.dsp.noise_alpha = float(alpha)
        self._noise_profiler.set_alpha(alpha)

    def set_noise_floor(self, floor: float) -> None:
        clamped = max(0.05, float(floor))
        self._config.dsp.noise_floor = clamped
        self._noise_profiler.set_floor(clamped)

    def set_noise_smooth(self, smooth: float) -> None:
        self._config.dsp.noise_smooth = smooth
        self._noise_profiler.set_smooth(smooth)

    def set_noise_attack(self, attack: float) -> None:
        self._config.dsp.noise_attack = attack
        self._noise_profiler.set_attack(attack)

    def set_squelch_enabled(self, enabled: bool) -> None:
        self._config.dsp.squelch_enabled = enabled
        self._squelch_enabled = enabled

    def set_squelch_threshold(self, threshold: float) -> None:
        self._config.dsp.squelch_threshold = threshold
        self._squelch_threshold = threshold

    def set_squelch_hold_ms(self, ms: float) -> None:
        self._config.dsp.squelch_hold_ms = ms
        self._squelch_hold_ms = ms
        hop_ms = self._config.audio.block_size / self._config.audio.sample_rate * 1000.0
        self._squelch_hold_frames = max(0, round(ms / hop_ms))

    def set_noise_mode(self, mode: str) -> None:
        self._config.dsp.noise_mode = mode
        self._noise_profiler.set_mode(mode)

    def set_perceptual_floor_enabled(self, v: bool) -> None:
        self._config.dsp.perceptual_floor_enabled = bool(v)
        self._noise_profiler.set_perceptual_floor_enabled(bool(v))

    def set_pf_boost(self, v: float) -> None:
        self._config.dsp.perceptual_floor_boost = float(v)
        self._noise_profiler.set_pf_boost(float(v))

    def set_pf_center(self, v: float) -> None:
        self._config.dsp.perceptual_floor_center = float(v)
        self._noise_profiler.set_pf_center(float(v))

    def set_pf_rolloff_hz(self, v: float) -> None:
        self._config.dsp.perceptual_floor_rolloff_hz = float(v)
        self._noise_profiler.set_pf_rolloff_hz(float(v))

    def set_pf_rolloff_depth(self, v: float) -> None:
        self._config.dsp.perceptual_floor_rolloff_depth = float(v)
        self._noise_profiler.set_pf_rolloff_depth(float(v))

    def set_post_filter_enabled(self, v: bool) -> None:
        self._config.dsp.post_filter_enabled = bool(v)
        self._noise_profiler.set_post_filter_enabled(bool(v))

    def set_post_filter_strength(self, v: float) -> None:
        self._config.dsp.post_filter_strength = float(v)
        self._noise_profiler.set_post_filter_strength(float(v))

    def set_fading_comp(self, v: bool) -> None:
        self._config.dsp.noise_fading_comp = bool(v)
        self._noise_profiler.set_fading_comp(bool(v))

    def set_fading_change_db(self, v: float) -> None:
        self._config.dsp.noise_fading_change_db = float(v)
        self._noise_profiler.set_fading_change_db(float(v))

    def set_fading_freeze_ms(self, v: float) -> None:
        self._config.dsp.noise_fading_freeze_ms = float(v)
        self._noise_profiler.set_fading_freeze_ms(float(v))

    @property
    def fading_comp_enabled(self) -> bool:
        return self._config.dsp.noise_fading_comp

    @property
    def fading_active(self) -> bool:
        return self._noise_profiler.fading_active

    @property
    def pitch_f0(self) -> "float | None":
        return self._noise_profiler.pitch_f0

    def set_pitch_enhance_enabled(self, v: bool) -> None:
        self._config.dsp.pitch_enhance_enabled = bool(v)
        self._noise_profiler.set_pitch_enabled(bool(v))

    def set_pitch_enhance_strength(self, v: float) -> None:
        self._config.dsp.pitch_enhance_strength = float(v)
        self._noise_profiler.set_pitch_strength(float(v))

    @property
    def noise_mode(self) -> str:
        return self._config.dsp.noise_mode

    def set_noise_preview(self, enabled: bool) -> None:
        self._noise_profiler.set_preview_mode(enabled)

    @property
    def anf_notched_bins(self) -> int:
        return self._anf.notched_bins

    @property
    def noise_voice_prob(self) -> float:
        return self._noise_profiler.voice_prob

    @property
    def pf_peak_pct(self) -> float:
        return self._noise_profiler.pf_peak_pct

    @property
    def pf_active_frac(self) -> float:
        return self._noise_profiler.pf_active_frac

    @property
    def post_filter_extra_db(self) -> float:
        return self._noise_profiler.pf_extra_db

    @property
    def noise_voice_prob_sq(self) -> float:
        """voice_prob rápido (release ~40ms), el que usa el gate de squelch."""
        return self._noise_profiler.voice_prob_sq

    @property
    def squelch_gate_open(self) -> bool:
        """True si el gate de squelch está abierto (audio pasa).
        Refleja las mismas condiciones que el bloque de squelch en _run_processor."""
        if (not self._squelch_enabled or not self._noise_enabled
                or not self._noise_profiler.has_profile):
            return True
        vp = self._noise_profiler.voice_prob_sq
        return vp >= self._squelch_threshold or self._squelch_hold_count > 0

    @property
    def noise_reduction_db(self) -> float:
        return self._noise_profiler.last_reduction_db

    @property
    def noise_has_profile(self) -> bool:
        return self._noise_profiler.has_profile

    @property
    def noise_is_learning(self) -> bool:
        return self._noise_profiler.is_learning

    @property
    def noise_duration_ms(self) -> float:
        return self._noise_profiler.duration_ms

    # ------------------------------------------------------------------
    # API pública — ANF
    # ------------------------------------------------------------------

    def set_anf_enabled(self, enabled: bool) -> None:
        self._config.dsp.anf_enabled = enabled
        self._anf.set_enabled(enabled)

    def set_anf_threshold(self, threshold: float) -> None:
        self._config.dsp.anf_threshold = threshold
        self._anf.set_threshold(threshold)

    def set_anf_depth(self, depth: float) -> None:
        self._config.dsp.anf_depth = depth
        self._anf.set_depth(depth)

    # ------------------------------------------------------------------
    # API pública — blanker
    # ------------------------------------------------------------------

    def set_blanker_frame(self, threshold: float) -> None:
        self._config.dsp.blanker_frame = threshold
        self._blanker_frame = float(threshold)

    def set_blanker_mini(self, threshold: float) -> None:
        self._config.dsp.blanker_mini = threshold
        self._blanker_mini = float(threshold)

    def set_blanker_enabled(self, v: bool) -> None:
        self._config.dsp.blanker_enabled = bool(v)
        self._blanker_enabled = bool(v)
    def set_bandpass_pre_enabled(self, v: bool) -> None:
        self._config.dsp.bandpass_pre_enabled = bool(v)
        self._bandpass_pre_enabled = bool(v)

    def set_bandpass_post_enabled(self, v: bool) -> None:
        self._config.dsp.bandpass_post_enabled = bool(v)
        self._bandpass_post_enabled = bool(v)
    def set_noise_enabled(self, v: bool) -> None:
        self._config.dsp.noise_enabled = bool(v)
        self._noise_enabled = bool(v)
        self._noise_profiler.set_enabled(bool(v))

    def set_presence_enabled(self, v: bool) -> None:
        self._config.dsp.presence_enabled = bool(v)
        self._presence_enabled = bool(v)

    def set_exciter_enabled(self, v: bool) -> None:
        self._config.dsp.exciter_enabled = bool(v)
        self._exciter.set_enabled(bool(v))

    def set_exciter_drive(self, drive: float) -> None:
        self._config.dsp.exciter_drive = drive
        self._exciter.set_drive(drive)

    def set_exciter_mix(self, mix: float) -> None:
        self._config.dsp.exciter_mix = mix
        self._exciter.set_mix(mix)

    @property
    def peak_reduction_db(self) -> float:
        """Reducción aplicada por el limitador en el último frame. 0.0 = sin actividad."""
        return self._limiter.last_reduction_db

    def pop_blanker_hits(self) -> int:
        # Lectura+reset no atómico: puede perder un conteo si el hilo DSP
        # incrementa entre ambas líneas. Aceptado a propósito — un lock aquí
        # agregaría contención al hilo de audio para proteger un contador
        # de diagnóstico que se lee 2 veces por segundo.
        h = self._blanker_hits
        self._blanker_hits = 0
        return h

    @property
    def spectrum_pre_frames(self) -> deque:
        return self._spec_pre_frames

    @property
    def spectrum_post_frames(self) -> deque:
        return self._spec_post_frames

    def get_noise_floor_data(self) -> "tuple[np.ndarray, np.ndarray] | None":
        """Retorna (freqs_hz, db) calibrado para coincidir con la escala del SpectrumWidget."""
        db = self._noise_profiler.noise_floor_db
        if db is None:
            return None
        fft_n = self._noise_profiler.noise_fft_n
        freqs = np.arange(fft_n // 2 + 1, dtype=np.float32) * (48000.0 / fft_n)

        # El noise_profiler usa sqrt(hanning(fft_n)), normalizado por fft_n/2.
        # El display usa hanning(2048), normalizado por 2048/2.
        # Para ruido estacionario, el factor RMS por bin es:
        #   display:  sqrt(sum(hann(2048)^2)) / 1024  = sqrt(3*2048/8) / 1024
        #   profiler: sqrt(sum(hann(fft_n)))  / (fft_n/2) = sqrt(fft_n/2) / (fft_n/2)
        # La corrección alinea ambas escalas.
        DISPLAY_FFT_N   = 2048
        display_factor  = np.sqrt(3.0 * DISPLAY_FFT_N / 8) / (DISPLAY_FFT_N / 2)
        profiler_factor = np.sqrt(fft_n / 2.0) / (fft_n / 2.0)
        correction_db   = float(20.0 * np.log10(display_factor / profiler_factor))

        return freqs, (db + correction_db).astype(np.float32)

    # ------------------------------------------------------------------
    # Ciclo de vida del stream
    # ------------------------------------------------------------------

    def start(self, headless: bool = False) -> None:
        """Inicia el procesamiento. headless=True omite el AudioStream (tests sin
        hardware): el hilo procesador corre igual y se alimenta via _process()."""
        with self._lock:
            if self._running:
                return
            self._bandpass.reset()
            self._bandpass_out.reset()
            self._presence.reset()
            self._body.reset()
            self._freq_shifter.reset()
            self._anf.reset()
            self._noise_profiler.reset(self._config.audio.block_size)
            self._agc.set_hop(self._config.audio.block_size)
            self._agc_voice.set_hop(self._config.audio.block_size)
            self._exciter.reset()
            hop_ms = self._config.audio.block_size / self._config.audio.sample_rate * 1000.0
            self._squelch_hold_frames = max(0, round(self._squelch_hold_ms / hop_ms))
            self._squelch_hold_count  = 0
            self._sq_gain_prev        = 1.0
            self._learn_gain_prev     = 1.0
            self._agc.set_hold(False)
            self._in_acc  = np.zeros(0, dtype=np.float32)
            self._out_acc = np.zeros(0, dtype=np.float32)
            self._drain_queues()
            self._running = True

        self._proc_thread = threading.Thread(target=self._run_processor, daemon=True)
        self._proc_thread.start()

        if not headless:
            try:
                stream = AudioStream(self._config.audio, self._process)
                stream.start()
            except Exception:
                # La apertura del stream falló (p. ej. dispositivos incompatibles):
                # revertir el arranque para no quedar a medio camino (running=True
                # con el hilo procesador vivo y sin stream).
                with self._lock:
                    self._running = False
                self._shutdown_processor_thread()
                raise
            with self._lock:
                self._stream = stream

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            stream = self._stream
            self._stream = None

        if stream:
            stream.stop()

        self._shutdown_processor_thread()

        # Cerrar la grabación en curso (header del WAV finalizado limpio)
        if self._recorder.recording:
            self._recorder.stop()

    def _shutdown_processor_thread(self) -> None:
        """Envía el sentinel y espera a que el hilo procesador termine, con
        drain + reintento por si la cola quedó llena. Compartido por stop() y por
        el rollback de start() (cuando falla la apertura del stream)."""
        # Drain first so the sentinel fits even if the queue was full
        # (safe: stream is stopped, no new data arrives)
        while True:
            try:
                self._in_queue.get_nowait()
            except queue.Empty:
                break
        try:
            self._in_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._proc_thread:
            self._proc_thread.join(timeout=2.0)
            if self._proc_thread.is_alive():
                # Thread hung past timeout — drain again so it unblocks
                while True:
                    try:
                        self._in_queue.get_nowait()
                    except queue.Empty:
                        break
                try:
                    self._in_queue.put_nowait(None)
                except queue.Full:
                    pass
                self._proc_thread.join(timeout=1.0)
            self._proc_thread = None

    def is_running(self) -> bool:
        return self._running

    @property
    def db_in(self) -> float:
        return self._db_in

    @property
    def db_out(self) -> float:
        return self._db_out

    @property
    def latency_ms(self) -> float:
        return self._latency_ms

    # ------------------------------------------------------------------
    # Thread de procesamiento DSP (fuera del callback de audio)
    # ------------------------------------------------------------------

    def _drain_queues(self) -> None:
        for q in (self._in_queue, self._out_queue):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        self._spec_pre_frames.clear()
        self._spec_post_frames.clear()

    def _run_processor(self) -> None:
        energy_hist = 1e-8

        while True:
            try:
                chunk = self._in_queue.get(timeout=0.05)
            except queue.Empty:
                if not self._running:
                    break
                continue

            if chunk is None:
                break

            try:
                # Referencia al chunk crudo para la grabación (ninguna etapa
                # muta el array original in place — el blanker copia primero)
                raw_chunk = chunk

                # Supresor de impulsiones en dos niveles
                frame_energy = float(np.dot(chunk, chunk)) / len(chunk)
                if frame_energy < energy_hist:
                    energy_hist = 0.95 * energy_hist + 0.05 * frame_energy
                else:
                    energy_hist = 0.999 * energy_hist + 0.001 * frame_energy

                if self._blanker_enabled:
                    thr_frame = self._blanker_frame
                    if frame_energy > thr_frame * energy_hist:
                        gain         = np.sqrt(thr_frame * energy_hist / frame_energy)
                        chunk        = chunk * gain
                        frame_energy = frame_energy * gain * gain
                        self._blanker_hits += 1

                    _MINI = 32
                    n_complete = (len(chunk) // _MINI) * _MINI
                    if n_complete > 0:
                        mini   = chunk[:n_complete].reshape(-1, _MINI)
                        mini_e = np.sum(mini ** 2, axis=1) / _MINI
                        thresh = self._blanker_mini * energy_hist
                        over   = mini_e > thresh
                        if np.any(over):
                            scales = np.where(over, np.sqrt(thresh / (mini_e + 1e-12)), 1.0)
                            chunk  = chunk.copy()
                            chunk[:n_complete] = (mini * scales[:, np.newaxis].astype(np.float32)).ravel()
                            self._blanker_hits += int(np.sum(over))

                # Durante el aprendizaje del perfil: AGC congelado (si no, sube
                # la ganancia sobre el ruido y el perfil captura un barrido de
                # niveles en vez de un nivel estable)
                learning = self._noise_profiler.is_learning
                self._agc.set_hold(learning)
                chunk = self._agc.process(chunk)

                with self._lock:
                    filtered = self._bandpass.process(chunk) if self._bandpass_pre_enabled else chunk

                filtered = self._anf.process(filtered)
                # Perfil independiente del filtro: durante el aprendizaje se alimenta
                # el profiler con el espectro COMPLETO (post-AGC, PRE-pasabanda/ANF),
                # así el noise_mag cubre todas las frecuencias. En reproducción el
                # cancelador suprime bien los agudos aunque el pasabanda cambie, se
                # ensanche o se apague (antes el perfil aprendía ~0 en los agudos —el
                # filtro los quitaba— y al ensanchar/reiniciar el siseo agudo pasaba
                # sin suprimir). El pasabanda/ANF igual corren arriba para no congelar
                # su estado IIR; su salida se descarta para el aprendizaje. El monitoreo
                # del aprendizaje se atenúa -12dB, así que no importa que sea sin filtrar.
                prof_in = chunk if learning else filtered
                self._spec_pre_frames.append(prof_in.copy())    # lo que ve el profiler
                # El VAD del profiler descuenta la ganancia del AGC (nivel de antena)
                self._noise_profiler.set_agc_gain(self._agc.gain_lin)
                filtered = self._noise_profiler.process(prof_in)

                # Monitoreo atenuado durante el aprendizaje: sin perfil todavía
                # no hay supresión y el ruido de banda sale a pleno — molesto y
                # puede saturar. -12 dB con rampa por frame (sin clicks).
                learn_gain = self._LEARN_DUCK_GAIN if learning else 1.0
                if learn_gain != self._learn_gain_prev or learn_gain < 1.0:
                    ramp = np.linspace(self._learn_gain_prev, learn_gain,
                                       len(filtered), dtype=np.float32)
                    filtered = filtered * ramp
                    self._learn_gain_prev = learn_gain

                # El squelch depende de voice_prob_sq, que solo se actualiza con el
                # cancelador activo — sin _noise_enabled el vp queda congelado y el
                # gate podría cerrar para siempre.
                if (self._squelch_enabled and self._noise_enabled
                        and self._noise_profiler.has_profile):
                    vp = self._noise_profiler.voice_prob_sq
                    if vp >= self._squelch_threshold:
                        self._squelch_hold_count = self._squelch_hold_frames
                    elif self._squelch_hold_count > 0:
                        self._squelch_hold_count -= 1
                    # Ganancia del gate: plena con voz y durante la primera mitad
                    # de la retención (no toca pausas entre palabras); fade suave
                    # en la segunda mitad — evita la "cola de squelch" (ruido a
                    # pleno volumen hasta el mute abrupto). Si vuelve la voz, la
                    # rampa por frame reabre sin click.
                    if vp >= self._squelch_threshold:
                        sq_gain = 1.0
                    else:
                        half    = max(1, self._squelch_hold_frames // 2)
                        sq_gain = min(1.0, self._squelch_hold_count / half)
                    if sq_gain < 1.0 or self._sq_gain_prev < 1.0:
                        ramp = np.linspace(self._sq_gain_prev, sq_gain,
                                           len(filtered), dtype=np.float32)
                        filtered = filtered * ramp
                    self._sq_gain_prev = sq_gain
                else:
                    self._sq_gain_prev = 1.0

                # Nivelador de voz: solo adapta con voz presente (el vp requiere
                # cancelador activo — invariante 2); con ruido o gate cerrado la
                # ganancia queda congelada y no persigue al ruido residual.
                if (self._voice_leveler_enabled and self._noise_enabled
                        and self._noise_profiler.has_profile):
                    self._agc_voice.set_hold(
                        self._noise_profiler.voice_prob < self._LEVELER_VP_THR)
                    filtered = self._agc_voice.process(filtered)

                with self._lock:
                    mixed = self._bandpass_out.process(filtered) if self._bandpass_post_enabled else filtered
                    if self._presence_enabled:
                        mixed = self._presence.process(mixed)
                        mixed = self._body.process(mixed)
                    mixed = self._exciter.process(mixed)
                    out_frame = self._limiter.process(mixed, self._config.audio.sample_rate)

                out_frame = self._freq_shifter.process(out_frame)
                self._spec_post_frames.append(out_frame.copy())

                if self._recorder.recording:
                    self._recorder.feed(
                        out_frame,
                        raw_chunk if self._recorder.wants_raw else None)

                try:
                    self._out_queue.put_nowait(out_frame)
                except queue.Full:
                    pass

            except Exception as exc:
                if self._on_error:
                    self._on_error(f"Error en procesador DSP: {exc}")
                # Reset internal DSP state so the next chunk has clean buffers
                self._noise_profiler.reset(self._config.audio.block_size)
                with self._lock:
                    self._bandpass.reset()
                    self._bandpass_out.reset()
                    self._presence.reset()
                    self._body.reset()
                    self._exciter.reset()
                energy_hist = 1e-8

    # ------------------------------------------------------------------
    # Callback de audio (hilo de alta prioridad)
    # ------------------------------------------------------------------

    def _process(self, audio_in: np.ndarray) -> np.ndarray:
        audio_in = audio_in * self._input_gain
        self._db_in = self._level_in.process(audio_in)

        if self._bypass:
            self._db_out = self._db_in
            self._latency_ms = 0.0
            # La grabación captura "lo que se escucha": en bypass, la señal
            # cruda va a ambos archivos (sin esto, la grabación quedaba PAUSADA
            # durante el bypass — el feed vivía solo en el hilo procesador).
            # feed() es no-bloqueante: seguro desde el callback de audio.
            # Bonus: alternar Bypass durante una grabación produce un
            # antes/después en el mismo archivo.
            if self._recorder.recording:
                self._recorder.feed(
                    audio_in,
                    audio_in if self._recorder.wants_raw else None)
            return audio_in

        hop = self._config.audio.block_size

        self._in_acc = np.concatenate((self._in_acc, audio_in))
        while len(self._in_acc) >= hop:
            chunk = self._in_acc[:hop].copy()
            self._in_acc = self._in_acc[hop:]
            try:
                self._in_queue.put_nowait(chunk)
            except queue.Full:
                pass

        while True:
            try:
                frame = self._out_queue.get_nowait()
                self._out_acc = np.concatenate((self._out_acc, frame))
            except queue.Empty:
                break

        n_out = len(audio_in)
        if len(self._out_acc) >= n_out:
            out = self._out_acc[:n_out]
            self._out_acc = self._out_acc[n_out:]
        elif len(self._out_acc) > 0:
            out = np.concatenate((
                self._out_acc,
                np.zeros(n_out - len(self._out_acc), dtype=np.float32),
            ))
            self._out_acc = np.zeros(0, dtype=np.float32)
        else:
            out = np.zeros(n_out, dtype=np.float32)

        self._db_out = self._level_out.process(out)
        if self._stream:
            hop_ms = self._config.audio.block_size / self._config.audio.sample_rate * 1000
            algo_hops = 1  # pipeline queue + callback cycle
            if self._config.dsp.anf_enabled:
                algo_hops += 1  # ANF OLA: 1 hop
            if self._config.dsp.noise_enabled:
                algo_hops += 1  # NoiseProfiler OLA: 1 hop
            self._latency_ms = self._stream.latency_ms + algo_hops * hop_ms

        if self._on_level_update:
            self._on_level_update(self._db_in, self._db_out, self._latency_ms)

        return out
