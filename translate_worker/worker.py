"""Entry point del proceso de traducción. Loop simple: una línea JSON de
pedido por stdin -> una línea JSON de resultado por stdout. Un pedido a la
vez (RadioNoiseKiller nunca manda el siguiente chunk antes de recibir la
respuesta del anterior), así que no hace falta asyncio ni colas internas.

Nunca se importa desde src/ — es un proceso separado a propósito, para que
el .spec de PyInstaller de la app principal no necesite torch/onnxruntime.
Instalación manual: ver README.md de esta carpeta.
"""
import base64
import sys

import numpy as np

import protocol
from asr import AsrEngine
from dedupe import dedupe_segments, normalize
from mt import MtEngine, NoLanguagePairError

MODEL_SIZE = sys.argv[1] if len(sys.argv) > 1 else "tiny"


def _decode_audio(audio_b64: str) -> np.ndarray:
    raw = base64.b64decode(audio_b64)
    return np.frombuffer(raw, dtype=np.float32)


def _arg_list(flag: str) -> list:
    """Valor de `--flag a,b,c` en argv (lista vacía si falta)."""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return [x for x in sys.argv[i + 1].split(",") if x]
    return []


def prefetch() -> None:
    """Modo instalación (lo lanza translate_installer.py): descarga el modelo
    de voz y los paquetes de idioma pedidos y sale. Imprime `progress: ...`."""
    print("progress: modelo de voz", flush=True)
    AsrEngine(MODEL_SIZE)
    mt = MtEngine()
    for s in _arg_list("--src"):
        for d in _arg_list("--dst"):
            if s == d:
                continue
            print(f"progress: idioma {s} -> {d}", flush=True)
            mt.ensure_pair(s, d)
    print("progress: listo", flush=True)


def main() -> None:
    if "--prefetch" in sys.argv:
        prefetch()
        return
    asr = AsrEngine(MODEL_SIZE)
    mt = MtEngine()
    print(protocol.encode_ready(MODEL_SIZE), flush=True)
    last_text = ""

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = protocol.decode_line(line)
        except ValueError as e:
            print(f"linea invalida ignorada: {e}", file=sys.stderr, flush=True)
            continue

        if msg.get("type") != "transcribe":
            continue
        req_id = msg.get("id", -1)
        try:
            audio = _decode_audio(msg["audio_b64"])
            lang_src = msg.get("lang_src", "auto")
            lang_dst = msg.get("lang_dst", "es")
            min_confidence = msg.get("min_confidence", 0.5)
            detected_lang, prob, segments = asr.transcribe(
                audio, msg["sample_rate"], lang_src)
            # La confianza es del CHUNK entero (detección de idioma de
            # faster-whisper), no por segmento — si no llega al mínimo, se
            # salta la traducción completa en vez de traducir texto que
            # probablemente está en el idioma equivocado (ver el spike:
            # confianzas de 24-41% dieron traducciones "con forma de
            # oración" pero sin sentido real). Ahorra además el costo de
            # las llamadas a argostranslate.
            # Repeticiones: dentro del chunk (bucle de Whisper) y contra el
            # último texto del chunk anterior.
            segments = dedupe_segments(segments, last_text)
            if segments:
                last_text = normalize(segments[-1]["text"])
            low_confidence = prob < min_confidence
            if not low_confidence:
                for seg in segments:
                    seg["translated"] = mt.translate(seg["text"], detected_lang, lang_dst)
            print(protocol.encode_result(req_id, detected_lang, prob, segments,
                                          low_confidence),
                  flush=True)
        except NoLanguagePairError as e:
            print(protocol.encode_error(req_id, "no_language_pair", str(e)), flush=True)
        except Exception as e:
            print(protocol.encode_error(req_id, "internal_error", str(e)), flush=True)


if __name__ == "__main__":
    main()
