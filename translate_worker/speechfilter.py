"""Descarta segmentos que no son voz (música, ruido, alucinaciones típicas de
Whisper). Puro stdlib: se testea sin faster-whisper.

Whisper, ante música o ruido, o devuelve símbolos (♪), o inventa frases de
"créditos" (Subtitles by..., Gracias por ver), o transcribe con muy poca
seguridad. Las tres cosas se reconocen sin modelo extra: los símbolos y las
frases por el texto, la baja seguridad por las métricas que faster-whisper ya
calcula por segmento (no_speech_prob, avg_logprob).

Limitación conocida: música con voz cantada se parece a voz y pasa el filtro."""
import re

# Mismo criterio que usa Whisper para marcar un tramo como "sin voz":
# probabilidad alta de no-voz Y transcripción poco probable.
NO_SPEECH_PROB = 0.6
AVG_LOGPROB = -1.0
# Con no_speech_prob así de alto se descarta aunque la transcripción parezca segura.
NO_SPEECH_PROB_SURE = 0.9

_MUSIC_SYMBOLS = re.compile(r"[♪♫♬♩🎵🎶]")
_ONLY_NOISE = re.compile(r"^[\W_]*$", re.UNICODE)
_TAGS = re.compile(
    r"^\s*[\[\(\*]\s*(music|musica|música|applause|aplausos|silence|silencio|"
    r"noise|ruido|inaudible)\s*[\]\)\*]\s*$", re.IGNORECASE)
_HALLUCINATIONS = re.compile(
    r"(subtitles? by|subt[ií]tulos? (realizados? )?por|amara\.org|"
    r"thanks? for watching|gracias por (ver|vernos)|suscr[ií]b)", re.IGNORECASE)


def is_non_speech(seg: dict) -> bool:
    """True si el segmento no debe mostrarse ni traducirse."""
    text = (seg.get("text") or "").strip()
    if _MUSIC_SYMBOLS.search(text) or _TAGS.match(text) or _HALLUCINATIONS.search(text):
        return True
    if not text or _ONLY_NOISE.match(text):
        return True
    nsp = seg.get("no_speech_prob")
    if nsp is None:
        return False
    if nsp > NO_SPEECH_PROB_SURE:
        return True
    lp = seg.get("avg_logprob")
    return nsp > NO_SPEECH_PROB and lp is not None and lp < AVG_LOGPROB


def split_speech(segments: list) -> tuple:
    """(segmentos con voz, cantidad descartada por no ser voz)."""
    kept = [s for s in segments if not is_non_speech(s)]
    return kept, len(segments) - len(kept)
