import numpy as np
from scipy.signal import butter, sosfilt_zi
from dsp.iir import sosfilt_fast


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
        LÍMITE (medido en el aire, SSB con S/N ≈ 0 dB, 15/9/2026): ese "se calla
        solo" es RELATIVO AL RUIDO. Como `k` normaliza por el RMS de la banda, con
        la banda llena de ruido el módulo agrega en las pausas lo mismo que con
        voz (−17 vs −19 dB rel. a la banda), y lo que agrega es ruido×ruido (picudez
        6,5 dB; un tono da 10) metido en 60–250 Hz, que la cadena había dejado
        limpio, justo debajo de la única banda donde la voz sobresale → la voz se
        vuelve MENOS inteligible. Reportado por el usuario: *"con alto ruido, el
        recuperador de graves no ayuda, sino todo lo contrario"*.

    RETIRADA AUTOMÁTICA POR PERIODICIDAD (`set_periodicity`). El nivel se escala por
    una rampa sobre la confianza de la autocorrelación del profiler (pre-cancelador,
    ya calculada para el pitch y el freeze de MCRA), con memoria de 2 s:
        r = clip((ema(conf) − _PERIOD_LO) / (_PERIOD_HI − _PERIOD_LO), 0, 1)
    Qué se midió antes de elegir esa señal (historial, "automatizar el apagado"):
      · gate por VAD como el excitador: NO. El daño es DURANTE la voz (ruido×voz),
        y ahí el vp está ≥ 0,30 el 95 % del tiempo; el zumbido de las pausas está a
        −67 dBFS, inaudible.
      · ganancia media del cancelador en 250-1000 Hz: NO discrimina (0,19-0,28 en
        cinco grabaciones, limpias y sucias por igual).
      · confianza de periodicidad: SÍ. Frames fuertes 0,67 (voz limpia) … 0,28
        (enterrada). Con memoria CORTA (200 ms) el detector sigue las sílabas y le
        roba 3,3 dB a la voz limpia; con 2 s sigue la condición de la estación
        (regla 4). Grave retenido con esta rampa: voz limpia 0,0 dB, AM con música
        −0,6 dB (r entre 0,78 y 1,0), voz enterrada −16,9 dB.
    Falla benigna (regla 3): si la confianza no sube, el módulo se retira — que es
    lo que el manual mandaba hacer a mano. Sin slider (regla 19): las dos puntas
    no son defendibles por condición. El EMA arranca en la primera confianza que
    recibe (con el stream recién abierto, ~0): los graves entran en ~2 s.
    """

    _BAND_LO_HZ: float = 250.0    # armónicos que sobreviven a un filtro SSB
    _BAND_HI_HZ: float = 1000.0
    _LP_HZ:      float = 320.0    # se queda con las diferencias (f0), no con las sumas
    _DC_HZ:      float = 60.0     # saca la continua del cuadrado
    _RMS_SMOOTH: float = 0.90     # memoria del RMS para la normalización (~100 ms)
    _RMS_MIN:    float = 1e-9
    # Calibrado para que amount=1.0 devuelva el fundamental al nivel que tenía antes
    # del filtro, medido sobre voces REALISTAS: fuente glotal con caída de 12 dB/oct
    # + formantes (F1 500-700 Hz), cuatro variantes (masculina grave, F1 alto,
    # masculina aguda y femenina).
    # OJO CON LA CALIBRACIÓN: la primera versión usó una voz de armónicos 1/k, donde
    # el fundamental es el parcial MÁS FUERTE. En una voz real la fuente cae y el F1
    # domina — y el F1 cae justo dentro de la banda que se eleva al cuadrado, así que
    # produce mucha más diferencia. Medido: con ese factor el 100% quedaba +10 a
    # +13 dB por encima del natural en las cuatro voces realistas, y solo +2 dB en la
    # 1/k. Reportado en el aire como "el efecto es muy fuerte, más de 15% es
    # demasiado". Con este factor el exceso queda en ±1 dB y la dispersión entre las
    # cuatro voces es de 2.7 dB (el mismo porcentaje suena parecido en voces
    # distintas).
    _REF_GAIN:   float = 0.37
    # Rampa de retirada por periodicidad (ver docstring): por debajo de LO el módulo
    # está apagado, por encima de HI entero. Memoria del EMA en segundos.
    _PERIOD_LO:    float = 0.20
    _PERIOD_HI:    float = 0.40
    _PERIOD_TAU_S: float = 2.0

    def __init__(self, sample_rate: int = 48000):
        self._enabled = False
        self._amount  = 0.35

        nyq = sample_rate / 2.0
        self._sos_band = butter(
            2, [self._BAND_LO_HZ / nyq, min(self._BAND_HI_HZ / nyq, 0.99)],
            btype='band', output='sos').astype(np.float64)
        # Pasa-bajos y quitacontinua en UNA cascada: es la misma serie de biquads
        # en el mismo orden que filtrarlos uno detrás del otro (idéntico bit a
        # bit) y se ahorra una llamada al filtro por frame.
        self._sos_low = np.vstack([
            butter(2, self._LP_HZ / nyq, btype='low', output='sos'),
            butter(2, self._DC_HZ / nyq, btype='high', output='sos'),
        ]).astype(np.float64)

        self._zi_band: np.ndarray | None = None
        self._zi_low:  np.ndarray | None = None
        self._rms:     float = 0.0
        self._sr:      float = float(sample_rate)
        # Periodicidad: objetivo del frame (1.0 = sin retirar, para quien no la
        # informe) y EMA (None hasta el primer frame → arranca sin rampa).
        self._period_target: float = 1.0
        self._period_ema: float | None = None

    def reset(self) -> None:
        self._zi_band = None
        self._zi_low  = None
        self._rms     = 0.0
        self._period_ema = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_amount(self, amount: float) -> None:
        self._amount = float(np.clip(amount, 0.0, 1.0))

    def set_periodicity(self, confidence: float) -> None:
        """Confianza de periodicidad del frame (0–1, la autocorrelación del profiler).
        Se suaviza acá con memoria de _PERIOD_TAU_S; llamar una vez por chunk."""
        self._period_target = float(np.clip(confidence, 0.0, 1.0))

    @property
    def periodicity(self) -> float:
        """EMA (2 s) de la confianza de periodicidad que alimenta la rampa (diagnóstico)."""
        return 1.0 if self._period_ema is None else float(self._period_ema)

    @property
    def periodicity_gate(self) -> float:
        """Factor 0–1 que la rampa de periodicidad aplica al nivel (diagnóstico)."""
        if self._period_ema is None:
            return 1.0
        return float(np.clip((self._period_ema - self._PERIOD_LO)
                             / (self._PERIOD_HI - self._PERIOD_LO), 0.0, 1.0))

    def process(self, chunk: np.ndarray) -> np.ndarray:
        # El EMA avanza aunque el módulo esté apagado: al encenderlo tiene que
        # reflejar la estación actual, no la de cuando se apagó.
        if self._period_ema is None:
            self._period_ema = self._period_target
        else:
            a = float(np.exp(-len(chunk) / self._sr / self._PERIOD_TAU_S))
            self._period_ema = a * self._period_ema + (1.0 - a) * self._period_target

        if not self._enabled or self._amount <= 0.0:
            return chunk
        r = self.periodicity_gate
        if r <= 0.0:
            return chunk

        x = chunk.astype(np.float64)

        if self._zi_band is None:
            self._zi_band = sosfilt_zi(self._sos_band) * 0.0
            self._zi_low  = np.zeros((self._sos_low.shape[0], 2))

        band, self._zi_band = sosfilt_fast(self._sos_band, x, self._zi_band)

        # El cuadrado es cuadrático: normalizar por el RMS de la banda deja el
        # efecto proporcional a la señal y no al cuadrado de su nivel.
        a = self._RMS_SMOOTH
        self._rms = a * self._rms + (1.0 - a) * float(np.sqrt(np.mean(band * band)))
        if self._rms < self._RMS_MIN:
            return chunk

        low, self._zi_low = sosfilt_fast(self._sos_low, band * band, self._zi_low)

        gain = self._amount * r * self._REF_GAIN / self._rms
        return (x + gain * low).astype(np.float32)
