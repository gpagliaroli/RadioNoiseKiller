"""
Tests del control de la radio por rigctld (src/cat.py), sin radio ni Hamlib:
un rigctld FALSO en un hilo (socketserver en 127.0.0.1, puerto libre).
- RigctldClient: lee frecuencia y modo, RPRT de error, reconexión cuando el
  servidor se cae y vuelve, puerto cerrado.
- mode_group con todos los modos.
- AutoPresetSwitcher: espera la estabilidad, no repite, None no dispara.
- choose_preset: no pisa un preset modificado, ignora inexistente / "".
- CatConfig: roundtrip y carga tolerante.
"""
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time

if not os.environ.get("RNK_DATA_DIR"):
    os.environ["RNK_DATA_DIR"] = tempfile.mkdtemp(prefix="rnk_test_cat_")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cat  # noqa: E402
from config import AppConfig  # noqa: E402


class _FakeRig:
    """rigctld mínimo: responde f y m con el estado de la instancia."""

    def __init__(self, port: int = 0):
        self.freq, self.mode, self.passband = 7074000, "LSB", 2400
        self.fail_f = False
        self.conns = []
        rig = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                rig.conns.append(self.request)
                try:
                    for raw in self.rfile:
                        cmd = raw.decode().strip()
                        if cmd == "f":
                            out = "RPRT -11\n" if rig.fail_f else f"{rig.freq}\n"
                        elif cmd == "m":
                            out = f"{rig.mode}\n{rig.passband}\n"
                        else:
                            out = "RPRT -4\n"
                        self.wfile.write(out.encode())
                except OSError:
                    pass          # close() cortó la conexión: es lo que se prueba

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        """Como un rigctld que muere: deja de aceptar Y corta las conexiones."""
        self.server.shutdown()
        self.server.server_close()
        for s in self.conns:
            try:
                s.shutdown(socket.SHUT_RDWR)
                s.close()
            except OSError:
                pass


def _wait(cond, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _client(port):
    return cat.RigctldClient("127.0.0.1", port, poll_s=0.05, retry_s=0.2, timeout_s=0.5)


def test_client_reads_freq_and_mode():
    rig = _FakeRig()
    c = _client(rig.port)
    c.start()
    try:
        assert _wait(lambda: c.state.connected), c.state
        assert c.state.freq_hz == 7074000 and c.state.mode == "LSB"
        rig.freq, rig.mode = 14200000, "usb"
        assert _wait(lambda: c.state.freq_hz == 14200000 and c.state.mode == "USB"), c.state
    finally:
        c.stop()
        rig.close()
    assert c.state == cat.CatState(), "stop() deja el estado en reposo"
    print("CAT: lee frecuencia y modo (modo normalizado a mayúsculas)  OK")


def test_client_rprt_error_and_recovery():
    rig = _FakeRig()
    c = _client(rig.port)
    c.start()
    try:
        assert _wait(lambda: c.state.connected)
        rig.fail_f = True
        assert _wait(lambda: not c.state.connected and "RPRT -11" in c.state.error), c.state
        rig.fail_f = False
        assert _wait(lambda: c.state.connected), "se recupera tras el error"
    finally:
        c.stop()
        rig.close()
    print("CAT: RPRT de error -> desconectado con el código, y se recupera  OK")


def test_client_reconnects_after_server_restart():
    rig = _FakeRig()
    port = rig.port
    c = _client(port)
    c.start()
    try:
        assert _wait(lambda: c.state.connected)
        rig.close()
        assert _wait(lambda: not c.state.connected), "detecta la caída"
        rig = _FakeRig(port)
        rig.freq = 3700000
        assert _wait(lambda: c.state.connected and c.state.freq_hz == 3700000, 8.0), c.state
    finally:
        c.stop()
        rig.close()
    print("CAT: reconecta cuando rigctld vuelve  OK")


def test_client_closed_port_never_raises():
    rig = _FakeRig()
    port = rig.port
    rig.close()                      # puerto libre y cerrado
    c = _client(port)
    c.start()
    try:
        assert _wait(lambda: c.state.error != ""), "reporta el error de conexión"
        assert not c.state.connected and c.is_running(), "el hilo sigue reintentando"
    finally:
        t0 = time.monotonic()
        c.stop()
        assert time.monotonic() - t0 < 2.5, "stop() no se cuelga"
    print("CAT: puerto cerrado -> error y reintento, stop() inmediato  OK")


def test_mode_group():
    casos = {"USB": "SSB", "lsb": "SSB", "PKTUSB": "SSB", "PKTLSB": "SSB",
             "AM": "AM", "SAM": "AM", "AMS": "AM", "DSB": "AM",
             "FM": "FM", "PKTFM": "FM", "WFM": "WFM", "CW": "CW", "CWR": "CW",
             " usb ": "SSB", "RTTY": None, "": None, None: None}
    for m, g in casos.items():
        assert cat.mode_group(m) == g, (m, cat.mode_group(m), g)
    assert set(cat.DEFAULT_MODE_PRESETS) == set(cat.MODE_GROUPS)
    print("CAT: grupos de modo  OK")


def test_switcher_waits_stability_and_does_not_repeat():
    s = cat.AutoPresetSwitcher(stable_s=1.0)
    assert s.update("SSB", 0.0) is None, "primer tick: candidato"
    assert s.update("SSB", 0.5) is None, "todavía no se sostuvo 1 s"
    assert s.update("SSB", 1.0) == "SSB", "sostenido 1 s: aplica"
    assert s.update("SSB", 5.0) is None, "mismo grupo: no repite"
    # Giro del selector: pasa por AM medio segundo y cae en FM.
    assert s.update("AM", 6.0) is None
    assert s.update("FM", 6.5) is None, "cambió el candidato: reinicia la espera"
    assert s.update("FM", 7.0) is None
    assert s.update("FM", 7.5) == "FM", "AM nunca se aplicó"
    assert s.update(None, 8.0) is None, "modo desconocido: nada"
    assert s.update("FM", 9.0) is None, "None no borró el último aplicado"
    # Volver al aplicado mientras hay candidato lo descarta.
    assert s.update("SSB", 10.0) is None
    assert s.update("FM", 10.2) is None
    assert s.update("FM", 12.0) is None, "FM ya estaba aplicado"
    s.reset()
    assert s.update("FM", 13.0) is None and s.update("FM", 14.0) == "FM", "tras reset vuelve a aplicar"
    print("CAT: preset automático espera 1 s estable y no repite  OK")


def test_choose_preset_rules():
    mapping = {"SSB": "SSB X", "AM": "AM Y", "FM": "Borrado", "CW": ""}
    exists = {"SSB X", "AM Y"}.__contains__
    assert cat.choose_preset("SSB", mapping, exists, "", False) == ("SSB X", cat.LOAD), "sin activo carga"
    assert cat.choose_preset("SSB", mapping, exists, "AM Y", False) == ("SSB X", cat.LOAD)
    assert cat.choose_preset("SSB", mapping, exists, "AM Y", True) == (None, cat.MODIFIED), \
        "no pisa un preset con cambios sin guardar"
    assert cat.choose_preset("SSB", mapping, exists, "SSB X", False) == (None, cat.ALREADY)
    assert cat.choose_preset("FM", mapping, exists, "", False) == (None, cat.MISSING)
    assert cat.choose_preset("CW", mapping, exists, "", False) == (None, cat.UNMAPPED)
    assert cat.choose_preset("WFM", mapping, exists, "", False) == (None, cat.UNMAPPED)
    print("CAT: reglas de elección del preset  OK")


def test_default_mapping_points_to_factory_presets():
    root = os.path.join(os.path.dirname(__file__), "..", "Presets")
    names = set()
    for f in os.listdir(root):
        if f.endswith(".json"):
            names.add(json.load(open(os.path.join(root, f), encoding="utf-8"))["name"])
    for g, n in cat.DEFAULT_MODE_PRESETS.items():
        assert n == "" or n in names, f"{g}: el preset de fábrica '{n}' no existe"
    print("CAT: la tabla de fábrica apunta a presets que existen  OK")


def test_cat_config_roundtrip_and_tolerant_load():
    c = AppConfig()
    assert c.cat.enabled is False and c.cat.port == 4532 and c.cat.eibi_follow is True
    assert c.cat.mode_presets == cat.DEFAULT_MODE_PRESETS
    assert c.cat.mode_presets is not AppConfig().cat.mode_presets, "dict propio por instancia"
    c.cat.enabled, c.cat.host, c.cat.port, c.cat.eibi_follow = True, "192.168.1.5", 4533, False
    c.cat.mode_presets["CW"] = "Mi CW"
    p = os.path.join(tempfile.mkdtemp(), "s.json")
    c.save(p)
    d = AppConfig()
    d.load(p)
    assert (d.cat.enabled, d.cat.host, d.cat.port, d.cat.eibi_follow) == (True, "192.168.1.5", 4533, False)
    assert d.cat.mode_presets["CW"] == "Mi CW" and d.cat.mode_presets["SSB"] == cat.DEFAULT_MODE_PRESETS["SSB"]
    data = json.load(open(p))
    data["cat"] = {"host": "  ", "port": 999999, "mode_presets": {"SSB": 5, "AM": "Otro", "XX": "y"}}
    json.dump(data, open(p, "w"))
    e = AppConfig()
    e.load(p)
    assert e.cat.host == cat.DEFAULT_HOST and e.cat.port == 65535
    assert e.cat.mode_presets["SSB"] == cat.DEFAULT_MODE_PRESETS["SSB"], "valor no-texto ignorado"
    assert e.cat.mode_presets["AM"] == "Otro" and "XX" not in e.cat.mode_presets
    data["cat"] = "basura"
    json.dump(data, open(p, "w"))
    f = AppConfig()
    f.load(p)
    assert f.cat.enabled is False and f.cat.mode_presets == cat.DEFAULT_MODE_PRESETS
    print("CAT: config guardada y carga tolerante  OK")


if __name__ == "__main__":
    test_client_reads_freq_and_mode()
    test_client_rprt_error_and_recovery()
    test_client_reconnects_after_server_restart()
    test_client_closed_port_never_raises()
    test_mode_group()
    test_switcher_waits_stability_and_does_not_repeat()
    test_choose_preset_rules()
    test_default_mapping_points_to_factory_presets()
    test_cat_config_roundtrip_and_tolerant_load()
    print()
    print("Todos los tests pasaron.")
