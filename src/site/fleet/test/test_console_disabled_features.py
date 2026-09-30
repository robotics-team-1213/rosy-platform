"""2026-09-30 tablet check: the console must not poll disabled Fleet features into a 404 storm.

A Fleet without task storage, discovery or enrollment does not install those routes, so they
answer FastAPI's plain 404 (no ``detail.code``). The console treats that as "not configured"
and stops polling until the next login; ``NO_MAP`` only slows the map poll. The gate logic
itself is covered by ``test/web/poll-gate.test.mjs``.
"""

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint

TOKEN = "operator-secret"


def _client():
    robot = FakeRobot("rosy-pinky-8kcn", state={"robot_id": "rosy-pinky-8kcn", "mode": "IDLE"})
    endpoints = [RobotEndpoint("rosy-pinky-8kcn", "http://127.0.0.1:8080", "robot-rest")]
    return TestClient(create_app(FleetConsole(endpoints, [robot]), console_token=TOKEN))


def test_disabled_feature_routes_answer_a_404_without_a_code():
    client = _client()
    headers = {"Authorization": f"Bearer {TOKEN}"}

    for path in ("/api/fleet/dispatch-control", "/api/fleet/discovery",
                 "/api/fleet/enrollment/robots"):
        response = client.get(path, headers=headers)
        assert response.status_code == 404, path
        detail = response.json().get("detail")
        assert not isinstance(detail, dict) or "code" not in detail, path

    no_map = client.get("/api/fleet/map", headers=headers)
    assert no_map.status_code == 404
    assert no_map.json()["detail"]["code"] == "NO_MAP"


def test_console_gates_disabled_feature_pollers():
    client = _client()

    gate = client.get("/console/assets/poll-gate.js")
    shell = client.get("/console/assets/console.js").text
    enrollment = client.get("/console/assets/enrollment.js").text
    map_view = client.get("/console/assets/map-view.js").text

    assert gate.status_code == 200
    assert "export function createPollGate" in gate.text
    assert "NO_MAP_RETRY_MS = 30000" in gate.text

    # dispatch-control (1 s) and discovery (5 s) stop on a route-absent 404.
    assert "if (!dispatchGate.due()) return view.dispatchControl;" in shell
    assert 'dispatchGate.fail(err.status, err.code) === "absent"' in shell
    assert "if (!discoveryGate.due()) return;" in shell
    assert 'discoveryGate.fail(err.status, err.code) === "absent"' in shell
    # Login / token save re-asks every disabled feature once.
    for reset in ("dispatchGate.reset();", "discoveryGate.reset();",
                  "enrollment.resetPolling();", "mapView.resetPolling();"):
        assert reset in shell

    assert "if (!gate.due()) return;" in enrollment
    assert "gate.fail(err.status, err.code);" in enrollment
    assert "error.status = resp.status;" in enrollment

    assert "createPollGate({ slowCodes: { NO_MAP: NO_MAP_RETRY_MS } })" in map_view
    assert "if (auth.locked || !mapGate.due()) return;" in map_view
