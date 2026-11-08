"""
Verifica que ningún ELF de un bundle Linux pida una glibc más nueva que la tope.

Un binario compilado contra una glibc más nueva que la del destino no arranca
("GLIBC_2.38 not found"). El paquete x86_64 de la v2.7 salió de ubuntu-latest
(24.04) y pedía 2.38: no arrancaba en Ubuntu 22.04 ni en Debian 12. Desde
entonces los dos jobs del CI compilan en 22.04 (glibc 2.35) y este script corre
al final de cada uno: si algún runner, wheel o lib del sistema sube la versión,
el build falla en vez de enterarse el usuario.

Lee la sección .gnu.version_r (versiones requeridas) de cada ELF con pyelftools.

Uso:
    python tools/check_glibc.py <carpeta del bundle> [--max 2.35]
    python tools/check_glibc.py <zip del bundle>     [--max 2.35]

Sale con 1 si algo supera el tope y lista qué archivo pide qué versión.
"""
import argparse
import io
import os
import re
import sys
import zipfile

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

_GLIBC = re.compile(r"^GLIBC_(\d+)\.(\d+)(?:\.(\d+))?$")


def _parse(v: str) -> tuple:
    return tuple(int(p) for p in v.split("."))


def glibc_required(data: bytes) -> "tuple | None":
    """Máxima versión GLIBC_x.y que pide un ELF, o None si no es ELF o no pide."""
    if data[:4] != b"\x7fELF":
        return None
    try:
        elf = ELFFile(io.BytesIO(data))
    except ELFError:
        return None
    sec = elf.get_section_by_name(".gnu.version_r")
    if sec is None:
        return None
    best = None
    for _verneed, auxs in sec.iter_versions():
        for aux in auxs:
            m = _GLIBC.match(aux.name)
            if m:
                v = tuple(int(g) for g in m.groups() if g is not None)
                best = v if best is None or v > best else best
    return best


def _iter_files(target: str):
    """(nombre, bytes) de cada archivo regular de una carpeta o de un zip."""
    if zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as z:
            for info in z.infolist():
                if not info.is_dir():
                    yield info.filename, z.read(info)
        return
    for d, _, fs in os.walk(target):
        for f in fs:
            path = os.path.join(d, f)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                yield os.path.relpath(path, target), fh.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("target", help="carpeta o zip del bundle")
    ap.add_argument("--max", default="2.35", help="glibc máxima permitida (default 2.35)")
    args = ap.parse_args()
    tope = _parse(args.max)

    n_elf, peor, culpables = 0, None, []
    for name, data in _iter_files(args.target):
        v = glibc_required(data)
        if v is None:
            continue
        n_elf += 1
        peor = v if peor is None or v > peor else peor
        if v > tope:
            culpables.append((v, name))

    if n_elf == 0:
        print(f"ERROR: no se encontró ningún ELF con dependencia de glibc en {args.target}")
        return 1
    fmt = lambda v: ".".join(map(str, v))   # noqa: E731
    print(f"{n_elf} ELF revisados; glibc máxima requerida: {fmt(peor)} (tope {args.max})")
    if culpables:
        print("ERROR: estos archivos piden una glibc más nueva que el tope:")
        for v, name in sorted(culpables, reverse=True):
            print(f"  GLIBC_{fmt(v)}  {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
