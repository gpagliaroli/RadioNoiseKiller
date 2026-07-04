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
