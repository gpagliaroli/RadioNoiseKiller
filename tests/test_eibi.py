"""
Tests de la solapa EiBi (sin red):
- Temporadas A/B y sus bordes.
- Parseo del CSV (Latin-1, CRLF, cabecera, filas rotas, persistencias).
- Búsqueda por frecuencia y "en el aire" (días, cruce de medianoche, fechas).
- Descarga con vencimiento: 304, 200 válido, 404 → temporada anterior, archivo corrupto,
  red caída — con un abridor HTTP simulado.
- Config (clamps == rango de los controles).
"""
import io
import os
import sys
import tempfile
import urllib.error
from datetime import date, datetime, timezone

if not os.environ.get("RNK_DATA_DIR"):
    os.environ["RNK_DATA_DIR"] = tempfile.mkdtemp(prefix="rnk_test_eibi_")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import eibi_db as db  # noqa: E402
from config import AppConfig, EIBI_FREQ_RANGE, EIBI_TOL_RANGE  # noqa: E402

HEADER = "kHz:75;Time(UTC):93;Days:59;ITU:49;Station:201;Lng:49;Target:62;Remarks:135;P:35;Start:60;Stop:60;"


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def _csv(rows, filler=0) -> bytes:
    lines = [HEADER] + rows
    # relleno de filas validas para superar MIN_ROWS en los tests de descarga
    lines += ["%d;0000-2400;;XXX;Relleno %d;E;Eu;;1;;" % (3000 + i, i) for i in range(filler)]
    return "\r\n".join(lines).encode("latin-1")


SAMPLE = _csv([
    "6140;0000-2400;;B;R\xe1dio Casa AM;P;LAm;am;1;;",             # todo el dia, con acento
    "6140;1900-2000;Mo-Fr;ARG;Radio Argentina;S;LAm;;1;;",          # dias de semana
    "6140;1900-0400;Sa;USA;Nocturna;E;Am;;1;;",                      # cruza la medianoche, solo sabado
    "6141.5;1200-1300;;CHN;China Radio;C;FE;;1;;",
    "6140;1900-2000;;XXX;Inactiva;E;Eu;;8;;",                        # P=8: se descarta
    "6140;1900-2000;irr;XXX;Irregular;E;Eu;;1;;",                    # dias no interpretables
    "6140;1900-2000;;CAN;Solo octubre;E;Am;;6;0110;2410",            # P=6: 1-oct a 24-oct
    "6140;1900-2000;;XXX;Utilidad;E;Eu;;91;;",                       # P=91: utilidad
    "fila rota sin campos",
    "abc;0000-2400;;X;Mala;E;Eu;;1;;",
    "7000;2500-2600;;X;Hora invalida;E;Eu;;1;;",
])


def test_season_for_borders():
    assert db.season_for(date(2026, 3, 28)) == "b25"   # antes del ultimo domingo de marzo
    assert db.season_for(date(2026, 3, 29)) == "a26"
    assert db.season_for(date(2026, 10, 24)) == "a26"
    assert db.season_for(date(2026, 10, 25)) == "b26"
    assert db.season_for(date(2027, 2, 1)) == "b26"    # invierno cruza el año
    assert db.previous_season("b26") == "a26" and db.previous_season("a26") == "b25"
    print("EiBi: temporadas A/B y bordes  OK")


def test_parse_csv():
    ents = db.parse_csv(SAMPLE)
    names = [e.station for e in ents]
    assert "Rádio Casa AM" in names, "Latin-1 mal decodificado"
    assert "Inactiva" not in names, "P=8 no se descarta"
    assert "Mala" not in names and "Hora invalida" not in names
    util = next(e for e in ents if e.station == "Utilidad")
    assert util.utility and util.persistence == 1
    rng = next(e for e in ents if e.station == "Solo octubre")
    assert rng.d0 == (10, 1) and rng.d1 == (10, 24)
    wrap = next(e for e in ents if e.station == "Nocturna")
    assert wrap.t0 == 19 * 60 and wrap.t1 == 4 * 60 and wrap.time_text == "1900-0400"
    assert next(e for e in ents if e.station == "Rádio Casa AM").time_text == "0000-2400"
    print("EiBi: parseo (Latin-1, filas rotas, P=6/8/9x)  OK")


def test_days_active():
    sat = date(2026, 10, 10)   # sabado
    assert db.days_active("", 5, sat) is True
    assert db.days_active("Mo-Fr", 5, sat) is False and db.days_active("Mo-Fr", 2, sat) is True
    assert db.days_active("SaSu", 5, sat) is True and db.days_active("Tu,Fr", 5, sat) is False
    assert db.days_active("We-Mo", 5, sat) is True and db.days_active("We-Mo", 1, sat) is False  # da la vuelta
    assert db.days_active("1245", 0, sat) is True and db.days_active("1245", 2, sat) is False   # lun, mar, jue, vie
    assert db.days_active("10Oct", 5, sat) is True and db.days_active("11Oct", 5, sat) is False
    assert db.days_active("irr", 5, sat) is None and db.days_active("Last7", 5, sat) is None
    assert db.days_active("Tu,irr", 5, sat) is None        # un dia no coincide pero hay algo no interpretable
    assert db.days_active("Tu,irr", 1, sat) is True
    print("EiBi: interpretacion de dias  OK")


def test_query_on_air_and_order():
    d = db.EibiDatabase(db.parse_csv(SAMPLE), "a26")
    now = utc(2026, 10, 10, 19, 30)    # sabado 19:30 UTC
    res = d.query(6140, 1, now)
    by = {m.entry.station: m.on_air for m in res}
    assert by["Rádio Casa AM"] is True
    assert by["Radio Argentina"] is False                 # Mo-Fr y hoy es sabado
    assert by["Nocturna"] is True                         # sabado 19:30 dentro de 1900-0400
    assert by["Irregular"] is None
    assert by["Solo octubre"] is True                     # 10-oct dentro de 1-oct..24-oct
    assert "Inactiva" not in by
    order = [m.on_air for m in res]
    rank = {True: 0, None: 1, False: 2}
    assert order == sorted(order, key=lambda v: rank[v]), "en el aire primero"
    # Tolerancia: 6141.5 queda dentro de +-2 pero fuera de +-1
    assert "China Radio" not in {m.entry.station for m in d.query(6140, 1, now)}
    assert "China Radio" in {m.entry.station for m in d.query(6140, 2, now)}
    # Utilidades: se pueden excluir
    assert "Utilidad" in by
    assert "Utilidad" not in {m.entry.station for m in d.query(6140, 1, now, include_utility=False)}
    print("EiBi: busqueda, en el aire, tolerancia y orden  OK")


def test_midnight_wrap_belongs_to_previous_day():
    d = db.EibiDatabase(db.parse_csv(SAMPLE), "a26")
    # 'Nocturna' es solo sabado 1900-0400: el domingo 02:00 UTC todavia es SU transmision
    dom_0200 = {m.entry.station: m.on_air for m in d.query(6140, 1, utc(2026, 10, 11, 2, 0))}
    assert dom_0200["Nocturna"] is True
    sab_0200 = {m.entry.station: m.on_air for m in d.query(6140, 1, utc(2026, 10, 10, 2, 0))}
    assert sab_0200["Nocturna"] is False        # ese sabado 02:00 es la cola del viernes
    print("EiBi: cruce de medianoche pertenece al dia anterior  OK")


def test_date_range_persistence_6():
    d = db.EibiDatabase(db.parse_csv(SAMPLE), "a26")
    fuera = {m.entry.station: m.on_air for m in d.query(6140, 1, utc(2026, 10, 30, 19, 30))}
    assert fuera["Solo octubre"] is False
    print("EiBi: P=6 solo entre las fechas  OK")


# ---------------------------------------------------------------------- #
# Descarga con vencimiento (abridor HTTP simulado)                         #
# ---------------------------------------------------------------------- #

class _Resp:
    def __init__(self, body: bytes, headers=None):
        self._b = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(script):
    """script: dict url_suffix -> (codigo | body | excepcion). Registra las requests."""
    log = []

    def op(req, timeout):
        log.append(req)
        key = req.full_url.rsplit("/", 1)[-1]
        v = script[key]
        if isinstance(v, Exception):
            raise v
        if isinstance(v, int):
            raise urllib.error.HTTPError(req.full_url, v, "x", {}, None)
        return v
    op.log = log
    return op


def _store():
    return db.EibiStore(tempfile.mkdtemp(prefix="rnk_eibi_store_"))


GOOD = _csv(["6140;0000-2400;;B;Radio X;P;LAm;;1;;"], filler=1200)


def test_updater_first_download_and_fresh_skips_network():
    st = _store()
    now = utc(2026, 10, 10, 12, 0)
    op = _opener({"sked-a26.csv": _Resp(GOOD, {"ETag": '"abc"', "Last-Modified": "Sun, 04 Oct 2026 12:53:56 GMT"})})
    up = db.EibiUpdater(st, op, lambda: now)
    up.run_sync()
    assert up.state == db.EibiUpdater.UPDATED, (up.state, up.message)
    assert st.meta()["season"] == "a26" and st.meta()["etag"] == '"abc"'
    assert len(st.load()) > 1000
    n = len(op.log)
    up2 = db.EibiUpdater(st, op, lambda: utc(2026, 10, 14, 12, 0))   # 4 dias despues: vigente
    up2.run_sync()
    assert up2.state == db.EibiUpdater.UP_TO_DATE and len(op.log) == n, "no debe tocar la red"
    print("EiBi: primera descarga y base vigente sin red  OK")


def test_updater_expired_sends_conditional_and_304_keeps_file():
    st = _store()
    t0 = utc(2026, 10, 1, 12, 0)
    db.EibiUpdater(st, _opener({"sked-a26.csv": _Resp(GOOD, {"ETag": '"abc"', "Last-Modified": "LM"})}),
                   lambda: t0).run_sync()
    op = _opener({"sked-a26.csv": 304})
    later = utc(2026, 10, 10, 12, 0)                  # 9 dias: vencida
    up = db.EibiUpdater(st, op, lambda: later)
    up.run_sync()
    assert up.state == db.EibiUpdater.UP_TO_DATE
    req = op.log[0]
    assert req.get_header("If-none-match") == '"abc"' and req.get_header("If-modified-since") == "LM"
    assert st.meta()["checked"] == later.isoformat() and st.meta()["downloaded"] == t0.isoformat()
    assert len(st.load()) > 1000
    print("EiBi: vencida -> consulta condicional, 304 conserva el archivo  OK")


def test_updater_force_ignores_age():
    st = _store()
    now = utc(2026, 10, 10, 12, 0)
    db.EibiUpdater(st, _opener({"sked-a26.csv": _Resp(GOOD, {})}), lambda: now).run_sync()
    op = _opener({"sked-a26.csv": 304})
    db.EibiUpdater(st, op, lambda: now).run_sync(force=True)
    assert len(op.log) == 1
    print("EiBi: 'Actualizar ahora' ignora el vencimiento  OK")


def test_updater_404_falls_back_to_previous_season():
    st = _store()
    op = _opener({"sked-b26.csv": 404, "sked-a26.csv": _Resp(GOOD, {"ETag": '"z"'})})
    up = db.EibiUpdater(st, op, lambda: utc(2026, 10, 26, 12, 0))     # b26 vigente pero no publicada
    up.run_sync()
    assert up.state == db.EibiUpdater.UPDATED and st.meta()["season"] == "a26"
    # y como la temporada guardada (a26) no es la vigente, la proxima vez vuelve a mirar si ya salio b26
    assert not st.is_fresh(utc(2026, 10, 27, 12, 0))
    print("EiBi: temporada nueva sin publicar -> usa la anterior  OK")


def test_updater_errors_keep_old_database():
    st = _store()
    now = utc(2026, 10, 1, 12, 0)
    db.EibiUpdater(st, _opener({"sked-a26.csv": _Resp(GOOD, {})}), lambda: now).run_sync()
    old = open(st.csv_path("a26"), "rb").read()
    later = utc(2026, 10, 20, 12, 0)
    for case, script in (
        ("corrupto", {"sked-a26.csv": _Resp(b"<html>error</html>", {})}),
        ("red caida", {"sked-a26.csv": urllib.error.URLError("sin red")}),
        ("500", {"sked-a26.csv": 500}),
    ):
        up = db.EibiUpdater(st, _opener(script), lambda: later)
        up.run_sync()
        assert up.state == db.EibiUpdater.ERROR, case
        assert open(st.csv_path("a26"), "rb").read() == old, "perdio la base buena (%s)" % case
        assert len(st.load()) > 1000
    print("EiBi: errores conservan la base anterior  OK")


def test_updater_no_database_and_all_404_is_error():
    up = db.EibiUpdater(_store(), _opener({"sked-b26.csv": 404, "sked-a26.csv": 404}),
                        lambda: utc(2026, 10, 26, 12, 0))
    up.run_sync()
    assert up.state == db.EibiUpdater.ERROR
    print("EiBi: sin base y sin archivo publicado -> error  OK")


def test_config_clamps():
    import json
    c = AppConfig()
    p = os.path.join(tempfile.mkdtemp(), "s.json")
    c.eibi.freq_khz, c.eibi.tol_khz, c.eibi.auto_update = 9560.5, 2.5, False
    c.save(p)
    d = AppConfig()
    d.load(p)
    assert (d.eibi.freq_khz, d.eibi.tol_khz, d.eibi.auto_update) == (9560.5, 2.5, False)
    data = json.load(open(p))
    data["eibi"].update(freq_khz=99999, tol_khz=-5)
    json.dump(data, open(p, "w"))
    e = AppConfig()
    e.load(p)
    assert e.eibi.freq_khz == EIBI_FREQ_RANGE[1] and e.eibi.tol_khz == EIBI_TOL_RANGE[0]
    data["eibi"].update(freq_khz="basura", tol_khz=None)
    json.dump(data, open(p, "w"))
    f = AppConfig()
    f.load(p)
    assert f.eibi.freq_khz == 6000.0 and f.eibi.tol_khz == 1.0
    print("EiBi: config guardada, clamps == rango de los controles  OK")


if __name__ == "__main__":
    test_season_for_borders()
    test_parse_csv()
    test_days_active()
    test_query_on_air_and_order()
    test_midnight_wrap_belongs_to_previous_day()
    test_date_range_persistence_6()
    test_updater_first_download_and_fresh_skips_network()
    test_updater_expired_sends_conditional_and_304_keeps_file()
    test_updater_force_ignores_age()
    test_updater_404_falls_back_to_previous_season()
    test_updater_errors_keep_old_database()
    test_updater_no_database_and_all_404_is_error()
    test_config_clamps()
    print()
    print("Todos los tests pasaron.")
