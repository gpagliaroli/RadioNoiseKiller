import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


class AuralExciter:
    """
    Excitador armónico estilo Aphex.

    Extrae contenido por encima del corte (HPF 1 kHz), lo satura con tanh
    para generar armónicos pares e impares, y mezcla solo los armónicos
    añadidos al original:

        salida = x + mix × (tanh(drive × hpf(x)) − hpf(x))

    Los armónicos generados caen en la zona de legibilidad (1–4 kHz),
    recuperando presencia y ataque de consonantes perdidos por los filtros
    anteriores del pipeline.

    drive: cuánta saturación (1.0=suave, 5.0=agresivo, 10.0=fuerte)
    mix:   cuánto de los armónicos se mezcla al original (0.0–1.0)
    """

    _CUTOFF_HZ: float = 1000.0  # HPF fijo: genera armónicos en 1–4 kHz

    def __init__(self, sample_rate: int = 48000):
        self._drive:   float = 2.0
        self._mix:     float = 0.3
        self._enabled: bool  = True

        sos = butter(2, self._CUTOFF_HZ / (sample_rate / 2),
                     btype='high', output='sos')
        self._sos: np.ndarray        = sos.astype(np.float64)
        self._zi:  np.ndarray | None = None

    def reset(self) -> None:
        self._zi = None

    def set_drive(self, drive: float) -> None:
        self._drive = float(np.clip(drive, 1.0, 10.0))

    def set_mix(self, mix: float) -> None:
        self._mix = float(np.clip(mix, 0.0, 1.0))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if not self._enabled or self._mix == 0.0:
            return chunk

        x = chunk.astype(np.float64)

        if self._zi is None:
            self._zi = sosfilt_zi(self._sos) * x[0]

        high, self._zi = sosfilt(self._sos, x, zi=self._zi)

        # Solo los armónicos añadidos (sin la señal original del HPF)
        harmonics = np.tanh(self._drive * high) - high

        return (x + self._mix * harmonics).astype(np.float32)
