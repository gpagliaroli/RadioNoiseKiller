"""
Tests del módulo de Traducción (ASR+MT offline, proceso separado):
- Protocolo IPC (src/translate_protocol.py): roundtrip, sin red ni proceso.
- Buffer continuo de audio en pipeline.py.
- TranslateClient con el subprocess mockeado (sin lanzar el proceso real,
  sin requerir faster-whisper/argostranslate instalados).

La calidad real de transcripción/traducción NO se testea aca (se validó a
mano con grabaciones reales en el spike) — ver docs/HISTORIAL_TECNICO.md.
"""
import os
import sys
import tempfile
import threading

if not os.environ.get("RNK_DATA_DIR"):
    os.environ["RNK_DATA_DIR"] = tempfile.mkdtemp(prefix="rnk_test_translate_")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

import translate_protocol as proto
from config import AppConfig
from pipeline import ProcessingPipeline
from translate_client import TranslateClient


# ---------------------------------------------------------------------- #
# 1. Protocolo IPC                                                        #
# ---------------------------------------------------------------------- #

def test_protocol_roundtrip():
    line = proto.encode_request(7, "QUJD", 16000, "auto", "es", 0.6)
    msg = proto.decode_line(line)
    assert msg == {"type": "transcribe", "id": 7, "audio_b64": "QUJD",
                   "sample_rate": 16000, "lang_src": "auto", "lang_dst": "es",
                   "min_confidence": 0.6}

    line = proto.encode_result(7, "zh", 0.97, [{"start": 0.0, "end": 1.0,
                                                 "text": "你好", "translated": "Hola"}])
    msg = proto.decode_line(line)
    assert msg["ok"] is True
    assert msg["detected_lang"] == "zh"
    assert msg["segments"][0]["translated"] == "Hola"
    assert msg["low_confidence"] is False, "low_confidence default debe ser False"

    line = proto.encode_result(8, "nn", 0.34, [{"start": 0.0, "end": 1.0, "text": "..."}],
                                low_confidence=True)
    msg = proto.decode_line(line)
    assert msg["low_confidence"] is True

    line = proto.encode_error(7, "no_language_pair", "zh->xx")
    msg = proto.decode_line(line)
    assert msg["ok"] is False
    assert msg["error"] == "no_language_pair"
    print("Protocolo: roundtrip request/result/error      OK")


def test_protocol_rejects_garbage():
    for bad in ["no es json", "{}", '{"sin_type": 1}', "[1,2,3]"]:
        try:
            proto.decode_line(bad)
            raise AssertionError(f"debia rechazar: {bad!r}")
        except ValueError:
            pass
        except Exception as e:
            assert isinstance(e, ValueError), f"excepcion inesperada para {bad!r}: {e!r}"
    print("Protocolo: rechaza basura sin tumbar el loop    OK")


# ---------------------------------------------------------------------- #
# 2. Buffer continuo en pipeline.py                                       #
# ---------------------------------------------------------------------- #

def test_translate_buffer_accumulates_and_pops():
    cfg = AppConfig()
    p = ProcessingPipeline(cfg)
    sr = cfg.audio.sample_rate
    hop = cfg.audio.block_size

    assert p.pop_translate_chunk(1.0) is None, "no deberia haber nada antes de activar"

    p.set_translate_enabled(True)
    # Feed manual (sin hilo de audio) apendeando hops chicos a la deque —
    # ES el punto que se estaba probando: el llenado NO debe reconstruir un
    # ndarray completo en cada hop (ver el comentario largo en pipeline.py,
    # invariante nueva: apendear es O(1), concatenar se paga solo al pop).
    n_hops = int(2.5 * sr / hop) + 1
    for i in range(n_hops):
        chunk = np.full(hop, 0.01 * (i % 7), dtype=np.float32)
        with p._translate_lock:
            p._translate_buf.append(chunk)
            p._translate_buf_len += len(chunk)

    got = p.pop_translate_chunk(2.0)
    assert got is not None and len(got) == int(2.0 * sr), \
        f"esperaba {int(2.0*sr)} muestras, dio {None if got is None else len(got)}"
    print("Buffer de traduccion: acumula y entrega chunks   OK")


def test_translate_buffer_disabled_does_not_pop():
    cfg = AppConfig()
    p = ProcessingPipeline(cfg)
    p.set_translate_enabled(True)
    with p._translate_lock:
        buf = np.ones(int(5.0 * cfg.audio.sample_rate), dtype=np.float32)
        p._translate_buf.append(buf)
        p._translate_buf_len += len(buf)
    p.set_translate_enabled(False)   # debe limpiar el buffer
    assert p.pop_translate_chunk(1.0) is None, \
        "set_translate_enabled(False) debe limpiar el buffer, no solo dejar de llenarlo"
    print("Buffer de traduccion: se limpia al desactivar    OK")


def test_translate_buffer_caps_at_max() -> None:
    """Mismo algoritmo de recorte que _process_chunk (append + popleft en
    bucle) — acá se prueba con hops chicos repetidos, no con un bloque
    gigante de una, para que el test sea representativo de cómo se llena
    en la práctica (un hop de audio por vez, ~cada 10-20ms)."""
    cfg = AppConfig()
    p = ProcessingPipeline(cfg)
    p.set_translate_enabled(True)
    hop = cfg.audio.block_size
    n_hops = p._translate_buf_max // hop + 50   # bastante para superar el tope
    for _ in range(n_hops):
        chunk = np.ones(hop, dtype=np.float32)
        with p._translate_lock:
            p._translate_buf.append(chunk)
            p._translate_buf_len += len(chunk)
            while p._translate_buf_len > p._translate_buf_max:
                old = p._translate_buf.popleft()
                p._translate_buf_len -= len(old)
    assert p._translate_buf_len <= p._translate_buf_max, \
        "el buffer no debe crecer sin limite (perderia audio nuevo igual, pero sin memoria acotada)"
    assert p._translate_buf_len > p._translate_buf_max - hop, \
        "el recorte no deberia dejar mucho menos que el tope (tira de a un hop por vez)"
    print("Buffer de traduccion: tope de tamano respetado   OK")


# ---------------------------------------------------------------------- #
# 3. TranslateClient con el subprocess mockeado                          #
# ---------------------------------------------------------------------- #

class _FakeStdin:
    def __init__(self):
        self.lines = []
    def write(self, s):
        self.lines.append(s)
    def flush(self):
        pass
    def close(self):
        pass


class _SlowStdin(_FakeStdin):
    """write() se queda esperando hasta release() — simula el pipe lleno
    porque el worker real sigue ocupado transcribiendo/traduciendo el chunk
    anterior y no vuelve a leer stdin."""
    def __init__(self):
        super().__init__()
        self._gate = threading.Event()
    def write(self, s):
        self._gate.wait()
        super().write(s)
    def release(self):
        self._gate.set()


class _BlockingLines:
    """Itera las lineas dadas y despues BLOQUEA (no levanta StopIteration)
    hasta que se llama a .close() — simula un proceso real que sigue vivo
    después de mandar sus mensajes, en vez de uno que cerró stdout (crash)."""
    def __init__(self, lines):
        self._lines = list(lines)
        self._closed = threading.Event()
    def __iter__(self):
        return self
    def __next__(self):
        if self._lines:
            return self._lines.pop(0)
        self._closed.wait()
        raise StopIteration
    def close(self):
        self._closed.set()


class _FakeProc:
    """Doble de subprocess.Popen: stdout da lineas predefinidas, sin tocar
    disco ni red ni requerir faster-whisper/argostranslate instalados."""
    def __init__(self, stdout_lines, blocking: bool = False, stdin=None):
        self.stdin = stdin if stdin is not None else _FakeStdin()
        self.stdout = _BlockingLines(stdout_lines) if blocking else iter(stdout_lines)
        self.stderr = iter([])
        self._returncode = None
    def poll(self):
        return self._returncode
    def terminate(self):
        self._returncode = 0
        if isinstance(self.stdout, _BlockingLines):
            self.stdout.close()
    def wait(self, timeout=None):
        pass
    def kill(self):
        self._returncode = -9


def test_translate_client_not_installed_without_paths():
    c = TranslateClient()
    c.start("", "")
    assert c.state == TranslateClient.NOT_INSTALLED
    print("TranslateClient: rutas vacias -> not_installed   OK")


def test_translate_client_not_installed_bad_path():
    c = TranslateClient()
    c.start(r"C:\ruta\que\no\existe\python.exe", r"C:\tampoco\worker.py")
    assert c.state == TranslateClient.NOT_INSTALLED
    print("TranslateClient: ruta invalida -> not_installed  OK")


def test_translate_client_ready_and_result_via_fake_proc():
    import time
    import subprocess
    c = TranslateClient()
    ready_line = proto.encode_ready("tiny") + "\n"
    result_line = proto.encode_result(1, "en", 0.9,
                                       [{"start": 0.0, "end": 1.0, "text": "hi",
                                         "translated": "hola"}]) + "\n"
    # blocking=True: el proceso "sigue vivo" tras mandar sus 2 lineas (no
    # cierra stdout) — si no, el reader loop lo interpreta como crash
    # apenas se agotan las lineas, que es bug-compatible con un proceso
    # real pero no lo que este test quiere ejercitar.
    fake = _FakeProc([ready_line, result_line], blocking=True)

    orig_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: fake
    try:
        c.start("python", "worker.py")
        t0 = time.time()
        while c.state != TranslateClient.READY and time.time() - t0 < 2.0:
            time.sleep(0.02)
    finally:
        subprocess.Popen = orig_popen

    assert c.state == TranslateClient.READY, c.state
    results = c.pop_results()
    assert len(results) == 1 and results[0]["segments"][0]["translated"] == "hola"
    c.stop()
    print("TranslateClient: ready + resultado via proceso falso  OK")


def test_translate_client_send_chunk_never_blocks():
    """send_chunk() nunca debe bloquear al que llama (el hilo Qt vía
    _tick) aunque la escritura real al pipe esté trabada — regresión del
    bug reportado por el usuario: la UI se congelaba con la traducción
    activa porque antes send_chunk() escribía directo al stdin del worker,
    y si éste seguía ocupado con el chunk anterior, el pipe se llenaba y
    write() bloqueaba en el hilo de la UI."""
    import time
    import subprocess
    c = TranslateClient()
    slow_stdin = _SlowStdin()
    fake = _FakeProc([proto.encode_ready("tiny") + "\n"], blocking=True, stdin=slow_stdin)

    orig_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: fake
    try:
        c.start("python", "worker.py")
        t0 = time.time()
        while c.state != TranslateClient.READY and time.time() - t0 < 2.0:
            time.sleep(0.02)
        assert c.state == TranslateClient.READY

        audio = np.zeros(1600, dtype=np.float32)
        id1 = c.send_chunk(audio, 16000)
        assert id1 is not None, "el primer chunk deberia aceptarse"
        time.sleep(0.1)   # dejar que _writer_loop saque id1 de la cola y se trabe en write()

        t0 = time.time()
        id2 = c.send_chunk(audio, 16000)   # la cola tiene lugar (writer ya sacó id1)
        dt2 = time.time() - t0
        assert dt2 < 0.5, f"send_chunk tardo {dt2:.2f}s — se esta bloqueando"
        time.sleep(0.1)

        t0 = time.time()
        id3 = c.send_chunk(audio, 16000)   # cola llena (id2 esperando) -> se descarta
        dt3 = time.time() - t0
        assert dt3 < 0.5, f"send_chunk tardo {dt3:.2f}s — se esta bloqueando"
        assert id3 is None, "con la cola llena deberia descartar el chunk, no esperar"

        slow_stdin.release()
    finally:
        subprocess.Popen = orig_popen
        slow_stdin.release()
        c.stop()
    print("TranslateClient: send_chunk nunca bloquea (regresion freeze)  OK")


def test_translate_client_crashed_on_unexpected_exit():
    import subprocess
    c = TranslateClient()
    fake = _FakeProc([proto.encode_ready("tiny") + "\n"])  # stdout se cierra despues

    orig_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: fake
    try:
        c.start("python", "worker.py")
        c._reader_thread.join(timeout=2.0)
    finally:
        subprocess.Popen = orig_popen

    assert c.state == TranslateClient.CRASHED, \
        f"stdout cerrado sin stop() explicito deberia marcar crashed, dio {c.state}"
    print("TranslateClient: salida inesperada -> crashed    OK")


# ---------------------------------------------------------------------- #
# 5. Instalador en un clic (sin red: pasos reales reemplazados por falsos) #
# ---------------------------------------------------------------------- #

import time
import translate_installer as inst


def _wait_installer(ins, timeout=5.0):
    t0 = time.monotonic()
    while ins.is_running() and time.monotonic() - t0 < timeout:
        time.sleep(0.02)


def _fake_installer(fail=False):
    ins = inst.TranslateInstaller()

    def make_python():
        py = inst.runtime_python()
        os.makedirs(os.path.dirname(py), exist_ok=True)
        open(py, "w").close()

    ins._make_python = make_python
    ins._pip_install = lambda: None
    if fail:
        def boom(*a):
            raise RuntimeError("sin internet")
        ins._prefetch = boom
    else:
        ins._prefetch = lambda *a: None
    return ins


def test_installer_paths_inside_data_dir():
    base = os.path.abspath(os.environ["RNK_DATA_DIR"])
    assert os.path.abspath(inst.runtime_dir()).startswith(base)
    assert not inst.is_installed()
    print("TranslateInstaller: rutas bajo RNK_DATA_DIR, no instalado por defecto  OK")


def test_installer_success_marks_installed_and_uninstalls():
    inst.uninstall()
    ins = _fake_installer()
    ins.start("tiny", ["en"], ["es"])
    _wait_installer(ins)
    assert ins.state == inst.TranslateInstaller.DONE, (ins.state, ins.last_error)
    assert ins.progress == 1.0
    assert inst.is_installed()
    assert os.path.isfile(inst.runtime_worker_script())   # worker copiado
    env = inst.worker_env()
    assert env["HF_HOME"].startswith(inst.runtime_dir())
    inst.uninstall()
    assert not inst.is_installed() and not os.path.exists(inst.runtime_dir())
    print("TranslateInstaller: instala, marca y desinstala  OK")


def test_installer_error_rolls_back():
    inst.uninstall()
    ins = _fake_installer(fail=True)
    ins.start("tiny", ["en"], ["es"])
    _wait_installer(ins)
    assert ins.state == inst.TranslateInstaller.ERROR
    assert "sin internet" in ins.last_error
    assert not os.path.exists(inst.runtime_dir())   # carpeta parcial borrada
    assert not inst.is_installed()
    print("TranslateInstaller: error -> estado ERROR y rollback de la carpeta  OK")


def test_installer_cancel():
    inst.uninstall()
    ins = inst.TranslateInstaller()
    gate = threading.Event()

    def slow_python():
        gate.wait(2.0)
        ins._check_cancel()

    ins._make_python = slow_python
    ins.start("tiny", ["en"], ["es"])
    ins.cancel()
    gate.set()
    _wait_installer(ins)
    assert ins.state == inst.TranslateInstaller.CANCELLED
    assert not os.path.exists(inst.runtime_dir())
    print("TranslateInstaller: cancelar deja todo limpio  OK")


def test_installer_estimate_scales_with_pairs():
    assert inst.estimate_download_mb("tiny", 2) > inst.estimate_download_mb("tiny", 1)
    print("TranslateInstaller: estimacion de descarga  OK")



if __name__ == "__main__":
    test_protocol_roundtrip()
    test_protocol_rejects_garbage()
    test_translate_buffer_accumulates_and_pops()
    test_translate_buffer_disabled_does_not_pop()
    test_translate_buffer_caps_at_max()
    test_translate_client_not_installed_without_paths()
    test_translate_client_not_installed_bad_path()
    test_translate_client_ready_and_result_via_fake_proc()
    test_translate_client_send_chunk_never_blocks()
    test_translate_client_crashed_on_unexpected_exit()
    test_installer_paths_inside_data_dir()
    test_installer_success_marks_installed_and_uninstalls()
    test_installer_error_rolls_back()
    test_installer_cancel()
    test_installer_estimate_scales_with_pairs()
    print()
    print("Todos los tests pasaron.")
