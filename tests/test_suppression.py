import sys
sys.path.insert(0, "src")
import numpy as np
from config import AppConfig
from pipeline import ProcessingPipeline

cfg = AppConfig()
p = ProcessingPipeline(cfg)
p.load_model()

hop = cfg.audio.block_size
rng = np.random.default_rng(42)

# Llenar buffer del modelo con ruido
for _ in range(15):
    p._process(rng.standard_normal(hop).astype(np.float32) * 0.1)

# Medir RMS a distintos niveles de supresion
noise = rng.standard_normal(hop * 5).astype(np.float32) * 0.1
results = {}
for level in [0.0, 0.25, 0.5, 0.75, 1.0]:
    p.set_suppression(level)
    out = np.concatenate([p._process(noise[i*hop:(i+1)*hop]) for i in range(5)])
    results[level] = float(np.sqrt(np.mean(out**2)))

print("Nivel supresion -> RMS salida (menor = mas supresion de ruido):")
for lvl, rms in results.items():
    print(f"  {int(lvl*100):3d}%  RMS={rms:.5f}")

print()
# Verificar gradiente: a mayor supresion, menor RMS de ruido
vals = list(results.values())
gradiente_ok = all(vals[i] >= vals[i+1] for i in range(len(vals)-1))
print(f"Gradiente correcto (mas supresion = menos ruido): {gradiente_ok}")
