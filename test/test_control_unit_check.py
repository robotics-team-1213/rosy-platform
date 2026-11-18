"""control_unit_check.py: the host check fails on non-mDNS peers and leftovers, with stubs only."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("control_unit_check", ROOT / "deploy/site/control_unit_check.py")
cuc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cuc)

MANIFEST = {"revision": "v1", "units": [{"id": "R"}, {"id": "A", "parent": "R", "resources": ["robot:x"]}]}


def test_digest_depends_on_content_not_on_order_or_revision_string_alone():
    shuffled = {"revision": "v1", "units": list(reversed(MANIFEST["units"]))}
    assert cuc.manifest_digest(MANIFEST) == cuc.manifest_digest(shuffled)
    changed = {"revision": "v1", "units": [{"id": "R"}, {"id": "A", "parent": "R", "resources": []}]}
    assert cuc.manifest_digest(MANIFEST) != cuc.manifest_digest(changed)


def test_peer_url_must_be_an_mdns_name(tmp_path):
    for url in ("https://127.0.0.1:8543", "https://peer-r:8544", "http://rosy-fleet-r.local:8544"):
        ok, step, detail = cuc.peer_check(url, tmp_path / "t", tmp_path / "ca", "v1", None, lookup=lambda _h: ["10.0.0.1"])
        assert (ok, step) == (False, "mdns-name") and "not an mDNS name" in detail


def test_unresolved_name_fails_at_resolve(tmp_path):
    ok, step, _ = cuc.peer_check("https://rosy-fleet-r.local:8544", tmp_path / "t", tmp_path / "ca", "v1", None,
                                 lookup=lambda _h: [])
    assert (ok, step) == (False, "resolve")


def test_host_check_needs_avahi_and_a_self_address():
    assert cuc.host_check("h", active=lambda: False)[1] == "avahi"
    assert cuc.host_check("h", active=lambda: True, lookup=lambda _n: [], local=set)[1] == "self-resolve"
    assert not cuc.host_check("h", active=lambda: True, lookup=lambda _n: ["10.0.0.9"], local=lambda: {"10.0.0.1"})[0]
    assert cuc.host_check("h", active=lambda: True, lookup=lambda _n: ["10.0.0.1"], local=lambda: {"10.0.0.1"})[0]


def test_advertised_name_is_the_avahi_host_name_not_the_os_hostname(tmp_path):
    conf = tmp_path / "avahi-daemon.conf"
    conf.write_text("[server]\n#host-name=foo\nhost-name=rosy-fleet-r\n", encoding="utf-8")
    assert cuc.advertised_name(conf) == "rosy-fleet-r"
    assert cuc.advertised_name(tmp_path / "missing.conf") == cuc.socket.gethostname().split(".")[0]


def test_only_the_parent_may_answer_parent_information_closed(tmp_path, monkeypatch):
    class Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(cuc.socket, "create_connection", lambda *a, **k: Sock())
    monkeypatch.setattr(cuc.ssl, "create_default_context", lambda **k: type("C", (), {"wrap_socket": lambda s, r, **k: Sock()})())
    (tmp_path / "t").write_text("tok")
    closed = b'{"detail":{"code":"CONTROL_UNIT_PARENT_INFORMATION_NOT_ENABLED"}}'
    request = lambda h, p, c, path, t, to: (200, b"ok") if path == "/healthz" else (403, closed)
    args = ("https://rosy-fleet-r.local:8544", tmp_path / "t", tmp_path / "ca", "v1", None)
    assert cuc.peer_check(*args, lookup=lambda _h: ["10.0.0.1"], request=request, is_parent=True)[0]
    assert cuc.peer_check(*args, lookup=lambda _h: ["10.0.0.1"], request=request)[1] == "auth"


def test_config_rows_without_printing_tokens(tmp_path):
    (tmp_path / "ca.pem").write_text("x")
    (tmp_path / "t.token").write_text("SECRET-TOKEN")
    (tmp_path / "control-unit.yaml").write_text(
        "unit_id: R\ntls_ca_file: ca.pem\nmanifest:\n  revision: v1\n  units:\n    - id: R\n    - id: A\n      parent: R\n"
        "peers:\n  A:\n    url: https://peer-a:8543\n    token_file: t.token\n", encoding="utf-8")
    rows = cuc.check_config(tmp_path / "control-unit.yaml", "h", active=lambda: True, local=lambda: {"10.0.0.1"})
    assert [(r["peer"], r["ok"], r["step"]) for r in rows][1:] == [("A", False, "mdns-name")]
    assert "SECRET-TOKEN" not in str(rows)
