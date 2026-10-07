"""``rosy-vision`` CLI (and its ``site_vision``/``overhead`` aliases, D-377) — argument parsing and the parts that don't need a live server."""

from __future__ import annotations

import json
import ssl
from pathlib import Path

import pytest

from rosy_vision import protocol
from rosy_vision.cli import _detect_advertise_host, _receive_pin, _server_ssl_context, main, parse_args

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "test" / "fixtures" / "protocol" / "overhead-ingest.v1.json")
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
    assert scripts == {"rosy-vision": "rosy_vision.cli:main", "rosy-lane-map": "rosy_vision.lane_map:main",
                       "site_vision": "rosy_vision.cli:main",
                       "overhead": "rosy_vision.cli:main"}


def _pem(tmp_path, name, *ders, bom=False):
    path = tmp_path / name
    text = "".join(ssl.DER_cert_to_PEM_cert(der) for der in ders)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("ascii"))
    return path


def _run_pair_link(monkeypatch, capsys, *extra):
    monkeypatch.setenv("CAM_TOKEN", "tok123")
    code = main(["pair-link", "--host", "192.168.1.102", "--port", "18447", "--source", "ceiling_north",
                 "--token-env", "CAM_TOKEN", *extra])
    out = capsys.readouterr()
    lines = [l for l in out.out.splitlines() if l.startswith("pairing: ")]
    parsed = protocol.parse_pairing_uri(lines[0].removeprefix("pairing: ")) if lines else None
    return code, parsed, out.err


def test_pair_link_pins_the_ca_the_proxy_serves_above_the_leaf(tmp_path, monkeypatch, capsys):
    vector = VECTORS["cert_pins"]["vectors"][0]
    ca_der = vector["der_utf8"].encode("utf-8")
    served = _pem(tmp_path, "site-fullchain.crt", b"leaf-stand-in", ca_der)
    ca = _pem(tmp_path, "site-ca.crt", ca_der, bom=True)
    code, parsed, _ = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(ca), "--pin-cert", str(served))
    assert code == 0
    assert parsed["secure"] is True
    assert parsed["pin"] == vector["pin"]
    assert parsed["ws_url"] == f"wss://192.168.1.102:18447{protocol.WS_PATH}"


def test_pair_link_refuses_a_leaf_only_proxy(tmp_path, monkeypatch, capsys):
    served = _pem(tmp_path, "site.crt", b"leaf-stand-in")
    ca = _pem(tmp_path, "site-ca.crt", b"ca-stand-in")
    code, parsed, err = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(ca), "--pin-cert", str(served))
    assert code == 2 and parsed is None
    assert "site-fullchain.crt" in err


def test_pair_link_never_pins_the_leaf_even_when_passed_as_the_ca(tmp_path, monkeypatch, capsys):
    served = _pem(tmp_path, "site-fullchain.crt", b"leaf-stand-in", b"ca-stand-in")
    leaf = _pem(tmp_path, "site.crt", b"leaf-stand-in")
    code, parsed, err = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(leaf), "--pin-cert", str(served))
    assert code == 2 and parsed is None
    assert "never a leaf" in err


@pytest.mark.parametrize("missing", ["--pin-ca", "--pin-cert"])
def test_pair_link_requires_both_the_ca_and_the_served_file(tmp_path, monkeypatch, capsys, missing):
    files = {"--pin-ca": _pem(tmp_path, "ca.crt", b"ca"), "--pin-cert": _pem(tmp_path, "full.crt", b"l", b"ca")}
    del files[missing]
    args = [part for flag, path in files.items() for part in (flag, str(path))]
    with pytest.raises(SystemExit) as excinfo:
        _run_pair_link(monkeypatch, capsys, *args)
    assert excinfo.value.code == 2


def test_pair_link_rejects_a_non_text_pem_cleanly(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "ca.crt"
    bad.write_bytes(b"\xff\xfe\x00garbage")
    served = _pem(tmp_path, "full.crt", b"l", b"ca")
    code, parsed, err = _run_pair_link(monkeypatch, capsys, "--pin-ca", str(bad), "--pin-cert", str(served))
    assert code == 2 and "not a PEM text file" in err


def test_pair_link_refuses_to_run_without_the_token(tmp_path, monkeypatch):
    monkeypatch.delenv("CAM_TOKEN", raising=False)
    assert main(["pair-link", "--host", "h", "--port", "1", "--source", "s", "--token-env", "CAM_TOKEN",
                 "--pin-ca", str(tmp_path / "ca.crt"), "--pin-cert", str(tmp_path / "full.crt")]) == 2


def test_receive_pins_only_a_served_ca(tmp_path, capsys):
    full = _pem(tmp_path, "full.crt", b"leaf-stand-in", b"ca-stand-in", bom=True)
    assert _receive_pin(full) == protocol.cert_pin(b"ca-stand-in")
    leaf_only = _pem(tmp_path, "site.crt", b"leaf-stand-in")
    assert _receive_pin(leaf_only) is None
    assert "leaf-only" in capsys.readouterr().out
    assert _receive_pin(tmp_path / "missing.crt") is None
