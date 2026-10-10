"""D-407 lane stuck decisions on Fleet: tracking, forwarding, CORE refusal passthrough, auth."""

from __future__ import annotations

import uuid
from datetime import datetime
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
from fleet.server.sighting_store import SightingStore
from fleet.server.ai_facts import AiFactLog
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
                              "rear_state": "clear", "turn_clearance_m": 0.09, "rear_blind_m": 0.05,
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
    assert stuck["rear_state"] == "clear"           # D-407 re-run C: empty vs unknown
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
    client.app.state.fleet_gather.max_age_s = 0.0    # every read below is a fresh gather
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
    assert (durable[0]["tier"], durable[0]["rule"], durable[0]["escalated"]) == ("human", None, None)
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
    # D-540 3: the answers open inside the critical queue row; there is no separate panel.
    assert 'id="critical-list"' in page.text
    assert 'id="stuck-panel"' not in page.text


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


def test_an_old_answer_log_gains_the_resolver_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE fleet_line_stuck_answers (
                       answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       at TEXT NOT NULL, audit_id TEXT, robot_id TEXT NOT NULL,
                       stuck_id TEXT NOT NULL, decision TEXT NOT NULL,
                       principal_id TEXT NOT NULL, accepted INTEGER, outcome TEXT,
                       code TEXT, message TEXT)""")
        db.execute("INSERT INTO fleet_line_stuck_answers (at, robot_id, stuck_id, decision, "
                   "principal_id) VALUES ('t', 'rosy_01', 'stuck-old', 'WAIT', 'op-7')")
    db.close()
    LineStuckAnswerLog(path)
    log = LineStuckAnswerLog(path)                       # migration is idempotent
    LineStuckBoard(log=log).record(robot_id="rosy_01", stuck_id="stuck-new", decision="WAIT",
                                   principal_id="fleet-resolver", accepted=True, tier="rule",
                                   rule="R1")
    new, old = log.rows()
    assert (new["tier"], new["rule"], new["escalated"]) == ("rule", "R1", None)
    assert old["stuck_id"] == "stuck-old" and old["tier"] is None


# ---- stuck episode log (autonomy-chain step 1) -------------------------------------------


def _online(robot_id="rosy_01", stuck=STUCK, pose=None) -> dict:
    state = _state(stuck)
    if pose is not None:
        state["pose"] = {"x": pose[0], "y": pose[1], "yaw": pose[2]}
    return {"robot_id": robot_id, "online": True, "state": state}


class _Board(LineStuckBoard):
    """Observe then flush, as SharedGather does (the flush runs off the event loop there)."""

    def observe(self, *args, **kwargs):
        super().observe(*args, **kwargs)
        self.flush()


def _episode_board(tmp_path, **kwargs):
    log = LineStuckAnswerLog(tmp_path / "fleet.sqlite3")
    wall = FakeClock()
    return _Board(FakeClock(), log=log, wall=wall, **kwargs), log, wall


def test_an_episode_opens_tracks_the_max_and_closes_cleared(tmp_path):
    board, log, wall = _episode_board(tmp_path)
    for held in (3.5, 4.5, 5.5):
        board.observe([_online(stuck={**STUCK, "held_s": held, "attempts": 1})])
        wall.advance(1.0)
    board.observe([_online(stuck=None)])

    [row] = log.episodes()
    assert (row["robot_id"], row["stuck_id"], row["close_reason"], row["source"]) == (
        "rosy_01", "stuck-abc", "cleared", "fleet_poll")
    assert row["held_s_max"] == 5.5 and row["attempts_max"] == 1
    assert row["cause"] == "obstacle_ahead" and row["phase_at_open"] == "ASKING"
    assert row["local_enabled_at_open"] == 0
    assert row["opened_at"] < row["closed_at"]
    assert row["resolved_by"] is None and row["escalation_code"] is None


def test_a_new_stuck_id_replaces_the_open_episode(tmp_path):
    board, log, _ = _episode_board(tmp_path)
    board.observe([_online()])
    board.observe([_online(stuck={**STUCK, "stuck_id": "stuck-def"})])
    by_id = {row["stuck_id"]: row for row in log.episodes()}
    assert by_id["stuck-abc"]["close_reason"] == "replaced"
    assert by_id["stuck-def"]["closed_at"] is None


def test_leaving_the_roster_closes_and_offline_keeps_open(tmp_path):
    board, log, _ = _episode_board(tmp_path)
    board.observe([_online()])
    board.observe([{"robot_id": "rosy_01", "online": False, "state": None}])
    assert log.episodes()[0]["closed_at"] is None
    board.observe([])
    assert log.episodes()[0]["close_reason"] == "left_roster"


def test_a_restart_closes_open_episodes_and_the_same_stuck_reopens_one_row(tmp_path):
    board, log, wall = _episode_board(tmp_path)
    board.observe([_online()])
    opened_at = log.episodes()[0]["opened_at"]

    wall.advance(30.0)
    again = _Board(FakeClock(), log=LineStuckAnswerLog(log.path), wall=wall)
    [row] = log.episodes()
    assert row["close_reason"] == "fleet_restart" and row["closed_at"] is not None

    again.observe([_online()])
    again.observe([_online()])                      # the same opening twice: still one row
    [row] = log.episodes()
    assert row["closed_at"] is None and row["close_reason"] is None
    assert row["opened_at"] == opened_at


@pytest.mark.parametrize("answers, resolved_by, last_tier, escalation", [
    ([("ESCALATE", None, "human", "no_resolver_token")], None, None, "no_resolver_token"),
    ([("RESUME", False, "human", None), ("WAIT", True, "rule", None)], "rule", "rule", None),
    ([("WAIT", None, "rule", None)], "rule_unconfirmed", "rule", None),
    ([("ABORT", None, "human", None)], "human_unconfirmed", "human", None),
    ([("RESUME", False, "human", None)], None, "human", None),
])
def test_resolved_by_comes_from_the_last_non_escalate_answer(tmp_path, answers, resolved_by,
                                                             last_tier, escalation):
    board, log, _ = _episode_board(tmp_path)
    board.observe([_online()])
    for decision, accepted, tier, escalated in answers:
        board.record(robot_id="rosy_01", stuck_id="stuck-abc", decision=decision,
                     principal_id="fleet-resolver", accepted=accepted, tier=tier,
                     escalated=escalated)
    board.observe([_online(stuck=None)])
    [row] = log.episodes()
    assert (row["resolved_by"], row["last_answer_tier"], row["escalation_code"]) == (
        resolved_by, last_tier, escalation)
    if resolved_by == "rule":
        assert row["resolved_principal"] == "fleet-resolver"


@pytest.mark.parametrize("peer_pose, expected", [
    ((0.20, 0.03, 3.14), 1),        # in the R1 band
    ((0.80, 0.00, 3.14), 0),        # beyond reach
])
def test_peer_ahead_at_open_uses_the_resolver_judgement(tmp_path, peer_pose, expected):
    from fleet.server.stuck_resolver import ResolverConfig, peer_ahead

    board, log, _ = _episode_board(tmp_path)
    me = _online(pose=(0.0, 0.0, 0.0), stuck={**STUCK, "local_enabled": True})
    peer = _online("rosy_02", stuck=None, pose=peer_pose)
    board.observe([me, peer])
    row = next(r for r in log.episodes() if r["robot_id"] == "rosy_01")
    assert row["peer_ahead_at_open"] == expected
    assert row["peer_ahead_at_open"] == int(peer_ahead(me, [me, peer], ResolverConfig()))
    assert row["local_enabled_at_open"] == 1


@pytest.mark.parametrize("local, stored", [(True, 1), (False, 0), (None, None)])
def test_local_enabled_at_open_keeps_cores_value(tmp_path, local, stored):
    board, log, _ = _episode_board(tmp_path)
    board.observe([_online(stuck={**STUCK, "local_enabled": local})])
    assert log.episodes()[0]["local_enabled_at_open"] == stored


def test_no_own_pose_leaves_peer_ahead_unknown_and_trip_busy_is_recorded(tmp_path):
    board, log, _ = _episode_board(tmp_path)
    board.observe([_online()])
    assert log.episodes()[0]["peer_ahead_at_open"] is None
    assert log.episodes()[0]["trip_busy_at_open"] is None       # no trip runner yet

    board.trip_busy = lambda robot_id: robot_id == "rosy_02"
    board.observe([_online(), _online("rosy_02")])
    by_robot = {row["robot_id"]: row for row in log.episodes()}
    assert by_robot["rosy_02"]["trip_busy_at_open"] == 1


def test_the_map_pose_is_recorded_when_the_service_exists(tmp_path):
    from fleet.localization.map_pose import MapPose

    board, log, _ = _episode_board(tmp_path)
    board.map_pose = lambda robot_id: MapPose(x=1.0, y=2.0, yaw=0.5, state="LOCALIZED",
                                              source="sighting", dead_reckon_m=0.0, age_s=0.4)
    board.observe([_online()])
    row = log.episodes()[0]
    assert (row["pose_x"], row["pose_y"], row["pose_yaw"], row["pose_state"], row["pose_age_s"]) == (
        1.0, 2.0, 0.5, "LOCALIZED", 0.4)


def test_episode_writes_equal_transitions_and_no_log_writes_nothing(tmp_path):
    calls = []

    class CountingLog(LineStuckAnswerLog):
        def open_episode(self, row):
            calls.append("open")
            super().open_episode(row)

        def close_episode(self, *args, **kwargs):
            calls.append("close")
            super().close_episode(*args, **kwargs)

    board = _Board(FakeClock(), log=CountingLog(tmp_path / "fleet.sqlite3"))
    for _ in range(5):
        board.observe([_online()])
    board.observe([_online(stuck=None)])
    board.observe([_online(stuck=None)])
    assert calls == ["open", "close"]

    bare = _Board(FakeClock())                           # no --tasks-db: memory only, as before
    bare.observe([_online()])
    bare.observe([_online(stuck=None)])
    assert bare.episodes() == []


def test_an_old_database_without_the_episode_table_opens(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (x INTEGER)")
    db.close()
    board = _Board(FakeClock(), log=LineStuckAnswerLog(path))
    board.observe([_online()])
    assert len(board.episodes()) == 1


def test_episode_writes_wait_for_the_flush_and_then_are_durable_in_order(tmp_path):
    log = LineStuckAnswerLog(tmp_path / "fleet.sqlite3")
    board = LineStuckBoard(FakeClock(), log=log)
    board.observe([_online()])
    board.observe([_online(stuck={**STUCK, "stuck_id": "stuck-def"})])
    board.observe([_online(stuck=None)])
    assert log.episodes() == []                          # observe() itself never touches SQLite
    board.flush()
    by_id = {row["stuck_id"]: row for row in log.episodes()}
    assert by_id["stuck-abc"]["close_reason"] == "replaced"
    assert by_id["stuck-def"]["close_reason"] == "cleared"
    board.flush()                                        # drained: nothing written twice
    assert len(log.episodes()) == 2


def test_the_shared_gather_flushes_episode_writes_in_a_worker_thread(tmp_path, monkeypatch):
    import asyncio
    import threading

    from fleet.server import console_routes

    log = LineStuckAnswerLog(tmp_path / "fleet.sqlite3")
    board = LineStuckBoard(FakeClock(), log=log)
    threads = []
    original = board.flush
    board.flush = lambda: (threads.append(threading.get_ident()), original())[1]

    class Console:
        class hub:
            class registry:
                events_since = staticmethod(lambda _rid, _seq: ())

        async def snapshot(self):
            return {"robots": [_online()]}

    gather = console_routes.SharedGather(Console(), board)
    asyncio.run(gather())
    assert threads and threads[0] != threading.get_ident()
    assert [row["stuck_id"] for row in log.episodes()] == ["stuck-abc"]


def test_episode_list_route_is_read_guarded_and_lists_recent(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    client, _ = _named_app(_console(robot), tmp_path)
    assert client.get("/api/fleet/line-stuck/episodes").status_code == 401
    board = client.app.state.line_stuck
    assert board.trip_busy is not None and board.map_pose is not None    # wired by the app
    _row(client)
    robot._state = _state(stuck=None)
    client.app.state.fleet_gather.max_age_s = 0.0
    _row(client)
    listed = client.get("/api/fleet/line-stuck/episodes?limit=5", headers=_auth(VIEWER))
    assert listed.status_code == 200, listed.text
    [episode] = listed.json()["episodes"]
    assert episode["stuck_id"] == "stuck-abc" and episode["close_reason"] == "cleared"


def test_incident_report_separates_sources_and_keeps_operator_reviews(tmp_path):
    robot = FakeRobot("rosy_01", state=_state())
    client, _ = _named_app(_console(robot), tmp_path)
    assert client.get("/api/fleet/incidents").status_code == 401
    _row(client)
    opened = client.get("/api/fleet/line-stuck/episodes", headers=_auth(VIEWER)).json()["episodes"][0]
    at = datetime.fromisoformat(opened["opened_at"]).timestamp()
    SightingStore(tmp_path / "fleet.sqlite3").save_sighting({
        "robot_id": "rosy_01", "source_id": "ceiling_north", "seq": 7,
        "captured_at": at, "received_at": at + 0.1})
    AiFactLog(tmp_path / "fleet.sqlite3").append([{
        "received_at": at, "principal_id": "ai-pc", "kind": "stalled",
        "robot_ids": ["rosy_01"], "value": {"still_s": 21}, "confidence": 0.8,
        "evidence": {"source": "state"}, "source": "analyzer:test@1", "observed_at": at,
        "ttl_s": 3.0, "stage": "shadow"}])
    AiFactLog(tmp_path / "fleet.sqlite3").append([{
        "received_at": at + 9, "principal_id": "ai-pc", "kind": "incident_context",
        "robot_ids": ["rosy_01"], "value": {"cause_draft": "obstacle"}, "confidence": 0.35,
        "evidence": {"stuck_id": "stuck-abc"}, "source": "analyzer:incident_context@1",
        "observed_at": at + 9, "ttl_s": 3.0, "stage": "shadow"}, {
        "received_at": at + 1, "principal_id": "ai-pc", "kind": "incident_context",
        "robot_ids": ["rosy_01"], "value": {"cause_draft": "unknown"}, "confidence": 0.2,
        "evidence": {"stuck_id": "another-stuck"}, "source": "analyzer:incident_context@1",
        "observed_at": at + 1, "ttl_s": 3.0, "stage": "shadow"}])
    response = client.get("/api/fleet/incidents", headers=_auth(VIEWER))
    assert response.status_code == 200, response.text
    [report] = response.json()["reports"]
    assert report["classification"] == "line_stuck"
    assert report["evidence"]["core"]["cause"] == "obstacle_ahead"
    assert report["evidence"]["rosy_cam"]["source_id"] == "ceiling_north"
    assert report["evidence"]["ai_facts"][0]["kind"] == "incident_context"
    assert report["evidence"]["ai_facts"][0]["evidence"]["stuck_id"] == "stuck-abc"
    assert report["evidence"]["ai_facts"][1]["kind"] == "stalled"
    assert len(report["evidence"]["ai_facts"]) == 2
    assert report["evidence"]["front_image"]["status"] == "requestable_while_open"
    [traffic] = response.json()["traffic_reports"]
    assert traffic["classification"] == "stalled" and traffic["evidence"]["ai_fact"]["source"] == "analyzer:test@1"
    url = "/api/fleet/incidents/rosy_01/stuck-abc/review"
    body = {"root_cause": "obstacle", "note": "floor box seen"}
    assert client.post(url, json=body, headers=_auth(VIEWER)).status_code == 403
    assert client.post(url, json={**body, "root_cause": "invented"}, headers=_auth(OPERATOR)).status_code == 422
    assert client.post(url, json=body, headers=_auth(OPERATOR)).json() == {"reviewed": True}
    [updated] = client.get("/api/fleet/incidents", headers=_auth(VIEWER)).json()["reports"]
    assert updated["reviews"][-1]["root_cause"] == "obstacle"
    assert updated["reviews"][-1]["principal_id"] == "op-7"
    assert client.post("/api/fleet/incidents/rosy_01/missing/review", json=body,
                       headers=_auth(OPERATOR)).status_code == 404
    fact_url = f"/api/fleet/incidents/facts/{traffic['evidence']['ai_fact']['fact_row']}/review"
    assert client.post(fact_url, json=body, headers=_auth(VIEWER)).status_code == 403
    assert client.post(fact_url, json=body, headers=_auth(OPERATOR)).json() == {"reviewed": True}
    [reviewed] = client.get("/api/fleet/incidents", headers=_auth(VIEWER)).json()["traffic_reports"]
    assert reviewed["reviews"][-1]["note"] == "floor box seen"
    assert client.post("/api/fleet/incidents/facts/99999/review", json=body,
                       headers=_auth(OPERATOR)).status_code == 404
    assert client.post("/api/fleet/incidents/facts/999999999999999999999/review", json=body,
                       headers=_auth(OPERATOR)).status_code == 422
    robot._state = _state(stuck=None)
    client.app.state.fleet_gather.max_age_s = 0.0
    _row(client)
    [closed] = client.get("/api/fleet/incidents", headers=_auth(VIEWER)).json()["reports"]
    assert closed["evidence"]["front_image"]["status"] == "not_retained"
