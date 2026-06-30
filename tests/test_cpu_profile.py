"""
Benchmark de CPU por componente del pipeline.

Ejecutar con:
    .venv\\Scripts\\python.exe tests\\test_cpu_profile.py

Mide el tiempo promedio de cada módulo procesando 480 samples @ 48 kHz (10 ms/frame).
Calcula %CPU asumiendo 100 frames/segundo (tiempo real).
"""

import sys, time, numpy as np
sys.path.insert(0, "src")

from config import AppConfig
from dsp.filters        import BandpassFilter
from dsp.gain           import GainLimiter
from dsp.anf            import AdaptiveNotchFilter
from dsp.noise_profiler import NoiseProfiler
from dsp.agc            import AGC
from models.deepfilternet import DeepFilterNet3

N_FRAMES   = 500          # frames de warm-up + medición
N_MEASURE  = 400          # frames que se cuentan (los primeros 100 son warm-up)
HOP        = 480
SR         = 48000
rng        = np.random.default_rng(0)

def make_signal(n=HOP, amp=0.05):
    return (rng.standard_normal(n) * amp).astype(np.float32)

def bench(name, fn, n=N_FRAMES, warmup=100):
    times = []
    for i in range(n):
        sig = make_signal()
        t0 = time.perf_counter()
        fn(sig)
        t1 = time.perf_counter()
        if i >= warmup:
            times.append(t1 - t0)
    avg_ms  = np.mean(times) * 1000
    p99_ms  = np.percentile(times, 99) * 1000
    cpu_pct = avg_ms / 10.0 * 100        # budget = 10 ms/frame
    print(f"  {name:<42}  {avg_ms:6.3f} ms/frame  p99={p99_ms:6.3f} ms  CPU~{cpu_pct:5.1f}%")
    return avg_ms

cfg = AppConfig()
print(f"\n{'='*72}")
print(f"  Benchmark de CPU — {HOP} samples @ {SR} Hz  (presupuesto: 10.0 ms/frame)")
print(f"{'='*72}\n")

total = 0.0

# -----------------------------------------------------------------------
# Blanker (frame + mini)
# -----------------------------------------------------------------------
energy_hist = [1e-8]
def run_blanker(chunk):
    fe = float(np.dot(chunk, chunk)) / len(chunk)
    eh = energy_hist[0]
    eh = 0.95 * eh + 0.05 * fe if fe < eh else 0.999 * eh + 0.001 * fe
    energy_hist[0] = eh
    if fe > 15.0 * eh:
        gain = np.sqrt(15.0 * eh / fe)
        chunk = chunk * gain
    mini = chunk.reshape(-1, 32)
    mini_e = np.sum(mini ** 2, axis=1) / 32
    over = mini_e > 8.0 * eh
    if np.any(over):
        scales = np.where(over, np.sqrt(8.0 * eh / (mini_e + 1e-12)), 1.0)
        chunk = (mini * scales[:, np.newaxis].astype(np.float32)).ravel()
    return chunk

total += bench("Blanker (frame + mini-frame 32)", run_blanker)

# -----------------------------------------------------------------------
# AGC
# -----------------------------------------------------------------------
agc = AGC(SR, HOP)
total += bench("AGC", agc.process)

# -----------------------------------------------------------------------
# Bandpass (pre)
# -----------------------------------------------------------------------
bp = BandpassFilter(cfg.dsp, SR)
total += bench("BandpassFilter (IIR Butterworth)", bp.process)

# -----------------------------------------------------------------------
# ANF (con y sin tono)
# -----------------------------------------------------------------------
anf = AdaptiveNotchFilter(SR, threshold=3.0, depth=0.9)
anf.set_enabled(True)
total += bench("ANF (filtro de muesca espectral)", anf.process)

# ANF con tono real
t = np.arange(HOP, dtype=np.float32) / SR
tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
def run_anf_tone(sig):
    return anf.process(tone + sig)
print(f"    (variante con tono 1 kHz activo:)", end="  ")
bench("ANF con tono activo", run_anf_tone)

# -----------------------------------------------------------------------
# NoiseProfiler
# -----------------------------------------------------------------------
prof = NoiseProfiler(HOP)
prof.start_learning()
for _ in range(200):
    prof.process(make_signal())
prof.stop_learning()
total += bench("NoiseProfiler (Wiener FFT-based)", prof.process)

# -----------------------------------------------------------------------
# DeepFilterNet3 — ONNX (el más pesado)
# -----------------------------------------------------------------------
print()
print("  [Cargando modelo ONNX...]")
model = DeepFilterNet3(cfg.model)
model.set_window_frames(10)

frame_times = []
for i in range(N_FRAMES):
    sig = make_signal()
    t0 = time.perf_counter()
    model.process_frame(sig)
    t1 = time.perf_counter()
    if i >= 100:
        frame_times.append(t1 - t0)

model_avg = np.mean(frame_times) * 1000
model_p99 = np.percentile(frame_times, 99) * 1000
model_cpu = model_avg / 10.0 * 100
total += model_avg
print(f"  {'DeepFilterNet3 (ONNX enc+erb_dec+df_dec)':<42}  {model_avg:6.3f} ms/frame  p99={model_p99:6.3f} ms  CPU~{model_cpu:5.1f}%")

# -----------------------------------------------------------------------
# GainLimiter
# -----------------------------------------------------------------------
limiter = GainLimiter()
total += bench("GainLimiter (peak follower)", lambda s: limiter.process(s, SR))

print()
print(f"{'-'*72}")
total_cpu = total / 10.0 * 100
print(f"  {'TOTAL estimado (sin solapamientos)':<42}  {total:6.3f} ms/frame               CPU~{total_cpu:5.1f}%")
print()
print("  Nota: los módulos corren en un thread dedicado (no bloquean la UI).")
print("  El presupuesto real depende del hardware; en i7 moderno 20-30% es normal.")
print()
