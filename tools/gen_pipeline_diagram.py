"""
Genera el diagrama del pipeline como PNG (PIL), en español e inglés.

Salida: Images/pipeline_diagram.png y Images/pipeline_diagram_en.png
Correr desde la raíz del proyecto:  .venv\\Scripts\\python.exe tools\\gen_pipeline_diagram.py

Las imágenes se versionan (las referencia el manual). Regenerar y commitear si se
cambia algún módulo del pipeline. Requiere Pillow (ya está en el venv).
"""
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersampling para bordes/texto nítidos (se reduce al final)
W = 900 * S

# Rutas de fuentes por plataforma (Windows primero; fallback Linux; luego default).
_BOLD_CANDIDATES = ["C:/Windows/Fonts/arialbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_REG_CANDIDATES = ["C:/Windows/Fonts/arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size * S)
        except OSError:
            continue
    return ImageFont.load_default()


F_TITLE = _font(_BOLD_CANDIDATES, 17)
F_DESC  = _font(_REG_CANDIDATES, 13)
F_IO    = _font(_BOLD_CANDIDATES, 19)
F_SUB_T = _font(_BOLD_CANDIDATES, 13)
F_SUB_D = _font(_REG_CANDIDATES, 11)

# Paleta
BG      = (255, 255, 255)
IO_BG   = (13, 59, 102);   IO_FG = (255, 255, 255)
ST_BG   = (232, 240, 250); ST_BORDER = (13, 59, 102); ST_TITLE = (13, 59, 102); ST_DESC = (70, 80, 95)
MAIN_BG = (255, 241, 230); MAIN_BORDER = (232, 115, 12); MAIN_TITLE = (183, 74, 0)
SUB_BG  = (244, 244, 246); SUB_BORDER = (150, 150, 155); SUB_TITLE = (90, 90, 95); SUB_DESC = (120, 120, 125)
ARROW   = (140, 150, 160)

# Etapas: (title_es, title_en, desc_es, desc_en, kind)
STAGES = [
    ("AUDIO — ENTRADA", "AUDIO — INPUT", "", "", "io"),
    ("Ganancia de entrada", "Input gain", "Nivel de la señal que entra", "Level of the incoming signal", "st"),
    ("Supresor de Impulsos", "Impulse Suppressor", "Elimina QRN y descargas breves (pre-AGC)", "Removes QRN and short bursts (pre-AGC)", "st"),
    ("AGC", "AGC", "Control automático de ganancia", "Automatic gain control", "st"),
    ("Filtro de Paso de Banda — PRE", "Bandpass Filter — PRE", "Limita el espectro antes del cancelador", "Limits the spectrum before the canceller", "st"),
    ("ANF — Muesca Espectral", "ANF — Spectral Notch", "Cancela heterodinos y tonos fijos", "Cancels heterodynes and steady tones", "st"),
    ("Cancelador de Ruido Estacionario", "Stationary Noise Canceller", "Filtro Wiener espectral adaptativo", "Adaptive spectral Wiener filter", "main"),
    ("Squelch de Voz", "Voice Squelch", "Silencia la salida entre transmisiones (opcional)", "Mutes output between overs (optional)", "st"),
    ("Filtro de Paso de Banda — POST", "Bandpass Filter — POST", "Limpia fugas espectrales post-procesado", "Cleans spectral leakage after processing", "st"),
    ("EQ de Voz: presencia + cuerpo", "Voice EQ: presence + body", "Realza consonantes y cuerpo de la voz", "Boosts consonants and voice body", "st"),
    ("Excitador Armónico", "Harmonic Exciter", "Genera armónicos para recuperar brillo (opcional)", "Adds harmonics to restore brightness (optional)", "st"),
    ("Ganancia de salida + Limitador", "Output gain + Limiter", "Nivel final y limitador de picos", "Final level and peak limiter", "st"),
    ("AUDIO — SALIDA", "AUDIO — OUTPUT", "", "", "io"),
]
# Sub-módulos del cancelador
SUBS = [
    ("Refuerzo de pitch de voz", "Voice pitch enhance", "opcional", "optional"),
    ("Post-filtro espectral", "Spectral post-filter", "opcional", "optional"),
]


def rrect(d, box, r, fill, outline, width=2):
    d.rounded_rectangle(box, radius=r * S, fill=fill, outline=outline, width=width * S)


def ctext(d, cx, cy, text, fnt, fill):
    l, t, rr, b = d.textbbox((0, 0), text, font=fnt)
    d.text((cx - (rr - l) / 2, cy - (b - t) / 2 - t), text, font=fnt, fill=fill)


def build(lang):
    i_t = 0 if lang == "es" else 1
    i_d = 2 if lang == "es" else 3
    box_w = 560 * S
    io_h = 46 * S
    st_h = 62 * S
    main_h = 70 * S
    gap = 26 * S
    sub_w = 210 * S
    sub_h = 46 * S
    sub_gap = 20 * S
    # centrar el bloque COMPLETO (columna + sub-módulos a la derecha), no solo
    # la columna — si no, los sub-módulos se salen del borde derecho.
    x0 = (W - (box_w + sub_gap + sub_w)) // 2

    H = 30 * S
    for _t_es, _t_en, _d_es, _d_en, kind in STAGES:
        H += (io_h if kind == "io" else main_h if kind == "main" else st_h) + gap
    H += 30 * S

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    y = 30 * S
    main_box = None
    for st in STAGES:
        title, desc, kind = st[i_t], st[i_d], st[4]
        h = io_h if kind == "io" else main_h if kind == "main" else st_h
        box = [x0, y, x0 + box_w, y + h]
        cx = (box[0] + box[2]) / 2
        if kind == "io":
            rrect(d, box, 10, IO_BG, IO_BG)
            ctext(d, cx, (box[1] + box[3]) / 2, title, F_IO, IO_FG)
        elif kind == "main":
            rrect(d, box, 12, MAIN_BG, MAIN_BORDER, 3)
            ctext(d, cx, box[1] + main_h * 0.36, title, F_TITLE, MAIN_TITLE)
            ctext(d, cx, box[1] + main_h * 0.70, desc, F_DESC, ST_DESC)
            main_box = box
        else:
            rrect(d, box, 10, ST_BG, ST_BORDER, 2)
            ctext(d, cx, box[1] + st_h * 0.34, title, F_TITLE, ST_TITLE)
            ctext(d, cx, box[1] + st_h * 0.68, desc, F_DESC, ST_DESC)
        y_next = y + h + gap
        if st is not STAGES[-1]:
            d.line([(cx, y + h), (cx, y_next)], fill=ARROW, width=2 * S)
            d.polygon([(cx - 5 * S, y_next - 6 * S), (cx + 5 * S, y_next - 6 * S), (cx, y_next)], fill=ARROW)
        y = y_next

    if main_box:
        sy = main_box[1] + (main_box[3] - main_box[1] - (sub_h * 2 + 10 * S)) / 2
        sx = main_box[2] + sub_gap
        for k, sub in enumerate(SUBS):
            s_t = sub[0 if lang == "es" else 1]
            s_d = sub[2 if lang == "es" else 3]
            sb = [sx, sy, sx + sub_w, sy + sub_h]
            d.rounded_rectangle(sb, radius=8 * S, fill=SUB_BG, outline=SUB_BORDER, width=2 * S)
            scx = (sb[0] + sb[2]) / 2
            ctext(d, scx, sb[1] + sub_h * 0.36, s_t, F_SUB_T, SUB_TITLE)
            ctext(d, scx, sb[1] + sub_h * 0.70, s_d, F_SUB_D, SUB_DESC)
            my = (sb[1] + sb[3]) / 2
            d.line([(main_box[2], my), (sx, my)], fill=SUB_BORDER, width=2 * S)
            sy += sub_h + 10 * S

    out = img.resize((W // S, H // S), Image.LANCZOS)
    name = "Images/pipeline_diagram.png" if lang == "es" else "Images/pipeline_diagram_en.png"
    out.save(name)
    print(f"OK: {name}  ({out.width}x{out.height})")


if __name__ == "__main__":
    build("es")
    build("en")
