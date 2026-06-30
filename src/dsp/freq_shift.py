import numpy as np
from scipy.signal import lfilter


class FrequencyShifter:
    """
    Corrección de tono SSB: desplaza uniformemente todas las frecuencias por Δf Hz.

    Uso típico en radio SSB: si el BFO está 100 Hz alto, la voz suena aguda.
    Aplicar Δf = -100 Hz restaura el tono natural.

    Algoritmo (heterodino en banda base):
        x_shift[n] = x_delayed[n]·cos(θ[n]) − Q[n]·sin(θ[n])
        θ[n] = 2π·Δf·n/sr  (fase continua entre bloques vía acumulador)
        Q[n] = filtro FIR Hilbert de x (cuadratura, delay = 31 muestras)
        x_delayed[n] = x[n-31] (compensa el delay de la cuadratura)

    La rama coseno pasa la señal directa y la rama seno pasa su cuadratura.
    La suma cancela la banda imagen y preserva solo la banda deseada (SSB puro).

    Latencia: 31 muestras ≈ 0.65 ms. Bypass (shift=0 Hz) mantiene este delay
    para no introducir saltos al habilitar/deshabilitar.
    """

    _FIR_LEN = 63  # tap count; delay = (63-1)/2 = 31 muestras

    def __init__(self, sample_rate: int = 48000):
        self._sr       = sample_rate
        self._shift_hz = 0.0
        self._phase    = 0.0   # acumulador de fase continuo entre bloques

        # FIR Hilbert transformer: h[n] = 2/(π·n) para n impar, 0 para n par
        N  = self._FIR_LEN
        ns = np.arange(N, dtype=np.float64) - (N - 1) // 2  # centrado: [-31..31]
        ns_safe = np.where(ns == 0, 1.0, ns)  # evitar div-por-cero en n=0
        h = np.where((ns == 0) | (ns % 2 == 0), 0.0, 2.0 / (np.pi * ns_safe))
        h *= np.blackman(N)   # ventana Blackman: supresión de banda ≈ 74 dB
        self._h_fir = h.astype(np.float64)
        self._zi    = np.zeros(N - 1, dtype=np.float64)

        # Buffer de delay para la rama real (compensa los 31 muestras del FIR)
        D = (N - 1) // 2   # = 31
        self._delay    = D
        self._real_buf = np.zeros(D, dtype=np.float32)

    # ------------------------------------------------------------------
    # Parámetros
    # ------------------------------------------------------------------

    def set_shift_hz(self, hz: float) -> None:
        """Δf en Hz. Positivo = voz más aguda, negativo = más grave. Rango ±500 Hz."""
        self._shift_hz = float(np.clip(hz, -500.0, 500.0))

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------

    def process(self, chunk: np.ndarray) -> np.ndarray:
        H = len(chunk)
        D = self._delay
        x = chunk.astype(np.float64)

        # Rama cuadratura: FIR Hilbert (delay D muestras integrado en el filtro)
        quadrature, self._zi = lfilter(self._h_fir, [1.0], x, zi=self._zi)

        # Rama real: compensar el mismo delay D
        delayed        = np.empty(H, dtype=np.float64)
        delayed[:D]    = self._real_buf
        delayed[D:]    = chunk[:H - D]
        self._real_buf = chunk[H - D:].copy().astype(np.float32)

        if abs(self._shift_hz) < 0.5:
            return delayed.astype(np.float32)

        # Oscilador con fase continua entre bloques (evita clicks en fronteras)
        phase_arr   = self._phase + 2.0 * np.pi * self._shift_hz / self._sr * np.arange(H)
        self._phase = (phase_arr[-1] + 2.0 * np.pi * self._shift_hz / self._sr) % (2.0 * np.pi)

        # SSB heterodino: Re{(x + j·Q) · e^{jθ}} = x·cos(θ) − Q·sin(θ)
        shifted = delayed * np.cos(phase_arr) - quadrature * np.sin(phase_arr)
        return shifted.astype(np.float32)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._zi[:]       = 0.0
        self._real_buf[:] = 0.0
        self._phase       = 0.0
