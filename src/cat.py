"""
Control de la radio (CAT) a través de rigctld de Hamlib, por TCP.

rigctld es el demonio de Hamlib que habla con la radio por el puerto serie/USB
y expone un protocolo de texto en TCP (por defecto localhost:4532). Hablar con
él en vez de con la radio evita un protocolo por marca (CI-V, CAT de Yaesu,
Kenwood...) y permite compartir la radio con WSJT-X/fldigi, que también lo usan.

    f\\n  ->  "14074000\\n"               frecuencia en Hz
    m\\n  ->  "USB\\n2400\\n"              modo y passband en Hz
    error ->  "RPRT -11\\n"

Sin Qt: el cliente corre en un hilo daemon y publica un `CatState` inmutable
que la GUI lee con un QTimer (mismo patrón que eibi_db.EibiUpdater). Ninguna
llamada de red ocurre en el hilo de la GUI. Una radio caída o un rigctld que no
responde no puede trabar la app ni el audio: timeouts de 1 s y reintento.

`AutoPresetSwitcher` y `choose_preset()` son la lógica del preset automático
por modo, puras y testeables sin Qt ni sockets.
"""
import socket
import threading
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4532

POLL_S = 0.5          # consulta de frecuencia y modo
RETRY_S = 5.0         # reintento de conexión
TIMEOUT_S = 1.0       # connect y cada respuesta
STABLE_S = 1.0        # el modo nuevo tiene que sostenerse esto antes de cargar preset

# Grupos de modo de Hamlib: el preset se elige por grupo, no por modo (USB y
# LSB se escuchan igual para el cancelador; PKTUSB es USB con datos).
MODE_GROUPS = ("SSB", "AM", "FM", "WFM", "CW")
_MODE_TO_GROUP = {
    "USB": "SSB", "LSB": "SSB", "PKTUSB": "SSB", "PKTLSB": "SSB",
    "ECSSUSB": "SSB", "ECSSLSB": "SSB",
    "AM": "AM", "SAM": "AM", "AMS": "AM", "DSB": "AM", "PKTAM": "AM",
    "SAL": "AM", "SAH": "AM",
    "FM": "FM", "PKTFM": "FM", "FMN": "FM",
    "WFM": "WFM",
    "CW": "CW", "CWR": "CW",
}

# Defaults de la tabla grupo -> preset: nombres de los presets de fábrica.
# "" = no cambiar el preset al entrar en ese grupo.
DEFAULT_MODE_PRESETS = {
    "SSB": "SSB - Ruido Medio -Perfil Adaptativo",
    "AM":  "AM SW - Ruido Medio y Fading",
    "FM":  "FM - Narrow (Experimental)",
    "WFM": "FM - Broadcast (Experimental)",
    "CW":  "",
}


def mode_group(mode: "str | None") -> "str | None":
    """Grupo (SSB/AM/FM/WFM/CW) de un modo de Hamlib, o None si es desconocido."""
    if not mode:
        return None
    return _MODE_TO_GROUP.get(mode.strip().upper())


@dataclass(frozen=True)
class CatState:
    connected: bool = False
    freq_hz: "int | None" = None
    mode: "str | None" = None
    error: str = ""          # último error (conexión rechazada, RPRT, timeout...)


class CatError(Exception):
    pass


class RigctldClient:
    """Consulta frecuencia y modo a rigctld en un hilo propio.

    `state` siempre devuelve un CatState completo: el hilo lo reemplaza de un
    golpe (asignación de referencia, atómica en Python), así que leerlo desde la
    GUI no necesita lock.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 poll_s: float = POLL_S, retry_s: float = RETRY_S,
                 timeout_s: float = TIMEOUT_S):
        self.host, self.port = host, int(port)
        self._poll_s, self._retry_s, self._timeout_s = poll_s, retry_s, timeout_s
        self._state = CatState()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    @property
    def state(self) -> CatState:
        return self._state

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rigctld", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None
        self._state = CatState()

    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), self._timeout_s)
            except OSError as e:
                self._state = CatState(error=str(e) or type(e).__name__)
                self._stop.wait(self._retry_s)
                continue
            try:
                sock.settimeout(self._timeout_s)
                rf = sock.makefile("r", encoding="ascii", errors="replace", newline="\n")
                while not self._stop.is_set():
                    freq = int(float(self._query(sock, rf, "f", 1)[0]))
                    mode = self._query(sock, rf, "m", 2)[0].strip().upper()
                    self._state = CatState(True, freq, mode)
                    self._stop.wait(self._poll_s)
            except (OSError, ValueError, CatError) as e:
                self._state = CatState(error=str(e) or type(e).__name__)
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
            # Reconexión: el primer reintento rápido (rigctld reiniciado), y
            # después el ritmo normal si sigue sin estar.
            self._stop.wait(min(self._retry_s, 1.0))

    @staticmethod
    def _query(sock: socket.socket, rf, cmd: str, n_lines: int) -> list:
        sock.sendall((cmd + "\n").encode("ascii"))
        lines = []
        while len(lines) < n_lines:
            line = rf.readline()
            if not line:
                raise CatError("rigctld cerró la conexión")
            line = line.strip()
            if line.startswith("RPRT"):
                code = line[4:].strip()
                if code != "0":
                    raise CatError(f"rigctld respondió RPRT {code} a '{cmd}'")
                continue
            lines.append(line)
        return lines


# ----------------------------------------------------------------------
# Preset automático por modo (lógica pura)
# ----------------------------------------------------------------------

class AutoPresetSwitcher:
    """Decide CUÁNDO actuar: cuando el grupo de modo cambia y el nuevo se sostiene
    `stable_s` segundos (al girar el selector de modo la radio pasa por modos
    intermedios). Al conectar, el primer grupo estable también cuenta. Un grupo
    desconocido (None) no dispara nada ni borra el último aplicado."""

    def __init__(self, stable_s: float = STABLE_S):
        self._stable_s = stable_s
        self._applied: "str | None" = None
        self._candidate: "str | None" = None
        self._since = 0.0

    def reset(self) -> None:
        """Al desconectar o desactivar: la próxima conexión vuelve a aplicar."""
        self._applied = self._candidate = None

    def update(self, group: "str | None", now: float) -> "str | None":
        """Devuelve el grupo a aplicar en este tick, o None."""
        if group is None or group == self._applied:
            self._candidate = None
            return None
        if group != self._candidate:
            self._candidate, self._since = group, now
            return None
        if now - self._since < self._stable_s:
            return None
        self._applied, self._candidate = group, None
        return group


# Resultados de choose_preset (el segundo elemento): lo que muestra la UI.
# DISCARD = carga, pero descarta cambios sin guardar del preset activo (la UI avisa).
LOAD, DISCARD, UNMAPPED, MISSING, ALREADY = "load", "discard", "unmapped", "missing", "already"


def choose_preset(group: str, mapping: dict, exists, active: str,
                  active_modified: bool) -> "tuple[str | None, str]":
    """(preset a cargar o None, motivo). `exists(nombre) -> bool`.

    El cambio de modo de la radio MANDA: carga el preset del modo aunque el
    activo tenga cambios sin guardar ("(modificado)") — decisión del usuario
    tras probarlo en el aire: el primer diseño no lo pisaba y en la práctica el
    preset "nunca cambiaba", porque casi siempre hay algún ajuste suelto. Se
    devuelve DISCARD para que la UI avise que esos cambios se perdieron.
    """
    name = (mapping.get(group) or "").strip()
    if not name:
        return None, UNMAPPED
    if not exists(name):
        return None, MISSING
    modified = bool(active) and active_modified
    if name == active and not modified:
        return None, ALREADY
    return name, DISCARD if modified else LOAD
