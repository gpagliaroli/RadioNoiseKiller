"""
Cliente del módulo de Traducción: lanza translate_worker/worker.py como
proceso separado y habla con él por stdin/stdout (ver translate_protocol.py).

Nunca importa nada de translate_worker/ — son dos lados del mismo protocolo,
duplicado a propósito (ver translate_protocol.py). Sigue el mismo patrón que
el resto del pipeline: hilos de Python simples + atributos leídos por
polling desde un QTimer de la UI (invariante 7 del proyecto: un estado de
diagnóstico no justifica señales Qt cruzando hilos ni locks finos).
"""
import base64
import queue
import subprocess
import threading
import time
from collections import deque

import numpy as np
from scipy.signal import resample_poly

import translate_protocol as proto
from utils import log_path

WHISPER_SAMPLE_RATE = 16000


class TranslateClient:
    # Estados posibles, leídos por polling desde la UI.
    NOT_INSTALLED = "not_installed"
    STARTING      = "starting"
    READY         = "ready"
    CRASHED       = "crashed"
    STOPPED       = "stopped"

    def __init__(self):
        self._proc: "subprocess.Popen | None" = None
        self._reader_thread: "threading.Thread | None" = None
        self._stderr_thread: "threading.Thread | None" = None
        self._writer_thread: "threading.Thread | None" = None
        # maxsize=1: si el worker sigue ocupado con el chunk anterior, un
        # chunk nuevo se DESCARTA en vez de esperar (ver send_chunk) — mismo
        # criterio "best-effort, nunca crece sin límite" del resto del
        # proyecto (p. ej. _out_queue en pipeline.py).
        self._write_queue: "queue.Queue | None" = None
        self._state = self.STOPPED
        self._last_error = ""
        self._lock = threading.Lock()
        self._results: deque = deque()   # resultados pendientes de leer (pop_results)
        self._next_id = 1
        self._sent_at: dict = {}   # req_id -> time.monotonic() al mandar el chunk

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def start(self, python_path: str, script_path: str, model_size: str = "tiny") -> None:
        """Lanza el proceso. No bloquea esperando el 'ready' — eso se refleja
        en .state apenas llega (leer con polling)."""
        if not python_path or not script_path:
            with self._lock:
                self._state = self.NOT_INSTALLED
                self._last_error = "Rutas del worker no configuradas"
            return
        try:
            self._proc = subprocess.Popen(
                [python_path, script_path, model_size],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
                encoding="utf-8",
            )
        except (FileNotFoundError, OSError) as e:
            with self._lock:
                self._state = self.NOT_INSTALLED
                self._last_error = str(e)
            return
        with self._lock:
            self._state = self.STARTING
            self._last_error = ""
        self._write_queue = queue.Queue(maxsize=1)
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if self._write_queue is not None:
            try:
                self._write_queue.put_nowait(None)   # sentinel: libera _writer_loop
            except queue.Full:
                pass
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        with self._lock:
            self._state = self.STOPPED
        self._results.clear()

    def send_chunk(self, audio: np.ndarray, sample_rate: int,
                    lang_src: str = "auto", lang_dst: str = "es",
                    min_confidence: float = 0.5) -> "int | None":
        """Remuestrea a 16 kHz (si hace falta) y ENCOLA el chunk para que lo
        mande el hilo escritor propio — este método NO escribe al pipe
        directo. Si el worker sigue ocupado con el chunk anterior, escribir
        directo bloquearía (el pipe se llena y el worker no está leyendo
        stdin mientras transcribe/traduce) — y como esto se llama desde el
        hilo Qt (el QTimer de la pestaña), ese bloqueo se sentía como la UI
        entera congelada (reportado por el usuario). Con la cola, si ya hay
        un chunk esperando se descarta el nuevo (best-effort, igual que el
        resto del proyecto) en vez de esperar."""
        proc = self._proc
        if proc is None or self._write_queue is None or self.state != self.READY:
            return None
        if sample_rate != WHISPER_SAMPLE_RATE:
            from math import gcd
            g = gcd(sample_rate, WHISPER_SAMPLE_RATE)
            audio = resample_poly(
                audio, WHISPER_SAMPLE_RATE // g, sample_rate // g).astype(np.float32)
        audio_b64 = base64.b64encode(audio.astype(np.float32).tobytes()).decode("ascii")
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            self._sent_at[req_id] = time.monotonic()
        line = proto.encode_request(req_id, audio_b64, WHISPER_SAMPLE_RATE,
                                     lang_src, lang_dst, min_confidence)
        try:
            self._write_queue.put_nowait(line)
        except queue.Full:
            with self._lock:
                self._sent_at.pop(req_id, None)
            return None
        return req_id

    def pop_results(self) -> list:
        """Resultados nuevos desde la última llamada (lista de dicts del
        mensaje 'result' decodificado). Llamar desde el hilo Qt por polling."""
        out = []
        while True:
            try:
                out.append(self._results.popleft())
            except IndexError:
                break
        return out

    # ------------------------------------------------------------------
    # Hilos internos
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = proto.decode_line(line)
                except ValueError:
                    continue
                if msg.get("type") == "ready":
                    with self._lock:
                        self._state = self.READY
                elif msg.get("type") == "result":
                    with self._lock:
                        sent = self._sent_at.pop(msg.get("id"), None)
                    msg["latency_s"] = (time.monotonic() - sent) if sent is not None else None
                    self._results.append(msg)
        except Exception:
            pass
        # El loop termina cuando el proceso cierra stdout (crash o stop()
        # normal). stop() ya puso STOPPED; si llegamos acá por una caída
        # inesperada, marcar CRASHED salvo que ya estemos detenidos a propósito.
        with self._lock:
            if self._state not in (self.STOPPED, self.NOT_INSTALLED):
                self._state = self.CRASHED

    def _writer_loop(self) -> None:
        """Único hilo que escribe al stdin del worker. `.get()` bloquea
        esperando el próximo chunk (normal, es SU hilo); lo que no puede
        bloquear es el `write()`/`flush()` si el pipe está lleno porque el
        worker sigue ocupado — por eso vive separado del hilo Qt."""
        proc = self._proc
        wq = self._write_queue
        if proc is None or wq is None:
            return
        while True:
            line = wq.get()
            if line is None:   # sentinel de stop()
                return
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                with self._lock:
                    self._state = self.CRASHED
                    self._last_error = str(e)
                return

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                try:
                    with open(log_path(), "a", encoding="utf-8") as f:
                        f.write(f"[translate_worker] {line}\n")
                except Exception:
                    pass
        except Exception:
            pass
