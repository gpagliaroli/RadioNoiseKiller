"""
Tests del lanzador de escritorio Linux/Pi (src/desktop_entry.py), sin tocar el
~/.local/share/applications real: todo va a carpetas temporales (invariante 11).
- install/uninstall: archivo, claves, permisos, rutas con espacios.
- default_targets desde el fuente: `run` del repo y el ícono existen.
- handle_cli: sin flags no hace nada; con flags escribe/borra en XDG_DATA_HOME.
"""
import configparser
import os
import sys
import tempfile

if not os.environ.get("RNK_DATA_DIR"):
    os.environ["RNK_DATA_DIR"] = tempfile.mkdtemp(prefix="rnk_test_desktop_")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import desktop_entry as de  # noqa: E402


def _parse(path: str) -> configparser.SectionProxy:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str           # las claves del .desktop distinguen mayúsculas
    cp.read(path, encoding="utf-8")
    return cp["Desktop Entry"]


def test_install_uninstall_roundtrip():
    apps = os.path.join(tempfile.mkdtemp(prefix="rnk apps "), "applications")
    exe = "/home/pi/Mis Programas/RadioNoiseKiller/RadioNoiseKiller"
    icon = "/home/pi/Mis Programas/RadioNoiseKiller/_internal/Images/RNK_ico.png"
    path = de.install(exe, icon, apps_dir=apps)
    assert path == os.path.join(apps, "radionoisekiller.desktop")
    raw = open(path, encoding="utf-8").read()
    assert "\r" not in raw, "el .desktop va con LF"
    e = _parse(path)
    assert e["Type"] == "Application" and e["Name"] == "RadioNoiseKiller"
    assert e["Exec"] == f'"{exe}"', "Exec con espacios va entre comillas"
    assert e["Icon"] == icon and e["Terminal"] == "false"
    assert "HamRadio" in e["Categories"].split(";")
    if os.name == "posix":
        assert os.stat(path).st_mode & 0o111, "ejecutable (GNOME lo pide para confiar)"
    assert de.uninstall(apps_dir=apps) == path and not os.path.exists(path)
    assert de.uninstall(apps_dir=apps) is None, "desinstalar dos veces no rompe"
    print("Desktop: install/uninstall con rutas con espacios  OK")


def test_exec_quoting_special_chars():
    q = de._quote_exec('/opt/a "b" $c `d`\\e')
    assert q == '"/opt/a \\"b\\" \\$c \\`d\\`\\\\e"', q
    print("Desktop: escape de Exec  OK")


def test_default_targets_from_source():
    exe, icon = de.default_targets()
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    assert exe == os.path.join(root, "run") and os.path.isfile(exe), exe
    assert os.path.isabs(icon) and os.path.isfile(icon), icon
    print("Desktop: desde el fuente apunta a ./run y al ícono del repo  OK")


def test_handle_cli():
    assert de.handle_cli([]) is None and de.handle_cli(["--otra"]) is None
    if not sys.platform.startswith("linux"):
        assert de.handle_cli([de.INSTALL_FLAG]) == 1, "fuera de Linux avisa y sale con 1"
        print("Desktop: CLI fuera de Linux sale con 1  OK")
        return
    xdg = tempfile.mkdtemp(prefix="rnk_xdg_")
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = xdg
    try:
        path = os.path.join(xdg, "applications", de.FILE_NAME)
        assert de.handle_cli([de.INSTALL_FLAG]) == 0 and os.path.isfile(path)
        assert de.handle_cli([de.UNINSTALL_FLAG]) == 0 and not os.path.exists(path)
    finally:
        if old is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old
    print("Desktop: CLI instala y quita en XDG_DATA_HOME  OK")


if __name__ == "__main__":
    test_install_uninstall_roundtrip()
    test_exec_quoting_special_chars()
    test_default_targets_from_source()
    test_handle_cli()
    print()
    print("Todos los tests pasaron.")
