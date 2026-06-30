import sys, time
sys.path.insert(0, "src")
import numpy as np
from config import ModelConfig
from models.deepfilternet import DeepFilterNet3

cfg = ModelConfig()
print("Cargando modelo...")
t0 = time.time()
model = DeepFilterNet3(cfg)
print(f"Modelo cargado en {time.time()-t0:.2f}s")

# Simulamos 20 frames de ruido (llenamos el buffer)
hop = cfg.hop_size
rng = np.random.default_rng(42)
print(f"\nProcesando {cfg.window_frames + DeepFilterNet3.LOOKAHEAD + 5} frames de ruido sintetico...")

total_time = 0.0
outputs = []
n_frames = cfg.window_frames + DeepFilterNet3.LOOKAHEAD + 5
for i in range(n_frames):
    noise = rng.standard_normal(hop).astype(np.float32) * 0.1
    t = time.time()
    out = model.process_frame(noise)
    elapsed = time.time() - t
    total_time += elapsed
    outputs.append(out)
    if i >= cfg.window_frames + DeepFilterNet3.LOOKAHEAD - 1:
        print(f"  Frame {i:2d}: salida shape={out.shape}, max={out.max():.4f}, tiempo={elapsed*1000:.1f}ms")

frame_budget_ms = hop / 48000 * 1000
avg_ms = total_time / n_frames * 1000
print(f"\nBudget por frame: {frame_budget_ms:.1f}ms")
print(f"Tiempo promedio de inferencia: {avg_ms:.1f}ms")
print(f"Factor tiempo real: {avg_ms/frame_budget_ms:.2f}x (< 1.0 = tiempo real OK)")
