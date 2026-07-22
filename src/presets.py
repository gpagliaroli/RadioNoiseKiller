"""
PresetManager — Guarda, carga, elimina y renombra presets de DSP/Gain.

Cada preset es un archivo .json en la carpeta Presets/:
  {"name": "...", "version": 1, "dsp": {...}, "gain": {...}}

Solo DSPConfig y GainConfig se persisten. AudioConfig (dispositivos) y
WindowConfig (posicion/zoom) son especificos del entorno y no forman parte
del preset.
"""
import json
import os
import re
from config import AppConfig, RadioMode


class PresetManager:
    VERSION = 1

    def __init__(self, directory: str):
        self._dir = directory
        os.makedirs(directory, exist_ok=True)

    # ------------------------------------------------------------------ #
    # API publica                                                          #
    # ------------------------------------------------------------------ #

    def list_names(self) -> list:
        """Retorna los nombres de presets ordenados alfabeticamente."""
        names = []
        for fname in sorted(os.listdir(self._dir)):
            if fname.lower().endswith(".json"):
                try:
                    data = self._read_file(os.path.join(self._dir, fname))
                    names.append(str(data["name"]))
                except Exception:
                    pass
        return names

    def save(self, name: str, config: AppConfig) -> None:
        """Guarda DSP+Gain actual del config como preset con ese nombre."""
        path = self._path_for(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._capture(name, config), f, indent=2, ensure_ascii=False)

    def load_into(self, name: str, config: AppConfig) -> None:
        """Carga los valores del preset en config (in-place).
        Llamar pipeline.apply_config(config) despues para aplicar en caliente."""
        data = self._read_file(self._path_for(name))
        self._apply_to_config(data, config)

    def delete(self, name: str) -> None:
        path = self._path_for(name)
        if os.path.exists(path):
            os.remove(path)

    def rename(self, old_name: str, new_name: str) -> None:
        old_path = self._path_for(old_name)
        new_path = self._path_for(new_name)
        if not os.path.exists(old_path):
            raise FileNotFoundError(f"Preset '{old_name}' no encontrado")
        data = self._read_file(old_path)
        data["name"] = new_name
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.remove(old_path)

    def exists(self, name: str) -> bool:
        return os.path.exists(self._path_for(name))

    def read(self, name: str) -> dict:
        """Dict crudo del preset guardado (para comparaciones en memoria sin re-leer disco)."""
        return self._read_file(self._path_for(name))

    def snapshot(self, name: str) -> dict:
        """(dsp, gain) NORMALIZADOS del preset: cargados en un AppConfig limpio y
        re-capturados. Compararlos contra _capture() del config actual evita falsos
        '(modificado)' cuando el JSON en disco trae claves obsoletas (campos
        eliminados del esquema, p. ej. el viejo AGC Custom) o le faltan campos
        nuevos — ambos lados pasan por el mismo _capture(). Lanza si no existe."""
        fresh = AppConfig()
        self.load_into(name, fresh)
        cap = self._capture(name, fresh)
        return {"dsp": cap["dsp"], "gain": cap["gain"]}

    def matches(self, name: str, config: AppConfig) -> bool:
        """True si los valores DSP+Gain actuales del config coinciden exactamente
        con los guardados en el preset (para mostrar '(modificado)' en la UI)."""
        try:
            saved = self.snapshot(name)
        except Exception:
            return False
        current = self._capture(name, config)
        return (saved["dsp"] == current["dsp"]
                and saved["gain"] == current["gain"])

    # ------------------------------------------------------------------ #
    # Internos                                                             #
    # ------------------------------------------------------------------ #

    def _path_for(self, name: str) -> str:
        return os.path.join(self._dir, self._safe_filename(name) + ".json")

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Convierte el nombre del preset a un nombre de archivo valido."""
        s = re.sub(r"[^\w\- ]", "_", name).strip()
        s = re.sub(r"\s+", "_", s)
        return s or "preset"

    @staticmethod
    def _read_file(path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _capture(name: str, config: AppConfig) -> dict:
        """Serializa DSPConfig + GainConfig a un diccionario."""
        dsp = config.dsp
        return {
            "name": name,
            "version": PresetManager.VERSION,
            "dsp": {
                "mode":                      dsp.mode.value,
                "agc_preset":                dsp.agc_preset,
                "blanker_enabled":           dsp.blanker_enabled,
                "blanker_frame":             dsp.blanker_frame,
                "blanker_mini":              dsp.blanker_mini,
                "bandpass_pre_enabled":      dsp.bandpass_pre_enabled,
                "bandpass_post_enabled":     dsp.bandpass_post_enabled,
                "bandpass_limits":           {m.value: list(v) for m, v in dsp.bandpass_limits.items()},
                "bandpass_out_independent":  dsp.bandpass_out_independent,
                "bandpass_out_limits":       {m.value: list(v) for m, v in dsp.bandpass_out_limits.items()},
                "filter_order":              dsp.filter_order,
                "anf_enabled":               dsp.anf_enabled,
                "anf_threshold":             dsp.anf_threshold,
                "anf_depth":                 dsp.anf_depth,
                "noise_enabled":             dsp.noise_enabled,
                "noise_mode":                dsp.noise_mode,
                "noise_alpha":               dsp.noise_alpha,
                "noise_floor":               dsp.noise_floor,
                "noise_smooth":              dsp.noise_smooth,
                "noise_attack":              dsp.noise_attack,
                "squelch_enabled":           dsp.squelch_enabled,
                "squelch_threshold":         dsp.squelch_threshold,
                "squelch_hold_ms":           dsp.squelch_hold_ms,
                "exciter_enabled":           dsp.exciter_enabled,
                "exciter_drive":             dsp.exciter_drive,
                "exciter_mix":               dsp.exciter_mix,
                "presence_enabled":          dsp.presence_enabled,
                "presence_freq":             dsp.presence_freq,
                "presence_db":               dsp.presence_db,
                "presence_q":                dsp.presence_q,
                "body_freq":                 dsp.body_freq,
                "body_db":                   dsp.body_db,
                "pitch_shift_hz":            dsp.pitch_shift_hz,
                "perceptual_floor_enabled":       dsp.perceptual_floor_enabled,
                "perceptual_floor_boost":         dsp.perceptual_floor_boost,
                "perceptual_floor_center":        dsp.perceptual_floor_center,
                "perceptual_floor_rolloff_hz":    dsp.perceptual_floor_rolloff_hz,
                "perceptual_floor_rolloff_depth": dsp.perceptual_floor_rolloff_depth,
                "post_filter_enabled":       dsp.post_filter_enabled,
                "post_filter_strength":      dsp.post_filter_strength,
                "pitch_enhance_enabled":     dsp.pitch_enhance_enabled,
                "pitch_enhance_strength":    dsp.pitch_enhance_strength,
                "noise_fading_comp":         dsp.noise_fading_comp,
                "noise_mcra_window_ms":      dsp.noise_mcra_window_ms,
                "noise_hf_boost":            dsp.noise_hf_boost,
                "noise_fading_change_db":    dsp.noise_fading_change_db,
                "noise_fading_freeze_ms":    dsp.noise_fading_freeze_ms,
                "voice_leveler_enabled":     dsp.voice_leveler_enabled,
                "voice_leveler_max_db":      dsp.voice_leveler_max_db,
                "voice_leveler_gate_voice":  dsp.voice_leveler_gate_voice,
                "voice_leveler_release_ms":  dsp.voice_leveler_release_ms,
            },
            "gain": {
                "input_gain_db":  config.gain.input_gain_db,
                "output_gain_db": config.gain.output_gain_db,
                "peak_limit_db":  config.gain.peak_limit_db,
            },
        }

    @staticmethod
    def _apply_to_config(data: dict, config: AppConfig) -> None:
        """Deserializa los valores del preset en config (in-place)."""
        d    = data.get("dsp",  {})
        g    = data.get("gain", {})
        dsp  = config.dsp
        gain = config.gain

        try:
            dsp.mode = RadioMode(d.get("mode", dsp.mode.value))
        except ValueError:
            pass
        dsp.agc_preset           = d.get("agc_preset",           dsp.agc_preset)
        if dsp.agc_preset == "custom":   # AGC Custom eliminado → preset válido
            dsp.agc_preset = "medium"
        dsp.blanker_enabled      = bool(d.get("blanker_enabled",  dsp.blanker_enabled))
        dsp.blanker_frame        = float(d.get("blanker_frame",   dsp.blanker_frame))
        dsp.blanker_mini         = float(d.get("blanker_mini",    dsp.blanker_mini))
        dsp.bandpass_pre_enabled  = bool(d.get("bandpass_pre_enabled",  dsp.bandpass_pre_enabled))
        dsp.bandpass_post_enabled = bool(d.get("bandpass_post_enabled", dsp.bandpass_post_enabled))
        for mode_str, limits in d.get("bandpass_limits", {}).items():
            try:
                dsp.bandpass_limits[RadioMode(mode_str)] = tuple(limits)
            except ValueError:
                pass
        dsp.bandpass_out_independent = bool(d.get("bandpass_out_independent",
                                                  dsp.bandpass_out_independent))
        for mode_str, limits in d.get("bandpass_out_limits", {}).items():
            try:
                dsp.bandpass_out_limits[RadioMode(mode_str)] = tuple(limits)
            except ValueError:
                pass
        dsp.filter_order    = int(d.get("filter_order",   dsp.filter_order))
        dsp.anf_enabled     = bool(d.get("anf_enabled",   dsp.anf_enabled))
        dsp.anf_threshold   = float(d.get("anf_threshold",dsp.anf_threshold))
        dsp.anf_depth       = float(d.get("anf_depth",    dsp.anf_depth))
        dsp.noise_enabled   = bool(d.get("noise_enabled", dsp.noise_enabled))
        nm = d.get("noise_mode", dsp.noise_mode)
        dsp.noise_mode      = nm if nm in ("static", "mcra") else "static"
        dsp.noise_alpha     = float(d.get("noise_alpha",  dsp.noise_alpha))
        dsp.noise_floor     = max(0.05, float(d.get("noise_floor", dsp.noise_floor)))
        dsp.noise_smooth    = float(d.get("noise_smooth", dsp.noise_smooth))
        dsp.noise_attack    = float(d.get("noise_attack", dsp.noise_attack))
        dsp.squelch_enabled    = bool(d.get("squelch_enabled",    dsp.squelch_enabled))
        dsp.squelch_threshold  = float(d.get("squelch_threshold", dsp.squelch_threshold))
        dsp.squelch_hold_ms    = float(d.get("squelch_hold_ms",   dsp.squelch_hold_ms))
        dsp.exciter_enabled    = bool(d.get("exciter_enabled",    dsp.exciter_enabled))
        dsp.exciter_drive      = float(d.get("exciter_drive",     dsp.exciter_drive))
        dsp.exciter_mix        = float(d.get("exciter_mix",       dsp.exciter_mix))
        dsp.presence_enabled   = bool(d.get("presence_enabled",   dsp.presence_enabled))
        dsp.presence_freq      = float(d.get("presence_freq",     dsp.presence_freq))
        dsp.presence_db        = float(d.get("presence_db",       dsp.presence_db))
        dsp.presence_q         = float(d.get("presence_q",        dsp.presence_q))
        dsp.body_freq          = float(d.get("body_freq",         dsp.body_freq))
        dsp.body_db            = float(d.get("body_db",           dsp.body_db))
        dsp.pitch_shift_hz     = float(d.get("pitch_shift_hz",    dsp.pitch_shift_hz))
        dsp.perceptual_floor_enabled       = bool(d.get("perceptual_floor_enabled",       dsp.perceptual_floor_enabled))
        dsp.perceptual_floor_boost         = float(d.get("perceptual_floor_boost",        dsp.perceptual_floor_boost))
        dsp.perceptual_floor_center        = float(d.get("perceptual_floor_center",       dsp.perceptual_floor_center))
        dsp.perceptual_floor_rolloff_hz    = float(d.get("perceptual_floor_rolloff_hz",   dsp.perceptual_floor_rolloff_hz))
        dsp.perceptual_floor_rolloff_depth = float(d.get("perceptual_floor_rolloff_depth",dsp.perceptual_floor_rolloff_depth))
        dsp.post_filter_enabled    = bool(d.get("post_filter_enabled",    dsp.post_filter_enabled))
        dsp.post_filter_strength   = float(d.get("post_filter_strength",  dsp.post_filter_strength))
        dsp.pitch_enhance_enabled  = bool(d.get("pitch_enhance_enabled",  dsp.pitch_enhance_enabled))
        dsp.pitch_enhance_strength = float(d.get("pitch_enhance_strength",dsp.pitch_enhance_strength))
        dsp.noise_fading_comp      = bool(d.get("noise_fading_comp",     dsp.noise_fading_comp))
        dsp.noise_mcra_window_ms = float(d.get("noise_mcra_window_ms", dsp.noise_mcra_window_ms))
        dsp.noise_hf_boost = float(d.get("noise_hf_boost", dsp.noise_hf_boost))
        dsp.noise_fading_change_db = float(d.get("noise_fading_change_db", dsp.noise_fading_change_db))
        dsp.noise_fading_freeze_ms = float(d.get("noise_fading_freeze_ms", dsp.noise_fading_freeze_ms))
        dsp.voice_leveler_enabled  = bool(d.get("voice_leveler_enabled",  dsp.voice_leveler_enabled))
        dsp.voice_leveler_max_db   = float(d.get("voice_leveler_max_db",  dsp.voice_leveler_max_db))
        dsp.voice_leveler_gate_voice = bool(d.get("voice_leveler_gate_voice", dsp.voice_leveler_gate_voice))
        dsp.voice_leveler_release_ms = float(d.get("voice_leveler_release_ms", dsp.voice_leveler_release_ms))

        gain.input_gain_db  = float(g.get("input_gain_db",  gain.input_gain_db))
        gain.output_gain_db = float(g.get("output_gain_db", gain.output_gain_db))
        gain.peak_limit_db  = float(g.get("peak_limit_db",  gain.peak_limit_db))
