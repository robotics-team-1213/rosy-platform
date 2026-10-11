"""Autonomous scope: condition recovery, bounded attempts and checked route changes."""

import asyncio

import pytest

from fleet.stuck.resolver import Answer, ResolverConfig, StuckResolver
from test_stuck_resolver import _row, _stuck
from test_stuck_resolver_loop import _setup
from test_ai_deadlock import _routable
from test_lane_traffic import _cycle, _ticks, run
from fleet.traffic.handover import CYCLE_PERIODS


def resolver(**config):
    core = StuckResolver(ResolverConfig(**config))
    core.autonomous_robots = frozenset({"rosy_01"})
    return core


def test_accepted_hold_reobserves_and_recovers_once_without_a_person():
    core = resolver()
    row = _row(stuck=_stuck(cause="lane_lost"))
    row["state"]["line_follow"]["crosswalk"] = {"state": "unknown"}
    wait = core.step(0, [row])[0]
    core.sent(wait, 0)
    held = core.result(wait, code=None)
    assert type(held).__name__ == "Hold"
    assert core.step(1, [row]) == []
    row["state"]["line_follow"]["crosswalk"] = None
    answer = core.step(2, [row])
    assert answer == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]
    core.sent(answer[0], 2)
    core.result(answer[0], code=None)
    assert core.step(3, [row]) == []


@pytest.mark.parametrize("config,reason", [({"rule_budget": 0}, "rule_budget"),
                                          ({"escalate_after_s": 0}, "deadline")])
def test_exhaustion_observes_without_resetting_the_budget(config, reason):
    core = resolver(**config)
    row = _row(stuck=_stuck())
    first = core.step(0, [row])
    held = core.step(1, [row])[0] if reason == "deadline" else first[0]
    assert type(held).__name__ == "Hold" and held.reason == reason
    chain = core._chains["rosy_01"]
    initial = (chain.started_at, chain.rule_answers)
    assert core.step(1000, [row]) == []
    assert (chain.started_at, chain.rule_answers) == initial


def test_unknown_motion_and_actual_human_claim_never_reopen():
    core = resolver()
    row = _row(stuck=_stuck())
    core.step(0, [row])
    answer = Answer("rosy_01", "stuck-1", "YIELD", "meet", yield_m=0.1, yield_turn_rad=0)
    core.sent(answer, 0)
    held = core.result(answer, code="STUCK_DECISION_OUTCOME_UNKNOWN")
    assert type(held).__name__ == "Hold"
    assert core.step(2, [row]) == []
    core.claim("rosy_01", "stuck-1")
    assert core.step(3, [row]) == []


def test_auto_hold_is_audited_as_observation_not_human_ownership():
    loop, board, robot = _setup()
    loop._resolver.autonomous_robots = frozenset({"rosy_01"})
    loop._resolver.config = ResolverConfig(rule_budget=0)
    asyncio.run(loop.run_once())
    note = board.view("rosy_01")["resolver"]
    assert note["tier"] == "rule" and note["decision"] == "WAIT"
    assert note["escalated"] == "auto_hold:rule_budget"
    assert robot.calls == []
    assert not loop._resolver.is_claimed("rosy_01", "stuck-abc")


def test_authorized_deterministic_replan_uses_checks_without_ai_or_operator(monkeypatch):
    runner, _store, fleet = _cycle(monkeypatch)
    runner.autonomous_robots = frozenset({"b"})
    _routable(monkeypatch, runner)
    _ticks(runner, fleet, n=CYCLE_PERIODS + 1)
    assert runner.view("b")["hold"] is None
    assert runner.view("b")["detail"]["replan_confirmed_by"] == "fleet-rule"


@pytest.mark.parametrize("change", ["stop", "hold", "route", "map", "scope"])
def test_replan_cannot_apply_after_await_invalidates_its_admission(monkeypatch, change):
    runner, store, fleet = _cycle(monkeypatch)
    _routable(monkeypatch, runner)
    _ticks(runner, fleet, n=CYCLE_PERIODS + 1)
    live = runner._live["b"]
    rev = live.route_rev
    hold = live.view["hold"]

    async def caps(*_args, **_kwargs):
        if change == "stop":
            runner._stop_epoch += 1
        elif change == "hold":
            live.view["hold"] = dict(hold)
        elif change == "route":
            live.route_rev += 1
        elif change == "scope":
            runner.autonomous_robots = frozenset()
        else:
            original = store.active()
            monkeypatch.setattr(store, "active", lambda: ("changed", *original[1:]))

    runner.autonomous_robots = frozenset({"b"})
    monkeypatch.setattr(runner, "_caps_checks", caps)
    run(runner._ai_confirm(live, principal_id="fleet-rule"))
    assert "replan_confirmed_by" not in live.view["detail"]
    assert live.route_rev == rev + int(change == "route")
