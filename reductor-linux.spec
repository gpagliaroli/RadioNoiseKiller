# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para Linux — x86_64 y ARM64 (Raspberry Pi).
Detecta libportaudio automáticamente via ldconfig; fallback por arquitectura.
"""
import os
import platform
import subprocess
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)
SRC  = ROOT / "src"

ARCH = platform.machine()   # "x86_64", "aarch64", "armv7l", …

# La app es QWidgets puro: estos módulos Qt se cuelan como dependencias de
# los hooks de PySide6 pero nunca se importan. (No excluir QtDBus — la
# integración de plataforma de Qt en Linux lo necesita.)
QT_EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtVirtualKeyboard", "PySide6.QtMultimedia",
]

# Basura Qt que igual entra al bundle vía binarios/datas de los hooks:
# libs de Quick/Qml/Pdf/Network, plugins de esos módulos, formatos de
# imagen (Qt6Gui trae PNG integrado) y traducciones de Qt (la app no
# instala QTranslator).
# OJO: NO filtrar libQt6OpenGL en Linux — el plugin de decoraciones de
# Qt Wayland (bradient) depende de ella; sin la lib el plugin no carga y
# la ventana queda SIN barra de título bajo Wayland ("Could not create
# decoration from factory!" en consola — reportado en la notebook Ubuntu).
_QT_JUNK = (
    "qt6quick", "qtquick", "qt6qml", "qtqml",
    "qt6pdf", "qtpdf",
    "qt6network", "qtnetwork", "qt6svg", "qtsvg",
    "qt6virtualkeyboard", "qtvirtualkeyboard",
    "plugins/imageformats", "plugins/tls", "plugins/qml",
    "plugins/virtualkeyboard", "plugins/networkinformation",
    "plugins/iconengines", "pyside6/translations",
)


def sin_basura_qt(toc):
    """Filtra entradas de PySide6 que la app no usa (ver _QT_JUNK)."""
    out = []
    for entry in toc:
        dest = entry[0].replace("\\", "/").lower()
        if any(pat in dest for pat in _QT_JUNK):
            continue
        out.append(entry)
    return out


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

    # Fallback según arquitectura
    arch_dir = {
        "x86_64":  "x86_64-linux-gnu",
        "aarch64": "aarch64-linux-gnu",
        "armv7l":  "arm-linux-gnueabihf",
    }.get(ARCH, ARCH + "-linux-gnu")

    for candidate in [
        f"/usr/lib/{arch_dir}/{name}.so.2",
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
    print(f"INFO: libportaudio encontrado en {portaudio} ({ARCH})")
else:
    print(f"WARNING: libportaudio no encontrado para {ARCH} — el audio puede no funcionar")

a = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(SRC)],
    binaries=extra_binaries,
    # Los presets de fábrica viajan como recurso; en el primer arranque
    # utils.seed_factory_presets() los copia a la carpeta escribible
    # (_MEIPASS y la carpeta Presets/ del usuario NO son la misma).
    datas=[(str(ROOT / "Images" / "RNK_ico.png"), "Images")]
          + [(str(p), "Presets") for p in sorted((ROOT / "Presets").glob("*.json"))],
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
    runtime_hooks=[str(ROOT / "pyi_rth_gio.py"),
                   str(ROOT / "pyi_rth_portaudio.py"),
                   str(ROOT / "pyi_rth_wayland.py")],
    excludes=["torch", "tensorflow", "matplotlib", "tkinter", "onnxruntime"]
             + QT_EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)

# Excluir libasound del bundle: la libasound empaquetada (la del runner de
# build) no puede cargar los plugins ALSA del host (pulse/pipewire/default —
# rutas y versiones distintas), y la enumeración de PortAudio queda solo con
# dispositivos hw:. Al excluirla, el linker usa la libasound del sistema
# (ABI estable, presente en cualquier Linux con audio) y los dispositivos
# virtuales vuelven a aparecer.
a.binaries = [b for b in a.binaries
              if not os.path.basename(b[0]).startswith("libasound.")]

a.binaries = sin_basura_qt(a.binaries)
a.datas    = sin_basura_qt(a.datas)

# Los hooks de PyInstaller NO recolectan los plugins de decoración ni de
# shell-integration de Qt Wayland (las carpetas quedan vacías en el bundle,
# también pasaba en v1.4). Sin libbradient.so la ventana no tiene barra de
# título bajo Wayland: "Could not create decoration from factory!".
# Se agregan a mano desde el wheel de PySide6.
import PySide6
_qt_plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
for _cat in ("wayland-decoration-client", "wayland-shell-integration"):
    _d = _qt_plugins / _cat
    if _d.is_dir():
        for _so in sorted(_d.glob("*.so")):
            a.binaries.append(
                (f"PySide6/Qt/plugins/{_cat}/{_so.name}", str(_so), "BINARY"))
            print(f"INFO: plugin wayland agregado a mano: {_cat}/{_so.name}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RadioNoiseKiller",
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
    name="RadioNoiseKiller",
)
