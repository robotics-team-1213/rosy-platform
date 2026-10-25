"""D-876: reading monitoring evidence must never run the operational gather."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeRobot, run
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.console_routes import SharedGather
from fleet.swarm.robots import RobotEndpoint


READ_TOKEN = "monitoring-read-fixture"
AUTH = {"Authorization": "Bearer " + READ_TOKEN}


def row(robot_id="rosy_01", **changes):
    return {"robot_id": robot_id, "online": False, "link": "tls-refused",
            "link_reason": {"code": "PAIRING_REQUIRED", "message": "private-message"},
            "error": {"reachable": True, "message": "private-exception"},
            "state": {"token": "private-token", "battery": {"percent": 90}},
            "_state_mono": 0.0} | changes


def seeded(rows=None):
    clock = FakeClock()
    body = {"robots": rows if rows is not None else [row()]}
    counters = {"snapshot": 0, "observe": 0, "flush": 0}

    async def snapshot():
        counters["snapshot"] += 1
        if counters["snapshot"] > 1:
            raise AssertionError("monitoring initiated another operational gather")
        return body

    def observe(*_args):
        counters["observe"] += 1

    def flush():
        counters["flush"] += 1

    console = SimpleNamespace(snapshot=snapshot, _clock=clock,
                              hub=SimpleNamespace(registry=SimpleNamespace(events_since=lambda *_: ())))
    gather = SharedGather(console, SimpleNamespace(observe=observe, flush=flush), clock=clock)
    run(gather())
    return gather, clock, counters, body


def app_client():
    clock = FakeClock()
    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "fixture")],
                           [robot], clock=clock)
    users = {sha256(READ_TOKEN.encode()).hexdigest(): {"principal_id": "monitor-reader", "role": "viewer"}}
    app = create_app(console, site_users=users, start_task_dispatcher=False)
    app.state.fleet_gather._clock = clock
    return TestClient(app), clock, robot, console


def test_real_fleet_http_route_is_guarded_and_empty_cache_does_not_gather():
    client, _clock, robot, console = app_client()

    async def forbidden():
        raise AssertionError("monitoring must not gather, dispatch, hand off or refresh")

    console.snapshot = forbidden
    assert client.get("/api/fleet/monitoring").status_code == 401
    response = client.get("/api/fleet/monitoring", headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json() == {"schema_version": 1, "sampled_at": None, "cache_age_s": None, "robots": []}
    assert "no-store" in response.headers.get("cache-control", "")
    assert robot.calls == []


def test_real_fleet_http_route_preserves_stale_cache_without_robot_reads():
    client, clock, robot, console = app_client()
    gather = client.app.state.fleet_gather
    run(gather())
    calls = list(robot.calls)

    async def forbidden():
        raise AssertionError("a passive read started the operational gather")

    console.snapshot = forbidden
    first = client.get("/api/fleet/monitoring", headers=AUTH)
    assert first.status_code == 200, first.text
    clock.advance(12)
    second = client.get("/api/fleet/monitoring", headers=AUTH)
    assert second.status_code == 200, second.text
    assert second.json()["cache_age_s"] == pytest.approx(12)
    assert second.json()["sampled_at"] == first.json()["sampled_at"]
    assert second.json()["robots"][0]["state_age_s"] == pytest.approx(12)
    assert robot.calls == calls


def test_only_closed_connection_evidence_crosses_the_cache_boundary():
    gather, clock, counters, original = seeded()
    before = deepcopy(original)
    first = gather.cached_monitoring()
    clock.advance(12)
    value = gather.cached_monitoring()
    assert value.sampled_at == first.sampled_at
    assert value.cache_age_s == pytest.approx(12)
    assert value.robots[0].state_age_s == pytest.approx(12)
    assert value.robots[0].reachable is True and value.robots[0].reason_code == "PAIRING_REQUIRED"
    assert value.robots[0].link == "tls-refused"
    assert "private-" not in value.model_dump_json()
    assert "battery" not in value.model_dump_json() and "_state_mono" not in value.model_dump_json()
    assert original == before and counters == {"snapshot": 1, "observe": 1, "flush": 1}
    value.robots.clear()
    assert len(gather.cached_monitoring().robots) == 1


def test_incomplete_legacy_cache_publication_cannot_refresh_old_evidence():
    gather, clock, _counters, _body = seeded()
    original = gather.cached_monitoring()
    # Reproduce a read between the producer's legacy field assignments.
    gather._snapshot = {"robots": [row("rosy_02")]}
    gather._at = 5.0
    gather.gathered_at += 100.0
    clock.advance(5)
    value = gather.cached_monitoring()
    assert value.robots[0].robot_id == "rosy_01"
    assert value.sampled_at == original.sampled_at and value.cache_age_s == pytest.approx(5)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True])
def test_invalid_cache_clock_is_not_normalized_into_fresh_evidence(bad):
    gather, _clock, counters, _body = seeded()
    gather._clock = lambda: bad
    with pytest.raises(ValueError):
        gather.cached_monitoring()
    assert counters["snapshot"] == 1


@pytest.mark.parametrize("mono", [None, -1.0, float("inf"), True, 100.0])
def test_unknown_invalid_or_future_robot_clock_keeps_state_age_unknown(mono):
    gather, _clock, _counters, _body = seeded([row(_state_mono=mono)])
    assert gather.cached_monitoring().robots[0].state_age_s is None


def test_corrupt_cache_fails_closed_without_echoing_source_errors():
    client, _clock, _robot, _console = app_client()
    gather = client.app.state.fleet_gather
    run(gather())
    gather._clock = lambda: float("nan")
    response = client.get("/api/fleet/monitoring", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "FLEET_MONITORING_UNAVAILABLE"}}
