from collections import deque

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
    _PITCH_EVERY:    int   = 3      # autocorr cada N frames (2 FFTs de 4096 — caro en CPUs
                                    # débiles; el pitch no cambia en 30ms, se cachea)
    _PITCH_SIGMA:    float = 1.5    # sigma (bins) de la máscara gaussiana por armónico

    # Parámetros MCRA
    _MCRA_ALPHA_S:       float = 0.9    # suavizado espectral
    _MCRA_ALPHA_D0:      float = 0.85   # velocidad de actualización del ruido (sin habla)
    _MCRA_DELTA:         float = 1.67   # umbral ratio S_f/S_min para detectar habla
    _MCRA_B:             int   = 4      # número de subtramas
    _MCRA_M:             int   = 20     # frames por subtrama → ventana total = B×M = 80 frames ≈ 800ms
    _MCRA_SQUELCH_RATIO: float = 0.05  # congelar si potencia_frame < 5% del piso estimado (-13 dB)
    # Cuarentena look-behind: λ_d se actualiza con el frame de hace K frames, y solo
    # si ningún frame posterior detectó fade/impulso mientras estaba en cola. Así el
    # onset de un fade (que la detección ve 1-2 frames tarde por el OLA al 50%) se
    # descarta retroactivamente y nunca contamina el estimado. No agrega latencia de
    # audio: solo el estimador consume frames viejos (ya promedia sobre ~800ms).
    _MCRA_QUAR_FRAMES:   int   = 3      # profundidad de la cuarentena (30ms @ hop 480)

    # Compensación de fading HF
    # Detecta cambios bruscos de energía (fading ionosférico) y congela MCRA para que el
    # piso de ruido no siga al nivel de señal. También acelera el release del estimador DD.
    # Umbral de detección y duración del freeze son ajustables por slider (ver setters);
    # estos dos quedan fijos:
    _FADING_EMA_ALPHA:    float = 0.80  # suavizado de energía para detección (TC≈4 frames)
    _FADING_BETA_RELEASE: float = 0.45  # beta DD en modo fading (release más rápido que 0.80)
    _FADING_VP_THR:       float = 0.40  # vp mínimo para congelar: distingue desvanecimiento de
                                        # señal (voz presente → congela) de subida de ruido de
                                        # banda ancha (vp bajo → NO congela, deja seguir el ruido)
    _PS_SMOOTH:           float = 0.6   # suavizado temporal de p_speech por bin (anti-gorgojeo):
                                        # estabiliza la clasificación voz/ruido, fuente del ruido
                                        # musical residual. EMA ~2-3 frames, sin retraso audible.

    # VAD frame-level (energy minimum tracker)
    # Dos trackers paralelos: uno lento (OMLSA) y uno rápido (squelch).
    # El ratio lambda_d/sig_power subestima el ruido ~40% (min-tracking bias),
    # por eso usamos un tracker de energía independiente del estimador.
    _VAD_ALPHA_FAST: float = 0.90   # lento: TC=10 frames (100ms) → voz suave en OMLSA
    _VAD_ALPHA_SQ:   float = 0.50   # rápido: TC=2 frames (20ms) → squelch reactivo
    _VAD_MIN_DECAY:  float = 1.002  # piso mínimo sube 0.2%/frame
    _VAD_SQ_RELEASE: float = 0.60   # release voice_prob_sq: 1.0→0.15 en ~4 frames (≈40ms)
    # Confirmación espectral (peakiness): ratio entre el SNR medio del top 5% de
    # bins y el SNR medio global. Invariante al nivel: el ruido plano (exponencial)
    # da ~4-5 sin importar cuánto suba (ráfagas, release del AGC); la voz concentra
    # energía en armónicos → 8-18. Medido en simulación: ruido p90=5.3, voz débil
    # p90=8.4, voz clara p90=17.6.
    _VAD_PEAK_BASE:  float = 5.5    # ratio donde la confianza empieza a subir
    _VAD_PEAK_SPAN:  float = 4.0    # ratio BASE+SPAN (9.5) → confianza plena
    # Confirmación por periodicidad (autocorrelación, independiente del estimador
    # de ruido — cubre voz sostenida cuando MCRA absorbió los armónicos):
    _VAD_PITCH_BASE: float = 0.25   # confianza de autocorr donde empieza a subir
    _VAD_PITCH_SPAN: float = 0.20   # BASE+SPAN (0.45) → confianza plena
    _VAD_CONF_RELEASE: float = 0.90 # release de la confianza (~100ms): cubre los
                                    # valles entre sílabas sin dejar pasar ruido

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
        # Suavizado de p_speech acoplado al slider Anti-gorgojeo (ver set_smooth):
        # el β temporal (rango 90-99%) tiene poco efecto audible; el suavizado de la
        # clasificación voz/ruido por bin es el que realmente baja el ruido musical.
        self._ps_smooth: float = self._PS_SMOOTH

        # Estado DD inter-frame
        self._gain_prev:     np.ndarray | None = None
        self._snr_post_prev: np.ndarray | None = None
        self._p_speech_prev: np.ndarray | None = None

        # VAD frame-level
        self._voice_prob:    float = 0.0   # suavizado lento (OMLSA)
        self._voice_prob_sq: float = 0.0   # suavizado rápido (squelch)
        self._agc_gain:      float = 1.0   # ganancia lineal del AGC (compensación del VAD)
        self._spec_conf:     float = 0.0   # confianza espectral suavizada (peakiness)
        self._snr_db:        float = 0.0   # S/N banda completa suavizado (indicador, EMA ~1s)

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
        self._pf_rolloff_depth: float = 0.55    # profundidad máxima del rolloff (0–0.95)
        self._floor_curve: np.ndarray = self._build_floor_curve()

        # Refuerzo del piso en agudos (over-sustracción dependiente de frecuencia):
        # multiplica el noise_mag efectivo por encima de ~2.5 kHz. En agudos la
        # energía del ruido es baja y el estimador reacciona tarde a las subidas
        # cíclicas; subir el piso ahí suprime mejor ese ruido, a costa de algo de
        # brillo de la voz. 0 = sin efecto (curva toda en 1.0).
        self._hf_boost:       float      = 0.0
        self._hf_boost_curve: np.ndarray = self._build_hf_boost_curve()

        # Compensación de fading HF
        self._fading_comp:         bool  = False
        self._fading_change_db:    float = 5.0   # umbral de detección (slider, 1-10 dB)
        self._fading_freeze_ms:    float = 200.0 # duración del freeze (slider, 100-500 ms)
        self._fading_freeze_frames: int  = self._calc_fading_freeze_frames()
        self._fading_energy_ema:   float | None = None  # EMA de energía de frame
        self._mcra_freeze_count:   int   = 0    # frames restantes de congelado MCRA
        self._fading_active:       bool  = False # True mientras hay evento de fading
        self._fading_latch:        bool  = False # latch para la UI: True si hubo freeze
                                                 # desde la última lectura (el freeze de
                                                 # ~200ms se pierde entre polls de 500ms)

        # Ventana de seguimiento de mínimos MCRA (ajustable, "Reactividad del piso").
        # Ventana total = B×M frames; M más chico = ventana más corta = el piso reacciona
        # más rápido a subidas de ruido (menos lag → menos vaivén con ruido cíclico).
        self._mcra_window_ms: float = 800.0     # slider 250-800 ms (default = comportamiento previo)
        self._mcra_M:         int   = self._calc_mcra_M()

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
        self._pitch_cache:    "tuple[float | None, float] | None" = None
        self._pitch_countdown: int = 0  # frames hasta la próxima autocorr

        # Estado MCRA
        self._mcra_Sf:        np.ndarray | None = None
        self._mcra_ld:        np.ndarray | None = None
        self._mcra_subs:      np.ndarray | None = None  # (B, nb) subframe minimums
        self._mcra_cur_min:   np.ndarray | None = None
        self._mcra_sub_count: int = 0
        self._mcra_sub_idx:   int = 0
        self._mcra_frames:    int = 0
        self._mcra_quar:      deque = deque()  # cuarentena: [power, contaminado]

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
        self._spec_conf      = 0.0
        self._snr_db         = 0.0
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
        self._mcra_quar.clear()
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
            # Curvas por-bin dependen de nb — sin esto, shape mismatch en el Wiener
            # tras cambiar el tamaño de bloque (invariante 9)
            self._floor_curve = self._build_floor_curve()
            self._hf_boost_curve = self._build_hf_boost_curve()
            # El freeze de fading y la ventana MCRA se expresan en frames — dependen del hop
            self._fading_freeze_frames = self._calc_fading_freeze_frames()
            self._mcra_M = self._calc_mcra_M()
        self._ola_prev        = np.zeros(self._hop, dtype=np.float32)
        self._ola_acc         = np.zeros(self._fft_n, dtype=np.float32)
        self._gain_prev       = None
        self._snr_post_prev   = None
        self._p_speech_prev   = None
        self._voice_prob         = 0.0
        self._voice_prob_sq      = 0.0
        self._spec_conf          = 0.0
        self._snr_db             = 0.0
        self._vad_energy_fast    = None
        self._vad_energy_min     = None
        self._vad_energy_fast_sq = None
        self._vad_energy_min_sq  = None
        self._pf_active_frac     = 0.0
        self._pf_extra_db        = 0.0
        self._pitch_cache        = None
        self._pitch_countdown    = 0
        self._fading_energy_ema  = None
        self._mcra_freeze_count  = 0
        self._fading_active      = False
        self._fading_latch       = False
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
            self._spec_conf     = 0.0
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
            self._spec_conf     = 0.0
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
        self._spec_conf         = 0.0
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
        # El slider Anti-gorgojeo (90-99%) también dosifica el suavizado de p_speech:
        # 0.90 → 0 (sin suavizado, más gorgojeo), 0.99 → 0.85 (máximo). Default
        # 0.97 → ~0.66. Es el mecanismo con efecto audible fuerte.
        pct = float(np.clip((self._beta - 0.90) / 0.09, 0.0, 1.0))
        self._ps_smooth = pct * 0.85

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
        self._pf_rolloff_depth = float(np.clip(v, 0.0, 0.95))   # == max del slider (invariante 1)
        self._floor_curve = self._build_floor_curve()

    def set_fading_comp(self, v: bool) -> None:
        self._fading_comp = bool(v)
        if not v:
            self._fading_energy_ema = None
            self._mcra_freeze_count = 0
            self._fading_active     = False

    def _calc_fading_freeze_frames(self) -> int:
        """Frames de freeze según la duración en ms y el hop actual (48 kHz)."""
        hop_ms = self._hop / 48.0
        return max(1, round(self._fading_freeze_ms / hop_ms))

    def _build_hf_boost_curve(self) -> np.ndarray:
        """Factor de over-sustracción por bin: 1.0 debajo de 2.5 kHz y rampa
        LOGARÍTMICA por encima — cada octava sobre 2.5 kHz suma hf_boost al factor
        (1 octava = 5 kHz → 1+hf_boost; 2 octavas = 10 kHz → 1+2·hf_boost). Así el
        refuerzo crece progresivamente cuanto más alta la frecuencia (donde la
        energía del ruido es menor), sin tope duro dentro de la banda. Cap a 2.5
        octavas (~14 kHz) para acotar cerca de Nyquist. Multiplica noise_mag en el
        cálculo de ganancia → más supresión en agudos."""
        freq_per_bin = 48000.0 / self._fft_n
        freqs = np.arange(self._nb, dtype=np.float64) * freq_per_bin
        octaves = np.clip(np.log2(np.maximum(freqs, 1.0) / 2500.0), 0.0, 2.5)
        return (1.0 + self._hf_boost * octaves).astype(np.float32)

    def set_hf_boost(self, v: float) -> None:
        """Refuerzo del piso en agudos (0 = off, 1.5 = +150% en el tope de la rampa).
        Clamp == rango del slider (0.0-1.5)."""
        self._hf_boost = float(np.clip(v, 0.0, 1.5))
        self._hf_boost_curve = self._build_hf_boost_curve()

    def _calc_mcra_M(self) -> int:
        """Frames por subtrama según la ventana en ms y el hop (48 kHz). La ventana
        total de seguimiento de mínimos es B×M frames; M más chico = ventana más
        corta = el piso reacciona más rápido a las subidas de ruido."""
        hop_ms = self._hop / 48.0
        return max(1, round(self._mcra_window_ms / (self._MCRA_B * hop_ms)))

    def set_mcra_window_ms(self, v: float) -> None:
        """Ventana de seguimiento de mínimos MCRA (Reactividad del piso de ruido).
        Corta (reactivo): sigue subidas rápidas de ruido. Larga (estable): mejor
        para ruido estacionario. Clamp == rango del slider (250-800 ms)."""
        self._mcra_window_ms = float(np.clip(v, 250.0, 800.0))
        self._mcra_M = self._calc_mcra_M()

    def set_agc_gain(self, g: float) -> None:
        """Ganancia lineal actual del AGC (aguas arriba del profiler).
        Los trackers de energía del VAD la descuentan para trabajar a nivel
        de antena: sin esto, el release del AGC tras la voz amplifica el ruido
        de banda y el VAD lo confunde con voz (el gate de squelch no cierra)."""
        self._agc_gain = max(float(g), 1e-6)

    def set_fading_change_db(self, v: float) -> None:
        # Mínimo 1 dB: con 0 el detector (change_db >= umbral, change_db es |Δ| ≥ 0)
        # dispararía en todos los frames → freeze permanente → MCRA nunca actualiza.
        self._fading_change_db = float(np.clip(v, 1.0, 10.0))

    def set_fading_freeze_ms(self, v: float) -> None:
        self._fading_freeze_ms = float(np.clip(v, 100.0, 500.0))
        self._fading_freeze_frames = self._calc_fading_freeze_frames()

    def set_post_filter_enabled(self, v: bool) -> None:
        self._post_filter_enabled = bool(v)

    def set_post_filter_strength(self, v: float) -> None:
        # Clamp == rango del slider de Avanzada Cancelador (invariante 1)
        self._post_filter_strength = float(np.clip(v, 0.0, 10.0))
        if self._post_filter_strength == 0.0:
            self._pf_extra_db = 0.0  # limpiar el indicador aunque no corra process()

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

        # Rolloff suave por encima de pf_rolloff_hz. La rampa alcanza la profundidad
        # plena 2500 Hz por encima del inicio (antes 6000 Hz → dentro de la banda de
        # voz apenas se activaba; el slider era casi inaudible). Con /2500 la
        # profundidad plena cae cerca del borde de banda útil y el slider recupera rango.
        min_rf = 1.0 - self._pf_rolloff_depth
        high_rolloff = np.clip(
            1.0 - self._pf_rolloff_depth * (freqs - self._pf_rolloff_hz) / 2500.0,
            min_rf, 1.0
        )

        multiplier = (1.0 + vocal_boost) * high_rolloff
        return np.clip(multiplier * self._floor, 0.02, 0.60).astype(np.float32)

    # ------------------------------------------------------------------
    # Pitch enhancement — autocorrelación + máscara armónica
    # ------------------------------------------------------------------

    def _pitch_autocorr(self) -> "tuple[float | None, float]":
        """Autocorrelación normalizada sobre _pitch_buf.
        Retorna (f0_Hz, confianza 0-1). f0 es el pico en 80-400 Hz; la confianza
        es el valor del pico (voz periódica ≈ 0.4-0.9, ruido de banda < 0.2)."""
        x = self._pitch_buf.astype(np.float64)
        x -= x.mean()
        e0 = float(np.dot(x, x))
        if e0 < 1e-8:
            return None, 0.0

        # Autocorrelación vía FFT (rápida y exacta)
        n    = len(x)
        nfft = 1 << (2 * n - 1).bit_length()
        X    = np.fft.rfft(x, n=nfft)
        acf  = np.fft.irfft(X * np.conj(X))[:n]
        acf /= (acf[0] + 1e-10)

        search   = acf[self._PITCH_LAG_MIN : self._PITCH_LAG_MAX + 1]
        if len(search) == 0:
            return None, 0.0

        peak_idx = int(np.argmax(search))
        peak_val = float(search[peak_idx])
        return 48000.0 / (peak_idx + self._PITCH_LAG_MIN), peak_val

    def _detect_pitch(self) -> "float | None":
        """f0 en Hz si la señal es periódica con confianza ≥ _PITCH_CONF_THR, None si no."""
        f0, conf = self._pitch_autocorr()
        if f0 is None or conf < self._PITCH_CONF_THR:
            return None
        return f0

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

    def _mcra_current(self) -> "np.ndarray | None":
        """Estimado actual sin actualizar. None si el warmup no terminó."""
        if self._mcra_ld is not None and self._mcra_frames >= self._mcra_M:
            return np.sqrt(self._mcra_ld).astype(np.float32)
        return None

    def _mcra_feed(self, spec: np.ndarray) -> "np.ndarray | None":
        """Encola el frame actual y alimenta MCRA con el frame diferido de la
        cuarentena (K frames atrás), salvo que haya sido marcado como
        contaminado por un fade/impulso detectado después de encolarlo.
        Retorna noise_mag (None durante warmup inicial)."""
        power = (np.abs(spec) ** 2 + 1e-12).astype(np.float64)
        self._mcra_quar.append([power, self._fading_active])
        if len(self._mcra_quar) <= self._MCRA_QUAR_FRAMES:
            return self._mcra_current()
        old_power, contaminated = self._mcra_quar.popleft()
        # Durante el warmup se consume igual (el freeze nunca aplicó en warmup)
        if contaminated and self._mcra_frames >= self._mcra_M:
            return self._mcra_current()
        return self._mcra_update(old_power)

    def _mcra_update(self, power: np.ndarray) -> "np.ndarray | None":
        """Actualiza el estimador MCRA con la potencia espectral de un frame
        (ya diferido por la cuarentena) y retorna noise_mag. None durante warmup."""
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
            if self._mcra_frames >= self._mcra_M:
                return np.sqrt(self._mcra_ld).astype(np.float32)
            return None

        # (El freeze de fading vive en _mcra_feed: los frames encolados durante un
        #  evento — o retroactivamente marcados al detectarlo — no llegan acá.)

        # 1. Suavizado de potencia espectral
        self._mcra_Sf = (self._MCRA_ALPHA_S * self._mcra_Sf
                         + (1.0 - self._MCRA_ALPHA_S) * power)

        # 2. Seguimiento de mínimos por subtramas
        self._mcra_cur_min = np.minimum(self._mcra_cur_min, self._mcra_Sf)
        self._mcra_sub_count += 1

        if self._mcra_sub_count >= self._mcra_M:
            self._mcra_subs[self._mcra_sub_idx] = self._mcra_cur_min.copy()
            self._mcra_sub_idx   = (self._mcra_sub_idx + 1) % self._MCRA_B
            self._mcra_cur_min   = self._mcra_Sf.copy()
            self._mcra_sub_count = 0

        # Esperamos al menos una subtrama completa antes de aplicar el Wiener
        if self._mcra_frames < self._mcra_M:
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

        # Autocorrelación cada _PITCH_EVERY frames (cacheada): la comparten el
        # pitch enhance y la confirmación de periodicidad del VAD
        if self._pitch_countdown <= 0 or self._pitch_cache is None:
            self._pitch_cache = self._pitch_autocorr()
            self._pitch_countdown = self._PITCH_EVERY
        self._pitch_countdown -= 1
        f0_frame, pitch_conf = self._pitch_cache
        if self._pitch_enabled:
            f0 = f0_frame if pitch_conf >= self._PITCH_CONF_THR else None
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
                    # VAD-smart: solo congelar si hay VOZ presente (desvanecimiento de
                    # señal). Una subida/bajada del ruido de banda ancha da vp bajo →
                    # NO congelar, para que el estimador SIGA el ruido en vez de quedar
                    # desfasado (antes congelaba en cada subida de ruido → vaivén).
                    # Usa el vp del frame anterior (la presencia de voz no cambia frame
                    # a frame; el freeze ya trabaja con lag y la cuarentena cubre el onset).
                    if (change_db >= self._fading_change_db
                            and self._voice_prob >= self._FADING_VP_THR):
                        self._mcra_freeze_count = self._fading_freeze_frames
                        # Marcado retroactivo: el onset del fade ya está en la
                        # cuarentena (la detección lo ve 1-2 frames tarde por el
                        # OLA) — que esos frames no actualicen λ_d
                        for item in self._mcra_quar:
                            item[1] = True
                if self._mcra_freeze_count > 0:
                    self._mcra_freeze_count -= 1
                    self._fading_active = True
                    self._fading_latch  = True   # visible para la UI aunque el poll llegue tarde
                else:
                    self._fading_active = False
                self._fading_energy_ema = (self._FADING_EMA_ALPHA * ema
                                           + (1.0 - self._FADING_EMA_ALPHA) * frame_e)

        if self._mode == "mcra":
            noise_mag = self._mcra_feed(spec)
        else:
            noise_mag = self._noise_mag

        # Refuerzo del piso en agudos (over-sustracción): sube el noise_mag efectivo
        # en HF sin tocar el estimado almacenado (crea un array nuevo).
        if noise_mag is not None and self._hf_boost > 0.0:
            noise_mag = noise_mag * self._hf_boost_curve

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
            # S/N para el indicador del espectro. Suavizado asimétrico: ataque
            # rápido (~100ms) y decaimiento lento (~1s) — lee los picos silábicos
            # de la señal sobre el piso, que es el S/N que espera un operador
            # (un EMA simétrico promedia los valles entre sílabas y marca bajo).
            # Nota: el estimado de ruido (min-tracking) subestima ~40% → el S/N
            # sobreestima ~1.5 dB; aceptable para un indicador comparativo.
            snr_inst = 10.0 * np.log10(max(mean_sig / (mean_noise_prof + 1e-30), 1e-6))
            if snr_inst > self._snr_db:
                self._snr_db = 0.90 * self._snr_db + 0.10 * snr_inst
            else:
                self._snr_db = 0.99 * self._snr_db + 0.01 * snr_inst
            # Energía compensada por el AGC (nivel de antena): sin esto, el release
            # del AGC tras la voz amplifica el ruido y los trackers lo toman por voz.
            mean_sig_comp = mean_sig / (self._agc_gain * self._agc_gain)
            # Portadora cortada: congelar ambos trackers
            if mean_sig < mean_noise_prof * self._MCRA_SQUELCH_RATIO:
                vp_raw    = 0.0
                vp_raw_sq = 0.0
            else:
                # Tracker lento (OMLSA)
                if self._vad_energy_fast is None:
                    self._vad_energy_fast = mean_sig_comp
                    self._vad_energy_min  = mean_sig_comp
                else:
                    self._vad_energy_fast = (self._VAD_ALPHA_FAST * self._vad_energy_fast
                                             + (1.0 - self._VAD_ALPHA_FAST) * mean_sig_comp)
                    if self._vad_energy_fast < self._vad_energy_min:
                        self._vad_energy_min = self._vad_energy_fast
                    else:
                        self._vad_energy_min *= self._VAD_MIN_DECAY
                vp_raw = float(np.clip(
                    self._vad_energy_fast / (self._vad_energy_min + 1e-30) - 1.0, 0.0, 1.0
                ))
                # Tracker rapido (squelch)
                if self._vad_energy_fast_sq is None:
                    self._vad_energy_fast_sq = mean_sig_comp
                    self._vad_energy_min_sq  = mean_sig_comp
                else:
                    self._vad_energy_fast_sq = (self._VAD_ALPHA_SQ * self._vad_energy_fast_sq
                                                + (1.0 - self._VAD_ALPHA_SQ) * mean_sig_comp)
                    if self._vad_energy_fast_sq < self._vad_energy_min_sq:
                        self._vad_energy_min_sq = self._vad_energy_fast_sq
                    else:
                        self._vad_energy_min_sq *= self._VAD_MIN_DECAY
                vp_raw_sq = float(np.clip(
                    self._vad_energy_fast_sq / (self._vad_energy_min_sq + 1e-30) - 1.0, 0.0, 1.0
                ))

                # --- Confirmación espectral (peakiness) ---
                # El tracker de energía satura con ratio 2:1 (3 dB): el ruido de
                # banda fluctuante lo lleva a 100% sin estructura de voz. Una
                # ráfaga plana eleva TODOS los bins por igual (el SNR relativo
                # top/media no cambia); la voz concentra energía en armónicos y
                # dispara ese ratio. snr_post ya está normalizado por bin con el
                # estimado de ruido, así que la métrica es invariante al nivel.
                k_top    = max(1, snr_post.size // 20)   # top 5% de bins
                top_mean = float(np.mean(np.partition(snr_post, -k_top)[-k_top:]))
                peak_ratio = top_mean / (float(np.mean(snr_post)) + 1e-12)
                conf_peak  = float(np.clip(
                    (peak_ratio - self._VAD_PEAK_BASE) / self._VAD_PEAK_SPAN, 0.0, 1.0
                ))
                # Periodicidad: inmune a que MCRA absorba los armónicos en voz
                # sostenida (la peakiness se aplana si λ_d aprendió la voz)
                conf_pitch = float(np.clip(
                    (pitch_conf - self._VAD_PITCH_BASE) / self._VAD_PITCH_SPAN, 0.0, 1.0
                ))
                conf_raw = max(conf_peak, conf_pitch)
                # Ataque instantáneo, release ~100ms: cubre los valles entre
                # sílabas (con ruido la confianza cruda es 0 y decae rápido)
                if conf_raw >= self._spec_conf:
                    self._spec_conf = conf_raw
                else:
                    self._spec_conf *= self._VAD_CONF_RELEASE
                vp_raw    *= self._spec_conf
                vp_raw_sq *= self._spec_conf

            # Suavizado lento (release=0.97) para OMLSA
            # >= y no >: con vp_raw == vp (ambos saturados en 1.0 con voz plena),
            # el > estricto aplicaba el release y el vp oscilaba 1.0/0.6 por frame
            if vp_raw >= self._voice_prob:
                self._voice_prob = 0.4 * self._voice_prob + 0.6 * vp_raw
            else:
                self._voice_prob *= 0.97
            self._voice_prob = float(np.clip(self._voice_prob, 0.0, 1.0))

            # Suavizado rapido (release=0.60, ~4 frames) para squelch
            if vp_raw_sq >= self._voice_prob_sq:
                self._voice_prob_sq = vp_raw_sq
            else:
                self._voice_prob_sq *= self._VAD_SQ_RELEASE
            self._voice_prob_sq = float(np.clip(self._voice_prob_sq, 0.0, 1.0))

            # --- β efectivo por bin ---
            beta_r        = np.float32(self._beta)
            vp            = np.float32(self._voice_prob)
            beta_fast_eff = np.float32(beta_r * (1.0 - vp) + self._beta_fast * vp)
            # Release acelerado SOLO durante un evento de fading activo (la
            # recuperación dispara su propia ventana, así que "la voz que vuelve
            # del fade" queda cubierta). Antes aplicaba siempre con el checkbox
            # activo: con mucho ruido y sin fading, los falsos positivos del
            # detector de bins subían con β=0.45 → gorgojeo extra audible.
            beta_release  = (np.float32(self._FADING_BETA_RELEASE)
                             if (self._fading_comp and self._mode == "mcra"
                                 and self._fading_active)
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

            # --- Anti-gorgojeo: suavizado temporal de p_speech por bin ---
            # Un bin que parpadea alrededor del umbral voz/ruido hace saltar su
            # ganancia frame a frame (ruido musical de fondo). El EMA lo estabiliza:
            # los bins de ruido que flickean quedan anclados bajos (→ suprimidos) y
            # la voz sostenida (p_speech≈1) no se toca. Onset de voz: ~2-3 frames.
            if (self._p_speech_prev is None
                    or self._p_speech_prev.shape != p_speech.shape):
                self._p_speech_prev = p_speech
            else:
                p_speech = (self._ps_smooth * self._p_speech_prev
                            + (1.0 - self._ps_smooth) * p_speech).astype(np.float32)
                self._p_speech_prev = p_speech

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
                else:
                    self._pf_extra_db = 0.0
                gain_out = np.power(
                    gain_out,
                    np.float32(1.0) + np.float32(self._post_filter_strength) * p_noise,
                ).astype(np.float32)
                # Usar un suelo mínimo bajo (no el _eff_floor) para no anular la supresión extra
                gain_out = np.maximum(gain_out, np.float32(0.005))
            else:
                # Post-filtro inactivo (checkbox off o agresividad 0): el indicador
                # debe volver a 0 — sin esto queda congelado en el último valor
                # medido (invariante 5: indicadores siempre actualizados)
                self._pf_extra_db = 0.0

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
    def snr_db(self) -> float:
        """S/N banda completa (dB, EMA ~1s) — señal actual vs piso de ruido estimado."""
        return self._snr_db

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

    def pop_fading_active(self) -> bool:
        """Para el indicador FADE de la UI: True si hubo freeze desde la última
        lectura (lee+resetea el latch). Sin esto, un freeze de ~200ms se pierde
        entre polls de 500ms y el indicador parpadea o no aparece. Read+reset sin
        lock a propósito (invariante 7: no vale contención en el hilo de audio por
        un indicador de diagnóstico)."""
        v = self._fading_latch or self._fading_active
        self._fading_latch = False
        return v

    @property
    def pitch_f0(self) -> "float | None":
        """f0 detectado (Hz) por el refuerzo de pitch SSB, o None si no hay detección activa."""
        return self._pitch_f0

    def get_profile(self) -> "dict | None":
        """Perfil estático actual como dict serializable (para guardarlo con
        nombre). None si no hay perfil aprendido."""
        if self._noise_mag is None:
            return None
        return {
            "sample_rate": 48000,
            "fft_n": self._fft_n,
            "learned_frames": self._n_frames,
            "noise_mag": [float(v) for v in self._noise_mag],
        }

    def set_profile(self, data: dict) -> None:
        """Aplica un perfil guardado. Si el fft_n de origen difiere del actual
        (cambió el tamaño de bloque), interpola la curva en frecuencia.
        Resetea el estado DD/VAD igual que al terminar un aprendizaje."""
        mag = np.asarray(data["noise_mag"], dtype=np.float32)
        src_fft_n = int(data.get("fft_n", (len(mag) - 1) * 2))
        if len(mag) != self._nb:
            src_freqs = np.arange(len(mag), dtype=np.float64) * (48000.0 / src_fft_n)
            dst_freqs = np.arange(self._nb, dtype=np.float64) * (48000.0 / self._fft_n)
            mag = np.interp(dst_freqs, src_freqs, mag.astype(np.float64))
            # La magnitud por bin escala con el tamaño de la FFT (misma señal,
            # ventana más larga = más energía por bin): compensar el cambio
            mag = (mag * (self._fft_n / src_fft_n)).astype(np.float32)
        self._noise_mag = mag.astype(np.float32)
        # Duración original expresada en frames del hop actual (para el label)
        src_hop = src_fft_n // 2
        self._n_frames = max(1, round(int(data.get("learned_frames", 0))
                                      * src_hop / self._hop))
        self._is_learning   = False
        self._gain_prev     = None
        self._snr_post_prev = None
        self._voice_prob    = 0.0
        self._voice_prob_sq = 0.0
        self._spec_conf     = 0.0

    @property
    def has_profile(self) -> bool:
        if self._mode == "mcra":
            return self._mcra_frames >= self._mcra_M
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
        return self._mode == "mcra" and self._mcra_frames >= self._mcra_M

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
