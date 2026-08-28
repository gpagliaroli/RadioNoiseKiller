"""
dsp.blanker — supresor de impulsos (QRN, descargas, chasquidos).

POR QUÉ SE REDISEÑÓ (reportado en el aire: "el supresor causa distorsión de la
voz, es notoria al activarlo"). La versión anterior vivía dentro de
`pipeline._run_processor` y tenía dos defectos que se median así, sobre voz
LIMPIA y sin un solo impulso presente:

    S/N 20 dB, umbrales del usuario -> 26,5% de los mini-frames atenuados,
                                       -6,8 dB de voz, distorsión -6,6 dB

Una distorsión de -6,6 dB es casi el 50% de la señal. Las dos causas:

1. **El umbral se comparaba contra el PISO DE RUIDO** (`mini_e > k * energy_hist`).
   Con voz a 20 dB sobre el piso, la energía de voz es 100x el piso contra un
   umbral de 12x: toda sílaba lo cruzaba. No suprimía impulsos, comprimía la voz
   a 12 veces el nivel de ruido con ataque de 0,67 ms y sin release. Delataba el
   error que EMPEORABA cuanto mejor era la señal (-8,2 dB a S/N 30).
2. **La ganancia se aplicaba como escalón rectangular cada 32 muestras**, sin
   crossfade: cada salto entre mini-frames vecinos es un click de banda ancha.

Diseño actual — **contraste local en el tiempo**: un impulso es un trozo que
sobresale de SUS VECINOS INMEDIATOS, no del piso de ruido. La voz es sostenida,
así que sus vecinos están igual de fuertes y el cociente da ~1: no dispara.
Es el mismo principio que usa el ANF en frecuencia (mediana de bins vecinos),
aplicado en el tiempo. Y la atenuación se aplica sobre una curva de ganancia
suavizada, nunca como escalón.

Los dos umbrales conservan su significado para el usuario ("cuántas veces por
encima"), sólo que ahora la referencia es el nivel local y no el piso de ruido.
"""
import numpy as np
from scipy.ndimage import median_filter as _mf


class ImpulseBlanker:

    _MINI: int = 32          # muestras por mini-frame (0,67 ms @ 48 kHz)
    _CTX_MINI: int = 33      # mini-frames de la mediana local (~22 ms, impar)
    _CTX_FRAME: int = 25     # frames de la mediana local del nivel de trama
    _RAMP: int = 16          # muestras de la rampa de ganancia (~0,33 ms)
    # OJO: la rampa tiene que ser MAS CORTA que el impulso, y el hueco de
    # ganancia MAS ANCHO. Con rampa de 64 muestras (2 mini-frames) el
    # suavizado diluia la correccion de un click de 0,3 ms y la supresion
    # medida caia a -0,5 dB: el filtro que mata el click de la correccion
    # se comia tambien la correccion. Por eso _RAMP corto + dilatacion.

    def __init__(self, sample_rate: int = 48000):
        self._sample_rate = int(sample_rate)
        self._frame_thr: float = 15.0
        self._mini_thr:  float = 8.0
        self._enabled:   bool  = False
        self._hits_frame: int  = 0     # disparos de la etapa de trama
        self._hits_mini:  int  = 0     # mini-frames atenuados

        # Ventana de suavizado de la ganancia: rampa coseno normalizada. Sin
        # esto la corrección introduce su propio click, que era la mitad del
        # problema original.
        w = np.hanning(self._RAMP + 2)[1:-1].astype(np.float32)
        self._ramp = w / w.sum()

        self._reset_state()

    def _reset_state(self) -> None:
        self._ctx_mini:  np.ndarray = np.zeros(0, dtype=np.float64)  # energías previas
        self._ctx_frame: list = []                                   # energías de trama
        self._gain_tail: np.ndarray = np.ones(self._RAMP // 2, dtype=np.float32)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._reset_state()
        self._hits_frame = self._hits_mini = 0

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_frame_threshold(self, v: float) -> None:
        """Cuántas veces sobre el nivel local tiene que estar una TRAMA."""
        self._frame_thr = float(np.clip(v, 2.0, 100.0))

    def set_mini_threshold(self, v: float) -> None:
        """Cuántas veces sobre el nivel local tiene que estar un MINI-FRAME."""
        self._mini_thr = float(np.clip(v, 2.0, 30.0))

    def pop_hits(self) -> tuple:
        """Disparos de cada etapa desde la última lectura: `(trama, mini)`.

        Van SEPARADOS porque las dos etapas hacen cosas distintas y se ajustan
        con sliders distintos. Sumados —que es como estaba— el número lo domina
        la mini (dispara por mini-frame, la trama una vez por bloque): medido
        sobre una grabación real, con los umbrales por defecto la trama aportaba
        el **9,8 %** del total, así que mover su umbral casi no movía el
        indicador. Con la trama en 4, donde le pone un techo a las ráfagas de
        nivel, pasa a ser el 44 % — y ahí hace falta poder verla sola.

        Lectura + reset sin lock (invariante 7).
        """
        h = (self._hits_frame, self._hits_mini)
        self._hits_frame = self._hits_mini = 0
        return h

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if not self._enabled or len(chunk) < self._MINI:
            return chunk

        n = len(chunk)
        M = self._MINI
        n_mini = n // M
        if n_mini == 0:
            return chunk

        # --- energías por mini-frame, con el contexto de los chunks previos ---
        e_cur = (np.sum(chunk[:n_mini * M].reshape(-1, M).astype(np.float64) ** 2, axis=1) / M)
        e_all = np.concatenate([self._ctx_mini, e_cur])
        off = len(self._ctx_mini)

        # Mediana local: la referencia es el nivel de los VECINOS, no el piso de
        # ruido. Un click sobresale de sus vecinos; una sílaba no, porque los
        # vecinos son la misma sílaba.
        med = _mf(e_all, size=self._CTX_MINI)[off:]
        over_mini = e_cur > self._mini_thr * (med + 1e-20)
        if np.any(over_mini):
            larga = over_mini.copy()
            larga[:-1] &= over_mini[1:]        # sigue alto en el siguiente
            larga[1:]  &= over_mini[:-1]       # y venia alto del anterior
            over_mini = over_mini & ~larga
            over_mini[-1] = False

        if np.any(over_mini):
            dil = over_mini.copy()
            dil[:-1] |= over_mini[1:]
            dil[1:]  |= over_mini[:-1]
            over_mini = dil

        # --- nivel de trama, misma idea a escala de trama ---
        fe = float(np.dot(chunk, chunk)) / n
        self._ctx_frame.append(fe)
        if len(self._ctx_frame) > self._CTX_FRAME:
            self._ctx_frame.pop(0)
        med_f = float(np.median(self._ctx_frame))
        frame_gain = 1.0
        if len(self._ctx_frame) >= 5 and fe > self._frame_thr * (med_f + 1e-20):
            # A escala de trama el objetivo es RECORTAR el exceso, no bajar al
            # nivel local: con 40 ms por trama la mediana de un segundo mezcla
            # silabas y silencios, asi que llevar una silaba fuerte hasta la
            # mediana es un compresor brutal (medido: -2,5 dB de voz con solo
            # 0,2% de disparos en la etapa mini). La etapa mini es la que
            # reemplaza impulsos; esta solo le pone un techo a las rafagas.
            frame_gain = float(np.sqrt(self._frame_thr * med_f / (fe + 1e-20)))
            self._hits_frame += 1

        if not np.any(over_mini) and frame_gain >= 1.0:
            self._ctx_mini = e_all[-(self._CTX_MINI):]
            self._gain_tail = np.ones(self._RAMP // 2, dtype=np.float32)
            return chunk

        self._hits_mini += int(np.sum(over_mini))

        # --- ganancia por muestra + suavizado (nunca un escalón) ---
        # El minimo(...,1.0) NO es decorativo: al dilatar la mascara, los
        # mini-frames vecinos no son impulsos y su energia es normal, asi que
        # sqrt(umbral*mediana/energia) les daria ganancia MAYOR que 1 — medido,
        # amplificaba el impulso +12,9 dB en vez de suprimirlo. Un supresor
        # nunca debe poder subir nada.
        # El umbral decide CUANDO actuar; el objetivo es el NIVEL LOCAL, no
        # "umbral x nivel local". Atenuar hasta el umbral deja el impulso 12
        # veces por encima de sus vecinos: medido, -11,9 dB de objetivo cuando
        # hacian falta -22. El viejo disimulaba esto porque su referencia era el
        # piso de ruido, mucho mas abajo que la voz — y por eso mismo destrozaba
        # la voz. Un blanker reemplaza el impulso por algo al nivel de lo que lo
        # rodea.
        g_mini = np.minimum(
            np.where(over_mini, np.sqrt(med / (e_cur + 1e-20)), 1.0),
            1.0,
        ).astype(np.float32)
        g = np.ones(n, dtype=np.float32) * np.float32(frame_gain)
        g[:n_mini * M] *= np.repeat(g_mini, M)

        # Suavizado de FASE CERO. Convolucionar con la cola prepuesta y tomar
        # mode="valid" retrasa la curva _RAMP-1 muestras: un impulso de 0,3 ms al
        # principio del bloque recibia la atenuacion DESPUES de haber pasado, y
        # la supresion medida se quedaba en -3,7 dB. Hay que centrar la ventana:
        # historia a la izquierda y relleno con el ultimo valor a la derecha.
        izq = self._RAMP // 2
        der = self._RAMP - 1 - izq
        g_ext = np.concatenate([self._gain_tail[-izq:] if izq else g[:0],
                                g,
                                np.full(der, g[-1], dtype=np.float32)])
        g_smooth = np.convolve(g_ext, self._ramp, mode="valid").astype(np.float32)
        self._gain_tail = g[-izq:].copy() if izq else g[:0].copy()

        self._ctx_mini = e_all[-(self._CTX_MINI):]
        return (chunk * g_smooth[:n]).astype(np.float32)
