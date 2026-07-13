"""Runtime hook (solo bundle Linux): decoraciones de ventana bajo Wayland.

En GNOME, Qt elige el plugin de decoración "adwaita", que depende de
libQt6Svg y libQt6DBus. Si no puede cargarlo NO cae a "bradient": la
ventana queda sin barra de título ("Could not create decoration from
factory!"). Forzamos "bradient", cuyas dependencias son exactamente las
mismas que las del plugin de plataforma wayland (si la app se ve, la
decoración carga). setdefault: respeta un override del usuario.
"""
import os

os.environ.setdefault("QT_WAYLAND_DECORATION", "bradient")
