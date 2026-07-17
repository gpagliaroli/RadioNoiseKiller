"""
NoiseProfileManager — guarda, carga, elimina y renombra perfiles de ruido
con nombre ("40m casa", "20m campo", ...).

Cada perfil es un archivo .json en la carpeta PerfilesRuido/:
  {"name": "...", "version": 1, "sample_rate": 48000, "fft_n": 960,
   "learned_frames": N, "created": "...", "noise_mag": [floats]}

El perfil guarda la curva de magnitud espectral del ruido tal como la
aprendió el NoiseProfiler. Si al cargar el fft_n difiere del actual
(cambió el tamaño de bloque), el profiler interpola en frecuencia —
un piso de ruido es una curva suave y la interpolación es transparente.
"""
import datetime
import json
import os
import re


class NoiseProfileManager:
    VERSION = 1

    def __init__(self, directory: str):
        self._dir = directory
        os.makedirs(directory, exist_ok=True)

    # ------------------------------------------------------------------ #
    # API publica                                                          #
    # ------------------------------------------------------------------ #

    def list_names(self) -> list:
        """Nombres de perfiles ordenados alfabeticamente."""
        names = []
        for fname in sorted(os.listdir(self._dir)):
            if fname.lower().endswith(".json"):
                try:
                    data = self._read_file(os.path.join(self._dir, fname))
                    names.append(str(data["name"]))
                except Exception:
                    pass
        return names

    def save(self, name: str, profile: dict) -> None:
        """Guarda un perfil (dict de pipeline.get_noise_profile_data())."""
        data = {
            "name": name,
            "version": self.VERSION,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            **profile,
        }
        with open(self._path_for(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self, name: str) -> dict:
        """Devuelve el dict del perfil (noise_mag, fft_n, learned_frames, ...)."""
        return self._read_file(self._path_for(name))

    def delete(self, name: str) -> None:
        path = self._path_for(name)
        if os.path.exists(path):
            os.remove(path)

    def rename(self, old_name: str, new_name: str) -> None:
        old_path = self._path_for(old_name)
        new_path = self._path_for(new_name)
        if not os.path.exists(old_path):
            raise FileNotFoundError(f"Perfil '{old_name}' no encontrado")
        data = self._read_file(old_path)
        data["name"] = new_name
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.remove(old_path)

    def exists(self, name: str) -> bool:
        return os.path.exists(self._path_for(name))

    # ------------------------------------------------------------------ #
    # Internos                                                             #
    # ------------------------------------------------------------------ #

    def _path_for(self, name: str) -> str:
        return os.path.join(self._dir, self._safe_filename(name) + ".json")

    @staticmethod
    def _safe_filename(name: str) -> str:
        s = re.sub(r"[^\w\- ]", "_", name).strip()
        s = re.sub(r"\s+", "_", s)
        return s or "perfil"

    @staticmethod
    def _read_file(path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
