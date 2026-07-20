"""
audio.devices — enumeración y deduplicación de dispositivos de audio.

Windows: PortAudio expone cada dispositivo bajo 4 APIs (MME, DirectSound, WASAPI, WDM-KS).
         Se prefiere WASAPI; WDM-KS solo para dispositivos sin equivalente WASAPI.

Linux:   PortAudio expone APIs ALSA, PulseAudio, JACK, PipeWire.
         Se acepta cualquier API y se deduplica por nombre, priorizando PipeWire/PulseAudio.
"""
import sys
from dataclasses import dataclass
import sounddevice as sd

if sys.platform == "win32":
    _API_PRIORITY = {
        "Windows WASAPI":     0,
        "Windows WDM-KS":     1,
        "MME":                2,
        "Windows DirectSound": 3,
    }
    _PREFERRED_APIS: set[str] | None = {"Windows WASAPI", "Windows WDM-KS"}
    _DEFAULT_API_TAG = "WASAPI"
else:
    _API_PRIORITY = {
        "PipeWire":                   0,
        "PulseAudio":                 1,
        "JACK Audio Connection Kit":  2,
        "ALSA":                       3,
    }
    _PREFERRED_APIS = None   # aceptar todas las APIs en Linux/Mac
    _DEFAULT_API_TAG = "PulseAudio"


class IncompatibleDevicesError(Exception):
    """Entrada y salida en APIs de host distintas: PortAudio no puede abrir un
    stream full-duplex que las combine (paBadIODeviceCombination, -9993).
    Caso típico en Windows: entrada WASAPI + una salida que solo existe en
    WDM-KS (p. ej. 'Altavoces' expuestos por WDM, o el Stereo Mix)."""

    def __init__(self, input_api: str, output_api: str):
        self.input_api = input_api
        self.output_api = output_api
        super().__init__(
            f"APIs de host incompatibles: entrada={input_api!r} salida={output_api!r}"
        )


def hostapi_of(device_index: "int | None", kind: str = "input") -> str:
    """Nombre de la API de host de un dispositivo (Windows WASAPI, Windows WDM-KS,
    ALSA, PulseAudio, ...). Con device_index None usa el default de `kind`."""
    dev = sd.query_devices(device_index) if device_index is not None \
        else sd.query_devices(kind=kind)
    return sd.query_hostapis()[dev["hostapi"]]["name"]


def duplex_hostapi_mismatch(input_index, output_index) -> "tuple[str, str] | None":
    """Devuelve (api_entrada, api_salida) si están en APIs de host DISTINTAS —
    combinación que PortAudio rechaza en un stream full-duplex con el error -9993
    (paBadIODeviceCombination) — o None si son compatibles (misma API) o no se
    puede determinar. Un stream duplex único exige ambos dispositivos en la misma
    API de host."""
    try:
        in_api = hostapi_of(input_index, "input")
        out_api = hostapi_of(output_index, "output")
    except Exception:
        return None   # ante la duda no bloquear — dejamos que PortAudio decida
    return (in_api, out_api) if in_api != out_api else None


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    host_api: str = ""

    def supports_input(self) -> bool:
        return self.max_input_channels > 0

    def supports_output(self) -> bool:
        return self.max_output_channels > 0

    def display_name(self) -> str:
        if sys.platform == "win32":
            tag = (" [WASAPI]" if "WASAPI" in self.host_api
                   else " [WDM]" if "WDM" in self.host_api
                   else "")
        else:
            tag = f" [{self.host_api}]" if self.host_api else ""
        return f"{self.name}{tag}"

    def __str__(self) -> str:
        return self.display_name()


def list_devices() -> list[AudioDevice]:
    """
    Devuelve la lista de dispositivos deduplicada por nombre+dirección,
    priorizando la API de menor latencia según la plataforma.
    """
    all_devs = sd.query_devices()
    all_apis = sd.query_hostapis()

    candidates: list[tuple[int, dict, str, int]] = []
    for i, dev in enumerate(all_devs):
        api_name = all_apis[dev["hostapi"]]["name"]
        if _PREFERRED_APIS is not None and api_name not in _PREFERRED_APIS:
            continue
        priority = _API_PRIORITY.get(api_name, 99)
        candidates.append((i, dev, api_name, priority))

    # Deduplicar por nombre normalizado + tipo (in/out), quedando con mejor prioridad
    best: dict[tuple[str, bool], tuple[int, dict, str, int]] = {}
    for item in candidates:
        idx, dev, api_name, priority = item
        norm = _normalize(dev["name"])
        for is_input in (True, False):
            if is_input and dev["max_input_channels"] == 0:
                continue
            if not is_input and dev["max_output_channels"] == 0:
                continue
            key = (norm, is_input)
            if key not in best or priority < best[key][3]:
                best[key] = item

    seen_indices: set[int] = set()
    result: list[AudioDevice] = []
    for (norm, _), (idx, dev, api_name, _) in sorted(best.items(), key=lambda x: x[1][0]):
        if idx in seen_indices:
            continue
        seen_indices.add(idx)
        result.append(AudioDevice(
            index=idx,
            name=dev["name"],
            max_input_channels=dev["max_input_channels"],
            max_output_channels=dev["max_output_channels"],
            default_sample_rate=dev["default_samplerate"],
            host_api=api_name,
        ))

    return result


def rescan_devices() -> list[AudioDevice]:
    """
    Reinicializa PortAudio y vuelve a enumerar el hardware.

    PortAudio congela la lista de dispositivos al inicializarse; para ver
    hardware conectado/desconectado después hay que terminar y reinicializar.
    NO llamar con un stream abierto — la reinicialización lo invalida.
    """
    sd._terminate()
    sd._initialize()
    return list_devices()


def get_default_input() -> "AudioDevice | None":
    devices = list_devices()
    for dev in devices:
        if dev.supports_input() and _DEFAULT_API_TAG in dev.host_api:
            return dev
    for dev in devices:
        if dev.supports_input():
            return dev
    return None


def get_default_output() -> "AudioDevice | None":
    devices = list_devices()
    for dev in devices:
        if dev.supports_output() and _DEFAULT_API_TAG in dev.host_api:
            return dev
    for dev in devices:
        if dev.supports_output():
            return dev
    return None


def _normalize(name: str) -> str:
    return name.lower().strip()
