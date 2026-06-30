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
