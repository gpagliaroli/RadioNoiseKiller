"""Test del filtro de repeticiones. Puro stdlib."""
from dedupe import dedupe_segments, is_pure_repeat, normalize


def _s(*texts):
    return [{"start": 0.0, "end": 1.0, "text": t} for t in texts]


def test_consecutive_duplicates_dropped():
    out = dedupe_segments(_s("Hello there.", "hello there", "Hello there!", "Bye."))
    assert [s["text"] for s in out] == ["Hello there.", "Bye."]


def test_non_consecutive_kept():
    out = dedupe_segments(_s("A b", "C d", "A b"))
    assert len(out) == 3


def test_pure_repeat_collapsed():
    assert is_pure_repeat("no sé no sé no sé")
    assert not is_pure_repeat("no sé nada")
    out = dedupe_segments(_s("hola hola hola"))
    assert out[0]["text"] == "hola"


def test_across_chunks():
    out = dedupe_segments(_s("Good evening."), last_text=normalize("good evening"))
    assert out == []


def test_empty_and_symbols_dropped():
    assert dedupe_segments(_s("", "...")) == []


if __name__ == "__main__":
    test_consecutive_duplicates_dropped()
    test_non_consecutive_kept()
    test_pure_repeat_collapsed()
    test_across_chunks()
    test_empty_and_symbols_dropped()
    print("Todos los tests pasaron.")
