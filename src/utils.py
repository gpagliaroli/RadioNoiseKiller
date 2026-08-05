"""
utils — rutas de recursos compatibles con desarrollo y bundle PyInstaller.

En un bundle PyInstaller los archivos de datos se extraen a sys._MEIPASS (directorio
temporal). resource_path() resuelve rutas relativas a ese directorio en producción
y a la raíz del proyecto en desarrollo.

settings.json se escribe en un directorio con permisos de escritura (junto al .exe
en bundle, raíz del proyecto en desarrollo) — nunca dentro de _MEIPASS que es de
solo lectura.

La variable de entorno RNK_DATA_DIR redirige TODOS los datos escribibles
(settings.json, Presets/, PerfilesRuido/, Grabaciones/) a otra carpeta. La usan
los tests headless para no tocar los datos reales del usuario: los presets de
fábrica están afinados en el aire y no son regenerables. Sin la variable el
comportamiento es idéntico al de siempre.
"""
import sys
import os

DATA_DIR_ENV = "RNK_DATA_DIR"


def resource_path(relative: str) -> str:
    """Resuelve rutas a recursos tanto en desarrollo como en bundle PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, relative)


def data_dir() -> str:
    """Directorio base de los datos escribibles (junto al .exe en bundle, raíz del
    proyecto en desarrollo). RNK_DATA_DIR lo redirige — ver el docstring del módulo."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    if hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_subdir(name: str) -> str:
    path = os.path.join(data_dir(), name)
    os.makedirs(path, exist_ok=True)
    return path


def settings_path() -> str:
    """Ruta al archivo settings.json (junto al .exe en bundle, en raíz en desarrollo)."""
    return os.path.join(data_dir(), "settings.json")


def noise_profiles_dir() -> str:
    """Ruta a la carpeta PerfilesRuido/ (junto al .exe en bundle, en raíz en
    desarrollo). La crea si no existe."""
    return _data_subdir("PerfilesRuido")


def recordings_dir() -> str:
    """Ruta a la carpeta Grabaciones/ (junto al .exe en bundle, en raíz en
    desarrollo). La crea si no existe."""
    return _data_subdir("Grabaciones")


def presets_dir() -> str:
    """Ruta a la carpeta Presets/ (junto al .exe en bundle, en raíz en desarrollo).
    La crea si no existe."""
    return _data_subdir("Presets")


def seed_factory_presets() -> int:
    """Copia los presets de fábrica del bundle a la carpeta Presets/ del usuario si
    está vacía. Devuelve cuántos copió.

    Hace falta porque las dos carpetas NO son la misma en un bundle: los recursos
    empaquetados viven en `_MEIPASS` (subcarpeta `_internal/`) y la carpeta de
    presets es escribible, junto al ejecutable. Sin este paso el usuario que baja
    el release se encuentra la lista de presets VACÍA — pasó en la v2.0, donde
    además el zip de Linux ni siquiera traía la carpeta.

    Solo copia si el destino no tiene ningún .json: así respeta a quien borró
    alguno a propósito, y no pisa los ajustes del usuario en cada arranque.
    En desarrollo origen y destino son la misma carpeta y no hace nada.
    """
    dst = presets_dir()
    src = resource_path("Presets")
    if os.path.abspath(src) == os.path.abspath(dst) or not os.path.isdir(src):
        return 0
    if any(f.lower().endswith(".json") for f in os.listdir(dst)):
        return 0
    import shutil
    n = 0
    for name in sorted(os.listdir(src)):
        if name.lower().endswith(".json"):
            try:
                shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
                n += 1
            except OSError:
                pass
    return n


