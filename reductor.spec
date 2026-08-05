# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)
SRC  = ROOT / "src"

# La app es QWidgets puro (QPainter para VU/espectro): estos módulos Qt se
# cuelan como dependencias de los hooks de PySide6 pero nunca se importan.
QT_EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtVirtualKeyboard", "PySide6.QtMultimedia",
]

# Basura Qt que igual entra al bundle vía binarios/datas de los hooks
# (~45 MB): renderer OpenGL por software, DLLs de Quick/Qml/Pdf/Network,
# plugins de esos módulos, formatos de imagen (Qt6Gui trae PNG integrado)
# y traducciones de Qt (la app no instala QTranslator).
_QT_JUNK = (
    "opengl32sw", "qdirect2d",
    "qt6quick", "qtquick", "qt6qml", "qtqml",
    "qt6pdf", "qtpdf", "qt6opengl", "qtopengl",
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

a = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
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
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib", "tkinter", "onnxruntime"]
             + QT_EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.binaries = sin_basura_qt(a.binaries)
a.datas    = sin_basura_qt(a.datas)

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
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "Images" / "RNK.ico"),
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
