"""Pairing links carry a ``.local`` name by default; an IP is a warned fallback (D-391, D-341 13)."""

from __future__ import annotations

import asyncio
import json
import ssl
from pathlib import Path

import pytest

from rosy_vision import cli, protocol

VECTORS = json.loads(
    (Path(__file__).resolve().parents[4] / "test" / "fixtures" / "protocol" / "overhead-ingest.v1.json")
    .read_text(encoding="utf-8")
)


class _Ws:
    def close(self):
        pass

    async def wait_closed(self):
        pass


def _receive_link(monkeypatch, capsys, *extra, hostname="Site-PC"):
    """Run ``receive`` far enough to print its link, then stop on the first sleep."""

    async def _start(self, *args, **kwargs):
        return _Ws()

    async def _stop(_):
        raise KeyboardInterrupt

    monkeypatch.setenv("ROSY_OVERHEAD_TOKEN", "tok123")
    monkeypatch.setattr(cli.IngestServer, "start", _start)
    monkeypatch.setattr(cli.asyncio, "sleep", _stop)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: hostname)
    monkeypatch.setattr(cli, "_detect_advertise_host", lambda host: "10.9.8.7")
    try:
        code = asyncio.run(cli._run_receive(cli.parse_args(["receive", *extra])))
    except KeyboardInterrupt:
        code = 0
    out = capsys.readouterr()
    lines = [line for line in out.out.splitlines() if line.startswith("pairing: ")]
    parsed = protocol.parse_pairing_uri(lines[0].removeprefix("pairing: ")) if lines else None
    return code, parsed, out, lines


def test_receive_link_defaults_to_the_local_hostname_not_the_route_ip(monkeypatch, capsys):
    code, parsed, out, lines = _receive_link(monkeypatch, capsys)
    assert code == 0
    assert parsed["host"] == "site-pc.local"
    assert "IP fallback: 10.9.8.7" in out.out
    assert "10.9.8.7" not in lines[0]
    assert "WARNING" not in out.err


def test_receive_tls_host_overrides_the_hostname(monkeypatch, capsys):
    _, parsed, _, _ = _receive_link(monkeypatch, capsys, "--tls-host", "Rosy-Site.local")
    assert parsed["host"] == "rosy-site.local"


@pytest.mark.parametrize("bad", ["site-pc", "site_pc.local", "10.0.0.5", "a.b.local"])
def test_receive_rejects_a_tls_host_that_is_not_a_dot_local_name(monkeypatch, capsys, bad):
    code, parsed, out, _ = _receive_link(monkeypatch, capsys, "--tls-host", bad)
    assert code == 2 and parsed is None
    assert ".local" in out.err


def test_receive_rejects_a_hostname_that_cannot_be_a_dot_local_name(monkeypatch, capsys):
    code, parsed, out, _ = _receive_link(monkeypatch, capsys, hostname="bad_host")
    assert code == 2 and parsed is None
    assert "--tls-host" in out.err


def test_receive_explicit_ip_advertise_host_is_allowed_with_a_warning(monkeypatch, capsys):
    code, parsed, out, _ = _receive_link(monkeypatch, capsys, "--advertise-host", "192.0.2.9")
    assert code == 0 and parsed["host"] == "192.0.2.9"
    assert "수동 주소" in out.err and "IP SAN" in out.err


def _pair_link_args(tmp_path, host):
    ca_der = VECTORS["cert_pins"]["vectors"][0]["der_utf8"].encode("utf-8")
    served = tmp_path / "site-fullchain.crt"
    ca = tmp_path / "site-ca.crt"
    served.write_text(ssl.DER_cert_to_PEM_cert(b"leaf-stand-in") + ssl.DER_cert_to_PEM_cert(ca_der))
    ca.write_text(ssl.DER_cert_to_PEM_cert(ca_der))
    return ["pair-link", "--host", host, "--port", "8443", "--source", "ceiling_north",
            "--token-env", "CAM_TOKEN", "--pin-ca", str(ca), "--pin-cert", str(served)]


def test_pair_link_warns_on_an_ip_host_but_still_succeeds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CAM_TOKEN", "tok123")
    assert cli.main(_pair_link_args(tmp_path, "192.0.2.9")) == 0
    out = capsys.readouterr()
    assert "pairing: rosyov://192.0.2.9:8443/" in out.out
    for needle in ("WARNING", "수동 주소", "subnet", "IP SAN", ".local"):
        assert needle in out.err


def test_pair_link_does_not_warn_on_a_local_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CAM_TOKEN", "tok123")
    assert cli.main(_pair_link_args(tmp_path, "site-pc.local")) == 0
    assert "WARNING" not in capsys.readouterr().err
