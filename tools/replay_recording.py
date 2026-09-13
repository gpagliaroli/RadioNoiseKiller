"""Pasa una grabación `_entrada.wav` por la cadena DSP real, en sincrónico.

Uso:
    .venv/Scripts/python.exe tools/replay_recording.py Grabaciones/RNK_..._entrada.wav
        [--settings settings.json] [--out salida.wav] [--trace] [clave=valor ...]

- Corre `ProcessingPipeline._process_chunk` sin hilo ni colas (regla de método 11:
  la dispersión del hilo se come cualquier diferencia que se quiera medir).
- `clave=valor` pisa campos de `DSPConfig` (p. ej. `noise_alpha=0.7`), así se
  comparan dos configuraciones sobre la MISMA señal.
- `--trace` imprime el estado interno por frame (nivel, AGC, vp, nivelador, gate,
  reducción, post-filtro, f0, ventana de ataque).
- La grabación ya trae la ganancia de entrada aplicada: se fuerza input_gain_db=0.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np                       # noqa: E402
from scipy.io import wavfile             # noqa: E402
from config import AppConfig             # noqa: E402
from pipeline import ProcessingPipeline  # noqa: E402


def replay(wav, settings="settings.json", overrides=None, trace=False):
    cfg = AppConfig()
    cfg.load(settings)
    cfg.gain.input_gain_db = 0.0
    for k, v in (overrides or {}).items():
        setattr(cfg.dsp, k, v)
    p = ProcessingPipeline(cfg)
    p.apply_config(cfg)
    p.start(headless=True)          # inicializa todos los módulos como en la app
    p._running = False
    p._shutdown_processor_thread()  # y se queda sin hilo: la cadena corre acá
    sr, x = wavfile.read(wav)
    x = (x / 32768.0).astype(np.float32)
    if x.ndim > 1:
        x = x[:, 0]
    hop = cfg.audio.block_size
    n = len(x) // hop
    out = np.zeros(n * hop, dtype=np.float32)
    npf = p._noise_profiler
    if trace:
        print("    t   in_dB out_dB  agc   vp   lev  gate    nr    pf   f0 atk")
    for i in range(n):
        c = x[i * hop:(i + 1) * hop]
        p._db_in = p._level_in.process(c)
        o = p._process_chunk(c)
        out[i * hop:(i + 1) * hop] = o
        if trace:
            print("%6.2f %6.1f %6.1f %5.1f %4.2f %5.1f %4.2f %6.1f %5.1f %4.0f %d" % (
                i * hop / sr,
                20 * np.log10(np.sqrt(np.mean(c ** 2)) + 1e-9),
                20 * np.log10(np.sqrt(np.mean(o ** 2)) + 1e-9),
                p._agc.gain_db, npf.voice_prob, p._agc_voice.gain_db, p._gate.gain,
                npf.last_reduction_db, npf.pf_extra_db, npf.pitch_f0 or 0,
                npf._atk_window))
    return sr, out, p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--settings", default="settings.json")
    ap.add_argument("--out")
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("overrides", nargs="*")
    a = ap.parse_args()
    ov = {}
    for kv in a.overrides:
        k, v = kv.split("=", 1)
        ov[k] = json.loads(v)
    sr, out, p = replay(a.wav, a.settings, ov, a.trace)
    print("errores DSP:", p.dsp_error_count,
          "| salida RMS %.1f dBFS" % (20 * np.log10(np.sqrt(np.mean(out ** 2)) + 1e-9)))
    if a.out:
        wavfile.write(a.out, sr, (np.clip(out, -1, 1) * 32767).astype(np.int16))
        print("escrito", a.out)
