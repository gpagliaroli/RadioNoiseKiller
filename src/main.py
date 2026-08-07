import sys
import os
# UN solo thread para OpenBLAS/MKL (antes de importar numpy). Los arrays del
# DSP son diminutos (481-4096 elementos): el multihilo BLAS nunca ayuda y sus
# hilos hacen busy-waiting entre operaciones — en CPUs débiles (AMD A6, 2
# cores) ese spinning aparecía como ~100% de CPU.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RadioNoiseKiller")
    app.setApplicationVersion("2.1.0")
    icon_path = resource_path(os.path.join("Images", "RNK_ico.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
