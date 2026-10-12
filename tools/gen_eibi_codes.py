"""Genera src/eibi_codes.py (nombres de idioma / país / zona de EiBi) a partir del
README.TXT oficial de EiBi (secciones "D) Codes used").

Uso:  .venv\\Scripts\\python.exe tools\\gen_eibi_codes.py [ruta_a_README.TXT]
Sin argumento, lo baja de http://www.eibispace.de/dx/README.TXT (el sitio sólo
responde por HTTP: el certificado HTTPS está vencido).
"""
import os
import re
import sys
import urllib.request

URL = "http://www.eibispace.de/dx/README.TXT"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "eibi_codes.py")


def _section(lines, start_pat, end_pat):
    a = next(i for i, l in enumerate(lines) if re.match(start_pat, l))
    b = next(i for i, l in enumerate(lines) if i > a and re.match(end_pat, l))
    return lines[a + 1:b]


def _clean_lang(rest: str) -> str:
    rest = re.sub(r"\s+\[[a-z-]{2,4}\]\s*$", "", rest)       # [iso639-3]
    rest = rest.split(":")[0]                                # "Español: España (30m)" -> "Español"
    rest = re.sub(r"\s*\([^)]*\)\s*$", "", rest)             # "(300m)" suelto
    return rest.strip()


def main() -> None:
    if len(sys.argv) > 1:
        raw = open(sys.argv[1], "rb").read()
    else:
        raw = urllib.request.urlopen(URL, timeout=30).read()
    lines = raw.decode("latin-1").splitlines()

    lang, country, target = {}, {}, {}
    for l in _section(lines, r"\s+I\) Language codes", r"\s+II\) Country codes"):
        m = re.match(r"   (\S+)\s{2,}(.+)$", l)
        if m and not m.group(1).startswith("[") and len(m.group(1)) <= 4:
            lang[m.group(1)] = _clean_lang(m.group(2))
    for l in _section(lines, r"\s+II\) Country codes", r"\s+III\) Target-area codes"):
        m = re.match(r"   ([A-Za-z*]{1,4})\s{2,}(\S.*)$", l)
        if m:
            country[m.group(1).rstrip("*")] = m.group(2).strip()
    for l in _section(lines, r"\s+III\) Target-area codes", r"\s+Alternatively, ITU country"):
        m = re.match(r"   (\S+)\s+- (.+)$", l)
        if m:
            target[m.group(1)] = m.group(2).strip()

    def dump(name, d):
        body = "".join("    %r: %r,\n" % (k, v) for k, v in d.items())
        return "%s = {\n%s}\n" % (name, body)

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write('"""Nombres de los códigos de EiBi (idioma, país ITU, zona objetivo).\n\n'
                "GENERADO por tools/gen_eibi_codes.py a partir del README.TXT de EiBi\n"
                '(eibispace.de, uso libre). No editar a mano."""\n\n')
        f.write(dump("LANGUAGES", lang) + "\n" + dump("COUNTRIES", country) + "\n" + dump("TARGETS", target))
        f.write('\n\ndef name_of(table: dict, code: str) -> str:\n'
                '    """Nombre legible del código, o el código crudo si no se conoce."""\n'
                '    return table.get(code, "") or code\n')
    print("idiomas %d, paises %d, zonas %d -> %s" % (len(lang), len(country), len(target), OUT))


if __name__ == "__main__":
    main()
