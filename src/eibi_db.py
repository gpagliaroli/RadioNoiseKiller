"""
Base de emisoras de onda corta EiBi (Eike Bierwirth, eibispace.de): parseo,
búsqueda por frecuencia + "en el aire ahora" y descarga con vencimiento.

Sin Qt: lógica pura, testeable sin ventana. La descarga corre en un hilo propio
y la UI lee `state` / `message` por polling (mismo patrón que
translate_installer.py).

Hechos del origen (verificados con curl, oct 2026):
- El sitio sólo responde por HTTP: el certificado HTTPS está vencido. No hay firma,
  así que se VALIDA el contenido antes de reemplazar la base guardada.
- Manda ETag / Last-Modified: con una consulta condicional el servidor contesta 304
  y no hace falta bajar los ~530 KB.
- Archivo `sked-XYY.csv` (A = verano, B = invierno), Latin-1, CRLF, separado por `;`.
- Condiciones de uso: libre, incluso dentro de software de terceros.
"""
import json
import os
import re
import threading
import urllib.error
import urllib.request
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from utils import eibi_dir

BASE_URL = "http://www.eibispace.de/dx/sked-{season}.csv"
MAX_AGE_DAYS = 7            # antes de eso no se toca la red
NETWORK_TIMEOUT_S = 20
MAX_BYTES = 5 * 1024 * 1024
MIN_ROWS = 1000             # un archivo con menos filas es sospechoso (error, página HTML...)

_DAY_CODES = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Temporadas
# ---------------------------------------------------------------------------

def _last_sunday(year: int, month: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def season_for(d: date) -> str:
    """'a26' (verano: último domingo de marzo → antes del último domingo de octubre)
    o 'b26' (invierno; cruza el año: de enero a marzo usa el año anterior)."""
    a0 = _last_sunday(d.year, 3)
    b0 = _last_sunday(d.year, 10)
    if a0 <= d < b0:
        return "a%02d" % (d.year % 100)
    if d >= b0:
        return "b%02d" % (d.year % 100)
    return "b%02d" % ((d.year - 1) % 100)


def previous_season(season: str) -> str:
    letter, yy = season[0], int(season[1:])
    if letter == "b":
        return "a%02d" % yy
    return "b%02d" % ((yy - 1) % 100)


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    freq_khz: float
    t0: int                 # minutos UTC de inicio (0..1439)
    t1: int                 # minutos UTC de fin (1..1440)
    days: str               # campo "Días" tal cual
    itu: str
    station: str
    lang: str
    target: str
    notes: str
    persistence: int        # 0..8 (sin el +90 de las utilidades)
    utility: bool
    d0: "tuple | None"      # (mes, día) si persistence == 6
    d1: "tuple | None"

    @property
    def time_text(self) -> str:
        return "%02d%02d-%02d%02d" % (self.t0 // 60, self.t0 % 60, self.t1 // 60, self.t1 % 60)


def _parse_time(text: str):
    m = re.fullmatch(r"(\d{2})(\d{2})-(\d{2})(\d{2})", text.strip())
    if not m:
        return None
    h0, m0, h1, m1 = (int(x) for x in m.groups())
    t0, t1 = h0 * 60 + m0, h1 * 60 + m1
    if t0 > 1439 or t1 > 1440 or h0 > 23 or m0 > 59 or m1 > 59:
        return None
    return t0, t1


def _parse_ddmm(text: str):
    text = text.strip()
    if len(text) == 4 and text.isdigit():
        day, month = int(text[:2]), int(text[2:])
        if 1 <= day <= 31 and 1 <= month <= 12:
            return month, day
    return None


def parse_csv(raw: bytes) -> list:
    """Lista de Entry. Salta la cabecera y las filas rotas (nunca levanta por una
    fila mala) y descarta las entradas inactivas (P=8)."""
    out = []
    for line in raw.decode("latin-1").splitlines():
        parts = line.split(";")
        if len(parts) < 9:
            continue
        try:
            freq = float(parts[0])
        except ValueError:
            continue                       # cabecera u otra línea no numérica
        tm = _parse_time(parts[1])
        if tm is None:
            continue
        try:
            p = int(parts[8])
        except ValueError:
            p = 1
        utility = p >= 90
        if utility:
            p -= 90
        if p == 8:
            continue
        out.append(Entry(
            freq_khz=freq, t0=tm[0], t1=tm[1], days=parts[2].strip(),
            itu=parts[3].strip(), station=parts[4].strip(), lang=parts[5].strip(),
            target=parts[6].strip(), notes=parts[7].strip(), persistence=p, utility=utility,
            d0=_parse_ddmm(parts[9]) if len(parts) > 9 else None,
            d1=_parse_ddmm(parts[10]) if len(parts) > 10 else None,
        ))
    return out


# ---------------------------------------------------------------------------
# "En el aire"
# ---------------------------------------------------------------------------

def _day_index(code: str):
    return _DAY_CODES.index(code)


def days_active(spec: str, weekday: int, today: date):
    """True / False / None (no interpretable). `weekday`: lunes = 0."""
    spec = spec.strip()
    if not spec:
        return True
    saw_unknown = False
    for part in spec.split(","):
        part = part.strip()
        if re.fullmatch(r"[1-7]+", part):                        # '1245' = lun, mar, jue, vie
            if (weekday + 1) in {int(c) for c in part}:
                return True
        elif re.fullmatch(r"(Mo|Tu|We|Th|Fr|Sa|Su)-(Mo|Tu|We|Th|Fr|Sa|Su)", part):
            a, b = _day_index(part[:2]), _day_index(part[3:])
            span = {(a + i) % 7 for i in range((b - a) % 7 + 1)}   # 'We-Mo' da la vuelta
            if weekday in span:
                return True
        elif re.fullmatch(r"(Mo|Tu|We|Th|Fr|Sa|Su)+", part):    # 'SaSu', 'Mo'
            if _DAY_CODES[weekday] in {part[i:i + 2] for i in range(0, len(part), 2)}:
                return True
        else:
            m = re.fullmatch(r"(\d{1,2})(" + "|".join(_MONTHS) + ")", part)
            if m:                                                # '24Oct'
                if (_MONTHS.index(m.group(2)) + 1, int(m.group(1))) == (today.month, today.day):
                    return True
            else:
                saw_unknown = True                               # 'irr', 'Last7', 'alt'...
    return None if saw_unknown else False


def _in_date_range(d0, d1, today: date) -> bool:
    cur = (today.month, today.day)
    return d0 <= cur <= d1 if d0 <= d1 else (cur >= d0 or cur <= d1)


def on_air(entry: Entry, now: datetime):
    """True / False / None (los días no se pueden interpretar). `now` en UTC."""
    minute = now.hour * 60 + now.minute
    today = now.date()
    if entry.persistence == 6 and entry.d0 and entry.d1 and not _in_date_range(entry.d0, entry.d1, today):
        return False
    if entry.t0 < entry.t1:                       # no cruza la medianoche
        if not (entry.t0 <= minute < entry.t1):
            return False
        return days_active(entry.days, now.weekday(), today)
    # cruza la medianoche (1900-0400): la parte posterior pertenece al día anterior
    if minute >= entry.t0:
        return days_active(entry.days, now.weekday(), today)
    if minute < entry.t1:
        ayer = today - timedelta(days=1)
        return days_active(entry.days, ayer.weekday(), ayer)
    return False


@dataclass(frozen=True)
class Match:
    entry: Entry
    delta_khz: float
    on_air: "bool | None"


class EibiDatabase:
    def __init__(self, entries: list, season: str = ""):
        self.entries = sorted(entries, key=lambda e: e.freq_khz)
        self._freqs = [e.freq_khz for e in self.entries]
        self.season = season

    def __len__(self) -> int:
        return len(self.entries)

    def query(self, freq_khz: float, tol_khz: float, now: datetime,
              include_utility: bool = True) -> list:
        lo = bisect_left(self._freqs, freq_khz - tol_khz - 1e-9)
        hi = bisect_right(self._freqs, freq_khz + tol_khz + 1e-9)
        out = []
        for e in self.entries[lo:hi]:
            if e.utility and not include_utility:
                continue
            out.append(Match(e, e.freq_khz - freq_khz, on_air(e, now)))
        rank = {True: 0, None: 1, False: 2}
        out.sort(key=lambda m: (rank[m.on_air], abs(m.delta_khz), m.entry.t0))
        return out


# ---------------------------------------------------------------------------
# Almacenamiento y descarga
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EibiStore:
    """Base guardada en data_dir()/EiBi/ (sked-XYY.csv + meta.json)."""

    def __init__(self, directory: "str | None" = None):
        self.dir = directory or eibi_dir()

    @property
    def _meta_path(self) -> str:
        return os.path.join(self.dir, "meta.json")

    def meta(self) -> dict:
        try:
            with open(self._meta_path, encoding="utf-8") as f:
                m = json.load(f)
            return m if isinstance(m, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_meta(self, meta: dict) -> None:
        tmp = self._meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, self._meta_path)

    def csv_path(self, season: str) -> str:
        return os.path.join(self.dir, "sked-%s.csv" % season)

    def load(self) -> "EibiDatabase | None":
        m = self.meta()
        season = m.get("season", "")
        try:
            with open(self.csv_path(season), "rb") as f:
                entries = parse_csv(f.read())
        except OSError:
            return None
        return EibiDatabase(entries, season) if entries else None

    def is_fresh(self, now: datetime) -> bool:
        """True si la base es de la temporada vigente y se verificó hace menos de MAX_AGE_DAYS."""
        m = self.meta()
        try:
            checked = datetime.fromisoformat(m["checked"])
        except (KeyError, ValueError):
            return False
        if not os.path.isfile(self.csv_path(m.get("season", ""))):
            return False
        if m.get("season") != season_for(now.date()):
            return False        # cambió la temporada: ver si ya se publicó la nueva
        return now - checked < timedelta(days=MAX_AGE_DAYS)

    def save(self, season: str, raw: bytes, etag: str, last_modified: str, now: datetime) -> None:
        os.makedirs(self.dir, exist_ok=True)
        path = self.csv_path(season)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)                       # atómico: nunca queda un archivo a medias
        stamp = now.isoformat()
        self._write_meta({"season": season, "etag": etag, "last_modified": last_modified,
                          "downloaded": stamp, "checked": stamp})

    def touch_checked(self, now: datetime) -> None:
        m = self.meta()
        if m:
            m["checked"] = now.isoformat()
            self._write_meta(m)


class EibiUpdater:
    """Descarga / verifica la base en un hilo propio. `opener(request, timeout)` es
    inyectable para los tests (por defecto urllib)."""

    IDLE, WORKING, UP_TO_DATE, UPDATED, ERROR = "idle", "working", "up_to_date", "updated", "error"

    def __init__(self, store: "EibiStore | None" = None, opener=None, now_fn=_now_utc):
        self.store = store or EibiStore()
        self._opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
        self._now = now_fn
        self._lock = threading.Lock()
        self._state = self.IDLE
        self._message = ""
        self._thread: "threading.Thread | None" = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    def is_running(self) -> bool:
        return self.state == self.WORKING

    def _set(self, state: str, message: str = "") -> None:
        with self._lock:
            self._state, self._message = state, message

    def start(self, force: bool = False) -> None:
        if self.is_running():
            return
        self._set(self.WORKING)
        self._thread = threading.Thread(target=self._run, args=(force,), daemon=True)
        self._thread.start()

    def run_sync(self, force: bool = False) -> None:
        """Para tests: lo mismo que start() pero en el hilo que llama."""
        self._set(self.WORKING)
        self._run(force)

    def _run(self, force: bool) -> None:
        try:
            now = self._now()
            if not force and self.store.is_fresh(now):
                self._set(self.UP_TO_DATE)
                return
            season = season_for(now.date())
            meta = self.store.meta()
            last_error = ""
            for cand in (season, previous_season(season)):
                outcome = self._fetch(cand, meta, now)
                if outcome == "404":
                    last_error = "sked-%s.csv todavía no está publicado" % cand
                    continue
                return
            # Ninguna temporada disponible: si ya hay base se conserva
            if self.store.load() is not None:
                self._set(self.UP_TO_DATE, last_error)
            else:
                self._set(self.ERROR, last_error)
        except Exception as e:                              # la red falla de mil maneras
            self._set(self.ERROR, str(e))

    def _fetch(self, season: str, meta: dict, now: datetime) -> str:
        """Devuelve '404' si el archivo no existe; en cualquier otro caso deja el estado
        final puesto y devuelve 'done'."""
        req = urllib.request.Request(BASE_URL.format(season=season),
                                     headers={"User-Agent": "RadioNoiseKiller"})
        if meta.get("season") == season and os.path.isfile(self.store.csv_path(season)):
            if meta.get("etag"):
                req.add_header("If-None-Match", meta["etag"])
            if meta.get("last_modified"):
                req.add_header("If-Modified-Since", meta["last_modified"])
        try:
            resp = self._opener(req, NETWORK_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                self.store.touch_checked(now)
                self._set(self.UP_TO_DATE)
                return "done"
            if e.code == 404:
                return "404"
            self._set(self.ERROR, "HTTP %d" % e.code)
            return "done"
        except (urllib.error.URLError, OSError) as e:
            self._set(self.ERROR, "Sin conexión: %s" % getattr(e, "reason", e))
            return "done"
        with resp:
            raw = resp.read(MAX_BYTES + 1)
            headers = resp.headers
        if len(raw) > MAX_BYTES:
            self._set(self.ERROR, "Archivo demasiado grande")
            return "done"
        entries = parse_csv(raw)
        if len(entries) < MIN_ROWS:
            self._set(self.ERROR, "El archivo descargado no parece una base EiBi válida")
            return "done"                                   # la base anterior queda intacta
        self.store.save(season, raw, headers.get("ETag", "") or "",
                        headers.get("Last-Modified", "") or "", now)
        self._set(self.UPDATED, "%d entradas" % len(entries))
        return "done"
