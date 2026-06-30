import threading
import queue
import numpy as np
from config import AppConfig, RadioMode
from audio.stream import AudioStream
from audio.devices import AudioDevice
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

    def __init__(self, config: AppConfig):
        self._config = config
        self._lock   = threading.Lock()
        self._running = False
        self._bypass  = False
        self._input_gain: float = 10 ** (config.gain.input_gain_db / 20.0)

        self._blanker_frame: float = config.dsp.blanker_frame
        self._blanker_mini:  float = config.dsp.blanker_mini
        self._blanker_hits:  int   = 0

        self._blanker_enabled:       bool = True
        self._bandpass_pre_enabled:  bool = config.dsp.bandpass_pre_enabled
        self._bandpass_post_enabled: bool = config.dsp.bandpass_post_enabled
        self._noise_enabled:         bool = True
        self._presence_enabled:      bool = True

        self._agc = AGC(config.audio.sample_rate, config.audio.block_size)
        self._bandpass     = BandpassFilter(config.dsp, config.audio.sample_rate)
        self._bandpass_out = BandpassFilter(config.dsp, config.audio.sample_rate)
        self._anf = AdaptiveNotchFilter(
            sample_rate=config.audio.sample_rate,
            threshold=config.dsp.anf_threshold,
            depth=config.dsp.anf_depth,
        )
        self._anf.set_enabled(config.dsp.anf_enabled)
        self._noise_profiler = NoiseProfiler(config.audio.block_size)
        self._noise_profiler.set_smooth(config.dsp.noise_smooth)
        self._noise_profiler.set_attack(config.dsp.noise_attack)
        self._squelch_enabled:   bool  = config.dsp.squelch_enabled
        self._squelch_threshold: float = config.dsp.squelch_threshold
        self._squelch_hold_ms:   float = config.dsp.squelch_hold_ms
        self._squelch_hold_frames: int = 0   # se calcula en start()
        self._squelch_hold_count:  int = 0
        self._exciter = AuralExciter(config.audio.sample_rate)
        self._exciter.set_drive(config.dsp.exciter_drive)
        self._exciter.set_mix(config.dsp.exciter_mix)
        self._exciter.set_enabled(config.dsp.exciter_enabled)
        self._presence = PresenceFilter(config.audio.sample_rate)
        self._presence.set_freq(config.dsp.presence_freq)
        self._presence.set_gain_db(config.dsp.presence_db)
        self._presence.set_q(config.dsp.presence_q)
        self._freq_shifter = FrequencyShifter(config.audio.sample_rate)
        self._freq_shifter.set_shift_hz(config.dsp.pitch_shift_hz)
        self._limiter = GainLimiter(
            gain_db=config.gain.output_gain_db,
            limit_db=config.gain.peak_limit_db,
        )
        self._level_in  = LevelMeter(sample_rate=config.audio.sample_rate)
        self._level_out = LevelMeter(sample_rate=config.audio.sample_rate)
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
        self._agc.set_preset(preset)

    def set_presence_db(self, db: float) -> None:
        self._config.dsp.presence_db = float(db)
        self._presence.set_gain_db(db)

    def set_presence_q(self, q: float) -> None:
        self._config.dsp.presence_q = float(q)
        self._presence.set_q(q)

    def set_presence_freq(self, hz: float) -> None:
        self._config.dsp.presence_freq = float(hz)
        self._presence.set_freq(hz)

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
            self._bandpass_out.set_limits(mode, lo, hi)

    def set_filter_order(self, order: int) -> None:
        self._config.dsp.filter_order = order
        with self._lock:
            self._bandpass.set_order(order)
            self._bandpass_out.set_order(order)

    # ------------------------------------------------------------------
    # API pública — cancelación de ruido estacionario
    # ------------------------------------------------------------------

    def start_noise_learning(self) -> None:
        self._noise_profiler.start_learning()

    def stop_noise_learning(self) -> int:
        return self._noise_profiler.stop_learning()

    def clear_noise_profile(self) -> None:
        self._noise_profiler.clear_profile()

    def set_noise_alpha(self, alpha: float) -> None:
        self._noise_profiler.set_alpha(alpha)

    def set_noise_floor(self, floor: float) -> None:
        self._noise_profiler.set_floor(floor)

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

    def set_noise_preview(self, enabled: bool) -> None:
        self._noise_profiler.set_preview_mode(enabled)

    @property
    def anf_notched_bins(self) -> int:
        return self._anf.notched_bins

    @property
    def noise_voice_prob(self) -> float:
        return self._noise_profiler.voice_prob

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

    def set_blanker_enabled(self,  v: bool) -> None: self._blanker_enabled  = bool(v)
    def set_bandpass_pre_enabled(self, v: bool) -> None:
        self._config.dsp.bandpass_pre_enabled = bool(v)
        self._bandpass_pre_enabled = bool(v)

    def set_bandpass_post_enabled(self, v: bool) -> None:
        self._config.dsp.bandpass_post_enabled = bool(v)
        self._bandpass_post_enabled = bool(v)
    def set_noise_enabled(self,    v: bool) -> None:
        self._noise_enabled = bool(v)
        self._noise_profiler.set_enabled(bool(v))
    def set_presence_enabled(self, v: bool) -> None: self._presence_enabled = bool(v)

    def set_exciter_enabled(self, v: bool) -> None:
        self._config.dsp.exciter_enabled = bool(v)
        self._exciter.set_enabled(bool(v))

    def set_exciter_drive(self, drive: float) -> None:
        self._config.dsp.exciter_drive = drive
        self._exciter.set_drive(drive)

    def set_exciter_mix(self, mix: float) -> None:
        self._config.dsp.exciter_mix = mix
        self._exciter.set_mix(mix)

    def pop_blanker_hits(self) -> int:
        h = self._blanker_hits
        self._blanker_hits = 0
        return h

    # ------------------------------------------------------------------
    # Ciclo de vida del stream
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._bandpass.reset()
            self._bandpass_out.reset()
            self._presence.reset()
            self._freq_shifter.reset()
            self._anf.reset()
            self._noise_profiler.reset(self._config.audio.block_size)
            self._exciter.reset()
            hop_ms = self._config.audio.block_size / self._config.audio.sample_rate * 1000.0
            self._squelch_hold_frames = max(0, round(self._squelch_hold_ms / hop_ms))
            self._squelch_hold_count  = 0
            self._in_acc  = np.zeros(0, dtype=np.float32)
            self._out_acc = np.zeros(0, dtype=np.float32)
            self._drain_queues()
            self._running = True

        self._proc_thread = threading.Thread(target=self._run_processor, daemon=True)
        self._proc_thread.start()

        with self._lock:
            self._stream = AudioStream(self._config.audio, self._process)
            self._stream.start()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            stream = self._stream
            self._stream = None

        if stream:
            stream.stop()

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

                chunk = self._agc.process(chunk)

                with self._lock:
                    filtered = self._bandpass.process(chunk) if self._bandpass_pre_enabled else chunk

                filtered = self._anf.process(filtered)
                filtered = self._noise_profiler.process(filtered)

                if self._squelch_enabled and self._noise_profiler.has_profile:
                    vp = self._noise_profiler.voice_prob
                    if vp >= self._squelch_threshold:
                        self._squelch_hold_count = self._squelch_hold_frames
                        sq_gain = 1.0
                    elif self._squelch_hold_count > 0:
                        self._squelch_hold_count -= 1
                        sq_gain = 1.0
                    else:
                        sq_gain = float(np.clip(vp / max(self._squelch_threshold, 1e-6), 0.0, 1.0))
                    filtered = filtered * np.float32(sq_gain)

                with self._lock:
                    mixed = self._bandpass_out.process(filtered) if self._bandpass_post_enabled else filtered
                    if self._presence_enabled:
                        mixed = self._presence.process(mixed)
                    mixed = self._exciter.process(mixed)
                    out_frame = self._limiter.process(mixed, self._config.audio.sample_rate)

                out_frame = self._freq_shifter.process(out_frame)

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
            self._latency_ms = self._stream.latency_ms

        if self._on_level_update:
            self._on_level_update(self._db_in, self._db_out, self._latency_ms)

        return out
