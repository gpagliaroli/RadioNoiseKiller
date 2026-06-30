# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para Linux (x86_64).
Detecta libportaudio automáticamente y la incluye en el bundle.
"""
import os
import subprocess
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)
SRC  = ROOT / "src"


def find_shared_lib(name: str) -> str | None:
    """Busca una librería compartida con ldconfig y devuelve su ruta."""
    try:
        result = subprocess.run(
            ["ldconfig", "-p"], capture_output=True, text=True, check=False
        )
        for line in result.stdout.splitlines():
            if name in line and "=>" in line:
                path = line.split("=>")[1].strip()
                if os.path.exists(path):
                    return path
    except FileNotFoundError:
        pass
    # Fallback: rutas comunes
    for candidate in [
        f"/usr/lib/x86_64-linux-gnu/{name}.so.2",
        f"/usr/lib/{name}.so.2",
        f"/usr/local/lib/{name}.so.2",
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


extra_binaries = []
portaudio = find_shared_lib("libportaudio")
if portaudio:
    extra_binaries.append((portaudio, "."))
else:
    print("WARNING: libportaudio no encontrado — el audio puede no funcionar")

a = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(SRC)],
    binaries=extra_binaries,
    datas=[],
    hiddenimports=[
        "sounddevice",
        "cffi",
        "_cffi_backend",
        "scipy.signal",
        "scipy.ndimage",
        "scipy.special._ufuncs",
        "numpy",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib", "tkinter", "onnxruntime"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ReductorRuidoRadio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ReductorRuidoRadio",
)
