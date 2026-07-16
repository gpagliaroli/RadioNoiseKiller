"""
audio.recorder — grabación a WAV 16-bit con hilo escritor propio.

El hilo DSP solo encola frames (feed() = queue.put, microsegundos); un hilo
escritor dedicado drena la cola y escribe a disco. Un pico de latencia del
disco NUNCA puede trabar el procesamiento de audio: si la cola se llena,
se descartan frames (se pierde un pedazo de grabación, no el audio en vivo).

Los archivos WAV los abre start() y los cierra SIEMPRE el hilo escritor
(finally) — el header del WAV se finaliza al cerrar, así el archivo queda
válido también si la grabación termina por error de disco.
"""
import queue
import threading
import wave

import numpy as np


class WavRecorder:
    """Graba uno o dos streams float32 (procesado y opcionalmente crudo)
    a archivos WAV mono 16-bit."""

    def __init__(self, sample_rate: int = 48000):
        self._sr = sample_rate
        self._queue: queue.Queue = queue.Queue(maxsize=256)   # ~2.5s @ hop 480
        self._thread: threading.Thread | None = None
        self._recording = False
        self._frames_written = 0
        self._error: str | None = None
        self._wav_proc: wave.Wave_write | None = None
        self._wav_raw:  wave.Wave_write | None = None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self, path_processed: str, path_raw: str | None = None) -> None:
        if self._recording:
            return
        self._wav_proc = self._open_wav(path_processed)
        self._wav_raw  = self._open_wav(path_raw) if path_raw else None
        self._drain()
        self._frames_written = 0
        self._error = None
        self._recording = True
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        """Detiene la grabación y devuelve los segundos grabados."""
        if not self._recording and self._thread is None:
            return 0.0
        self._recording = False
        try:
            self._queue.put(None, timeout=1.0)   # sentinel
        except queue.Full:
            self._drain()
            self._queue.put_nowait(None)
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        return self._frames_written / self._sr

    def feed(self, processed: np.ndarray, raw: "np.ndarray | None" = None) -> None:
        """Encola un frame. Llamable desde el hilo DSP (no bloquea nunca)."""
        if not self._recording:
            return
        try:
            self._queue.put_nowait((processed.copy(),
                                    raw.copy() if raw is not None else None))
        except queue.Full:
            pass  # descartar antes que trabar el DSP

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def wants_raw(self) -> bool:
        """True si esta grabación incluye el archivo de entrada cruda.
        Fijado en start() — cambiar el checkbox a mitad de grabación no
        afecta la grabación en curso (evita archivos desincronizados)."""
        return self._wav_raw is not None

    @property
    def seconds(self) -> float:
        """Segundos escritos a disco hasta ahora (para el indicador REC)."""
        return self._frames_written / self._sr

    @property
    def error(self) -> "str | None":
        """Mensaje de error si la escritura falló (disco lleno, permisos)."""
        return self._error

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _open_wav(self, path: str) -> wave.Wave_write:
        w = wave.open(path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)          # 16-bit
        w.setframerate(self._sr)
        return w

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @staticmethod
    def _to_int16(data: np.ndarray) -> bytes:
        return (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()

    def _writer(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                proc, raw = item
                try:
                    self._wav_proc.writeframes(self._to_int16(proc))
                    if raw is not None and self._wav_raw is not None:
                        self._wav_raw.writeframes(self._to_int16(raw))
                    self._frames_written += len(proc)
                except OSError as exc:
                    self._error = f"{exc}"
                    self._recording = False
                    break
        finally:
            for w in (self._wav_proc, self._wav_raw):
                if w is not None:
                    try:
                        w.close()
                    except OSError:
                        pass
            self._wav_proc = None
            self._wav_raw = None
