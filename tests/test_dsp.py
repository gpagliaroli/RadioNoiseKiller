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
