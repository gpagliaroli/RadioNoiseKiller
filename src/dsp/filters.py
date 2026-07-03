"""
dsp.filters — filtros bandpass por modo de radio.

Usa filtros Butterworth IIR en formato Second-Order Sections (SOS) para baja latencia
y estabilidad numérica. El estado del filtro (zi) se mantiene entre frames para
garantizar continuidad en la señal procesada.
"""
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi, lfilter
from config import DSPConfig, RadioMode


class BandpassFilter:
    """
    Filtro Butterworth IIR en modo sos para baja latencia.
    Mantiene el estado entre frames para procesamiento continuo.
    """

    def __init__(self, config: DSPConfig, sample_rate: int = 48000):
        self._sr = sample_rate
        self._config = config
        self._sos: np.ndarray | None = None
        self._zi: np.ndarray | None = None
        self._set_mode(config.mode)

    def set_mode(self, mode: RadioMode) -> None:
        self._config.mode = mode
        self._set_mode(mode)

    def set_limits(self, mode: RadioMode, lo: int, hi: int) -> None:
        self._config.bandpass_limits[mode] = (lo, hi)
        if self._config.mode == mode:
            self._set_mode(mode)

    def set_order(self, order: int) -> None:
        self._config.filter_order = order
        self._set_mode(self._config.mode)

    def _set_mode(self, mode: RadioMode) -> None:
        lo, hi = self._config.bandpass_limits[mode]
        nyq = self._sr / 2.0
        self._sos = butter(
            self._config.filter_order,
            [lo / nyq, hi / nyq],
            btype="bandpass",
            output="sos",
        )
        self._zi = sosfilt_zi(self._sos) * 0.0  # estado inicial en cero

    def process(self, audio: np.ndarray) -> np.ndarray:
        out, self._zi = sosfilt(self._sos, audio, zi=self._zi)
        return out.astype(np.float32)

    def reset(self) -> None:
        if self._sos is not None:
            self._zi = sosfilt_zi(self._sos) * 0.0


class PresenceFilter:
    """
    Filtro ecualizador de pico (peaking EQ) para resaltar la banda de presencia de voz.
    Implementado como biquad IIR estacionario (Audio EQ Cookbook).

    Centro por defecto: 2000 Hz — rango crítico para inteligibilidad en radio.
    Q = 0.9 → ancho de banda ~1.4 octavas, suave para voz.
    """

    def __init__(self, sample_rate: int, freq_hz: float = 2000.0, q: float = 0.7):
        self._sr      = sample_rate
        self._freq_hz = freq_hz
        self._q       = q
        self._gain_db = 0.0
        self._b       = np.array([1.0, 0.0, 0.0])
        self._a       = np.array([1.0, 0.0, 0.0])
        self._zi      = np.zeros(2)

    def set_gain_db(self, gain_db: float) -> None:
        gain_db = float(np.clip(gain_db, -12.0, 12.0))
        if abs(gain_db - self._gain_db) < 0.02:
            return
        self._gain_db = gain_db
        self._update_coeffs()

    def set_q(self, q: float) -> None:
        self._q = float(np.clip(q, 0.2, 4.0))
        self._update_coeffs()

    def set_freq(self, freq_hz: float) -> None:
        freq_hz = float(np.clip(freq_hz, 100.0, 8000.0))
        if abs(freq_hz - self._freq_hz) < 1.0:
            return
        self._freq_hz = freq_hz
        self._update_coeffs()

    def _update_coeffs(self) -> None:
        if abs(self._gain_db) < 0.05:
            self._b = np.array([1.0, 0.0, 0.0])
            self._a = np.array([1.0, 0.0, 0.0])
            return

        w0    = 2.0 * np.pi * self._freq_hz / self._sr
        A     = 10.0 ** (self._gain_db / 40.0)
        alpha = np.sin(w0) / (2.0 * self._q)

        a0 = 1.0 + alpha / A
        self._b = np.array([
            (1.0 + alpha * A) / a0,
            (-2.0 * np.cos(w0)) / a0,
            (1.0 - alpha * A) / a0,
        ])
        self._a = np.array([
            1.0,
            (-2.0 * np.cos(w0)) / a0,
            (1.0 - alpha / A) / a0,
        ])
        self._zi = np.zeros(2)

    def process(self, samples: np.ndarray) -> np.ndarray:
        if abs(self._gain_db) < 0.05:
            return samples
        out, self._zi = lfilter(self._b, self._a, samples.astype(np.float64), zi=self._zi)
        return out.astype(np.float32)

    def reset(self) -> None:
        self._zi = np.zeros(2)
