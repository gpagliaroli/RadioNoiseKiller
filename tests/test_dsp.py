import sys
sys.path.insert(0, "src")
import numpy as np
from config import DSPConfig
from dsp.filters import BandpassFilter
from dsp.gain import GainLimiter
from dsp.level import LevelMeter

SR = 48000
cfg = DSPConfig()

# --- Bandpass ---
bp = BandpassFilter(cfg, SR)
t = np.linspace(0, 1, SR, dtype=np.float32)

# Señal de 1000 Hz (dentro de banda) + 100 Hz (fuera de banda) + 10000 Hz (fuera de banda)
sig_in  = np.sin(2 * np.pi * 100  * t) * 0.5   # debería atenuarse
sig_in += np.sin(2 * np.pi * 1000 * t) * 0.5   # debería pasar
sig_in += np.sin(2 * np.pi * 10000 * t) * 0.5  # debería atenuarse

sig_out = bp.process(sig_in)

# Calcular energía en cada componente
def component_energy(sig, freq, sr):
    t2 = np.linspace(0, len(sig)/sr, len(sig))
    ref = np.sin(2*np.pi*freq*t2)
    return abs(np.dot(sig, ref)) / len(sig)

e_100  = component_energy(sig_out, 100,  SR)
e_1k   = component_energy(sig_out, 1000, SR)
e_10k  = component_energy(sig_out, 10000, SR)

print("=== BandpassFilter (SSB: 200-3000 Hz) ===")
print(f"  100 Hz  energia: {e_100:.4f}  (esperado: bajo)")
print(f"  1000 Hz energia: {e_1k:.4f}  (esperado: alto)")
print(f"  10kHz   energia: {e_10k:.4f}  (esperado: bajo)")
print(f"  OK: {e_1k > e_100 * 3 and e_1k > e_10k * 3}")

# --- Gain Limiter ---
gl = GainLimiter(gain_db=6.0, limit_db=-3.0)
loud = np.ones(480, dtype=np.float32) * 2.0  # señal que excede el límite
out = gl.process(loud, SR)
print("\n=== GainLimiter ===")
print(f"  Max entrada: {loud.max():.2f} | Max salida: {out.max():.4f} (limite ~{10**(-3/20):.4f})")
assert out.max() <= 10 ** (-3 / 20) * 1.01, "la salida supera el limite"

# --- Gain Limiter: rodilla suave (curva de transferencia) ---
print("\n=== GainLimiter — rodilla suave ===")

def peak_out_db(level_db, limit_db=-1.0, n=SR // 2):
    g = GainLimiter(gain_db=0.0, limit_db=limit_db)
    x = (10 ** (level_db / 20.0)) * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)
    y = g.process(x.astype(np.float32), SR)
    return 20 * np.log10(np.max(np.abs(y[n // 2:])) + 1e-12)

levels = [-12.0, -5.0, -2.0, 0.0, 5.0, 10.0]
outs = [peak_out_db(l) for l in levels]
for l, o in zip(levels, outs):
    print(f"  in {l:+6.1f} dB -> out {o:+6.2f} dB")
assert abs(outs[0] - (-12.0)) < 0.05, "passthrough por debajo de la rodilla"
assert abs(outs[1] - (-5.0)) < 0.15, "inicio de rodilla intacto (limite-4dB)"
assert -2.6 < outs[2] < -2.0, "compresion gradual en la rodilla"
assert abs(outs[-1] - (-1.0)) < 0.1, "techo exacto en el limite"
assert all(o <= -1.0 + 0.05 for o in outs), "nada supera el limite"
assert all(outs[i] < outs[i + 1] + 0.01 for i in range(len(outs) - 1)), "transferencia monotona"
print("  Curva de transferencia: OK")

# --- Gain Limiter: procesado por chunks == señal entera (carry del envelope) ---
sig = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(SR // 4) / SR)
sig[1000:1050] = 1.8   # pico aislado que dispara el limitador
gl_a, gl_b = GainLimiter(0.0, -1.0), GainLimiter(0.0, -1.0)
ya = gl_a.process(sig.astype(np.float32), SR)
yb = np.concatenate([gl_b.process(sig[i:i + 480].astype(np.float32), SR)
                     for i in range(0, len(sig) // 480 * 480, 480)])
err = float(np.max(np.abs(ya[:len(yb)] - yb)))
print(f"  Chunks vs entero: err max {err:.1e}")
assert err < 1e-6, "el carry del envelope entre chunks diverge"
print("  Carry entre chunks: OK")

# --- Level Meter ---
lm = LevelMeter()
silence = np.zeros(480, dtype=np.float32)
signal  = np.ones(480, dtype=np.float32) * 0.5
print("\n=== LevelMeter ===")
print(f"  Silencio: {lm.process(silence):.1f} dBFS")
print(f"  0.5 RMS:  {lm.process(signal):.1f} dBFS  (esperado ~-6 dBFS)")

# --- Excitador armónico -----------------------------------------------------
# El excitador debe AGREGAR ARMONICOS, no ecualizar: la version v1.9.1 aplicaba
# tanh(d*h) - h, que para señal chica vale (d-1)*h -> un realce de agudos lineal
# de +1.8 dB con los armonicos 58 dB abajo (inaudibles). Ver dsp/exciter.py.
from dsp.exciter import AuralExciter   # noqa: E402

print("\n=== AuralExciter ===")
_N = SR
_t = np.arange(_N) / SR


def _ex_run(x, drive=2.0, mix=0.3, gate=1.0):
    ex = AuralExciter(SR)
    ex.set_drive(drive); ex.set_mix(mix); ex.set_enabled(True)
    out = []
    for i in range(0, len(x), 480):
        ex.set_voice_gate(gate)
        out.append(ex.process(x[i:i + 480].astype(np.float32)))
    return np.concatenate(out)


def _spec_db(y):
    Y = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / (len(y) / 4)
    return 20 * np.log10(np.maximum(Y, 1e-12))


def _bin(f):
    return int(round(f * _N / SR))


# 1. Sin fuga lineal: no toca el nivel de la banda, a ningun nivel de entrada
leaks = []
for _db in (-40, -20, -6):
    _x = (10 ** (_db / 20) * np.sin(2 * np.pi * 2000 * _t)).astype(np.float32)
    leaks.append(_spec_db(_ex_run(_x))[_bin(2000)] - _spec_db(_x)[_bin(2000)])
print(f"  Fuga lineal @2kHz: {', '.join(f'{v:+.2f} dB' for v in leaks)}")
assert all(abs(v) < 0.3 for v in leaks), "el excitador ecualiza en vez de agregar armonicos"

# 2. Genera armonicos de verdad y el drive los controla
_x = (0.1 * np.sin(2 * np.pi * 1500 * _t)).astype(np.float32)
h3 = {d: _spec_db(_ex_run(_x, d))[_bin(4500)] - _spec_db(_ex_run(_x, d))[_bin(1500)]
      for d in (2.0, 5.0)}
print(f"  H3 rel. fundamental: drive 2 {h3[2.0]:.1f} dB, drive 5 {h3[5.0]:.1f} dB")
assert h3[2.0] < -20.0, "demasiada distorsion a drive bajo"
assert h3[5.0] > h3[2.0] + 3.0, "el drive no aumenta los armonicos"

# 3. Independiente del nivel de entrada (normalizacion de la no linealidad)
h3_lvl = []
for _db in (-40, -25, -10):
    _x = (10 ** (_db / 20) * np.sin(2 * np.pi * 1500 * _t)).astype(np.float32)
    _S = _spec_db(_ex_run(_x, 5.0))
    h3_lvl.append(_S[_bin(4500)] - _S[_bin(1500)])
print(f"  H3 vs nivel: {', '.join(f'{v:.1f}' for v in h3_lvl)} dB")
assert max(h3_lvl) - min(h3_lvl) < 2.0, "el efecto depende del nivel de entrada"

# 4. Gate por VAD: sin voz no levanta el ruido de fondo
_rng = np.random.default_rng(5)
_nz = (_rng.standard_normal(_N) * 10 ** (-35 / 20)).astype(np.float32)
_hi = slice(_bin(1500), _bin(6000))
lift = float(np.mean(_spec_db(_ex_run(_nz, gate=0.0))[_hi] - _spec_db(_nz)[_hi]))
print(f"  Ruido de fondo con gate cerrado: {lift:+.2f} dB")
assert abs(lift) < 0.2, "el excitador levanta el ruido residual sin voz"

# 5. Abrir/cerrar el gate no produce clicks
_x = (0.1 * np.sin(2 * np.pi * 1500 * _t[:4800])).astype(np.float32)
_ex = AuralExciter(SR); _ex.set_drive(5.0); _ex.set_mix(0.5); _ex.set_enabled(True)
_o = []
for _i in range(0, len(_x), 480):
    _ex.set_voice_gate(0.0 if (_i // 480) % 4 < 2 else 1.0)
    _o.append(_ex.process(_x[_i:_i + 480]))
_step = float(np.max(np.abs(np.diff(np.concatenate(_o)))))
print(f"  Salto maximo al conmutar el gate: {_step:.5f}")
assert _step < float(np.max(np.abs(np.diff(_x)))) * 1.5, "click al abrir/cerrar el gate"
print("  Excitador: OK")

# --- Caracter par/impar del excitador ---------------------------------------
print("\n=== Excitador: caracter par/impar ===")
_x15 = (0.1 * np.sin(2 * np.pi * 1500 * _t)).astype(np.float32)


def _ex_char(x, char, drive=5.0, mix=1.0):
    ex = AuralExciter(SR)
    ex.set_drive(drive); ex.set_mix(mix); ex.set_enabled(True); ex.set_character(char)
    out = []
    for i in range(0, len(x), 480):
        ex.set_voice_gate(1.0)
        out.append(ex.process(x[i:i + 480].astype(np.float32)))
    return np.concatenate(out)


_S_odd = _spec_db(_ex_char(_x15, 0.0))
_S_even = _spec_db(_ex_char(_x15, 1.0))
_h2_odd = _S_odd[_bin(3000)] - _S_odd[_bin(1500)]
_h2_even = _S_even[_bin(3000)] - _S_even[_bin(1500)]
_h3_even = _S_even[_bin(4500)] - _S_even[_bin(1500)]
print(f"  H2: impar {_h2_odd:.1f} dB -> par {_h2_even:.1f} dB   (H3 en par: {_h3_even:.1f} dB)")
assert _h2_odd < -60.0, "tanh pura no deberia generar armonicos pares"
assert _h2_even > -35.0, "el caracter par no genera 2do armonico"
assert _h3_even < -60.0, "el caracter par no deberia dejar armonicos impares"

# El caracter es un crossfade de TIMBRE: no debe cambiar el nivel de salida
_vv = np.zeros(SR, dtype=np.float64)
for _k in range(1, 20):
    if _k * 150 < 3400:
        _vv += (1.0 / _k) * np.sin(2 * np.pi * _k * 150 * _t)
_vv = (_vv * 0.05).astype(np.float32)
_levels = [20 * np.log10(np.sqrt(np.mean(_ex_char(_vv, c) ** 2))
                         / np.sqrt(np.mean(_vv ** 2))) for c in (0.0, 0.5, 1.0)]
print(f"  Nivel vs caracter: {', '.join(f'{v:+.2f}' for v in _levels)} dB")
assert max(_levels) - min(_levels) < 1.0, "el caracter cambia el nivel (deberia ser timbre)"
print("  Caracter par/impar: OK")

# --- Recuperacion de graves (derivada de los armonicos) ---------------------
# Un pasa-altos de 300 Hz (filtro tipico de SSB) deja el fundamental de una voz de
# 120 Hz unos 32 dB abajo: no hay energia que una EQ pueda levantar. Se recupera
# DERIVANDOLO de los armonicos que sobrevivieron (band^2 -> la diferencia entre
# armonicos adyacentes cae en f0), no sintetizandolo aparte. Ver dsp/bass.py.
from dsp.bass import BassRestorer          # noqa: E402
from scipy.signal import sosfilt as _sosfilt, butter as _butter   # noqa: E402

print("\n=== BassRestorer ===")


def _voice_glide(n_samp, f_lo=110.0, f_hi=140.0):
    """Voz realista: entonacion (f0 sube y baja como en una frase), fuente glotal
    con caida de 12 dB/octava y formantes.
    OJO: NO usar armonicos 1/k para calibrar el nivel. Ahi el fundamental es el
    parcial mas fuerte; en una voz real domina el F1 (300-800 Hz), que cae dentro
    de la banda que el modulo eleva al cuadrado. Calibrar con 1/k sobreestimaba el
    factor en ~11 dB (reportado en el aire como "el efecto es muy fuerte")."""
    tt = np.arange(n_samp) / SR
    f0 = f_lo + (f_hi - f_lo) * 0.5 * (1 + np.sin(2 * np.pi * 0.7 * tt))
    ph = 2 * np.pi * np.cumsum(f0) / SR
    f0m = 0.5 * (f_lo + f_hi)
    s = np.zeros_like(tt)
    for k in range(1, 40):
        fk = k * f0m
        if fk >= 3600:
            break
        src = 10 ** (-12.0 * np.log2(max(k, 1)) / 20.0)
        env = sum(a / (1.0 + ((fk - fc) / (bw / 2)) ** 2)
                  for fc, bw, a in ((500, 90, 1.0), (1500, 130, 0.5), (2500, 180, 0.3)))
        s += src * env * np.sin(k * ph + 0.7 * k)
    s = s / (np.sqrt(np.mean(s ** 2)) + 1e-12) * 0.05
    return (s * (0.6 + 0.4 * np.sin(2 * np.pi * 3.0 * tt))).astype(np.float32)


_vb = _voice_glide(SR)
_hp300 = _butter(4, 300 / (SR / 2), btype='high', output='sos')
_vbf = _sosfilt(_hp300, _vb).astype(np.float32)
_bp_f0 = _butter(2, [80 / (SR / 2), 180 / (SR / 2)], btype='band', output='sos')


def _bass_run(src, amount):
    br = BassRestorer(SR)
    br.set_enabled(True); br.set_amount(amount)
    return np.concatenate([br.process(src[i:i + 480]) for i in range(0, len(src), 480)])


def _f0_db(y):
    return 20 * np.log10(np.sqrt(np.mean(_sosfilt(_bp_f0, y) ** 2)) + 1e-12)


_nat, _filt = _f0_db(_vb), _f0_db(_vbf)
_rest = _f0_db(_bass_run(_vbf, 1.0))
print(f"  Fundamental: natural {_nat:.1f} dB, filtrado {_filt:.1f} dB, restaurado {_rest:.1f} dB")
assert _filt < _nat - 10.0, "el filtro de prueba deberia matar el fundamental"
assert _rest > _filt + 10.0, "no restaura el fundamental"
assert abs(_rest - _nat) < 4.0, "el 100% deberia dejarlo cerca del nivel natural"

# Lo restaurado tiene que ser LA VOZ, no un tono pegado encima: se compara con el
# fundamental original. El oscilador independiente daba +0.01 aca (reportado en el
# aire como "muy artificial"); derivado de los armonicos va en fase con la voz.
_ref = _sosfilt(_bp_f0, _vb)[960:]
_got = _sosfilt(_bp_f0, _bass_run(_vbf, 0.5) - _vbf)[960:]
_corr = float(np.corrcoef(_ref, _got)[0, 1])
print(f"  Coherencia con el fundamental original: {_corr:+.3f}")
assert _corr > 0.5, "el grave restaurado no esta en fase con la voz (suena artificial)"

# Sin voz no hay armonicos de donde derivar: no debe retumbar (el oscilador
# agregaba +3.3 dB aca porque la autocorrelacion se dispara con cualquier cosa)
_nzb = (np.random.default_rng(5).standard_normal(SR) * 0.01).astype(np.float32)
_nzf = _sosfilt(_hp300, _nzb).astype(np.float32)
_lp200 = _butter(2, 200 / (SR / 2), btype='low', output='sos')
_added = _bass_run(_nzf, 1.0) - _nzf
_rumble = (20 * np.log10(np.sqrt(np.mean(_sosfilt(_lp200, _added) ** 2)) + 1e-12)
           - 20 * np.log10(np.sqrt(np.mean(_nzf ** 2)) + 1e-12))
print(f"  Con ruido solo agrega {_rumble:.1f} dB bajo 200 Hz")
assert _rumble < -10.0, "retumba con ruido (deberia callarse sin voz)"
print("  Recuperacion de graves: OK")

# --- AGC: techo de ganancia (para que no persiga el ruido) -------------------
# El AGC lleva lo que mida a su target sin distinguir voz de ruido: con señal
# debil sube el ruido de banda hasta +36 dB. El techo lo limita SIN congelarlo —
# congelarlo con un detector de voz se traba, porque el detector deja de disparar
# con la ganancia baja y el hold no se libera nunca (medido: la voz que vuelve
# quedaba 21 dB abajo). Ver dsp/agc.py.
from dsp.agc import AGC   # noqa: E402

print("\n=== AGC: techo de ganancia ===")
_nz_agc = (np.random.default_rng(3).standard_normal(SR) * 10 ** (-55 / 20)).astype(np.float32)


def _agc_gain_after(limit_db):
    a = AGC(SR, 480)
    a.set_preset("medium")

    a.set_max_gain_limit(limit_db)
    for i in range(0, len(_nz_agc), 480):
        a.process(_nz_agc[i:i + 480])
    return a.gain_db


_g_libre = _agc_gain_after(None)
_g_tope = _agc_gain_after(12.0)
print(f"  Ruido a -55 dBFS: sin techo {_g_libre:.1f} dB, con techo de 12 dB {_g_tope:.1f} dB")
assert _g_libre > 25.0, "sin techo el AGC deberia perseguir el ruido hasta el tope del preset"
assert _g_tope <= 12.5, "el techo no limita la ganancia"

# Y el techo NO congela: al llegar señal fuerte el AGC baja la ganancia como siempre
_a = AGC(SR, 480)
_a.set_preset("fast"); _a.set_max_gain_limit(12.0)
for i in range(0, len(_nz_agc), 480):
    _a.process(_nz_agc[i:i + 480])
_fuerte = (0.3 * np.sin(2 * np.pi * 800 * _t[:SR // 2])).astype(np.float32)
for i in range(0, len(_fuerte), 480):
    _a.process(_fuerte[i:i + 480])
print(f"  Con señal fuerte baja a {_a.gain_db:.1f} dB (sigue adaptando, no se congelo)")
assert _a.gain_db < 5.0, "el AGC quedo trabado con el techo puesto"
print("  Techo de ganancia del AGC: OK")


# --------------------------------------------------------------------- #
# ANF — persistencia: no confundir armonicos de voz con heterodinos      #
# --------------------------------------------------------------------- #
# El criterio espectral (mag > umbral * mediana vecina) es INSTANTANEO, y un
# armonico de voz lo cumple igual que una portadora. Medido antes del arreglo,
# con voz sola y NINGUN heterodino: marcaba bins en el 100% de los frames y se
# comia 2,9 dB de voz con profundidad 0,4 (8,4 con 0,9). Lo detecto el usuario
# viendo marcas rojas en la cascada que seguian a la voz. Lo que separa un
# heterodino de un armonico es el TIEMPO, no el espectro.
from dsp.anf import AdaptiveNotchFilter   # noqa: E402
from scipy.signal import lfilter          # noqa: E402

print("\n--- ANF: persistencia ---")

_rng_anf = np.random.default_rng(5)
_n_anf = 8 * SR
_t_anf = np.arange(_n_anf) / SR
# Voz con entonacion (los armonicos se MUEVEN — es lo que los distingue) +
# envolvente silabica. Sin entonacion el test seria optimista.
_f0 = 110.0 * (1.0 + 0.10 * np.sin(2 * np.pi * 0.6 * _t_anf))
_fase = 2 * np.pi * np.cumsum(_f0) / SR
_src = sum(np.sin(k * _fase) / (k ** 2) for k in range(1, 40))
_vz = np.zeros(_n_anf)
for _fc in (500.0, 1500.0, 2500.0):
    _r = np.exp(-np.pi * 120.0 / SR)
    _vz += lfilter([1 - _r], [1.0, -2 * _r * np.cos(2 * np.pi * _fc / SR), _r * _r], _src)
_env = np.zeros(_n_anf)
_i = 0
while _i + int(0.20 * SR) < _n_anf:
    _env[_i:_i + int(0.20 * SR)] = np.hanning(int(0.20 * SR))
    _i += int(0.28 * SR)
_vz = (_vz * _env + _rng_anf.standard_normal(_n_anf) * 0.004)
_vz = (_vz / (np.sqrt(np.mean(_vz ** 2)) + 1e-12) * 0.1).astype(np.float32)


def _corre_anf(sig, hop, depth):
    a = AdaptiveNotchFilter(SR, threshold=3.0, depth=depth)
    a.set_enabled(True)
    out, marcas = [], []
    for i in range(len(sig) // hop):
        out.append(a.process(sig[i * hop:(i + 1) * hop]))
        marcas.append(a.notched_bins > 0)
    return np.concatenate(out), float(np.mean(marcas))


def _db_anf(x):
    return 20.0 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


for _hop in (480, 960):
    _out, _frac = _corre_anf(_vz, _hop, 0.9)
    _dano = _db_anf(_out) - _db_anf(_vz[:len(_out)])
    print(f"  Voz sola, hop {_hop}: marcas en {_frac*100:.0f}% de los frames, "
          f"voz {_dano:+.2f} dB")
    assert _frac < 0.05, \
        f"el ANF marca voz como tono en el {_frac*100:.0f}% de los frames (hop {_hop})"
    assert _dano > -0.5, \
        f"el ANF se come {_dano:.2f} dB de voz sin ningun heterodino (hop {_hop})"

# Y con un heterodino de verdad lo sigue cancelando
_het = (0.05 * np.sin(2 * np.pi * 1350.0 * _t_anf)).astype(np.float32)
_mez = (_vz + _het).astype(np.float32)
_out_h, _ = _corre_anf(_mez, 960, 0.9)


def _energia(x, lo, hi):
    X = np.fft.rfft(x.astype(np.float64) * np.hanning(len(x)))
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    m = (f > lo) & (f < hi)
    return 20.0 * np.log10(np.sqrt(np.mean(np.abs(X[m]) ** 2)) + 1e-12)


_m2 = len(_out_h) // 2          # segunda mitad: ya enganchado
_ref_h = _mez[:len(_out_h)]
_d_tono = _energia(_out_h[_m2:], 1320, 1380) - _energia(_ref_h[_m2:], 1320, 1380)
_d_voz  = _energia(_out_h[_m2:], 200, 1300) - _energia(_ref_h[_m2:], 200, 1300)
print(f"  Heterodino 1350 Hz: {_d_tono:.1f} dB   |   voz fuera del tono: {_d_voz:+.2f} dB")
assert _d_tono < -10.0, f"el heterodino real ya no se cancela ({_d_tono:.1f} dB)"
assert _d_voz > -0.5, f"cancelar el tono se lleva {_d_voz:.2f} dB de voz"

# La persistencia va en frames -> depende del hop (invariante 9)
for _hp in (240, 480, 960, 1920):
    _a2 = AdaptiveNotchFilter(SR)
    _a2.set_enabled(True)
    _a2.process(np.zeros(_hp, dtype=np.float32))
    _ms = _a2._persist_frames * _hp / (SR / 1000.0)
    assert abs(_ms - AdaptiveNotchFilter._PERSIST_MS) < 30.0, \
        f"persistencia mal escalada con hop {_hp}: {_ms:.0f} ms"
print("  Persistencia recalculada por hop (invariante 9): OK")
print("  ANF: OK")


# --------------------------------------------------------------------- #
# Supresor de impulsos: no debe tocar la voz                             #
# --------------------------------------------------------------------- #
# Reportado en el aire ("causa distorsion de la voz, es notoria al activarlo").
# La version anterior comparaba contra el PISO DE RUIDO, asi que con voz 20 dB
# sobre el piso toda silaba cruzaba el umbral: atenuaba el 26% de los
# mini-frames sobre voz LIMPIA, -6,8 dB de voz y -6,6 dB de distorsion (casi el
# 50% de la senal). Y el error EMPEORABA cuanto mejor era la senal.
from dsp.blanker import ImpulseBlanker   # noqa: E402

print("\n--- Supresor de impulsos ---")

_hop_b = 1920
_n_b = 6 * SR
_t_b = np.arange(_n_b) / SR
_f0b = 120.0 * (1.0 + 0.10 * np.sin(2 * np.pi * 0.6 * _t_b))
_faseb = 2 * np.pi * np.cumsum(_f0b) / SR
_srcb = sum(np.sin(k * _faseb) / (k ** 2) for k in range(1, 40))
_vb = np.zeros(_n_b)
for _fc in (500.0, 1500.0, 2500.0):
    _r = np.exp(-np.pi * 120.0 / SR)
    _vb += lfilter([1 - _r], [1.0, -2 * _r * np.cos(2 * np.pi * _fc / SR), _r * _r], _srcb)
_envb = np.zeros(_n_b)
_i = 0
while _i + int(0.20 * SR) < _n_b:
    _envb[_i:_i + int(0.20 * SR)] = np.hanning(int(0.20 * SR))
    _i += int(0.28 * SR)
_vb *= _envb
_vb /= (np.sqrt(np.mean(_vb ** 2)) + 1e-12)
_voz_b = (_vb + np.random.default_rng(3).standard_normal(_n_b) * 0.1).astype(np.float32)


def _pasar_blanker(sig, thr_f=20.0, thr_m=12.0):
    b = ImpulseBlanker(SR)
    b.set_enabled(True)
    b.set_frame_threshold(thr_f)
    b.set_mini_threshold(thr_m)
    o = np.concatenate([b.process(sig[i * _hop_b:(i + 1) * _hop_b])
                        for i in range(len(sig) // _hop_b)])
    return o, b.pop_hits()


def _distorsion(out, ref):
    k = np.dot(out, ref) / np.dot(ref, ref)
    err = out - k * ref
    return 20.0 * np.log10((np.sqrt(np.mean(err ** 2)) + 1e-12)
                           / (np.sqrt(np.mean((k * ref) ** 2)) + 1e-12))


_out_b, _hits_b = _pasar_blanker(_voz_b)
_ref_b = _voz_b[:len(_out_b)]
_dano_b = _db_anf(_out_b) - _db_anf(_ref_b)
_dist_b = _distorsion(_out_b, _ref_b)
_pct_b = 100.0 * _hits_b / max(1, len(_out_b) // 32)
print(f"  Voz limpia: {_pct_b:.2f}% de disparos, voz {_dano_b:+.2f} dB, "
      f"distorsion {_dist_b:.1f} dB")
assert _pct_b < 2.0, f"dispara sobre voz limpia el {_pct_b:.1f}% (era 26%)"
assert _dano_b > -1.5, f"se come {_dano_b:.2f} dB de voz sin impulsos (era -6,8)"
assert _dist_b < -12.0, f"distorsion {_dist_b:.1f} dB sobre voz limpia (era -6,6)"

# Y un impulso real se sigue suprimiendo
_imp_b = _voz_b.copy()
_pos_b = [int(x * SR) for x in (1.0, 2.3, 3.5, 4.7)]
_amp_b = np.sqrt(np.mean(_voz_b ** 2)) * 10 ** (25 / 20.0)
_rb = np.random.default_rng(9)
for _q in _pos_b:
    _imp_b[_q:_q + 14] += (_amp_b * _rb.standard_normal(14)).astype(np.float32)
_out_i, _ = _pasar_blanker(_imp_b)
_res = max(np.max(np.abs(_out_i[_q - 20:_q + 40])) for _q in _pos_b)
_pin = max(np.max(np.abs(_imp_b[_q - 20:_q + 40])) for _q in _pos_b)
_sup = 20.0 * np.log10(_res / _pin)
print(f"  Impulso real: {_sup:.1f} dB")
assert _sup < -8.0, f"ya no suprime impulsos ({_sup:.1f} dB)"

# El supresor NUNCA puede amplificar (la dilatacion de la mascara lo permitia:
# medido, subia el impulso +12,9 dB en vez de bajarlo)
assert np.max(np.abs(_out_i)) <= np.max(np.abs(_imp_b)) * 1.01, \
    "el supresor amplifico la senal"
print("  Supresor de impulsos: OK")
