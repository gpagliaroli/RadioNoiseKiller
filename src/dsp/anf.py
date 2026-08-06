import numpy as np
from scipy.ndimage import median_filter as _mf


class AdaptiveNotchFilter:
    """
    Filtro de muesca espectral para cancelación de tonos e interferencias
    periódicas (heterodinos, portadoras de AM, armónicos de red).

    Mejoras vs. versión anterior:
      - Overlap-Add (OLA) con ventana sqrt-Hann al 50%: elimina el raspado
        a 100 Hz causado por discontinuidades en los bordes de bloque.
      - Suavizado temporal de ganancias: transiciones suaves cuando un tono
        entra o sale → sin clics al detectar/perder un heterodino.

    Principio de detección:
      baseline[k] = mediana de los kernel_size bins vecinos de k
      is_tone[k]  = mag[k] > threshold × baseline[k]
      La voz broadband y el ruido NO destacan sobre la mediana local.

    OLA: cada chunk de H muestras se analiza en un frame de 2H muestras
    ([chunk_anterior | chunk_actual]), con ventana sqrt-Hann. La salida
    es la superposición del frame anterior (segundo mitad) con el frame
    actual (primera mitad). Introduce 1 hop (10 ms) de latencia.
    """

    def __init__(self, sample_rate: int = 48000,
                 threshold: float = 3.0,
                 depth: float = 0.9,
                 kernel_size: int = 15):
        self._sample_rate = int(sample_rate)
        self._threshold   = float(np.clip(threshold, 1.1, 30.0))
        self._depth       = float(np.clip(depth, 0.0, 1.0))
        self._kernel_size = max(3, int(kernel_size) | 1)
        self._enabled     = False
        self._smooth_coef: float = 0.80  # suavizado temporal inter-frame

        # Estado OLA — inicializado en primer uso
        self._hop:      int = 0
        self._ola_prev: np.ndarray = np.zeros(0, dtype=np.float32)
        self._ola_acc:  np.ndarray = np.zeros(0, dtype=np.float32)
        self._ola_win:  np.ndarray = np.zeros(0, dtype=np.float32)
        self._smooth_gains: np.ndarray | None = None
        self._last_notched_bins: int = 0
        self._last_tone_freqs: "np.ndarray | None" = None

    def _init_ola(self, hop: int) -> None:
        self._hop      = hop
        self._ola_prev = np.zeros(hop, dtype=np.float32)
        self._ola_acc  = np.zeros(2 * hop, dtype=np.float32)
        # sqrt-Hann: satisface COLA al 50% de solapamiento
        self._ola_win  = np.sqrt(np.hanning(2 * hop)).astype(np.float32)
        self._smooth_gains = None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def reset(self) -> None:
        if self._hop:
            self._ola_prev[:] = 0.0
            self._ola_acc[:]  = 0.0
        self._smooth_gains = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_threshold(self, threshold: float) -> None:
        self._threshold = float(np.clip(threshold, 1.1, 30.0))

    def set_depth(self, depth: float) -> None:
        self._depth = float(np.clip(depth, 0.0, 1.0))

    def set_kernel_size(self, size: int) -> None:
        self._kernel_size = max(3, int(size) | 1)

    # ------------------------------------------------------------------
    # Procesamiento — OLA 50% con suavizado temporal de ganancias
    # ------------------------------------------------------------------

    def process(self, chunk: np.ndarray) -> np.ndarray:
        hop = len(chunk)
        if hop != self._hop:
            self._init_ola(hop)

        # Frame de análisis: [bloque anterior | bloque actual]
        frame = np.empty(2 * hop, dtype=np.float32)
        frame[:hop] = self._ola_prev
        frame[hop:] = chunk
        self._ola_prev = chunk.copy()

        # FFT del frame con ventana de análisis
        spec = np.fft.rfft(frame * self._ola_win)

        if self._enabled:
            mag = np.abs(spec)
            baseline = _mf(mag, size=self._kernel_size)
            is_tone  = mag > self._threshold * (baseline + 1e-12)

            self._last_notched_bins = int(np.sum(is_tone))
            # Frecuencias de los tonos, para el marcador de la cascada. Se
            # rebindea un array nuevo (no se muta el anterior): la UI lo lee sin
            # lock y en el peor caso ve el frame previo — material de diagnostico
            # (misma decision que pop_blanker_hits, invariante 7).
            idx = np.flatnonzero(is_tone)
            self._last_tone_freqs = (idx * (self._sample_rate / (2.0 * self._hop))
                                     ).astype(np.float32)
            gain_inst = np.where(
                is_tone,
                (1.0 - self._depth) + self._depth * baseline / (mag + 1e-12),
                1.0,
            ).astype(np.float32)

            # Suavizado temporal: previene cambios bruscos entre frames
            if self._smooth_gains is None or len(self._smooth_gains) != len(spec):
                self._smooth_gains = gain_inst.copy()
            else:
                c = self._smooth_coef
                self._smooth_gains = (c * self._smooth_gains
                                      + (1.0 - c) * gain_inst).astype(np.float32)

            spec_out = (self._smooth_gains * spec).astype(np.complex64)
        else:
            spec_out = spec  # bypass: reconstrucción perfecta vía OLA

        # IFFT + ventana de síntesis (= ventana de análisis para sqrt-Hann)
        out_frame = (np.fft.irfft(spec_out, n=2 * hop).astype(np.float32)
                     * self._ola_win)

        # Overlap-Add: primero acumular, luego extraer, luego desplazar
        self._ola_acc      += out_frame
        result              = self._ola_acc[:hop].copy()
        self._ola_acc[:hop] = self._ola_acc[hop:]
        self._ola_acc[hop:] = 0.0

        return result

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def notched_bins(self) -> int:
        return self._last_notched_bins

    @property
    def tone_freqs(self) -> "np.ndarray | None":
        """Frecuencias (Hz) de los tonos cancelados en el ultimo frame, o None si
        el ANF esta desactivado. Lo usa el marcador de heterodinos de la cascada."""
        return self._last_tone_freqs if self._enabled else None
