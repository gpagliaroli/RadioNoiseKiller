"""
utils — rutas de recursos compatibles con desarrollo y bundle PyInstaller.

En un bundle PyInstaller los archivos de datos se extraen a sys._MEIPASS (directorio
temporal). resource_path() resuelve rutas relativas a ese directorio en producción
y a la raíz del proyecto en desarrollo.

settings.json se escribe en un directorio con permisos de escritura (junto al .exe
en bundle, raíz del proyecto en desarrollo) — nunca dentro de _MEIPASS que es de
solo lectura.
"""
import sys
import os


def resource_path(relative: str) -> str:
    """Resuelve rutas a recursos tanto en desarrollo como en bundle PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, relative)


def settings_path() -> str:
    """Ruta al archivo settings.json (junto al .exe en bundle, en raíz en desarrollo)."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(os.path.dirname(sys.executable), "settings.json")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "settings.json")


def noise_profiles_dir() -> str:
    """Ruta a la carpeta PerfilesRuido/ (junto al .exe en bundle, en raíz en
    desarrollo). La crea si no existe."""
    if hasattr(sys, "_MEIPASS"):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "PerfilesRuido")
    os.makedirs(path, exist_ok=True)
    return path


def recordings_dir() -> str:
    """Ruta a la carpeta Grabaciones/ (junto al .exe en bundle, en raíz en
    desarrollo). La crea si no existe."""
    if hasattr(sys, "_MEIPASS"):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "Grabaciones")
    os.makedirs(path, exist_ok=True)
    return path


def presets_dir() -> str:
    """Ruta a la carpeta Presets/ (junto al .exe en bundle, en raíz en desarrollo).
    La crea si no existe."""
    if hasattr(sys, "_MEIPASS"):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "Presets")
    os.makedirs(path, exist_ok=True)
    return path


