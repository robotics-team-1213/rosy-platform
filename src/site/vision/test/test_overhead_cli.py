"""``rosy-vision`` CLI (and its ``site_vision``/``overhead`` aliases, D-377) — argument parsing and the parts that don't need a live server."""

from __future__ import annotations

import json
import ssl
from pathlib import Path

import pytest

from rosy_vision import protocol
from rosy_vision.cli import _detect_advertise_host, _server_ssl_context, main, parse_args

VECTORS = json.loads(
    (Path(__file__).resolve().parents[4] / "test" / "fixtures" / "protocol" / "overhead-ingest.v1.json")
    .read_text(encoding="utf-8")
)


def test_receive_defaults_match_the_design_doc():
    args = parse_args(["receive"])
    assert args.command == "receive"
    assert args.host == "0.0.0.0"
    assert args.port == 8095
    assert args.token_env == "ROSY_OVERHEAD_TOKEN"
    assert args.stats_jsonl is None
    assert args.advertise_host is None
    assert args.save_latest is None
    assert args.tls_cert is None and args.tls_key is None


def test_receive_accepts_every_documented_flag(tmp_path):
    stats_path = tmp_path / "stats.jsonl"
    save_dir = tmp_path / "latest"
    args = parse_args(
        [
            "receive",
            "--host",
            "127.0.0.1",
            "--port",
            "9001",
            "--token-env",
            "MY_TOKEN",
            "--source-name",
            "cam-north",
            "--stats-jsonl",
            str(stats_path),
            "--advertise-host",
            "site-pc.local",
            "--save-latest",
            str(save_dir),
        ]
    )
    assert args.host == "127.0.0.1"
    assert args.port == 9001
    assert args.token_env == "MY_TOKEN"
    assert args.source_name == "cam-north"
    assert args.stats_jsonl == stats_path
    assert args.advertise_host == "site-pc.local"
    assert args.save_latest == save_dir


def test_tls_server_requires_a_certificate_and_key_pair(tmp_path):
    assert _server_ssl_context(None, None) is None
    with pytest.raises(ValueError, match="provided together"):
        _server_ssl_context(tmp_path / "site.crt", None)


def test_detect_advertise_host_keeps_an_explicit_non_wildcard_host():
    assert _detect_advertise_host("192.168.1.20") == "192.168.1.20"


def test_detect_advertise_host_resolves_the_wildcard_to_something_non_empty():
    resolved = _detect_advertise_host("0.0.0.0")
    assert isinstance(resolved, str) and resolved


def test_pairing_uri_from_cli_args_round_trips():
    uri = protocol.pairing_uri("site-pc.local", 8095, "tok123", "overhead-1")
    parsed = protocol.parse_pairing_uri(uri)
    assert parsed == {
        "host": "site-pc.local",
        "port": 8095,
        "token": "tok123",
        "source": "overhead-1",
        "secure": False,
        "pin": None,
        "ws_url": f"ws://site-pc.local:8095{protocol.WS_PATH}",
    }


def test_old_console_scripts_are_aliases_of_rosy_vision(monkeypatch):
    """D-377 3: `site_vision` and `overhead` stay for one site candidate release, then stage 5 removes both."""
    import runpy

    import setuptools

    captured: dict = {}
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: captured.update(kwargs))
    package = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(package)
    runpy.run_path(str(package / "setup.py"), run_name="__main__")

    scripts = {}
    for spec in captured["entry_points"]["console_scripts"]:
        name, target = (part.strip() for part in spec.split("=", 1))
        scripts[name] = target
    assert captured["name"] == "rosy_vision"
    assert scripts == {"rosy-vision": "rosy_vision.cli:main", "site_vision": "rosy_vision.cli:main",
                       "overhead": "rosy_vision.cli:main"}


def test_pair_link_prints_a_pinned_wss_link_from_the_served_pem(tmp_path, monkeypatch, capsys):
    vector = VECTORS["cert_pins"]["vectors"][0]
    served = tmp_path / "site.crt"
    served.write_text(ssl.DER_cert_to_PEM_cert(b"leaf-stand-in")
                      + ssl.DER_cert_to_PEM_cert(vector["der_utf8"].encode("utf-8")), encoding="ascii")
    monkeypatch.setenv("CAM_TOKEN", "tok123")
    assert main(["pair-link", "--host", "192.168.1.102", "--port", "18447", "--source", "ceiling_north",
                 "--token-env", "CAM_TOKEN", "--pin-cert", str(served)]) == 0
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("pairing: "))
    parsed = protocol.parse_pairing_uri(line.removeprefix("pairing: "))
    assert parsed["secure"] is True
    assert parsed["pin"] == vector["pin"]
    assert parsed["ws_url"] == f"wss://192.168.1.102:18447{protocol.WS_PATH}"


def test_pair_link_refuses_to_run_without_the_token(tmp_path, monkeypatch):
    monkeypatch.delenv("CAM_TOKEN", raising=False)
    assert main(["pair-link", "--host", "h", "--port", "1", "--source", "s",
                 "--token-env", "CAM_TOKEN", "--pin-cert", str(tmp_path / "missing.crt")]) == 2


def _pem(tmp_path, name, *ders):
    path = tmp_path / name
    path.write_text("".join(ssl.DER_cert_to_PEM_cert(der) for der in ders), encoding="ascii")
    return path


def _run_pair_link(monkeypatch, capsys, *extra):
    monkeypatch.setenv("CAM_TOKEN", "tok123")
    code = main(["pair-link", "--host", "192.168.1.102", "--port", "18447", "--source", "ceiling_north",
                 "--token-env", "CAM_TOKEN", *extra])
    out = capsys.readouterr()
    lines = [l for l in out.out.splitlines() if l.startswith("pairing: ")]
    pin = protocol.parse_pairing_uri(lines[0].removeprefix("pairing: "))["pin"] if lines else None
    return code, pin, out.err


def test_pair_link_pins_the_ca_when_the_served_file_carries_it(tmp_path, monkeypatch, capsys):
    ca_der = VECTORS["cert_pins"]["vectors"][0]["der_utf8"].encode("utf-8")
    served = _pem(tmp_path, "site-fullchain.crt", b"leaf-stand-in", ca_der)
    ca = _pem(tmp_path, "site-ca.crt", ca_der)
    code, pin, err = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(ca), "--pin-cert", str(served))
    assert code == 0
    assert pin == VECTORS["cert_pins"]["vectors"][0]["pin"]
    assert "WARNING" not in err


def test_pair_link_refuses_a_ca_pin_the_proxy_does_not_serve(tmp_path, monkeypatch, capsys):
    served = _pem(tmp_path, "site.crt", b"leaf-stand-in")
    ca = _pem(tmp_path, "site-ca.crt", b"ca-stand-in")
    code, pin, err = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(ca), "--pin-cert", str(served))
    assert code == 2 and pin is None
    assert "site-fullchain.crt" in err


def test_pair_link_warns_when_it_can_only_pin_the_leaf(tmp_path, monkeypatch, capsys):
    served = _pem(tmp_path, "site.crt", b"leaf-stand-in")
    code, pin, err = _run_pair_link(monkeypatch, capsys, "--pin-cert", str(served))
    assert code == 0
    assert pin == protocol.cert_pin(b"leaf-stand-in")
    assert "WARNING" in err and "--pin-ca" in err


def test_pair_link_with_only_the_ca_notes_the_fullchain_requirement(tmp_path, monkeypatch, capsys):
    ca = _pem(tmp_path, "site-ca.crt", b"ca-stand-in")
    code, pin, err = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(ca))
    assert code == 0 and pin == protocol.cert_pin(b"ca-stand-in")
    assert "leaf + CA" in err


def test_pair_link_needs_a_pin_source(monkeypatch, capsys):
    code, pin, err = _run_pair_link(monkeypatch, capsys)
    assert code == 2 and pin is None
