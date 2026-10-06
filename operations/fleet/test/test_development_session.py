"""D-473 관제 콘솔 개발 연결 모드 — 세션 저장소, LAN 주소, Host/Origin, 상한, 만료."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from fleet.server.development_session import DevelopmentSessions, console_authority, lan_address


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("host", [
    "127.0.0.1", "10.1.2.3", "172.31.255.1", "192.168.0.9", "169.254.10.1",
    "::1", "fe80::1", "::ffff:192.168.1.5", "100.82.51.8", "100.64.0.1", "100.127.255.254",
])
def test_lan_address_accepts_loopback_rfc1918_and_link_local(host):
    assert lan_address(host)


@pytest.mark.parametrize("host", [
    "100.128.0.1", "172.32.0.1", "8.8.8.8", "2001:db8::1", "testclient", "", None,
])
def test_lan_address_refuses_everything_else(host):
    assert not lan_address(host)


@pytest.mark.parametrize(("host", "origin", "ok"), [
    ("192.168.1.10:8090", None, True),
    ("192.168.1.10:8090", "http://192.168.1.10:8090", True),
    ("rosy-site.local:8443", "https://rosy-site.local:8443", True),
    ("localhost:8090", "http://localhost:8090", True),
    ("[::1]:8090", "http://[::1]:8090", True),
    ("evil.example:8090", "http://evil.example:8090", False),  # DNS rebinding
    ("192.168.1.10:8090", "http://evil.example", False),
    ("192.168.1.10:8090", "http://192.168.1.10:9999", False),
    ("192.168.1.10:8090", "null", False),
    ("8.8.8.8", None, False),
    ("user@192.168.1.10:8090", None, False),
    (None, None, False),
])
def test_console_authority_requires_a_local_host_and_a_matching_origin(host, origin, ok):
    assert console_authority(host, origin) is ok


def test_session_is_a_named_operator_that_expires_after_one_hour():
    clock = Clock()
    sessions = DevelopmentSessions(clock=clock)
    token, principal, expires_at = sessions.issue()

    assert re.fullmatch(r"development-[0-9a-f]{8}", principal.principal_id)
    assert principal.role == "operator"
    assert expires_at == datetime.fromtimestamp(clock.now + 3600, timezone.utc).isoformat(timespec="seconds")
    assert sessions.principal(token) == principal
    clock.now += 3599
    assert sessions.principal(token) == principal
    clock.now += 1
    assert sessions.principal(token) is None
    assert sessions.principal("not-a-session") is None


def test_ninth_session_evicts_the_oldest():
    sessions = DevelopmentSessions(clock=Clock())
    tokens = [sessions.issue()[0] for _ in range(9)]

    assert sessions.principal(tokens[0]) is None
    assert all(sessions.principal(token) is not None for token in tokens[1:])


def test_six_requests_per_address_per_minute():
    clock = Clock()
    sessions = DevelopmentSessions(clock=clock)

    assert all(sessions.admit("192.168.1.50") for _ in range(6))
    assert not sessions.admit("192.168.1.50")
    assert sessions.admit("192.168.1.51")
    clock.now += 60
    assert sessions.admit("192.168.1.50")


def test_revoked_session_no_longer_authenticates():
    sessions = DevelopmentSessions()
    token, _, _ = sessions.issue()
    sessions.revoke(token)

    assert sessions.principal(token) is None
