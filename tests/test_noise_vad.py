"""
test_noise_vad — VAD del squelch y cuarentena MCRA del NoiseProfiler.

Cubre los comportamientos v1.3 que no verifican los otros tests:
  - VAD con confirmacion espectral: ruido fluctuante no dispara el gate,
    voz armonica si, el release del AGC no reabre.
  - Cuarentena MCRA look-behind: los impulsos no contaminan lambda_d.
  - Ventana MCRA: clamps de los setters y recalculo de M al cambiar hop.

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


def make_profiler():
    p = NoiseProfiler(HOP)
    p.set_mode("mcra")
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

# 6. Impulso aislado (+20 dB, 1 frame) no contamina
#
# El check es la MEDIA sobre varias semillas, no una sola corrida. Antes usaba el
# ruido fluctuante de una semilla fija contra un umbral de 0.2 dB, y eso era una
# loteria: medido sobre 12 semillas, la deriva va de 0.02 a 0.47 dB segun donde
# caiga el impulso respecto de la envolvente del ruido. El test pasaba por la
# semilla que le habia tocado, no porque el limite se cumpliera — 3 de esas 12
# semillas lo violaban ya antes de tocar nada.
#
# Con la media de 8 semillas el numero es estable (~0.18 dB) y el guard sigue
# sirviendo para lo que importa: detectar que el estimador empiece a comerse los
# impulsos de verdad (una regresion real llevaria esto a varios dB).
def drift_por_impulso(seed):
    r = np.random.default_rng(seed)
    x = r.standard_normal(400 * HOP) * 0.01
    env = np.repeat(10 ** (r.uniform(-6, 6, size=41) / 20.0), 10 * HOP)[:400 * HOP]
    st = (x * env).astype(np.float32).reshape(400, HOP)
    p = make_profiler()
    for i in range(300):
        p.process(st[i])
    ld_pre = ld_mean(p)
    p.process((st[100] * 10.0).astype(np.float32))
    for i in range(10):
        p.process(st[i])
    return abs(10 * np.log10(ld_mean(p) / ld_pre))


drift_imp = float(np.mean([drift_por_impulso(s) for s in range(8)]))
check("impulso +20dB aislado: drift medio de lambda_d < 0.35 dB (%.3f)" % drift_imp,
      drift_imp < 0.35)

# 7. La adaptacion normal sigue: subida lenta de +6 dB debe seguirse
p6 = make_profiler()
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
print("\n=== Ventana MCRA: clamps y hop (invariantes 1 y 9) ===")

p7 = NoiseProfiler(480)
p7.reset(960)
check("reset limpia cuarentena", len(p7._mcra_quar) == 0)
p7.reset(240)

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

# El umbral de habla por bin (δ) escala con la ventana: la tasa de falsos
# positivos con RUIDO PURO no debe depender de donde este el slider.
#
# Antes δ era la constante 1.67 y el ratio S_f/S_min del ruido puro crece con la
# ventana (1.40 a 250 ms, 1.65 a 800 ms), asi que la tasa iba de 20 % a 43 %: el
# control de "Reactividad del piso" tenia un segundo efecto no documentado sobre
# el detector de habla. El guard es la DISPERSION entre extremos, no el valor
# absoluto — si alguien vuelve a fijar δ, esto se rompe.
def _falsos_imin(window_ms):
    r = np.random.default_rng(11)
    p = NoiseProfiler(HOP); p.set_mode("mcra"); p.set_enabled(True)
    p.set_mcra_window_ms(window_ms)
    for _ in range(700):
        p.process(r.normal(0, 0.02, HOP).astype(np.float32))
    fp = []
    for _ in range(200):
        p.process(r.normal(0, 0.02, HOP).astype(np.float32))
        s_min = np.minimum(np.min(p._mcra_subs, axis=0), p._mcra_cur_min)
        s_min = np.where(s_min == np.inf, p._mcra_cur_min, s_min)
        fp.append(float(np.mean((p._mcra_Sf / (s_min + 1e-12)) > p._mcra_delta)))
    return float(np.mean(fp)) * 100


fp_corta, fp_larga = _falsos_imin(250), _falsos_imin(800)
check("falsos I_min con ruido puro no dependen del slider (%.1f%% vs %.1f%%)"
      % (fp_corta, fp_larga), abs(fp_corta - fp_larga) < 8.0)
check("falsos I_min en un rango sano (%.1f%%, %.1f%%)"
      % (fp_corta, fp_larga), max(fp_corta, fp_larga) < 30.0)
_pd = NoiseProfiler(HOP); _pd.set_mode("mcra")
_pd.set_mcra_window_ms(250); _d_corta = _pd._mcra_delta
_pd.set_mcra_window_ms(800); _d_larga = _pd._mcra_delta
check("delta crece con la ventana, no es constante (%.2f -> %.2f)"
      % (_d_corta, _d_larga), _d_larga > _d_corta + 0.2)

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
check("con voz el VAD no fuerza el suavizado automatico (vp=%.2f)" % vp_sm, vp_sm > 0.4)

# NOTA: aca habia dos checks que comparaban el efecto del slider CON voz contra
# SIN voz. Quedaron sin sentido a proposito: con voz confirmada por el VAD rapido
# los bins que suben ya no se suavizan (para no ablandar el ataque de silaba), asi
# que el slider pesa poco durante la voz. Su trabajo ahora es el release y el ruido
# de fondo, donde ademas el automatico (_PS_SMOOTH_QUIET) domina. Lo que si tiene
# que seguir siendo cierto es que el parpadeo de ganancia sin voz sea bajo en
# terminos absolutos, con el slider donde este.
nz_only = fluct_noise(400)
q_sm, vp_q = _red_jump_var(0.6, nz_only)
q_no, _ = _red_jump_var(0.0, nz_only)
check("sin voz el parpadeo de ganancia es bajo con el slider al maximo (%.4f)" % q_sm,
      q_sm < 0.15)
check("sin voz el parpadeo de ganancia es bajo con el slider al minimo (%.4f)" % q_no,
      q_no < 0.15)
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

# ---------------------------------------------------------------------------
print()
print("=== Post-filtro: profundidad fija en bins de ruido (anti-gorgojeo) ===")

# El post-filtro RESTA ~4.5 dB por unidad en los bins de ruido, en vez de
# exponenciar la ganancia (que multiplicaba la fluctuacion en dB del ruido ->
# gorgojeo, y castigaba los bins de voz con p_speech intermedio). Se aplica
# DESPUES de la Intensidad, para ser independiente de ella.

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

# 10b. La profundidad del post-filtro NO debe depender de la Intensidad.
#      La receta de operacion validada en el aire es "Intensidad baja + post alto":
#      si la profundidad extra entra ANTES de gain^alpha, alpha la achica (a 0.5 un
#      bin anclado a -30 dB sale a -15 dB) y hay que subir la Intensidad para domar
#      el soplido — justo lo que la receta evita. Reportado en el aire.
def _run_post_a(strength, frames, alpha):
    p = make_profiler()
    p.set_alpha(alpha); p.set_floor(0.1); p.set_smooth(0.96); p.set_attack(0.80)
    if strength:
        p.set_post_filter_enabled(True)
        p.set_post_filter_strength(strength)
    return [p.process(f) for f in frames]


extra_lo = (_residuo(_run_post_a(0.0, nz2, 0.5))[1]
            - _residuo(_run_post_a(6.0, nz2, 0.5))[1])
extra_hi = (_residuo(_run_post_a(0.0, nz2, 1.0))[1]
            - _residuo(_run_post_a(6.0, nz2, 1.0))[1])
check("la profundidad del post-filtro no depende de la Intensidad "
      "(%.1f dB a 0.5 vs %.1f dB a 1.0)" % (extra_lo, extra_hi),
      abs(extra_lo - extra_hi) < 4.0 and extra_lo > 8.0)

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
print("=== Freeze de MCRA por voz (periodicidad) ===")

# MCRA tomaba la voz SOSTENIDA por ruido: su ventana de minimos la absorbe, lambda_d
# sube hasta el nivel de la voz y el cancelador empieza a restar la voz misma.
# Ahora los frames con voz no alimentan el estimador. El gate es la PERIODICIDAD
# (autocorrelacion), no el vp: el vp se calcula sobre snr_post, que depende de
# lambda_d, asi que al congelar el ruido nuevo parece señal, sube el vp y realimenta
# el freeze (medido: con un salto de +10 dB el estimador quedaba congelado el 67%
# de los frames sin recuperarse en 3 s).


def _mk_mcra(win=500.0):
    p = make_profiler()
    p.set_alpha(0.55); p.set_floor(0.15); p.set_smooth(0.96); p.set_attack(0.80)
    p.set_mcra_window_ms(win)
    return p


# 13. Con voz sostenida, el estimador NO debe subir hasta el nivel de la voz.
nz_conv = fluct_noise(300)
vsus = voice_sig(200)
pv = _mk_mcra()
for f in nz_conv:
    pv.process(f)
ld_antes = float(np.mean(pv._mcra_ld))
for f in vsus:
    pv.process(f)
subida = 10 * np.log10(float(np.mean(pv._mcra_ld)) / ld_antes)
check("voz sostenida no contamina el estimador (subio %.1f dB)" % subida, subida < 3.0)
check("el freeze por voz se activo (hold=%d)" % pv._mcra_voice_hold,
      pv._mcra_voice_hold > 0)

# 14. Un salto de ruido SIN voz debe seguirse igual (guardia del lazo de
#     realimentacion: si el gate fuera por vp, el estimador quedaria congelado).
nz_lo = fluct_noise(300, base=0.01)
nz_hi = fluct_noise(200, base=0.01 * 10 ** 0.5)     # +10 dB
pn = _mk_mcra()
for f in nz_lo:
    pn.process(f)
ld0 = float(np.mean(pn._mcra_ld))
holds = 0
for f in nz_hi:
    pn.process(f)
    holds += 1 if pn._mcra_voice_hold > 0 else 0
seg = 10 * np.log10(float(np.mean(pn._mcra_ld)) / ld0)
check("salto de ruido sin voz: el estimador lo sigue (+%.1f dB de +10)" % seg, seg > 8.0)
check("salto de ruido sin voz: no dispara el freeze (%d frames)" % holds, holds == 0)

# 15. El hold depende del hop (invariante 9).
ph = _mk_mcra()
f480 = ph._mcra_voice_hold_frames
ph.reset(240)
check("el hold del freeze se recalcula con el hop (%d -> %d)"
      % (f480, ph._mcra_voice_hold_frames),
      ph._mcra_voice_hold_frames == 2 * f480)

# ---------------------------------------------------------------------------
print()
print("=== Ataque de silaba (la voz no debe sonar 'limitada') ===")

# El suavizado de p_speech ablandaba el arranque de cada silaba: salia ~5.8 dB mas
# atenuado que su meseta (a Intensidad 0.9), lo que se percibe como voz comprimida
# y con menos claridad — reportado en el aire. Con voz confirmada por el VAD
# rapido, los bins que SUBEN ya no se suavizan. Sin ese gate el ataque se arregla
# igual pero el residuo de ruido empeora 10 dB.
_N = 400
_t = np.arange(_N * HOP) / SR
_v = np.zeros_like(_t)
_k = 1
while _k * 150.0 < 2800:
    _v += (1.0 / _k) * np.sin(2 * np.pi * _k * 150.0 * _t)
    _k += 1
_env = np.zeros_like(_t)
_syl, _i = [], 0
while _i + 40 * HOP < len(_t):
    _r = int(0.005 * SR)
    _env[_i:_i + 25 * HOP] = 1.0
    _env[_i:_i + _r] = np.linspace(0, 1, _r)
    _env[_i + 25 * HOP - _r:_i + 25 * HOP] = np.linspace(1, 0, _r)
    _syl.append(_i // HOP)
    _i += 40 * HOP
_clean = (_v * _env * 0.05).astype(np.float32).reshape(_N, HOP)
_mix = (_clean + rng.standard_normal(_N * HOP).reshape(_N, HOP) * 0.0055).astype(np.float32)
_conv = (rng.standard_normal(300 * HOP) * 0.0055).astype(np.float32).reshape(300, HOP)


def _mag(frames):
    w = np.sqrt(np.hanning(2 * HOP)).astype(np.float32)
    out, prev = [], np.zeros(HOP, dtype=np.float32)
    for f in frames:
        fr = np.concatenate([prev, f]); prev = f
        out.append(np.abs(np.fft.rfft(fr * w)))
    return np.array(out)


_lo, _hi = int(300 / 50), int(3400 / 50)
_Sc = _mag(list(_clean))[:, _lo:_hi]
pa = make_profiler()
pa.set_alpha(0.9); pa.set_floor(0.15); pa.set_smooth(0.96); pa.set_attack(0.80)
pa.set_mcra_window_ms(500.0)
pa.set_post_filter_enabled(True); pa.set_post_filter_strength(3.0)
for f in _conv:
    pa.process(f)
_So = _mag([pa.process(f) for f in _mix])[:, _lo:_hi]
_So = np.vstack([_So[1:], _So[-1:]])
_rel = 20 * np.log10(np.maximum(_So.mean(1), 1e-9) / np.maximum(_Sc.mean(1), 1e-9))
_ons = float(np.mean([_rel[s + 1:s + 3].mean() for s in _syl[1:]]))
_pla = float(np.mean([_rel[s + 10:s + 22].mean() for s in _syl[1:]]))
check("el arranque de silaba sale a nivel de meseta (%.2f dB)" % (_ons - _pla),
      _ons - _pla > -2.0)

# Y el fondo EN LOS HUECOS entre palabras tiene que seguir suprimido: la ventana de
# ataque se dispara por FLANCO justamente por esto. Gatearla por NIVEL de vp_sq la
# dejaba abierta toda la transmision (el vp_sq no baja entre palabras) y el ruido de
# los huecos subia 3.6 dB con mas parpadeo — reportado en el aire como "mucho ruido
# de fondo y volvio el gorgojeo".
_gaps = [g for s in _syl[1:] for g in range(s + 27, s + 39) if g < _N]
_Sin = _mag(list(_mix))[:, _lo:_hi]
_sup = (10 * np.log10(float(np.mean(_So[_gaps] ** 2)))
        - 10 * np.log10(float(np.mean(_Sin[_gaps] ** 2))))
_flick = float(np.mean(np.std(20 * np.log10(np.maximum(_So[_gaps], 1e-8)), axis=0)))
check("el fondo entre palabras sigue suprimido (%.1f dB)" % _sup, _sup < -12.0)
check("el fondo entre palabras no parpadea de mas (%.1f dB)" % _flick, _flick < 12.0)

# ---------------------------------------------------------------------------
print()
if _fails:
    print("FALLARON %d checks:" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("Todos los tests pasaron.")
