"""The bay-departure scenario route moves robots only when asked, with berth-park's gates (2868c99d7b review)."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fleet.server.ledger import berth_parking_scenario as scenario
from fleet.server.site_auth import SitePrincipal

URL = "/api/fleet/scenario/bay-departure"


def _client(monkeypatch, *, refusal=None, named=True, results=None):
    moved, anchors = [], []

    async def fake_physical(request, console, robot_id, spec, **kw):
        moved.append(robot_id)
        return (results or {}).get(robot_id) or {
            "executed": True, "succeeded": True, "after": {"site_pose": {"x": 0.0, "y": 0.47, "yaw": 0.0}}}

    def operator() -> SitePrincipal:
        if not named:
            raise HTTPException(403, {"code": "NAMED_OPERATOR_REQUIRED"})
        return SitePrincipal(principal_id="op-named", role="operator")

    monkeypatch.setattr(scenario, "_execute_physical_berth_park", fake_physical)
    app = FastAPI()
    app.state.tracking = SimpleNamespace(set_anchor=lambda *a, **k: anchors.append(a))
    scenario.install_berth_scenario_routes(app, console=SimpleNamespace(trip_refusal=lambda ids: refusal),
                                           operator_guard=[], require_named_operator=operator)
    return TestClient(app), moved, anchors


def test_empty_body_moves_nothing(monkeypatch):
    client, moved, anchors = _client(monkeypatch)
    res = client.post(URL)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "EXECUTE_PHYSICAL_REQUIRED"
    assert client.post(URL, json={}).status_code == 400
    assert client.post(URL, json={"execute_physical": "yes"}).status_code == 400
    assert not moved and not anchors


def test_plan_only_moves_and_pins_nothing(monkeypatch):
    client, moved, anchors = _client(monkeypatch)
    res = client.post(URL, json={"execute_physical": False})
    body = res.json()
    assert res.status_code == 200 and not moved and not anchors
    assert body["depart_order"] == ["rosy_46", "rosy_45", "rosy_42"]
    assert all(body["live_robots"][r]["site_pose"] is None for r in scenario.SCENARIO_ROBOTS)
    assert body["cell_contract_handoff"]["stop_place_id"] == "S3"


def test_physical_run_needs_an_idempotency_key(monkeypatch):
    client, moved, _ = _client(monkeypatch)
    res = client.post(URL, json={"execute_physical": True})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED" and not moved


def test_physical_run_needs_a_named_operator(monkeypatch):
    client, moved, _ = _client(monkeypatch, named=False)
    res = client.post(URL, json={"execute_physical": True}, headers={"Idempotency-Key": "k1"})
    assert res.status_code == 403 and not moved
    assert "Depends(require_named_operator)" in inspect.getsource(scenario.install_berth_scenario_routes)


def test_trip_latch_refuses_before_any_motion(monkeypatch):
    client, moved, _ = _client(monkeypatch, refusal=HTTPException(409, {"code": "TRIP_RUNNING"}))
    res = client.post(URL, json={"execute_physical": True}, headers={"Idempotency-Key": "k1"})
    assert res.status_code == 409 and not moved


def test_failed_park_stops_the_sequence_and_pins_nothing(monkeypatch):
    failed = {"executed": True, "succeeded": False, "stop_reason": "reverse_timeout", "after": {"site_pose": None}}
    client, moved, anchors = _client(monkeypatch, results={"rosy_46": failed})
    res = client.post(URL, json={"execute_physical": True}, headers={"Idempotency-Key": "k1"})
    body = res.json()
    assert res.status_code == 200 and moved == ["rosy_46"] and not anchors
    assert body["live_robots"]["rosy_46"]["pin_skipped"] == "NOT_MEASURED"
    assert "rosy_45" not in body["live_robots"]


def test_measured_parks_run_in_order_and_rosy_42_is_not_pinned(monkeypatch):
    client, moved, anchors = _client(monkeypatch)
    res = client.post(URL, json={"execute_physical": True}, headers={"Idempotency-Key": "k1"})
    body = res.json()
    assert res.status_code == 200 and moved == ["rosy_46", "rosy_45"] and not anchors
    assert body["live_robots"]["rosy_46"]["site_pose"]["y"] == 0.47
    assert body["live_robots"]["rosy_42"]["site_pose"] is None
    assert "_pin_robot_on_fleet" not in inspect.getsource(scenario)  # no preset S3 pin (R3)
