"""
audio.stream — stream de audio en tiempo real via sounddevice (PortAudio).

El callback de sounddevice corre en un hilo de alta prioridad gestionado por PortAudio.
El procesador recibe bloques de audio float32 mono a 48kHz y devuelve el audio procesado.
No hacer operaciones bloqueantes (I/O, locks lentos) dentro del callback.
"""
import threading
import queue
import numpy as np
import sounddevice as sd
from collections.abc import Callable
from config import AudioConfig


AudioCallback = Callable[[np.ndarray], np.ndarray]


class AudioStream:
    """
    Gestiona el stream de entrada/salida en tiempo real.
    El procesador recibe bloques de audio (float32, mono, 48kHz) y devuelve el audio procesado.
    """

    def __init__(self, config: AudioConfig, processor: AudioCallback):
        self._config = config
        self._processor = processor
        self._stream: sd.Stream | None = None
        self._lock = threading.Lock()
        self._running = False
        self._overrun_count = 0
        self._underrun_count = 0

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stream = sd.Stream(
                samplerate=self._config.sample_rate,
                blocksize=self._config.block_size,
                device=(self._config.input_device, self._config.output_device),
                channels=self._config.channels,
                dtype=self._config.dtype,
                callback=self._callback,
                finished_callback=self._on_finished,
            )
            self._stream.start()
            self._running = True

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

    def is_running(self) -> bool:
        return self._running

    @property
    def latency_ms(self) -> float:
        if self._stream:
            return (self._stream.latency[0] + self._stream.latency[1]) * 1000
        return 0.0

    @property
    def overruns(self) -> int:
        return self._overrun_count

    def _callback(
        self,
        indata: np.ndarray,
        outdata: np.ndarray,
        frames: int,
        time,
        status: sd.CallbackFlags,
    ) -> None:
        if status.input_overflow:
            self._overrun_count += 1
        if status.output_underflow:
            self._underrun_count += 1

        audio_in = indata[:, 0].copy()  # mono
        try:
            audio_out = self._processor(audio_in)
        except Exception:
            import traceback
            traceback.print_exc()
            audio_out = audio_in

        if self._config.channels == 1:
            outdata[:, 0] = audio_out
        else:
            outdata[:] = audio_out[:, np.newaxis]

    def _on_finished(self) -> None:
        self._running = False
