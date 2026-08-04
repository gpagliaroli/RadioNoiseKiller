import sys
sys.path.insert(0, "src")
import numpy as np
from config import DSPConfig, RadioMode
from dsp.filters import BandpassFilter
from dsp.gain import GainLimiter
from dsp.level import LevelMeter

SR = 48000
cfg = DSPConfig()

# --- Bandpass ---
bp = BandpassFilter(cfg, SR)
t = np.linspace(0, 1, SR, dtype=np.float32)

# Señal de 1000 Hz (dentro de banda) + 100 Hz (fuera de banda) + 10000 Hz (fuera de banda)
sig_in  = np.sin(2 * np.pi * 100  * t) * 0.5   # debería atenuarse
sig_in += np.sin(2 * np.pi * 1000 * t) * 0.5   # debería pasar
sig_in += np.sin(2 * np.pi * 10000 * t) * 0.5  # debería atenuarse

sig_out = bp.process(sig_in)

# Calcular energía en cada componente
def component_energy(sig, freq, sr):
    t2 = np.linspace(0, len(sig)/sr, len(sig))
    ref = np.sin(2*np.pi*freq*t2)
    return abs(np.dot(sig, ref)) / len(sig)

e_100  = component_energy(sig_out, 100,  SR)
e_1k   = component_energy(sig_out, 1000, SR)
e_10k  = component_energy(sig_out, 10000, SR)

print("=== BandpassFilter (SSB: 200-3000 Hz) ===")
print(f"  100 Hz  energia: {e_100:.4f}  (esperado: bajo)")
print(f"  1000 Hz energia: {e_1k:.4f}  (esperado: alto)")
print(f"  10kHz   energia: {e_10k:.4f}  (esperado: bajo)")
print(f"  OK: {e_1k > e_100 * 3 and e_1k > e_10k * 3}")

# --- Gain Limiter ---
gl = GainLimiter(gain_db=6.0, limit_db=-3.0)
loud = np.ones(480, dtype=np.float32) * 2.0  # señal que excede el límite
out = gl.process(loud, SR)
print(f"\n=== GainLimiter ===")
print(f"  Max entrada: {loud.max():.2f} | Max salida: {out.max():.4f} (limite ~{10**(-3/20):.4f})")
assert out.max() <= 10 ** (-3 / 20) * 1.01, "la salida supera el limite"

# --- Gain Limiter: rodilla suave (curva de transferencia) ---
print(f"\n=== GainLimiter — rodilla suave ===")

def peak_out_db(level_db, limit_db=-1.0, n=SR // 2):
    g = GainLimiter(gain_db=0.0, limit_db=limit_db)
    x = (10 ** (level_db / 20.0)) * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)
    y = g.process(x.astype(np.float32), SR)
    return 20 * np.log10(np.max(np.abs(y[n // 2:])) + 1e-12)

levels = [-12.0, -5.0, -2.0, 0.0, 5.0, 10.0]
outs = [peak_out_db(l) for l in levels]
for l, o in zip(levels, outs):
    print(f"  in {l:+6.1f} dB -> out {o:+6.2f} dB")
assert abs(outs[0] - (-12.0)) < 0.05, "passthrough por debajo de la rodilla"
assert abs(outs[1] - (-5.0)) < 0.15, "inicio de rodilla intacto (limite-4dB)"
assert -2.6 < outs[2] < -2.0, "compresion gradual en la rodilla"
assert abs(outs[-1] - (-1.0)) < 0.1, "techo exacto en el limite"
assert all(o <= -1.0 + 0.05 for o in outs), "nada supera el limite"
assert all(outs[i] < outs[i + 1] + 0.01 for i in range(len(outs) - 1)), "transferencia monotona"
print("  Curva de transferencia: OK")

# --- Gain Limiter: procesado por chunks == señal entera (carry del envelope) ---
sig = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(SR // 4) / SR)
sig[1000:1050] = 1.8   # pico aislado que dispara el limitador
gl_a, gl_b = GainLimiter(0.0, -1.0), GainLimiter(0.0, -1.0)
ya = gl_a.process(sig.astype(np.float32), SR)
yb = np.concatenate([gl_b.process(sig[i:i + 480].astype(np.float32), SR)
                     for i in range(0, len(sig) // 480 * 480, 480)])
err = float(np.max(np.abs(ya[:len(yb)] - yb)))
print(f"  Chunks vs entero: err max {err:.1e}")
assert err < 1e-6, "el carry del envelope entre chunks diverge"
print("  Carry entre chunks: OK")

# --- Level Meter ---
lm = LevelMeter()
silence = np.zeros(480, dtype=np.float32)
signal  = np.ones(480, dtype=np.float32) * 0.5
print(f"\n=== LevelMeter ===")
print(f"  Silencio: {lm.process(silence):.1f} dBFS")
print(f"  0.5 RMS:  {lm.process(signal):.1f} dBFS  (esperado ~-6 dBFS)")

# --- Excitador armónico -----------------------------------------------------
# El excitador debe AGREGAR ARMONICOS, no ecualizar: la version v1.9.1 aplicaba
# tanh(d*h) - h, que para señal chica vale (d-1)*h -> un realce de agudos lineal
# de +1.8 dB con los armonicos 58 dB abajo (inaudibles). Ver dsp/exciter.py.
from dsp.exciter import AuralExciter   # noqa: E402

print("\n=== AuralExciter ===")
_N = SR
_t = np.arange(_N) / SR


def _ex_run(x, drive=2.0, mix=0.3, gate=1.0):
    ex = AuralExciter(SR)
    ex.set_drive(drive); ex.set_mix(mix); ex.set_enabled(True)
    out = []
    for i in range(0, len(x), 480):
        ex.set_voice_gate(gate)
        out.append(ex.process(x[i:i + 480].astype(np.float32)))
    return np.concatenate(out)


def _spec_db(y):
    Y = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / (len(y) / 4)
    return 20 * np.log10(np.maximum(Y, 1e-12))


def _bin(f):
    return int(round(f * _N / SR))


# 1. Sin fuga lineal: no toca el nivel de la banda, a ningun nivel de entrada
leaks = []
for _db in (-40, -20, -6):
    _x = (10 ** (_db / 20) * np.sin(2 * np.pi * 2000 * _t)).astype(np.float32)
    leaks.append(_spec_db(_ex_run(_x))[_bin(2000)] - _spec_db(_x)[_bin(2000)])
print(f"  Fuga lineal @2kHz: {', '.join(f'{v:+.2f} dB' for v in leaks)}")
assert all(abs(v) < 0.3 for v in leaks), "el excitador ecualiza en vez de agregar armonicos"

# 2. Genera armonicos de verdad y el drive los controla
_x = (0.1 * np.sin(2 * np.pi * 1500 * _t)).astype(np.float32)
h3 = {d: _spec_db(_ex_run(_x, d))[_bin(4500)] - _spec_db(_ex_run(_x, d))[_bin(1500)]
      for d in (2.0, 5.0)}
print(f"  H3 rel. fundamental: drive 2 {h3[2.0]:.1f} dB, drive 5 {h3[5.0]:.1f} dB")
assert h3[2.0] < -20.0, "demasiada distorsion a drive bajo"
assert h3[5.0] > h3[2.0] + 3.0, "el drive no aumenta los armonicos"

# 3. Independiente del nivel de entrada (normalizacion de la no linealidad)
h3_lvl = []
for _db in (-40, -25, -10):
    _x = (10 ** (_db / 20) * np.sin(2 * np.pi * 1500 * _t)).astype(np.float32)
    _S = _spec_db(_ex_run(_x, 5.0))
    h3_lvl.append(_S[_bin(4500)] - _S[_bin(1500)])
print(f"  H3 vs nivel: {', '.join(f'{v:.1f}' for v in h3_lvl)} dB")
assert max(h3_lvl) - min(h3_lvl) < 2.0, "el efecto depende del nivel de entrada"

# 4. Gate por VAD: sin voz no levanta el ruido de fondo
_rng = np.random.default_rng(5)
_nz = (_rng.standard_normal(_N) * 10 ** (-35 / 20)).astype(np.float32)
_hi = slice(_bin(1500), _bin(6000))
lift = float(np.mean(_spec_db(_ex_run(_nz, gate=0.0))[_hi] - _spec_db(_nz)[_hi]))
print(f"  Ruido de fondo con gate cerrado: {lift:+.2f} dB")
assert abs(lift) < 0.2, "el excitador levanta el ruido residual sin voz"

# 5. Abrir/cerrar el gate no produce clicks
_x = (0.1 * np.sin(2 * np.pi * 1500 * _t[:4800])).astype(np.float32)
_ex = AuralExciter(SR); _ex.set_drive(5.0); _ex.set_mix(0.5); _ex.set_enabled(True)
_o = []
for _i in range(0, len(_x), 480):
    _ex.set_voice_gate(0.0 if (_i // 480) % 4 < 2 else 1.0)
    _o.append(_ex.process(_x[_i:_i + 480]))
_step = float(np.max(np.abs(np.diff(np.concatenate(_o)))))
print(f"  Salto maximo al conmutar el gate: {_step:.5f}")
assert _step < float(np.max(np.abs(np.diff(_x)))) * 1.5, "click al abrir/cerrar el gate"
print("  Excitador: OK")

# --- Caracter par/impar del excitador ---------------------------------------
print("\n=== Excitador: caracter par/impar ===")
_x15 = (0.1 * np.sin(2 * np.pi * 1500 * _t)).astype(np.float32)


def _ex_char(x, char, drive=5.0, mix=1.0):
    ex = AuralExciter(SR)
    ex.set_drive(drive); ex.set_mix(mix); ex.set_enabled(True); ex.set_character(char)
    out = []
    for i in range(0, len(x), 480):
        ex.set_voice_gate(1.0)
        out.append(ex.process(x[i:i + 480].astype(np.float32)))
    return np.concatenate(out)


_S_odd = _spec_db(_ex_char(_x15, 0.0))
_S_even = _spec_db(_ex_char(_x15, 1.0))
_h2_odd = _S_odd[_bin(3000)] - _S_odd[_bin(1500)]
_h2_even = _S_even[_bin(3000)] - _S_even[_bin(1500)]
_h3_even = _S_even[_bin(4500)] - _S_even[_bin(1500)]
print(f"  H2: impar {_h2_odd:.1f} dB -> par {_h2_even:.1f} dB   (H3 en par: {_h3_even:.1f} dB)")
assert _h2_odd < -60.0, "tanh pura no deberia generar armonicos pares"
assert _h2_even > -35.0, "el caracter par no genera 2do armonico"
assert _h3_even < -60.0, "el caracter par no deberia dejar armonicos impares"

# El caracter es un crossfade de TIMBRE: no debe cambiar el nivel de salida
_vv = np.zeros(SR, dtype=np.float64)
for _k in range(1, 20):
    if _k * 150 < 3400:
        _vv += (1.0 / _k) * np.sin(2 * np.pi * _k * 150 * _t)
_vv = (_vv * 0.05).astype(np.float32)
_levels = [20 * np.log10(np.sqrt(np.mean(_ex_char(_vv, c) ** 2))
                         / np.sqrt(np.mean(_vv ** 2))) for c in (0.0, 0.5, 1.0)]
print(f"  Nivel vs caracter: {', '.join(f'{v:+.2f}' for v in _levels)} dB")
assert max(_levels) - min(_levels) < 1.0, "el caracter cambia el nivel (deberia ser timbre)"
print("  Caracter par/impar: OK")

# --- Recuperacion de graves (sintesis del fundamental) ----------------------
# Un pasa-altos de 300 Hz (filtro tipico de SSB) deja el fundamental de una voz de
# 120 Hz unos 32 dB abajo: no hay energia que una EQ pueda levantar, hay que
# sintetizarla. Ver dsp/bass.py.
from dsp.bass import BassSynth            # noqa: E402
from scipy.signal import sosfilt as _sosfilt, butter as _butter   # noqa: E402

print("\n=== BassSynth ===")
_F0 = 120.0
_vb = np.zeros(SR, dtype=np.float64)
for _k in range(1, 25):
    if _k * _F0 < 3400:
        _vb += (1.0 / _k) * np.sin(2 * np.pi * _k * _F0 * _t + 0.7 * _k)
_vb = (_vb * 0.05).astype(np.float32)
_hp = _butter(4, 300 / (SR / 2), btype='high', output='sos')
_vbf = _sosfilt(_hp, _vb).astype(np.float32)


def _bass_run(frames_src, amount, f0=_F0, conf=0.8):
    bs = BassSynth(SR)
    bs.set_enabled(True); bs.set_amount(amount)
    out = []
    for i in range(0, len(frames_src), 480):
        bs.set_voice(f0, conf)
        out.append(bs.process(frames_src[i:i + 480]))
    return np.concatenate(out)


_nat = _spec_db(_vb)[_bin(_F0)]
_filt = _spec_db(_vbf)[_bin(_F0)]
_rest = _spec_db(_bass_run(_vbf, 1.0))[_bin(_F0)]
print(f"  @120 Hz: natural {_nat:.1f} dB, filtrada {_filt:.1f} dB, restaurada {_rest:.1f} dB")
assert _filt < _nat - 20.0, "el filtro de prueba deberia matar el fundamental"
assert _rest > _filt + 20.0, "no restaura el fundamental"
assert abs(_rest - _nat) < 4.0, "el 100% deberia dejarlo cerca del nivel natural"

# No debe sonar cuando no corresponde (un f0 mal detectado se escucha como retumbe)
for _lab, _f0, _cf in (("confianza baja", _F0, 0.2), ("sin f0", None, 0.9),
                       ("f0 fuera de rango", 400.0, 0.9)):
    _d = float(np.max(np.abs(_bass_run(_vbf, 1.0, _f0, _cf) - _vbf)))
    assert _d == 0.0, f"BassSynth suena con {_lab}"
print("  Silencio con f0 dudoso o fuera de rango: OK")

# Fase continua entre bloques (sin clicks)
_yb = _bass_run(_vbf, 1.0)
_edges = max(abs(_yb[i * 480] - _yb[i * 480 - 1]) for i in range(1, len(_yb) // 480))
assert _edges <= float(np.max(np.abs(np.diff(_vbf)))) * 1.5, "click en el borde de bloque"
print(f"  Continuidad de fase entre bloques: OK (salto {_edges:.5f})")
