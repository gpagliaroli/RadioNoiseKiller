"""
dsp.iir — `sosfilt` sin el costo fijo de la versión pública de scipy.

`scipy.signal.sosfilt` valida, convierte y hace `moveaxis` en cada llamada:
medido sobre 960 muestras, 18 de sus 20 µs son ese costo fijo y 2 el filtrado
(el núcleo C, `_sosfilt`, tarda 4 µs con la conversión incluida). La cadena
llama 7 veces por frame, y en la Raspberry Pi eso pesaba más que el propio DSP.

`sosfilt_fast` llama directo al MISMO núcleo C que usa `sosfilt`, con los
mismos tipos, así que el resultado es idéntico bit a bit. `_sosfilt` es API
privada de scipy: si no está, cambió de firma o da distinto que la pública
(auto-chequeo al importar), se usa `sosfilt` y lo único que se pierde es la
velocidad, nunca la exactitud del audio.
"""
import numpy as np
from scipy.signal import sosfilt as _sosfilt_publico


def _sosfilt_rapido(sos: np.ndarray, x: np.ndarray, zi: np.ndarray):
    y = np.array(x, dtype=np.float64, ndmin=2, order="C")   # copia: se filtra en el lugar
    z = np.array(zi, dtype=np.float64, order="C").reshape(1, -1, 2)
    _nucleo(sos, y, z)
    return y[0], z[0]


def _sosfilt_lento(sos: np.ndarray, x: np.ndarray, zi: np.ndarray):
    y, z = _sosfilt_publico(sos, x, zi=zi)
    return np.asarray(y, dtype=np.float64), z


def _funciona() -> bool:
    """La vía rápida tiene que dar EXACTAMENTE lo mismo que la pública, con estado
    entre bloques y entrada float32 (los dos casos de la cadena)."""
    from scipy.signal import butter, sosfilt_zi
    sos = butter(2, [0.02, 0.2], btype="band", output="sos")
    rng = np.random.default_rng(1)
    zr = zl = sosfilt_zi(sos) * 0.3
    for _ in range(3):
        x = rng.standard_normal(97).astype(np.float32)
        yr, zr = _sosfilt_rapido(sos, x, zr)
        yl, zl = _sosfilt_lento(sos, x, zl)
        if not (np.array_equal(yr, yl) and np.array_equal(zr, zl)):
            return False
    return True


try:
    from scipy.signal._sosfilt import _sosfilt as _nucleo
    RAPIDO = _funciona()
except Exception:
    RAPIDO = False

# sosfilt_fast(sos, x, zi) -> (y float64, zi): igual a sosfilt(sos, x, zi=zi)
# bit a bit. `sos` tiene que ser float64 (lo es todo lo que sale de butter()).
sosfilt_fast = _sosfilt_rapido if RAPIDO else _sosfilt_lento
