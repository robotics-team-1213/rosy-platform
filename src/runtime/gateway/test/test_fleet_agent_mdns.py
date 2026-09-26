"""FleetAgent may use DNS-SD for location only after operator pairing."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from core_features.fleet_agent.discovery import locate_fleet, parse_avahi
from core_features.fleet_agent.agent import FleetAgent


def _row(address="192.168.1.20", hostname="fleet-a.local", port=8443):
    return (f'=;eth0;IPv4;ROSY Fleet;_rosy-fleet._tcp;local;{hostname};'
            f'{address};{port};"product=rosy" "role=fleet" '
            '"proto=site-v1" "tls=required"')


def test_resolved_site_is_selected_only_by_expected_hostname_and_ca(tmp_path, monkeypatch):
    ca = tmp_path / "site-ca.crt"
    ca.write_text("fixture", encoding="utf-8")
    output = _row() + "\n" + _row(address="192.168.1.30", hostname="other.local")
    calls = []

    def runner(args, **kwargs):
        assert args[-1] == "_rosy-fleet._tcp"
        return SimpleNamespace(stdout=output)

    def probe(candidate, expected, ca_file):
        calls.append((candidate, expected, ca_file))

    assert locate_fleet("fleet-a.local", ca, runner=runner, probe=probe) == \
        "https://fleet-a.local:8443"
    assert calls == [({"hostname": "fleet-a.local", "address": "192.168.1.20",
                       "port": 8443}, "fleet-a.local", ca)]


def test_unknown_duplicate_or_invalid_site_cannot_be_selected(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_text("fixture", encoding="utf-8")
    output = _row() + "\n" + _row(address="192.168.1.21")

    def runner(*_args, **_kwargs):
        return SimpleNamespace(stdout=output)
    with pytest.raises(ValueError, match="ambiguous"):
        locate_fleet("fleet-a.local", ca, runner=runner, probe=lambda *_a: None)
    with pytest.raises(ValueError, match="not found"):
        locate_fleet("missing.local", ca, runner=runner, probe=lambda *_a: None)
    with pytest.raises(ValueError, match="local hostname"):
        locate_fleet("fleet-a.example", ca, runner=runner, probe=lambda *_a: None)
    with pytest.raises(ValueError, match="CA file"):
        locate_fleet("fleet-a.local", Path("missing.crt"), runner=runner,
                     probe=lambda *_a: None)
    assert parse_avahi(_row(hostname="evil.example")) == []
    assert parse_avahi(_row().replace('"tls=required"', '"tls=none"')) == []


def test_agent_requires_persistent_pairing_token_before_mdns_work():
    class State:
        pass

    class Events:
        pass

    class Identity:
        pass

    agent = FleetAgent(State(), Events(), {"fleet": {"discovery": {
        "expected_hostname": "fleet-a.local", "ca_file": "/etc/rosy/site-ca.crt"},
        "pairing_credential": "one-time-bootstrap-only"}}, Identity())
    agent.start()
    assert agent.enabled is False
    assert agent.connected is False


def test_agent_starts_discovery_only_with_approved_token(tmp_path):
    seen = []

    class QuietAgent(FleetAgent):
        async def _run(self, hub_url, pairing_token):
            seen.append((hub_url, pairing_token))

    async def exercise():
        agent = QuietAgent(object(), object(), {"fleet": {
            "pairing_token": "approved-agent-token",
            "discovery": {"expected_hostname": "fleet-a.local",
                          "ca_file": str(tmp_path / "site-ca.crt")}}}, object())
        agent.start()
        await asyncio.sleep(0)
        assert agent.enabled is True
        assert seen == [("", "approved-agent-token")]
        agent.stop()

    asyncio.run(exercise())


def test_agent_reaches_verified_mdns_url_with_site_ca(tmp_path, monkeypatch):
    import core_features.fleet_agent.agent as agent_module
    import websockets

    ca = tmp_path / "site-ca.crt"
    ca.write_text("fixture", encoding="utf-8")
    seen = []
    ready = asyncio.Event()
    tls_context = object()

    def locate(hostname, ca_file):
        seen.append((hostname, ca_file))
        return "https://fleet-a.local:8443"

    def connect(url, **options):
        seen.append((url, options))
        ready.set()
        raise OSError("simulated site outage")

    class Events:
        def subscribe(self, _cb):
            pass

        def unsubscribe(self, _cb):
            pass

    monkeypatch.setattr(agent_module, "locate_fleet", locate)
    monkeypatch.setattr(agent_module.ssl, "create_default_context", lambda **_kw: tls_context)
    monkeypatch.setattr(websockets, "connect", connect)

    async def exercise():
        agent = FleetAgent(object(), Events(), {"fleet": {
            "pairing_token": "approved-agent-token",
            "discovery": {"expected_hostname": "fleet-a.local", "ca_file": str(ca)}}},
            object())
        agent.start()
        await asyncio.wait_for(ready.wait(), timeout=2)
        agent.stop()
        await asyncio.sleep(0)

    asyncio.run(exercise())
    assert seen[0] == ("fleet-a.local", ca)
    assert seen[1] == ("wss://fleet-a.local:8443/ws/robots",
                       {"ssl": tls_context, "proxy": None})
