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
from fleet.server.console_routes import SharedGather
from fleet.server.line_stuck import LineStuckAnswerLog, LineStuckBoard
from fleet.server.stuck_resolver import ResolverConfig, StuckResolver
from fleet.server.stuck_resolver_loop import PRINCIPAL_ID, StuckResolverLoop
from site_map_fixture import painted_track
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
    loop = StuckResolverLoop(SharedGather(console, board, max_age_s=0.0), board,
                             StuckResolver(config or ResolverConfig(), painted=painted_track),
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
    loop = StuckResolverLoop(SharedGather(console, board), board,
                             StuckResolver(ResolverConfig(), painted=painted_track), clients=lambda: {},
                             clock=FakeClock())
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


@pytest.mark.parametrize("error", [httpx.ReadTimeout("reply lost"), ValueError("reply lost"),
                                  asyncio.CancelledError()])
def test_applied_yield_with_lost_reply_is_escalated_without_replay(error):
    from fleet.meet.place import pose_on

    painted = painted_track()
    door = next(item for item in painted.doors if item.edge_id == "east")
    state = _state(stuck={**STUCK, "decisions": ["WAIT", "YIELD"]})
    state["pose"] = dict(zip(("x", "y", "yaw"), pose_on(painted, "east", 1.2, direction=1)))
    peer = {"robot_id": "peer", "online": True, "state": {
        "pose": dict(zip(("x", "y", "yaw"), pose_on(painted, "east", 1.45, direction=-1)))}}
    board = LineStuckBoard(clock=FakeClock())
    applied = []

    async def snapshot():
        rows = [{"robot_id": "rosy_01", "online": True, "state": state}, peer]
        board.observe(rows)
        return {"robots": rows}

    async def decision(stuck_id, answer, **segment):
        applied.append((stuck_id, answer, segment))  # CORE applied it before the reply was lost.
        if isinstance(error, asyncio.CancelledError):
            await asyncio.Event().wait()
        raise error

    robot = type("Robot", (), {})()
    robot.line_stuck_decision = decision
    loop = StuckResolverLoop(snapshot, board, StuckResolver(ResolverConfig(), painted=painted_track),
                             clients=lambda: {"rosy_01": robot}, clock=FakeClock())
    if isinstance(error, asyncio.CancelledError):
        async def cancelled_reply():
            task = asyncio.create_task(loop.run_once())
            while not applied:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        asyncio.run(asyncio.wait_for(cancelled_reply(), 5))
    else:
        asyncio.run(loop.run_once())
    for phase in ("ASKING", "YIELDING", "YIELDED"):
        state["line_follow"]["stuck"]["phase"] = phase
        if phase == "YIELDED":
            state["pose"] = dict(zip(("x", "y", "yaw"),
                                     pose_on(painted, "east", door.s_m, direction=-1)))
        for _ in range(3):
            asyncio.run(loop.run_once())
    assert len(applied) == 1 and applied[0][1] == "YIELD"
    assert applied[0][2]["yield_m"] > 0
    answers = board.answers()
    assert answers[0]["accepted"] is None
    assert answers[0]["code"] == "STUCK_DECISION_OUTCOME_UNKNOWN"
    assert [row["decision"] for row in answers] == ["YIELD", "ESCALATE"]
    assert board.view("rosy_01")["resolver"]["escalated"] == "core:STUCK_DECISION_OUTCOME_UNKNOWN"


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


def _app(tmp_path, resolver_robot, *, signal_console=None):
    robot = FakeRobot("rosy_01", state=_state())
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")],
                           [robot], signal_console=signal_console)
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    return create_app(
        console, task_service=FleetTaskService(store, robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
        stuck_resolver_clients={"rosy_01": resolver_robot},
        site_users={sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "op-7",
                                                            "role": "operator"}})


def test_the_episode_log_judges_peers_with_the_running_resolvers_config(tmp_path):
    app = _app(tmp_path, FakeRobot("rosy_01", state=_state()))
    assert app.state.line_stuck.peer_config is app.state.stuck_resolver._resolver.config


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


def test_lifespan_supervises_signals_and_resolver_together_without_ui_reads(tmp_path):
    from threading import Event

    from fake_signals import FakeSignal
    from fleet.server.signals import SignalConsole, SignalEndpoint

    signal = FakeSignal("signal_1")
    resolver_robot = FakeRobot("rosy_01", state=_state())
    signal_started, resolver_started = Event(), Event()
    workers = {}
    original_status = signal.status
    original_decision = resolver_robot.line_stuck_decision

    async def status():
        signal_started.set()
        return await original_status()

    async def decision(stuck_id, answer):
        workers["resolver"] = asyncio.current_task()
        resolver_started.set()
        return await original_decision(stuck_id, answer)

    signal.status = status
    resolver_robot.line_stuck_decision = decision
    signals = SignalConsole(
        [SignalEndpoint("signal_1", "http://127.0.0.1:9081", "signal-token")], [signal])
    original_run = signals.run

    async def supervise():
        workers["signal"] = asyncio.current_task()
        await original_run()

    signals.run = supervise
    app = _app(tmp_path, resolver_robot, signal_console=signals)
    with TestClient(app):
        assert signal_started.wait(5), "signal supervision must start without a UI/API read"
        assert resolver_started.wait(5), "resolver must start beside signal supervision"
        assert workers["signal"] is app.state.signal_supervision
        assert workers["signal"] is not workers["resolver"]
        assert all(not worker.done() for worker in workers.values())
    assert all(worker.cancelled() for worker in workers.values())


class _CountingConsole:
    def __init__(self):
        self.snapshots = 0
        self.hub = type("Hub", (), {"registry": type("Reg", (), {
            "events_since": staticmethod(lambda _rid, _seq: ())})()})()

    async def snapshot(self):
        self.snapshots += 1
        await asyncio.sleep(0.01)                       # let the second caller arrive
        return {"robots": [{"robot_id": "rosy_01", "online": True, "state": _state()}]}


def test_concurrent_gathers_within_max_age_fetch_once():
    console, clock = _CountingConsole(), FakeClock()
    board = LineStuckBoard(clock=clock)
    observed = []
    real_observe = board.observe
    board.observe = lambda *a, **k: observed.append(1) or real_observe(*a, **k)
    gather = SharedGather(console, board, max_age_s=1.0, clock=clock)

    async def both():
        return await asyncio.gather(gather(), gather())
    first, second = asyncio.run(both())
    assert first is second and console.snapshots == 1 and observed == [1]
    clock.advance(1.5)
    asyncio.run(gather())
    assert console.snapshots == 2 and observed == [1, 1]


def test_the_loop_reads_the_shared_gather_and_never_observes_itself():
    board = LineStuckBoard(clock=FakeClock())
    board.observe = lambda *a, **k: pytest.fail("the loop must not observe the board itself")
    robot = FakeRobot("rosy_01", state=_state())

    async def snapshot():
        return {"robots": [{"robot_id": "rosy_01", "online": True, "state": _state()}]}
    loop = StuckResolverLoop(snapshot, board, StuckResolver(ResolverConfig(), painted=painted_track),
                             clients=lambda: {"rosy_01": robot}, clock=FakeClock())
    asyncio.run(loop.run_once())
    assert ("line_stuck_decision", "stuck-abc", "BACK_AND_RETRY") in robot.calls


def test_the_app_shares_one_gather_between_state_route_and_resolver(tmp_path):
    app = _app(tmp_path, FakeRobot("rosy_01", state=_state()))
    assert app.state.stuck_resolver._snapshot is app.state.fleet_gather
    row = TestClient(app).get("/api/fleet/state",
                              headers={"Authorization": f"Bearer {OPERATOR}"}).json()["robots"][0]
    assert row["line_stuck"]["stuck_id"] == "stuck-abc"


def test_a_human_claim_keeps_the_escalation_reason():
    loop, board, _ = _setup(config=ResolverConfig())
    board.observe([{"robot_id": "rosy_01", "online": True, "state": _state()}])
    loop.claim("rosy_01", "stuck-abc")
    assert board.view("rosy_01")["resolver"]["escalated"] == "human_claimed"
    board.note_resolver("rosy_01", "stuck-abc", tier="human", rule=None, decision=None,
                        escalated="deadline")
    loop.claim("rosy_01", "stuck-abc")
    note = board.view("rosy_01")["resolver"]
    assert (note["tier"], note["escalated"]) == ("human", "deadline")


class _HangingRobot(FakeRobot):
    async def line_stuck_decision(self, stuck_id, decision, **_extra):
        self._record("line_stuck_decision", stuck_id, decision)
        await asyncio.Event().wait()


def test_cancel_while_awaiting_the_robot_records_an_unknown_outcome():
    robot = _HangingRobot("rosy_01", state=_state())
    loop, board, _ = _setup(resolver_robot=robot)

    async def scenario():
        task = asyncio.create_task(loop.run_once())
        for _ in range(200):
            if robot.calls:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(asyncio.wait_for(scenario(), 5))
    last = board.answers()[-1]
    assert last["accepted"] is None and last["code"] == "STUCK_DECISION_OUTCOME_UNKNOWN"
    assert (last["tier"], last["rule"]) == ("rule", "R2")
