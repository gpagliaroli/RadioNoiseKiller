"""
test_noise_vad — VAD del squelch, cuarentena MCRA y fading comp del NoiseProfiler.

Cubre los comportamientos v1.3 que no verifican los otros tests:
  - VAD con confirmacion espectral: ruido fluctuante no dispara el gate,
    voz armonica si, el release del AGC no reabre.
  - Cuarentena MCRA look-behind: fades e impulsos no contaminan lambda_d.
  - Fading comp: clamps de los setters y recalculo de frames al cambiar hop.

IMPORTANTE: validar detectores con ruido FLUCTUANTE y voz CON ENVOLVENTE.
El ruido gaussiano estacionario y los tonos puros dan falsos OK (paso dos veces).
"""
import sys
sys.path.insert(0, "src")
import numpy as np
from dsp.noise_profiler import NoiseProfiler

HOP, SR = 480, 48000
rng = np.random.default_rng(7)

_fails = []


def check(name, cond):
    print(("  [OK]   " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def voice_sig(n_frames, level=1.0, f0=150.0):
    """Voz sintetica: armonicos de f0 con amplitud decayente, envolvente silabica 4 Hz."""
    t = np.arange(n_frames * HOP) / SR
    sig = np.zeros_like(t)
    k = 1
    while k * f0 < 2800:
        sig += (1.0 / k) * np.sin(2 * np.pi * k * f0 * t + rng.uniform(0, 6.28))
        k += 1
    env = 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * t)
    return (sig * env * level * 0.05).astype(np.float32).reshape(n_frames, HOP)


def fluct_noise(n_frames, base=0.01):
    """Ruido de banda fluctuante: envolvente aleatoria +-6 dB cada ~100 ms (QRN)."""
    x = rng.standard_normal(n_frames * HOP) * base
    env = np.repeat(10 ** (rng.uniform(-6, 6, size=n_frames // 10 + 1) / 20.0),
                    10 * HOP)[: n_frames * HOP]
    return (x * env).astype(np.float32).reshape(n_frames, HOP)


def make_profiler(fading=False):
    p = NoiseProfiler(HOP)
    p.set_mode("mcra")
    p.set_fading_comp(fading)
    return p


def gate_frac(vps, thr=0.30, hold_frames=50):
    """Replica la logica del gate del pipeline: fraccion de frames abiertos."""
    hold, opens = 0, 0
    for vp in vps:
        if vp >= thr:
            hold = hold_frames
            opens += 1
        elif hold > 0:
            hold -= 1
            opens += 1
    return opens / len(vps)


# ---------------------------------------------------------------------------
print("=== VAD del squelch (confirmacion espectral) ===")

nz = fluct_noise(1000)
vx = voice_sig(300)

# 1. Ruido fluctuante puro: vp debe quedar cerca de 0 (antes marcaba 100%)
p = make_profiler()
vps = []
for i in range(600):
    p.set_agc_gain(1.0)
    p.process(nz[i])
    if i >= 200:
        vps.append(p.voice_prob_sq)
check("ruido fluctuante +-6dB: vp medio < 0.15 (%.2f)" % np.mean(vps), np.mean(vps) < 0.15)
check("ruido fluctuante: gate cerrado > 95%% del tiempo", gate_frac(vps) < 0.05)

# 2. Voz armonica sobre ruido: gate abierto de forma continua
p2 = make_profiler()
for i in range(300):
    p2.set_agc_gain(1.0)
    p2.process(nz[600 + i])
vps_v = []
for i in range(300):
    p2.set_agc_gain(1.0)
    p2.process(vx[i] + nz[300 + i])
    vps_v.append(p2.voice_prob_sq)
check("voz clara: vp p90 > 0.9 (%.2f)" % np.percentile(vps_v, 90), np.percentile(vps_v, 90) > 0.9)
check("voz clara: gate abierto > 95%% (umbral 30%%, hold 500ms)", gate_frac(vps_v) > 0.95)

# 3. Release del AGC amplificando ruido: el vp no debe subir
p3 = make_profiler()
for i in range(300):
    p3.set_agc_gain(1.0)
    p3.process(nz[i])
for i in range(200):
    p3.set_agc_gain(1.0)
    p3.process(vx[i] + nz[300 + i])
vps_rel = []
for i in range(200):
    g = 16.0 ** ((i + 1) / 200.0)          # AGC subiendo +24 dB en 2 s
    p3.set_agc_gain(g)
    p3.process((nz[500 + i] * g).astype(np.float32))
    if i >= 50:
        vps_rel.append(p3.voice_prob_sq)
check("release AGC sobre ruido: vp medio < 0.15 (%.2f)" % np.mean(vps_rel), np.mean(vps_rel) < 0.15)

# 4. Voz plena sostenida: el vp no debe oscilar (bug del > estricto)
p4 = make_profiler()
for i in range(200):
    p4.set_agc_gain(1.0)
    p4.process(nz[i])
vp_seq = []
tone_v = voice_sig(60, level=2.0)
for i in range(60):
    p4.set_agc_gain(1.0)
    p4.process(tone_v[i] + nz[200 + i])
    vp_seq.append(p4.voice_prob_sq)
osc = sum(1 for i in range(20, 59) if abs(vp_seq[i] - vp_seq[i + 1]) > 0.35)
check("voz sostenida: sin oscilacion 1.0/0.6 frame a frame", osc < 5)

# ---------------------------------------------------------------------------
print("\n=== Cuarentena MCRA (look-behind) ===")

def ld_mean(p):
    return float(np.mean(p._mcra_ld))

steady = (rng.standard_normal(600 * HOP).reshape(600, HOP) * 0.01).astype(np.float32)

# 5. Fade brusco no contamina lambda_d con fading comp ON
p_on, p_off = make_profiler(True), make_profiler(False)
for i in range(300):
    p_on.process(steady[i]); p_off.process(steady[i])
ld_pre_on, ld_pre_off = ld_mean(p_on), ld_mean(p_off)
faded = (steady[300:315] * 0.2).astype(np.float32)       # caida de -14 dB
for i in range(15):
    p_on.process(faded[i]); p_off.process(faded[i])
drift_on  = abs(10 * np.log10(ld_mean(p_on)  / ld_pre_on))
drift_off = abs(10 * np.log10(ld_mean(p_off) / ld_pre_off))
check("fade -14dB, comp ON: drift lambda_d < 0.2 dB (%.3f)" % drift_on, drift_on < 0.2)
check("fade -14dB: comp ON protege mas que OFF (%.2f vs %.2f dB)" % (drift_on, drift_off),
      drift_on < drift_off)

# 6. Impulso aislado (+20 dB, 1 frame) no contamina
p5 = make_profiler(True)
for i in range(300):
    p5.process(steady[i])
ld_pre = ld_mean(p5)
p5.process((steady[100] * 10.0).astype(np.float32))
for i in range(10):
    p5.process(steady[i])
drift_imp = abs(10 * np.log10(ld_mean(p5) / ld_pre))
check("impulso +20dB aislado: drift lambda_d < 0.2 dB (%.3f)" % drift_imp, drift_imp < 0.2)

# 7. La adaptacion normal sigue: subida lenta de +6 dB debe seguirse
p6 = make_profiler(True)
for i in range(300):
    p6.process(steady[i])
ld_pre = ld_mean(p6)
for i in range(200):
    g = 2.0 ** ((i + 1) / 200.0)
    p6.process((rng.standard_normal(HOP) * 0.01 * g).astype(np.float32))
for i in range(200):
    p6.process((rng.standard_normal(HOP) * 0.02).astype(np.float32))
rise = 10 * np.log10(ld_mean(p6) / ld_pre)
check("subida lenta +6dB: lambda_d la sigue (+4 a +8 dB, %.1f)" % rise, 4.0 < rise < 8.0)

# ---------------------------------------------------------------------------
print("\n=== Fading comp: clamps y hop (invariantes 1 y 9) ===")

p7 = NoiseProfiler(480)
p7.set_fading_change_db(0.5);  check("clamp sensibilidad lo (2.0)",  p7._fading_change_db == 2.0)
p7.set_fading_change_db(99.0); check("clamp sensibilidad hi (10.0)", p7._fading_change_db == 10.0)
p7.set_fading_freeze_ms(50);   check("clamp freeze lo (100)",  p7._fading_freeze_ms == 100.0)
p7.set_fading_freeze_ms(9999); check("clamp freeze hi (500)",  p7._fading_freeze_ms == 500.0)
p7.set_fading_freeze_ms(200)
check("freeze 200ms @ hop 480 = 20 frames", p7._fading_freeze_frames == 20)
p7.reset(960)
check("reset(960) recalcula frames (10)", p7._fading_freeze_frames == 10)
check("reset limpia cuarentena", len(p7._mcra_quar) == 0)
p7.reset(240)
check("reset(240) recalcula frames (40)", p7._fading_freeze_frames == 40)

# 8. Sin eventos de fading, el checkbox NO debe alterar el procesamiento.
#    (Bug real: el release acelerado beta=0.45 aplicaba siempre con el checkbox
#    activo -> gorgojeo extra con mucho ruido y sin fading. Reportado en 40m.)
mild = rng.standard_normal(500 * HOP) * 0.01
env_mild = np.repeat(10 ** (rng.uniform(-1.5, 1.5, size=51) / 20.0), 10 * HOP)[: 500 * HOP]
mild = (mild * env_mild).astype(np.float32).reshape(500, HOP)   # +-3dB < umbral de 5dB
pa, pb = make_profiler(True), make_profiler(False)
out_a, out_b = [], []
fade_seen = False
for i in range(500):
    out_a.append(pa.process(mild[i]))
    out_b.append(pb.process(mild[i]))
    fade_seen = fade_seen or pa.fading_active
diff = float(np.max(np.abs(np.concatenate(out_a) - np.concatenate(out_b))))
check("ruido suave: ningun evento de fading disparado", not fade_seen)
check("sin eventos: comp ON == comp OFF, salida identica (dif %.1e)" % diff, diff == 0.0)

# ---------------------------------------------------------------------------
print()
if _fails:
    print("FALLARON %d checks:" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("Todos los tests pasaron.")
