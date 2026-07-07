"""
Runtime hook PyInstaller (Linux): preferir la libportaudio del sistema.

El bundle incluye la libportaudio del runner de build como fallback, pero la
del sistema suele ser más nueva y mejor integrada (backend PulseAudio nativo,
enumeración de PCMs virtuales default/pipewire). Pre-cargarla por ruta
absoluta con RTLD_GLOBAL hace que el dlopen posterior de sounddevice
("libportaudio.so.2") reutilice la ya cargada en lugar de resolver la del
bundle vía LD_LIBRARY_PATH. Si el sistema no la tiene, no pasa nada y se usa
la empaquetada.
"""
import ctypes
import glob
import sys

if sys.platform.startswith("linux"):
    _candidates = []
    for pat in (
        "/usr/lib/*/libportaudio.so.2",      # multiarch (x86_64/aarch64-linux-gnu)
        "/usr/lib/libportaudio.so.2",
        "/usr/local/lib/libportaudio.so.2",
    ):
        _candidates.extend(glob.glob(pat))
    for _path in _candidates:
        try:
            ctypes.CDLL(_path, mode=ctypes.RTLD_GLOBAL)
            break
        except OSError:
            continue
