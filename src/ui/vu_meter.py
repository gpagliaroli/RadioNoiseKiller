from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtCore import Qt, QRect


class VuMeter(QWidget):
    """Widget de VU meter horizontal en dBFS (-60 a 0 dB)."""

    FLOOR_DB = -60.0

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._label = label
        self._level_db = self.FLOOR_DB
        self.setMinimumSize(180, 18)
        self.setMaximumHeight(18)

    def set_level(self, db: float) -> None:
        self._level_db = max(self.FLOOR_DB, min(0.0, db))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        fraction = (self._level_db - self.FLOOR_DB) / (-self.FLOOR_DB)
        fill_w = int(w * fraction)

        # Fondo
        p.fillRect(0, 0, w, h, QColor("#1a1a2e"))

        # Gradiente: verde → amarillo → rojo
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0,  QColor("#00c853"))  # verde
        grad.setColorAt(0.75, QColor("#ffd600"))  # amarillo
        grad.setColorAt(1.0,  QColor("#d50000"))  # rojo
        p.fillRect(0, 1, fill_w, h - 2, grad)

        # Borde
        p.setPen(QColor("#444"))
        p.drawRect(0, 0, w - 1, h - 1)

        # Texto — font explícito para evitar pointSize=-1 en displays con escalado
        font = p.font()
        if font.pointSize() <= 0:
            font.setPointSize(8)
            p.setFont(font)
        p.setPen(QColor("#ddd"))
        db_str = f"{self._label} {self._level_db:+.1f} dB"
        p.drawText(QRect(4, 0, w - 8, h), Qt.AlignVCenter | Qt.AlignLeft, db_str)
