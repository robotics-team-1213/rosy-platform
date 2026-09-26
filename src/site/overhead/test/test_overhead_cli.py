"""``rosy_overhead`` CLI — argument parsing and the parts that don't need a live server."""

from __future__ import annotations

import pytest

from overhead import protocol
from overhead.cli import _detect_advertise_host, _server_ssl_context, parse_args


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
        "ws_url": f"ws://site-pc.local:8095{protocol.WS_PATH}",
    }
