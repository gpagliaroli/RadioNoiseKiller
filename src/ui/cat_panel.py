"""
Grupo "Radio (CAT — rigctld)" de la pestaña Presets: activar, host/puerto,
estado de la conexión y la tabla grupo de modo -> preset.

Sólo UI y config: el cliente (cat.RigctldClient) y la decisión de cargar un
preset viven en MainWindow, que lee el estado con su propio timer.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout,
)

import cat
from config import AppConfig
from i18n import tr

_NO_CHANGE = ""

# Etiqueta de cada grupo en la tabla (qué modos de la radio abarca).
_GROUP_LABELS = {
    "SSB": "SSB (USB / LSB)",
    "AM":  "AM (AM / SAM)",
    "FM":  "FM",
    "WFM": "FM ancha (WFM)",
    "CW":  "CW",
}


class CatPanel(QGroupBox):
    connection_changed = Signal()   # activar / host / puerto -> reiniciar el cliente
    mapping_changed = Signal()      # tabla modo -> preset -> guardar

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(tr("Radio (CAT — rigctld de Hamlib)"), parent)
        self._config = config
        self._combos: "dict[str, QComboBox]" = {}
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        row = QHBoxLayout()
        self._chk_enabled = QCheckBox(tr("Activar"))
        self._chk_enabled.setToolTip(tr(
            "Lee la frecuencia y el modo de la radio desde rigctld (Hamlib).\n"
            "Al cambiar de modo carga el preset de la tabla. rigctld tiene que\n"
            "estar corriendo: ver el capítulo Control de la radio del manual."))
        row.addWidget(self._chk_enabled)
        row.addSpacing(12)
        row.addWidget(QLabel(tr("Host:")))
        self._edit_host = QLineEdit()
        self._edit_host.setFixedWidth(130)
        self._edit_host.setToolTip(tr("Equipo donde corre rigctld (127.0.0.1 = esta misma PC)."))
        row.addWidget(self._edit_host)
        row.addWidget(QLabel(tr("Puerto:")))
        self._spin_port = QSpinBox()
        self._spin_port.setRange(1, 65535)
        self._spin_port.setKeyboardTracking(False)
        self._spin_port.setToolTip(tr("Puerto TCP de rigctld (4532 por defecto)."))
        row.addWidget(self._spin_port)
        row.addStretch()
        root.addLayout(row)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #777777; font-size: 8pt;")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel(tr("Modo de la radio")), 0, 0)
        grid.addWidget(QLabel(tr("Preset que se carga")), 0, 1)
        for i, g in enumerate(cat.MODE_GROUPS, start=1):
            grid.addWidget(QLabel(tr(_GROUP_LABELS[g])), i, 0)
            combo = QComboBox()
            combo.setMinimumWidth(280)
            combo.currentIndexChanged.connect(self._on_mapping_changed)
            self._combos[g] = combo
            grid.addWidget(combo, i, 1)
        grid.setColumnStretch(2, 1)
        root.addLayout(grid)

        note = QLabel(tr(
            "El preset se carga cuando el modo nuevo se mantiene 1 segundo. Si el preset "
            "activo tiene cambios sin guardar (modificado), no se reemplaza."))
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 8pt;")
        root.addWidget(note)

        self._chk_enabled.toggled.connect(self._on_connection_edited)
        self._edit_host.editingFinished.connect(self._on_connection_edited)
        self._spin_port.valueChanged.connect(self._on_connection_edited)

    def _load_values(self) -> None:
        c = self._config.cat
        for w in (self._chk_enabled, self._edit_host, self._spin_port):
            w.blockSignals(True)
        self._chk_enabled.setChecked(c.enabled)
        self._edit_host.setText(c.host)
        self._spin_port.setValue(c.port)
        for w in (self._chk_enabled, self._edit_host, self._spin_port):
            w.blockSignals(False)
        self._update_enabled_state()

    # ------------------------------------------------------------------

    def set_preset_names(self, names: list) -> None:
        """Rellena los combos con los presets existentes. Un preset de la tabla que
        ya no existe se muestra igual, marcado, para que no se pierda en silencio."""
        for g, combo in self._combos.items():
            current = self._config.cat.mode_presets.get(g, "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("(no cambiar)"), _NO_CHANGE)
            for n in names:
                combo.addItem(n, n)
            if current and current not in names:
                combo.addItem(tr("{name} (no existe)").format(name=current), current)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def set_status(self, text: str, color: str) -> None:
        # Lo llama un timer cada 500 ms: no re-aplicar el stylesheet si no cambió
        # (recalcular estilos en la Pi le roba tiempo al hilo del DSP).
        if (text, color) == getattr(self, "_status_now", None):
            return
        self._status_now = (text, color)
        self._lbl_status.setText(text)
        self._lbl_status.setStyleSheet(f"color: {color}; font-size: 8pt;")

    # ------------------------------------------------------------------

    def _update_enabled_state(self) -> None:
        on = self._chk_enabled.isChecked()
        self._edit_host.setEnabled(not on)
        self._spin_port.setEnabled(not on)
        if not on:
            self.set_status(tr("Desactivado."), "#777777")

    def _on_connection_edited(self, *_) -> None:
        c = self._config.cat
        host = self._edit_host.text().strip() or cat.DEFAULT_HOST
        if self._edit_host.text() != host:
            self._edit_host.setText(host)
        changed = (c.enabled, c.host, c.port) != (
            self._chk_enabled.isChecked(), host, self._spin_port.value())
        c.enabled = self._chk_enabled.isChecked()
        c.host = host
        c.port = self._spin_port.value()
        self._update_enabled_state()
        if changed:
            self.connection_changed.emit()

    def _on_mapping_changed(self, *_) -> None:
        for g, combo in self._combos.items():
            self._config.cat.mode_presets[g] = combo.currentData() or _NO_CHANGE
        self.mapping_changed.emit()
