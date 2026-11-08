"""
Lanzador de escritorio para Linux / Raspberry Pi: un archivo .desktop en
~/.local/share/applications para que la app aparezca en el menú con su ícono.

    ./RadioNoiseKiller/RadioNoiseKiller --install-desktop     (paquete)
    ./run --install-desktop                                   (desde el fuente)
    ... --uninstall-desktop                                   (lo quita)

main.py atiende estos flags ANTES de crear el QApplication y sale: no hace falta
display. Sin Qt a propósito (import barato).

Desde el fuente, Exec apunta al script `run` del repo y no a src/main.py: así el
lanzador pasa por el .venv y lo crea si falta.
"""
import os
import sys

DESKTOP_ID = "radionoisekiller"          # nombre del archivo y app_id en Wayland
FILE_NAME = DESKTOP_ID + ".desktop"

INSTALL_FLAG = "--install-desktop"
UNINSTALL_FLAG = "--uninstall-desktop"


def applications_dir() -> str:
    """Carpeta de lanzadores del usuario según XDG ($XDG_DATA_HOME/applications)."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "applications")


def default_targets() -> "tuple[str, str]":
    """(ejecutable, ícono) absolutos para el modo actual: paquete o fuente."""
    if getattr(sys, "frozen", False):
        from utils import resource_path
        return (os.path.abspath(sys.executable),
                os.path.abspath(resource_path(os.path.join("Images", "RNK_ico.png"))))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return (os.path.join(root, "run"), os.path.join(root, "Images", "RNK_ico.png"))


def _quote_exec(path: str) -> str:
    """Comillas para la clave Exec (spec Desktop Entry): ruta con espacios incluida."""
    esc = path.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{esc}"'


def desktop_text(exec_path: str, icon_path: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=RadioNoiseKiller",
        "GenericName=Radio noise reduction",
        "GenericName[es]=Reducción de ruido para radio",
        "Comment=Real-time noise reduction for AM/SSB radio audio",
        "Comment[es]=Reducción de ruido en tiempo real para audio de radio AM/SSB",
        f"Exec={_quote_exec(exec_path)}",
        f"Icon={icon_path}",
        "Terminal=false",
        "Categories=AudioVideo;Audio;HamRadio;",
        "Keywords=radio;ham;noise;SSB;AM;",
        "",
    ])


def install(exec_path: str, icon_path: str, apps_dir: "str | None" = None) -> str:
    """Escribe el .desktop y devuelve su ruta."""
    apps_dir = apps_dir or applications_dir()
    os.makedirs(apps_dir, exist_ok=True)
    path = os.path.join(apps_dir, FILE_NAME)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(desktop_text(exec_path, icon_path))
    os.chmod(path, 0o755)    # algunos escritorios (GNOME) piden el bit para confiar en él
    return path


def uninstall(apps_dir: "str | None" = None) -> "str | None":
    """Borra el .desktop. Devuelve su ruta si existía, None si no había nada."""
    path = os.path.join(apps_dir or applications_dir(), FILE_NAME)
    if not os.path.exists(path):
        return None
    os.remove(path)
    return path


def handle_cli(argv: list) -> "int | None":
    """Atiende --install-desktop / --uninstall-desktop. None = seguir con la app."""
    if INSTALL_FLAG not in argv and UNINSTALL_FLAG not in argv:
        return None
    if not sys.platform.startswith("linux"):
        print("El lanzador de escritorio es sólo para Linux / Raspberry Pi.")
        return 1
    try:
        if UNINSTALL_FLAG in argv:
            path = uninstall()
            print(f"Lanzador eliminado: {path}" if path else "No había lanzador instalado.")
            return 0
        exec_path, icon_path = default_targets()
        path = install(exec_path, icon_path)
    except OSError as e:
        print(f"No se pudo escribir el lanzador: {e}", file=sys.stderr)
        return 1
    print(f"Lanzador instalado: {path}")
    print(f"  Ejecuta: {exec_path}")
    print("Aparece en el menú de aplicaciones (en algunos escritorios, tras cerrar sesión).")
    print("Si movés la carpeta de la app, volvé a correr --install-desktop.")
    return 0
