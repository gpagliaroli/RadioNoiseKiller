from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QMessageBox, QInputDialog,
)
from PySide6.QtCore import Signal
from config import AppConfig
from pipeline import ProcessingPipeline
from presets import PresetManager
from i18n import tr


class PresetsTab(QWidget):
    """Pestaña de gestion de presets DSP.

    Emite preset_loaded despues de aplicar un preset en caliente,
    para que MainWindow actualice la UI con los nuevos valores.
    """
    preset_loaded = Signal()
    state_changed = Signal()   # cambió last_preset → MainWindow agenda el guardado

    def __init__(self, config: AppConfig, pipeline: ProcessingPipeline,
                 manager: PresetManager, parent=None):
        super().__init__(parent)
        self._config   = config
        self._pipeline = pipeline
        self._manager  = manager
        self._active: str | None = None
        self._build_ui()
        self._refresh_list()
        # Restaurar el preset activo de la sesión anterior (solo informativo)
        lp = config.last_preset
        if lp and self._manager.exists(lp):
            self._set_active(lp, modified=not self._manager.matches(lp, config))
            self._select_by_name(lp)

    def showEvent(self, event) -> None:
        # Re-evaluar "(modificado)" cada vez que se muestra la pestaña:
        # el usuario pudo haber retocado sliders desde la última vez.
        super().showEvent(event)
        if self._active and self._manager.exists(self._active):
            self._set_active(
                self._active,
                modified=not self._manager.matches(self._active, self._config),
            )

    # ------------------------------------------------------------------ #
    # Construccion de la UI                                               #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(QLabel(tr("Presets guardados:")))
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._on_load)
        root.addWidget(self._list, 1)

        name_row = QHBoxLayout()
        lbl_name = QLabel(tr("Nombre:"))
        lbl_name.setFixedWidth(60)
        name_row.addWidget(lbl_name)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("Nombre del preset..."))
        self._name_edit.textChanged.connect(self._update_button_states)
        name_row.addWidget(self._name_edit)
        root.addLayout(name_row)

        btn1 = QHBoxLayout()
        self._btn_save_new  = QPushButton(tr("Guardar como nuevo"))
        self._btn_overwrite = QPushButton(tr("Sobrescribir seleccionado"))
        btn1.addWidget(self._btn_save_new)
        btn1.addWidget(self._btn_overwrite)
        root.addLayout(btn1)

        btn2 = QHBoxLayout()
        self._btn_load   = QPushButton(tr("Cargar"))
        self._btn_delete = QPushButton(tr("Eliminar"))
        btn2.addWidget(self._btn_load)
        btn2.addWidget(self._btn_delete)
        root.addLayout(btn2)

        self._btn_rename = QPushButton(tr("Renombrar seleccionado"))
        root.addWidget(self._btn_rename)

        active_row = QHBoxLayout()
        lbl_act = QLabel(tr("Preset activo:"))
        lbl_act.setFixedWidth(90)
        active_row.addWidget(lbl_act)
        self._lbl_active = QLabel(tr("(ninguno)"))
        self._lbl_active.setStyleSheet("color: #90caf9; font-weight: bold;")
        active_row.addWidget(self._lbl_active)
        active_row.addStretch()
        root.addLayout(active_row)

        note = QLabel(
            tr("Cargar un preset aplica todos los ajustes DSP y Ganancia\n"
            "en caliente, sin reiniciar el audio.\n"
            "Doble-clic en la lista carga el preset directamente.")
        )
        note.setStyleSheet("color: #888; font-size: 8pt;")
        root.addWidget(note)

        self._btn_save_new.clicked.connect(self._on_save_new)
        self._btn_overwrite.clicked.connect(self._on_overwrite)
        self._btn_load.clicked.connect(self._on_load)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_rename.clicked.connect(self._on_rename)

        self._update_button_states()

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self, row: int) -> None:
        item = self._list.item(row)
        if item:
            self._name_edit.setText(item.text())
        self._update_button_states()

    def _on_save_new(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            return
        if self._manager.exists(name):
            ans = QMessageBox.question(
                self, tr("Confirmar reemplazo"),
                tr("Ya existe un preset llamado '{name}'.\n\nDeseas reemplazarlo?").format(name=name),
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._manager.save(name, self._config)
        self._set_active(name)
        self._refresh_list()
        self._select_by_name(name)

    def _on_overwrite(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        name = item.text()
        self._manager.save(name, self._config)
        self._set_active(name)
        # Tras sobrescribir, la config ya coincide con el preset → el estado
        # "(modificado)" cambió aunque el nombre activo no. _set_active solo
        # emite state_changed si el nombre cambia, así que lo forzamos para que
        # MainWindow recalcule el título de la ventana (si no, queda "(modificado)").
        self.state_changed.emit()

    def _on_load(self, *_) -> None:
        item = self._list.currentItem()
        if not item:
            return
        name = item.text()
        try:
            self._manager.load_into(name, self._config)
            self._pipeline.apply_config(self._config)
            self._set_active(name)
            self.preset_loaded.emit()
        except Exception as e:
            QMessageBox.warning(self, tr("Error al cargar preset"), str(e))

    def _on_delete(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        name = item.text()
        ans = QMessageBox.question(
            self, tr("Confirmar eliminacion"),
            tr("Eliminar el preset '{name}'?").format(name=name),
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._manager.delete(name)
        if self._active == name:
            self._active = None
            self._lbl_active.setText(tr("(ninguno)"))
            self._config.last_preset = ""
            self.state_changed.emit()
        self._refresh_list()

    def _on_rename(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        old = item.text()
        new, ok = QInputDialog.getText(
            self, tr("Renombrar preset"), tr("Nuevo nombre:"), text=old
        )
        new = new.strip()
        if not ok or not new or new == old:
            return
        if self._manager.exists(new):
            QMessageBox.warning(self, tr("Nombre en uso"),
                                tr("Ya existe un preset llamado '{name}'.").format(name=new))
            return
        try:
            self._manager.rename(old, new)
            if self._active == old:
                self._set_active(new)
            self._refresh_list()
            self._select_by_name(new)
        except Exception as e:
            QMessageBox.warning(self, tr("Error al renombrar"), str(e))

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _set_active(self, name: str, modified: bool = False) -> None:
        self._active = name
        self._lbl_active.setText(tr("{name}  (modificado)").format(name=name) if modified else name)
        if self._config.last_preset != name:
            self._config.last_preset = name
            self.state_changed.emit()

    def _refresh_list(self) -> None:
        current = self._list.currentItem()
        current_name = current.text() if current else None
        self._list.clear()
        for name in self._manager.list_names():
            self._list.addItem(QListWidgetItem(name))
        if current_name:
            self._select_by_name(current_name)
        self._update_button_states()

    def _select_by_name(self, name: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).text() == name:
                self._list.setCurrentRow(i)
                return

    def _update_button_states(self, *_) -> None:
        has_selection = self._list.currentItem() is not None
        has_name      = bool(self._name_edit.text().strip())
        self._btn_save_new.setEnabled(has_name)
        self._btn_overwrite.setEnabled(has_selection)
        self._btn_load.setEnabled(has_selection)
        self._btn_delete.setEnabled(has_selection)
        self._btn_rename.setEnabled(has_selection)
