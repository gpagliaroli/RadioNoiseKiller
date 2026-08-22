from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QImage, QColor, QPen, QFont, QLinearGradient
from i18n import tr


def _lut_from_stops(stops: list) -> np.ndarray:
    """LUT 256×3 (uint8) interpolando linealmente entre puntos de control
    (posición 0..1 → RGB). Índice 0 = extremo bajo de la escala."""
    xs = np.array([s[0] for s in stops])
    cols = np.array([s[1] for s in stops], dtype=np.float32)
    t = np.linspace(0.0, 1.0, 256)
    lut = np.empty((256, 3), dtype=np.uint8)
    for c in range(3):
        lut[:, c] = np.clip(np.interp(t, xs, cols[:, c]), 0, 255).astype(np.uint8)
    return lut


def _build_sdr_lut() -> np.ndarray:
    """Escala de nivel, estilo SDR clásico: azul→cian→verde→amarillo→rojo."""
    return _lut_from_stops([
        (0.00, (0,   0,  30)),   # fondo (casi negro azulado)
        (0.25, (0,   0, 200)),   # azul
        (0.45, (0, 200, 200)),   # cian
        (0.60, (0, 200,   0)),   # verde
        (0.78, (220, 220, 0)),   # amarillo
        (1.00, (220,  0,   0)),  # rojo
    ])


def _build_diff_lut() -> np.ndarray:
    """Escala DIVERGENTE para el modo Diferencia (entrada − salida en dB).

    El cero va al centro y se pinta con el mismo fondo que la escala de nivel,
    así "acá no pasa nada" se ve como fondo vacío y solo saltan a la vista los
    bins donde el procesamiento hizo algo:
      - positivo (se quitó señal) → la MISMA rampa SDR comprimida en la mitad
        superior, para que el ojo la lea igual que en los modos Entrada/Salida.
      - negativo (se amplificó)   → violeta/magenta, un color que no aparece en
        la rampa de nivel y por eso no se puede confundir con "mucha reducción".
    """
    return _lut_from_stops([
        (0.00, (200,   0, 200)),   # -DIFF_SPAN: amplificado fuerte (magenta)
        (0.25, (90,    0, 120)),   # violeta oscuro
        (0.50, (0,     0,  30)),   # 0 dB: sin cambio = fondo
        (0.62, (0,     0, 200)),   # azul
        (0.72, (0,   200, 200)),   # cian
        (0.80, (0,   200,   0)),   # verde
        (0.89, (220, 220,   0)),   # amarillo
        (1.00, (220,   0,   0)),   # +DIFF_SPAN: reducción máxima (rojo)
    ])


class WaterfallWidget(QWidget):
    """
    Cascada (waterfall): historia tiempo-frecuencia bajo el espectro.

    Eje X = frecuencia (alineado con el SpectrumWidget: mismos márgenes y max_bin),
    eje Y = tiempo (fila superior = ahora, hacia abajo = pasado, ~30 s),
    color = magnitud en dB (LUT SDR clásico).

    Dos escalas, según la fuente elegida en la UI:
      - NIVEL (Entrada / Salida): dBFS contra la rampa SDR, techo = slider Máx Y.
      - DIFERENCIA: entrada−salida en dB con una LUT divergente y escala fija
        (±DIFF_SPAN). Muestra CUÁNTO quita el procesamiento en cada frecuencia y
        momento, sin tener que comparar dos imágenes a ojo.

    Las filas las empuja el SpectrumWidget (una por tick, dB instantáneo sin EMA)
    vía push_row(). El buffer es circular; el pintado arma un QImage escalado.
    Todo vectorizado en numpy para no contender el GIL con el hilo de audio.
    """

    FFT_SIZE    = 2048
    SAMPLE_RATE = 48_000
    MAX_FREQ_HZ = 12_000
    DB_MIN      = -80.0
    HISTORY_SEC = 30.0         # profundidad por defecto
    HISTORY_MAX = 120.0        # el buffer se dimensiona para esto (~7 MB)
    TICK_MS     = 67           # igual que el timer del SpectrumWidget (~15 fps)

    # Modo Diferencia: escala FIJA y simétrica en dB. No usa el slider Máx Y —
    # ese controla un techo de nivel (dBFS) y acá los valores son diferencias.
    # ±30 dB cubre de sobra lo que hace la cadena (el piso del cancelador son
    # 20 dB y el post-filtro suma unos 25 más); lo que se pase, se satura.
    DIFF_SPAN   = 30.0

    # OJO: _ML y _MR tienen que seguir siendo los mismos que en SpectrumWidget —
    # de eso depende que los ejes de frecuencia de los dos gráficos queden
    # alineados. Por eso la escala de color va en el margen SUPERIOR (que sí se
    # puede crecer sin desalinear nada) y no a la derecha, como es habitual.
    _ML = 42   # margen izquierdo (etiquetas de tiempo) — igual que el espectro
    _MR = 10
    _MT = 15   # margen superior: escala de color + etiqueta de fuente
    _MB = 16   # margen inferior (etiquetas Hz)

    _LUT      = _build_sdr_lut()
    _LUT_DIFF = _build_diff_lut()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)

        self._diff_mode = False   # False = nivel (Entrada/Salida); True = diferencia
        self._n_bins = self.FFT_SIZE // 2 + 1
        # El buffer se dimensiona SIEMPRE para la profundidad máxima y el zoom se
        # hace al dibujar: así cambiar la profundidad no descarta la historia ya
        # capturada ni obliga a reasignar el ring en caliente.
        self._rows   = max(1, int(self.HISTORY_MAX / (self.TICK_MS / 1000.0)))
        self._ring   = np.full((self._rows, self._n_bins), self._empty_value, dtype=np.float32)
        self._cursor = 0          # posición de la fila más nueva (recién escrita)
        self._history_sec = self.HISTORY_SEC
        self._tone_freqs: np.ndarray | None = None   # heterodinos detectados por el ANF

        self._db_max      = 0.0
        self._max_freq_hz = self.MAX_FREQ_HZ
        self._freq_per_bin = self.SAMPLE_RATE / self.FFT_SIZE
        self._update_max_bin()

        self._active       = False
        self._source_label = tr("Entrada")
        self._rgb: np.ndarray | None = None   # mantiene vivo el buffer del QImage

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @property
    def _empty_value(self) -> float:
        """Valor con el que se rellena el buffer vacío. En modo nivel es el piso
        de la escala; en Diferencia es 0 (= sin cambio), porque el piso de esa
        escala significa 'amplificado a full' y pintaría la pantalla de magenta."""
        return 0.0 if self._diff_mode else self.DB_MIN

    def start(self) -> None:
        self._ring.fill(self._empty_value)
        self._cursor = 0
        self._active = True
        self.update()

    def stop(self) -> None:
        self._active = False
        self._ring.fill(self._empty_value)
        self._cursor = 0
        self.update()

    def clear(self) -> None:
        self._ring.fill(self._empty_value)
        self._cursor = 0
        self.update()

    def push_row(self, db: np.ndarray) -> None:
        """Agrega una fila al tope de la cascada: dB absolutos en modo nivel,
        o entrada−salida en dB en modo Diferencia (longitud n_bins)."""
        if not self._active:
            return
        self._cursor = (self._cursor + 1) % self._rows
        n = min(len(db), self._n_bins)
        self._ring[self._cursor, :n] = db[:n]
        if n < self._n_bins:
            self._ring[self._cursor, n:] = self._empty_value
        self.update()

    def set_db_max(self, db_max: int) -> None:
        self._db_max = float(db_max)
        self.update()

    def set_max_freq_hz(self, hz: int) -> None:
        self._max_freq_hz = max(1000, min(hz, self.MAX_FREQ_HZ))
        self._update_max_bin()
        self.update()

    def set_history_sec(self, sec: float) -> None:
        """Profundidad visible. No toca el buffer: solo cuántas filas se dibujan."""
        self._history_sec = float(np.clip(sec, 5.0, self.HISTORY_MAX))
        self.update()

    def set_tone_freqs(self, freqs: "np.ndarray | None") -> None:
        """Frecuencias (Hz) de los tonos que el ANF está cancelando ahora mismo.
        None o vacío = sin marcadores. Se lee desde el hilo de UI sin lock: es
        material de diagnóstico y el peor caso es dibujar un frame desactualizado
        (misma decisión que `pop_blanker_hits`, invariante 7)."""
        self._tone_freqs = freqs

    def set_source_label(self, text: str) -> None:
        self._source_label = text
        self.update()

    def set_diff_mode(self, on: bool) -> None:
        """Conmuta entre escala de NIVEL (dBFS, fuente Entrada/Salida) y escala
        de DIFERENCIA (entrada−salida en dB). Rellena el buffer con el vacío de
        la escala nueva: las filas viejas están en otra unidad y pintarlas con
        la LUT nueva sería basura (main_window igual llama a clear())."""
        on = bool(on)
        if on == self._diff_mode:
            return
        self._diff_mode = on
        self._ring.fill(self._empty_value)
        self._cursor = 0
        self.update()

    def _update_max_bin(self) -> None:
        self._max_bin = min(self._n_bins,
                            int(self._max_freq_hz / self._freq_per_bin) + 1)

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        W, H = self.width(), self.height()
        ml, mr, mt, mb = self._ML, self._MR, self._MT, self._MB
        pw = W - ml - mr
        ph = H - mt - mb

        p.fillRect(0, 0, W, H, QColor("#0d1117"))
        p.fillRect(ml, mt, pw, ph, QColor("#11192a"))

        if self._active and pw > 0 and ph > 0:
            self._draw_waterfall(p, ml, mt, pw, ph)

        self._draw_axes(p, ml, mt, pw, ph)
        p.end()

    def _visible_rows(self) -> int:
        n = int(round(self._history_sec / (self.TICK_MS / 1000.0)))
        return int(np.clip(n, 1, self._rows))

    def _scale(self) -> tuple:
        """(valor del índice 0, ancho de la escala, LUT) según el modo. Único
        lugar donde se decide el mapeo valor→color: lo comparten el pintado de
        la cascada y la escala de color, así no se pueden desincronizar."""
        if self._diff_mode:
            return -self.DIFF_SPAN, 2.0 * self.DIFF_SPAN, self._LUT_DIFF
        return self.DB_MIN, max(self._db_max - self.DB_MIN, 1.0), self._LUT

    def _draw_waterfall(self, p: QPainter, ml: int, mt: int, pw: int, ph: int) -> None:
        mb = self._max_bin
        nvis = self._visible_rows()
        # Filas ordenadas de más nueva (arriba) a más vieja (abajo), solo las que
        # entran en la profundidad elegida. El ring va cronológico; roll para que
        # la fila del cursor quede primera.
        order = (self._cursor - np.arange(nvis)) % self._rows
        rows = self._ring[order, :mb]                       # (nvis, max_bin)

        lo, span, lut = self._scale()
        frac = np.clip((rows - lo) / span, 0.0, 1.0)
        idx  = (frac * 255.0).astype(np.uint8)
        rgb  = np.ascontiguousarray(lut[idx])                # (nvis, max_bin, 3) uint8
        self._rgb = rgb                                      # evita GC durante el draw

        img = QImage(rgb.data, mb, nvis, mb * 3, QImage.Format_RGB888)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(ml, mt, pw, ph), img)

    def _draw_axes(self, p: QPainter, ml: int, mt: int, pw: int, ph: int) -> None:
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)

        p.setPen(QPen(QColor("#2a3f5a"), 1))
        p.drawRect(ml, mt, pw, ph)

        # Eje de tiempo (izquierda): 0 s arriba, −profundidad abajo. El paso se
        # adapta para no amontonar etiquetas cuando la historia es larga.
        p.setPen(QColor("#607d8b"))
        hist = self._history_sec
        step = 5 if hist <= 20 else 10 if hist <= 45 else 15 if hist <= 70 else 30
        t = 0
        while t <= hist:
            y = int(mt + ph * (t / hist))
            if mt - 8 <= y <= mt + ph + 8:
                label = "0" if t == 0 else f"-{t}s"
                p.drawText(QRectF(0, y - 8, ml - 3, 16),
                           Qt.AlignRight | Qt.AlignVCenter, label)
            t += step

        # Eje de frecuencia (abajo): mismas marcas que el espectro
        for khz in range(1, 13):
            bin_idx = int(khz * 1000 / self._freq_per_bin)
            if bin_idx >= self._max_bin:
                break
            x = int(ml + pw * bin_idx / max(self._max_bin - 1, 1))
            p.drawText(QRectF(x - 15, mt + ph + 1, 30, self._MB - 1),
                       Qt.AlignCenter, f"{khz}k")

        # Marcadores de heterodino: los tonos que el ANF está cancelando ahora.
        # Van sobre el eje de frecuencia, así que un tono estable se ve como una
        # marca fija y uno intermitente parpadea — que es justo lo que se quiere
        # distinguir a ojo.
        if self._active and self._tone_freqs is not None and len(self._tone_freqs):
            p.setPen(QPen(QColor("#ff5252"), 1))
            top = self._max_bin * self._freq_per_bin
            for hz in self._tone_freqs:
                if 0 < hz < top:
                    x = int(ml + pw * (hz / self._freq_per_bin)
                            / max(self._max_bin - 1, 1))
                    p.drawLine(x, mt + ph + 1, x, mt + ph + 5)

        self._draw_colorbar(p, ml, pw)

        # Etiqueta de la fuente (margen superior, a la derecha)
        if self._active:
            p.setPen(QColor("#90a4ae"))
            p.drawText(QRectF(ml, 0, pw - 2, mt),
                       Qt.AlignRight | Qt.AlignVCenter, self._source_label)

    def _draw_colorbar(self, p: QPainter, ml: int, pw: int) -> None:
        """Escala de color en el margen superior: qué dB representa cada tono.
        Va arriba y no a la derecha para no mover el margen _MR, del que depende
        la alineación del eje de frecuencia con el espectro."""
        bw, bh, by = 90, 7, (self._MT - 7) // 2
        if pw < bw + 90:
            return
        lo, span, lut = self._scale()
        grad = QLinearGradient(ml, 0, ml + bw, 0)
        for i in range(0, 256, 15):
            r, g, b = (int(v) for v in lut[i])
            grad.setColorAt(i / 255.0, QColor(r, g, b))
        p.fillRect(QRectF(ml, by, bw, bh), grad)
        p.setPen(QPen(QColor("#2a3f5a"), 1))
        p.drawRect(QRectF(ml, by, bw, bh))

        p.setPen(QColor("#607d8b"))
        if self._diff_mode:
            # El signo importa más que los extremos: "+" = se quitó señal.
            text = f"−{self.DIFF_SPAN:.0f} · 0 · +{self.DIFF_SPAN:.0f} dB"
        else:
            text = f"{lo:.0f}..{lo + span:.0f} dB"
        p.drawText(QRectF(ml + bw + 3, 0, 90, self._MT),
                   Qt.AlignLeft | Qt.AlignVCenter, text)
