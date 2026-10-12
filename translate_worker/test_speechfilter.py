"""Test del filtro de no-voz. Puro stdlib."""
from speechfilter import is_non_speech, split_speech


def _s(text, nsp=None, lp=None):
    d = {"text": text}
    if nsp is not None:
        d["no_speech_prob"] = nsp
    if lp is not None:
        d["avg_logprob"] = lp
    return d


def test_music_symbols_and_tags():
    for t in ("♪", "♪ la la la ♪", "[Music]", "(música)", "*Applause*", "...", ""):
        assert is_non_speech(_s(t)), t
    print("speechfilter: simbolos y etiquetas de musica  OK")


def test_hallucinations():
    for t in ("Subtitles by the Amara.org community", "Subtítulos realizados por la comunidad",
              "Thanks for watching!", "Gracias por ver el video"):
        assert is_non_speech(_s(t)), t
    print("speechfilter: alucinaciones tipicas  OK")


def test_normal_speech_kept():
    assert not is_non_speech(_s("Welcome to our broadcast"))
    assert not is_non_speech(_s("Welcome to our broadcast", 0.1, -0.3))
    # no_speech_prob alto pero la transcripcion es segura: se conserva
    assert not is_non_speech(_s("Buenas noches", 0.7, -0.4))
    print("speechfilter: la voz normal se conserva  OK")


def test_confidence_rules():
    assert is_non_speech(_s("blah blah", 0.7, -1.5))   # no-voz probable y poco segura
    assert is_non_speech(_s("blah blah", 0.95, -0.2))  # casi seguro que no es voz
    assert not is_non_speech(_s("blah blah", 0.5, -2.0))
    print("speechfilter: umbrales de seguridad  OK")


def test_split():
    kept, dropped = split_speech([_s("Hello"), _s("♪"), _s("World", 0.95)])
    assert [s["text"] for s in kept] == ["Hello"] and dropped == 2
    print("speechfilter: split_speech  OK")


if __name__ == "__main__":
    test_music_symbols_and_tags()
    test_hallucinations()
    test_normal_speech_kept()
    test_confidence_rules()
    test_split()
    print("Todos los tests pasaron.")
