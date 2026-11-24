"""Operator-pressed relocalization (panel decision 2026-11-14): routes, gate, audit.

Fakes only; the robot is a `FakeRobot` and the service a real `LocalizationService` on the
console's clients, like the map-pin route tests beside this file.
"""

import asyncio
import math
import time
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from core_common.protocol.localization import CandidateReport
from fakes import FakeRobot, fresh_reads
from fleet.server.app import create_app
from fleet.server.localization_service import LocalizationService
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.api.ports import RobotApiError

OPERATOR, NAMED, VIEWER = "operator-secret", "named-secret", "viewer-secret"


def _state(loc, frame="odom"):
    return {"robot_id": "r1", "map_id": "test-site", "map_grid_id": "occupancy:123456789012",
            "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "odom_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0, "stamp": time.time()},
            "localization": {"state": loc, "pose_frame": frame, "request_id": "q1"}}


def _report():
    return CandidateReport.model_validate({
        "robot_id": "r1", "request_id": "q1", "stamp": 1.0,
        "candidates": [{"x": 1.0, "y": 2.0, "yaw": 0.5, "scan_fit": 0.9},
                       {"x": -1.0, "y": -2.0, "yaw": 0.5 + math.pi, "scan_fit": 0.8}]})


def _app(tmp_path, with_service=True):
    robot = FakeRobot("r1", state=_state("CANDIDATES"))
    robot.candidates = _report()
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1"})
    users = {sha256(NAMED.encode()).hexdigest(): {"principal_id": "kim", "role": "operator"},
             sha256(VIEWER.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}}
    svc = LocalizationService(console.clients) if with_service else None
    app = create_app(console, console_token=OPERATOR, task_service=task_service,
                     start_task_dispatcher=False, site_users=users, localization_service=svc)
    fresh_reads(app)
    return app, robot


def _events(app, action):
    return [e for e in app.state.site_maps.events() if e["action"] == action]


# --- POST /relocalize --------------------------------------------------------------------------


def test_relocalize_needs_a_named_operator(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/fleet/robots/r1/relocalize").status_code == 401
        viewer = client.post("/api/fleet/robots/r1/relocalize",
                             headers={"Authorization": f"Bearer {VIEWER}"})
        assert viewer.status_code == 403


def test_relocalize_refuses_offline_trip_and_localized(tmp_path, monkeypatch):
    from fleet.server.trip_runner import TripRunner
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        named = {"Authorization": f"Bearer {NAMED}"}
        assert client.post("/api/fleet/robots/nope/relocalize", headers=named).status_code == 404
        robot.state_error = ConnectionError("down")
        offline = client.post("/api/fleet/robots/r1/relocalize", headers=named)
        assert offline.status_code == 409 and offline.json()["detail"]["code"] == "ROBOT_OFFLINE"
        robot.state_error = None
        monkeypatch.setattr(TripRunner, "robot_busy", lambda self, robot_id: True)
        trip = client.post("/api/fleet/robots/r1/relocalize", headers=named)
        assert trip.status_code == 409 and trip.json()["detail"]["code"] == "RELOCALIZE_TRIP_ACTIVE"
        monkeypatch.setattr(TripRunner, "robot_busy", lambda self, robot_id: False)
        robot._state = _state("LOCALIZED", "map")
        done = client.post("/api/fleet/robots/r1/relocalize", headers=named)
        assert done.status_code == 409
        assert done.json()["detail"]["code"] == "ALREADY_LOCALIZED"
        assert done.json()["detail"]["localization"]["state"] == "LOCALIZED"
    assert not _events(app, "relocalize")            # every refusal: no operator action taken


def test_a_press_allows_motion_starts_the_ladder_and_is_audited(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        reply = client.post("/api/fleet/robots/r1/relocalize",
                            headers={"Authorization": f"Bearer {NAMED}"})
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["requested_by"] == "kim" and body["motion_allowed"] is True
        assert body["mission"]["kind"] == "rotate_in_place" and body["mission"]["result"] == "sent"
        assert [m[0] for m in robot.missions] == ["rotate_in_place"]
        view = client.get("/api/fleet/robots/r1/localization",
                          headers={"Authorization": f"Bearer {VIEWER}"}).json()
        assert view["motion_allowed"] is True
        assert view["last_operator_request"]["by"] == "kim"
    [event] = _events(app, "relocalize")
    assert event["principal_id"] == "kim" and event["detail"]["robot_id"] == "r1"


def test_relocalize_without_the_localization_service_answers_503(tmp_path):
    app, _ = _app(tmp_path, with_service=False)
    with TestClient(app) as client:
        press = client.post("/api/fleet/robots/r1/relocalize",
                            headers={"Authorization": f"Bearer {NAMED}"})
        assert press.status_code == 503
        assert press.json()["detail"]["code"] == "LOCALIZATION_DISABLED"
        view = client.get("/api/fleet/robots/r1/localization",
                          headers={"Authorization": f"Bearer {VIEWER}"})
        assert view.status_code == 503


# --- GET /localization ------------------------------------------------------------------------


def test_localization_view_passes_through_what_fleet_reads(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        robot._state = _state("CANDIDATES")
        view = client.get("/api/fleet/robots/r1/localization",
                          headers={"Authorization": f"Bearer {VIEWER}"}).json()
        assert view["localization"]["state"] == "CANDIDATES"
        assert view["localization"]["request_id"] == "q1"
        assert [c["x"] for c in view["candidates"]["candidates"]] == [1.0, -1.0]
        assert view["candidates"]["request_id"] == "q1"
        assert view["motion_allowed"] is False and view["last_operator_request"] is None
        assert "ladder" in view                        # the service's own view, polled or not
        assert client.get("/api/fleet/robots/nope/localization",
                          headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 404


# --- POST /localization/confirm ---------------------------------------------------------------


def test_confirm_needs_a_named_operator(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/fleet/robots/r1/localization/confirm",
                           json={"candidate_id": 0}).status_code == 401
        viewer = client.post("/api/fleet/robots/r1/localization/confirm", json={"candidate_id": 0},
                             headers={"Authorization": f"Bearer {VIEWER}"})
        assert viewer.status_code == 403


def test_confirm_posts_the_reported_candidate_by_index_and_pose(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        named = {"Authorization": f"Bearer {NAMED}"}
        by_index = client.post("/api/fleet/robots/r1/localization/confirm",
                               json={"candidate_id": 0}, headers=named)
        assert by_index.status_code == 200, by_index.text
        assert by_index.json()["core"] == {"request_id": "q1"}
        by_pose = client.post("/api/fleet/robots/r1/localization/confirm",
                              json={"x": -1.0, "y": -2.0, "yaw": 0.5 + math.pi}, headers=named)
        assert by_pose.status_code == 200
        assert [d.pose.x for d in robot.decisions] == [1.0, -1.0]
        assert all(d.source == "human" and d.request_id == "q1" for d in robot.decisions)
        assert all(d.candidate_index is None for d in robot.decisions)   # a pose, not an index
    events = _events(app, "localization_confirm")    # newest first
    assert len(events) == 2
    assert all(e["principal_id"] == "kim" for e in events)
    assert [e["detail"]["candidate_index"] for e in events] == [1, 0]


def test_confirm_refuses_anything_the_robot_did_not_report(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        named = {"Authorization": f"Bearer {NAMED}"}
        for body in ({"candidate_id": 5}, {"x": 5.0, "y": 5.0, "yaw": 0.0}, {}):
            reply = client.post("/api/fleet/robots/r1/localization/confirm", json=body,
                                headers=named)
            assert reply.status_code in (404, 422), body
        assert client.post("/api/fleet/robots/r1/localization/confirm", json={"candidate_id": 0},
                           headers=named).status_code == 200   # a reported one still passes
    assert len(_events(app, "localization_confirm")) == 1


@pytest.mark.parametrize("outcome", ["matching", "wrong_pose", "new_grid", "wrong_receipt"])
def test_confirm_anchors_only_matching_core_localization(tmp_path, monkeypatch, outcome):
    app, robot = _app(tmp_path)
    service = app.state.localization_service
    if outcome == "wrong_receipt":
        async def wrong_receipt(decision):
            return {"request_id": "different"}
        monkeypatch.setattr(robot, "localization_decision", wrong_receipt)

    named = {"Authorization": f"Bearer {NAMED}"}
    reply = TestClient(app).post("/api/fleet/robots/r1/localization/confirm",
                                 json={"candidate_id": 0}, headers=named)
    assert reply.status_code == 200
    assert service.anchors() == set()

    robot._state = _state("LOCALIZED", "map")
    robot._state["pose"] = {"x": 1.0, "y": 2.0, "yaw": 0.5}
    if outcome == "wrong_pose":
        robot._state["pose"]["x"] = -1.0
    if outcome == "new_grid":
        robot._state["map_grid_id"] = "occupancy:987654321098"
    asyncio.run(service.tick())
    assert service.anchors() == ({"r1"} if outcome == "matching" else set())


def test_confirm_without_a_candidate_report_is_refused(tmp_path):
    app, robot = _app(tmp_path)
    robot.candidates = None
    with TestClient(app) as client:
        reply = client.post("/api/fleet/robots/r1/localization/confirm",
                            json={"candidate_id": 0}, headers={"Authorization": f"Bearer {NAMED}"})
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "NO_CANDIDATES"


@pytest.mark.parametrize("method", ["localization_candidates", "localization_decision"])
def test_confirm_reports_receiver_rate_limit(tmp_path, monkeypatch, method):
    app, robot = _app(tmp_path)

    async def limited(*args):
        raise RobotApiError("r1", 429, "RATE_LIMITED", "retry later", {"retry_after_s": 15})

    monkeypatch.setattr(robot, method, limited)
    with TestClient(app) as client:
        reply = client.post("/api/fleet/robots/r1/localization/confirm",
                            json={"candidate_id": 0}, headers={"Authorization": f"Bearer {NAMED}"})
    assert reply.status_code == 429
    assert reply.headers["Retry-After"] == "15"
    assert reply.json()["detail"]["code"] == "RATE_LIMITED"
    assert reply.json()["detail"]["retry_after_s"] == 15
    assert not _events(app, "localization_confirm")
