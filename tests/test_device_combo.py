"""
Detección de combinación de dispositivos incompatible (PaErrorCode -9993).

Un stream full-duplex de PortAudio exige que la entrada y la salida sean de la
MISMA API de host. Combinar, p. ej., un micrófono WASAPI con unos 'Altavoces'
que solo existen en WDM-KS falla con paBadIODeviceCombination (-9993) al Activar.

Este test mockea sounddevice (sin hardware) para verificar que:
  - duplex_hostapi_mismatch() detecta el cruce de APIs y lo reporta,
  - una combinación de la misma API pasa,
  - AudioStream.start() lanza IncompatibleDevicesError ANTES de tocar PortAudio.
"""
import sys
sys.path.insert(0, "src")
import sounddevice as sd
from config import AudioConfig
from audio.devices import (
    duplex_hostapi_mismatch, hostapi_of, IncompatibleDevicesError,
)

# Tabla simulada: 0=mic WASAPI, 1=altavoces WDM-KS, 2=altavoces WASAPI
_DEVS = [
    {"name": "Micrófono",     "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000},
    {"name": "Altavoces WDM", "hostapi": 1, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000},
    {"name": "Altavoces",     "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000},
]
_APIS = [{"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]


def _fake_query_devices(device=None, kind=None):
    if device is None:
        return _DEVS
    return _DEVS[device]


def _install_fakes():
    sd.query_devices = _fake_query_devices
    sd.query_hostapis = lambda: _APIS


def test_hostapi_of():
    _install_fakes()
    assert hostapi_of(0) == "Windows WASAPI"
    assert hostapi_of(1) == "Windows WDM-KS"
    print("hostapi_of devuelve la API correcta       OK")


def test_mismatch_detected():
    _install_fakes()
    # WASAPI (0) + WDM-KS (1) -> incompatible
    assert duplex_hostapi_mismatch(0, 1) == ("Windows WASAPI", "Windows WDM-KS")
    # WASAPI (0) + WASAPI (2) -> compatible
    assert duplex_hostapi_mismatch(0, 2) is None
    print("duplex_hostapi_mismatch detecta el cruce  OK")


def test_stream_raises_before_portaudio():
    """AudioStream.start() debe lanzar IncompatibleDevicesError por el chequeo
    proactivo, sin llegar a abrir el stream real (sd.Stream)."""
    _install_fakes()
    # Bomba: si el chequeo NO frena, sd.Stream explota distinto y lo notamos
    def _boom(*a, **k):
        raise AssertionError("sd.Stream no debería llamarse con APIs cruzadas")
    sd.Stream = _boom

    from audio.stream import AudioStream
    cfg = AudioConfig()
    cfg.input_device = 0     # WASAPI
    cfg.output_device = 1    # WDM-KS
    st = AudioStream(cfg, lambda x: x)
    try:
        st.start()
        assert False, "start() debería haber lanzado IncompatibleDevicesError"
    except IncompatibleDevicesError as e:
        assert e.input_api == "Windows WASAPI"
        assert e.output_api == "Windows WDM-KS"
    print("AudioStream.start lanza antes de PortAudio OK")


def test_raw_hdmi_hidden_on_linux():
    """El HDMI de la Raspberry Pi abierto por ALSA `hw:` no acepta float32/int16
    y falla al Activar con -9994. Medido en una Pi 4 real: las placas USB, los
    auriculares y las salidas ALSA `hdmi`/`default` sí abren."""
    import audio.devices as ad
    devs = [
        {"name": "vc4-hdmi-0: MAI PCM i2s-hifi-0 (hw:0,0)", "hostapi": 0,
         "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 44100},
        {"name": "bcm2835 Headphones: - (hw:2,0)", "hostapi": 0,
         "max_input_channels": 0, "max_output_channels": 8, "default_samplerate": 44100},
        {"name": "USB PnP Sound Device: Audio (hw:3,0)", "hostapi": 0,
         "max_input_channels": 1, "max_output_channels": 2, "default_samplerate": 44100},
        {"name": "hdmi", "hostapi": 0,
         "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 44100},
    ]
    saved = (sd.query_devices, sd.query_hostapis, sys.platform, ad._PREFERRED_APIS)
    try:
        sd.query_devices = lambda device=None, kind=None: devs if device is None else devs[device]
        sd.query_hostapis = lambda: [{"name": "ALSA"}]
        sys.platform = "linux"
        ad._PREFERRED_APIS = None
        assert ad.is_raw_hdmi_hw(devs[0]["name"], "ALSA")
        assert not ad.is_raw_hdmi_hw("hdmi", "ALSA"), "la salida ALSA 'hdmi' sí abre"
        assert not ad.is_raw_hdmi_hw(devs[1]["name"], "ALSA")
        assert not ad.is_raw_hdmi_hw(devs[0]["name"], "PulseAudio")
        idx = [d.index for d in ad.list_devices()]
        assert 0 not in idx, f"el HDMI hw: sigue en la lista: {idx}"
        assert idx == [1, 2, 3], idx
        # El default ya no cae en el HDMI por ser el primero de la lista
        assert ad.get_default_output().index == 1
        sys.platform = "win32"
        assert not ad.is_raw_hdmi_hw(devs[0]["name"], "ALSA"), "en Windows no se filtra"
    finally:
        sd.query_devices, sd.query_hostapis, sys.platform, ad._PREFERRED_APIS = saved
    print("HDMI hw: oculto en Linux, intacto en Windows OK")


if __name__ == "__main__":
    test_hostapi_of()
    test_mismatch_detected()
    test_stream_raises_before_portaudio()
    test_raw_hdmi_hidden_on_linux()
    print()
    print("test_device_combo: OK")
