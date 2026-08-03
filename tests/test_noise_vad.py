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

# 5. Fading VAD-smart: el freeze dispara solo con VOZ (desvanecimiento de señal),
#    NO ante un cambio de ruido de banda ancha (fix del vaivén con ruido ciclico).
# 5a. Cambio de RUIDO sin voz: comp ON no congela -> sigue el ruido como comp OFF.
p_on, p_off = make_profiler(True), make_profiler(False)
for i in range(300):
    p_on.process(steady[i]); p_off.process(steady[i])
ld_pre_on, ld_pre_off = ld_mean(p_on), ld_mean(p_off)
faded = (steady[300:315] * 0.2).astype(np.float32)       # -14 dB de ruido puro (sin voz)
froze = False
for i in range(15):
    p_on.process(faded[i]); p_off.process(faded[i])
    froze = froze or p_on.fading_active
check("cambio de ruido sin voz: comp ON NO congela (vp bajo)", not froze)
drift_on  = abs(10 * np.log10(ld_mean(p_on)  / ld_pre_on))
drift_off = abs(10 * np.log10(ld_mean(p_off) / ld_pre_off))
check("cambio de ruido sin voz: comp ON sigue el ruido como OFF (%.2f ~ %.2f dB)"
      % (drift_on, drift_off), abs(drift_on - drift_off) < 0.5)

# 5b. Desvanecimiento con VOZ presente: comp ON SI congela (protege el estimador).
p_v = make_profiler(True)
for i in range(250):
    p_v.set_agc_gain(1.0); p_v.process(nz[i])
for i in range(40):                                      # voz clara -> vp alto
    p_v.set_agc_gain(1.0); p_v.process(vx[i] + nz[300 + i])
vp_before = p_v.voice_prob_sq
froze_v = False
for i in range(15):                                      # fade -14 dB de voz+ruido
    fs = ((vx[40 + i] + nz[340 + i]) * 0.2).astype(np.float32)
    p_v.set_agc_gain(1.0); p_v.process(fs)
    froze_v = froze_v or p_v.fading_active
check("voz presente (vp=%.2f) + fade: comp ON SI congela" % vp_before, froze_v)

# Latch del indicador FADE: si el freeze termina entre dos polls de la UI (freeze
# ~200ms vs poll 500ms), pop_fading_active igual lo reporta una vez (y se resetea).
p_l = make_profiler(True)
p_l._fading_active = True; p_l._fading_latch = True    # hubo freeze...
p_l._fading_active = False                             # ...que ya termino
check("latch FADE: pop=True tras freeze aunque fading_active=False", p_l.pop_fading_active() is True)
check("latch FADE: segunda lectura se resetea a False", p_l.pop_fading_active() is False)

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
p7.set_fading_change_db(0.5);  check("clamp sensibilidad lo (1.0)",  p7._fading_change_db == 1.0)
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

# Reactividad del piso (ventana MCRA): clamp e invariante 9 (recalculo por hop).
# p7 esta en hop 240 -> hop_ms=5, B=4 -> M = window_ms / 20
p7.set_mcra_window_ms(100);  check("clamp ventana MCRA lo (250)", p7._mcra_window_ms == 250.0)
p7.set_mcra_window_ms(9999); check("clamp ventana MCRA hi (800)", p7._mcra_window_ms == 800.0)
check("ventana 800ms @ hop 240 -> M=40", p7._mcra_M == 40)
p7.set_mcra_window_ms(300);  check("ventana 300ms @ hop 240 -> M=15", p7._mcra_M == 15)
p7.reset(480)  # hop_ms=10 -> M = 300/(4*10)
check("reset(480) recalcula M de la ventana", p7._mcra_M == max(1, round(300 / (4 * 10))))

# Comportamiento: una ventana corta (reactiva) sigue una subida de ruido en
# MENOS frames que una larga (estable) — el nucleo del fix del vaivén.
def _frames_to_track(window_ms):
    p = NoiseProfiler(HOP); p.set_mode("mcra"); p.set_mcra_window_ms(window_ms)
    lo = (rng.standard_normal(120 * HOP).reshape(120, HOP) * 0.01).astype(np.float32)
    hi = (rng.standard_normal(200 * HOP).reshape(200, HOP) * 0.05).astype(np.float32)  # +14 dB
    for i in range(120):
        p.process(lo[i])
    base = float(np.mean(p._mcra_ld))
    for i in range(200):
        p.process(hi[i])
        if float(np.mean(p._mcra_ld)) >= base * 4.0:   # el piso empezo a seguir la subida
            return i
    return 999
f_react  = _frames_to_track(250)
f_stable = _frames_to_track(800)
check("ventana reactiva sigue la subida de ruido antes que la estable (%d < %d)"
      % (f_react, f_stable), f_react < f_stable)

# Refuerzo del piso en agudos (over-sustracción HF): clamp, forma de la curva
# e invariante 9 (redimensiona en reset). fft_n=960 @ hop480 -> freq_per_bin=50.
p8 = NoiseProfiler(480)
p8.set_hf_boost(9.0);  check("clamp hf_boost hi (1.5)", p8._hf_boost == 1.5)
p8.set_hf_boost(-1.0); check("clamp hf_boost lo (0.0)", p8._hf_boost == 0.0)
p8.set_hf_boost(1.0)
c8 = p8._hf_boost_curve
check("hf_boost: 1.0 debajo de 2.5kHz (bin 40 = 2000Hz)", abs(c8[40] - 1.0) < 1e-6)
# Rampa logaritmica: 1 octava (5kHz) = 1+boost; sigue creciendo por encima (no topa)
check("hf_boost: 1 octava @ 5kHz = 2.0 (bin 100)", abs(c8[100] - 2.0) < 1e-6)
check("hf_boost log: monotona creciente sobre el corte (3<4<5<6 kHz)",
      c8[60] < c8[80] < c8[100] < c8[120])
check("hf_boost log: sigue creciendo por encima de 5kHz (no topa como la lineal)",
      c8[120] > c8[100] + 0.1)
p8.reset(240)
check("hf_boost: curva redimensionada en reset (inv 9)", len(p8._hf_boost_curve) == p8._nb)

# Anti-gorgojeo: el suavizado temporal de p_speech reduce el salto de ganancia
# frame a frame (ruido musical). Se mide CON VOZ presente: sin voz el gate
# automatico (_PS_SMOOTH_QUIET + EMA de ganancia) domina y tapa la diferencia
# del slider — que es justamente lo que se quiere sin voz.
def _red_jump_var(smooth, frames):
    p = NoiseProfiler(HOP); p.set_mode("mcra"); p._ps_smooth = smooth
    for i in range(200):
        p.process(frames[i])
    reds = []
    for i in range(200, 400):
        p.process(frames[i]); reds.append(p.last_reduction_db)
    return float(np.var(np.diff(reds))), p.voice_prob


mixed_vn = (voice_sig(400) + fluct_noise(400) * 0.7).astype(np.float32)
v_sm, vp_sm = _red_jump_var(0.6, mixed_vn)
v_no, _ = _red_jump_var(0.0, mixed_vn)
check("con voz, el suavizado de p_speech reduce el salto de ganancia (%.4f < %.4f)"
      % (v_sm, v_no), v_sm < v_no)
check("con voz el VAD no fuerza el suavizado automatico (vp=%.2f)" % vp_sm, vp_sm > 0.4)

# Y sin voz el anti-gorgojeo automatico actua solo, con el slider donde este:
nz_only = fluct_noise(400)
q_sm, vp_q = _red_jump_var(0.6, nz_only)
q_no, _ = _red_jump_var(0.0, nz_only)
check("sin voz el salto de ganancia es chico con el slider al minimo (%.4f)" % q_no,
      q_no < max(v_no * 0.5, 1e-9))
check("sin voz el VAD queda bajo (vp=%.2f)" % vp_q, vp_q < 0.4)
# El slider Anti-gorgojeo (set_smooth) dosifica _ps_smooth: 0.90->0, 0.99->0.85
pc = NoiseProfiler(HOP)
pc.set_smooth(0.90); check("beta 0.90 -> ps_smooth 0", abs(pc._ps_smooth - 0.0) < 1e-6)
pc.set_smooth(0.99); check("beta 0.99 -> ps_smooth 0.85", abs(pc._ps_smooth - 0.85) < 1e-6)
pc.set_smooth(0.97); check("beta 0.97 -> ps_smooth ~0.66", abs(pc._ps_smooth - 0.66) < 0.02)
# reset limpia el estado por-bin (invariante 9: sin shape mismatch tras cambiar hop)
p9 = NoiseProfiler(480); p9.set_mode("mcra")
for i in range(30):
    p9.process((rng.standard_normal(480) * 0.02).astype(np.float32))
p9.reset(240)
check("reset limpia _p_speech_prev (sin shape mismatch)", p9._p_speech_prev is None)
p9.process((rng.standard_normal(240) * 0.02).astype(np.float32))  # no debe crashear

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
print("=== Post-filtro: ancla profunda (anti-gorgojeo) ===")

# El post-filtro hunde el piso de los bins de ruido en ~4.5 dB por unidad, en vez
# de exponenciar la ganancia (que multiplicaba la fluctuacion en dB del ruido ->
# gorgojeo, y castigaba los bins de voz con p_speech intermedio).

def _stft_pow(frames):
    w = np.sqrt(np.hanning(2 * HOP)).astype(np.float32)
    out, prev = [], np.zeros(HOP, dtype=np.float32)
    for f in frames:
        fr = np.concatenate([prev, f]); prev = f
        out.append(np.abs(np.fft.rfft(fr * w)) ** 2 + 1e-16)
    return np.array(out)


def _residuo(frames, skip=120):
    """(fluctuacion temporal en dB, nivel medio dB) en la banda de voz."""
    P = _stft_pow(frames)[skip:][:, int(300 / 50):int(3400 / 50)]
    return (float(np.mean(np.std(10 * np.log10(P), axis=0))),
            10 * np.log10(float(np.mean(P))))


def _run_post(strength, frames):
    p = make_profiler()
    p.set_alpha(0.55); p.set_floor(0.1); p.set_smooth(0.96); p.set_attack(0.80)
    if strength:
        p.set_post_filter_enabled(True)
        p.set_post_filter_strength(strength)
    return [p.process(f) for f in frames], p


nz2 = fluct_noise(600)
std_in, lvl_in = _residuo(list(nz2))
out0, p0 = _run_post(0.0, nz2)
out6, p6 = _run_post(6.0, nz2)
std0, lvl0 = _residuo(out0)
std6, lvl6 = _residuo(out6)

# 9. La supresion extra llega a la salida: el clamp posterior al suavizado en
#    frecuencia debe usar el ancla, no el piso normal (bug historico: clampear
#    con _eff_floor anula silenciosamente toda la supresion extra).
check("post 6 suprime mas que post 0 (%.1f dB extra)" % (lvl0 - lvl6), lvl6 < lvl0 - 6.0)

# 10. Y NO amplifica la fluctuacion del residuo (eso era el gorgojeo): el
#     residuo debe fluctuar como el ruido de entrada, no varias veces mas.
check("post 6 no dispara la fluctuacion (%.1f dB vs %.1f dB de entrada)"
      % (std6, std_in), std6 < std_in * 1.6)

# 11. Indicador "Reduccion extra": negativo con post activo, 0 sin el.
check("pf_extra_db reporta con post 6 (%.1f dB)" % p6.pf_extra_db, p6.pf_extra_db < -5.0)
check("pf_extra_db en 0 sin post-filtro", p0.pf_extra_db == 0.0)

# 12. El EMA de ganancia anti-gorgojeo se rearma tras reset (invariante 9).
p6.reset(240)
try:
    p6.process(np.zeros(240, dtype=np.float32))
    check("reset(hop) rearma el estado por-bin del anti-gorgojeo", True)
except Exception as e:
    check("reset(hop) rearma el estado por-bin del anti-gorgojeo: %s" % e, False)

# ---------------------------------------------------------------------------
print()
if _fails:
    print("FALLARON %d checks:" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("Todos los tests pasaron.")
