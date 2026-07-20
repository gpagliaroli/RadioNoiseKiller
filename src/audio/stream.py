"""
audio.stream — stream de audio en tiempo real via sounddevice (PortAudio).

El callback de sounddevice corre en un hilo de alta prioridad gestionado por PortAudio.
El procesador recibe bloques de audio float32 mono a 48kHz y devuelve el audio procesado.
No hacer operaciones bloqueantes (I/O, locks lentos) dentro del callback.
"""
import threading
import numpy as np
import sounddevice as sd
from collections.abc import Callable
from config import AudioConfig
from audio.devices import duplex_hostapi_mismatch, IncompatibleDevicesError


AudioCallback = Callable[[np.ndarray], np.ndarray]


def pick_input_channel(indata: np.ndarray, mode: str) -> np.ndarray:
    """Reduce el bloque de entrada a mono según el canal elegido.

    mode: "left" | "right" | "mix". Con entrada mono se ignora (columna 0).
    Devuelve SIEMPRE una copia (el buffer de PortAudio se reutiliza).
    """
    if indata.shape[1] == 1 or mode == "left":
        return indata[:, 0].copy()
    if mode == "right":
        return indata[:, 1].copy()
    return (indata[:, 0] + indata[:, 1]) * 0.5  # mix — ya es un array nuevo


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
            # Chequeo proactivo: un stream full-duplex exige que entrada y salida
            # sean de la MISMA API de host. Si no, PortAudio falla con -9993
            # (paBadIODeviceCombination). Lo detectamos antes para dar un mensaje
            # claro en vez del error críptico.
            mismatch = duplex_hostapi_mismatch(
                self._config.input_device, self._config.output_device)
            if mismatch:
                raise IncompatibleDevicesError(*mismatch)
            # Abrir estéreo cuando el dispositivo lo permite: la entrada para
            # poder elegir canal (interfaces con la radio en el canal derecho,
            # doble receptor), la salida en dual-mono (con salida de 1 canal
            # algunos drivers reproducen en un solo auricular o fallan al abrir).
            in_ch  = min(2, max(1, self._device_max(self._config.input_device,  "input")))
            out_ch = min(2, max(1, self._device_max(self._config.output_device, "output")))
            try:
                self._stream = sd.Stream(
                    samplerate=self._config.sample_rate,
                    blocksize=self._config.block_size,
                    device=(self._config.input_device, self._config.output_device),
                    channels=(in_ch, out_ch),
                    dtype=self._config.dtype,
                    callback=self._callback,
                    finished_callback=self._on_finished,
                )
                self._stream.start()
            except sd.PortAudioError as e:
                # Red de seguridad por si el chequeo proactivo no detectó el caso
                # (índices raros, drivers atípicos): traducir el -9993 igual.
                if "-9993" in str(e) or "combination" in str(e).lower():
                    m = duplex_hostapi_mismatch(
                        self._config.input_device, self._config.output_device)
                    raise IncompatibleDevicesError(*(m or ("?", "?"))) from e
                raise
            self._running = True

    @staticmethod
    def _device_max(device: "int | None", kind: str) -> int:
        try:
            info = sd.query_devices(device, kind) if device is not None \
                else sd.query_devices(kind=kind)
            return int(info[f"max_{kind}_channels"])
        except Exception:
            return 1

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

        # Lectura por bloque: cambiar input_channel en la UI aplica en vivo
        # (lectura de atributo str — atómica, sin lock)
        audio_in = pick_input_channel(indata, self._config.input_channel)
        try:
            audio_out = self._processor(audio_in)
        except Exception:
            import traceback
            traceback.print_exc()
            audio_out = audio_in

        # Dual-mono: la misma señal procesada a todos los canales de salida
        outdata[:] = audio_out[:, np.newaxis]

    def _on_finished(self) -> None:
        self._running = False
