"""
dsp.gain — control de ganancia y limitador de picos.

GainLimiter aplica ganancia lineal seguida de un peak limiter vectorizado:
  envelope[i] = max_j<=i( |audio[j]| * coef^(i-j) )
             = coef^i * cummax( |audio| / coef^arange(n) )
Ataque instantáneo, release exponencial suave — sin bucles Python.
"""
import numpy as np


class GainLimiter:
    """
    Aplica ganancia lineal y limita picos para proteger la salida de audio.
    El limiter usa un envelope follower vectorizado (numpy cummax).
    """

    def __init__(self, gain_db: float = 0.0, limit_db: float = -1.0):
        self._gain      = 10 ** (gain_db / 20.0)
        self._limit     = 10 ** (limit_db / 20.0)
        self._envelope  = 0.0
        self._release   = 0.100          # tiempo de release en segundos
        self._coef      = None           # precalculado en el primer proceso
        self._coefs_n   = None           # longitud del array precalculado
        self._cached_sr = None

    def set_gain_db(self, db: float) -> None:
        self._gain = 10 ** (db / 20.0)

    def _ensure_coefs(self, n: int, sample_rate: int) -> np.ndarray:
        if n != self._coefs_n or sample_rate != self._cached_sr:
            coef = float(np.exp(-1.0 / (self._release * sample_rate)))
            self._coef      = coef
            self._coefs_n   = n
            self._cached_sr = sample_rate
            # coefs[i] = coef^i — precomputado para el tamaño de chunk más común
            self._coefs_arr = (coef ** np.arange(n)).astype(np.float64)
        return self._coefs_arr

    def process(self, audio: np.ndarray, sample_rate: int = 48000) -> np.ndarray:
        audio = (audio * self._gain).astype(np.float64)
        n     = len(audio)
        coefs = self._ensure_coefs(n, sample_rate)

        # Envelope vectorizado: envelope[i] = max_{j<=i}(|audio[j]| * coef^(i-j))
        #   = coefs[i] * cummax(|audio| / coefs)
        abs_audio = np.abs(audio)
        scaled    = abs_audio / coefs                          # |audio[j]| / coef^j
        if self._envelope > 0:
            # incluir contribución del envelope previo (como si viniera de sample -1)
            scaled[0] = max(scaled[0], self._envelope / self._coef)
        cum_max   = np.maximum.accumulate(scaled)              # causal max
        envelope  = cum_max * coefs                            # escalar de vuelta

        self._envelope = float(envelope[-1])

        # Aplicar limitación: gain_env = min(1, limit/envelope)
        with np.errstate(divide="ignore", invalid="ignore"):
            gain_env = np.minimum(1.0, self._limit / (envelope + 1e-12))
        return (audio * gain_env).astype(np.float32)
