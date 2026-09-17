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
      destaca[k]  = mag[k] > threshold × baseline[k]
      is_tone[k]  = destaca[k] Y viene destacando hace _PERSIST_MS

    La segunda condición NO es opcional. El criterio espectral solo es
    instantáneo, y un armónico de voz sobresale de la mediana local exactamente
    igual que una portadora: medido con voz sola y NINGÚN heterodino presente,
    el ANF marcaba bins en el 100% de los frames (15,8 bins por frame con hop
    960) y se comía 2,9 dB de voz con profundidad 0,4 — 8,4 dB con 0,9. Era la
    causa real de que "la Profundidad alta opaca la voz".

    Lo que separa un heterodino de un armónico es el TIEMPO: la portadora se
    queda clavada en el mismo bin durante segundos, el armónico se mueve con la
    entonación y se apaga entre sílabas. Con 350 ms de persistencia los falsos
    positivos sobre voz caen a 0% y el heterodino se sigue cazando el 95% de las
    veces, a costa de ~0,4 s para engancharlo (irrelevante en algo estable).

    Enganche de portadora (post-v2.5): la persistencia de 350 ms sola no
    alcanza con un heterodino que hace fading. Medido en una grabación de SW con
    un tono de 5 kHz: el tono destacaba el 91 % de los frames pero el notch sólo
    actuaba el 65 % — cada bajón del fading (uno cada ~0,6 s) reseteaba la racha
    y el tono volvía a sonar entero durante los 350 ms de re-confirmación. Eso
    es el "lo detecta y se va, cíclico" que reportó el usuario. Un bin que viene
    destacando la mayor parte de los últimos segundos (ocupación EMA ≥ 0,85, τ
    1,5 s) es una portadora, no un armónico, y queda ENGANCHADO: se mantiene
    1 s tras perderla (hold), se notchea con umbral más bajo (histéresis 0,6×),
    se ensancha ±2 bins (el lóbulo principal de la ventana sqrt-Hann, que es el
    residuo que quedaba), con profundidad PLENA y ataque instantáneo de la
    ganancia (el suavizado simétrico de 0,8 iba un frame atrás del fading y
    dejaba el tono asomando). Sobre la grabación: residuo audible 78 % → 13 %
    de los frames; sobre cuatro grabaciones de voz sin heterodino: daño en la
    banda de la voz sin cambio (≤ 0,03 dB). El umbral de ocupación importa:
    con 0,70 el enganche tomaba el fundamental de la voz (20–25 % de los frames
    en 275–475 Hz); con 0,85 sólo engancha lo que destacó ~3 s seguidos.
    Y la ocupación sola no distingue una portadora de la parcial más fuerte de
    una nota sostenida (música en AM; la voz sintética con f0 fijo del test de
    integración enganchaba su armónico de 300 Hz): lo que las separa es que el
    **armónico sube y baja con el programa y la portadora no**. Se mide la
    correlación (EMA, τ 1,5 s) entre el log-nivel del bin y el log-nivel del
    frame: heterodino real 0,28 (p90 0,48), espurias fijas 0,05–0,12, parciales
    de la voz sintética 0,90–1,00. Sólo engancha con correlación < 0,5.

    OLA: cada chunk de H muestras se analiza en un frame de 2H muestras
    ([chunk_anterior | chunk_actual]), con ventana sqrt-Hann. La salida
    es la superposición del frame anterior (segundo mitad) con el frame
    actual (primera mitad). Introduce 1 hop (10 ms) de latencia.
    """

    # Tiempo que un bin tiene que venir destacando para tratarlo como tono.
    # 350 ms: medido, lleva los falsos positivos sobre voz a 0% conservando el
    # 95% de detección de heterodinos. En frames depende del hop → se recalcula
    # en _init_ola (invariante 9 del proyecto).
    _PERSIST_MS: float = 350.0
    # Enganche de portadora (ver docstring). Ocupación = EMA por bin de
    # "destaca o su vecino"; con 0,85 el fundamental de la voz no engancha
    # (medido: 0,70 lo tomaba). Todo en ms → frames en _init_ola (invariante 9).
    _LOCK_TAU_MS:  float = 1500.0   # memoria de la ocupación
    _LOCK_OCC:     float = 0.85     # ocupación mínima para enganchar
    _LOCK_HOLD_MS: float = 1000.0   # cuánto se retiene el enganche sin tono
    _LOCK_HYST:    float = 0.6      # umbral relativo para un bin enganchado
    _LOCK_WIDEN:   int   = 2        # bins a cada lado: lóbulo de sqrt-Hann
    _LOCK_CORR:    float = 0.5      # corr bin/frame máxima: más alto = parcial

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
        # Persistencia: frames consecutivos que cada bin lleva destacando
        self._streak:         np.ndarray = np.zeros(0, dtype=np.int32)
        self._persist_frames: int = 1
        # Enganche: ocupación por bin y hold restante en frames
        self._occ:         np.ndarray = np.zeros(0, dtype=np.float32)
        self._lock_hold:   np.ndarray = np.zeros(0, dtype=np.int32)
        self._occ_coef:    float = 0.0
        self._hold_frames: int = 1
        self._last_locked_bins: int = 0
        # Correlación bin/frame (misma τ que la ocupación): momentos EMA
        self._c_mx:  np.ndarray = np.zeros(0, dtype=np.float32)
        self._c_mxx: np.ndarray = np.zeros(0, dtype=np.float32)
        self._c_mxy: np.ndarray = np.zeros(0, dtype=np.float32)
        self._c_my:  np.ndarray = np.zeros(0, dtype=np.float32)
        self._c_myy: np.ndarray = np.zeros(0, dtype=np.float32)

    def _init_ola(self, hop: int) -> None:
        self._hop      = hop
        self._ola_prev = np.zeros(hop, dtype=np.float32)
        self._ola_acc  = np.zeros(2 * hop, dtype=np.float32)
        # sqrt-Hann: satisface COLA al 50% de solapamiento
        self._ola_win  = np.sqrt(np.hanning(2 * hop)).astype(np.float32)
        self._smooth_gains = None
        # El hop define la duración de un frame → la persistencia en frames
        # se recalcula acá y en ningún otro lado (invariante 9)
        hop_ms = 1000.0 * hop / self._sample_rate
        self._persist_frames = max(1, round(self._PERSIST_MS / hop_ms))
        self._streak = np.zeros(hop + 1, dtype=np.int32)   # nb = 2*hop//2 + 1
        self._occ       = np.zeros(hop + 1, dtype=np.float32)
        self._lock_hold = np.zeros(hop + 1, dtype=np.int32)
        self._occ_coef  = float(np.exp(-hop_ms / self._LOCK_TAU_MS))
        self._hold_frames = max(1, round(self._LOCK_HOLD_MS / hop_ms))
        self._c_mx  = np.zeros(hop + 1, dtype=np.float32)
        self._c_mxx = np.zeros(hop + 1, dtype=np.float32)
        self._c_mxy = np.zeros(hop + 1, dtype=np.float32)
        self._c_my  = np.zeros(hop + 1, dtype=np.float32)
        self._c_myy = np.zeros(hop + 1, dtype=np.float32)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def reset(self) -> None:
        if self._hop:
            self._ola_prev[:] = 0.0
            self._ola_acc[:]  = 0.0
        self._smooth_gains = None
        # Sin esto, tras un reinicio del stream un bin arrastraria la racha
        # vieja y notchearia desde el primer frame
        self._streak[:] = 0
        self._occ[:] = 0.0
        self._lock_hold[:] = 0
        self._c_mx[:] = 0.0
        self._c_mxx[:] = 0.0
        self._c_mxy[:] = 0.0
        self._c_my[:] = 0.0
        self._c_myy[:] = 0.0
        self._last_notched_bins = 0
        self._last_locked_bins = 0
        self._last_tone_freqs = None

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
            destaca  = mag > self._threshold * (baseline + 1e-12)

            # La racha sobrevive si el vecino inmediato tambien destaca: un
            # heterodino que deriva lentamente cruza de bin y, sin esta
            # tolerancia, reiniciaria la cuenta cada vez y no llegaria nunca a
            # confirmarse.
            vecino = destaca.copy()
            vecino[:-1] |= destaca[1:]
            vecino[1:]  |= destaca[:-1]
            self._streak = np.where(vecino, self._streak + 1, 0)

            # Se notchea solo donde HAY tono ahora y ademas ya venia sostenido
            is_tone = destaca & (self._streak >= self._persist_frames)

            # Enganche de portadora: ocupación sostenida → hold + histéresis +
            # ensanche + profundidad plena (ver docstring de la clase)
            a = self._occ_coef
            self._occ = (a * self._occ + (1.0 - a) * vecino).astype(np.float32)
            estable = self._occ >= self._LOCK_OCC
            # Portadora vs. parcial de una nota sostenida: la parcial sube y
            # baja con el programa (correlación bin/frame ~0,95), la portadora
            # no (~0,3). Ver docstring; sin esto la voz sintética con f0 fijo
            # del test de integración enganchaba su armónico de 300 Hz.
            x = np.log(mag + 1e-9)
            # Nivel del frame SIN el bin y sus vecinos (±2, el lóbulo): un
            # heterodino fuerte pesa en la energía total y se correlacionaba
            # consigo mismo (el sintético con fading quedaba en 80 % de lock).
            e = mag * mag
            resto = e.sum() - np.convolve(e, np.ones(5, dtype=np.float32), "same")
            y = 0.5 * np.log(np.maximum(resto, 0.0) / len(e) + 1e-18)
            self._c_mx  = (a * self._c_mx  + (1.0 - a) * x).astype(np.float32)
            self._c_mxx = (a * self._c_mxx + (1.0 - a) * x * x).astype(np.float32)
            self._c_mxy = (a * self._c_mxy + (1.0 - a) * x * y).astype(np.float32)
            self._c_my  = (a * self._c_my  + (1.0 - a) * y).astype(np.float32)
            self._c_myy = (a * self._c_myy + (1.0 - a) * y * y).astype(np.float32)
            vx = np.maximum(self._c_mxx - self._c_mx * self._c_mx, 1e-6)
            vy = np.maximum(self._c_myy - self._c_my * self._c_my, 1e-6)
            corr = (self._c_mxy - self._c_mx * self._c_my) / np.sqrt(vx * vy)
            lock_now = estable & (corr < self._LOCK_CORR)
            self._lock_hold = np.where(lock_now, self._hold_frames,
                                       np.maximum(self._lock_hold - 1, 0))
            locked = lock_now | (self._lock_hold > 0)
            lt = locked & (mag > self._threshold * self._LOCK_HYST * (baseline + 1e-12))
            self._last_locked_bins = int(np.sum(lt))
            marca = is_tone | lt          # núcleo, para el marcador de la cascada
            core = lt.copy()
            for d in range(1, self._LOCK_WIDEN + 1):
                lt[d:]  |= core[:-d]
                lt[:-d] |= core[d:]
            is_tone = is_tone | lt
            depth = np.where(lt, 1.0, self._depth).astype(np.float32)

            self._last_notched_bins = int(np.sum(marca))
            # Frecuencias de los tonos, para el marcador de la cascada. Se
            # rebindea un array nuevo (no se muta el anterior): la UI lo lee sin
            # lock y en el peor caso ve el frame previo — material de diagnostico
            # (misma decision que pop_blanker_hits, invariante 7).
            idx = np.flatnonzero(marca)
            self._last_tone_freqs = (idx * (self._sample_rate / (2.0 * self._hop))
                                     ).astype(np.float32)
            gain_inst = np.where(
                is_tone,
                (1.0 - depth) + depth * baseline / (mag + 1e-12),
                1.0,
            ).astype(np.float32)

            # Suavizado temporal: previene cambios bruscos entre frames. En los
            # bins enganchados el ataque es instantáneo: el tono hace fading
            # más rápido que el suavizado y con 0,8 la ganancia iba un frame
            # atrás (residuo audible 52 % vs 13 %). NO generalizarlo a todos los
            # bins: medido, sube el daño a la voz de −0,7 a −1,2 dB.
            if self._smooth_gains is None or len(self._smooth_gains) != len(spec):
                self._smooth_gains = gain_inst.copy()
            else:
                c = self._smooth_coef
                suave = c * self._smooth_gains + (1.0 - c) * gain_inst
                self._smooth_gains = np.where(
                    lt & (gain_inst < self._smooth_gains), gain_inst, suave
                ).astype(np.float32)

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
    def locked_bins(self) -> int:
        """Bins enganchados como portadora en el último frame (subconjunto de
        notched_bins). Para el indicador de actividad."""
        return self._last_locked_bins

    @property
    def tone_freqs(self) -> "np.ndarray | None":
        """Frecuencias (Hz) de los tonos cancelados en el ultimo frame, o None si
        el ANF esta desactivado. Lo usa el marcador de heterodinos de la cascada."""
        return self._last_tone_freqs if self._enabled else None
