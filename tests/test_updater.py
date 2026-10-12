"""
Tests del aviso de versión nueva (sin red):
- parse_version / is_newer / is_due.
- UpdateChecker contra respuestas simuladas de GitHub (200 mayor/igual/menor, pre-release,
  403, 404, JSON roto, timeout, sin red, certificado).
- UpdateConfig: roundtrip y carga tolerante.
"""
import io
import json
import os
import sys
import tempfile
import urllib.error
from datetime import datetime, timedelta, timezone

if not os.environ.get("RNK_DATA_DIR"):
    os.environ["RNK_DATA_DIR"] = tempfile.mkdtemp(prefix="rnk_test_updater_")
os.environ["RNK_NO_UPDATE_CHECK"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import updater as up  # noqa: E402
from config import AppConfig  # noqa: E402
from version import APP_VERSION, display_version  # noqa: E402


class _Resp:
    def __init__(self, body: bytes):
        self._b = io.BytesIO(body)

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _release(tag="v2.7", **extra):
    d = {"tag_name": tag, "html_url": "https://github.com/x/y/releases/tag/" + tag,
         "body": "## Novedades\n- algo", "published_at": "2026-11-01T10:00:00Z",
         "draft": False, "prerelease": False}
    d.update(extra)
    return _Resp(json.dumps(d).encode("utf-8"))


def _opener(result):
    seen = []

    def op(req, timeout):
        seen.append(req)
        if isinstance(result, Exception):
            raise result
        return result
    op.seen = seen
    return op


def _check(result, current="2.6.0"):
    c = up.UpdateChecker(current, _opener(result))
    c.run_sync()
    return c


def test_version_parsing():
    assert up.parse_version("v2.6") == (2, 6, 0)
    assert up.parse_version("2.6.1") == (2, 6, 1)
    assert up.parse_version(" v2.10 ") == (2, 10, 0)
    for bad in ("", None, "latest", "v2", "v2.x", "2.6.1.4", "release-2.6"):
        assert up.parse_version(bad) is None, bad
    assert up.is_newer("v2.10", "2.9.0") and not up.is_newer("v2.9", "2.10.0")
    assert up.is_newer("v2.6.1", "2.6.0") and not up.is_newer("v2.6", "2.6.0")
    assert not up.is_newer("basura", "2.6.0") and not up.is_newer("v2.7", "basura")
    assert display_version("2.6.0") == "2.6" and display_version("2.6.1") == "2.6.1"
    assert up.parse_version(APP_VERSION) is not None
    print("Updater: version parseada y comparada (v2.10 > v2.9)  OK")


def test_is_due():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    assert up.is_due("", now) and up.is_due("basura", now)
    assert not up.is_due((now - timedelta(hours=23)).isoformat(), now)
    assert up.is_due((now - timedelta(hours=25)).isoformat(), now)
    assert up.is_due((now + timedelta(hours=5)).isoformat(), now), "reloj atrasado: no quedarse sin chequear"
    assert up.is_due((now - timedelta(hours=25)).replace(tzinfo=None).isoformat(), now)   # sin zona horaria
    print("Updater: limite de 24 h  OK")


def test_available_same_older():
    c = _check(_release("v2.7"))
    assert c.state == up.UpdateChecker.AVAILABLE
    r = c.result
    assert r["tag"] == "v2.7" and r["label"] == "v2.7" and r["version"] == "2.7.0"
    assert "Novedades" in r["notes"] and r["url"].endswith("v2.7")
    assert _check(_release("v2.6.1")).result["label"] == "v2.6.1"
    assert _check(_release("v2.6")).state == up.UpdateChecker.UP_TO_DATE
    assert _check(_release("v2.5")).state == up.UpdateChecker.UP_TO_DATE
    assert _check(_release("v2.7", prerelease=True)).state == up.UpdateChecker.UP_TO_DATE
    assert _check(_release("v2.7", draft=True)).state == up.UpdateChecker.UP_TO_DATE
    print("Updater: disponible / al dia / mas vieja / pre-release  OK")


def test_request_headers_and_long_notes():
    op = _opener(_release("v2.7", body="x" * 10000))
    c = up.UpdateChecker("2.6.0", op)
    c.run_sync()
    req = op.seen[0]
    assert req.full_url == up.API_URL and req.full_url.startswith("https://")
    assert req.get_header("User-agent") == "RadioNoiseKiller"
    assert len(c.result["notes"]) <= up.MAX_NOTES_CHARS + 2
    print("Updater: HTTPS, User-Agent y notas recortadas  OK")


def test_errors_never_raise():
    cases = {
        "403": urllib.error.HTTPError(up.API_URL, 403, "x", {}, None),
        "404": urllib.error.HTTPError(up.API_URL, 404, "x", {}, None),
        "500": urllib.error.HTTPError(up.API_URL, 500, "x", {}, None),
        "sin red": urllib.error.URLError("sin red"),
        "certificado": urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] bad"),
        "timeout": TimeoutError("timed out"),
        "json roto": _Resp(b"<html>nope</html>"),
        "sin tag": _Resp(b"{}"),
        "tag raro": _release("nightly"),
        "enorme": _Resp(b"x" * (up.MAX_BYTES + 10)),
    }
    for name, res in cases.items():
        c = _check(res)
        assert c.state == up.UpdateChecker.ERROR, (name, c.state)
        assert c.message, name
    assert "límite" in _check(cases["403"]).message
    assert "certificado" in _check(cases["certificado"]).message.lower()
    print("Updater: todos los errores quedan en estado ERROR con mensaje  OK")


def test_update_config_roundtrip_and_tolerant_load():
    c = AppConfig()
    c.update.auto_check, c.update.last_check, c.update.skipped_version = False, "2026-10-12T10:00:00+00:00", "v2.7"
    p = os.path.join(tempfile.mkdtemp(), "s.json")
    c.save(p)
    d = AppConfig()
    d.load(p)
    assert (d.update.auto_check, d.update.last_check, d.update.skipped_version) == (
        False, "2026-10-12T10:00:00+00:00", "v2.7")
    data = json.load(open(p))
    data["update"] = {"auto_check": "si", "last_check": None, "skipped_version": 5}
    json.dump(data, open(p, "w"))
    e = AppConfig()
    e.load(p)
    assert e.update.auto_check is True and e.update.last_check == "" and e.update.skipped_version == "5"
    f = AppConfig()
    assert f.update.auto_check is True, "default: activado"
    print("Updater: config guardada y carga tolerante  OK")


if __name__ == "__main__":
    test_version_parsing()
    test_is_due()
    test_available_same_older()
    test_request_headers_and_long_notes()
    test_errors_never_raise()
    test_update_config_roundtrip_and_tolerant_load()
    print()
    print("Todos los tests pasaron.")
