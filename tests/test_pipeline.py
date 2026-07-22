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
    "en bypass entrada y salida del espectro deben coincidir"
print("\nBypass: OK (espectro alimentado)")

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

print(f"\nErrores: {errors if errors else 'ninguno'}")
print("\nPipeline: OK")
