from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QImage, QColor, QPen, QFont, QLinearGradient
from i18n import tr


def _build_sdr_lut() -> np.ndarray:
    """LUT 256×3 (uint8) estilo SDR clásico: azul→cian→verde→amarillo→rojo,
    interpolada linealmente entre puntos de control. Índice 0 = nivel más bajo."""
    stops = [
        (0.00, (0,   0,  30)),   # fondo (casi negro azulado)
        (0.25, (0,   0, 200)),   # azul
        (0.45, (0, 200, 200)),   # cian
        (0.60, (0, 200,   0)),   # verde
        (0.78, (220, 220, 0)),   # amarillo
        (1.00, (220,  0,   0)),  # rojo
    ]
    xs = np.array([s[0] for s in stops])
    cols = np.array([s[1] for s in stops], dtype=np.float32)
    t = np.linspace(0.0, 1.0, 256)
    lut = np.empty((256, 3), dtype=np.uint8)
    for c in range(3):
        lut[:, c] = np.clip(np.interp(t, xs, cols[:, c]), 0, 255).astype(np.uint8)
    return lut


class WaterfallWidget(QWidget):
    """
    Cascada (waterfall): historia tiempo-frecuencia bajo el espectro.

    Eje X = frecuencia (alineado con el SpectrumWidget: mismos márgenes y max_bin),
    eje Y = tiempo (fila superior = ahora, hacia abajo = pasado, ~30 s),
    color = magnitud en dB (LUT SDR clásico).

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

    # OJO: _ML y _MR tienen que seguir siendo los mismos que en SpectrumWidget —
    # de eso depende que los ejes de frecuencia de los dos gráficos queden
    # alineados. Por eso la escala de color va en el margen SUPERIOR (que sí se
    # puede crecer sin desalinear nada) y no a la derecha, como es habitual.
    _ML = 42   # margen izquierdo (etiquetas de tiempo) — igual que el espectro
    _MR = 10
    _MT = 15   # margen superior: escala de color + etiqueta de fuente
    _MB = 16   # margen inferior (etiquetas Hz)

    _LUT = _build_sdr_lut()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)

        self._n_bins = self.FFT_SIZE // 2 + 1
        # El buffer se dimensiona SIEMPRE para la profundidad máxima y el zoom se
        # hace al dibujar: así cambiar la profundidad no descarta la historia ya
        # capturada ni obliga a reasignar el ring en caliente.
        self._rows   = max(1, int(self.HISTORY_MAX / (self.TICK_MS / 1000.0)))
        self._ring   = np.full((self._rows, self._n_bins), self.DB_MIN, dtype=np.float32)
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

    def start(self) -> None:
        self._ring.fill(self.DB_MIN)
        self._cursor = 0
        self._active = True
        self.update()

    def stop(self) -> None:
        self._active = False
        self._ring.fill(self.DB_MIN)
        self._cursor = 0
        self.update()

    def clear(self) -> None:
        self._ring.fill(self.DB_MIN)
        self._cursor = 0
        self.update()

    def push_row(self, db: np.ndarray) -> None:
        """Agrega una fila dB (longitud n_bins) al tope de la cascada."""
        if not self._active:
            return
        self._cursor = (self._cursor + 1) % self._rows
        n = min(len(db), self._n_bins)
        self._ring[self._cursor, :n] = db[:n]
        if n < self._n_bins:
            self._ring[self._cursor, n:] = self.DB_MIN
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

    def _draw_waterfall(self, p: QPainter, ml: int, mt: int, pw: int, ph: int) -> None:
        mb = self._max_bin
        nvis = self._visible_rows()
        # Filas ordenadas de más nueva (arriba) a más vieja (abajo), solo las que
        # entran en la profundidad elegida. El ring va cronológico; roll para que
        # la fila del cursor quede primera.
        order = (self._cursor - np.arange(nvis)) % self._rows
        rows = self._ring[order, :mb]                       # (nvis, max_bin)

        span = max(self._db_max - self.DB_MIN, 1.0)
        frac = np.clip((rows - self.DB_MIN) / span, 0.0, 1.0)
        idx  = (frac * 255.0).astype(np.uint8)
        rgb  = np.ascontiguousarray(self._LUT[idx])          # (nvis, max_bin, 3) uint8
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
        grad = QLinearGradient(ml, 0, ml + bw, 0)
        for i in range(0, 256, 15):
            r, g, b = (int(v) for v in self._LUT[i])
            grad.setColorAt(i / 255.0, QColor(r, g, b))
        p.fillRect(QRectF(ml, by, bw, bh), grad)
        p.setPen(QPen(QColor("#2a3f5a"), 1))
        p.drawRect(QRectF(ml, by, bw, bh))

        p.setPen(QColor("#607d8b"))
        p.drawText(QRectF(ml + bw + 3, 0, 60, self._MT),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   f"{self.DB_MIN:.0f}..{self._db_max:.0f} dB")
