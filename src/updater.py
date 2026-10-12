"""
Chequeo de versión nueva contra GitHub Releases. Sólo AVISA: no descarga ni
reemplaza nada (eso sería una fase 2, ver el plan de la v2.7).

Sin Qt: lógica pura y testeable. La consulta corre en un hilo propio y la UI lee
`state` / `result` / `message` por polling (mismo patrón que eibi_db.EibiUpdater);
`opener` es inyectable para los tests.

Hechos del origen (verificados en oct 2026):
- Repo público: /releases/latest responde sin token (60 consultas/h por IP; acá se
  hace como máximo 1 por día).
- /releases/latest excluye borradores y pre-releases.
- El JSON trae tag_name, html_url, body (notas) y, por asset, un `digest` sha256.
"""
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = "https://api.github.com/repos/gpagliaroli/RadioNoiseKiller/releases/latest"
CHECK_INTERVAL = timedelta(hours=24)
NETWORK_TIMEOUT_S = 15
MAX_BYTES = 1024 * 1024
MAX_NOTES_CHARS = 4000


def parse_version(text) -> "tuple | None":
    """'v2.6.1' -> (2, 6, 1); 'v2.6' -> (2, 6, 0); cualquier otra cosa -> None."""
    m = re.fullmatch(r"\s*v?(\d+)\.(\d+)(?:\.(\d+))?\s*", str(text or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def is_newer(candidate, current) -> bool:
    c, k = parse_version(candidate), parse_version(current)
    return c is not None and k is not None and c > k


def is_due(last_check_iso: str, now: datetime) -> bool:
    """True si pasaron 24 h desde la última consulta (o nunca se hizo / fecha ilegible)."""
    try:
        last = datetime.fromisoformat(last_check_iso)
    except (TypeError, ValueError):
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last >= CHECK_INTERVAL or last > now   # reloj atrasado: no quedarse sin chequear


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class UpdateChecker:
    IDLE, CHECKING, UP_TO_DATE, AVAILABLE, ERROR = (
        "idle", "checking", "up_to_date", "available", "error")

    def __init__(self, current_version: str, opener=None):
        self.current_version = current_version
        self._opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
        self._lock = threading.Lock()
        self._state = self.IDLE
        self._message = ""
        self._result: "dict | None" = None
        self._thread: "threading.Thread | None" = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    @property
    def result(self) -> "dict | None":
        with self._lock:
            return self._result

    def is_running(self) -> bool:
        return self.state == self.CHECKING

    def _set(self, state: str, message: str = "", result: "dict | None" = None) -> None:
        with self._lock:
            self._state, self._message, self._result = state, message, result

    def start(self) -> None:
        if self.is_running():
            return
        self._set(self.CHECKING)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def run_sync(self) -> None:
        """Para tests: lo mismo que start() en el hilo que llama."""
        self._set(self.CHECKING)
        self._run()

    def _run(self) -> None:
        try:
            self._check()
        except Exception as e:                  # la red falla de mil maneras; la GUI nunca ve una excepción
            self._set(self.ERROR, "Error inesperado: %s" % e)

    def _check(self) -> None:
        req = urllib.request.Request(API_URL, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "RadioNoiseKiller",
        })
        try:
            resp = self._opener(req, NETWORK_TIMEOUT_S)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                self._set(self.ERROR, "GitHub rechazó la consulta (límite de consultas); probá más tarde")
            elif e.code == 404:
                self._set(self.ERROR, "No hay versiones publicadas")
            else:
                self._set(self.ERROR, "GitHub respondió HTTP %d" % e.code)
            return
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if "CERTIFICATE" in str(reason).upper():
                self._set(self.ERROR, "No se pudo verificar el certificado de GitHub")
            else:
                self._set(self.ERROR, "Sin conexión: %s" % reason)
            return
        except OSError as e:                    # timeout, conexión cortada
            self._set(self.ERROR, "Sin conexión: %s" % e)
            return
        with resp:
            raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            self._set(self.ERROR, "Respuesta demasiado grande")
            return
        try:
            data = json.loads(raw.decode("utf-8"))
            tag = str(data["tag_name"])
        except (ValueError, KeyError, TypeError):
            self._set(self.ERROR, "Respuesta de GitHub inválida")
            return
        if data.get("draft") or data.get("prerelease"):
            self._set(self.UP_TO_DATE)          # /latest no los devuelve; por si acaso
            return
        if parse_version(tag) is None:
            self._set(self.ERROR, "Versión publicada con formato desconocido: %s" % tag)
            return
        if not is_newer(tag, self.current_version):
            self._set(self.UP_TO_DATE)
            return
        v = parse_version(tag)
        notes = str(data.get("body") or "")
        if len(notes) > MAX_NOTES_CHARS:
            notes = notes[:MAX_NOTES_CHARS].rstrip() + "\n…"
        self._set(self.AVAILABLE, "", {
            "tag": tag,
            "version": "%d.%d.%d" % v,
            "label": "v%d.%d" % v[:2] if v[2] == 0 else "v%d.%d.%d" % v,
            "notes": notes,
            "url": str(data.get("html_url") or "https://github.com/gpagliaroli/RadioNoiseKiller/releases/latest"),
            "published": str(data.get("published_at") or ""),
        })
