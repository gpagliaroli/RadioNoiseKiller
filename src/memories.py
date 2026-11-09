"""
Memorias de emisoras de la solapa CAT: nombre + frecuencia + modo.

Son memorias de la APP, no los canales de memoria de la radio: viven en
`Memorias.json` (carpeta de datos, aparte de settings.json para poder copiarlas
a otra PC o a la Pi) y se sintonizan por CAT con `RigctldClient.tune()`.
El preset no se guarda: lo pone la tabla modo -> preset al cambiar el modo.

Sin Qt; la carga es tolerante (un archivo roto no puede impedir que arranque
la app) y el guardado atómico.
"""
import csv
import json
import os
from dataclasses import dataclass

import cat
from utils import data_dir

FILE_NAME = "Memorias.json"

# Orden de la tabla (tocando el encabezado). Se recuerda en el archivo.
SORT_KEYS = ("name", "freq", "mode")
DEFAULT_SORT = ("freq", False)


@dataclass(frozen=True)
class Memory:
    name: str
    freq_hz: int
    mode: str              # modo de Hamlib (USB, LSB, AM, FM...)


def default_name(freq_hz: int, mode: str, lang: str = "es") -> str:
    """'7.074,0 kHz USB' (o '7,074.0 kHz USB' en inglés): cuando EiBi no da nombre."""
    txt = f"{freq_hz / 1000:,.1f}"
    if lang != "en":
        txt = txt.replace(",", "#").replace(".", ",").replace("#", ".")
    return f"{txt} kHz {mode}".strip()


def sort_order(items: list, key: str, desc: bool) -> "list[int]":
    """Índices de `items` en el orden de la vista. Los empates se desempatan por
    frecuencia (o modo), así dentro de un mismo modo quedan por frecuencia."""
    keyfn = {
        "name": lambda m: (m.name.casefold(), m.freq_hz),
        "freq": lambda m: (m.freq_hz, m.mode),
        "mode": lambda m: (m.mode, m.freq_hz),
    }.get(key, lambda m: (m.freq_hz, m.mode))
    return sorted(range(len(items)), key=lambda i: keyfn(items[i]), reverse=bool(desc))


def _clean(name, freq_hz, mode) -> "Memory | None":
    """Memory válida o None (fila rota de un archivo o de un CSV)."""
    try:
        f = int(round(float(freq_hz)))
    except (TypeError, ValueError):
        return None
    if f <= 0 or not isinstance(mode, str) or not isinstance(name, str):
        return None
    mode = mode.strip().upper()
    name = name.strip() or default_name(f, mode)
    return Memory(name, f, mode)


class MemoryStore:
    def __init__(self, path: "str | None" = None):
        self.path = path or os.path.join(data_dir(), FILE_NAME)
        self.items: "list[Memory]" = []
        self.sort_key, self.sort_desc = DEFAULT_SORT

    def __len__(self) -> int:
        return len(self.items)

    def load(self) -> None:
        self.items = []
        self.sort_key, self.sort_desc = DEFAULT_SORT
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        srt = data.get("sort") if isinstance(data, dict) else None
        if isinstance(srt, dict) and srt.get("key") in SORT_KEYS:
            self.sort_key, self.sort_desc = srt["key"], srt.get("desc") is True
        rows = data.get("memories") if isinstance(data, dict) else None
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict):
                m = _clean(r.get("name"), r.get("freq_hz"), r.get("mode"))
                if m is not None and self.find(m) is None:
                    self.items.append(m)
        self._sort()

    def save(self) -> None:
        data = {"version": 1,
                "sort": {"key": self.sort_key, "desc": self.sort_desc},
                "memories": [{"name": m.name, "freq_hz": m.freq_hz, "mode": m.mode}
                             for m in self.items]}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------

    def find(self, m: Memory) -> "int | None":
        """Índice de una memoria en la misma frecuencia y el mismo grupo de modo
        (USB y LSB en 7074 son la misma escucha para el usuario)."""
        g = cat.mode_group(m.mode) or m.mode
        for i, x in enumerate(self.items):
            if x.freq_hz == m.freq_hz and (cat.mode_group(x.mode) or x.mode) == g:
                return i
        return None

    def add(self, m: Memory) -> "tuple[int, bool]":
        """(índice, True si es nueva). Una que ya existe no se duplica."""
        i = self.find(m)
        if i is not None:
            return i, False
        self.items.append(m)
        self._sort()
        return self.items.index(m), True

    def remove(self, i: int) -> None:
        del self.items[i]

    def rename(self, i: int, name: str) -> None:
        m = self.items[i]
        self.items[i] = Memory(name.strip() or default_name(m.freq_hz, m.mode), m.freq_hz, m.mode)

    def _sort(self) -> None:
        self.items.sort(key=lambda m: (m.freq_hz, m.mode, m.name))

    # ------------------------------------------------------------------

    def export_csv(self, path: str) -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["name", "freq_khz", "mode"])
            for m in self.items:
                w.writerow([m.name, f"{m.freq_hz / 1000:.3f}".rstrip("0").rstrip("."), m.mode])

    def import_csv(self, path: str) -> int:
        """Agrega las filas válidas que no existan; devuelve cuántas agregó.
        Acepta ';' o ',' como separador y cualquier orden de columnas con cabecera."""
        with open(path, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        delim = ";" if text.count(";") >= text.count(",") else ","
        added = 0
        for r in csv.DictReader(text.splitlines(), delimiter=delim):
            r = {(k or "").strip().lower(): (v or "") for k, v in r.items()}
            try:
                hz = float(r.get("freq_khz", "").replace(",", ".")) * 1000
            except ValueError:
                continue
            m = _clean(r.get("name", ""), hz, r.get("mode", ""))
            if m is not None and self.add(m)[1]:
                added += 1
        return added
