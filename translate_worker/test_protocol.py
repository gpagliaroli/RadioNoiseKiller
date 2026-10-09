"""Test del protocolo IPC, lado worker. Puro stdlib (json) — corre con
cualquier Python, no necesita el venv con faster-whisper/argostranslate
instalado. Ver también tests/test_translate.py (gemelo, lado src/)."""
import protocol


def test_roundtrip():
    msg = protocol.decode_line(protocol.encode_request(1, "QUJD", 16000))
    assert msg["type"] == "transcribe" and msg["audio_b64"] == "QUJD"

    msg = protocol.decode_line(protocol.encode_result(1, "en", 0.9, [{"text": "hi"}]))
    assert msg["ok"] is True and msg["segments"][0]["text"] == "hi"

    msg = protocol.decode_line(protocol.encode_error(1, "boom", "detalle"))
    assert msg["ok"] is False and msg["error"] == "boom"
    print("protocol: roundtrip OK")


if __name__ == "__main__":
    test_roundtrip()
    print("Todos los tests pasaron.")
