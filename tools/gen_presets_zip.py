"""
Regenera Presets/Presets.zip a partir de los presets de fábrica versionados.

El zip es el paquete que se distribuye al usuario final (el bundle NO trae los
presets: `presets_dir()` crea una carpeta vacía junto al .exe). Se arma a mano,
así que se desactualiza solo — correr este script cada vez que se agrega, quita
o ajusta un preset de fábrica, y antes de publicar un release.

Uso:
    .venv\\Scripts\\python.exe tools\\gen_presets_zip.py     (Windows)
    .venv/bin/python        tools/gen_presets_zip.py        (Linux/Pi)

El zip es DETERMINISTA (nombres ordenados y timestamp fijo): regenerarlo sin
cambios reales no produce diff, que es lo que hace tolerable versionar un
binario. Verifica además que cada JSON parsee y que su campo "name" coincida
con el nombre de archivo esperado.
"""
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRESETS_DIR = os.path.join(ROOT, "Presets")
ZIP_PATH = os.path.join(PRESETS_DIR, "Presets.zip")

# Timestamp fijo (mínimo que admite el formato zip) para que el binario sea
# reproducible y no genere diff por la fecha de modificación.
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def _safe_filename(name: str) -> str:
    """Misma normalización que PresetManager._safe_filename."""
    s = re.sub(r"[^\w\- ]", "_", name).strip()
    s = re.sub(r"\s+", "_", s)
    return s or "preset"


def main() -> int:
    files = sorted(f for f in os.listdir(PRESETS_DIR) if f.lower().endswith(".json"))
    if not files:
        print(f"ERROR: no hay presets en {PRESETS_DIR}")
        return 1

    problems = []
    for fname in files:
        path = os.path.join(PRESETS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"  {fname}: no parsea ({e})")
            continue
        name = data.get("name")
        if not name:
            problems.append(f"  {fname}: sin campo 'name'")
        elif _safe_filename(name) + ".json" != fname:
            problems.append(
                f"  {fname}: el campo 'name' ({name!r}) no corresponde al archivo")
    if problems:
        print("ERROR: presets invalidos:\n" + "\n".join(problems))
        return 1

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for fname in files:
            info = zipfile.ZipInfo(fname, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(PRESETS_DIR, fname), "rb") as f:
                z.writestr(info, f.read())

    size_kb = os.path.getsize(ZIP_PATH) / 1024
    print(f"Presets.zip regenerado ({len(files)} presets, {size_kb:.1f} KB):")
    for fname in files:
        print(f"  {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
