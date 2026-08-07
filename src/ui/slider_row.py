"""
ui.slider_row — widget reutilizable de control con slider.

Combina una etiqueta, un QSlider horizontal y una etiqueta de valor con unidad.
Internamente trabaja con enteros (QSlider) y escala a float según step y min/max.
Soporta cualquier rango y paso flotante (ej: -20 a +20 dB con step 0.5).
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSlider, QMenu
from PySide6.QtCore import Qt, Signal
from i18n import tr


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
        label_width: int = 150,
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
        # Largo FIJO (pedido del usuario): el slider no se estira. El sobrante lo
        # absorbe un stretch al final, así nombre + slider + valor quedan juntos a
        # la izquierda y el espacio libre va a la derecha.
        self._slider.setFixedWidth(400)
        layout.addWidget(self._slider)

        self._val_lbl = QLabel()
        self._val_lbl.setFixedWidth(value_width)
        # Alineado a la izquierda: el valor queda pegado al final del slider
        self._val_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._val_lbl)
        layout.addStretch()

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

    def setToolTip(self, text: str) -> None:
        """Propaga el tooltip a los HIJOS, no solo al contenedor.

        Sin esto el tooltip solo aparece al pasar por los pocos pixeles de la
        fila que no ocupa ninguno de los tres widgets — es decir, casi nunca:
        justo sobre el slider (que es donde el usuario apunta) no se muestra.
        Mismo patron que set_enabled, que tampoco sirve sobre el contenedor."""
        super().setToolTip(text)
        for w in (self._lbl, self._slider, self._val_lbl):
            w.setToolTip(text)

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
        # Reutiliza _update_label (incluyendo overrides de porcentaje, etc.)
        # para obtener el texto exacto que se mostraría con el valor default.
        current_val = self.value()
        self._update_label(self._default)
        default_str = self._val_lbl.text()
        self._update_label(current_val)

        menu = QMenu(self)
        action = menu.addAction(tr("↺  Restaurar por defecto  ({val})").format(val=default_str))
        if menu.exec(self._slider.mapToGlobal(pos)) == action:
            self.set_value(self._default, emit=True)
