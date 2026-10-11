"""Real discovery-record, parser, HTTP and bounded-process contracts for rooms."""

from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_api_web.api.v1 import rooms
from core_common.discover import DiscoveredDevice


def device(host="robot-1.local", address="10.0.0.7", port=8080, tls="none", identity=None, service="_rosy._tcp"):
    txt = (("product", "rosy"), ("role", "robot"), ("proto", "core-v1"), ("tls", tls))
    return DiscoveredDevice(identity or host, service, host, port, (address,), txt)


def line(record, domain="local"):
    txt = " ".join(f'"{key}={value}"' for key, value in record.txt)
    return (f"=;eth0;IPv4;{record.instance};{record.service_type};{domain};"
            f"{record.host};{record.addresses[0]};{record.port};{txt}")


@pytest.fixture(autouse=True)
def empty_fallback_cache():
    with rooms._lock:
        rooms._inflight, rooms._expires, rooms._cached, rooms._error = False, 0, (), None


def client():
    app = FastAPI()
    app.include_router(rooms.rooms_router)
    return TestClient(app)


def test_actual_fqdn_tls_and_public_row_shape():
    result = rooms._parse_avahi(line(device(host="robot-1.local.", tls="required")))
    assert result == [{"hostname": "robot-1.local", "address": "10.0.0.7", "port": 8080,
                       "kind": "robot", "url": "https://robot-1.local:8080/pilot/#join"}]
    assert "token" not in result[0]
    assert rooms._parse_avahi(line(device()))[0]["url"] == "http://robot-1.local:8080/pilot/#join"


@pytest.mark.parametrize("record,domain", [(device(service="_rosy-fleet._tcp"), "local"),
                                           (device(), "other"), (device(address="127.0.0.1"), "local"),
                                           (device(address="fe80::1"), "local"), (device(host="evil.test"), "local")])
def test_actual_type_domain_address_and_hostname_are_classified(record, domain):
    assert rooms._parse_avahi(line(record, domain)) == []


def test_wrong_robot_role_and_duplicate_txt_are_rejected():
    record = device()
    for txt in (record.txt + (("role", "robot"),), tuple((k, "fleet" if k == "role" else v) for k, v in record.txt)):
        bad = DiscoveredDevice(record.instance, record.service_type, record.host, record.port, record.addresses, txt)
        assert rooms._parse_avahi(line(bad)) == []


def test_duplicate_interfaces_cap_and_late_identity_conflicts():
    records = [device(host=f"robot-{i}.local", address=f"10.0.0.{i+1}") for i in range(70)]
    assert len(rooms._rooms(records + records)) == 64
    assert len(rooms._parse_avahi("\n".join([line(device())] * 100))) == 1
    assert rooms._rooms(records + [device(host="robot-0.local", address="10.0.1.1")]) == [
        row for row in rooms._rooms(records) if row["hostname"] != "robot-0.local"]
    assert rooms._rooms([device(identity="same"), device(host="robot-2.local", identity="same")]) == []
    assert rooms._rooms([device(), device(port=9000)]) == []
    assert rooms._rooms([device(), device(tls="required")]) == []


def test_overflow_identity_conflict_removes_retained_row_without_admitting_new_host():
    records = [device(host=f"robot-{i}.local", address=f"10.0.0.{i+1}") for i in range(64)]
    # The row limit cannot conceal a competing advertisement for an admitted name.
    overflow = device(host="overflow.local", identity="robot-0.local")
    result = rooms._rooms(records + [overflow])
    assert len(result) == 63
    assert not any(row["hostname"] in ("robot-0.local", "overflow.local") for row in result)
    # More names on an already conflicting host are discarded without poisoning other owners.
    competing = [device(host="robot-0.local", identity=f"robot-{i}.local") for i in range(1, 64)]
    sizes = {}

    def trace(frame, event, _arg):
        if frame.f_code is rooms._rooms.__code__ and event == "return":
            sizes.update({key: len(frame.f_locals[key]) for key in ("found", "identities", "conflicts")})
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        assert rooms._rooms(records + [overflow] + competing) == result
    finally:
        sys.settrace(previous)
    assert sizes["found"] == sizes["identities"] == 64
    assert sizes["conflicts"] <= 64


def test_shared_live_cache_is_first_and_no_subprocess_or_stale_local_copy(monkeypatch):
    records = [device()]

    class Cache:
        def browse(self, service):
            assert service == "_rosy._tcp"
            return True

        def snapshot(self, service):
            return records
    monkeypatch.setattr(rooms, "get_shared_cache", lambda: Cache())
    monkeypatch.setattr(rooms, "_avahi_browse_robot", lambda **kw: pytest.fail("fallback must not run"))
    assert client().get("/api/v1/site/rooms").json()["rooms"][0]["hostname"] == "robot-1.local"
    records.clear()
    assert client().get("/api/v1/site/rooms").json() == {"rooms": []}


@pytest.mark.parametrize("failed", [False, True])
def test_parallel_http_get_singleflight_success_or_error_cache_and_expiry(monkeypatch, failed):
    entered, release = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(rooms, "get_shared_cache", lambda: type("Cache", (), {"browse": lambda self, s: False})())

    def browse(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(2)
        if failed:
            raise rooms._Unavailable("fixture unavailable")
        return rooms._rooms([device()])
    monkeypatch.setattr(rooms, "_avahi_browse_robot", browse)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(lambda: client().get("/api/v1/site/rooms")) for _ in range(8)]
        assert entered.wait(2)
        time.sleep(.05)
        release.set()
        responses = [job.result(timeout=3) for job in jobs]
    assert len(calls) == 1
    assert all(r.status_code == (503 if failed else 200) for r in responses)
    assert all(r.headers["Cache-Control"] == "no-store" for r in responses)
    assert client().get("/api/v1/site/rooms").status_code == (503 if failed else 200)
    assert len(calls) == 1
    with rooms._lock:
        rooms._expires = time.monotonic() - 1
    client().get("/api/v1/site/rooms")
    assert len(calls) == 2


def test_cached_result_cannot_be_mutated_by_a_caller(monkeypatch):
    monkeypatch.setattr(rooms, "_avahi_browse_robot", lambda **kw: rooms._rooms([device()]))
    first = rooms._fallback(timeout_s=1)
    first[0]["url"] = "bad"
    assert rooms._fallback(timeout_s=1)[0]["url"].startswith("http://robot-1.local:")


@pytest.mark.parametrize("script,error", [("import time; time.sleep(30)", "timed out"),
                                          ("import sys,time; sys.stdout.buffer.write(b'x'*200000); "
                                           "sys.stdout.flush(); time.sleep(30)", "limit")])
def test_actual_child_timeout_or_output_overflow_is_killed_and_reaped(monkeypatch, script, error):
    popen = subprocess.Popen
    children = []

    def start(_args, **kwargs):
        process = popen([sys.executable, "-c", script], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(rooms.subprocess, "Popen", start)
    before = time.monotonic()
    with pytest.raises(rooms._Unavailable, match=error):
        rooms._avahi_browse_robot(timeout_s=.4)
    assert time.monotonic() - before < 2
    assert children[0].poll() is not None
    assert children[0].stdout.closed


def test_completed_real_child_output_is_classified_and_reaped(monkeypatch):
    popen = subprocess.Popen
    children = []
    output = line(device(tls="required")) + "\n"

    def start(_args, **kwargs):
        process = popen([sys.executable, "-c", f"import sys; sys.stdout.write({output!r})"], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(rooms.subprocess, "Popen", start)
    result = rooms._avahi_browse_robot(timeout_s=1)
    assert result[0]["url"] == "https://robot-1.local:8080/pilot/#join"
    assert children[0].poll() == 0 and children[0].stdout.closed


def test_missing_avahi_does_not_become_a_successful_empty_scan(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(rooms.subprocess, "Popen", missing)
    with pytest.raises(rooms._Unavailable):
        rooms._fallback(timeout_s=1)
    with pytest.raises(rooms._Unavailable):
        rooms._fallback(timeout_s=1)


def test_unexpected_scan_failure_is_not_cached_as_empty_success(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("fixture unexpected failure")
    monkeypatch.setattr(rooms, "_avahi_browse_robot", broken)
    with pytest.raises(RuntimeError):
        rooms._fallback(timeout_s=1)
    with pytest.raises(rooms._Unavailable):
        rooms._fallback(timeout_s=1)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1, 5])
def test_invalid_time_bounds_do_not_start_discovery(value):
    with pytest.raises(ValueError):
        rooms.scan_robots(timeout_s=value)
