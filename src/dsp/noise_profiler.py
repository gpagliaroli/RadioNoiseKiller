import numpy as np


class NoiseProfiler:
    """
    Reducción de ruido estacionario — DD Wiener + VAD adaptativo + OLA.

    Ganancia DD (Ephraim-Malah):
        SNR_post[k] = |Y[k]|² / (α·noise[k])²
        inst[k]     = max(SNR_post[k] − 1, 0)
        SNR_prior[k] = (1−β_eff)·inst[k] + β_eff·gain_prev[k]²·SNR_post_prev[k]
        gain[k]     = max( SNR_prior[k]/(SNR_prior[k]+1), floor )

    La fórmula DD converge a floor en ruido puro con β simétrico alto:
        Con β=0.97: SNR_prior(ruido) ≈ 0.051 → gain ≈ 0.049 < floor → suprimido

    Asimetría controlada por VAD:
        g_detect[k] = max(1 − noise_mag[k]² / |Y[k]|², 0)
            ≈ 0  para bins de ruido  (P(g_detect>0.80) ≈ 0.67%)
            → 1  para bins de voz con SNR > 6 dB

        β_attack  = β_release × (1−voice_prob) + β_fast × voice_prob   (configurable, rápido)
        use_fast  = (bin subiendo) AND (g_detect > 0.80)
        β_eff[k]  = β_attack si use_fast[k], β_release de lo contrario

    Resultado:
        - Ruido puro: β simétrico → sin gorgojeo; gains convergen a floor
        - Voz: bins de voz suben rápido (65% en 10ms, 94% en 50ms) sin afectar bins de ruido
        - Control "Anti-gorgojeo" (β_release): actúa en todos los bins durante el ruido

    OLA:
        Overlap-Add con ventana sqrt-Hann al 50% (1 hop de latencia extra).
        Elimina discontinuidades en bordes de bloque.
    """

    _VAD_THRESHOLD: float = 0.80  # g_detect > umbral → bin claramente de voz

    def __init__(self, hop_size: int = 480):
        self._hop   = hop_size
        self._fft_n = 2 * hop_size
        self._nb    = self._fft_n // 2 + 1

        # OLA
        self._ola_win  = np.sqrt(np.hanning(self._fft_n)).astype(np.float32)
        self._ola_prev = np.zeros(hop_size, dtype=np.float32)
        self._ola_acc  = np.zeros(self._fft_n, dtype=np.float32)

        # Perfil de ruido
        self._noise_mag: np.ndarray | None = None
        self._is_learning = False
        self._accum       = np.zeros(self._nb, dtype=np.float64)
        self._n_frames    = 0

        # Parámetros controlados por sliders
        self._alpha:     float = 0.7   # intensidad de sustracción (0=off, 1=máximo)
        self._floor:     float = 0.1   # ganancia mínima por bin
        self._beta:      float = 0.97  # β_release: alto = sin gorgojeo al retornar al ruido
        self._beta_fast: float = 0.80  # β_attack: bajo = onset de voz más rápido (bajo riesgo con floor≥0.05)

        # Estado DD inter-frame
        self._gain_prev:     np.ndarray | None = None
        self._snr_post_prev: np.ndarray | None = None

        # VAD frame-level
        self._voice_prob: float = 0.0

        self._last_reduction_db: float = 0.0
        self._preview_mode: bool = False
        self._enabled:      bool = True

    # ------------------------------------------------------------------
    # Control de aprendizaje
    # ------------------------------------------------------------------

    def reset(self, hop_size: int | None = None) -> None:
        if hop_size is not None and hop_size != self._hop:
            self._hop   = hop_size
            self._fft_n = 2 * hop_size
            self._nb    = self._fft_n // 2 + 1
            self._ola_win = np.sqrt(np.hanning(self._fft_n)).astype(np.float32)
            self._accum   = np.zeros(self._nb, dtype=np.float64)
            self._noise_mag = None
            self._n_frames  = 0
        self._ola_prev      = np.zeros(self._hop, dtype=np.float32)
        self._ola_acc       = np.zeros(self._fft_n, dtype=np.float32)
        self._gain_prev     = None
        self._snr_post_prev = None
        self._voice_prob    = 0.0

    def start_learning(self) -> None:
        self._accum[:]    = 0.0
        self._n_frames    = 0
        self._is_learning = True

    def stop_learning(self) -> int:
        self._is_learning = False
        if self._n_frames > 0:
            self._noise_mag     = np.sqrt(self._accum / self._n_frames).astype(np.float32)
            self._gain_prev     = None
            self._snr_post_prev = None
            self._voice_prob    = 0.0
        return self._n_frames

    def clear_profile(self) -> None:
        self._is_learning       = False
        self._noise_mag         = None
        self._accum[:]          = 0.0
        self._n_frames          = 0
        self._gain_prev         = None
        self._snr_post_prev     = None
        self._voice_prob        = 0.0
        self._last_reduction_db = 0.0
        self._ola_prev          = np.zeros(self._hop,   dtype=np.float32)
        self._ola_acc           = np.zeros(self._fft_n, dtype=np.float32)

    # ------------------------------------------------------------------
    # Parámetros en tiempo real
    # ------------------------------------------------------------------

    def set_alpha(self, alpha: float) -> None:
        self._alpha = float(np.clip(alpha, 0.0, 1.0))

    def set_floor(self, floor: float) -> None:
        self._floor = float(np.clip(floor, 0.0, 0.5))

    def set_smooth(self, smooth: float) -> None:
        """β_release: cuán lento decaen los gains al retornar al ruido.
        Alto (0.97-0.98) = sin gorgojeo. Default 0.97."""
        self._beta = float(np.clip(smooth, 0.0, 0.99))

    def set_attack(self, attack: float) -> None:
        """β_fast: velocidad de ataque para bins de voz confirmados.
        Bajo (0.50-0.70) = onset rápido, consonantes nítidas. Default 0.80."""
        self._beta_fast = float(np.clip(attack, 0.0, 0.99))

    def set_preview_mode(self, enabled: bool) -> None:
        self._preview_mode = bool(enabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------

    def process(self, chunk: np.ndarray) -> np.ndarray:
        hop = len(chunk)

        # Frame OLA: [bloque anterior | bloque actual]
        frame       = np.empty(self._fft_n, dtype=np.float32)
        frame[:hop] = self._ola_prev
        frame[hop:] = chunk
        self._ola_prev = chunk.copy()

        spec = np.fft.rfft(frame * self._ola_win, n=self._fft_n)

        if self._is_learning:
            self._accum    += np.abs(spec) ** 2
            self._n_frames += 1

        noise_mag = self._noise_mag
        if noise_mag is None or not self._enabled:
            out_frame = np.fft.irfft(spec, n=self._fft_n).astype(np.float32) * self._ola_win
        else:
            sig_power   = np.abs(spec).astype(np.float32) ** 2 + 1e-12
            noise_power = (self._alpha * noise_mag) ** 2 + 1e-12
            noise_prof2 = noise_mag.astype(np.float64) ** 2 + 1e-12

            # --- SNR a posteriori y componente instantánea DD ---
            snr_post = (sig_power / noise_power).astype(np.float32)
            inst     = np.maximum(snr_post - 1.0, 0.0)

            # --- Detector de bins de voz (con α=1 implícito, sin escalar por alpha) ---
            # g_detect[k] ≈ 0 para bins de ruido, → 1 para bins dominados por voz
            # P(g_detect > 0.80) ≈ 0.67% en ruido puro → falsos positivos mínimos
            g_detect  = np.maximum(1.0 - noise_prof2 / sig_power.astype(np.float64),
                                   0.0).astype(np.float32)
            voice_bin = g_detect > self._VAD_THRESHOLD

            # --- VAD frame-level ---
            # En ruido puro: mean_sig / mean(noise_mag²) ≈ 1.0 → voice_prob → 0
            # Con voz:       ratio >> 1.0 → voice_prob → 1.0
            mean_sig        = float(np.mean(sig_power))
            mean_noise_prof = float(np.mean(noise_prof2))
            snr_ratio       = mean_sig / mean_noise_prof
            vp_raw          = float(np.clip(snr_ratio - 1.0, 0.0, 1.0))

            if vp_raw > self._voice_prob:
                self._voice_prob = 0.4 * self._voice_prob + 0.6 * vp_raw  # ataque: ~2 frames
            else:
                self._voice_prob *= 0.97                                    # release: ~330 ms
            self._voice_prob = float(np.clip(self._voice_prob, 0.0, 1.0))

            # --- β efectivo por bin ---
            # β_release = slider (alto → sin gorgojeo)
            # β_attack  = (β_release → 0) según voice_prob — solo actúa en bins claramente de voz
            beta_r        = np.float32(self._beta)
            vp            = np.float32(self._voice_prob)
            beta_fast_eff = np.float32(beta_r * (1.0 - vp) + self._beta_fast * vp)

            # --- DD SNR a priori ---
            if self._gain_prev is None:
                snr_prior = inst.copy()
            else:
                rising   = snr_post > self._snr_post_prev
                # Ataque rápido solo para bins claramente de voz en frames de voz
                use_fast = rising & voice_bin
                beta_eff = np.where(use_fast, beta_fast_eff, beta_r)
                snr_prior = ((1.0 - beta_eff) * inst
                             + beta_eff * self._gain_prev ** 2 * self._snr_post_prev)

            # --- Gain DD (estado interno) ---
            # gain_dd alimenta el estimador DD en el próximo frame (no modificado)
            gain_dd = np.maximum(snr_prior / (snr_prior + 1.0), self._floor).astype(np.float32)
            self._gain_prev     = gain_dd
            self._snr_post_prev = snr_post

            # --- OMLSA: anclar bins de ruido exactamente al floor ---
            # p_speech[k] = 0 → bin de ruido confirmado → gain_out = floor (sin fluctuación)
            # p_speech[k] = 1 → bin de voz confirmado  → gain_out = gain_dd (sin cambio)
            # La mezcla geométrica es suave en la transición y preserva la escala log.
            p_speech = np.minimum(g_detect / self._VAD_THRESHOLD, 1.0).astype(np.float32)
            gain_out = (gain_dd ** p_speech) * (self._floor ** (1.0 - p_speech))

            # --- Suavizado de gain en frecuencia (elimina picos bin-aislados) ---
            # Un bin aislado con gain alto rodeado de floor es el patrón típico del gorgojeo.
            kernel   = np.array([0.25, 0.50, 0.25], dtype=np.float32)
            gain_out = np.convolve(gain_out, kernel, mode='same')
            gain_out = np.maximum(gain_out, self._floor).astype(np.float32)

            self._last_reduction_db = 20.0 * np.log10(max(float(np.mean(gain_out)), 1e-6))

            if self._preview_mode:
                spec_out = ((1.0 - gain_out) * spec).astype(np.complex64)
            else:
                spec_out = (gain_out * spec).astype(np.complex64)

            out_frame = np.fft.irfft(spec_out, n=self._fft_n).astype(np.float32) * self._ola_win

        # Overlap-Add
        self._ola_acc      += out_frame
        result              = self._ola_acc[:hop].copy()
        self._ola_acc[:hop] = self._ola_acc[hop:]
        self._ola_acc[hop:] = 0.0

        return result

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def voice_prob(self) -> float:
        return self._voice_prob

    @property
    def has_profile(self) -> bool:
        return self._noise_mag is not None

    @property
    def is_learning(self) -> bool:
        return self._is_learning

    @property
    def frames_learned(self) -> int:
        return self._n_frames

    @property
    def duration_ms(self) -> float:
        return self._n_frames * self._hop / 48000.0 * 1000.0

    @property
    def last_reduction_db(self) -> float:
        return self._last_reduction_db

    @property
    def noise_floor_db(self) -> np.ndarray | None:
        """Piso de ruido aprendido en dB (~dBFS). Shape: (fft_n//2 + 1,). None si no hay perfil."""
        if self._noise_mag is None:
            return None
        return (20.0 * np.log10(
            np.maximum(self._noise_mag, 1e-10) / (self._fft_n / 2.0)
        )).astype(np.float32)

    @property
    def noise_fft_n(self) -> int:
        return self._fft_n
