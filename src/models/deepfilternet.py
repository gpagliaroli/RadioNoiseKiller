import numpy as np
import onnxruntime as ort
from config import ModelConfig
from utils import resource_path


class DeepFilterNet3:
    """
    Wrapper para inferencia en tiempo real con DeepFilterNet3 via ONNX Runtime.

    Estrategia de streaming: acumulamos window_frames frames en un ring buffer,
    procesamos la ventana completa y emitimos el audio del primer frame.
    Latencia resultante: (window_frames + lookahead) × hop_size / sr

    Cadena de procesamiento por frame:
      1. ERB mask  → ganancia espectral sobre todos los bins (reducción de ruido global)
      2. Deep filter → FIR complejo sobre los primeros nb_df bins (voz, más preciso)
         Fórmula: Y_DF(k,f) = Σ_{d=0}^{D-1} c(k,d,f) · X(k-d+LOOKAHEAD, f)
         — el filtro usa LOOKAHEAD frames futuros del espectro original sin enmascarar
    """

    LOOKAHEAD = 2

    # Umbrales LSNR para gating de decoders (mismos que libDF original)
    _LSNR_MIN = -10.0   # por debajo: no aplicar DF (señal demasiado débil)
    _LSNR_MAX =  20.0   # por encima: señal limpia, DF puede omitirse

    def __init__(self, config: ModelConfig):
        self._cfg = config
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._enc     = ort.InferenceSession(resource_path(config.enc_path),     sess_options=opts)
        self._erb_dec = ort.InferenceSession(resource_path(config.erb_dec_path), sess_options=opts)
        self._df_dec  = ort.InferenceSession(resource_path(config.df_dec_path),  sess_options=opts)

        self._fft_size      = config.fft_size
        self._hop           = config.hop_size
        self._nb_erb        = config.nb_erb
        self._nb_df         = config.nb_df
        self._df_order      = config.df_order
        self._window_frames = config.window_frames
        self._sr            = 48000

        # Ventana de análisis Hann (igual que entrenamiento)
        self._win_analysis = np.hanning(self._fft_size).astype(np.float32)

        # Ventana de síntesis normalizada para OLA con 50 % de solapamiento
        ola_factor = np.sum(self._win_analysis ** 2) / self._hop   # ≈ 0.75 para Hann
        self._win_synthesis = (self._win_analysis / ola_factor).astype(np.float32)

        self._erb_filters = self._build_erb_filters()
        # _erb_band[k] = índice de banda ERB del bin lineal k (para reconstrucción de máscara)
        self._erb_band = np.argmax(self._erb_filters, axis=1)

        # Buffer de entrada (muestras)
        n_total        = (self._window_frames + self.LOOKAHEAD) * self._hop
        self._in_buf   = np.zeros(n_total, dtype=np.float32)
        # Buffer OLA: carry de la segunda mitad del frame anterior
        self._out_buf  = np.zeros(self._fft_size, dtype=np.float32)
        # Historial espectral para el deep filter (df_order frames previos de spec[0])
        self._df_hist  = np.zeros((self._df_order, self._nb_df), dtype=np.complex64)

        self._frames_ready   = 0
        self._attenuation    = config.attenuation_limit
        self._mask_exp:    float = config.mask_exp
        self._mask_floor:  float = config.mask_floor
        self._mask_smooth: float = config.mask_smooth

        # Máscara previa para suavizado temporal inter-frame
        self._prev_mask_lin = np.ones(self._fft_size // 2 + 1, dtype=np.float32)
        # VAD: probabilidad suavizada de presencia de voz (0=ruido, 1=voz)
        self._vad_smooth: float = 0.0

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_attenuation(self, db: float) -> None:
        self._attenuation = db

    def set_mask_exp(self, exp: float) -> None:
        self._mask_exp = float(max(0.5, min(5.0, exp)))

    def set_mask_floor(self, floor: float) -> None:
        self._mask_floor = float(max(0.0, min(0.5, floor)))

    def set_mask_smooth(self, smooth: float) -> None:
        self._mask_smooth = float(max(0.0, min(0.95, smooth)))

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def set_window_frames(self, window_frames: int) -> None:
        """Redimensiona el buffer de entrada para el nuevo window_frames y resetea el estado."""
        if window_frames == self._window_frames:
            self._reset_buffers()
            return
        self._window_frames = window_frames
        n_total = (window_frames + self.LOOKAHEAD) * self._hop
        self._in_buf = np.zeros(n_total, dtype=np.float32)
        self._out_buf = np.zeros(self._fft_size, dtype=np.float32)
        self._df_hist = np.zeros((self._df_order, self._nb_df), dtype=np.complex64)
        self._prev_mask_lin = np.ones(self._fft_size // 2 + 1, dtype=np.float32)
        self._frames_ready = 0
        self._vad_smooth = 0.0

    def warmup(self) -> None:
        rng = np.random.default_rng(0)
        n = self._window_frames + self.LOOKAHEAD + 2
        for _ in range(n):
            self.process_frame(rng.standard_normal(self._hop).astype(np.float32) * 0.01)
        self._reset_buffers()

    def _reset_buffers(self) -> None:
        self._in_buf[:]        = 0.0
        self._out_buf[:]       = 0.0
        self._df_hist[:]       = 0.0
        self._prev_mask_lin[:] = 1.0
        self._frames_ready     = 0
        self._vad_smooth       = 0.0

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    def process_frame(self, samples: np.ndarray) -> np.ndarray:
        hop = self._hop
        self._in_buf = np.roll(self._in_buf, -hop)
        self._in_buf[-hop:] = samples[:hop]
        self._frames_ready = min(self._frames_ready + 1, self._window_frames + self.LOOKAHEAD)

        if self._frames_ready < self._window_frames + self.LOOKAHEAD:
            return np.zeros(hop, dtype=np.float32)

        return self._run_inference()

    # ------------------------------------------------------------------
    # Inferencia
    # ------------------------------------------------------------------

    def _run_inference(self) -> np.ndarray:
        hop      = self._hop
        n_frames = self._window_frames + self.LOOKAHEAD
        audio    = self._in_buf.copy()

        # STFT frame a frame (ventana de análisis Hann)
        spec_frames = []
        for i in range(n_frames):
            start   = i * hop
            segment = audio[start: start + self._fft_size]
            if len(segment) < self._fft_size:
                segment = np.pad(segment, (0, self._fft_size - len(segment)))
            spec_frames.append(np.fft.rfft(segment * self._win_analysis))

        spec = np.array(spec_frames, dtype=np.complex64)  # (n_frames, 481)

        feat_erb, feat_spec = self._extract_features(spec)

        # Encoder
        e0, e1, e2, e3, emb, c0, lsnr = self._enc.run(None, {
            "feat_erb":  feat_erb,
            "feat_spec": feat_spec,
        })

        # lsnr del frame que emitimos (frame 0 = más antiguo en el buffer)
        lsnr_frame0 = float(lsnr[0, 0, 0])

        # ERB decoder → máscara de ganancia espectral
        mask_erb = self._erb_dec.run(None, {
            "emb": emb, "e3": e3, "e2": e2, "e1": e1, "e0": e0,
        })[0]   # (1, 1, n_frames, nb_erb)

        # DF decoder → coeficientes FIR complejos + alpha (blend DF/ERB por frame)
        df_out   = self._df_dec.run(None, {"emb": emb, "c0": c0})
        coefs    = df_out[0]   # (1, n_frames, nb_df, 10)  — packed complex (re,im×5)
        df_alpha = df_out[1]   # (1, n_frames, 1)           — blend factor sigmoid ≈ 0..1

        f0, pitch_conf = self._estimate_pitch(audio)
        enhanced = self._apply_mask_and_df(spec, mask_erb, coefs, df_alpha, lsnr_frame0, f0, pitch_conf)

        # ISTFT del frame emitido (frame 0) + OLA
        reconstructed = np.fft.irfft(enhanced[0], n=self._fft_size)
        windowed_out  = (reconstructed * self._win_synthesis).astype(np.float32)

        output              = self._out_buf[:hop] + windowed_out[:hop]
        self._out_buf[:hop] = windowed_out[hop:]

        return output

    # ------------------------------------------------------------------
    # Procesamiento espectral
    # ------------------------------------------------------------------

    def _extract_features(self, spec: np.ndarray):
        mag     = np.abs(spec)
        erb_log = np.log1p(mag @ self._erb_filters).astype(np.float32)

        spec_df = spec[:, :self._nb_df]
        spec_ri = np.stack([spec_df.real, spec_df.imag], axis=0)

        feat_erb  = erb_log[np.newaxis, np.newaxis, :, :]  # (1,1,S,32)
        feat_spec = spec_ri[np.newaxis, :, :, :]            # (1,2,S,96)
        return feat_erb, feat_spec

    def _apply_mask_and_df(self, spec, mask_erb, coefs, df_alpha, lsnr_frame0: float,
                           f0: float = 0.0, pitch_conf: float = 0.0):
        nb_df    = self._nb_df
        df_order = self._df_order
        L        = self.LOOKAHEAD
        nb_bins  = self._fft_size // 2 + 1

        # --- ERB mask → ganancia espectral ---
        mask        = mask_erb[0, 0, :, :]          # (n_frames, nb_erb)
        mask_linear = mask[:, self._erb_band]        # (n_frames, 481) — asignación directa de banda
        mask_linear = np.clip(mask_linear, 0.0, 1.0)

        if self._mask_exp != 1.0:
            mask_linear = mask_linear ** self._mask_exp

        # --- Pitch-aware mask floor ---
        # Bins armónicos protegidos con floor alto; el resto con floor reducido.
        if f0 > 0.0 and pitch_conf >= 0.35:
            floor = np.full(nb_bins, self._mask_floor * 0.5, dtype=np.float32)
            harmonic_floor = float(np.clip(self._mask_floor * 8.0, self._mask_floor, 0.3))
            bins_per_hz = self._fft_size / self._sr
            for k in range(1, 25):
                f_h = f0 * k
                if f_h > self._sr / 2:
                    break
                b = round(f_h * bins_per_hz)
                for b2 in range(max(0, b - 1), min(nb_bins, b + 2)):
                    floor[b2] = harmonic_floor
        else:
            floor = self._mask_floor

        mask_linear = np.maximum(mask_linear, floor)

        # --- VAD adaptativo basado en LSNR ---
        # Sigmoid centrada en −5 dB: convierte LSNR en probabilidad de voz (0–1)
        voice_prob = 1.0 / (1.0 + np.exp(-0.4 * (lsnr_frame0 + 5.0)))
        # Ataque rápido (voz detectada en ~3 frames), release lento (~65 frames = 650 ms)
        alpha_vad = 0.35 if voice_prob > self._vad_smooth else 0.015
        self._vad_smooth = alpha_vad * voice_prob + (1.0 - alpha_vad) * self._vad_smooth
        vad_scale = float(np.clip(self._vad_smooth / 0.25, 0.0, 1.0))

        # --- Suavizado temporal inter-frame (solo frame 0 = el que emitimos) ---
        alpha_s = self._mask_smooth
        if alpha_s > 0.0:
            mask_linear[0] = alpha_s * self._prev_mask_lin + (1.0 - alpha_s) * mask_linear[0]
        # _prev_mask_lin se guarda ANTES de aplicar VAD para que la recuperación
        # de voz arranque desde el nivel del modelo, no desde cero
        self._prev_mask_lin = mask_linear[0].copy()

        # Escalar máscara hacia cero durante silencios de banda
        if vad_scale < 1.0:
            mask_linear[0] = mask_linear[0] * vad_scale

        enhanced = (spec * mask_linear).astype(np.complex64)

        # --- Deep filter (solo si el SNR justifica aplicarlo) ---
        # lsnr < _LSNR_MIN: frame de ruido puro → coefs inestables, preservar ERB
        # lsnr > _LSNR_MAX: señal ya limpia, DF no aporta
        if self._LSNR_MIN <= lsnr_frame0:
            raw = coefs[0, 0]      # (nb_df, 10) — coefs para frame 0
            D   = raw.shape[-1]

            # Desempaquetar coefs complejos: [re0,im0,re1,im1,...] → complex (nb_df, df_order)
            if D == df_order * 2:
                c = raw[:, 0::2].astype(np.complex64) + 1j * raw[:, 1::2].astype(np.complex64)
            else:
                c = raw.astype(np.complex64)

            # Armar vector de frames para el FIR con lookahead correcto:
            # tap d=0 → spec[L]   (2 frames adelante del frame emitido)
            # tap d=1 → spec[L-1] (1 frame adelante)
            # tap d=2 → spec[0]   (el frame que emitimos)
            # tap d=3 → df_hist[0] (frame anterior)
            # tap d=4 → df_hist[1] (2 frames atrás)
            past = np.empty((df_order, nb_df), dtype=np.complex64)
            for d in range(df_order):
                fi = L - d   # índice de frame: 2,1,0,−1,−2
                if fi >= 0:
                    past[d] = spec[fi, :nb_df]
                else:
                    past[d] = self._df_hist[-fi - 1]

            # Y_DF[k] = Σ_d c[k,d] * past[d,k]
            enhanced_df = np.sum(c * past.T, axis=1)  # (nb_df,)

            # Restricción de amplitud: el DF no debe superar el espectro original
            input_mag   = np.abs(spec[0, :nb_df])
            df_mag      = np.abs(enhanced_df) + 1e-12
            enhanced_df = np.where(df_mag > input_mag,
                                   enhanced_df * (input_mag / df_mag),
                                   enhanced_df)

            # Blend usando el alpha del modelo (≈0.5, entrenado para calibrar DF vs ERB)
            alpha_df   = float(df_alpha[0, 0, 0])
            erb_frame0 = enhanced[0, :nb_df].copy()
            enhanced[0, :nb_df] = (alpha_df * enhanced_df +
                                   (1.0 - alpha_df) * erb_frame0).astype(np.complex64)

        # Actualizar historial (siempre, incluso cuando se omite el DF)
        self._df_hist = np.roll(self._df_hist, 1, axis=0)
        self._df_hist[0] = spec[0, :nb_df]

        return enhanced

    # ------------------------------------------------------------------
    # Pitch detection (autocorrelación FFT sobre el último hop)
    # ------------------------------------------------------------------

    def _estimate_pitch(self, audio: np.ndarray) -> tuple[float, float]:
        """Retorna (f0_hz, confidence). f0=0 si no se detecta pitch claro."""
        frame = audio[-self._hop:].astype(np.float64)
        frame -= frame.mean()
        peak = np.max(np.abs(frame))
        if peak < 1e-6:
            return 0.0, 0.0

        frame /= peak
        N = len(frame)

        # Autocorrelación vía FFT: O(N log N) en vez de O(N²)
        F = np.fft.rfft(frame, n=2 * N)
        corr = np.fft.irfft(F * np.conj(F))[:N]
        corr /= corr[0] + 1e-12

        # Buscar en rango de pitch vocal: 80–400 Hz
        lag_min = int(self._sr / 400)   # 120 muestras @ 48kHz
        lag_max = int(self._sr / 80)    # 600 muestras @ 48kHz
        if lag_max >= N:
            return 0.0, 0.0

        best_lag = lag_min + int(np.argmax(corr[lag_min:lag_max]))
        confidence = float(corr[best_lag])
        if confidence < 0.35:
            return 0.0, 0.0

        return float(self._sr / best_lag), confidence

    # ------------------------------------------------------------------
    # Banco de filtros ERB  (Slaney 1993 — igual que entrenamiento DeepFilterNet3)
    # ------------------------------------------------------------------

    def _build_erb_filters(self) -> np.ndarray:
        nb_bins = self._fft_size // 2 + 1   # 481
        nb_erb  = self._nb_erb               # 32
        freqs   = np.linspace(0, self._sr / 2, nb_bins)

        def hz2erb(f):
            return 9.265 * np.log(1.0 + np.asarray(f, np.float64) / 228.8455)

        def erb2hz(e):
            return 228.8455 * (np.exp(np.asarray(e, np.float64) / 9.265) - 1.0)

        erb_edges          = np.linspace(hz2erb(0.0), hz2erb(self._sr / 2.0), nb_erb + 1)
        hz_edges           = erb2hz(erb_edges)
        hz_edges[-1]      += 1.0   # asegurar inclusión del bin de Nyquist

        filters = np.zeros((nb_bins, nb_erb), dtype=np.float32)
        for i in range(nb_erb):
            mask = (freqs >= hz_edges[i]) & (freqs < hz_edges[i + 1])
            cnt  = mask.sum()
            if cnt > 0:
                filters[mask, i] = 1.0 / cnt

        return filters
