import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


class BassRestorer:
    """
    Recuperación de graves: devuelve el FUNDAMENTAL de la voz cuando el filtro de
    la radio ya lo cortó, DERIVÁNDOLO de los armónicos que sí sobrevivieron.

    Por qué hace falta: un pasa-altos de 300 Hz —el típico de un filtro SSB— deja
    el fundamental de una voz masculina 14 a 38 dB abajo (medido: f0=200 Hz −14 dB,
    150 Hz −24 dB, 120 Hz −32 dB, 100 Hz −38 dB). No queda energía que levantar,
    así que ninguna EQ puede recuperarlo. La EQ de Cuerpo sigue siendo la
    herramienta correcta cuando los graves SÍ están; esto es para cuando no están.

    Cómo:
        band = bandpass(x, 250–1000 Hz)   armónicos que sobrevivieron al filtro
        sq   = band²                       no linealidad par
        out  = x + amount · k · hp(lp(sq))

    Al elevar al cuadrado, cada par de armónicos adyacentes produce su DIFERENCIA,
    que es exactamente f0 (4f0 − 3f0 = f0). El pasa-bajos de 320 Hz se queda con
    eso y descarta las sumas; el pasa-altos de 60 Hz saca la continua. `k` divide
    por el RMS de la banda (con memoria entre bloques) porque el cuadrado es
    cuadrático: sin eso el efecto dependería del nivel de entrada.

    POR QUÉ DERIVARLO Y NO SINTETIZARLO. La primera versión era un oscilador en el
    f0 que entrega la autocorrelación. Reportado en el aire: *"quedó muy
    artificial, y son como demasiados bajos y como que vienen con un poco de
    delay"*. Los tres síntomas salían de lo mismo — el oscilador es independiente
    de la voz:
      · artificial: medido con entonación real (f0 oscilando 110–140 Hz), la
        correlación del grave generado con el fundamental original era **+0.01**:
        un tono pegado encima, que bate contra los armónicos en vez de sumarse.
        Derivándolo de los armónicos la correlación es **+0.78** — es la voz.
      · delay: el f0 se calcula cada 3 frames, más el suavizado de f0 y la
        envolvente de ataque → el grave llegaba tarde. Acá no hay detección ni
        envolvente: es muestra a muestra, latencia **0 ms** (medido).
      · demasiados bajos: el oscilador sumaba **+3.3 dB** bajo 200 Hz con ruido
        SOLO (la autocorrelación se dispara con cualquier cosa periódica). El
        derivado agrega **−19.1 dB** en el mismo caso: sin voz no hay armónicos de
        donde derivar, así que se calla solo. Por eso tampoco necesita gate ni
        umbral de confianza.
    """

    _BAND_LO_HZ: float = 250.0    # armónicos que sobreviven a un filtro SSB
    _BAND_HI_HZ: float = 1000.0
    _LP_HZ:      float = 320.0    # se queda con las diferencias (f0), no con las sumas
    _DC_HZ:      float = 60.0     # saca la continua del cuadrado
    _RMS_SMOOTH: float = 0.90     # memoria del RMS para la normalización (~100 ms)
    _RMS_MIN:    float = 1e-9
    # Calibrado para que amount=1.0 devuelva el fundamental al nivel que tenía
    # antes del filtro (voz con entonación: natural −32.5 dB, filtrada −55.4 dB,
    # restaurada −32.5 dB con este factor).
    _REF_GAIN:   float = 1.4

    def __init__(self, sample_rate: int = 48000):
        self._enabled = False
        self._amount  = 0.35

        nyq = sample_rate / 2.0
        self._sos_band = butter(
            2, [self._BAND_LO_HZ / nyq, min(self._BAND_HI_HZ / nyq, 0.99)],
            btype='band', output='sos').astype(np.float64)
        self._sos_lp = butter(
            2, self._LP_HZ / nyq, btype='low', output='sos').astype(np.float64)
        self._sos_dc = butter(
            2, self._DC_HZ / nyq, btype='high', output='sos').astype(np.float64)

        self._zi_band: np.ndarray | None = None
        self._zi_lp:   np.ndarray | None = None
        self._zi_dc:   np.ndarray | None = None
        self._rms:     float = 0.0

    def reset(self) -> None:
        self._zi_band = None
        self._zi_lp   = None
        self._zi_dc   = None
        self._rms     = 0.0

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_amount(self, amount: float) -> None:
        self._amount = float(np.clip(amount, 0.0, 1.0))

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if not self._enabled or self._amount <= 0.0:
            return chunk

        x = chunk.astype(np.float64)

        if self._zi_band is None:
            self._zi_band = sosfilt_zi(self._sos_band) * 0.0
            self._zi_lp   = sosfilt_zi(self._sos_lp) * 0.0
            self._zi_dc   = sosfilt_zi(self._sos_dc) * 0.0

        band, self._zi_band = sosfilt(self._sos_band, x, zi=self._zi_band)

        # El cuadrado es cuadrático: normalizar por el RMS de la banda deja el
        # efecto proporcional a la señal y no al cuadrado de su nivel.
        a = self._RMS_SMOOTH
        self._rms = a * self._rms + (1.0 - a) * float(np.sqrt(np.mean(band * band)))
        if self._rms < self._RMS_MIN:
            return chunk

        low, self._zi_lp = sosfilt(self._sos_lp, band * band, zi=self._zi_lp)
        low, self._zi_dc = sosfilt(self._sos_dc, low, zi=self._zi_dc)

        gain = self._amount * self._REF_GAIN / self._rms
        return (x + gain * low).astype(np.float32)
