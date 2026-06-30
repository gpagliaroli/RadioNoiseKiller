from __future__ import annotations
import numpy as np
from collections import deque
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont


class SpectrumWidget(QWidget):
    """
    Visualizador de espectro en tiempo real.

    Curvas disponibles:
      - Entrada  (azul):   señal antes del cancelador de ruido
      - Salida   (verde):  señal procesada final
      - Cancelado (naranja): área entre ambas curvas = lo que se eliminó
      - Piso de ruido (amarillo/punteado): perfil aprendido por el cancelador

    La FFT se calcula en el hilo UI vía QTimer (25 fps).
    Los datos vienen de deques llenados por el hilo de procesamiento (GIL-safe).
    """

    FFT_SIZE    = 2048
    SAMPLE_RATE = 48_000
    MAX_FREQ_HZ = 8_000
    DB_MIN      = -80.0
    DB_MAX      =   0.0
    ALPHA       = 0.35    # suavizado EMA

    _ML = 42   # margen izquierdo (etiquetas dB)
    _MR = 10
    _MT = 10
    _MB = 28   # margen inferior (etiquetas Hz)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 180)

        # Deques externos llenados por el pipeline (GIL protege append/list())
        self.pre_frames:  deque[np.ndarray] = deque(maxlen=8)
        self.post_frames: deque[np.ndarray] = deque(maxlen=8)

        n_bins = self.FFT_SIZE // 2 + 1
        self._db_pre   = np.full(n_bins, self.DB_MIN, dtype=np.float32)
        self._db_post  = np.full(n_bins, self.DB_MIN, dtype=np.float32)
        self._db_floor: np.ndarray | None = None
        self._ema_pre  = None
        self._ema_post = None
        self._window   = np.hanning(self.FFT_SIZE).astype(np.float32)

        freq_per_bin  = self.SAMPLE_RATE / self.FFT_SIZE
        self._max_bin = min(n_bins, int(self.MAX_FREQ_HZ / freq_per_bin) + 1)
        # Frecuencias del display para interpolación del piso de ruido
        self._display_freqs = np.arange(self._max_bin, dtype=np.float32) * freq_per_bin

        self._active         = False
        self._show_pre       = True
        self._show_post      = True
        self._show_cancelled = True
        self._show_floor     = True

        self._floor_learning = False

        self._timer = QTimer(self)
        self._timer.setInterval(40)   # 25 fps
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._ema_pre  = None
        self._ema_post = None
        self._db_floor = None
        self._active   = True
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._active   = False
        n = self.FFT_SIZE // 2 + 1
        self._db_pre   = np.full(n, self.DB_MIN, dtype=np.float32)
        self._db_post  = np.full(n, self.DB_MIN, dtype=np.float32)
        self._db_floor = None
        self._ema_pre  = None
        self._ema_post = None
        self.update()

    def set_show_pre(self, v: bool) -> None:
        self._show_pre = v
        self.update()

    def set_show_post(self, v: bool) -> None:
        self._show_post = v
        self.update()

    def set_show_cancelled(self, v: bool) -> None:
        self._show_cancelled = v
        self.update()

    def set_show_floor(self, v: bool) -> None:
        self._show_floor = v
        self.update()

    def start_floor_learning(self) -> None:
        self._floor_learning = True

    def stop_floor_learning(self) -> None:
        """Toma snapshot del EMA actual — después de 5s con ALPHA=0.35 está completamente convergido."""
        self._floor_learning = False
        if self._ema_pre is not None:
            self._db_floor = self._ema_pre.copy()

    def clear_floor(self) -> None:
        self._db_floor       = None
        self._floor_learning = False
        self.update()

    # ------------------------------------------------------------------
    # Actualización (hilo UI)
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        changed = False

        if self._show_pre or self._show_cancelled or self._floor_learning:
            frames = list(self.pre_frames)
            if frames:
                db = self._compute_db(np.concatenate(frames))
                self._ema_pre = db if self._ema_pre is None else (
                    self.ALPHA * db + (1.0 - self.ALPHA) * self._ema_pre
                )
                self._db_pre = self._ema_pre
                changed = True

        if self._show_post or self._show_cancelled:
            frames = list(self.post_frames)
            if frames:
                db = self._compute_db(np.concatenate(frames))
                self._ema_post = db if self._ema_post is None else (
                    self.ALPHA * db + (1.0 - self.ALPHA) * self._ema_post
                )
                self._db_post = self._ema_post
                changed = True

        if changed:
            self.update()

    def _compute_db(self, samples: np.ndarray) -> np.ndarray:
        if len(samples) < self.FFT_SIZE:
            samples = np.pad(samples, (self.FFT_SIZE - len(samples), 0))
        else:
            samples = samples[-self.FFT_SIZE:]
        mag = np.abs(np.fft.rfft(samples * self._window))
        mag = np.maximum(mag, 1e-10)
        db  = 20.0 * np.log10(mag / (self.FFT_SIZE / 2.0))
        return np.clip(db, self.DB_MIN, self.DB_MAX).astype(np.float32)

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        ml, mr, mt, mb = self._ML, self._MR, self._MT, self._MB
        pw = W - ml - mr
        ph = H - mt - mb

        p.fillRect(0, 0, W, H, QColor("#0d1117"))
        p.fillRect(ml, mt, pw, ph, QColor("#11192a"))

        if not self._active:
            p.setPen(QColor("#4a5568"))
            font = QFont()
            font.setPointSize(9)
            p.setFont(font)
            p.drawText(QRectF(ml, mt, pw, ph),
                       Qt.AlignCenter,
                       "Activar el procesamiento para ver el espectro")
            self._draw_axes(p, ml, mt, pw, ph)
            p.end()
            return

        self._draw_grid(p, ml, mt, pw, ph)

        # Área "cancelada" (entre pre y post, donde pre > post)
        if self._show_cancelled and self._show_pre and self._show_post:
            self._draw_cancelled(p, ml, mt, pw, ph)

        # Curva pre: solo línea cuando el área cancelada ya muestra el espacio
        if self._show_pre:
            if self._show_cancelled and self._show_post:
                self._draw_line_only(p, self._db_pre,
                                     QColor(66, 165, 250), ml, mt, pw, ph)
            else:
                self._draw_curve(p, self._db_pre,
                                 QColor(66, 165, 250, 70),
                                 QColor(66, 165, 250),
                                 ml, mt, pw, ph)

        # Curva post (relleno + línea)
        if self._show_post:
            self._draw_curve(p, self._db_post,
                             QColor(105, 240, 174, 80),
                             QColor(105, 240, 174),
                             ml, mt, pw, ph)

        # Piso de ruido aprendido (línea punteada ámbar)
        if self._show_floor and self._db_floor is not None:
            self._draw_floor_line(p, self._db_floor, ml, mt, pw, ph)

        self._draw_axes(p, ml, mt, pw, ph)
        p.end()

    # ------------------------------------------------------------------
    # Helpers de coordenadas
    # ------------------------------------------------------------------

    def _db_to_y(self, db: float, ph: int, mt: int) -> float:
        frac = (db - self.DB_MIN) / (self.DB_MAX - self.DB_MIN)
        return mt + ph * (1.0 - frac)

    def _bin_to_x(self, bin_idx: int, ml: int, pw: int) -> float:
        return ml + pw * bin_idx / max(self._max_bin - 1, 1)

    # ------------------------------------------------------------------
    # Primitivas de dibujo
    # ------------------------------------------------------------------

    def _draw_curve(self, p: QPainter,
                    db_arr: np.ndarray,
                    fill_color: QColor, line_color: QColor,
                    ml: int, mt: int, pw: int, ph: int) -> None:
        bins   = db_arr[:self._max_bin]
        n      = len(bins)
        bottom = mt + ph

        fill = QPainterPath()
        x0   = self._bin_to_x(0, ml, pw)
        y0   = self._db_to_y(float(bins[0]), ph, mt)
        fill.moveTo(x0, bottom)
        fill.lineTo(x0, y0)
        for i in range(1, n):
            fill.lineTo(self._bin_to_x(i, ml, pw),
                        self._db_to_y(float(bins[i]), ph, mt))
        fill.lineTo(self._bin_to_x(n - 1, ml, pw), bottom)
        fill.closeSubpath()
        p.fillPath(fill, fill_color)

        line = QPainterPath()
        line.moveTo(x0, y0)
        for i in range(1, n):
            line.lineTo(self._bin_to_x(i, ml, pw),
                        self._db_to_y(float(bins[i]), ph, mt))
        p.setPen(QPen(line_color, 1.2))
        p.drawPath(line)

    def _draw_line_only(self, p: QPainter,
                        db_arr: np.ndarray,
                        color: QColor,
                        ml: int, mt: int, pw: int, ph: int) -> None:
        bins = db_arr[:self._max_bin]
        n    = len(bins)
        path = QPainterPath()
        path.moveTo(self._bin_to_x(0, ml, pw),
                    self._db_to_y(float(bins[0]), ph, mt))
        for i in range(1, n):
            path.lineTo(self._bin_to_x(i, ml, pw),
                        self._db_to_y(float(bins[i]), ph, mt))
        p.setPen(QPen(color, 1.2))
        p.drawPath(path)

    def _draw_cancelled(self, p: QPainter,
                         ml: int, mt: int, pw: int, ph: int) -> None:
        """Rellena el área entre pre y post donde pre > post (lo que se canceló)."""
        bins_pre  = self._db_pre[:self._max_bin]
        bins_post = self._db_post[:self._max_bin]
        n = len(bins_pre)

        path = QPainterPath()
        # Borde superior: curva pre (de izquierda a derecha)
        path.moveTo(self._bin_to_x(0, ml, pw),
                    self._db_to_y(float(bins_pre[0]), ph, mt))
        for i in range(1, n):
            path.lineTo(self._bin_to_x(i, ml, pw),
                        self._db_to_y(float(bins_pre[i]), ph, mt))
        # Borde inferior: max(y_pre, y_post) en coords pantalla
        # = min(dB_pre, dB_post) = post donde hubo cancelación, pre donde no
        # El área resultante solo es visible donde pre_dB > post_dB
        for i in range(n - 1, -1, -1):
            y_pre  = self._db_to_y(float(bins_pre[i]),  ph, mt)
            y_post = self._db_to_y(float(bins_post[i]), ph, mt)
            path.lineTo(self._bin_to_x(i, ml, pw), max(y_pre, y_post))
        path.closeSubpath()
        p.fillPath(path, QColor(255, 112, 67, 100))   # naranja semi-transparente

    def _draw_floor_line(self, p: QPainter,
                          db_floor: np.ndarray,
                          ml: int, mt: int, pw: int, ph: int) -> None:
        """Línea punteada ámbar — piso de ruido aprendido."""
        n    = len(db_floor)
        pen  = QPen(QColor(255, 213, 79), 1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(self._bin_to_x(0, ml, pw),
                    self._db_to_y(float(db_floor[0]), ph, mt))
        for i in range(1, n):
            path.lineTo(self._bin_to_x(i, ml, pw),
                        self._db_to_y(float(db_floor[i]), ph, mt))
        p.drawPath(path)

    def _draw_grid(self, p: QPainter,
                   ml: int, mt: int, pw: int, ph: int) -> None:
        pen = QPen(QColor("#1e2d40"), 1)
        pen.setStyle(Qt.DotLine)
        p.setPen(pen)

        for db in (-20, -40, -60):
            y = int(self._db_to_y(db, ph, mt))
            p.drawLine(ml, y, ml + pw, y)

        freq_per_bin = self.SAMPLE_RATE / self.FFT_SIZE
        for khz in range(1, 9):
            bin_idx = int(khz * 1000 / freq_per_bin)
            if bin_idx >= self._max_bin:
                break
            x = int(self._bin_to_x(bin_idx, ml, pw))
            p.drawLine(x, mt, x, mt + ph)

    def _draw_axes(self, p: QPainter,
                   ml: int, mt: int, pw: int, ph: int) -> None:
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)

        p.setPen(QPen(QColor("#2a3f5a"), 1))
        p.drawRect(ml, mt, pw, ph)

        p.setPen(QColor("#607d8b"))
        for db in (0, -20, -40, -60, -80):
            y = int(self._db_to_y(db, ph, mt))
            p.drawText(QRectF(0, y - 8, ml - 3, 16),
                       Qt.AlignRight | Qt.AlignVCenter,
                       str(db))

        freq_per_bin = self.SAMPLE_RATE / self.FFT_SIZE
        for khz in range(1, 9):
            bin_idx = int(khz * 1000 / freq_per_bin)
            if bin_idx >= self._max_bin:
                break
            x = int(self._bin_to_x(bin_idx, ml, pw))
            p.drawText(QRectF(x - 15, mt + ph + 2, 30, self._MB - 2),
                       Qt.AlignCenter,
                       f"{khz}k")
