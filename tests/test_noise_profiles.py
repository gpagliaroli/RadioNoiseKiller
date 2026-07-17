"""Perfiles de ruido nombrados: aprender → guardar → cargar → interpolar."""
import sys
import tempfile
import time

sys.path.insert(0, "src")
import numpy as np

from config import AppConfig
from dsp.noise_profiler import NoiseProfiler
from noise_profiles import NoiseProfileManager
from pipeline import ProcessingPipeline

tmp = tempfile.mkdtemp()
mgr = NoiseProfileManager(tmp)

# --- 1. aprender un perfil en el pipeline (modo estático) ---
cfg = AppConfig()
p = ProcessingPipeline(cfg)
p.start(headless=True)
rng = np.random.default_rng(5)
hop = cfg.audio.block_size
p.start_noise_learning()
for _ in range(60):
    p._process(rng.standard_normal(hop).astype(np.float32) * 0.05)
    time.sleep(0.004)
time.sleep(0.2)  # dejar que el hilo procesador consuma la cola
p.stop_noise_learning()
assert p.noise_has_profile, "no aprendio el perfil"

data = p.get_noise_profile_data()
assert data is not None and len(data["noise_mag"]) == hop + 1
print(f"perfil aprendido: {data['learned_frames']} frames, {len(data['noise_mag'])} bins")

# --- 2. guardar y listar ---
mgr.save("40m casa", data)
mgr.save("20m campo", data)
assert set(mgr.list_names()) == {"40m casa", "20m campo"}
print("guardados y listados:", mgr.list_names())

# --- 3. cargar en un pipeline nuevo, sin aprender ---
p.stop()
cfg2 = AppConfig()
p2 = ProcessingPipeline(cfg2)
loaded = mgr.load("40m casa")
p2.set_noise_profile_data(loaded)
assert p2.noise_has_profile, "el perfil cargado no quedo activo"
assert p2.noise_mode == "static", "cargar un perfil debe forzar modo estatico"
d2 = p2.get_noise_profile_data()
assert np.allclose(d2["noise_mag"], data["noise_mag"], rtol=1e-4), "perfil cargado != guardado"
print("cargado en pipeline nuevo: OK (identico)")

# --- 4. interpolacion: cargar un perfil de otro fft_n ---
prof = NoiseProfiler(hop_size=480)          # nb = 481
mag = np.linspace(0.1, 0.5, 481).astype(np.float32)
prof.set_profile({"noise_mag": mag.tolist(), "fft_n": 960, "learned_frames": 50})
prof2 = NoiseProfiler(hop_size=960)         # nb = 961, distinto
prof2.set_profile({"noise_mag": mag.tolist(), "fft_n": 960, "learned_frames": 50})
assert prof2._noise_mag is not None and len(prof2._noise_mag) == 961, "no interpolo al nb nuevo"
# extremos preservados (aprox) tras interpolar + escalar x2
assert prof2._noise_mag[0] > 0 and np.all(np.isfinite(prof2._noise_mag))
print(f"interpolacion 481->961 bins: OK (pico {prof2._noise_mag.max():.3f})")

# --- 5. rename / delete ---
mgr.rename("40m casa", "40m casa noche")
assert mgr.exists("40m casa noche") and not mgr.exists("40m casa")
mgr.delete("20m campo")
assert mgr.list_names() == ["40m casa noche"]
print("rename/delete: OK")

print("\ntest_noise_profiles: OK")
