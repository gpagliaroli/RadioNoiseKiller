"""
Instalador del módulo de Traducción en un clic.

Arma, en `data_dir()/TraduccionRuntime/`, un entorno Python propio con
faster-whisper + argostranslate (los pins de translate_worker/requirements.txt),
copia el worker y pre-descarga los modelos pedidos. Sólo stdlib: nada de esto
puede arrastrar faster-whisper/torch al .spec de la app principal.

Todo corre en un hilo propio; la UI lee `state` / `progress` / `status_text` /
`last_error` por polling (mismo patrón que TranslateClient, sin señales Qt
cruzando hilos). Nada de red ni de subprocess toca el hilo de la GUI.

Opt-in: este módulo nunca se invoca solo — lo dispara el botón "Instalar" de
la pestaña Traducción, tras una confirmación con los tamaños.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

from utils import data_dir, log_path, resource_path

PYTHON_EMBED_VERSION = "3.11.9"
PYTHON_EMBED_URL = (
    "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
    .format(v=PYTHON_EMBED_VERSION))
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# Tamaños aproximados para la confirmación previa (MB).
SIZE_PACKAGES_MB = 450
SIZE_WHISPER_MB = {"tiny": 75, "base": 145, "small": 480}
SIZE_LANG_PAIR_MB = 100

_NETWORK_TIMEOUT_S = 30
_IS_WINDOWS = sys.platform == "win32"


def runtime_dir() -> str:
    return os.path.join(data_dir(), "TraduccionRuntime")


def runtime_python() -> str:
    if _IS_WINDOWS:
        return os.path.join(runtime_dir(), "python", "python.exe")
    return os.path.join(runtime_dir(), "python", "bin", "python")


def runtime_worker_script() -> str:
    return os.path.join(runtime_dir(), "worker", "worker.py")


def models_dir() -> str:
    return os.path.join(runtime_dir(), "models")


def _marker_path() -> str:
    return os.path.join(runtime_dir(), "installed.json")


def is_installed() -> bool:
    return (os.path.isfile(_marker_path()) and os.path.isfile(runtime_python())
            and os.path.isfile(runtime_worker_script()))


def worker_env() -> dict:
    """Variables para que el worker guarde modelos DENTRO de la carpeta del
    módulo (así desinstalar = borrar una carpeta)."""
    env = dict(os.environ)
    env["HF_HOME"] = os.path.join(models_dir(), "hf")
    env["ARGOS_PACKAGES_DIR"] = os.path.join(models_dir(), "argos")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def estimate_download_mb(model_size: str, n_lang_pairs: int) -> int:
    return (SIZE_PACKAGES_MB + SIZE_WHISPER_MB.get(model_size, 75)
            + SIZE_LANG_PAIR_MB * max(1, n_lang_pairs))


def _worker_source_dir() -> str:
    return resource_path("translate_worker")


def refresh_worker_files() -> None:
    """Copia los .py del worker de la app a la carpeta del runtime (si cambió
    la app, el worker se actualiza sin reinstalar el entorno)."""
    src = _worker_source_dir()
    dst = os.path.join(runtime_dir(), "worker")
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        if name.endswith(".py") and not name.startswith("test_"):
            shutil.copy2(os.path.join(src, name), os.path.join(dst, name))


def uninstall() -> None:
    shutil.rmtree(runtime_dir(), ignore_errors=True)


class _Cancelled(Exception):
    pass


class TranslateInstaller:
    IDLE        = "idle"
    PYTHON      = "downloading_python"
    PACKAGES    = "installing_packages"
    MODELS      = "downloading_models"
    DONE        = "done"
    ERROR       = "error"
    CANCELLED   = "cancelled"

    _RUNNING = (PYTHON, PACKAGES, MODELS)

    def __init__(self):
        self._lock = threading.Lock()
        self._state = self.IDLE
        self._progress = 0.0
        self._status = ""
        self._error = ""
        self._thread: "threading.Thread | None" = None
        self._proc: "subprocess.Popen | None" = None
        self._cancel = threading.Event()

    # -- lectura por polling ------------------------------------------------
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def progress(self) -> float:
        with self._lock:
            return self._progress

    @property
    def status_text(self) -> str:
        with self._lock:
            return self._status

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._error

    def is_running(self) -> bool:
        return self.state in self._RUNNING

    # -- control ------------------------------------------------------------
    def start(self, model_size: str = "tiny", src_langs=("en",), dst_langs=("es",)) -> None:
        if self.is_running():
            return
        self._cancel.clear()
        self._set(self.PYTHON, 0.0, "", "")
        self._thread = threading.Thread(
            target=self._run, args=(model_size, list(src_langs), list(dst_langs)),
            daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    # -- internos -----------------------------------------------------------
    def _set(self, state=None, progress=None, status=None, error=None) -> None:
        with self._lock:
            if state is not None:
                self._state = state
            if progress is not None:
                self._progress = progress
            if status is not None:
                self._status = status
            if error is not None:
                self._error = error

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise _Cancelled()

    def _run(self, model_size: str, src_langs: list, dst_langs: list) -> None:
        try:
            os.makedirs(runtime_dir(), exist_ok=True)
            self._set(self.PYTHON, 0.0, "Preparando Python...")
            self._make_python()
            self._check_cancel()
            refresh_worker_files()
            self._set(self.PACKAGES, 0.10, "Instalando componentes...")
            self._pip_install()
            self._check_cancel()
            self._set(self.MODELS, 0.80, "Descargando modelos...")
            self._prefetch(model_size, src_langs, dst_langs)
            self._check_cancel()
            with open(_marker_path(), "w", encoding="utf-8") as f:
                json.dump({"requirements": self._requirements_hash(),
                           "model": model_size}, f)
            self._set(self.DONE, 1.0, "Listo")
        except _Cancelled:
            shutil.rmtree(runtime_dir(), ignore_errors=True)
            self._set(self.CANCELLED, 0.0, "Cancelado")
        except Exception as e:
            self._log(f"instalacion fallida: {e!r}")
            # Carpeta parcial inservible: se borra, el reintento parte limpio.
            shutil.rmtree(runtime_dir(), ignore_errors=True)
            self._set(self.ERROR, 0.0, "", str(e))
        finally:
            self._proc = None

    def _requirements_hash(self) -> str:
        path = os.path.join(_worker_source_dir(), "requirements.txt")
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]

    def _log(self, text: str) -> None:
        try:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(f"[translate_installer] {text}\n")
        except Exception:
            pass

    def _download(self, url: str, dest: str, lo: float, hi: float, label: str) -> None:
        try:
            with urllib.request.urlopen(url, timeout=_NETWORK_TIMEOUT_S) as r, \
                    open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    self._check_cancel()
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self._set(progress=lo + (hi - lo) * done / total, status=label)
        except _Cancelled:
            raise
        except OSError as e:
            raise RuntimeError(
                "No se pudo descargar (se necesita internet solo para instalar): "
                f"{e}") from e

    def _make_python(self) -> None:
        py_dir = os.path.join(runtime_dir(), "python")
        if os.path.isfile(runtime_python()):
            return
        if _IS_WINDOWS:
            zip_path = os.path.join(runtime_dir(), "python_embed.zip")
            self._download(PYTHON_EMBED_URL, zip_path, 0.0, 0.05, "Descargando Python...")
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(py_dir)
            os.remove(zip_path)
            self._enable_site_and_worker_path(py_dir)
            get_pip = os.path.join(runtime_dir(), "get-pip.py")
            self._download(GET_PIP_URL, get_pip, 0.05, 0.08, "Descargando pip...")
            self._run_cmd([runtime_python(), get_pip, "--no-warn-script-location"])
            os.remove(get_pip)
        else:
            self._run_cmd([sys.executable if not getattr(sys, "frozen", False)
                           else "python3", "-m", "venv", py_dir],
                          fail_hint="Falta el módulo venv. En Debian/Ubuntu/"
                                    "Raspberry Pi OS: sudo apt install python3-venv")

    def _enable_site_and_worker_path(self, py_dir: str) -> None:
        """El Python embebible trae un python3XX._pth que desactiva `site`
        (sin eso pip no funciona) e ignora PYTHONPATH/directorio del script."""
        for name in os.listdir(py_dir):
            if name.endswith("._pth"):
                p = os.path.join(py_dir, name)
                with open(p, "r", encoding="utf-8") as f:
                    lines = [ln.rstrip("\n") for ln in f]
                lines = [("import site" if ln.strip() == "#import site" else ln)
                         for ln in lines]
                lines.append(os.path.join(runtime_dir(), "worker"))
                with open(p, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")

    def _popen(self, cmd: list) -> "subprocess.Popen":
        kwargs = {}
        if _IS_WINDOWS:
            kwargs["creationflags"] = 0x08000000   # CREATE_NO_WINDOW
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", env=worker_env(), **kwargs)

    def _run_cmd(self, cmd: list, fail_hint: str = "") -> list:
        """Corre un comando, devuelve sus líneas de salida; lanza RuntimeError
        con el final de la salida si falla."""
        proc = self._popen(cmd)
        self._proc = proc
        lines = []
        for line in proc.stdout:
            self._check_cancel()
            lines.append(line.rstrip())
        proc.wait()
        self._proc = None
        self._check_cancel()
        if proc.returncode != 0:
            tail = "\n".join(lines[-6:])
            raise RuntimeError((fail_hint + "\n" if fail_hint else "") + tail)
        return lines

    def _pip_install(self) -> None:
        req = os.path.join(_worker_source_dir(), "requirements.txt")
        proc = self._popen([runtime_python(), "-m", "pip", "install", "--no-input",
                            "--disable-pip-version-check", "--no-warn-script-location",
                            "-r", req])
        self._proc = proc
        lines, n = [], 0
        for line in proc.stdout:
            self._check_cancel()
            line = line.rstrip()
            lines.append(line)
            n += 1
            # Progreso asintótico: pip no informa un total.
            frac = 0.10 + 0.70 * (1.0 - 0.5 ** (n / 25.0))
            self._set(progress=frac, status=line[:80] if line else None)
        proc.wait()
        self._proc = None
        self._check_cancel()
        if proc.returncode != 0:
            raise RuntimeError("pip falló:\n" + "\n".join(lines[-6:]))

    def _prefetch(self, model_size: str, src_langs: list, dst_langs: list) -> None:
        cmd = [runtime_python(), runtime_worker_script(), model_size, "--prefetch",
               "--src", ",".join(src_langs), "--dst", ",".join(dst_langs)]
        proc = self._popen(cmd)
        self._proc = proc
        lines = []
        t0 = time.monotonic()
        for line in proc.stdout:
            self._check_cancel()
            line = line.rstrip()
            lines.append(line)
            if line.startswith("progress:"):
                self._set(status=line[len("progress:"):].strip())
            # Avance lento y monótono dentro del tramo de modelos.
            self._set(progress=min(0.98, 0.80 + 0.18 * (1.0 - 0.5 ** ((time.monotonic() - t0) / 60.0))))
        proc.wait()
        self._proc = None
        self._check_cancel()
        if proc.returncode != 0:
            raise RuntimeError("No se pudieron descargar los modelos:\n"
                               + "\n".join(lines[-6:]))
