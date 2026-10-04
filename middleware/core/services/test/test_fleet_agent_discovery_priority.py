"""D-452: approved peer identity wins over a stale transport URL."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core_common.discover import DiscoveredDevice
from core_features.fleet_agent.agent import FleetAgent, fleet_link_configured
from core_features.fleet_agent.discovery import locate_fleet


def config(ca, **changes):
    return {"fleet": {"hub_url": "http://192.0.2.90:8080", "pairing_token": "approved-token",
                      "discovery": {"expected_hostname": "fleet-a.local", "ca_file": str(ca)},
                      **changes}}


class Events:
    def __init__(self):
        self.cleaned = False

    def subscribe(self, _callback):
        return lambda: setattr(self, "cleaned", True)


def candidate(address):
    return DiscoveredDevice("Fleet A", "_rosy-fleet._tcp", "fleet-a.local", 9443,
                            (address,), (("product", "rosy"), ("role", "fleet"),
                                         ("proto", "site-v1"), ("tls", "required")))


def test_start_prefers_discovery_and_keeps_legacy_only_without_a_profile(tmp_path):
    class Quiet(FleetAgent):
        async def _run(self, url, token):
            calls.append((url, token))

    calls = []

    async def exercise():
        for cfg in (config(tmp_path / "ca.crt"), config(tmp_path / "ca.crt", discovery={})):
            agent = Quiet(None, None, cfg, None)
            agent.start()
            await agent._task
            agent.stop()

    asyncio.run(exercise())
    assert calls == [("", "approved-token"), ("http://192.0.2.90:8080", "approved-token")]


@pytest.mark.parametrize("profile", [
    {"expected_hostname": "fleet-a.local"},
    {"expected_hostname": "fleet-a.local", "ca_file": "relative.pem"},
    {"expected_hostname": "foreign.example", "ca_file": "/etc/site.crt"},
    {"expected_hostname": "", "ca_file": "/etc/site.crt"},
    "invalid-profile",
])
def test_broken_trust_profile_never_downgrades_to_legacy_url(tmp_path, profile):
    cfg = config(tmp_path / "ca.crt", discovery=profile)
    assert not fleet_link_configured(cfg["fleet"])
    agent = FleetAgent(None, None, cfg, None)
    agent.start()
    assert not agent.enabled and agent._task is None


def test_one_time_credential_never_becomes_an_agent_token(tmp_path):
    cfg = config(tmp_path / "ca.crt", pairing_token="", pairing_credential="bootstrap-only")
    agent = FleetAgent(None, None, cfg, None)
    agent.start()
    assert not agent.enabled and agent._task is None


@pytest.mark.parametrize("second", ["dhcp", "expired", "conflict", "untrusted", "tls-rejected"])
def test_reconnect_rechecks_live_hints_without_identity_or_token_downgrade(tmp_path, monkeypatch, second):
    import core_features.fleet_agent.agent as module
    import websockets

    ca = tmp_path / "ca.crt"
    ca.write_text("fixture")
    first = candidate("192.0.2.10")
    next_rows = {
        "dhcp": [candidate("192.0.2.11")], "expired": [],
        "conflict": [candidate("192.0.2.11"), replace(candidate("192.0.2.12"), instance="Duplicate")],
        "untrusted": [replace(candidate("192.0.2.11"), txt=(("product", "rosy"), ("role", "fleet"), ("proto", "site-v1"), ("tls", "none")))],
        "tls-rejected": [candidate("192.0.2.11")],
    }[second]
    discoveries, probes, connections, tokens, contexts = [], [], [], [], []
    tls_context = object()
    events = Events()
    sessions = []

    class Cache:
        def wait(self, kind, *, timeout_s):
            assert kind == "_rosy-fleet._tcp" and timeout_s == 3
            discoveries.append(kind)
            if len(discoveries) == 1:
                return [first]
            if second in ("expired", "untrusted"):
                agent.enabled = False  # End the bounded fixture after observing absence.
            return next_rows

    cache = Cache()

    def probe(*args):
        if second == "tls-rejected" and args[0]["address"] == "192.0.2.11":
            raise module.ssl.SSLCertVerificationError("fixture peer identity rejected")
        probes.append(args)

    def resolve(host, ca_file):
        return locate_fleet(host, ca_file, cache=cache, probe=probe)

    def context(**kwargs):
        contexts.append(kwargs)
        return tls_context

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            sessions.append("closed")

    def connect(url, **options):
        connections.append((url, options))
        return Socket()

    class SessionAgent(FleetAgent):
        async def _session(self, _ws, token):
            tokens.append(token)
            if len(tokens) == 2:
                self.enabled = False
            return "fixture transport lost"

    agent = SessionAgent(None, events, config(ca), SimpleNamespace())
    monkeypatch.setattr(module, "locate_fleet", resolve)
    monkeypatch.setattr(module.ssl, "create_default_context", context)
    monkeypatch.setattr(module, "retry_delay", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(websockets, "connect", connect)

    async def exercise():
        agent.start()
        await asyncio.wait_for(agent._task, 2)

    asyncio.run(exercise())
    assert len(discoveries) == 2
    expected_addresses = ["192.0.2.10", "192.0.2.11"] if second == "dhcp" else ["192.0.2.10"]
    assert connections == [("wss://fleet-a.local:9443/ws/robots", {
        "ssl": tls_context, "proxy": None, "host": address, "port": 9443,
        "server_hostname": "fleet-a.local"}) for address in expected_addresses]
    assert contexts == [{"cafile": str(ca)}] * len(connections)
    assert tokens == ["approved-token"] * len(connections)
    assert [p[0]["address"] for p in probes] == expected_addresses
    assert all(p[1:] == ("fleet-a.local", ca) for p in probes)
    assert len(sessions) == len(connections) and events.cleaned
    assert not agent.connected and not agent.enabled
