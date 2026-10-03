"""D-438 resolver loop, board notes, claim route and hub wake-up."""

from __future__ import annotations

import asyncio

from fakes import FakeClock, FakeRobot
from fleet.server.line_stuck import LineStuckBoard

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


from fleet.server.console import FleetConsole  # noqa: E402
from fleet.server.stuck_resolver import ResolverConfig, StuckResolver  # noqa: E402
from fleet.server.stuck_resolver_loop import PRINCIPAL_ID, StuckResolverLoop  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402
from fleet.swarm.transport import RobotApiError  # noqa: E402


def _setup(state=None, *, resolver_robot=None):
    robot = FakeRobot("rosy_01", state=state or _state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot])
    resolver_robot = resolver_robot or FakeRobot("rosy_01", state=state or _state())
    board = LineStuckBoard(clock=FakeClock())
    clock = FakeClock()
    loop = StuckResolverLoop(console, board, StuckResolver(ResolverConfig()),
                             clients=lambda: {"rosy_01": resolver_robot}, clock=clock)
    return loop, board, resolver_robot


def test_one_pass_answers_and_records_as_the_resolver():
    loop, board, resolver_robot = _setup()
    asyncio.run(loop.run_once())
    assert ("line_stuck_decision", "stuck-abc", "BACK_AND_RETRY") in resolver_robot.calls
    answer = board.answers()[-1]
    assert answer["principal_id"] == PRINCIPAL_ID and answer["accepted"] is True
    assert board.view("rosy_01")["resolver"]["rule"] == "R2"


def test_refusal_is_recorded_and_escalates_when_nothing_is_left():
    resolver_robot = FakeRobot("rosy_01", state=_state())
    resolver_robot.stuck_decision_error = RobotApiError(
        "rosy_01", 409, "STUCK_DECISION_REFUSED", "BACK_AND_RETRY refused: attempts_exhausted")
    loop, board, _ = _setup(resolver_robot=resolver_robot)
    asyncio.run(loop.run_once())
    asyncio.run(loop.run_once())
    assert board.answers()[-1]["code"] == "STUCK_DECISION_REFUSED"
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
