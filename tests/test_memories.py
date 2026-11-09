"""
Tests de las memorias de emisoras de la solapa CAT (src/memories.py), sin Qt:
roundtrip, carga tolerante, no duplicar (misma frecuencia y grupo de modo),
orden por frecuencia, CSV ida y vuelta, default_name y RNK_DATA_DIR.
"""
import json
import os
import sys
import tempfile

if not os.environ.get("RNK_DATA_DIR"):
    os.environ["RNK_DATA_DIR"] = tempfile.mkdtemp(prefix="rnk_test_mem_")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import memories  # noqa: E402
from memories import Memory, MemoryStore  # noqa: E402


def _tmp(name="Memorias.json"):
    return os.path.join(tempfile.mkdtemp(), name)


def test_default_path_uses_data_dir():
    s = MemoryStore()
    assert os.path.dirname(s.path) == os.environ["RNK_DATA_DIR"], s.path
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    assert not os.path.abspath(s.path).startswith(root + os.sep), "nunca en el proyecto"
    print("Memorias: el archivo va a RNK_DATA_DIR  OK")


def test_roundtrip_and_order():
    p = _tmp()
    s = MemoryStore(p)
    s.add(Memory("Radio Nacional", 870000, "AM"))
    s.add(Memory("40 m FT8", 7074000, "USB"))
    s.add(Memory("RAE", 9690000, "AM"))
    s.add(Memory("Baja", 530000, "AM"))
    assert [m.freq_hz for m in s.items] == [530000, 870000, 7074000, 9690000]
    s.save()
    t = MemoryStore(p)
    t.load()
    assert t.items == s.items
    assert not os.path.exists(p + ".tmp"), "guardado atómico sin restos"
    print("Memorias: roundtrip y orden por frecuencia  OK")


def test_add_does_not_duplicate_same_freq_and_group():
    s = MemoryStore(_tmp())
    assert s.add(Memory("A", 7074000, "USB")) == (0, True)
    assert s.add(Memory("B", 7074000, "LSB")) == (0, False), "USB/LSB = mismo grupo"
    assert s.add(Memory("C", 7074000, "AM"))[1] is True, "otro grupo sí entra"
    assert s.add(Memory("D", 7075000, "USB"))[1] is True
    assert len(s) == 3 and s.items[0].name in ("A", "C")
    print("Memorias: no duplica misma frecuencia + grupo de modo  OK")


def test_rename_and_remove():
    s = MemoryStore(_tmp())
    s.add(Memory("A", 6000000, "AM"))
    s.rename(0, "  Nuevo  ")
    assert s.items[0].name == "Nuevo"
    s.rename(0, "   ")
    assert s.items[0].name == memories.default_name(6000000, "AM"), "vacío -> nombre por defecto"
    s.remove(0)
    assert len(s) == 0
    print("Memorias: renombrar y borrar  OK")


def test_tolerant_load():
    p = _tmp()
    s = MemoryStore(p)
    s.load()
    assert len(s) == 0, "archivo ausente"
    open(p, "w").write("{roto")
    s.load()
    assert len(s) == 0, "JSON roto"
    json.dump({"memories": "x"}, open(p, "w"))
    s.load()
    assert len(s) == 0
    json.dump({"memories": [
        {"name": "ok", "freq_hz": 9560000, "mode": "am"},
        {"name": "sin freq", "mode": "AM"},
        {"name": "freq mala", "freq_hz": "abc", "mode": "AM"},
        {"name": "negativa", "freq_hz": -5, "mode": "AM"},
        {"name": 5, "freq_hz": 1000, "mode": "AM"},
        "basura",
        {"name": "", "freq_hz": 7074000.4, "mode": "usb"},
        {"name": "dup", "freq_hz": 9560000, "mode": "SAM"},
    ]}, open(p, "w"))
    s.load()
    assert [(m.name, m.freq_hz, m.mode) for m in s.items] == [
        (memories.default_name(7074000, "USB"), 7074000, "USB"),
        ("ok", 9560000, "AM"),
    ], s.items
    print("Memorias: carga tolerante (filas rotas y duplicadas se saltean)  OK")


def test_csv_roundtrip_and_import():
    s = MemoryStore(_tmp())
    s.add(Memory("Radio; con punto y coma", 9560000, "AM"))
    s.add(Memory("FT8", 7074500, "USB"))
    p = _tmp("m.csv")
    s.export_csv(p)
    t = MemoryStore(_tmp())
    assert t.import_csv(p) == 2
    assert t.items == s.items, t.items
    assert t.import_csv(p) == 0, "re-importar no duplica"
    q = _tmp("otro.csv")
    open(q, "w", encoding="utf-8").write(
        "﻿Mode,Freq_kHz,Name\nAM,6070,CFRX\nUSB,abc,mala\nFM,145500,Repetidora\n")
    assert t.import_csv(q) == 2, "separador ',' y columnas en otro orden"
    assert t.items[-1] == Memory("Repetidora", 145500000, "FM")
    print("Memorias: CSV ida y vuelta, import tolerante  OK")


def test_sort_order_and_persistence():
    items = [Memory("rae", 9560000, "AM"), Memory("Baja", 530000, "AM"),
             Memory("FT8", 7074000, "USB"), Memory("baja", 1000000, "AM"),
             Memory("CW", 7030000, "CW")]
    names = lambda key, desc: [items[i].name for i in memories.sort_order(items, key, desc)]
    assert names("name", False) == ["Baja", "baja", "CW", "FT8", "rae"], "sin mayúsculas, desempata por freq"
    assert names("name", True) == ["rae", "FT8", "CW", "baja", "Baja"]
    assert names("freq", False) == ["Baja", "baja", "CW", "FT8", "rae"]
    assert names("freq", True) == ["rae", "FT8", "CW", "baja", "Baja"]
    assert names("mode", False) == ["Baja", "baja", "rae", "CW", "FT8"], "dentro del modo, por freq"
    assert names("mode", True) == ["FT8", "CW", "rae", "baja", "Baja"]
    assert names("xx", False) == names("freq", False), "clave desconocida = frecuencia"
    p = _tmp()
    s = MemoryStore(p)
    assert (s.sort_key, s.sort_desc) == memories.DEFAULT_SORT == ("freq", False)
    s.add(items[0])
    s.sort_key, s.sort_desc = "mode", True
    s.save()
    t = MemoryStore(p)
    t.load()
    assert (t.sort_key, t.sort_desc) == ("mode", True), "el orden se recuerda"
    data = json.load(open(p, encoding="utf-8"))
    data["sort"] = {"key": "bogus", "desc": "si"}
    json.dump(data, open(p, "w"))
    t.load()
    assert (t.sort_key, t.sort_desc) == memories.DEFAULT_SORT and len(t) == 1
    print("Memorias: orden por nombre/frecuencia/modo, asc/desc, persistido  OK")


def test_default_name():
    assert memories.default_name(7074000, "USB") == "7.074,0 kHz USB"
    assert memories.default_name(7074000, "USB", "en") == "7,074.0 kHz USB"
    assert memories.default_name(145500000, "") == "145.500,0 kHz"
    print("Memorias: nombre por defecto  OK")


if __name__ == "__main__":
    test_default_path_uses_data_dir()
    test_roundtrip_and_order()
    test_add_does_not_duplicate_same_freq_and_group()
    test_rename_and_remove()
    test_tolerant_load()
    test_csv_roundtrip_and_import()
    test_sort_order_and_persistence()
    test_default_name()
    print()
    print("Todos los tests pasaron.")
