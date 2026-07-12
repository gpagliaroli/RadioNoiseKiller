import sys
import os
# UN solo thread para OpenBLAS/MKL (antes de importar numpy). Los arrays del
# DSP son diminutos (481-4096 elementos): el multihilo BLAS nunca ayuda y sus
# hilos hacen busy-waiting entre operaciones — en CPUs débiles (AMD A6, 2
# cores) ese spinning aparecía como ~100% de CPU.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RadioNoiseKiller")
    app.setApplicationVersion("1.4.0")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
