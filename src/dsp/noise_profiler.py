import numpy as np
from scipy.special import exp1 as _exp1


class NoiseProfiler:
    """
    Reducción de ruido estacionario — DD Wiener + VAD adaptativo + OLA.

    Dos modos de operación:
      "static" — perfil aprendido manualmente (comportamiento original)
      "mcra"   — estimación adaptativa continua (MCRA, Cohen & Berdugo 2002)
                 no requiere aprendizaje manual; se calibra en ~200ms y se
                 adapta en tiempo real a los cambios del ruido de banda.

    Ganancia Log-MMSE (Ephraim-Malah 1985):
        SNR_post[k] = |Y[k]|² / noise[k]²
        inst[k]     = max(SNR_post[k] − 1, 0)
        SNR_prior[k] = (1−β_eff)·inst[k] + β_eff·gain_prev[k]²·SNR_post_prev[k]
        g_wiener[k] = SNR_prior[k] / (SNR_prior[k] + 1)          (ganancia Wiener base)
        v[k]        = g_wiener[k] · SNR_post[k]                  (parámetro E₁)
        gain_dd[k]  = clip( g_wiener[k] · exp(½·E₁(v[k])), floor, 1 )
        → para SNR bajo: gain_dd > gain_wiener (menos supresión en bins de voz débil)
        → para SNR alto: exp(½·E₁(v)) → 1, recupera el Wiener clásico

    OMLSA + control de intensidad:
        p_speech[k] = min(g_detect[k] / 0.80, 1)
        gain_omlsa  = gain_dd^p_speech · floor^(1−p_speech)
        gain_out    = gain_omlsa^alpha     (alpha=0 passthrough, alpha=1 pleno)

    MCRA (estimación adaptativa de noise_mag):
        S_f[k]     = α_s·S_f_prev + (1−α_s)·|Y[k]|²     (suavizado potencia)
        S_min[k]   = mín de S_f en ventana deslizante B·M frames (~800ms)
        I_min[k]   = S_f[k]/S_min[k] > δ  →  1 si hay habla, 0 si ruido
        α_d[k]     = α_d0 + (1−α_d0)·I_min[k]            (actualiza lento con habla)
        λ_d[k]     = α_d·λ_d_prev + (1−α_d)·|Y[k]|²     (estimado de ruido)
        noise_mag  = sqrt(λ_d)

    OLA:
        Overlap-Add con ventana sqrt-Hann al 50% (1 hop de latencia extra).
    """

    _VAD_THRESHOLD: float = 0.80

    # Parámetros pitch enhancement (SSB)
    _PITCH_BUF_N:    int   = 2048   # muestras de audio para autocorrelación (~42ms @ 48kHz)
    _PITCH_LAG_MIN:  int   = 120    # lag mínimo → 400 Hz
    _PITCH_LAG_MAX:  int   = 600    # lag máximo →  80 Hz
    _PITCH_CONF_THR: float = 0.30   # umbral de confianza de la autocorrelación
    _PITCH_SIGMA:    float = 1.5    # sigma (bins) de la máscara gaussiana por armónico

    # Parámetros MCRA
    _MCRA_ALPHA_S:       float = 0.9    # suavizado espectral
    _MCRA_ALPHA_D0:      float = 0.85   # velocidad de actualización del ruido (sin habla)
    _MCRA_DELTA:         float = 1.67   # umbral ratio S_f/S_min para detectar habla
    _MCRA_B:             int   = 4      # número de subtramas
    _MCRA_M:             int   = 20     # frames por subtrama → ventana total = B×M = 80 frames ≈ 800ms
    _MCRA_SQUELCH_RATIO: float = 0.05  # congelar si potencia_frame < 5% del piso estimado (-13 dB)

    # Compensación de fading HF
    # Detecta cambios bruscos de energía (fading ionosférico) y congela MCRA para que el
    # piso de ruido no siga al nivel de señal. También acelera el release del estimador DD.
    _FADING_CHANGE_DB:    float = 5.0   # umbral: cambio ≥5 dB en un frame → fade detectado
    _FADING_FREEZE_FRAMES: int  = 20    # frames a congelar MCRA tras el evento (200ms)
    _FADING_EMA_ALPHA:    float = 0.80  # suavizado de energía para detección (TC≈4 frames)
    _FADING_BETA_RELEASE: float = 0.45  # beta DD en modo fading (release más rápido que 0.80)

    # VAD frame-level (energy minimum tracker)
    # Dos trackers paralelos: uno lento (OMLSA) y uno rápido (squelch).
    # El ratio lambda_d/sig_power subestima el ruido ~40% (min-tracking bias),
    # por eso usamos un tracker de energía independiente del estimador.
    _VAD_ALPHA_FAST: float = 0.90   # lento: TC=10 frames (100ms) → voz suave en OMLSA
    _VAD_ALPHA_SQ:   float = 0.50   # rápido: TC=2 frames (20ms) → squelch reactivo
    _VAD_MIN_DECAY:  float = 1.002  # piso mínimo sube 0.2%/frame
    _VAD_SQ_RELEASE: float = 0.60   # release voice_prob_sq: 1.0→0.15 en ~4 frames (≈40ms)

    def __init__(self, hop_size: int = 480):
        self._hop   = hop_size
        self._fft_n = 2 * hop_size
        self._nb    = self._fft_n // 2 + 1

        # OLA
        self._ola_win  = np.sqrt(np.hanning(self._fft_n)).astype(np.float32)
        self._ola_prev = np.zeros(hop_size, dtype=np.float32)
        self._ola_acc  = np.zeros(self._fft_n, dtype=np.float32)

        # Perfil estático
        self._noise_mag:  np.ndarray | None = None
        self._is_learning = False
        self._accum       = np.zeros(self._nb, dtype=np.float64)
        self._n_frames    = 0

        # Parámetros controlados por sliders
        self._alpha:     float = 0.7
        self._floor:     float = 0.1
        self._beta:      float = 0.97
        self._beta_fast: float = 0.80

        # Estado DD inter-frame
        self._gain_prev:     np.ndarray | None = None
        self._snr_post_prev: np.ndarray | None = None

        # VAD frame-level
        self._voice_prob:    float = 0.0   # suavizado lento (OMLSA)
        self._voice_prob_sq: float = 0.0   # suavizado rápido (squelch)

        self._last_reduction_db: float = 0.0
        self._preview_mode: bool = False
        self._enabled:      bool = True

        # Modo de operación
        self._mode: str = "static"

        # Piso perceptual (curva de enmascaramiento auditivo por bin)
        self._perceptual_floor_enabled: bool  = False
        self._pf_boost:         float = 0.75    # amplitud del boost vocal (0–2.5)
        self._pf_center:        float = 500.0   # Hz, centro del pico de boost
        self._pf_rolloff_hz:    float = 3000.0  # Hz, inicio del rolloff de alta frecuencia
        self._pf_rolloff_depth: float = 0.55    # profundidad máxima del rolloff (0–0.7)
        self._floor_curve: np.ndarray = self._build_floor_curve()

        # Compensación de fading HF
        self._fading_comp:         bool  = False
        self._fading_energy_ema:   float | None = None  # EMA de energía de frame
        self._mcra_freeze_count:   int   = 0    # frames restantes de congelado MCRA
        self._fading_active:       bool  = False # True mientras hay evento de fading

        # Métricas para indicadores UI
        self._pf_active_frac: float = 0.0   # fracción de bins retenidos por el piso perceptual
        self._pf_extra_db:    float = 0.0   # reducción extra del post-filtro en bins de ruido (dB)

        # Post-filtro espectral (ruido musical residual)
        self._post_filter_enabled:  bool  = False
        self._post_filter_strength: float = 1.0

        # Pitch enhancement (SSB)
        self._pitch_enabled:  bool  = False
        self._pitch_strength: float = 0.7
        self._pitch_buf = np.zeros(self._PITCH_BUF_N, dtype=np.float32)
        self._pitch_f0:       float | None = None
        self._pitch_f0_hold:  int = 0   # frames a mantener el último f0 cuando la autocorr falla

        # Estado MCRA
        self._mcra_Sf:        np.ndarray | None = None
        self._mcra_ld:        np.ndarray | None = None
        self._mcra_subs:      np.ndarray | None = None  # (B, nb) subframe minimums
        self._mcra_cur_min:   np.ndarray | None = None
        self._mcra_sub_count: int = 0
        self._mcra_sub_idx:   int = 0
        self._mcra_frames:    int = 0

        # VAD frame-level — tracker lento (OMLSA)
        self._vad_energy_fast:    float | None = None
        self._vad_energy_min:     float | None = None
        # VAD frame-level — tracker rápido (squelch)
        self._vad_energy_fast_sq: float | None = None
        self._vad_energy_min_sq:  float | None = None

    # ------------------------------------------------------------------
    # Control de modo
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode not in ("static", "mcra"):
            return
        self._mode = mode
        self._gain_prev      = None
        self._snr_post_prev  = None
        self._voice_prob     = 0.0
        self._voice_prob_sq  = 0.0
        self._fading_energy_ema = None
        self._mcra_freeze_count = 0
        self._fading_active     = False
        if mode == "mcra":
            self._reset_mcra()

    def _reset_mcra(self) -> None:
        self._mcra_Sf        = None
        self._mcra_ld        = None
        self._mcra_subs      = None
        self._mcra_cur_min   = None
        self._mcra_sub_count = 0
        self._mcra_sub_idx   = 0
        self._mcra_frames         = 0
        self._vad_energy_fast     = None
        self._vad_energy_min      = None
        self._vad_energy_fast_sq  = None
        self._vad_energy_min_sq   = None

    # ------------------------------------------------------------------
    # Control de aprendizaje (modo estático)
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
            # La curva de piso perceptual depende de nb — sin esto, shape mismatch
            # en el Wiener tras cambiar el tamaño de bloque
            self._floor_curve = self._build_floor_curve()
        self._ola_prev        = np.zeros(self._hop, dtype=np.float32)
        self._ola_acc         = np.zeros(self._fft_n, dtype=np.float32)
        self._gain_prev       = None
        self._snr_post_prev   = None
        self._voice_prob         = 0.0
        self._voice_prob_sq      = 0.0
        self._vad_energy_fast    = None
        self._vad_energy_min     = None
        self._vad_energy_fast_sq = None
        self._vad_energy_min_sq  = None
        self._pf_active_frac     = 0.0
        self._pf_extra_db        = 0.0
        self._fading_energy_ema  = None
        self._mcra_freeze_count  = 0
        self._fading_active      = False
        if self._mode == "mcra":
            self._reset_mcra()

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
            self._voice_prob_sq = 0.0
        return self._n_frames

    def clear_profile(self) -> None:
        self._pitch_buf[:]  = 0.0
        self._pitch_f0      = None
        self._pitch_f0_hold = 0
        if self._mode == "mcra":
            self._reset_mcra()
            self._gain_prev     = None
            self._snr_post_prev = None
            self._voice_prob    = 0.0
            self._voice_prob_sq = 0.0
            self._last_reduction_db = 0.0
            self._ola_prev = np.zeros(self._hop,   dtype=np.float32)
            self._ola_acc  = np.zeros(self._fft_n, dtype=np.float32)
            return
        self._is_learning       = False
        self._noise_mag         = None
        self._accum[:]          = 0.0
        self._n_frames          = 0
        self._gain_prev         = None
        self._snr_post_prev     = None
        self._voice_prob        = 0.0
        self._voice_prob_sq     = 0.0
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
        self._floor_curve = self._build_floor_curve()

    def set_smooth(self, smooth: float) -> None:
        self._beta = float(np.clip(smooth, 0.0, 0.99))

    def set_attack(self, attack: float) -> None:
        self._beta_fast = float(np.clip(attack, 0.0, 0.99))

    def set_preview_mode(self, enabled: bool) -> None:
        self._preview_mode = bool(enabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_perceptual_floor_enabled(self, v: bool) -> None:
        self._perceptual_floor_enabled = bool(v)

    def set_pf_boost(self, v: float) -> None:
        self._pf_boost = float(np.clip(v, 0.0, 2.5))
        self._floor_curve = self._build_floor_curve()

    def set_pf_center(self, v: float) -> None:
        self._pf_center = float(np.clip(v, 200.0, 1200.0))
        self._floor_curve = self._build_floor_curve()

    def set_pf_rolloff_hz(self, v: float) -> None:
        self._pf_rolloff_hz = float(np.clip(v, 1000.0, 6000.0))
        self._floor_curve = self._build_floor_curve()

    def set_pf_rolloff_depth(self, v: float) -> None:
        self._pf_rolloff_depth = float(np.clip(v, 0.0, 0.7))
        self._floor_curve = self._build_floor_curve()

    def set_fading_comp(self, v: bool) -> None:
        self._fading_comp = bool(v)
        if not v:
            self._fading_energy_ema = None
            self._mcra_freeze_count = 0
            self._fading_active     = False

    def set_post_filter_enabled(self, v: bool) -> None:
        self._post_filter_enabled = bool(v)

    def set_post_filter_strength(self, v: float) -> None:
        self._post_filter_strength = float(np.clip(v, 0.0, 4.0))

    def set_pitch_enabled(self, v: bool) -> None:
        self._pitch_enabled = bool(v)
        if not v:
            self._pitch_f0      = None
            self._pitch_f0_hold = 0

    def set_pitch_strength(self, v: float) -> None:
        self._pitch_strength = float(np.clip(v, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Piso perceptual — curva de enmascaramiento auditivo por bin
    # ------------------------------------------------------------------

    def _build_floor_curve(self) -> np.ndarray:
        """Curva de piso por bin siguiendo la energía vocal y el enmascaramiento auditivo.

        Multiplica self._floor por un factor que depende de la frecuencia:
          · Pico en ~500 Hz (+75%): zona de fundamentales y primer formante vocal.
            Piso más alto = menos supresión = protege la calidez de la voz.
          · Neutro en 1000–3000 Hz: rango de formantes, floor sin modificar.
          · Rolloff sobre 3 kHz (hasta –55%): energía vocal escasa en AM;
            piso más bajo = más supresión = elimina ruido de alta frecuencia.
        """
        freq_per_bin = 48000.0 / self._fft_n
        freqs = np.arange(self._nb, dtype=np.float64) * freq_per_bin

        # Boost vocal: Gaussiana en escala logarítmica
        safe_f = np.maximum(freqs, 50.0)
        vocal_boost = self._pf_boost * np.exp(
            -0.5 * ((np.log2(safe_f / self._pf_center) / 0.6) ** 2)
        )

        # Rolloff suave por encima de pf_rolloff_hz
        min_rf = 1.0 - self._pf_rolloff_depth
        high_rolloff = np.clip(
            1.0 - self._pf_rolloff_depth * (freqs - self._pf_rolloff_hz) / 6000.0,
            min_rf, 1.0
        )

        multiplier = (1.0 + vocal_boost) * high_rolloff
        return np.clip(multiplier * self._floor, 0.02, 0.60).astype(np.float32)

    # ------------------------------------------------------------------
    # Pitch enhancement — autocorrelación + máscara armónica
    # ------------------------------------------------------------------

    def _detect_pitch(self) -> "float | None":
        """Detecta f0 por autocorrelación normalizada sobre _pitch_buf.
        Retorna Hz si la señal es periódica con confianza ≥ _PITCH_CONF_THR, None si no."""
        x = self._pitch_buf.astype(np.float64)
        x -= x.mean()
        e0 = float(np.dot(x, x))
        if e0 < 1e-8:
            return None

        # Autocorrelación vía FFT (rápida y exacta)
        n    = len(x)
        nfft = 1 << (2 * n - 1).bit_length()
        X    = np.fft.rfft(x, n=nfft)
        acf  = np.fft.irfft(X * np.conj(X))[:n]
        acf /= (acf[0] + 1e-10)

        search   = acf[self._PITCH_LAG_MIN : self._PITCH_LAG_MAX + 1]
        if len(search) == 0:
            return None

        peak_idx = int(np.argmax(search))
        peak_val = float(search[peak_idx])

        if peak_val < self._PITCH_CONF_THR:
            return None

        return 48000.0 / (peak_idx + self._PITCH_LAG_MIN)

    def _harmonic_mask(self, f0: float) -> np.ndarray:
        """Máscara gaussiana centrada en cada armónico de f0 (en bins FFT)."""
        freq_per_bin = 48000.0 / self._fft_n
        mask = np.zeros(self._nb, dtype=np.float32)
        bins = np.arange(self._nb, dtype=np.float32)
        h = 1
        while True:
            center = h * f0 / freq_per_bin
            if center >= self._nb:
                break
            mask += np.exp(-0.5 * ((bins - center) / self._PITCH_SIGMA) ** 2).astype(np.float32)
            h += 1
        return np.minimum(mask, 1.0)

    # ------------------------------------------------------------------
    # MCRA — estimación adaptativa de ruido
    # ------------------------------------------------------------------

    def _mcra_update(self, spec: np.ndarray) -> "np.ndarray | None":
        """Actualiza el estimador MCRA y retorna noise_mag. None durante warmup inicial."""
        power = (np.abs(spec) ** 2 + 1e-12).astype(np.float64)
        self._mcra_frames += 1

        # Inicialización en el primer frame
        if self._mcra_Sf is None:
            self._mcra_Sf      = power.copy()
            self._mcra_ld      = power.copy()
            self._mcra_subs    = np.full((self._MCRA_B, self._nb), np.inf)
            self._mcra_cur_min = power.copy()
            self._mcra_sub_count = 1
            return None

        # Detección de squelch de portadora: si la energía del frame es mucho
        # menor que el piso de ruido estimado, la portadora desapareció.
        # Congelar TODO el estado MCRA para que al volver la señal se retome
        # desde el perfil de ruido memorizado (sin perder el aprendizaje).
        frame_mean = float(np.mean(power))
        noise_mean = float(np.mean(self._mcra_ld))
        if frame_mean < noise_mean * self._MCRA_SQUELCH_RATIO:
            if self._mcra_frames >= self._MCRA_M:
                return np.sqrt(self._mcra_ld).astype(np.float32)
            return None

        # Freeze de fading: no actualizar λ_d durante un evento de fading detectado
        if self._fading_comp and self._mcra_freeze_count > 0 and self._mcra_frames >= self._MCRA_M:
            return np.sqrt(self._mcra_ld).astype(np.float32)

        # 1. Suavizado de potencia espectral
        self._mcra_Sf = (self._MCRA_ALPHA_S * self._mcra_Sf
                         + (1.0 - self._MCRA_ALPHA_S) * power)

        # 2. Seguimiento de mínimos por subtramas
        self._mcra_cur_min = np.minimum(self._mcra_cur_min, self._mcra_Sf)
        self._mcra_sub_count += 1

        if self._mcra_sub_count >= self._MCRA_M:
            self._mcra_subs[self._mcra_sub_idx] = self._mcra_cur_min.copy()
            self._mcra_sub_idx   = (self._mcra_sub_idx + 1) % self._MCRA_B
            self._mcra_cur_min   = self._mcra_Sf.copy()
            self._mcra_sub_count = 0

        # Esperamos al menos una subtrama completa antes de aplicar el Wiener
        if self._mcra_frames < self._MCRA_M:
            self._mcra_ld = 0.95 * self._mcra_ld + 0.05 * power
            return None

        # 3. Mínimo global = min de subtramas ya llenadas + subtrama actual
        S_min = np.minimum(np.min(self._mcra_subs, axis=0), self._mcra_cur_min)
        # Si alguna subtrama aún no tiene datos (inf), usar la actual como fallback
        S_min = np.where(S_min == np.inf, self._mcra_cur_min, S_min)

        # 4. Indicador de presencia de habla por bin
        ratio = self._mcra_Sf / (S_min + 1e-12)
        I_min = (ratio > self._MCRA_DELTA).astype(np.float64)

        # 5. α_d adaptativo: actualiza lento cuando hay habla, rápido en silencio
        alpha_d = self._MCRA_ALPHA_D0 + (1.0 - self._MCRA_ALPHA_D0) * I_min

        # 6. Actualizar estimado de potencia de ruido
        self._mcra_ld = alpha_d * self._mcra_ld + (1.0 - alpha_d) * power

        return np.sqrt(self._mcra_ld).astype(np.float32)

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------

    def process(self, chunk: np.ndarray) -> np.ndarray:
        hop = len(chunk)

        # Buffer rolling para pitch (siempre activo, detección lazy cuando está habilitado)
        self._pitch_buf[:-hop] = self._pitch_buf[hop:]
        self._pitch_buf[-hop:] = chunk

        if self._pitch_enabled:
            f0 = self._detect_pitch()
            if f0 is not None:
                self._pitch_f0      = f0
                self._pitch_f0_hold = 3          # mantener 3 frames ante gaps de detección
            elif self._pitch_f0_hold > 0:
                self._pitch_f0_hold -= 1
                if self._pitch_f0_hold == 0:
                    self._pitch_f0 = None

        # Frame OLA: [bloque anterior | bloque actual]
        frame       = np.empty(self._fft_n, dtype=np.float32)
        frame[:hop] = self._ola_prev
        frame[hop:] = chunk
        self._ola_prev = chunk.copy()

        spec = np.fft.rfft(frame * self._ola_win, n=self._fft_n)

        # Acumulación para perfil estático
        if self._is_learning and self._mode == "static":
            self._accum    += np.abs(spec) ** 2
            self._n_frames += 1

        # Obtener noise_mag según el modo
        # --- Detección de fading HF (antes de MCRA para que el freeze ya esté activo) ---
        if self._fading_comp and self._mode == "mcra":
            frame_e = float(np.mean(np.abs(spec) ** 2))
            if self._fading_energy_ema is None:
                self._fading_energy_ema = frame_e
                self._fading_active = False
            else:
                ema = self._fading_energy_ema
                if ema > 1e-15:
                    change_db = abs(10.0 * np.log10(max(frame_e, 1e-15) / ema))
                    if change_db >= self._FADING_CHANGE_DB:
                        self._mcra_freeze_count = self._FADING_FREEZE_FRAMES
                if self._mcra_freeze_count > 0:
                    self._mcra_freeze_count -= 1
                    self._fading_active = True
                else:
                    self._fading_active = False
                self._fading_energy_ema = (self._FADING_EMA_ALPHA * ema
                                           + (1.0 - self._FADING_EMA_ALPHA) * frame_e)

        if self._mode == "mcra":
            noise_mag = self._mcra_update(spec)
        else:
            noise_mag = self._noise_mag

        if noise_mag is None or not self._enabled:
            out_frame = np.fft.irfft(spec, n=self._fft_n).astype(np.float32) * self._ola_win
        else:
            sig_power   = np.abs(spec).astype(np.float32) ** 2 + 1e-12
            noise_power = noise_mag.astype(np.float32) ** 2 + 1e-12
            noise_prof2 = noise_mag.astype(np.float64) ** 2 + 1e-12

            # --- SNR a posteriori y componente instantánea DD ---
            snr_post = (sig_power / noise_power).astype(np.float32)
            inst     = np.maximum(snr_post - 1.0, 0.0)

            # --- Detector de bins de voz ---
            g_detect  = np.maximum(1.0 - noise_prof2 / sig_power.astype(np.float64),
                                   0.0).astype(np.float32)
            voice_bin = g_detect > self._VAD_THRESHOLD

            # --- VAD frame-level (dual energy minimum tracker) ---
            # Dos trackers paralelos, independientes del estimador de ruido (sin bias MCRA):
            #  - lento (alpha=0.90, TC=100ms): voz suave para OMLSA/beta
            #  - rapido (alpha=0.50, TC=20ms): squelch reactivo
            # Con alpha=0.90, la energia tarda ~60 frames en bajar desde +20dB de voz;
            # con alpha=0.50 baja en ~14 frames (<200ms incluso a +30dB SNR).
            mean_sig        = float(np.mean(sig_power))
            mean_noise_prof = float(np.mean(noise_prof2))
            # Portadora cortada: congelar ambos trackers
            if mean_sig < mean_noise_prof * self._MCRA_SQUELCH_RATIO:
                vp_raw    = 0.0
                vp_raw_sq = 0.0
            else:
                # Tracker lento (OMLSA)
                if self._vad_energy_fast is None:
                    self._vad_energy_fast = mean_sig
                    self._vad_energy_min  = mean_sig
                else:
                    self._vad_energy_fast = (self._VAD_ALPHA_FAST * self._vad_energy_fast
                                             + (1.0 - self._VAD_ALPHA_FAST) * mean_sig)
                    if self._vad_energy_fast < self._vad_energy_min:
                        self._vad_energy_min = self._vad_energy_fast
                    else:
                        self._vad_energy_min *= self._VAD_MIN_DECAY
                vp_raw = float(np.clip(
                    self._vad_energy_fast / (self._vad_energy_min + 1e-30) - 1.0, 0.0, 1.0
                ))
                # Tracker rapido (squelch)
                if self._vad_energy_fast_sq is None:
                    self._vad_energy_fast_sq = mean_sig
                    self._vad_energy_min_sq  = mean_sig
                else:
                    self._vad_energy_fast_sq = (self._VAD_ALPHA_SQ * self._vad_energy_fast_sq
                                                + (1.0 - self._VAD_ALPHA_SQ) * mean_sig)
                    if self._vad_energy_fast_sq < self._vad_energy_min_sq:
                        self._vad_energy_min_sq = self._vad_energy_fast_sq
                    else:
                        self._vad_energy_min_sq *= self._VAD_MIN_DECAY
                vp_raw_sq = float(np.clip(
                    self._vad_energy_fast_sq / (self._vad_energy_min_sq + 1e-30) - 1.0, 0.0, 1.0
                ))

            # Suavizado lento (release=0.97) para OMLSA
            if vp_raw > self._voice_prob:
                self._voice_prob = 0.4 * self._voice_prob + 0.6 * vp_raw
            else:
                self._voice_prob *= 0.97
            self._voice_prob = float(np.clip(self._voice_prob, 0.0, 1.0))

            # Suavizado rapido (release=0.60, ~4 frames) para squelch
            if vp_raw_sq > self._voice_prob_sq:
                self._voice_prob_sq = vp_raw_sq
            else:
                self._voice_prob_sq *= self._VAD_SQ_RELEASE
            self._voice_prob_sq = float(np.clip(self._voice_prob_sq, 0.0, 1.0))

            # --- β efectivo por bin ---
            beta_r        = np.float32(self._beta)
            vp            = np.float32(self._voice_prob)
            beta_fast_eff = np.float32(beta_r * (1.0 - vp) + self._beta_fast * vp)
            # En modo fading comp (solo MCRA), el release es más rápido para seguir
            # la señal al volver del fade
            beta_release  = (np.float32(self._FADING_BETA_RELEASE)
                             if self._fading_comp and self._mode == "mcra"
                             else beta_fast_eff)

            # --- DD SNR a priori ---
            if self._gain_prev is None:
                snr_prior = inst.copy()
            else:
                rising   = snr_post > self._snr_post_prev
                use_fast = rising & voice_bin
                beta_eff = np.where(use_fast, beta_release, beta_r)
                snr_prior = ((1.0 - beta_eff) * inst
                             + beta_eff * self._gain_prev ** 2 * self._snr_post_prev)

            # Piso efectivo: escalar o curva perceptual por bin
            _eff_floor = (self._floor_curve if self._perceptual_floor_enabled
                          else np.float32(self._floor))

            # --- Gain Log-MMSE (Ephraim-Malah 1985) ---
            g_wiener = snr_prior / (snr_prior + 1.0)
            v        = np.maximum(g_wiener * snr_post, 1e-10)
            gain_raw = (g_wiener * np.exp(0.5 * _exp1(v))).astype(np.float32)
            # Medir fraccion de bins retenidos por el piso perceptual
            if self._perceptual_floor_enabled:
                self._pf_active_frac = float(np.mean(gain_raw < _eff_floor))
            gain_dd  = np.clip(gain_raw, _eff_floor, 1.0).astype(np.float32)
            self._gain_prev     = gain_dd
            self._snr_post_prev = snr_post

            # --- OMLSA: anclar bins de ruido al floor ---
            p_speech = np.minimum(g_detect / self._VAD_THRESHOLD, 1.0).astype(np.float32)

            # --- Refuerzo armónico SSB: elevar p_speech en bins de armónicos del f0 ---
            if self._pitch_enabled and self._pitch_f0 is not None:
                hmask    = self._harmonic_mask(self._pitch_f0)
                p_speech = np.maximum(p_speech, hmask * np.float32(self._pitch_strength))

            gain_out = (gain_dd ** p_speech) * (_eff_floor ** (1.0 - p_speech))

            # --- Suavizado de gain en frecuencia ---
            kernel   = np.array([0.25, 0.50, 0.25], dtype=np.float32)
            gain_out = np.convolve(gain_out, kernel, mode='same')
            gain_out = np.maximum(gain_out, _eff_floor).astype(np.float32)

            # Intensidad: gain^alpha → alpha=0 passthrough, alpha=1 reducción plena
            if self._alpha < 1.0:
                gain_out = np.power(gain_out, self._alpha).astype(np.float32)

            # Post-filtro espectral: supresión adicional en bins de ruido residual
            # gain_post[k] = gain[k] ^ (1 + strength * (1 - p_speech[k]))
            # Bins de voz (p_speech=1): sin cambio. Bins de ruido (p_speech=0): gain^(1+strength)
            if self._post_filter_enabled and self._post_filter_strength > 0.0:
                p_noise  = np.float32(1.0) - p_speech
                # Métrica de reducción extra: extra_exp * log(gain) dB, en bins de ruido
                noise_mask = p_speech < 0.3
                if np.any(noise_mask):
                    log_gain_db = 20.0 * np.log10(np.maximum(gain_out[noise_mask], 1e-6))
                    extra_exp   = np.float32(self._post_filter_strength) * p_noise[noise_mask]
                    self._pf_extra_db = float(np.mean(extra_exp * log_gain_db))
                gain_out = np.power(
                    gain_out,
                    np.float32(1.0) + np.float32(self._post_filter_strength) * p_noise,
                ).astype(np.float32)
                # Usar un suelo mínimo bajo (no el _eff_floor) para no anular la supresión extra
                gain_out = np.maximum(gain_out, np.float32(0.005))

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
    def voice_prob_sq(self) -> float:
        """voice_prob con release rápido (~40ms), específico para el gate de squelch."""
        return self._voice_prob_sq

    @property
    def pf_peak_pct(self) -> float:
        """Floor en el bin del centro vocal (fracción 0-1). Indica el piso a la frecuencia de máximo boost."""
        if not self._perceptual_floor_enabled:
            return self._floor
        freq_per_bin = 48000.0 / self._fft_n
        center_bin = min(round(self._pf_center / freq_per_bin), len(self._floor_curve) - 1)
        return float(self._floor_curve[center_bin])

    @property
    def pf_active_frac(self) -> float:
        """Fracción de bins retenidos por el piso perceptual en el último frame procesado."""
        return self._pf_active_frac

    @property
    def pf_extra_db(self) -> float:
        """Reducción extra (dB, ≤0) aplicada por el post-filtro en bins de ruido."""
        return self._pf_extra_db

    @property
    def fading_active(self) -> bool:
        """True si hay un evento de fading activo (MCRA congelado por cambio brusco de energía)."""
        return self._fading_active

    @property
    def pitch_f0(self) -> "float | None":
        """f0 detectado (Hz) por el refuerzo de pitch SSB, o None si no hay detección activa."""
        return self._pitch_f0

    @property
    def has_profile(self) -> bool:
        if self._mode == "mcra":
            return self._mcra_frames >= self._MCRA_M
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
    def mcra_ready(self) -> bool:
        return self._mode == "mcra" and self._mcra_frames >= self._MCRA_M

    @property
    def noise_floor_db(self) -> "np.ndarray | None":
        if self._mode == "mcra":
            if self._mcra_ld is None:
                return None
            mag = np.sqrt(self._mcra_ld).astype(np.float32)
        else:
            if self._noise_mag is None:
                return None
            mag = self._noise_mag
        return (20.0 * np.log10(
            np.maximum(mag, 1e-10) / (self._fft_n / 2.0)
        )).astype(np.float32)

    @property
    def noise_fft_n(self) -> int:
        return self._fft_n
