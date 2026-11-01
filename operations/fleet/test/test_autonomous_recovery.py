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


def test_autonomous_start_requires_recording_and_background_resolver(tmp_path):
    from fleet.server.app import create_app
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    loop, _board, _robot = _setup()
    console = loop._snapshot._console
    scope = frozenset({"rosy_01"})
    with pytest.raises(ValueError, match="durable journal"):
        create_app(console, autonomous_robots=scope, stuck_resolver_clients={})
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "journal.sqlite3"), robot_ids=scope)
    with pytest.raises(ValueError, match="background stuck resolver"):
        create_app(console, task_service=tasks, autonomous_robots=scope)
    app = create_app(console, task_service=tasks, autonomous_robots=scope, stuck_resolver_clients={})
    assert app.state.line_stuck._log.path == tasks.store.path
    assert app.state.fleet_gather.observations is not None
    assert app.state.stuck_resolver._resolver.autonomous_robots == scope
    assert create_app(console).state.line_stuck._log is None


@pytest.mark.parametrize("result", ["crash", "accepted", "write_failed", "admission_changed",
                                    "client_changed", "server_error", "bad_response", "empty_response", "refused"])
def test_moving_dispatch_is_journaled_before_send_and_rechecked(tmp_path, monkeypatch, result):
    from copy import deepcopy
    from fleet.stuck.reports import LineStuckAnswerLog
    from fleet.swarm.transport import RobotApiError
    journal = LineStuckAnswerLog(tmp_path / "journal.sqlite3")
    loop, board, robot = _setup(log=journal)
    loop._resolver.autonomous_robots = frozenset({"rosy_01"})
    calls = []

    class Crash(BaseException):
        pass

    async def send(*args, **kwargs):
        assert journal.uncertain_motion() == {("rosy_01", "stuck-abc")}
        calls.append(args)
        if result == "crash":
            raise Crash()
        if result in ("server_error", "bad_response", "refused"):
            status, code = {"server_error": (500, "HTTP_500"), "bad_response": (200, "BAD_RESPONSE"),
                            "refused": (409, "STUCK_DECISION_REFUSED")}[result]
            raise RobotApiError("rosy_01", status, code, "test receipt")
        return {} if result == "empty_response" else {"outcome": "back"}

    monkeypatch.setattr(robot, "line_stuck_decision", send)
    if result == "write_failed":
        monkeypatch.setattr(journal, "append", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    if result in ("admission_changed", "client_changed"):
        original, reads = loop._admission_row, []

        async def changed(rid):
            row = deepcopy(await original(rid))
            reads.append(rid)
            if len(reads) == 2:
                if result == "client_changed":
                    loop._clients = lambda: {}
                else:
                    row["state"]["safety"]["estop"] = True
            return row

        monkeypatch.setattr(loop, "_admission_row", changed)
    if result == "crash":
        with pytest.raises(Crash):
            asyncio.run(loop.run_once())
        assert journal.rows()[0]["code"] == "FLEET_STUCK_DISPATCH_PENDING"
        restarted, _board, _robot = _setup(log=journal)
        restarted._resolver.autonomous_robots = frozenset({"rosy_01"})
        assert restarted._resolver._uncertain == {("rosy_01", "stuck-abc")}
        asyncio.run(restarted.run_once())
        assert _robot.calls == []
    else:
        asyncio.run(loop.run_once())
        assert bool(calls) == (result in ("accepted", "server_error", "bad_response", "empty_response", "refused"))
        if result in ("server_error", "bad_response", "empty_response"):
            assert journal.uncertain_motion() == {("rosy_01", "stuck-abc")}
            restarted, _board, _robot = _setup(log=journal)
            assert restarted._resolver._uncertain == {("rosy_01", "stuck-abc")}
        elif result != "write_failed":
            assert journal.uncertain_motion() == set()
        else:
            assert board.view("rosy_01")["resolver"]["escalated"] == "auto_hold:journal_unavailable"


def test_accepted_hold_reobserves_and_recovers_once_without_a_person():
    core = resolver()
    row = _row(stuck=_stuck(cause="lane_lost"))
    row["state"]["line_follow"]["crosswalk"] = {"state": "unknown"}
    wait = core.step(0, [row])[0]
    core.sent(wait, 0)
    held = core.result(wait, code=None)
    row["state"]["line_follow"]["stuck"]["phase"] = "WAITING_CONSOLE"
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
    row["state"]["line_follow"]["mode"] = "IR_LINE"
    assert core.step(1001, [row]) == []
    assert core._chains["rosy_01"] is chain
    assert (chain.started_at, chain.rule_answers) == initial


@pytest.mark.parametrize("phase", ["YIELDED", "TURNING", "CRAWLING", "BACKING", "SETTLING"])
@pytest.mark.parametrize("budget", [1, 2])
def test_unresolved_yield_only_resumes_after_completed_owner_segment(monkeypatch, phase, budget):
    core = resolver(rule_budget=budget)
    row = _row(stuck=_stuck())
    core.step(0, [row])
    answer = Answer("rosy_01", "stuck-1", "YIELD", "meet", yield_m=0.1, yield_turn_rad=0)
    core.sent(answer, 0)
    core.result(answer, code=None)
    chain = core._chains["rosy_01"]
    chain.rule_answers = 1  # Exhausted rule tier; existing meet segments do not consume that counter.
    chain.unresolved.add("YIELD")
    core._escalate(chain, "rosy_01", "stuck-1", "unresolved:YIELD")
    row["state"]["line_follow"]["stuck"]["phase"] = phase
    monkeypatch.setattr(core, "_meet", lambda *_: ("meet", "YIELD", 0, 0.1))
    held = core.step(21, [row])
    if budget == 1 and phase == "YIELDED":
        assert len(held) == 1 and held[0].reason == "rule_budget"
    else:
        assert held == []
    monkeypatch.setattr(core, "_meet", lambda *_: ("meet", "RESUME"))
    actions = core.step(22, [row])
    if budget == 1 and phase == "YIELDED":
        assert chain.observing == "rule_budget" and actions == []
    else:
        assert actions == ([Answer("rosy_01", "stuck-1", "RESUME", "meet")] if phase == "YIELDED" else [])


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


def test_restart_freeze_requires_exact_owner_case_closure(tmp_path):
    from types import SimpleNamespace
    from fleet.stuck.reports import LineStuckAnswerLog
    journal = LineStuckAnswerLog(tmp_path / "journal.sqlite3")
    _loop, board, _robot = _setup(log=journal)
    board.record(robot_id="rosy_01", stuck_id="stuck-abc", decision="BACK_AND_RETRY",
                 principal_id="fleet-resolver", accepted=None,
                 code="STUCK_DECISION_OUTCOME_UNKNOWN", tier="rule")
    loop, _board, robot = _setup(log=journal)
    loop._resolver.autonomous_robots = frozenset({"rosy_01"})
    assert loop._resolver._uncertain == {("rosy_01", "stuck-abc")}
    closed = SimpleNamespace(type="nav.line_stuck_closed", data={"stuck_id": "another-case"})
    loop.stuck_event = lambda _rid, _type, sid: closed if closed.data["stuck_id"] == sid else None
    asyncio.run(loop.run_once())
    assert robot.calls == [] and journal.uncertain_motion()
    closed.data["stuck_id"] = "stuck-abc"
    original = loop._snapshot

    async def closed_snapshot():
        snapshot = await original()
        snapshot["robots"][0]["state"]["line_follow"]["stuck"] = None
        return snapshot

    loop._snapshot = closed_snapshot
    asyncio.run(loop.run_once())
    assert not loop._resolver._uncertain and not journal.uncertain_motion()
    restarted, _board, _robot = _setup(log=journal)
    assert not restarted._resolver._uncertain


@pytest.mark.parametrize("change", ["estop", "activity", "case", "mode", "missing"])
def test_unknown_motion_survives_unrelated_state_and_chain_changes(change):
    core = resolver()
    row = _row(stuck=_stuck())
    core.step(0, [row])
    answer = Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")
    core.sent(answer, 0)
    core.result(answer, code="STUCK_DECISION_OUTCOME_UNKNOWN")
    if change == "estop":
        row["state"]["safety"]["estop"] = True
    elif change == "activity":
        row["state"]["activity"] = "calibration"
    elif change == "case":
        row["state"]["line_follow"]["stuck"]["stuck_id"] = "new-case"
    elif change == "mode":
        row["state"]["line_follow"]["mode"] = "IR_LINE"
    core.step(1, [] if change == "missing" else [row])
    row["state"]["safety"]["estop"] = False
    row["state"].pop("activity", None)
    assert not any(isinstance(a, Answer) for a in core.step(2, [row]))
    assert core._uncertain == {("rosy_01", "stuck-1")}


def test_wait_observation_does_not_replace_the_actual_accepted_receipt():
    from test_stuck_resolver_loop import _state, STUCK
    state = _state(stuck={**STUCK, "cause": "lane_lost"})
    state["line_follow"]["crosswalk"] = {"state": "unknown"}
    loop, board, _robot = _setup(state)
    loop._resolver.autonomous_robots = frozenset({"rosy_01"})
    asyncio.run(loop.run_once())
    assert board.view("rosy_01")["fleet_answer"]["accepted"] is True
    assert board.answers()[-1]["decision"] == "ESCALATE"
    assert board.answers()[-1]["tier"] == "rule"


def test_existing_replan_hold_recovers_without_replanning_or_resetting_attempts(monkeypatch):
    from fleet.server.trip_runner import TripError
    runner, _store, fleet = _cycle(monkeypatch)
    _routable(monkeypatch, runner)
    runner.autonomous_robots = frozenset({"b"})
    original = runner._pose_checks

    async def unavailable(*_args):
        raise TripError(422, "TRIP_POSE_UNTRUSTED")

    monkeypatch.setattr(runner, "_pose_checks", unavailable)
    _ticks(runner, fleet, n=CYCLE_PERIODS + 1)
    live = runner._live["b"]
    hold, tried = live.view["hold"], dict(runner.traffic._tried)
    assert hold is not None
    monkeypatch.setattr(runner, "_pose_checks", original)
    _ticks(runner, fleet)
    assert live.view["hold"] is None
    assert live.view["detail"]["replan_confirmed_by"] == "fleet-rule"
    assert tried["b"][1] == hold["blocked"]


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


@pytest.mark.parametrize("change", ["stop", "hold", "content", "route", "map", "scope"])
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
        elif change == "content":
            hold["plan"]["segments"] = []
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
