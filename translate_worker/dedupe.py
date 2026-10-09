"""Filtro de segmentos repetidos. Puro stdlib: se testea sin faster-whisper.

Whisper con audio ruidoso a veces entra en bucle y emite la misma frase
varias veces; este filtro es la red de seguridad por si los parámetros
anti-repetición de asr.py no alcanzan."""
import re

_NO_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    return _NO_ALNUM.sub(" ", text.lower()).strip()


def is_pure_repeat(text: str) -> bool:
    """True si el texto es una misma frase repetida 2+ veces seguidas
    ("hola hola hola", "no sé no sé")."""
    words = normalize(text).split()
    n = len(words)
    for size in range(1, n // 2 + 1):
        if n % size == 0 and words == words[:size] * (n // size):
            return True
    return False


def dedupe_segments(segments: list, last_text: str = "") -> list:
    """Descarta segmentos idénticos al anterior (o al último texto del chunk
    previo, `last_text` ya normalizado). Los que son una frase repetida N
    veces se reducen a una sola vez. Conserva el orden."""
    out = []
    prev = last_text
    for seg in segments:
        key = normalize(seg.get("text", ""))
        if not key or key == prev:
            continue
        if is_pure_repeat(seg["text"]):
            words = key.split()
            for size in range(1, len(words) + 1):
                if words == words[:size] * (len(words) // size):
                    seg = dict(seg, text=" ".join(words[:size]))
                    break
        out.append(seg)
        prev = normalize(seg["text"])
    return out
