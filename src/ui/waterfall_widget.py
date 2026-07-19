from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QImage, QColor, QPen, QFont
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
    HISTORY_SEC = 30.0
    TICK_MS     = 67           # igual que el timer del SpectrumWidget (~15 fps)

    _ML = 42   # margen izquierdo (etiquetas de tiempo) — igual que el espectro
    _MR = 10
    _MT = 4
    _MB = 16   # margen inferior (etiquetas Hz)

    _LUT = _build_sdr_lut()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)

        self._n_bins = self.FFT_SIZE // 2 + 1
        self._rows   = max(1, int(self.HISTORY_SEC / (self.TICK_MS / 1000.0)))
        self._ring   = np.full((self._rows, self._n_bins), self.DB_MIN, dtype=np.float32)
        self._cursor = 0          # posición de la fila más nueva (recién escrita)

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

    def _draw_waterfall(self, p: QPainter, ml: int, mt: int, pw: int, ph: int) -> None:
        mb = self._max_bin
        # Filas ordenadas de más nueva (arriba) a más vieja (abajo).
        # El ring va cronológico; roll para que la fila del cursor quede primera.
        order = (self._cursor - np.arange(self._rows)) % self._rows
        rows = self._ring[order, :mb]                       # (rows, max_bin)

        span = max(self._db_max - self.DB_MIN, 1.0)
        frac = np.clip((rows - self.DB_MIN) / span, 0.0, 1.0)
        idx  = (frac * 255.0).astype(np.uint8)
        rgb  = np.ascontiguousarray(self._LUT[idx])          # (rows, max_bin, 3) uint8
        self._rgb = rgb                                      # evita GC durante el draw

        img = QImage(rgb.data, mb, self._rows, mb * 3, QImage.Format_RGB888)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(ml, mt, pw, ph), img)

    def _draw_axes(self, p: QPainter, ml: int, mt: int, pw: int, ph: int) -> None:
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)

        p.setPen(QPen(QColor("#2a3f5a"), 1))
        p.drawRect(ml, mt, pw, ph)

        # Eje de tiempo (izquierda): 0 s arriba, −HISTORY_SEC abajo, cada 10 s
        p.setPen(QColor("#607d8b"))
        step = 10
        t = 0
        while t <= self.HISTORY_SEC:
            y = int(mt + ph * (t / self.HISTORY_SEC))
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

        # Etiqueta de la fuente (arriba a la derecha)
        if self._active:
            p.setPen(QColor("#90a4ae"))
            p.drawText(QRectF(ml, mt + 1, pw - 4, 14),
                       Qt.AlignRight | Qt.AlignTop, self._source_label)
