"""D-407 lane stuck decisions on Fleet: tracking, forwarding, CORE refusal passthrough, auth."""

from __future__ import annotations

import uuid
from hashlib import sha256

import httpx
import pytest
from fastapi.testclient import TestClient

from core_common.protocol.schemas import EventMessage
from fakes import FakeClock, FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.console_routes import LineStuckDecisionRequest
from fleet.server.line_stuck import LineStuckAnswerLog, LineStuckBoard
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

STUCK = {"stuck_id": "stuck-abc", "cause": "obstacle_ahead", "phase": "ASKING",
         "held_s": 3.5, "attempts": 0, "max_attempts": 2, "local_enabled": False,
         "ask_remaining_s": 11.5, "last_answer": None,
         "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]}
OPERATOR, VIEWER = "operator-token", "viewer-token"


def _state(stuck=STUCK) -> dict:
    return {"robot_id": "rosy_01", "mode": "NAVIGATION", "safety": {"estop": False},
            "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": stuck}}


def _console(robot: FakeRobot, clock=None) -> FleetConsole:
    endpoint = RobotEndpoint(robot.robot_id, "http://127.0.0.1:8080", "rest-token")
    return FleetConsole([endpoint], [robot], **({"clock": clock} if clock else {}))


def _named_app(console: FleetConsole, tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    app = create_app(
        console, task_service=FleetTaskService(store, robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
        site_users={
            sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "op-7", "role": "operator"},
            sha256(VIEWER.encode()).hexdigest(): {"principal_id": "watcher", "role": "viewer"},
        })
    return TestClient(app), store


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _opened_event(stuck_id="stuck-abc", seq=4) -> EventMessage:
    return EventMessage(seq=seq, robot_id="rosy_01", type="nav.line_stuck_opened",
                        data={"stuck_id": stuck_id, "cause": "obstacle_ahead",
                              "front_clearance_m": 0.12, "rear_clearance_m": 0.31,
                              "turn_clearance_m": 0.09, "rear_blind_m": 0.05,
                              "preview_seq": 812, "last_lane": None})


def _row(client) -> dict:
    response = client.get("/api/fleet/state", headers=_auth(VIEWER))
    assert response.status_code == 200, response.text
    return response.json()["robots"][0]


def test_the_state_row_carries_the_open_stuck_with_clearances_from_the_opened_event(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    console = _console(robot)
    console.hub.registry.record("rosy_01").events.extend(
        [_opened_event("stuck-old", 2), _opened_event()])
    client, _ = _named_app(console, tmp_path)

    stuck = _row(client)["line_stuck"]
    assert stuck["stuck_id"] == "stuck-abc" and stuck["phase"] == "ASKING"
    assert stuck["cause"] == "obstacle_ahead" and stuck["max_attempts"] == 2
    assert stuck["front_clearance_m"] == 0.12 and stuck["rear_clearance_m"] == 0.31
    assert stuck["turn_clearance_m"] == 0.09 and stuck["preview_seq"] == 812
    assert stuck["opened_event"] is True and stuck["robot_online"] is True
    assert stuck["fleet_answer"] is None


def test_without_the_agent_event_the_stuck_still_shows_with_unknown_clearances(tmp_path):
    client, _ = _named_app(_console(FakeRobot("rosy_01", state=_state())), tmp_path)

    row = _row(client)

    assert row["line_stuck"]["stuck_id"] == "stuck-abc"
    assert row["line_stuck"]["front_clearance_m"] is None
    assert row["line_stuck"]["opened_event"] is False


def test_a_closed_stuck_leaves_the_list_and_an_unreachable_robot_keeps_it_marked(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    client, _ = _named_app(_console(robot), tmp_path)
    _row(client)

    robot.state_error = ConnectionError("down")
    held = _row(client)["line_stuck"]
    assert held["stuck_id"] == "stuck-abc" and held["robot_online"] is False

    robot.state_error = None
    robot._state = _state(stuck=None)
    assert _row(client)["line_stuck"] is None
    assert client.app.state.line_stuck.pending() == []


def test_board_reports_how_old_its_observation_is():
    clock = FakeClock()
    board = LineStuckBoard(clock)
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state()}])
    clock.advance(2.5)
    assert board.view("rosy_01")["observed_age_s"] == 2.5


def test_list_route_serves_the_last_gather_without_asking_the_robots_again(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    client, _ = _named_app(_console(robot), tmp_path)

    assert client.get("/api/fleet/line-stuck").status_code == 401
    before = client.get("/api/fleet/line-stuck", headers=_auth(VIEWER)).json()
    assert before == {"pending": [], "answers": [], "observed_age_s": None}
    _row(client)
    reads = robot.calls.count(("state",))
    listed = client.get("/api/fleet/line-stuck", headers=_auth(VIEWER))

    assert listed.status_code == 200
    assert [p["stuck_id"] for p in listed.json()["pending"]] == ["stuck-abc"]
    assert listed.json()["answers"] == [] and listed.json()["observed_age_s"] is not None
    assert robot.calls.count(("state",)) == reads


def test_an_operator_answer_is_forwarded_and_audited_with_the_principal(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    console = _console(robot)
    client, store = _named_app(console, tmp_path)

    response = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                           json={"stuck_id": "stuck-abc", "decision": "WAIT"},
                           headers=_auth(OPERATOR))

    assert response.status_code == 200, response.text
    durable = LineStuckAnswerLog(store.path).rows()
    assert len(durable) == 1
    assert {k: durable[0][k] for k in ("robot_id", "stuck_id", "decision", "principal_id",
                                       "accepted", "outcome", "code")} == {
        "robot_id": "rosy_01", "stuck_id": "stuck-abc", "decision": "WAIT",
        "principal_id": "op-7", "accepted": 1, "outcome": "hold", "code": None}
    audit_ids = {row.get("request_id") for row in store.api_audit()}
    assert durable[0]["audit_id"] and durable[0]["audit_id"] in audit_ids
    assert ("line_stuck_decision", "stuck-abc", "WAIT") in robot.calls
    body = response.json()
    assert body["actor_id"] == "op-7" and body["result"]["outcome"] == "hold"
    assert body["answer"]["principal_id"] == "op-7" and body["answer"]["accepted"] is True
    assert _row(client)["line_stuck"]["fleet_answer"]["decision"] == "WAIT"
    audit = store.api_audit()
    assert audit[0]["principal_id"] == "op-7" and audit[0]["status_code"] == 200
    assert audit[0]["path"] == "/api/fleet/robots/rosy_01/line-stuck/decision"
    assert OPERATOR not in str(audit)


def test_a_viewer_cannot_answer_and_nothing_reaches_the_robot(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    client, _ = _named_app(_console(robot), tmp_path)

    response = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                           json={"stuck_id": "stuck-abc", "decision": "ABORT"},
                           headers=_auth(VIEWER))

    assert response.status_code == 403
    assert not any(call[0] == "line_stuck_decision" for call in robot.calls)


def test_a_bad_decision_or_unknown_robot_is_refused_before_any_robot_call(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    client, _ = _named_app(_console(robot), tmp_path)

    bad = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                      json={"stuck_id": "stuck-abc", "decision": "GO"}, headers=_auth(OPERATOR))
    extra = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                        json={"stuck_id": "stuck-abc", "decision": "WAIT", "force": True},
                        headers=_auth(OPERATOR))
    odd_id = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                         json={"stuck_id": "stuck abc\n<x>", "decision": "WAIT"},
                         headers=_auth(OPERATOR))
    core_id = f"stuck-{uuid.uuid4().hex[:12]}"   # CORE StuckRecovery's id shape
    assert LineStuckDecisionRequest(stuck_id=core_id, decision="WAIT").stuck_id == core_id
    assert LineStuckDecisionRequest(stuck_id=str(uuid.uuid4()), decision="WAIT")
    unknown = client.post("/api/fleet/robots/rosy_99/line-stuck/decision",
                          json={"stuck_id": "stuck-abc", "decision": "WAIT"},
                          headers=_auth(OPERATOR))

    assert bad.status_code == 422 and extra.status_code == 422 and odd_id.status_code == 422
    assert unknown.status_code == 404
    assert not any(call[0] == "line_stuck_decision" for call in robot.calls)


def test_core_stuck_id_mismatch_reaches_the_operator_verbatim_as_409(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    robot.stuck_decision_error = RobotApiError(
        "rosy_01", 409, "STUCK_ID_MISMATCH", "no open stuck with this id (late or wrong answer)")
    console = _console(robot)
    client, _ = _named_app(console, tmp_path)

    response = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                           json={"stuck_id": "stuck-late", "decision": "RESUME"},
                           headers=_auth(OPERATOR))

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "STUCK_ID_MISMATCH", "robot_id": "rosy_01", "robot_status": 409,
        "message": "no open stuck with this id (late or wrong answer)"}
    answer = client.app.state.line_stuck.answers()[-1]
    assert answer["accepted"] is False and answer["code"] == "STUCK_ID_MISMATCH"
    assert answer["principal_id"] == "op-7"


def test_a_refused_resume_keeps_cores_reason_and_shows_on_the_open_stuck(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    robot.stuck_decision_error = RobotApiError(
        "rosy_01", 409, "STUCK_DECISION_REFUSED", "RESUME refused: object_within_stop_distance")
    console = _console(robot)
    client, _ = _named_app(console, tmp_path)

    response = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                           json={"stuck_id": "stuck-abc", "decision": "RESUME"},
                           headers=_auth(OPERATOR))

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "RESUME refused: object_within_stop_distance"
    _row(client)
    shown = client.get("/api/fleet/line-stuck", headers=_auth(VIEWER)).json()["pending"][0]
    assert shown["fleet_answer"]["code"] == "STUCK_DECISION_REFUSED"


def test_the_console_serves_the_panel_module_and_its_shell(tmp_path):
    client, _ = _named_app(_console(FakeRobot("rosy_01", state=_state())), tmp_path)

    asset = client.get("/console/assets/line-stuck.js")
    page = client.get("/console")

    assert asset.status_code == 200 and "createLineStuckPanel" in asset.text
    assert ".style" not in asset.text   # CSP style-src 'self': classes only
    for needle in ('id="stuck-panel"', 'id="stuck-list"', 'id="stuck-heading"'):
        assert needle in page.text


_REQUEST = httpx.Request("POST", "http://127.0.0.1:8080/api/v1/line-follow/stuck/decision")


@pytest.mark.parametrize("error, code, accepted, durable_accepted", [
    (httpx.ConnectError("refused", request=_REQUEST), "ROBOT_UNREACHABLE", False, 0),
    (ConnectionRefusedError("refused"), "ROBOT_UNREACHABLE", False, 0),
    (httpx.ReadTimeout("timed out", request=_REQUEST), "STUCK_DECISION_OUTCOME_UNKNOWN", None, None),
    (httpx.RemoteProtocolError("dropped", request=_REQUEST), "STUCK_DECISION_OUTCOME_UNKNOWN",
     None, None),
])
def test_transport_failures_are_502_recorded_and_a_timeout_says_the_outcome_is_unknown(
        tmp_path, error, code, accepted, durable_accepted):
    robot = FakeRobot("rosy_01", state=_state())
    robot.stuck_decision_error = error
    client, store = _named_app(_console(robot), tmp_path)

    response = client.post("/api/fleet/robots/rosy_01/line-stuck/decision",
                           json={"stuck_id": "stuck-abc", "decision": "ABORT"},
                           headers=_auth(OPERATOR))

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == code and detail["transport"] == type(error).__name__
    if accepted is None:
        assert "may have applied" in detail["message"] and "Re-read the stuck" in detail["message"]
    else:
        assert "not delivered" in detail["message"]
    assert client.app.state.line_stuck.answers()[-1]["accepted"] is accepted
    row = LineStuckAnswerLog(store.path).rows()[0]
    assert row["accepted"] == durable_accepted and row["code"] == code
    assert store.api_audit()[0]["status_code"] == 502
