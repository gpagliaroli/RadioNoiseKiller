"""
Grupo "Memorias" de la solapa CAT: emisoras guardadas (nombre + frecuencia +
modo) que se sintonizan por CAT con doble clic o "Sintonizar".

Sólo UI y archivo: no conoce al cliente CAT. Pide sintonizar / guardar la
frecuencia actual con señales que conecta MainWindow.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

import memories
from i18n import get_language, tr
from utils import data_dir

_COLUMNS = ["Nombre", "Frecuencia", "Modo"]


class MemoriesPanel(QGroupBox):
    tune_requested = Signal(int, str, str)    # freq_hz, modo, nombre
    save_current_requested = Signal()

    def __init__(self, store: "memories.MemoryStore | None" = None, parent=None):
        super().__init__(tr("Memorias"), parent)
        self._store = store or memories.MemoryStore()
        self._store.load()
        self._connected = None
        self._build_ui()
        self._refresh()
        self.set_connected(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([tr(c) for c in _COLUMNS])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

        row = QHBoxLayout()
        self._btn_save = QPushButton(tr("Guardar actual"))
        self._btn_save.setToolTip(tr(
            "Guarda la frecuencia y el modo de la radio. El nombre sale de la\n"
            "emisora EiBi en el aire en esa frecuencia, si hay."))
        self._btn_tune = QPushButton(tr("Sintonizar"))
        self._btn_tune.setToolTip(tr(
            "Lleva la radio a la memoria elegida (también con doble clic).\n"
            "El preset lo carga la tabla de modos de arriba."))
        self._btn_delete = QPushButton(tr("Borrar"))
        # Textos cortos: la fila entra justa en el ancho fijo de la ventana.
        self._btn_import = QPushButton(tr("Importar…"))
        self._btn_import.setToolTip(tr(
            "Agrega memorias desde un CSV con columnas name;freq_khz;mode\n"
            "(las que ya existen se saltean)."))
        self._btn_export = QPushButton(tr("Exportar…"))
        self._btn_export.setToolTip(tr("Guarda todas las memorias en un CSV (name;freq_khz;mode)."))
        for b in (self._btn_save, self._btn_tune, self._btn_delete):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self._btn_import)
        row.addWidget(self._btn_export)
        root.addLayout(row)

        note = QLabel(tr(
            "Doble clic para sintonizar; F2 para renombrar. También se guardan desde "
            "la solapa EiBi (\"Guardar en memorias\")."))
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 8pt;")
        root.addWidget(note)

        self._table.itemDoubleClicked.connect(lambda *_: self._on_tune())
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.itemSelectionChanged.connect(self._update_buttons)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._btn_save.clicked.connect(self.save_current_requested)
        self._btn_tune.clicked.connect(self._on_tune)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_import.clicked.connect(self._on_import)
        self._btn_export.clicked.connect(self._on_export)

    # ------------------------------------------------------------------

    def set_connected(self, connected: bool) -> None:
        # Lo llama el timer del CAT cada 500 ms: sólo actuar si cambió.
        if connected == self._connected:
            return
        self._connected = connected
        self._update_buttons()

    def add_memory(self, name: str, freq_hz: int, mode: str) -> bool:
        """Agrega (o encuentra) la memoria, la selecciona y guarda. True si era nueva."""
        m = memories.Memory(name.strip() or memories.default_name(freq_hz, mode, get_language()),
                            int(freq_hz), (mode or "").strip().upper())
        i, new = self._store.add(m)
        if new:
            self._save()
            self._refresh()
        self._table.selectRow(i)
        self._table.scrollToItem(self._table.item(i, 0))
        return new

    def memory_names(self) -> list:
        return [m.name for m in self._store.items]

    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._store.items))
        for r, m in enumerate(self._store.items):
            name = QTableWidgetItem(m.name)
            freq = QTableWidgetItem(memories.default_name(m.freq_hz, "", get_language()))
            mode = QTableWidgetItem(m.mode)
            freq.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for it in (freq, mode):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(r, 0, name)
            self._table.setItem(r, 1, freq)
            self._table.setItem(r, 2, mode)
        self._table.blockSignals(False)
        self._update_buttons()

    def _save(self) -> None:
        try:
            self._store.save()
        except OSError as e:
            QMessageBox.warning(self, tr("Error al guardar las memorias"), str(e))

    def _current(self) -> int:
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _update_buttons(self) -> None:
        sel = self._current() >= 0
        self._btn_save.setEnabled(bool(self._connected))
        self._btn_tune.setEnabled(bool(self._connected) and sel)
        self._btn_delete.setEnabled(sel)
        self._btn_export.setEnabled(len(self._store) > 0)

    def _on_tune(self) -> None:
        i = self._current()
        if i < 0 or not self._connected:
            return
        m = self._store.items[i]
        self.tune_requested.emit(m.freq_hz, m.mode, m.name)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        r = item.row()
        self._store.rename(r, item.text())
        self._save()
        self._table.blockSignals(True)
        item.setText(self._store.items[r].name)
        self._table.blockSignals(False)

    def _on_delete(self) -> None:
        i = self._current()
        if i < 0:
            return
        name = self._store.items[i].name
        ans = QMessageBox.question(self, tr("Confirmar eliminacion"),
                                   tr("Borrar la memoria '{name}'?").format(name=name))
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._store.remove(i)
        self._save()
        self._refresh()

    def _on_context_menu(self, pos) -> None:
        item = self._table.itemAt(pos)
        if item is None:
            return
        self._table.selectRow(item.row())
        menu = QMenu(self)
        act_tune = menu.addAction(tr("Sintonizar"))
        act_tune.setEnabled(bool(self._connected))
        act_rename = menu.addAction(tr("Renombrar"))
        act_delete = menu.addAction(tr("Borrar"))
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is act_tune:
            self._on_tune()
        elif chosen is act_rename:
            self._table.editItem(self._table.item(item.row(), 0))
        elif chosen is act_delete:
            self._on_delete()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Importar memorias"), data_dir(), "CSV (*.csv)")
        if not path:
            return
        try:
            n = self._store.import_csv(path)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            QMessageBox.warning(self, tr("Error al importar"), str(e))
            return
        if n:
            self._save()
            self._refresh()
        QMessageBox.information(self, tr("Importar memorias"),
                                tr("Se agregaron {n} memorias.").format(n=n))

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Exportar memorias"), "memorias.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            self._store.export_csv(path)
        except OSError as e:
            QMessageBox.warning(self, tr("Error al exportar"), str(e))
