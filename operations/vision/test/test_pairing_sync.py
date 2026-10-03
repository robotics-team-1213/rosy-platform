"""D-341 11-12: Vision's paired-credential view and its Fleet sync thread."""

from __future__ import annotations

import threading
import time
from hashlib import sha256

import pytest
from rosy_vision.pairing_sync import PairedCredentials, PairingSync, parse_listing

TOKEN_A = "a" * 10 + "-phone-one"
TOKEN_B = "b" * 10 + "-phone-two"


def _digest(token: str) -> bytes:
    return sha256(token.encode("utf-8")).digest()


def _row(token: str, source: str = "ceiling_north", credential_id: str = "cred-1",
         expires_at: str = "2099-01-01T00:00:00Z") -> dict:
    return {"credential_id": credential_id, "source_id": source,
            "token_sha256": sha256(token.encode()).hexdigest(), "expires_at": expires_at}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_state_is_unknown_until_the_first_sync():
    credentials = PairedCredentials(["ceiling_north"])
    assert credentials.check("ceiling_north", _digest(TOKEN_A)) == ("unavailable", None)
    assert credentials.check_any(_digest(TOKEN_A)) == "unavailable"


def test_synced_digest_admits_only_its_own_source():
    credentials = PairedCredentials(["ceiling_north", "ceiling_south"])
    credentials.replace([_row(TOKEN_A), _row(TOKEN_B, "ceiling_south", "cred-2")])
    assert credentials.check("ceiling_north", _digest(TOKEN_A)) == ("ok", "cred-1")
    assert credentials.check("ceiling_south", _digest(TOKEN_A)) == ("unknown", None)
    assert credentials.check("ceiling_north", _digest("nobody")) == ("unknown", None)
    assert credentials.check_any(_digest(TOKEN_B)) == "ok"
    assert credentials.check_any(_digest("nobody")) == "unknown"


def test_rows_for_unconfigured_or_static_sources_are_ignored():
    credentials = PairedCredentials(["ceiling_north"])
    credentials.replace([_row(TOKEN_A, "bench_static")])
    assert credentials.check_any(_digest(TOKEN_A)) == "unknown"


def test_a_list_older_than_ten_minutes_is_unknown_again():
    clock = Clock()
    credentials = PairedCredentials(["ceiling_north"], clock=clock)
    credentials.replace([_row(TOKEN_A)])
    clock.now += 600
    assert credentials.check("ceiling_north", _digest(TOKEN_A))[0] == "ok"
    clock.now += 0.1
    assert credentials.check("ceiling_north", _digest(TOKEN_A)) == ("unavailable", None)


def test_expired_credentials_are_unknown():
    wall = Clock()
    wall.now = 4_102_444_800.0  # 2100-01-01
    credentials = PairedCredentials(["ceiling_north"], wall=wall)
    credentials.replace([_row(TOKEN_A)])
    assert credentials.check("ceiling_north", _digest(TOKEN_A)) == ("unknown", None)


@pytest.mark.parametrize("body", [
    [], {"credentials": []}, {"role": "robot", "credentials": []},
    {"role": "overhead-camera", "credentials": [{"source_id": "x"}]},
    {"role": "overhead-camera", "credentials": [{**_row(TOKEN_A), "token_sha256": "ABC"}]},
    {"role": "overhead-camera", "credentials": [{**_row(TOKEN_A), "expires_at": "tomorrow"}]},
])
def test_malformed_listing_is_refused(body):
    with pytest.raises(ValueError):
        parse_listing(body)


def test_sync_keeps_the_last_good_list_when_fleet_fails():
    results = [{"role": "overhead-camera", "credentials": [_row(TOKEN_A)]}, OSError("fleet down")]
    calls = []
    credentials = PairedCredentials(["ceiling_north"])
    sync = PairingSync(credentials, fetch=lambda: _next(results), on_cycle=lambda: calls.append(1))
    sync.run_once()
    sync.run_once()
    assert credentials.check("ceiling_north", _digest(TOKEN_A)) == ("ok", "cred-1")
    assert calls == [1, 1]
    assert sync.failures == 1


def _next(results):
    item = results.pop(0)
    if isinstance(item, Exception):
        raise item
    return item


def test_sync_thread_is_not_starved_by_python_work_on_the_caller_thread():
    """2026-10-01 starvation lesson: the sync runs on its own thread, not the ingest loop."""
    fetched = []
    credentials = PairedCredentials(["ceiling_north"])

    def fetch():
        fetched.append(time.monotonic())
        return {"role": "overhead-camera", "credentials": []}

    sync = PairingSync(credentials, fetch=fetch, interval_s=0.05)
    sync.start()
    try:
        deadline = time.monotonic() + 0.8
        spin = 0
        while time.monotonic() < deadline:  # GIL-holding Python work, like a blocked loop
            spin += 1
        assert len(fetched) >= 5
    finally:
        sync.stop()
    assert not any(thread.name == "rosy-vision-pairing-sync" for thread in threading.enumerate()
                   if thread.is_alive())


def test_sync_needs_a_url_and_token_or_a_fetcher():
    with pytest.raises(ValueError):
        PairingSync(PairedCredentials(["ceiling_north"]))
    with pytest.raises(ValueError):
        PairingSync(PairedCredentials(["ceiling_north"]), url="ftp://fleet:8090", token="x")


@pytest.mark.parametrize("url, ca_file", [
    ("http://fleet:8090", "site-ca.crt"),     # plain HTTP: the sync token would cross the LAN in clear
    ("https://fleet:8090", None),             # no pinned site CA: a spoofer's cert would be accepted
])
def test_sync_refuses_http_or_an_unpinned_ca(url, ca_file):
    # Security review finding 2: either gap lets a LAN spoofer serve its own digest list.
    with pytest.raises(ValueError):
        PairingSync(PairedCredentials({"ceiling_north"}), url=url, token="t" * 43, ca_file=ca_file)
