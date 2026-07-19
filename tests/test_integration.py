"""
test_integration — pipeline completo sin hardware, con TODOS los modulos activos.

A diferencia de test_pipeline (config default: casi todo apagado), este test
ejercita el camino real de _run_processor con: MCRA + squelch + fading comp +
post-filtro + piso perceptual + pitch enhance + exciter + EQ + AGC custom.
Incluye las dos maniobras historicamente fragiles: cambio de modo de ruido en
caliente y cambio de tamano de bloque con reinicio (shape mismatch, estados
pegados, "nunca termina de calibrar").

Usa pipeline.start(headless=True): hilo procesador real, sin AudioStream.
"""
import sys
import time
sys.path.insert(0, "src")
import numpy as np
from config import AppConfig, RadioMode
from pipeline import ProcessingPipeline

rng = np.random.default_rng(11)
SR = 48000

_fails = []


def check(name, cond):
    print(("  [OK]   " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def voice_frames(n_frames, hop, level=1.0, f0=150.0):
    t = np.arange(n_frames * hop) / SR
    sig = np.zeros_like(t)
    k = 1
    while k * f0 < 2800:
        sig += (1.0 / k) * np.sin(2 * np.pi * k * f0 * t + rng.uniform(0, 6.28))
        k += 1
    env = 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * t)
    return (sig * env * level * 0.05).astype(np.float32).reshape(n_frames, hop)


def noise_frames(n_frames, hop, base=0.01):
    x = rng.standard_normal(n_frames * hop) * base
    env = np.repeat(10 ** (rng.uniform(-4, 4, size=n_frames // 10 + 1) / 20.0),
                    10 * hop)[: n_frames * hop]
    return (x * env).astype(np.float32).reshape(n_frames, hop)


def feed(pipeline, frames, collect=False):
    """Alimenta frames via _process con cadencia suave; retorna RMS de salida."""
    outs = []
    for f in frames:
        out = pipeline._process(f)
        if collect:
            outs.append(out)
        time.sleep(0.0008)   # deja drenar al hilo procesador
    time.sleep(0.05)
    if collect:
        cat = np.concatenate(outs) if outs else np.zeros(1)
        return float(np.sqrt(np.mean(cat ** 2)))
    return 0.0


# --- Configuracion con todo activado ---
cfg = AppConfig()
d = cfg.dsp
d.mode                      = RadioMode.SSB
d.noise_enabled             = True
d.noise_mode                = "mcra"
d.squelch_enabled           = True
d.squelch_threshold         = 0.30
d.squelch_hold_ms           = 300.0
d.noise_fading_comp         = True
d.post_filter_enabled       = True
d.perceptual_floor_enabled  = True
d.pitch_enhance_enabled     = True
d.exciter_enabled           = True
d.presence_db               = 4.0
d.body_db                   = 3.0
d.agc_preset                = "medium"

pipeline = ProcessingPipeline(cfg)
errors = []
pipeline.set_error_callback(lambda msg: errors.append(msg))

hop = cfg.audio.block_size

print("=== Fase 1: ruido de banda (warmup MCRA + squelch cerrado) ===")
pipeline.start(headless=True)
rms_noise = feed(pipeline, noise_frames(400, hop), collect=True)
check("MCRA completo el warmup (has_profile)", pipeline.noise_has_profile)
check("gate cerrado con solo ruido", not pipeline.squelch_gate_open)
check("vp bajo con solo ruido (%.2f)" % pipeline.noise_voice_prob_sq,
      pipeline.noise_voice_prob_sq < 0.30)

print("\n=== Fase 2: voz (gate abre, audio pasa) ===")
vps = []
vx = voice_frames(300, hop)
for i in range(0, 300, 50):
    feed(pipeline, vx[i:i + 50])
    vps.append(pipeline.noise_voice_prob_sq)
check("vp sube con voz (max %.2f)" % max(vps), max(vps) > 0.5)
check("gate abierto con voz", pipeline.squelch_gate_open)
check("indicador S/N alto con voz (%.1f dB)" % pipeline.snr_db, pipeline.snr_db > 6.0)

print("\n=== Fase 3: vuelve el ruido (gate cierra tras la retencion) ===")
feed(pipeline, noise_frames(150, hop))
check("gate cerrado de nuevo tras el hold", not pipeline.squelch_gate_open)
check("indicador S/N cae con solo ruido (%.1f dB)" % pipeline.snr_db, pipeline.snr_db < 6.0)

print("\n=== Fase 3b: nivelador de voz (adapta con voz, congela con ruido) ===")
pipeline.set_agc_preset("off")             # sin AGC de entrada: la voz debil llega debil
pipeline.set_voice_leveler_enabled(True)
vx_w = voice_frames(250, hop, level=0.3)
feed(pipeline, vx_w)
g_voice = pipeline.voice_leveler_gain_db
check("nivelador sube ganancia con voz debil (%.1f dB)" % g_voice, g_voice > 2.0)
feed(pipeline, noise_frames(150, hop))
g_noise = pipeline.voice_leveler_gain_db
check("con solo ruido la ganancia queda congelada (%.1f vs %.1f dB)" % (g_noise, g_voice),
      abs(g_noise - g_voice) < 0.5)
pipeline.set_voice_leveler_enabled(False)
pipeline.set_agc_preset("slow")

print("\n=== Fase 4: cambios en caliente ===")
pipeline.set_noise_mode("static")
feed(pipeline, noise_frames(50, hop))
pipeline.set_noise_mode("mcra")
feed(pipeline, noise_frames(250, hop))
check("vuelta a MCRA en caliente recalibra (has_profile)", pipeline.noise_has_profile)
pipeline.apply_config(cfg)              # carga de preset completa en caliente
feed(pipeline, noise_frames(100, hop))
check("apply_config en caliente sin errores", len(errors) == 0)

print("\n=== Fase 4b: aprendizaje estatico (AGC congelado + monitoreo atenuado) ===")
pipeline.set_noise_mode("static")
pipeline.clear_noise_profile()
rms_pre = feed(pipeline, noise_frames(60, hop), collect=True)
g_before = pipeline.agc_gain_db
pipeline.start_noise_learning()
rms_learn = feed(pipeline, noise_frames(200, hop), collect=True)
g_after = pipeline.agc_gain_db
frames_learned = pipeline.stop_noise_learning()
check("el aprendizaje capturo frames (%d)" % frames_learned, frames_learned > 100)
check("AGC congelado durante el aprendizaje (delta %.1f dB)" % abs(g_after - g_before),
      abs(g_after - g_before) < 1.0)
check("monitoreo atenuado durante el aprendizaje (rms %.4f vs %.4f)" % (rms_learn, rms_pre),
      rms_learn < rms_pre * 0.6)
pipeline.set_noise_mode("mcra")
feed(pipeline, noise_frames(250, hop))

print("\n=== Fase 5: cambio de tamano de bloque (reinicio) ===")
pipeline.stop()
cfg.audio.block_size = 960
pipeline.start(headless=True)
hop2 = 960
feed(pipeline, noise_frames(300, hop2))
check("hop 960: MCRA completa el warmup (no 'nunca termina de calibrar')",
      pipeline.noise_has_profile)
vps2 = []
vx2 = voice_frames(200, hop2)
for i in range(0, 200, 40):
    feed(pipeline, vx2[i:i + 40])
    vps2.append(pipeline.noise_voice_prob_sq)
check("hop 960: la voz abre el gate (max vp %.2f)" % max(vps2), max(vps2) > 0.5)
pipeline.stop()
cfg.audio.block_size = 480
pipeline.start(headless=True)
feed(pipeline, noise_frames(250, 480))
check("vuelta a hop 480 sin errores", pipeline.noise_has_profile)
pipeline.stop()

print("\n=== Resultado ===")
check("cero errores del hilo procesador en todo el recorrido", len(errors) == 0)
if errors:
    for e in errors[:5]:
        print("    error: " + str(e))

print()
if _fails:
    print("FALLARON %d checks:" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("Todos los tests pasaron.")
