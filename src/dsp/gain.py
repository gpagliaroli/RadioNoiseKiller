"""
dsp.gain — control de ganancia y limitador de picos.

GainLimiter aplica ganancia lineal seguida de un peak limiter vectorizado:
  envelope[i] = max_j<=i( |audio[j]| * coef^(i-j) )
             = coef^i * cummax( |audio| / coef^arange(n) )
Ataque instantáneo, release exponencial suave — sin bucles Python.

La curva de limitación usa rodilla suave (soft knee): la compresión arranca
gradualmente _KNEE_DB/2 por debajo del límite en vez de aplastar de golpe
(∞:1 con rodilla dura). La salida nunca supera el límite, pero los picos se
redondean en lugar de recortarse — suaviza sin "apretar" la voz.
"""
import numpy as np


class GainLimiter:
    """
    Aplica ganancia lineal y limita picos para proteger la salida de audio.
    El limiter usa un envelope follower vectorizado (numpy cummax).
    """

    # Parámetros de escucha — ajustar acá según cómo suene con radio real:
    _KNEE_DB:    float = 6.0    # ancho total de la rodilla, centrada en el límite.
                                # Más ancho = transición más gradual (empieza antes).
    _RELEASE_S:  float = 0.050  # release del envelope. 0.100 producía ducking
                                # audible (~100-200ms de atenuación tras cada pico).

    def __init__(self, gain_db: float = 0.0, limit_db: float = -1.0):
        self._gain      = 10 ** (gain_db / 20.0)
        self._limit     = 10 ** (limit_db / 20.0)
        self._envelope  = 0.0
        self._release   = self._RELEASE_S
        self._coef      = None           # precalculado en el primer proceso
        self._coefs_n   = None           # longitud del array precalculado
        self._cached_sr = None
        self._last_reduction_db: float = 0.0

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
            # incluir contribución del envelope previo (como si viniera de sample -1):
            # env[0] = max(|a[0]|, env_prev·coef) → en dominio scaled (÷coef^0) es
            # env_prev·coef. Antes dividía por coef (inflaba el envelope ~0.04% por
            # borde de chunk → limitaba de más).
            scaled[0] = max(scaled[0], self._envelope * self._coef)
        cum_max   = np.maximum.accumulate(scaled)              # causal max
        envelope  = cum_max * coefs                            # escalar de vuelta

        self._envelope = float(envelope[-1])

        # Curva de limitación con rodilla suave (en dominio dB):
        #   por debajo de (límite − K/2):  sin cambio (gain = 1)
        #   zona de rodilla (ancho K):     compresión cuadrática progresiva
        #   por encima de (límite + K/2):  salida plana en el límite
        # La salida nunca supera el límite; los picos se redondean sin recorte duro.
        env_db = 20.0 * np.log10(envelope + 1e-12)
        lim_db = 20.0 * np.log10(self._limit)
        half   = self._KNEE_DB / 2.0
        over   = env_db - lim_db                     # dB respecto del límite
        out_db = np.where(
            over <= -half, env_db,
            np.where(over >= half, lim_db,
                     env_db - (over + half) ** 2 / (2.0 * self._KNEE_DB)))
        gain_env = 10.0 ** ((out_db - env_db) / 20.0)

        min_gain = float(np.min(gain_env))
        self._last_reduction_db = 20.0 * np.log10(min_gain) if min_gain < 1.0 else 0.0

        return (audio * gain_env).astype(np.float32)

    @property
    def last_reduction_db(self) -> float:
        """Reducción aplicada en el último frame. 0.0 = sin limitación activa."""
        return self._last_reduction_db
