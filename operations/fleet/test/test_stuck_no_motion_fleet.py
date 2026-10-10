"""2026-10-10 user: a CORE no_motion stuck (zero command >= stuck_report_s, any reason) goes
through the Fleet resolver (R6 under R3's preconditions, else R5 WAIT + human)."""

from __future__ import annotations

import asyncio

import pytest
from fakes import FakeClock, FakeRobot
from fleet.server.console import FleetConsole
from fleet.server.console_routes import SharedGather
from fleet.server.line_stuck import LineStuckBoard
from fleet.server.stuck_resolver import Answer, ResolverConfig, StuckResolver
from fleet.server.stuck_resolver_loop import StuckResolverLoop
from fleet.swarm.robots import RobotEndpoint
from site_map_fixture import painted_track

NO_MOTION = {"stuck_id": "stuck-nm", "cause": "no_motion", "detail": "lane_departure",
             "phase": "WAITING_CONSOLE", "held_s": 0.2, "attempts": 0, "max_attempts": 2,
             "local_enabled": True, "ask_remaining_s": None, "last_answer": None,
             "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT", "YIELD"]}


def _state(stuck=NO_MOTION, crosswalk=True):
    line = {"mode": "CAMERA_LINE", "state": "HOLD", "reason": "lane_departure", "stuck": stuck}
    if crosswalk:
        line["crosswalk"] = None
    return {"robot_id": "rosy_41", "mode": "NAVIGATION", "safety": {"estop": False}, "line_follow": line}


def _row(state):
    return {"robot_id": "rosy_41", "online": True, "state": state}


def test_no_motion_backs_off_under_r3_preconditions_as_r6():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_row(_state())]) == [Answer("rosy_41", "stuck-nm", "BACK_AND_RETRY", "R6")]


@pytest.mark.parametrize("stuck, crosswalk, reason", [
    ({**NO_MOTION, "local_enabled": False}, True, "local_disabled"),
    ({**NO_MOTION, "attempts": 2}, True, "attempts"),
    (NO_MOTION, False, "crosswalk_unknown"),
])
def test_no_motion_holds_with_wait_and_a_human_otherwise(stuck, crosswalk, reason):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_row(_state(stuck, crosswalk))]) == [
        Answer("rosy_41", "stuck-nm", "WAIT", "R5", escalate=f"no_motion_hold:{reason}")]


def _loop():
    robot = FakeRobot("rosy_41", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_41", "http://127.0.0.1:8080", "rest-token")], [robot])
    board = LineStuckBoard(clock=FakeClock())
    loop = StuckResolverLoop(SharedGather(console, board, max_age_s=0.0), board,
                             StuckResolver(ResolverConfig(), painted=painted_track),
                             clients=lambda: {"rosy_41": robot}, clock=FakeClock())
    return loop, board, robot


def test_round_trip_core_no_motion_to_fleet_answer():
    loop, board, robot = _loop()
    asyncio.run(loop.run_once())
    assert ("line_stuck_decision", "stuck-nm", "BACK_AND_RETRY") in robot.calls
    assert board.view("rosy_41")["resolver"]["rule"] == "R6"


def test_site_config_names_enrolled_robots(tmp_path):
    from types import SimpleNamespace

    from fleet.cli import _stuck_resolver_enrolled

    path = tmp_path / "fleet-site.yaml"
    path.write_text("fleet:\n  stuck_resolver:\n    enrolled_robots: [rosy_40, rosy_41]\n",
                    encoding="utf-8")
    assert _stuck_resolver_enrolled(SimpleNamespace(site_config=str(path))) == {"rosy_40", "rosy_41"}
    assert _stuck_resolver_enrolled(SimpleNamespace(site_config=None)) == frozenset()
