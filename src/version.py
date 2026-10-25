"""Versión de la aplicación: ÚNICA fuente (la leen main.py, el título de la ventana
y el chequeo de actualizaciones). Al hacer un release se cambia sólo acá."""
APP_VERSION = "2.7.0"


def display_version(version: str = APP_VERSION) -> str:
    """'2.6.0' -> '2.6' ; '2.6.1' -> '2.6.1' (el parche 0 no se muestra)."""
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) == 3 and parts[2] == "0" else version
