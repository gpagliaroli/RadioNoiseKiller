"""
audio.stream — stream de audio en tiempo real via sounddevice (PortAudio).

El callback de sounddevice corre en un hilo de alta prioridad gestionado por PortAudio.
El procesador recibe bloques de audio float32 mono a 48kHz y devuelve el audio procesado.
No hacer operaciones bloqueantes (I/O, locks lentos) dentro del callback.
"""
import threading
import time as _time   # el callback tiene un parametro `time`: no lo pisa
import numpy as np
import sounddevice as sd
from collections.abc import Callable
from config import AudioConfig
from audio.devices import duplex_hostapi_mismatch, IncompatibleDevicesError


AudioCallback = Callable[[np.ndarray], np.ndarray]

# Protección contra un driver colgado (interfaz USB que se cae, servicio de
# audio de Windows que se traba): Pa_OpenStream / Pa_StopStream / Pa_CloseStream
# pueden no volver NUNCA. Se ejecutan en un hilo auxiliar y la GUI espera como
# mucho estos segundos; pasado el plazo, el stream se da por abandonado (el hilo
# queda colgado en el driver — no hay forma de matarlo — pero la app sigue viva
# y el usuario puede cerrar con la configuración guardada).
OPEN_TIMEOUT_S  = 8.0    # abrir + arrancar; en hardware sano tarda < 1 s
CLOSE_TIMEOUT_S = 3.0    # detener + cerrar; en hardware sano tarda < 100 ms
# Si el callback no llega en este tiempo con el stream activo, el dispositivo
# dejó de responder (PortAudio no siempre avisa: finished_callback solo se
# dispara cuando el driver reporta el fin del stream, y un driver colgado no lo
# reporta). 3 s deja margen de sobra a los stalls de CPU legítimos (< 300 ms).
STALL_TIMEOUT_S = 3.0

_abandoned = 0


def abandoned_streams() -> int:
    """Cantidad de streams que quedaron colgados en el driver (ver main.py:
    con uno de éstos, el atexit de sounddevice se bloquearía al salir)."""
    return _abandoned


class AudioDeviceError(RuntimeError):
    """El dispositivo de audio no respondió a tiempo al abrir el stream."""


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
        self._finished = False          # PortAudio dio por terminado el stream
        self._abandoned = False         # el driver no respondió: hilo colgado
        self._last_callback_t = 0.0     # _time.monotonic() del último callback
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
                self._stream = self._open_with_timeout(in_ch, out_ch)
            except sd.PortAudioError as e:
                # Red de seguridad por si el chequeo proactivo no detectó el caso
                # (índices raros, drivers atípicos): traducir el -9993 igual.
                if "-9993" in str(e) or "combination" in str(e).lower():
                    m = duplex_hostapi_mismatch(
                        self._config.input_device, self._config.output_device)
                    raise IncompatibleDevicesError(*(m or ("?", "?"))) from e
                raise
            self._finished = False
            self._last_callback_t = _time.monotonic()
            self._running = True

    def _open_with_timeout(self, in_ch: int, out_ch: int) -> sd.Stream:
        """Abre y arranca el stream en un hilo auxiliar, esperando como mucho
        OPEN_TIMEOUT_S. Si el driver no responde a tiempo, levanta
        AudioDeviceError y el hilo queda a cargo de cerrar el stream si es que
        el driver termina abriéndolo más tarde (así no queda un stream huérfano
        llamando al callback de un pipeline que ya no corre)."""
        result: dict = {}
        state_lock = threading.Lock()
        gave_up = [False]

        def worker():
            try:
                st = sd.Stream(
                    samplerate=self._config.sample_rate,
                    blocksize=self._config.block_size,
                    device=(self._config.input_device, self._config.output_device),
                    channels=(in_ch, out_ch),
                    dtype=self._config.dtype,
                    callback=self._callback,
                    finished_callback=self._on_finished,
                )
                st.start()
            except BaseException as e:   # se re-levanta en el hilo que llamó
                result["error"] = e
                return
            with state_lock:
                if gave_up[0]:
                    # Llegó tarde: nadie lo va a usar. Cerrarlo acá mismo.
                    try:
                        st.stop()
                        st.close()
                    except Exception:
                        pass
                    return
                result["stream"] = st

        t = threading.Thread(target=worker, name="rnk-open-stream", daemon=True)
        t.start()
        t.join(OPEN_TIMEOUT_S)
        with state_lock:
            if "stream" in result:
                return result["stream"]
            if "error" in result:
                raise result["error"]
            gave_up[0] = True
        global _abandoned
        _abandoned += 1
        self._abandoned = True
        raise AudioDeviceError(
            "El dispositivo de audio no responde (timeout al abrir el stream)")

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
            stream, self._stream = self._stream, None
        if stream is None:
            return
        # stop() antes de close(): sin eso PortAudio se cuelga en close (nota del
        # exit handler de sounddevice). Las dos en un hilo aparte con timeout: con
        # el driver caído ninguna de las dos vuelve y la GUI quedaba congelada.
        def worker():
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        t = threading.Thread(target=worker, name="rnk-close-stream", daemon=True)
        t.start()
        t.join(CLOSE_TIMEOUT_S)
        if t.is_alive():
            global _abandoned
            _abandoned += 1
            self._abandoned = True
            print("AudioStream: el driver no respondió al cerrar el stream — "
                  "se abandona (hilo colgado en PortAudio)", flush=True)

    def is_running(self) -> bool:
        return self._running

    @property
    def finished(self) -> bool:
        """True si PortAudio dio por terminado el stream por su cuenta (el
        dispositivo desapareció o el driver lo cerró) mientras estaba activo."""
        return self._finished

    @property
    def abandoned(self) -> bool:
        return self._abandoned

    @property
    def seconds_since_callback(self) -> float:
        """Tiempo desde el último callback de PortAudio. Con el stream activo,
        más de STALL_TIMEOUT_S significa que el dispositivo dejó de responder."""
        return _time.monotonic() - self._last_callback_t

    @property
    def device_lost(self) -> bool:
        """El dispositivo dejó de entregar audio: stream terminado por el driver
        o callback ausente por más de STALL_TIMEOUT_S. Sólo válido con el stream
        arrancado (start() ya volvió)."""
        return self._running and (
            self._finished or self.seconds_since_callback > STALL_TIMEOUT_S)

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
        self._last_callback_t = _time.monotonic()   # float: escritura atómica
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
        # Lo dispara PortAudio tanto tras nuestro stop() como cuando el driver
        # termina el stream solo (dispositivo desconectado). _running queda en
        # True a propósito: lo baja stop(), que es quien cierra; `finished` es
        # lo que mira el watchdog para distinguir los dos casos.
        self._finished = True
