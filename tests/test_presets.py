"""
Tests de presets: cobertura de campos, save/load, rename, delete,
y verificacion de que apply_config() transfiere todos los campos DSP+Gain.
"""
import dataclasses
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import AppConfig, DSPConfig, GainConfig, RadioMode
from presets import PresetManager
from pipeline import ProcessingPipeline


# Campos de DSPConfig gestionados como sub-dict en el preset (no campo simple)
_DSP_COMPLEX = {"bandpass_limits"}


def _all_dsp_fields():
    return {f.name for f in dataclasses.fields(DSPConfig)} - _DSP_COMPLEX


def _all_gain_fields():
    return {f.name for f in dataclasses.fields(GainConfig)}


# ---------------------------------------------------------------------- #
# 1. _capture() cubre todos los campos                                    #
# ---------------------------------------------------------------------- #

def test_capture_covers_all_dsp_fields():
    """_capture() debe serializar todos los campos simples de DSPConfig."""
    app  = AppConfig()
    data = PresetManager._capture("test", app)
    dsp_keys = set(data["dsp"].keys())

    missing = _all_dsp_fields() - dsp_keys
    assert not missing, f"Campos DSPConfig no en preset._capture(): {sorted(missing)}"
    print("_capture() cubre DSPConfig       OK")


def test_capture_covers_all_gain_fields():
    """_capture() debe serializar todos los campos de GainConfig."""
    app  = AppConfig()
    data = PresetManager._capture("test", app)
    gain_keys = set(data["gain"].keys())

    missing = _all_gain_fields() - gain_keys
    assert not missing, f"Campos GainConfig no en preset._capture(): {sorted(missing)}"
    print("_capture() cubre GainConfig      OK")


# ---------------------------------------------------------------------- #
# 2. apply_config() transfiere todos los campos al pipeline               #
# ---------------------------------------------------------------------- #

def test_apply_config_covers_all_fields():
    """apply_config() debe escribir en pipeline._config todos los campos DSP+Gain.

    Si se agrega un campo nuevo a DSPConfig o GainConfig y no se actualiza
    apply_config() ni _capture(), este test fallara con el nombre del campo.
    """
    src = AppConfig()
    # Asignar valores distintos al default en cada campo
    src.dsp.agc_preset                    = "fast"
    src.dsp.blanker_enabled               = False
    src.dsp.blanker_frame                 = 20.0
    src.dsp.blanker_mini                  = 5.0
    src.dsp.bandpass_pre_enabled          = False
    src.dsp.bandpass_post_enabled         = False
    src.dsp.filter_order                  = 2
    src.dsp.anf_enabled                   = False
    src.dsp.anf_threshold                 = 5.0
    src.dsp.anf_depth                     = 0.5
    src.dsp.noise_enabled                 = False
    src.dsp.noise_mode                    = "mcra"
    src.dsp.noise_alpha                   = 0.5
    src.dsp.noise_floor                   = 0.15
    src.dsp.noise_smooth                  = 0.90
    src.dsp.noise_attack                  = 0.60
    src.dsp.squelch_enabled               = True
    src.dsp.squelch_threshold             = 0.30
    src.dsp.squelch_hold_ms               = 300.0
    src.dsp.exciter_enabled               = True
    src.dsp.exciter_drive                 = 5.0
    src.dsp.exciter_mix                   = 0.5
    src.dsp.presence_enabled              = False
    src.dsp.presence_freq                 = 1500.0
    src.dsp.presence_db                   = 3.0
    src.dsp.presence_q                    = 1.0
    src.dsp.body_freq                     = 400.0
    src.dsp.body_db                       = 4.0
    src.dsp.pitch_shift_hz                = 100.0
    src.dsp.perceptual_floor_enabled      = True
    src.dsp.perceptual_floor_boost        = 1.0
    src.dsp.perceptual_floor_center       = 400.0
    src.dsp.perceptual_floor_rolloff_hz   = 2500.0
    src.dsp.perceptual_floor_rolloff_depth = 0.40
    src.dsp.post_filter_enabled           = True
    src.dsp.post_filter_strength          = 2.0
    src.dsp.pitch_enhance_enabled         = True
    src.dsp.pitch_enhance_strength        = 0.5
    src.dsp.noise_fading_comp             = True
    src.gain.input_gain_db                = 3.0
    src.gain.output_gain_db               = -2.0
    src.gain.peak_limit_db                = -6.0

    pipeline = ProcessingPipeline(AppConfig())
    pipeline.apply_config(src)

    failed = []
    for fname in _all_dsp_fields():
        expected = getattr(src.dsp, fname)
        got      = getattr(pipeline._config.dsp, fname)
        if expected != got:
            failed.append(f"  DSPConfig.{fname}: esperado={expected!r}, obtenido={got!r}")

    for fname in _all_gain_fields():
        expected = getattr(src.gain, fname)
        got      = getattr(pipeline._config.gain, fname)
        if expected != got:
            failed.append(f"  GainConfig.{fname}: esperado={expected!r}, obtenido={got!r}")

    assert not failed, "apply_config() no trasfiere:\n" + "\n".join(failed)
    print("apply_config() transfiere todos los campos  OK")


# ---------------------------------------------------------------------- #
# 3. CRUD de presets                                                      #
# ---------------------------------------------------------------------- #

def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        app = AppConfig()
        app.dsp.noise_alpha      = 0.5
        app.dsp.exciter_enabled  = True
        app.gain.input_gain_db   = 3.0

        mgr.save("Mi Preset", app)
        assert mgr.exists("Mi Preset")
        assert "Mi Preset" in mgr.list_names()

        app2 = AppConfig()
        mgr.load_into("Mi Preset", app2)
        assert app2.dsp.noise_alpha     == 0.5
        assert app2.dsp.exciter_enabled == True
        assert app2.gain.input_gain_db  == 3.0
        print("Save / load roundtrip            OK")


def test_rename():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        mgr.save("Viejo Nombre", AppConfig())
        mgr.rename("Viejo Nombre", "Nuevo Nombre")
        assert not mgr.exists("Viejo Nombre")
        assert mgr.exists("Nuevo Nombre")
        assert "Nuevo Nombre" in mgr.list_names()
        assert "Viejo Nombre" not in mgr.list_names()
        print("Rename                           OK")


def test_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        mgr.save("A Borrar", AppConfig())
        assert mgr.exists("A Borrar")
        mgr.delete("A Borrar")
        assert not mgr.exists("A Borrar")
        assert "A Borrar" not in mgr.list_names()
        print("Delete                           OK")


def test_multiple_presets_list_order():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        for name in ["Zeta", "Alpha", "Beta"]:
            mgr.save(name, AppConfig())
        names = mgr.list_names()
        assert names == sorted(names), f"Lista no esta ordenada: {names}"
        print("List ordenado alfabeticamente    OK")


def test_load_applies_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        app = AppConfig()
        app.dsp.mode = RadioMode.AM
        mgr.save("AM Preset", app)

        app2 = AppConfig()
        app2.dsp.mode = RadioMode.SSB
        mgr.load_into("AM Preset", app2)
        assert app2.dsp.mode == RadioMode.AM
        print("load_into aplica RadioMode       OK")


# ---------------------------------------------------------------------- #
# 4. Claves ausentes -> defaults de fabrica (no el valor vivo del config)  #
# ---------------------------------------------------------------------- #

def test_missing_keys_use_factory_defaults():
    """Un preset viejo sin las claves nuevas debe cargarlas en su DEFAULT.

    Regresion del bug recurrente: el fallback de `d.get()` era el valor VIVO del
    config, asi que un campo agregado despues del preset heredaba lo que hubiera
    en la sesion -> nunca coincidia con el snapshot normalizado -> '(modificado)'
    espurio permanente. Ver CLAUDE.md (v1.8.2 / v1.9).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        # Preset "viejo": solo un puñado de claves, sin los campos recientes
        old = {
            "name": "Viejo",
            "version": 1,
            "dsp": {"mode": "AM", "noise_alpha": 0.5},
            "gain": {"input_gain_db": 3.0},
        }
        with open(os.path.join(tmpdir, "Viejo.json"), "w", encoding="utf-8") as f:
            json.dump(old, f)

        dflt = DSPConfig()
        # Config "sucio": valores no-default en los campos ausentes del preset
        app = AppConfig()
        app.dsp.voice_leveler_gate_voice = not dflt.voice_leveler_gate_voice
        app.dsp.voice_leveler_release_ms = 400.0
        app.dsp.noise_hf_boost           = 1.2
        app.dsp.noise_mcra_window_ms     = 250.0
        app.dsp.post_filter_strength     = 6.0
        app.gain.output_gain_db          = -4.0

        mgr.load_into("Viejo", app)

        # Lo que el preset SI trae
        assert app.dsp.mode == RadioMode.AM
        assert app.dsp.noise_alpha == 0.5
        assert app.gain.input_gain_db == 3.0
        # Lo ausente vuelve a fabrica, no conserva el valor vivo
        failed = []
        for fname in ("voice_leveler_gate_voice", "voice_leveler_release_ms",
                      "noise_hf_boost", "noise_mcra_window_ms", "post_filter_strength"):
            expected = getattr(dflt, fname)
            got      = getattr(app.dsp, fname)
            if expected != got:
                failed.append(f"  DSPConfig.{fname}: esperado={expected!r}, obtenido={got!r}")
        if app.gain.output_gain_db != GainConfig().output_gain_db:
            failed.append(f"  GainConfig.output_gain_db: obtenido={app.gain.output_gain_db!r}")
        assert not failed, "Claves ausentes no usan el default:\n" + "\n".join(failed)

        # Y por lo tanto NO debe marcar '(modificado)' recien cargado
        assert mgr.matches("Viejo", app), "'(modificado)' espurio tras cargar preset incompleto"
        print("Claves ausentes -> default       OK")


def test_missing_bandpass_mode_uses_default():
    """Un modo ausente en bandpass_limits vuelve al default, no queda el vivo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PresetManager(tmpdir)
        old = {
            "name": "SoloAM",
            "version": 1,
            "dsp": {"bandpass_limits": {"AM": [400, 4000]}},
            "gain": {},
        }
        with open(os.path.join(tmpdir, "SoloAM.json"), "w", encoding="utf-8") as f:
            json.dump(old, f)

        app = AppConfig()
        app.dsp.bandpass_limits[RadioMode.SSB]     = (100, 2000)
        app.dsp.bandpass_out_limits[RadioMode.AM]  = (500, 4500)

        mgr.load_into("SoloAM", app)

        dflt = DSPConfig()
        assert app.dsp.bandpass_limits[RadioMode.AM] == (400, 4000)
        assert app.dsp.bandpass_limits[RadioMode.SSB] == dflt.bandpass_limits[RadioMode.SSB]
        assert app.dsp.bandpass_out_limits == dflt.bandpass_out_limits
        print("Bandpass: modo ausente -> default OK")


if __name__ == "__main__":
    test_capture_covers_all_dsp_fields()
    test_capture_covers_all_gain_fields()
    test_apply_config_covers_all_fields()
    test_save_load_roundtrip()
    test_rename()
    test_delete()
    test_multiple_presets_list_order()
    test_load_applies_mode()
    test_missing_keys_use_factory_defaults()
    test_missing_bandpass_mode_uses_default()
    print()
    print("Todos los tests pasaron.")
