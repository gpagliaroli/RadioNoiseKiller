"""
Solapa EiBi: "¿qué emisora de onda corta es esta?". Busca en la grilla EiBi
(eibispace.de) por frecuencia y marca cuáles están en el aire a la hora UTC
actual (o a una hora elegida). La base se baja sola al abrir la solapa si venció
(ver eibi_db.py) y hay un botón para forzar la actualización.

La grilla es la PROGRAMACIÓN publicada, no lo que realmente está al aire: sólo la
escucha confirma la emisora.
"""
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QTime, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView,
    QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QTimeEdit,
    QVBoxLayout, QWidget,
)

import eibi_codes
import eibi_db
from config import AppConfig, EIBI_FREQ_RANGE, EIBI_TOL_RANGE
from i18n import tr

_POLL_MS = 500
_CLOCK_REFRESH_S = 30
_MAX_ROWS = 300

_DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]    # weekday(): lunes = 0
_COLUMNS = ["En el aire", "kHz", "Δ kHz", "Hora UTC", "Días", "Emisora", "País",
            "Idioma", "Zona", "Sitio / notas"]

_GREEN, _GREY, _AMBER, _RED = "#69f0ae", "#777777", "#ffb74d", "#ef5350"


class EibiTab(QWidget):
    state_changed = Signal()   # cambió algo persistente -> MainWindow agenda guardado

    def __init__(self, config: AppConfig, updater: "eibi_db.EibiUpdater | None" = None,
                 parent=None):
        super().__init__(parent)
        self._config = config
        self._updater = updater or eibi_db.EibiUpdater()
        self._store = self._updater.store
        self._db: "eibi_db.EibiDatabase | None" = None
        self._shown_once = False
        self._last_updater_state = eibi_db.EibiUpdater.IDLE
        self._last_minute = None
        self._clock_ticks = 0
        self._build_ui()
        self._load_values()
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Frecuencia:")))
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(*EIBI_FREQ_RANGE)
        self._spin_freq.setDecimals(2)
        self._spin_freq.setSingleStep(1.0)
        self._spin_freq.setSuffix(" kHz")
        self._spin_freq.setKeyboardTracking(False)
        self._spin_freq.setToolTip(tr("Frecuencia sintonizada, en kHz (ej. 6140 o 9560)."))
        row.addWidget(self._spin_freq)
        row.addSpacing(12)
        row.addWidget(QLabel(tr("Tolerancia ±")))
        self._spin_tol = QDoubleSpinBox()
        self._spin_tol.setRange(*EIBI_TOL_RANGE)
        self._spin_tol.setDecimals(1)
        self._spin_tol.setSingleStep(0.5)
        self._spin_tol.setSuffix(" kHz")
        self._spin_tol.setKeyboardTracking(False)
        self._spin_tol.setToolTip(tr(
            "Cuánto se busca alrededor de la frecuencia. Subila si tu receptor está "
            "levemente desafinado o si estás en una banda con canales cada 5 kHz."))
        row.addWidget(self._spin_tol)
        row.addStretch()
        root.addLayout(row)

        time_row = QHBoxLayout()
        self._chk_now = QCheckBox(tr("Usar hora actual (UTC)"))
        self._chk_now.setChecked(True)
        self._chk_now.setToolTip(tr(
            "Toma la hora y el día del reloj de la PC convertidos a UTC. "
            "Destildalo para consultar otro horario."))
        time_row.addWidget(self._chk_now)
        self._lbl_now = QLabel("")
        self._lbl_now.setStyleSheet("color: #69f0ae; font-weight: bold;")
        time_row.addWidget(self._lbl_now)
        time_row.addSpacing(12)
        self._edit_time = QTimeEdit()
        self._edit_time.setDisplayFormat("HH:mm")
        time_row.addWidget(self._edit_time)
        self._combo_day = QComboBox()
        for i, d in enumerate(_DAYS):
            self._combo_day.addItem(tr(d), i)
        time_row.addWidget(self._combo_day)
        time_row.addStretch()
        root.addLayout(time_row)

        self._chk_auto = QCheckBox(tr("Verificar la base automáticamente al abrir esta solapa"))
        self._chk_auto.setToolTip(tr(
            "Si la base tiene más de 7 días, consulta al servidor si hay una versión más "
            "nueva y solo la baja si cambió. Sin esto, se actualiza con el botón."))
        root.addWidget(self._chk_auto)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([tr(c) for c in _COLUMNS])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setStretchLastSection(True)
        root.addWidget(self._table, 1)

        self._lbl_result = QLabel("")
        self._lbl_result.setStyleSheet("color: #888; font-size: 8pt;")
        self._lbl_result.setWordWrap(True)
        root.addWidget(self._lbl_result)

        db_row = QHBoxLayout()
        self._lbl_db = QLabel("")
        self._lbl_db.setWordWrap(True)
        self._lbl_db.setStyleSheet("font-size: 8pt;")
        db_row.addWidget(self._lbl_db, 1)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)           # indeterminada: no se conoce el avance
        self._progress.setFixedWidth(90)
        self._progress.setVisible(False)
        db_row.addWidget(self._progress)
        self._btn_update = QPushButton(tr("Actualizar ahora"))
        self._btn_update.setToolTip(tr("Consulta al servidor y baja la base si hay una versión más nueva."))
        db_row.addWidget(self._btn_update)
        root.addLayout(db_row)

        credit = QLabel(tr(
            "Datos: EiBi — Eike Bierwirth (eibispace.de). Es la programación publicada: "
            "solo escuchar confirma qué emisora es."))
        credit.setWordWrap(True)
        credit.setStyleSheet("color: #888; font-size: 8pt;")
        root.addWidget(credit)

        self._spin_freq.valueChanged.connect(self._on_params_changed)
        self._spin_tol.valueChanged.connect(self._on_params_changed)
        self._chk_now.toggled.connect(self._on_time_mode_changed)
        self._edit_time.timeChanged.connect(self._refresh_results)
        self._combo_day.currentIndexChanged.connect(self._refresh_results)
        self._chk_auto.toggled.connect(self._on_auto_changed)
        self._btn_update.clicked.connect(self._on_update_clicked)

    def _load_values(self) -> None:
        e = self._config.eibi
        for w in (self._spin_freq, self._spin_tol, self._chk_auto):
            w.blockSignals(True)
        self._spin_freq.setValue(e.freq_khz)
        self._spin_tol.setValue(e.tol_khz)
        self._chk_auto.setChecked(e.auto_update)
        for w in (self._spin_freq, self._spin_tol, self._chk_auto):
            w.blockSignals(False)
        self._on_time_mode_changed(self._chk_now.isChecked())

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._shown_once:
            return
        self._shown_once = True
        self._reload_db()
        if self._config.eibi.auto_update:
            self._updater.start(force=False)
        self._refresh_db_label()

    def _on_params_changed(self, *_) -> None:
        self._config.eibi.freq_khz = self._spin_freq.value()
        self._config.eibi.tol_khz = self._spin_tol.value()
        self.state_changed.emit()
        self._refresh_results()

    def _on_auto_changed(self, checked: bool) -> None:
        self._config.eibi.auto_update = bool(checked)
        self.state_changed.emit()

    def _on_time_mode_changed(self, use_now: bool) -> None:
        self._edit_time.setEnabled(not use_now)
        self._combo_day.setEnabled(not use_now)
        self._lbl_now.setVisible(use_now)
        if not use_now:
            now = eibi_db._now_utc()      # punto de partida cómodo: la hora actual
            self._edit_time.blockSignals(True)
            self._edit_time.setTime(QTime(now.hour, now.minute))
            self._edit_time.blockSignals(False)
            self._combo_day.blockSignals(True)
            self._combo_day.setCurrentIndex(now.weekday())
            self._combo_day.blockSignals(False)
        self._refresh_results()

    def _on_update_clicked(self) -> None:
        self._updater.start(force=True)
        self._refresh_db_label()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        st = self._updater.state
        if st != self._last_updater_state:
            self._last_updater_state = st
            if st in (eibi_db.EibiUpdater.UPDATED, eibi_db.EibiUpdater.UP_TO_DATE):
                self._reload_db()
            self._refresh_db_label()
        working = self._updater.is_running()
        self._progress.setVisible(working)
        self._btn_update.setEnabled(not working)
        if not self.isVisible():
            return
        # "En el aire" cambia con el reloj: refrescar al cambiar el minuto.
        if self._chk_now.isChecked():
            now = eibi_db._now_utc()
            key = (now.hour, now.minute)
            if key != self._last_minute:
                self._last_minute = key
                self._refresh_results()

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def _reload_db(self) -> None:
        try:
            self._db = self._store.load()
        except Exception:
            self._db = None
        self._refresh_results()

    def _query_time(self) -> datetime:
        if self._chk_now.isChecked():
            return eibi_db._now_utc()
        today = eibi_db._now_utc()
        shift = (self._combo_day.currentData() - today.weekday()) % 7
        t = self._edit_time.time()
        return (today + timedelta(days=shift)).replace(
            hour=t.hour(), minute=t.minute(), second=0, microsecond=0, tzinfo=timezone.utc)

    def _refresh_results(self, *_) -> None:
        when = self._query_time()
        if self._chk_now.isChecked():
            self._lbl_now.setText("UTC %02d:%02d · %s" % (
                when.hour, when.minute, tr(_DAYS[when.weekday()])))
        self._table.setRowCount(0)
        if self._db is None:
            self._lbl_result.setText(tr(
                "Todavía no hay base descargada. Se baja sola al abrir esta solapa "
                "(necesita internet una vez) o con el botón Actualizar ahora."))
            return
        matches = self._db.query(self._spin_freq.value(), self._spin_tol.value(), when)
        shown = matches[:_MAX_ROWS]
        self._table.setRowCount(len(shown))
        for r, m in enumerate(shown):
            self._fill_row(r, m)
        n_air = sum(1 for m in matches if m.on_air)
        if not matches:
            self._lbl_result.setText(tr("Sin coincidencias en {f:.1f} ± {t:.1f} kHz.").format(
                f=self._spin_freq.value(), t=self._spin_tol.value()))
        else:
            txt = tr("{n} coincidencias, {a} en el aire a las {h:02d}:{m:02d} UTC.").format(
                n=len(matches), a=n_air, h=when.hour, m=when.minute)
            if len(matches) > _MAX_ROWS:
                txt += " " + tr("Se muestran las primeras {n}.").format(n=_MAX_ROWS)
            self._lbl_result.setText(txt)

    def _fill_row(self, row: int, m: "eibi_db.Match") -> None:
        e = m.entry
        if m.on_air is True:
            mark, color = "●", _GREEN
        elif m.on_air is None:
            mark, color = "?", _AMBER
        else:
            mark, color = "○", _GREY
        cells = [
            mark, "%g" % e.freq_khz, "%+.1f" % m.delta_khz, e.time_text, e.days or "—",
            e.station, eibi_codes.name_of(eibi_codes.COUNTRIES, e.itu),
            eibi_codes.name_of(eibi_codes.LANGUAGES, e.lang) if e.lang else "",
            eibi_codes.name_of(eibi_codes.TARGETS, e.target), e.notes,
        ]
        tips = {
            0: tr("En el aire ahora") if m.on_air else (
                tr("Los días no se pueden interpretar: revisá la columna Días") if m.on_air is None
                else tr("Fuera de horario")),
            7: e.lang, 8: e.target,
        }
        for c, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if c in tips and tips[c]:
                item.setToolTip(tips[c])
            if m.on_air is False:
                item.setForeground(QColor(_GREY))
            elif c == 0:
                item.setForeground(QColor(color))
            self._table.setItem(row, c, item)

    def _refresh_db_label(self) -> None:
        st = self._updater.state
        if self._updater.is_running():
            self._set_db_label(tr("Actualizando la base EiBi..."), "#cccccc")
            return
        meta = self._store.meta()
        if self._db is None:
            if st == eibi_db.EibiUpdater.ERROR:
                self._set_db_label(tr("No se pudo bajar la base: {err}").format(
                    err=self._updater.message), _RED)
            else:
                self._set_db_label(tr("Sin base descargada."), _AMBER)
            return
        try:
            checked = datetime.fromisoformat(meta["checked"])
            age_d = (eibi_db._now_utc() - checked).days
            age_txt = tr("verificada hace {d} d").format(d=age_d) if age_d > 0 else tr("verificada hoy")
        except (KeyError, ValueError):
            age_txt = tr("verificación desconocida")
        text = tr("EiBi {season} · {n} entradas · {age}").format(
            season=self._db.season.upper(), n=len(self._db), age=age_txt)
        color = "#cccccc"
        if st == eibi_db.EibiUpdater.ERROR:
            text += " · " + tr("no se pudo actualizar: {err}").format(err=self._updater.message)
            color = _AMBER
        elif not self._store.is_fresh(eibi_db._now_utc()):
            text += " · " + tr("vencida")
            color = _AMBER
        self._set_db_label(text, color)

    def _set_db_label(self, text: str, color: str) -> None:
        self._lbl_db.setText(text)
        self._lbl_db.setStyleSheet("font-size: 8pt; color: %s;" % color)
