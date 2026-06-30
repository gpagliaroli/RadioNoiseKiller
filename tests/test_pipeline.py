import sys, time
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

print(f"\nErrores: {errors if errors else 'ninguno'}")
print("\nPipeline: OK")
