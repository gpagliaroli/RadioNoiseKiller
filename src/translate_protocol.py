"""
Protocolo IPC entre RadioNoiseKiller (este módulo) y translate_worker/ (proceso
separado): una línea JSON por mensaje, \\n-delimitada, UTF-8, por stdin/stdout.

Este archivo se DUPLICA (no se importa) desde translate_worker/protocol.py —
el proceso de traducción nunca se importa desde src/, para que el .spec de la
app principal no pueda arrastrar sus dependencias por accidente. Si se edita
un lado, editar el otro y correr los tests de los dos.
"""
import json


def encode_ready(asr_model: str, device: str = "cpu") -> str:
    return json.dumps({"type": "ready", "asr_model": asr_model, "device": device})


def encode_request(req_id: int, audio_b64: str, sample_rate: int,
                    lang_src: str = "auto", lang_dst: str = "es",
                    min_confidence: float = 0.5) -> str:
    return json.dumps({
        "type": "transcribe",
        "id": req_id,
        "audio_b64": audio_b64,
        "sample_rate": sample_rate,
        "lang_src": lang_src,
        "lang_dst": lang_dst,
        "min_confidence": min_confidence,
    })


def encode_result(req_id: int, detected_lang: str, detected_lang_prob: float,
                   segments: list, low_confidence: bool = False,
                   music: bool = False) -> str:
    """segments: lista de dicts {"start", "end", "text", "translated"}.
    low_confidence=True: detected_lang_prob no llegó al mínimo pedido en el
    request — "translated" queda sin poner en los segmentos (ver worker.py),
    la UI decide no mostrar texto en ese caso (ver translate_tab.py)."""
    return json.dumps({
        "type": "result",
        "id": req_id,
        "ok": True,
        "detected_lang": detected_lang,
        "detected_lang_prob": detected_lang_prob,
        "segments": segments,
        "low_confidence": low_confidence,
        "music": music,   # el chunk no tenía voz (música/ruido): sin segmentos
    })


def encode_error(req_id: int, error: str, detail: str = "") -> str:
    return json.dumps({
        "type": "result",
        "id": req_id,
        "ok": False,
        "error": error,
        "detail": detail,
    })


def decode_line(line: str) -> dict:
    """Levanta ValueError si la línea no es JSON válido — el que llama decide
    qué hacer (loguear y seguir, nunca debe tumbar el loop de lectura)."""
    data = json.loads(line)
    if not isinstance(data, dict) or "type" not in data:
        raise ValueError(f"mensaje sin 'type': {line!r}")
    return data
