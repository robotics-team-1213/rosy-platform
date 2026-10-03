"""D-438 resolver loop, board notes, claim route and hub wake-up."""

from __future__ import annotations

import asyncio
import time
from hashlib import sha256

import httpx
import pytest
from fastapi.testclient import TestClient
from fakes import FakeClock, FakeRobot
from fleet.server.app import _fan_out_events, create_app
from fleet.server.console import FleetConsole
from fleet.server.line_stuck import LineStuckAnswerLog, LineStuckBoard
from fleet.server.stuck_resolver import ResolverConfig, StuckResolver
from fleet.server.stuck_resolver_loop import PRINCIPAL_ID, StuckResolverLoop
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

STUCK = {"stuck_id": "stuck-abc", "cause": "obstacle_ahead", "phase": "ASKING",
         "held_s": 3.5, "attempts": 0, "max_attempts": 2, "local_enabled": True,
         "ask_remaining_s": 11.5, "last_answer": None,
         "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]}


def _state(stuck=STUCK) -> dict:
    return {"robot_id": "rosy_01", "mode": "NAVIGATION", "safety": {"estop": False},
            "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": stuck}}


def test_board_view_carries_the_resolver_note():
    board = LineStuckBoard(clock=FakeClock())
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state()}])
    assert board.view("rosy_01")["resolver"] is None
    board.note_resolver("rosy_01", "stuck-abc", tier="rule", rule="R2",
                        decision="BACK_AND_RETRY", escalated=None)
    note = board.view("rosy_01")["resolver"]
    assert note["tier"] == "rule" and note["rule"] == "R2" and note["escalated"] is None
    board.note_resolver("rosy_01", "stuck-abc", tier="human", rule=None, decision=None,
                        escalated="no_rule")
    assert board.view("rosy_01")["resolver"]["escalated"] == "no_rule"
    board.observe([{"robot_id": "rosy_01", "online": True,
                    "state": _state(stuck={**STUCK, "stuck_id": "stuck-new"})}])
    assert board.view("rosy_01")["resolver"] is None
    assert ("rosy_01", "stuck-abc") not in board._resolver
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state(stuck=None)}])
    assert board.view("rosy_01") is None


def _setup(state=None, *, resolver_robot=None, config=None, log=None):
    robot = FakeRobot("rosy_01", state=state or _state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    resolver_robot = resolver_robot or FakeRobot("rosy_01", state=state or _state())
    clock = FakeClock()
    board = LineStuckBoard(clock=clock, log=log)
    loop = StuckResolverLoop(console, board, StuckResolver(config or ResolverConfig()),
                             clients=lambda: {"rosy_01": resolver_robot}, clock=clock)
    return loop, board, resolver_robot


def test_one_pass_answers_and_records_as_the_resolver():
    loop, board, resolver_robot = _setup()
    asyncio.run(loop.run_once())
    assert ("line_stuck_decision", "stuck-abc", "BACK_AND_RETRY") in resolver_robot.calls
    answer = board.answers()[-1]
    assert answer["principal_id"] == PRINCIPAL_ID and answer["accepted"] is True
    assert board.view("rosy_01")["resolver"]["rule"] == "R2"


def test_durable_rows_carry_the_tier_rule_and_every_escalation(tmp_path):
    log = LineStuckAnswerLog(tmp_path / "fleet.sqlite3")
    robot = _failing(RobotApiError("rosy_01", 409, "CALIBRATION_ACTIVE", "calibrating"))
    loop, board, _ = _setup(resolver_robot=robot, log=log)
    asyncio.run(loop.run_once())
    escalation, answer = log.rows()                     # newest first
    assert (answer["tier"], answer["rule"], answer["decision"]) == ("rule", "R2", "BACK_AND_RETRY")
    assert answer["escalated"] is None and answer["principal_id"] == PRINCIPAL_ID
    assert {k: escalation[k] for k in ("decision", "accepted", "escalated", "principal_id",
                                       "tier")} == {
        "decision": "ESCALATE", "accepted": None, "escalated": "core:CALIBRATION_ACTIVE",
        "principal_id": PRINCIPAL_ID, "tier": "human"}
    assert board.view("rosy_01")["fleet_answer"]["decision"] == "BACK_AND_RETRY"


def test_refusal_is_recorded_and_escalates_when_nothing_is_left():
    resolver_robot = FakeRobot("rosy_01", state=_state())
    resolver_robot.stuck_decision_error = RobotApiError(
        "rosy_01", 409, "STUCK_DECISION_REFUSED", "BACK_AND_RETRY refused: attempts_exhausted")
    loop, board, _ = _setup(resolver_robot=resolver_robot)
    asyncio.run(loop.run_once())
    asyncio.run(loop.run_once())
    refused, escalated = board.answers()[-2:]
    assert refused["code"] == "STUCK_DECISION_REFUSED" and escalated["decision"] == "ESCALATE"
    assert board.view("rosy_01")["resolver"]["escalated"] == "no_rule"


def test_robot_without_resolver_token_escalates():
    robot = FakeRobot("rosy_01", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    board = LineStuckBoard(clock=FakeClock())
    loop = StuckResolverLoop(console, board, StuckResolver(ResolverConfig()),
                             clients=lambda: {}, clock=FakeClock())
    asyncio.run(loop.run_once())
    assert board.view("rosy_01")["resolver"]["escalated"] == "no_resolver_token"
    assert robot.calls.count(("line_stuck_decision", "stuck-abc", "BACK_AND_RETRY")) == 0


def _failing(error):
    robot = FakeRobot("rosy_01", state=_state())
    robot.stuck_decision_error = error
    return robot


def test_unreachable_is_audited_false_resent_once_then_escalates():
    robot = _failing(httpx.ConnectError("down"))
    loop, board, _ = _setup(resolver_robot=robot)
    asyncio.run(loop.run_once())
    last = board.answers()[-1]
    assert last["accepted"] is False and last["code"] == "ROBOT_UNREACHABLE"
    asyncio.run(loop.run_once())
    assert len([c for c in robot.calls if c[0] == "line_stuck_decision"]) == 2
    asyncio.run(loop.run_once())
    assert board.view("rosy_01")["resolver"]["escalated"] == "core:ROBOT_UNREACHABLE"


def test_unexpected_client_error_is_unknown_outcome_and_pass_survives():
    robot = _failing(ValueError("boom"))
    loop, board, _ = _setup(resolver_robot=robot)
    asyncio.run(loop.run_once())
    last = board.answers()[-1]
    assert last["accepted"] is None and last["code"] == "STUCK_DECISION_OUTCOME_UNKNOWN"


def test_run_wakes_early_and_stops_on_cancel():
    loop, board, robot = _setup(config=ResolverConfig(poll_s=60))

    async def scenario():
        task = asyncio.create_task(loop.run())
        for _ in range(200):                    # first pass
            if robot.calls:
                break
            await asyncio.sleep(0.01)
        assert robot.calls
        passes = []
        orig = loop.run_once

        async def counted():
            passes.append(1)
            await orig()
        loop.run_once = counted
        loop.wake.set()
        for _ in range(200):
            if passes:
                break
            await asyncio.sleep(0.01)
        assert passes                           # woke well before poll_s
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(asyncio.wait_for(scenario(), 5))


OPERATOR = "operator-token"


def _app(tmp_path, resolver_robot):
    robot = FakeRobot("rosy_01", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    return create_app(
        console, task_service=FleetTaskService(store, robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
        stuck_resolver_clients={"rosy_01": resolver_robot},
        site_users={sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "op-7",
                                                            "role": "operator"}})


# TestClient is used without `with`: the lifespan task never starts, so run_once() is
# the only thing that can answer.
def test_claim_route_silences_the_resolver(tmp_path):
    resolver_robot = FakeRobot("rosy_01", state=_state())
    app = _app(tmp_path, resolver_robot)
    response = TestClient(app).post("/api/fleet/robots/rosy_01/line-stuck/claim",
                                    json={"stuck_id": "stuck-abc"},
                                    headers={"Authorization": f"Bearer {OPERATOR}"})
    assert response.status_code == 200
    asyncio.run(app.state.stuck_resolver.run_once())
    assert not [c for c in resolver_robot.calls if c[0] == "line_stuck_decision"]


def test_human_decision_claims_the_stuck(tmp_path):
    app = _app(tmp_path, FakeRobot("rosy_01", state=_state()))
    TestClient(app).post("/api/fleet/robots/rosy_01/line-stuck/decision",
                         json={"stuck_id": "stuck-abc", "decision": "WAIT"},
                         headers={"Authorization": f"Bearer {OPERATOR}"})
    assert ("rosy_01", "stuck-abc") in app.state.stuck_resolver._resolver._claims


def test_fan_out_feeds_the_task_projection_and_wakes_on_stuck_events():
    seen, wake = [], asyncio.Event()
    fan = _fan_out_events(lambda event: seen.append(event) or {"ok": True}, wake)
    assert fan({"type": "nav.goal_reached"}) == {"ok": True} and not wake.is_set()
    fan({"type": "nav.line_stuck_opened"})
    assert wake.is_set() and len(seen) == 2


def test_claim_and_decision_for_unknown_robot_are_404_and_unclaimed(tmp_path):
    app = _app(tmp_path, FakeRobot("rosy_01", state=_state()))
    headers = {"Authorization": f"Bearer {OPERATOR}"}
    client = TestClient(app)
    assert client.post("/api/fleet/robots/ghost/line-stuck/claim",
                       json={"stuck_id": "stuck-abc"}, headers=headers).status_code == 404
    assert client.post("/api/fleet/robots/ghost/line-stuck/decision",
                       json={"stuck_id": "stuck-abc", "decision": "WAIT"},
                       headers=headers).status_code == 404
    assert not app.state.stuck_resolver._resolver._claims


def test_lifespan_runs_the_resolver_and_exits_cleanly(tmp_path):
    resolver_robot = FakeRobot("rosy_01", state=_state())
    app = _app(tmp_path, resolver_robot)
    with TestClient(app):
        for _ in range(200):
            if [c for c in resolver_robot.calls if c[0] == "line_stuck_decision"]:
                break
            time.sleep(0.01)
        assert [c for c in resolver_robot.calls if c[0] == "line_stuck_decision"]


def test_line_stuck_js_claims_and_shows_the_resolver_note():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "fleet/server/web/line-stuck.js").read_text(
        encoding="utf-8")
    assert "/line-stuck/claim" in js and "export function resolverText" in js
