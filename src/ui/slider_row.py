"""
ui.slider_row — widget reutilizable de control con slider.

Combina una etiqueta, un QSlider horizontal y una etiqueta de valor con unidad.
Internamente trabaja con enteros (QSlider) y escala a float según step y min/max.
Soporta cualquier rango y paso flotante (ej: -20 a +20 dB con step 0.5).
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSlider, QMenu
from PySide6.QtCore import Qt, Signal


class SliderRow(QWidget):
    """
    Fila de control con: [label] [slider] [valor + unidad]

    Maneja valores float escalando internamente a enteros para QSlider.
    """
    valueChanged = Signal(float)

    def __init__(
        self,
        label: str,
        min_val: float,
        max_val: float,
        default: float,
        step: float = 1.0,
        unit: str = "",
        fmt: str = "{:.0f}",
        label_width: int = 140,
        value_width: int = 72,
        parent=None,
    ):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._default = default
        self._step = step
        self._unit = unit
        self._fmt = fmt
        self._n_steps = round((max_val - min_val) / step)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self._lbl = QLabel(label)
        self._lbl.setFixedWidth(label_width)
        layout.addWidget(self._lbl)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, self._n_steps)
        self._slider.setValue(self._to_int(default))
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._slider.setContextMenuPolicy(Qt.CustomContextMenu)
        self._slider.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._slider, stretch=1)

        self._val_lbl = QLabel()
        self._val_lbl.setFixedWidth(value_width)
        self._val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._val_lbl)

        self._update_label(default)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def value(self) -> float:
        return self._from_int(self._slider.value())

    def set_value(self, val: float, emit: bool = False) -> None:
        self._slider.blockSignals(not emit)
        self._slider.setValue(self._to_int(val))
        self._slider.blockSignals(False)
        self._update_label(val)

    def set_enabled(self, enabled: bool) -> None:
        self._slider.setEnabled(enabled)
        self._lbl.setEnabled(enabled)
        self._val_lbl.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _to_int(self, val: float) -> int:
        return round((val - self._min) / self._step)

    def _from_int(self, i: int) -> float:
        return self._min + i * self._step

    def _on_slider_changed(self, i: int) -> None:
        val = self._from_int(i)
        self._update_label(val)
        self.valueChanged.emit(val)

    def _update_label(self, val: float) -> None:
        self._val_lbl.setText(self._fmt.format(val) + (" " + self._unit if self._unit else ""))

    def _show_context_menu(self, pos) -> None:
        default_str = self._fmt.format(self._default)
        if self._unit:
            default_str += f" {self._unit}"
        menu = QMenu(self)
        action = menu.addAction(f"↺  Restaurar por defecto  ({default_str})")
        if menu.exec(self._slider.mapToGlobal(pos)) == action:
            self.set_value(self._default, emit=True)
