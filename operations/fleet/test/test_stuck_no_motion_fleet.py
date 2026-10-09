"""2026-10-10 user: a CORE no_motion stuck (zero command >= stuck_report_s, any reason) goes
through the Fleet resolver (R6 under R3's preconditions, else R5 WAIT + human) and the AI PC is
asked once for facts (D-577 shadow: shown on the row, no rule reads them)."""

from __future__ import annotations

import asyncio

import pytest
from fakes import FakeClock, FakeRobot
from fleet.server.console import FleetConsole
from fleet.server.console_routes import SharedGather
from fleet.server.line_stuck import LineStuckBoard
from fleet.server.stuck_ai import parse_facts
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


class _FakeAi:
    timeout_s = 1.0

    def __init__(self, reply):
        self.reply, self.asked = reply, []

    async def __call__(self, situation):
        self.asked.append(situation)
        if isinstance(self.reply, Exception):
            raise self.reply
        return parse_facts(self.reply)


def _loop(ai):
    robot = FakeRobot("rosy_41", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_41", "http://127.0.0.1:8080", "rest-token")], [robot])
    board = LineStuckBoard(clock=FakeClock())
    loop = StuckResolverLoop(SharedGather(console, board, max_age_s=0.0), board,
                             StuckResolver(ResolverConfig(), painted=painted_track),
                             clients=lambda: {"rosy_41": robot}, clock=FakeClock())
    loop.ai_ask = ai
    return loop, board, robot


async def _passes(loop, n=2):
    for _ in range(n):
        await loop.run_once()
        await asyncio.sleep(0)
    await asyncio.gather(*loop._ai_tasks)


FACT = {"kind": "stalled", "robot_ids": ["rosy_41"], "value": {"still_s": 6.1}, "confidence": 0.8,
        "source": "analyzer:stall@1", "observed_at": "2026-10-10T00:00:00Z", "ttl_s": 5.0}


def test_round_trip_fleet_answers_core_and_shows_the_ai_facts_once():
    ai = _FakeAi({"facts": [FACT]})
    loop, board, robot = _loop(ai)
    asyncio.run(_passes(loop))
    assert ("line_stuck_decision", "stuck-nm", "BACK_AND_RETRY") in robot.calls   # rule, not AI
    assert len(ai.asked) == 1                                                      # once per stuck
    assert ai.asked[0]["stuck"]["cause"] == "no_motion"
    assert ai.asked[0]["line_follow"]["reason"] == "lane_departure"
    assert board.view("rosy_41")["ai_facts"] == [FACT]


@pytest.mark.parametrize("reply", [
    {"facts": [{**FACT, "value": "WAIT"}]},                  # a command word is never a fact
    {"facts": [{**FACT, "kind": "advice"}]},
    {"facts": [{**FACT, "confidence": 1.5}]},
    {"facts": [{**FACT, "decision": "RESUME"}]},
    ConnectionError("ai pc down"),
])
def test_a_bad_or_absent_ai_reply_is_no_facts_and_the_rule_still_answers(reply):
    ai = _FakeAi(reply)
    loop, board, robot = _loop(ai)
    asyncio.run(_passes(loop))
    assert board.view("rosy_41")["ai_facts"] is None
    assert ("line_stuck_decision", "stuck-nm", "BACK_AND_RETRY") in robot.calls


def test_site_config_names_enrolled_robots_and_the_ai_pc(tmp_path):
    from types import SimpleNamespace

    from fleet.cli import _stuck_resolver_site

    path = tmp_path / "fleet-site.yaml"
    path.write_text("fleet:\n  stuck_resolver:\n    enrolled_robots: [rosy_40, rosy_41]\n"
                    "    ai_url: http://100.108.76.123:8787\n", encoding="utf-8")
    ids, ask = _stuck_resolver_site(SimpleNamespace(site_config=str(path)))
    assert ids == {"rosy_40", "rosy_41"} and ask._url == "http://100.108.76.123:8787/v1/situation"
    assert _stuck_resolver_site(SimpleNamespace(site_config=None)) == (frozenset(), None)
