from __future__ import annotations
import numpy as np
from collections import deque
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPolygonF, QBrush
from i18n import tr


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
    MAX_FREQ_HZ = 12_000
    DB_MIN      = -80.0
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

        self._db_max      =   0.0          # controlado por el slider Máx Y
        self._max_freq_hz = self.MAX_FREQ_HZ  # controlado por el slider Máx X

        n_bins = self.FFT_SIZE // 2 + 1
        self._db_pre   = np.full(n_bins, self.DB_MIN, dtype=np.float32)
        self._db_post  = np.full(n_bins, self.DB_MIN, dtype=np.float32)
        self._db_floor: np.ndarray | None = None
        self._ema_pre  = None
        self._ema_post = None
        self._window   = np.hanning(self.FFT_SIZE).astype(np.float32)

        self._freq_per_bin = self.SAMPLE_RATE / self.FFT_SIZE
        self._n_bins       = n_bins
        self._update_max_bin()

        self._active         = False
        self._show_pre       = True
        self._show_post      = True
        self._show_cancelled = True
        self._show_floor     = True

        self._floor_learning = False

        # Cascada (waterfall): widget hermano al que empujamos la fila dB cruda
        # (instantánea, sin EMA) de la fuente elegida. None = sin cascada.
        self.waterfall            = None
        self._waterfall_on        = False
        self._waterfall_source    = "input"   # "input" | "output" | "diff"

        self._timer = QTimer(self)
        self._timer.setInterval(67)   # ~15 fps — reduce GIL contention con el thread de audio
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

    @property
    def has_floor(self) -> bool:
        """True si hay una curva de piso de ruido cargada en el widget."""
        return self._db_floor is not None

    def set_noise_floor_from_hz(self, freqs_hz: np.ndarray, db: np.ndarray) -> None:
        """Actualiza el piso de ruido desde datos (freqs_hz, db) — usado por el modo MCRA."""
        widget_freqs = np.arange(self._n_bins, dtype=np.float32) * self._freq_per_bin
        interpolated = np.interp(widget_freqs, freqs_hz, db).astype(np.float32)
        self._db_floor = np.clip(interpolated, self.DB_MIN, 0.0)
        self.update()

    def set_db_max(self, db_max: int) -> None:
        self._db_max = float(db_max)
        self.update()

    def set_max_freq_hz(self, hz: int) -> None:
        self._max_freq_hz = max(1000, min(hz, self.MAX_FREQ_HZ))
        self._update_max_bin()
        self.update()

    def set_waterfall_enabled(self, on: bool) -> None:
        """Activa/desactiva el empuje de filas a la cascada (cuando está oculta
        no computamos la FFT de su fuente para no gastar CPU)."""
        self._waterfall_on = bool(on)

    def set_waterfall_source(self, source: str) -> None:
        self._waterfall_source = source if source in ("input", "output", "diff") else "input"

    def _update_max_bin(self) -> None:
        self._max_bin = min(self._n_bins,
                            int(self._max_freq_hz / self._freq_per_bin) + 1)

    # ------------------------------------------------------------------
    # Actualización (hilo UI)
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        if not self.isVisible():
            return
        changed = False
        wf_diff = self._waterfall_on and self._waterfall_source == "diff"
        wf_pre  = wf_diff or (self._waterfall_on and self._waterfall_source == "input")
        wf_post = wf_diff or (self._waterfall_on and self._waterfall_source == "output")
        raw_pre = raw_post = None

        if self._show_pre or self._show_cancelled or self._floor_learning or wf_pre:
            frames = list(self.pre_frames)
            if frames:
                db = self._compute_db(np.concatenate(frames))
                raw_pre = db
                db = np.clip(db, self.DB_MIN, 0.0)
                self._ema_pre = db if self._ema_pre is None else (
                    self.ALPHA * db + (1.0 - self.ALPHA) * self._ema_pre
                )
                self._db_pre = self._ema_pre
                changed = True

        if self._show_post or self._show_cancelled or wf_post:
            frames = list(self.post_frames)
            if frames:
                db = self._compute_db(np.concatenate(frames))
                raw_post = db
                db = np.clip(db, self.DB_MIN, 0.0)
                self._ema_post = db if self._ema_post is None else (
                    self.ALPHA * db + (1.0 - self.ALPHA) * self._ema_post
                )
                self._db_post = self._ema_post
                changed = True

        # Empujar la fila CRUDA (instantánea, sin EMA) a la cascada. En modo
        # Diferencia hace falta que las DOS estén disponibles en el mismo tick;
        # si falta una no se empuja nada (mejor un hueco que una fila falsa).
        if self.waterfall is not None and self._waterfall_on:
            if wf_diff:
                row = (raw_pre - raw_post
                       if raw_pre is not None and raw_post is not None else None)
            else:
                row = raw_pre if self._waterfall_source == "input" else raw_post
            if row is not None:
                self.waterfall.push_row(row)

        if changed:
            self.update()

    def _compute_db(self, samples: np.ndarray) -> np.ndarray:
        """dB SIN clipear. El clip a [DB_MIN, 0] lo hace el llamador para las
        curvas; la cascada en modo Diferencia necesita el valor crudo, porque
        recortar ambos lados a −80 dB haría desaparecer justo la supresión más
        profunda (entrada y salida chocarían contra el mismo piso → diff ≈ 0)."""
        if len(samples) < self.FFT_SIZE:
            samples = np.pad(samples, (self.FFT_SIZE - len(samples), 0))
        else:
            samples = samples[-self.FFT_SIZE:]
        mag = np.abs(np.fft.rfft(samples * self._window))
        mag = np.maximum(mag, 1e-10)
        db  = 20.0 * np.log10(mag / (self.FFT_SIZE / 2.0))
        return db.astype(np.float32)

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
                       tr("Activar el procesamiento para ver el espectro"))
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
    # Helpers de coordenadas (vectorizados con numpy — GIL libre en el cómputo)
    # ------------------------------------------------------------------

    def _db_to_y(self, db: float, ph: int, mt: int) -> float:
        frac = (db - self.DB_MIN) / (self._db_max - self.DB_MIN)
        return mt + ph * (1.0 - frac)

    def _bin_to_x(self, bin_idx: int, ml: int, pw: int) -> float:
        return ml + pw * bin_idx / max(self._max_bin - 1, 1)

    def _compute_xy(self, bins: np.ndarray, ml: int, mt: int,
                    pw: int, ph: int) -> tuple[np.ndarray, np.ndarray]:
        """Devuelve (xs, ys) como arrays float32; el cómputo numpy libera el GIL."""
        n   = len(bins)
        xs  = ml + pw * (np.arange(n, dtype=np.float32) / max(self._max_bin - 1, 1))
        frac = np.clip(
            (bins.astype(np.float32) - self.DB_MIN) / (self._db_max - self.DB_MIN),
            0.0, 1.0
        )
        ys  = (mt + ph * (1.0 - frac)).astype(np.float32)
        return xs, ys

    @staticmethod
    def _to_polyline(xs: np.ndarray, ys: np.ndarray) -> QPolygonF:
        return QPolygonF([QPointF(float(x), float(y)) for x, y in zip(xs, ys)])

    # ------------------------------------------------------------------
    # Primitivas de dibujo  (QPolygonF en lugar de QPainterPath/lineTo)
    # ------------------------------------------------------------------

    def _draw_curve(self, p: QPainter,
                    db_arr: np.ndarray,
                    fill_color: QColor, line_color: QColor,
                    ml: int, mt: int, pw: int, ph: int) -> None:
        bins = db_arr[:self._max_bin]
        xs, ys = self._compute_xy(bins, ml, mt, pw, ph)
        bottom = float(mt + ph)

        # Relleno — sin antialiasing (no se nota en áreas planas)
        fill_pts = ([QPointF(float(xs[0]), bottom)]
                    + [QPointF(float(x), float(y)) for x, y in zip(xs, ys)]
                    + [QPointF(float(xs[-1]), bottom)])
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setBrush(QBrush(fill_color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF(fill_pts))

        # Línea con antialiasing
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(line_color, 1.2))
        p.drawPolyline(self._to_polyline(xs, ys))

    def _draw_line_only(self, p: QPainter,
                        db_arr: np.ndarray,
                        color: QColor,
                        ml: int, mt: int, pw: int, ph: int) -> None:
        bins = db_arr[:self._max_bin]
        xs, ys = self._compute_xy(bins, ml, mt, pw, ph)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(color, 1.2))
        p.drawPolyline(self._to_polyline(xs, ys))

    def _draw_cancelled(self, p: QPainter,
                         ml: int, mt: int, pw: int, ph: int) -> None:
        bins_pre  = self._db_pre[:self._max_bin]
        bins_post = self._db_post[:self._max_bin]
        xs, ys_pre  = self._compute_xy(bins_pre,  ml, mt, pw, ph)
        _,  ys_post = self._compute_xy(bins_post, ml, mt, pw, ph)
        # Borde inferior: max(y_pre, y_post) en coords pantalla
        ys_bot = np.maximum(ys_pre, ys_post)
        # Polígono: curva pre (izq→der) + borde inferior (der→izq)
        pts = ([QPointF(float(x), float(y)) for x, y in zip(xs, ys_pre)]
               + [QPointF(float(x), float(y)) for x, y in zip(reversed(xs), reversed(ys_bot))])
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setBrush(QBrush(QColor(255, 112, 67, 100)))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF(pts))

    def _draw_floor_line(self, p: QPainter,
                          db_floor: np.ndarray,
                          ml: int, mt: int, pw: int, ph: int) -> None:
        bins = db_floor[:self._max_bin]
        xs, ys = self._compute_xy(bins, ml, mt, pw, ph)
        pen = QPen(QColor(255, 213, 79), 1.5)
        pen.setStyle(Qt.DashLine)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(pen)
        p.drawPolyline(self._to_polyline(xs, ys))

    def _draw_grid(self, p: QPainter,
                   ml: int, mt: int, pw: int, ph: int) -> None:
        pen = QPen(QColor("#1e2d40"), 1)
        pen.setStyle(Qt.DotLine)
        p.setPen(pen)

        db = -20
        while db >= self.DB_MIN:
            y = int(self._db_to_y(float(db), ph, mt))
            if mt <= y <= mt + ph:
                p.drawLine(ml, y, ml + pw, y)
            db -= 20

        for khz in range(1, 13):
            bin_idx = int(khz * 1000 / self._freq_per_bin)
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
        # etiquetas desde el máximo visible hacia abajo, cada 20 dB
        db = int(self._db_max // 20) * 20   # múltiplo de 20 más cercano por debajo del techo
        while db >= self.DB_MIN:
            y = int(self._db_to_y(float(db), ph, mt))
            if mt - 8 <= y <= mt + ph + 8:
                p.drawText(QRectF(0, y - 8, ml - 3, 16),
                           Qt.AlignRight | Qt.AlignVCenter,
                           str(db))
            db -= 20

        for khz in range(1, 13):
            bin_idx = int(khz * 1000 / self._freq_per_bin)
            if bin_idx >= self._max_bin:
                break
            x = int(self._bin_to_x(bin_idx, ml, pw))
            p.drawText(QRectF(x - 15, mt + ph + 2, 30, self._MB - 2),
                       Qt.AlignCenter,
                       f"{khz}k")
