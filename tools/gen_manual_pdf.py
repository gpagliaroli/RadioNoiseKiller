"""
Genera un PDF del manual desde Markdown (markdown2 + xhtml2pdf), con portada.

Uso (desde la raíz del proyecto):
    .venv\\Scripts\\python.exe tools\\gen_manual_pdf.py MANUAL.md    MANUAL_RadioNoiseKiller_vX.Y.pdf
    .venv\\Scripts\\python.exe tools\\gen_manual_pdf.py MANUAL_EN.md MANUAL_RadioNoiseKiller_vX.Y_EN.pdf

weasyprint NO funciona en Windows (requiere GTK) — por eso xhtml2pdf. Las
imágenes (Images/...) se resuelven contra el cwd via link_callback. La portada
usa el logo Images/RNK_ico.png reescalado. Los PDFs están gitignoreados.
Requiere markdown2, xhtml2pdf y Pillow (en el venv).
"""
import os
import re
import sys
import tempfile

import markdown2
from PIL import Image
from xhtml2pdf import pisa

ICON_SRC = "Images/RNK_ico.png"
COVER_ICON = os.path.join(tempfile.gettempdir(), "_rnk_cover_icon.png")

CSS = """
@page { size: a4; margin: 2cm 1.8cm 2cm 1.8cm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; color: #1a1a1a; line-height: 1.4; }
h1 { font-size: 20pt; color: #0d3b66; border-bottom: 2px solid #0d3b66; padding-bottom: 4px; margin-top: 8px; }
h2 { font-size: 14pt; color: #0d3b66; border-bottom: 1px solid #b0c4de; padding-bottom: 2px; margin-top: 16px; }
h3 { font-size: 11.5pt; color: #14507a; margin-top: 12px; }
h4 { font-size: 10pt; color: #14507a; margin-top: 8px; }
p  { margin: 4px 0; }
img { max-width: 100%; }
code { font-family: "Courier New", monospace; font-size: 8.5pt; background: #f0f0f0; color: #a03030; }
pre  { font-family: "Courier New", monospace; font-size: 8pt; background: #f5f5f5;
       border: 1px solid #ddd; padding: 6px; margin: 6px 0; }
pre code { background: transparent; color: #222; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
th { background: #0d3b66; color: #fff; font-size: 8.5pt; padding: 4px 6px; text-align: left; border: 1px solid #0d3b66; }
td { font-size: 8.5pt; padding: 4px 6px; border: 1px solid #c8c8c8; vertical-align: top; }
tr:nth-child(even) td { background: #f4f7fb; }
blockquote { background: #fff8e1; border-left: 3px solid #ffb300; margin: 6px 0; padding: 4px 8px; font-size: 9pt; }
hr { border: none; border-top: 1px solid #ccc; margin: 10px 0; }
ul, ol { margin: 4px 0 4px 16px; }
li { margin: 2px 0; }
strong { color: #0d3b66; }
.cover { text-align: center; }
.cover-title { font-size: 30pt; color: #0d3b66; font-weight: bold; margin-top: 18px; }
.cover-sub  { font-size: 13pt; color: #14507a; margin-top: 6px; }
.cover-ver  { font-size: 12pt; color: #555; margin-top: 24px; }
"""


def _prep_cover_icon():
    """Reescala el ícono grande a un tamaño apto para la portada (una vez)."""
    im = Image.open(ICON_SRC).convert("RGBA")
    im.thumbnail((520, 520), Image.LANCZOS)
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    bg.convert("RGB").save(COVER_ICON, "PNG")


def _cover_html(title, subtitle, version):
    icon = COVER_ICON.replace("\\", "/")
    return (
        '<div class="cover">'
        f'<img src="{icon}" style="width: 280px;" />'
        f'<div class="cover-title">{title}</div>'
        f'<div class="cover-sub">{subtitle}</div>'
        f'<div class="cover-ver">{version}</div>'
        '</div>'
        '<div style="page-break-after: always;"></div>'
    )


def _link_callback(uri, rel):
    """Resuelve rutas relativas (Images/...) contra la raíz del proyecto."""
    if os.path.isabs(uri) and os.path.exists(uri):
        return uri
    cand = os.path.join(os.getcwd(), uri)
    return cand if os.path.exists(cand) else uri


def main():
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = f.read()

    is_en = src.endswith("_EN.md")
    m = re.search(r"\*\*(Versi[oó]n[^*]+)\*\*", md)
    version = m.group(1).strip() if m else ("Version 1.8" if is_en else "Versión 1.8")
    subtitle = "User Manual" if is_en else "Manual de Usuario"

    # Quitar el bloque de título del cuerpo (lo reemplaza la portada): todo hasta
    # el primer '---' inclusive.
    body_md = re.sub(r"^.*?\n---\n", "", md, count=1, flags=re.DOTALL)

    _prep_cover_icon()
    html_body = markdown2.markdown(body_md, extras=[
        "tables", "fenced-code-blocks", "header-ids", "break-on-newline", "cuddled-lists",
    ])
    cover = _cover_html("RadioNoiseKiller", subtitle, version)
    html = (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head>"
            f"<body>{cover}{html_body}</body></html>")

    with open(dst, "wb") as out:
        result = pisa.CreatePDF(html, dest=out, encoding="utf-8", link_callback=_link_callback)
    if result.err:
        print(f"ERROR generando {dst}: {result.err} errores")
        sys.exit(1)
    print(f"OK: {dst}")


if __name__ == "__main__":
    main()
