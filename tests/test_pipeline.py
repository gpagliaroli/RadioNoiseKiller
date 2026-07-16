import sys
import time
sys.path.insert(0, "src")
import numpy as np
from config import AppConfig, RadioMode
from pipeline import ProcessingPipeline

cfg = AppConfig()
pipeline = ProcessingPipeline(cfg)

errors = []
pipeline.set_error_callback(lambda msg: errors.append(msg))

print("Simulando procesamiento de frames...")
rng = np.random.default_rng(42)
hop = cfg.audio.block_size

latencies = []
for i in range(500):
    noise = rng.standard_normal(hop).astype(np.float32) * 0.05
    t0 = time.perf_counter()
    out = pipeline._process(noise)
    dt = (time.perf_counter() - t0) * 1000
    latencies.append(dt)

budget = hop / cfg.audio.sample_rate * 1000
avg = sum(latencies) / len(latencies)
maxi = max(latencies)
p99  = sorted(latencies)[int(len(latencies) * 0.99)]
print(f"Budget por frame:    {budget:.1f} ms")
print(f"Latencia promedio:   {avg:.2f} ms")
print(f"Latencia p99:        {p99:.2f} ms")
print(f"Latencia maxima:     {maxi:.2f} ms")
print(f"Tiempo real OK:      {avg < budget}")

pipeline.set_mode(RadioMode.AM)
pipeline.set_bypass(True)
out_bypass = pipeline._process(np.ones(hop, dtype=np.float32) * 0.1)
assert np.allclose(out_bypass, np.ones(hop) * 0.1, atol=1e-5), "Bypass fallo"
print("\nBypass: OK")

# ------------------------------------------------------------------
# Supresor de impulsos (headless: necesita el hilo procesador corriendo)
# Ruido de base para establecer el piso de energia + un impulso fuerte:
# con blanker ON debe suprimirlo y contar hits; OFF es el control negativo.
# ------------------------------------------------------------------
print("\nSupresor de impulsos...")

def _run_impulse(blanker_on: bool) -> tuple[float, int]:
    c = AppConfig()
    c.dsp.blanker_enabled = blanker_on
    c.dsp.noise_enabled = False        # aislar el blanker del resto
    c.dsp.anf_enabled = False
    c.dsp.bandpass_pre_enabled = False
    c.dsp.bandpass_post_enabled = False
    c.dsp.presence_enabled = False
    c.dsp.exciter_enabled = False
    c.dsp.agc_preset = "off"
    p = ProcessingPipeline(c)
    p.start(headless=True)
    r = np.random.default_rng(7)
    h = c.audio.block_size
    for _ in range(100):                       # piso de energia estable
        p._process(r.standard_normal(h).astype(np.float32) * 0.01)
        time.sleep(0.002)
    p.pop_blanker_hits()                       # limpiar contador
    chunk = r.standard_normal(h).astype(np.float32) * 0.01
    chunk[200:240] += 1.0                      # impulso x100 sobre el piso
    p._process(chunk)
    peak = 0.0
    for _ in range(10):                        # drenar la salida diferida
        out_f = p._process(r.standard_normal(h).astype(np.float32) * 0.01)
        peak = max(peak, float(np.max(np.abs(out_f))))
        time.sleep(0.005)
    hits = p.pop_blanker_hits()
    p.stop()
    return peak, hits

peak_on, hits_on = _run_impulse(True)
peak_off, hits_off = _run_impulse(False)
print(f"  blanker ON : pico de salida {peak_on:.3f}, hits {hits_on}")
print(f"  blanker OFF: pico de salida {peak_off:.3f}, hits {hits_off}")
assert hits_on > 0, "blanker ON no conto hits con impulso presente"
assert peak_on < 0.2, f"blanker ON no suprimio el impulso (pico {peak_on:.3f})"
assert peak_off > 0.5, f"control negativo: sin blanker el impulso debe pasar (pico {peak_off:.3f})"
assert hits_off == 0, "blanker OFF no debe contar hits"
print("Supresor de impulsos: OK")

print(f"\nErrores: {errors if errors else 'ninguno'}")
print("\nPipeline: OK")
