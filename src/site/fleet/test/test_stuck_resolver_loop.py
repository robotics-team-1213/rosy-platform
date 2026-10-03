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
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state(stuck=None)}])
    assert board.view("rosy_01") is None
