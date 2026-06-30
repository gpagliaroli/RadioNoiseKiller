"""
dsp.level — medidor de nivel RMS para VU meter.

Calcula el nivel RMS de cada bloque de audio con decaimiento exponencial suave.
El nivel sube inmediatamente al pico pero baja gradualmente (decay_db_per_sec).
Retorna dBFS en el rango [-60, 0].
"""
import numpy as np


class LevelMeter:
    """
    Medidor de nivel RMS con decaimiento suave para VU meter en la UI.
    Devuelve el nivel en dBFS en el rango [-60, 0].
    """

    FLOOR_DB = -60.0

    def __init__(self, decay_db_per_sec: float = 20.0, sample_rate: int = 48000):
        self._rms = 0.0
        self._decay = 10 ** (-decay_db_per_sec / (20.0 * sample_rate))

    def process(self, audio: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms > self._rms:
            self._rms = rms
        else:
            self._rms *= self._decay ** len(audio)

        if self._rms < 1e-9:
            return self.FLOOR_DB
        db = 20.0 * np.log10(self._rms)
        return float(np.clip(db, self.FLOOR_DB, 0.0))
