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
pipeline.spectrum_pre_frames.clear()
pipeline.spectrum_post_frames.clear()
out_bypass = pipeline._process(np.ones(hop, dtype=np.float32) * 0.1)
assert np.allclose(out_bypass, np.ones(hop) * 0.1, atol=1e-5), "Bypass fallo"
# El espectro debe seguir alimentandose en bypass (antes quedaba congelado):
# entrada == salida == señal cruda, ambos deques reciben el frame.
assert len(pipeline.spectrum_pre_frames) == 1, "espectro (entrada) no se alimenta en bypass"
assert len(pipeline.spectrum_post_frames) == 1, "espectro (salida) no se alimenta en bypass"
assert np.allclose(pipeline.spectrum_pre_frames[-1], pipeline.spectrum_post_frames[-1]), \
    "en bypass entrada y salida (0 dB) del espectro deben coincidir"
print("\nBypass: OK (espectro alimentado)")

# La ganancia de salida DEBE actuar en bypass (antes solo la aplicaba el
# limitador del hilo procesador, que en bypass no corre → el slider no accionaba).
pipeline.spectrum_pre_frames.clear()
pipeline.spectrum_post_frames.clear()
pipeline.set_output_gain_db(6.0)  # x2 lineal aprox (10**(6/20)=1.995)
out_gain = pipeline._process(np.ones(hop, dtype=np.float32) * 0.1)
assert np.allclose(out_gain, 0.1 * (10 ** (6.0 / 20.0)), atol=1e-5), \
    "ganancia de salida no se aplico en bypass"
# La "Salida" del espectro/grabacion refleja la ganancia; la "Entrada" no.
assert np.allclose(pipeline.spectrum_pre_frames[-1], np.ones(hop) * 0.1, atol=1e-5), \
    "en bypass la Entrada del espectro no debe llevar la ganancia de salida"
assert np.allclose(pipeline.spectrum_post_frames[-1], out_gain, atol=1e-5), \
    "en bypass la Salida del espectro debe llevar la ganancia de salida"
pipeline.set_output_gain_db(0.0)  # restaurar unity para el test de mute
print("Bypass: OK (ganancia de salida aplicada)")

# ------------------------------------------------------------------
# Mute de salida: silencia la salida al dispositivo pero el proceso sigue
# (el espectro se sigue alimentando). Se prueba sobre el path de bypass
# (sincrono, sin hilo procesador).
pipeline.spectrum_pre_frames.clear()
pipeline.set_output_mute(True)
out_muted = pipeline._process(np.ones(hop, dtype=np.float32) * 0.1)
assert np.allclose(out_muted, 0.0), "Mute no silencio la salida"
assert len(pipeline.spectrum_pre_frames) == 1, "Mute congelo el espectro (deberia seguir)"
pipeline.set_output_mute(False)
out_unmuted = pipeline._process(np.ones(hop, dtype=np.float32) * 0.1)
assert np.allclose(out_unmuted, np.ones(hop) * 0.1, atol=1e-5), "Unmute no restauro la salida"
pipeline.set_bypass(False)
print("Mute de salida: OK (salida en silencio, espectro vivo)")

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

# ------------------------------------------------------------------
# Grabación a WAV (headless): graba N frames y verifica los archivos
# ------------------------------------------------------------------
print("\nGrabacion WAV...")
import glob
import os
import tempfile
import wave

rec_dir = tempfile.mkdtemp()
c = AppConfig()
c.dsp.noise_enabled = False
c.audio.record_raw_input = True        # dos archivos: procesado + entrada
p = ProcessingPipeline(c)
p.start(headless=True)
rng_r = np.random.default_rng(11)
h = c.audio.block_size
p.start_recording(directory=rec_dir)
N_FRAMES = 50
for _ in range(N_FRAMES):
    p._process(rng_r.standard_normal(h).astype(np.float32) * 0.1)
    time.sleep(0.004)
time.sleep(0.3)                        # dejar drenar la cola del escritor
secs = p.stop_recording()
p.stop()

wavs = sorted(glob.glob(os.path.join(rec_dir, "*.wav")))
assert len(wavs) == 2, f"esperaba 2 WAV (procesado+entrada), hay {len(wavs)}: {wavs}"
for path in wavs:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 48000, f"sample rate {w.getframerate()}"
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "formato no es mono 16-bit"
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16)
    assert n > 0, f"{os.path.basename(path)} vacio"
    assert np.max(np.abs(data)) > 100, f"{os.path.basename(path)} sin contenido"
    print(f"  {os.path.basename(path)}: {n} muestras, pico {np.max(np.abs(data))}")
assert secs > 0, "stop_recording devolvio 0 segundos"
print(f"Grabacion WAV: OK ({secs:.2f} s grabados)")

# ------------------------------------------------------------------
# Perfil de ruido independiente del filtro: se aprende sobre el espectro
# COMPLETO (pre-pasabanda), así suprime los agudos aunque el pasabanda cambie
# o se apague (antes aprendía ~0 en los agudos con el filtro angosto → siseo
# sin suprimir al ensanchar/reiniciar).
# ------------------------------------------------------------------
print("\nPerfil independiente del filtro...")
from config import RadioMode

cf = AppConfig()
cf.dsp.noise_mode = "static"
cf.dsp.noise_enabled = True
cf.dsp.bandpass_pre_enabled = True
cf.dsp.mode = RadioMode.SSB
cf.dsp.bandpass_limits[RadioMode.SSB] = (300, 1500)   # pasabanda ANGOSTO
cf.dsp.anf_enabled = False
cf.dsp.squelch_enabled = False
cf.dsp.perceptual_floor_enabled = False
cf.dsp.post_filter_enabled = False
pf = ProcessingPipeline(cf)
pf.start(headless=True)
hp = cf.audio.block_size
fpb = 48000.0 / (hp * 2)
rp = np.random.default_rng(7)

pf.start_noise_learning()
for _ in range(200):
    pf._process((rp.standard_normal(hp) * 0.1).astype(np.float32))
time.sleep(0.3)
pf.stop_noise_learning()

mag = pf._noise_profiler._noise_mag
assert mag is not None, "no se aprendio perfil"


def _band_e(lo, hi):
    b0, b1 = int(lo / fpb), int(hi / fpb)
    return float(np.mean(mag[b0:b1] ** 2))


# El perfil debe tener energia en los AGUDOS (fuera del pasabanda angosto de aprendizaje)
assert _band_e(3000, 6000) > 0.3 * _band_e(300, 1500), \
    "el perfil no aprendio ruido en los agudos (deberia ser full-spectrum)"

# Y debe SUPRIMIR los agudos con el pasabanda apagado (caso ensanche/reinicio)
pf.set_bandpass_pre_enabled(False)
ins, outs = [], []
for _ in range(60):
    x = (rp.standard_normal(hp) * 0.1).astype(np.float32)
    y = pf._process(x)
    ins.append(x)
    if y is not None:
        outs.append(y)
time.sleep(0.2)
xi = np.concatenate(ins[-len(outs):])
yo = np.concatenate(outs)


def _hi_e(x):
    X = np.abs(np.fft.rfft(x))
    fpb2 = 48000.0 / len(x)
    return float(np.mean(X[int(3000 / fpb2):int(6000 / fpb2)] ** 2))


red_db = 10 * np.log10(max(_hi_e(yo), 1e-30) / max(_hi_e(xi), 1e-30))
assert red_db < -6.0, f"no suprime agudos con pasabanda off (reduccion {red_db:.1f} dB)"
pf.stop()
print(f"Perfil independiente del filtro: OK (agudos suprimidos {red_db:.1f} dB con filtro off)")

# --- Preview: no debe pasar por las etapas de coloreo -----------------------
# El preview es material de DIAGNOSTICO (lo que el cancelador RESTA). Si pasa
# por el nivelador, la EQ de presencia o el excitador, un resto de voz apenas
# audible sale nivelado, realzado en 1.5 kHz y con armonicos nuevos — y las tres
# se disparan justo cuando hay voz (el excitador tiene gate por VAD), asi que
# suena mucho mas presente de lo que realmente se esta quitando. El squelch
# ademas cerraria el gate sin voz y no se escucharia el ruido eliminado.
def _preview_calls(preview: bool) -> dict:
    c = AppConfig()
    d = c.dsp
    d.noise_enabled = True
    d.noise_mode = "mcra"
    d.blanker_enabled = False
    d.anf_enabled = False
    d.squelch_enabled = True
    d.voice_leveler_enabled = True
    d.voice_leveler_gate_voice = False
    d.presence_enabled = True
    d.presence_db = 3.0
    d.exciter_enabled = True
    d.exciter_mix = 0.3
    pp = ProcessingPipeline(c)
    calls = {"exciter": 0, "presence": 0, "leveler": 0}
    for name, obj in (("exciter", pp._exciter), ("presence", pp._presence),
                      ("leveler", pp._agc_voice)):
        orig = obj.process

        def wrap(x, *a, _o=orig, _n=name, **k):
            calls[_n] += 1
            return _o(x, *a, **k)
        obj.process = wrap
    pp.start(headless=True)
    try:
        pp.set_noise_preview(preview)
        rr = np.random.default_rng(9)
        for i in range(200):
            tt = (np.arange(hop) + i * hop) / 48000.0
            v = sum((1.0 / k) * np.sin(2 * np.pi * k * 150 * tt) for k in range(1, 18))
            pp._process(((v * 0.05) + rr.standard_normal(hop) * 0.01).astype(np.float32))
            if i % 10 == 0:
                time.sleep(0.004)
        time.sleep(0.4)
        return dict(calls)
    finally:
        pp.stop()


_norm = _preview_calls(False)
_prev = _preview_calls(True)
assert all(v > 0 for v in _norm.values()), f"sin preview las etapas deben correr: {_norm}"
assert all(v == 0 for v in _prev.values()), f"el preview no debe colorear: {_prev}"
print(f"Preview sin coloreo: OK (normal {_norm}, preview {_prev})")

# --- Piso de ruido de la entrada: debe medir el RUIDO, no el nivel ----------
# El techo de ruido del AGC vale (techo - piso), asi que si el seguidor mide el
# nivel de la voz en vez del ruido, el control queda inservible. La primera
# version usaba un minimo con decaimiento y trepaba hacia la voz: con voz a -20
# dBFS y ruido a -40 marcaba -28 (reportado en el aire: "el piso que detecta
# incluye voz, el piso marcado es lo que indica el VU"). Ahora es minimo por
# ventana deslizante, el mismo patron que usa MCRA.
_pf_cfg = AppConfig()
_pf_cfg.dsp.agc_noise_ceiling_enabled = True
_pf_cfg.dsp.agc_preset = "off"
_pf_cfg.dsp.noise_enabled = False
_pf_cfg.dsp.blanker_enabled = False
_pf_cfg.dsp.anf_enabled = False
_pp = ProcessingPipeline(_pf_cfg)

_rr = np.random.default_rng(4)
_VOZ_DB, _RUIDO_DB = -20.0, -40.0
_tt = np.arange(1200 * hop) / 48000.0
_vv = np.zeros_like(_tt)
for _k in range(1, 20):
    if _k * 130 < 3400:
        _vv += (1.0 / _k) * np.sin(2 * np.pi * _k * 130 * _tt)
_vv /= (np.sqrt(np.mean(_vv ** 2)) + 1e-12)
_ee = np.zeros_like(_tt)
for _i in range(1200):
    if (_i % 40) < 25:                       # 250 ms de voz cada 400 ms
        _ee[_i * hop:(_i + 1) * hop] = 1.0
_xx = (_vv * _ee * 10 ** (_VOZ_DB / 20) * np.sqrt(2)
       + _rr.standard_normal(1200 * hop) * 10 ** (_RUIDO_DB / 20)).astype(np.float32)
for _i in range(1200):
    _pp._track_input_noise(_xx[_i * hop:(_i + 1) * hop])

_piso = _pp.input_noise_db
print(f"Piso de entrada medido: {_piso:.1f} dBFS "
      f"(ruido real {_RUIDO_DB:.0f}, voz {_VOZ_DB:.0f})")
assert abs(_piso - _RUIDO_DB) < 4.0, \
    f"el seguidor no mide el piso ({_piso:.1f} dB con ruido en {_RUIDO_DB:.0f})"
assert _piso < _VOZ_DB - 12.0, "el piso esta contaminado por la voz"
print("Piso de ruido de entrada: OK")

# ---------------------------------------------------------------------- #
# Diagnostico del hilo procesador (invariante 9)                           #
# ---------------------------------------------------------------------- #
# Un fallo por frame en _run_processor se recupera solo, asi que el usuario NO
# ve ningun error: en MCRA el manejador resetea el profiler cada frame y el
# estimador nunca sale del warmup -> no calibra, no reduce y no dibuja el piso
# en el espectro, todo junto. Cambiar de modo lo "arregla" (set_mode rearma el
# estado), que es lo que lo vuelve indescifrable. Reportado en el aire y no
# reproducible en el banco: por eso se cuenta y se deja traceback en disco.
import io as _io
import os as _os

_log = _os.path.join(_os.environ.get("RNK_DATA_DIR") or ".", "errores_dsp.log")
if _os.path.exists(_log):
    _os.remove(_log)

_cfg_e = AppConfig()
_cfg_e.dsp.noise_mode = "mcra"
_cfg_e.dsp.noise_enabled = True
_cfg_e.dsp.perceptual_floor_enabled = True
_pe = ProcessingPipeline(_cfg_e)
_pe.start(headless=True)
assert _pe.dsp_error_count == 0, "arranca con errores ya contados"
# Curva por-bin con el tamano viejo: el shape mismatch del invariante 9
_pe._noise_profiler._floor_curve = np.ones(7, dtype=np.float32)
_rng_e = np.random.default_rng(7)
_hop_e = _cfg_e.audio.block_size
# La linea que falla vive DESPUES del warmup (que es B*M frames + la cuarentena),
# asi que hay que alimentar lo suficiente para llegar hasta ahi. Con 40 frames el
# test pasaba a verde sin haber ejercitado nada.
for _i in range(140):
    _pe._process(_rng_e.standard_normal(_hop_e).astype(np.float32) * 0.05)
    time.sleep(0.003)
time.sleep(0.4)

assert _pe.dsp_error_count > 0, "el fallo no quedo contado"
assert _pe.dsp_last_error, "no se guardo el texto del ultimo error"
assert _os.path.exists(_log), "no se escribio errores_dsp.log"
_texto = _io.open(_log, encoding="utf-8").read()
assert "Traceback" in _texto, "el log no trae el traceback"
assert "modo=mcra" in _texto, "el log no registra el modo"
_bloques = _texto.count("(error #")
assert _bloques <= ProcessingPipeline._DSP_LOG_MAX, \
    f"el log no esta acotado: {_bloques} bloques con {_pe.dsp_error_count} errores"

# Y SE RECUPERA SOLO: reset() rearma las curvas por-bin cuyo tamano no coincide
# con _nb. Sin eso la curva corrupta sobrevive al reset, el error se repite y
# MCRA no sale nunca del warmup — el sintoma reportado en el aire, que solo se
# curaba cambiando de modo.
assert len(_pe._noise_profiler._floor_curve) == _pe._noise_profiler._nb, \
    "reset() no rearmo la curva por-bin corrupta"
for _i in range(160):
    _pe._process(_rng_e.standard_normal(_hop_e).astype(np.float32) * 0.05)
    time.sleep(0.002)
time.sleep(0.5)
_err_final = _pe.dsp_error_count
assert _pe.noise_has_profile, \
    f"MCRA no se recupero: sigue en warmup tras {_err_final} errores"
print(f"Errores del procesador: {_err_final} contados, "
      f"{_bloques} registrados (tope {ProcessingPipeline._DSP_LOG_MAX}), "
      f"y MCRA se recupero solo")
_pe.stop()

# El contador se limpia en cada arranque: si no, un error viejo dejaria el aviso pegado
_pe._noise_profiler.reset(_hop_e)
_pe.start(headless=True)
assert _pe.dsp_error_count == 0, "start() no reseteo el contador de errores"
_pe.stop()
print("Diagnostico del hilo procesador: OK")

print(f"\nErrores: {errors if errors else 'ninguno'}")
print("\nPipeline: OK")
