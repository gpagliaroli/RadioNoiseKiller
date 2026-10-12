"""Diálogo "hay una versión nueva": notas del release y tres salidas. No descarga
nada: abre la página del release en el navegador."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
)

from i18n import tr


class UpdateDialog(QDialog):
    LATER, SKIP, OPEN = "later", "skip", "open"

    def __init__(self, current_label: str, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Nueva versión disponible"))
        self.setMinimumWidth(520)
        self._url = result["url"]
        self.choice = self.LATER

        lay = QVBoxLayout(self)
        head = QLabel(tr("Hay una versión nueva: <b>{new}</b> (instalada: {cur}).").format(
            new=result["label"], cur=current_label))
        head.setWordWrap(True)
        lay.addWidget(head)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(result.get("notes") or tr("(El release no trae notas.)"))
        notes.setMinimumHeight(220)
        lay.addWidget(notes, 1)

        hint = QLabel(tr("Se abre la página del release en el navegador; desde ahí se descarga el zip de tu plataforma."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 8pt;")
        lay.addWidget(hint)

        row = QHBoxLayout()
        self._btn_open = QPushButton(tr("Abrir página de descarga"))
        self._btn_open.setDefault(True)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_later = QPushButton(tr("Recordármelo después"))
        self._btn_later.clicked.connect(self.reject)
        self._btn_skip = QPushButton(tr("Omitir esta versión"))
        self._btn_skip.setToolTip(tr("No vuelve a avisar hasta que salga una versión posterior."))
        self._btn_skip.clicked.connect(self._on_skip)
        row.addWidget(self._btn_skip)
        row.addStretch()
        row.addWidget(self._btn_later)
        row.addWidget(self._btn_open)
        lay.addLayout(row)

    def _on_open(self) -> None:
        self.choice = self.OPEN
        QDesktopServices.openUrl(QUrl(self._url))
        self.accept()

    def _on_skip(self) -> None:
        self.choice = self.SKIP
        self.accept()
