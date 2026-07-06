"""
Runtime hook PyInstaller (Linux): aísla GIO del sistema.

El bundle incluye su propia libglib (la del runner de build). Los módulos GIO
del sistema (gvfs, etc.) están compilados contra la glib del host — si es más
nueva, cargarlos dentro de la glib empaquetada produce errores de símbolos al
arrancar ("undefined symbol: g_variant_builder_init_static"). Son inofensivos
(solo se pierde integración gvfs en diálogos de archivo, que la app no usa),
pero ensucian el shell. Apuntar GIO_MODULE_DIR a un directorio inexistente
dentro del bundle evita que GIO intente cargarlos.
"""
import os
import sys

if sys.platform.startswith("linux"):
    os.environ["GIO_MODULE_DIR"] = os.path.join(
        getattr(sys, "_MEIPASS", "."), "gio-modules-disabled"
    )
