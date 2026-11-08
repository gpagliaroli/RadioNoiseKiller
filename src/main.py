import sys
import os
# UN solo thread para OpenBLAS/MKL (antes de importar numpy). Los arrays del
# DSP son diminutos (481-4096 elementos): el multihilo BLAS nunca ayuda y sus
# hilos hacen busy-waiting entre operaciones — en CPUs débiles (AMD A6, 2
# cores) ese spinning aparecía como ~100% de CPU.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

# --install-desktop / --uninstall-desktop (Linux/Pi): escribe o quita el lanzador
# del menú y sale, sin crear ventana (ni necesitar display).
import desktop_entry                      # noqa: E402  (sin Qt: import barato)
_rc = desktop_entry.handle_cli(sys.argv[1:])
if _rc is not None:
    sys.exit(_rc)

# Escala de la interfaz elegida por el usuario. QT_SCALE_FACTOR solo tiene efecto
# si esta definida ANTES de crear el QApplication, asi que la leemos del
# settings.json aca — antes incluso de importar Qt. setdefault: si el usuario ya
# la exporto a mano (o el sistema la definio), su valor manda.
from config import read_ui_scale          # noqa: E402  (sin Qt: import barato)
from utils import settings_path           # noqa: E402
_ui_scale = read_ui_scale(settings_path())
if _ui_scale != 1.0:
    os.environ.setdefault("QT_SCALE_FACTOR", str(_ui_scale))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.main_window import MainWindow
from utils import resource_path
from version import APP_VERSION


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RadioNoiseKiller")
    app.setApplicationVersion(APP_VERSION)
    # En Wayland es el app_id: asocia la ventana con el lanzador instalado
    # (ícono en el dock/panel). Sin efecto en Windows.
    app.setDesktopFileName(desktop_entry.DESKTOP_ID)
    icon_path = resource_path(os.path.join("Images", "RNK_ico.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    rc = app.exec()
    # Si un stream quedó colgado en el driver (ver audio/stream.py), el atexit
    # de sounddevice llamaría a Pa_StopStream/Pa_Terminate sobre él y el proceso
    # no terminaría nunca — la ventana ya cerrada y el .exe vivo en segundo
    # plano. La configuración ya se guardó en closeEvent: salir sin handlers.
    from audio.stream import abandoned_streams
    if abandoned_streams():
        sys.stdout.flush()
        os._exit(rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
