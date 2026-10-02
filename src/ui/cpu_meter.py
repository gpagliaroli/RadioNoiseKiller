from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtCore import Qt, QRect


class CpuMeter(QWidget):
    """Widget de medidor de carga de CPU del hilo procesador, en % del
    presupuesto de tiempo real de un frame (ver Pipeline.cpu_load_pct).
    100% = el procesado tarda tanto como el hueco real-time disponible —
    más que eso es la firma de un underrun.

    A propósito NO calca el estilo de VuMeter (barra llena + texto superpuesto
    con doble clip): el usuario pidió que se distinga a simple vista de los VU
    de la misma fila — barra más angosta (8px vs. 18px) y texto AFUERA de la
    barra (etiqueta a la izquierda, porcentaje a la derecha), no encima."""

    CEIL_PCT = 150.0   # tope visual: más que esto ya está en underrun franco
    BAR_H    = 8
    LABEL_W  = 30
    PCT_W    = 34

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._label = label
        self._load_pct = 0.0
        self.setMinimumSize(180, 14)
        self.setFixedHeight(14)

    def set_load(self, pct: float) -> None:
        self._load_pct = max(0.0, min(self.CEIL_PCT, pct))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        font = p.font()
        if font.pointSize() <= 0:
            font.setPointSize(8)
            p.setFont(font)

        # Etiqueta, a la izquierda — afuera de la barra (no encima).
        p.setPen(QColor("#888"))
        p.drawText(QRect(0, 0, self.LABEL_W, h),
                   Qt.AlignVCenter | Qt.AlignLeft, self._label)

        bar_x0 = self.LABEL_W
        bar_w  = max(0, w - self.LABEL_W - self.PCT_W)
        bar_y  = (h - self.BAR_H) // 2
        fraction = self._load_pct / self.CEIL_PCT
        fill_w = int(bar_w * fraction)

        p.fillRect(bar_x0, bar_y, bar_w, self.BAR_H, QColor("#1a1a2e"))
        if fill_w > 0:
            grad = QLinearGradient(bar_x0, 0, bar_x0 + bar_w, 0)
            grad.setColorAt(0.0,  QColor("#29b6f6"))  # celeste: holgado
            grad.setColorAt(0.5,  QColor("#ff9100"))  # naranja: ~75% del presupuesto
            grad.setColorAt(0.67, QColor("#d50000"))  # rojo: 100% del presupuesto (underrun)
            p.fillRect(bar_x0, bar_y, fill_w, self.BAR_H, grad)
        p.setPen(QColor("#444"))
        p.drawRect(bar_x0, bar_y, bar_w - 1, self.BAR_H - 1)

        # Porcentaje, a la derecha — también afuera de la barra.
        p.setPen(QColor("#ccc"))
        p.drawText(QRect(bar_x0 + bar_w, 0, self.PCT_W, h),
                   Qt.AlignVCenter | Qt.AlignRight, f"{self._load_pct:.0f}%")
