"""
Benchmark de CPU por módulo del pipeline. NO es un test de regresión: no está en
`run_all.py` y no falla nunca — es una herramienta de diagnóstico.

    .venv\\Scripts\\python.exe tests\\test_cpu_profile.py      (Windows)
    .venv/bin/python        tests/test_cpu_profile.py         (Linux/Pi)

Mide el tiempo de procesar un frame de 480 muestras (10 ms @ 48 kHz) y lo expresa
como % de un núcleo: 10 000 µs por frame = 100% de un core en tiempo real. Sirve
para decidir qué activar en equipos débiles — el caso testigo es un AMD A6 de dos
núcleos, donde la app llegó a estar al 100% antes de la optimización de v1.4.

Ojo al leer los números: dependen del equipo y de la carga del momento. Lo que
importa es la comparación ENTRE módulos y contra corridas previas del mismo
equipo, no el valor absoluto.
"""
import sys
import time

sys.path.insert(0, "src")

import numpy as np
from config import AppConfig, DSPConfig, RadioMode
from dsp.agc import AGC
from dsp.anf import AdaptiveNotchFilter
from dsp.bass import BassRestorer
from dsp.exciter import AuralExciter
from dsp.filters import BandpassFilter, PresenceFilter
from dsp.freq_shift import FrequencyShifter
from dsp.gain import GainLimiter
from dsp.level import LevelMeter
from dsp.noise_profiler import NoiseProfiler

SR, HOP = 48000, 480
FRAME_US = HOP / SR * 1e6          # 10 000 µs de audio por frame
N_WARM, N_RUN = 100, 400

rng = np.random.default_rng(7)
_t = np.arange(N_RUN * HOP) / SR
_voz = np.zeros_like(_t)
for _k in range(1, 25):
    if _k * 130 < 3400:
        _voz += (1.0 / _k) * np.sin(2 * np.pi * _k * 130 * _t)
_voz /= np.sqrt(np.mean(_voz ** 2))
SEÑAL = ((_voz * 0.05 + rng.standard_normal(N_RUN * HOP) * 0.01)
         .astype(np.float32).reshape(N_RUN, HOP))
WARM = SEÑAL[:N_WARM]


def bench(nombre: str, fn) -> tuple:
    """Corre fn(frame) sobre la señal y devuelve (nombre, µs/frame, % de un core)."""
    for f in WARM:
        fn(f)
    t0 = time.perf_counter()
    for f in SEÑAL:
        fn(f)
    us = (time.perf_counter() - t0) / len(SEÑAL) * 1e6
    return nombre, us, 100.0 * us / FRAME_US


def modulos():
    cfg = DSPConfig()

    bp = BandpassFilter(cfg, SR)
    yield bench("Filtro de paso de banda", bp.process)

    anf = AdaptiveNotchFilter(SR, HOP)
    yield bench("ANF (muesca espectral)", anf.process)

    agc = AGC(SR, HOP)
    agc.set_preset("medium")
    yield bench("AGC", agc.process)

    for modo, post in (("static", 0.0), ("mcra", 0.0), ("mcra", 6.0)):
        p = NoiseProfiler(HOP)
        p.set_mode(modo)
        if modo == "static":
            p.start_learning()
            for f in WARM:
                p.process(f)
            p.stop_learning()
        if post:
            p.set_post_filter_enabled(True)
            p.set_post_filter_strength(post)
        etiqueta = ("Cancelador (perfil estático)" if modo == "static"
                    else "Cancelador (adaptativo)" if not post
                    else "Cancelador (adaptativo + post-filtro)")
        yield bench(etiqueta, p.process)

    pf = PresenceFilter(SR)
    pf.set_gain_db(4.0)
    yield bench("EQ de presencia (una banda)", pf.process)

    ex = AuralExciter(SR)
    ex.set_enabled(True)
    ex.set_voice_gate(1.0)
    yield bench("Excitador armónico", ex.process)

    ex2 = AuralExciter(SR)
    ex2.set_enabled(True)
    ex2.set_character(0.5)
    ex2.set_voice_gate(1.0)
    yield bench("Excitador (carácter mixto)", ex2.process)

    br = BassRestorer(SR)
    br.set_enabled(True)
    yield bench("Recuperar graves", br.process)

    fs = FrequencyShifter(SR)
    fs.set_shift_hz(100.0)
    yield bench("Corrimiento de frecuencia", fs.process)

    gl = GainLimiter(0.0, -1.0)
    yield bench("Limitador de picos", lambda f: gl.process(f, SR))

    lm = LevelMeter()
    yield bench("Medidor de nivel", lm.process)


print("=" * 72)
print("  CPU por módulo — µs por frame de 10 ms y % de un núcleo")
print("=" * 72)
total = 0.0
for nombre, us, pct in modulos():
    total += us
    print(f"  {nombre:<38} {us:8.1f} us   {pct:5.2f} %")
print("-" * 72)
print(f"  {'suma de los módulos medidos':<38} {total:8.1f} us   "
      f"{100.0 * total / FRAME_US:5.2f} %")

# --- Pipeline completo, que es lo que se siente en el equipo ---------------
from pipeline import ProcessingPipeline   # noqa: E402

print()
print("=" * 72)
print("  Pipeline completo — CPU de TODOS los hilos por frame")
print("=" * 72)
print("  (se mide con process_time: el DSP corre en el hilo procesador, no en")
print("   el callback, así que cronometrar _process() solo mide la cola)")
for etiqueta, ajustes in (
    ("mínimo (pasabanda + limitador)",
     dict(blanker_enabled=False, anf_enabled=False, noise_enabled=False,
          presence_enabled=False)),
    ("típico (adaptativo + post-filtro)",
     dict(noise_mode="mcra", post_filter_enabled=True, post_filter_strength=3.0)),
    ("todo activado",
     dict(noise_mode="mcra", post_filter_enabled=True, post_filter_strength=3.0,
          perceptual_floor_enabled=True, pitch_enhance_enabled=True,
          squelch_enabled=True, voice_leveler_enabled=True, exciter_enabled=True,
          bass_enabled=True, agc_noise_ceiling_enabled=True,
          bandpass_out_independent=True)),
):
    cfg = AppConfig()
    cfg.dsp.mode = RadioMode.SSB
    cfg.dsp.agc_preset = "medium"
    for k, v in ajustes.items():
        setattr(cfg.dsp, k, v)
    p = ProcessingPipeline(cfg)
    p.start(headless=True)
    try:
        for f in WARM:
            p._process(f)
        time.sleep(0.3)
        # process_time() cuenta CPU de todos los hilos e IGNORA el sleep, así que
        # mide el trabajo real aunque haya que darle aire al hilo procesador.
        t0 = time.process_time()
        for i, f in enumerate(SEÑAL):
            p._process(f)
            if i % 20 == 0:
                time.sleep(0.002)
        time.sleep(0.4)           # que el procesador termine la cola
        us = (time.process_time() - t0) / len(SEÑAL) * 1e6
    finally:
        p.stop()
    print(f"  {etiqueta:<38} {us:8.1f} us   {100.0 * us / FRAME_US:5.2f} %")
