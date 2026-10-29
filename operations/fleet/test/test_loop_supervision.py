"""루프 감시 — 사망 경보, readyz 표면, 디스패치 루프 가시성 (계획 2026-10-27).

변이 검증 대상(계획 8): supervised/attach 하나 제거, stopping 플래그 제거,
디스패치 pass 복원은 각각 이 파일의 시험을 red로 만들어야 한다. 최소 앱에서
켜지지 않는 선택 루프(charge 등)의 언랩은 전체 옵션 구성 시험
(test_start_fleet_loops_enumerates_every_loop_when_all_services_are_configured)이 잡는다.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeRobot
from fleet.server import background_workers
from fleet.server import loop_supervision
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.loop_supervision import DEAD, NOT_CONFIGURED, RUNNING, LoopSupervisor
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

SUPERVISION_LOGGER = "fleet.server.loop_supervision"

EXPECTED_LOOPS = {
    "notifications", "arm-transfer-dispatcher", "signals", "stuck-resolver",
    "localization", "calibration-drift", "trip-runner", "charge-runtime",
    "goal-lease-renew", "identity", "lane-compliance", "tether-watch", "paths",
    "job-trips", "task-dispatch", "proposal-expiry", "mission-dispatch",
    "cell-job-dispatch", "goal-evidence-expiry", "mission-feedback-schedule",
    "mission-model-turn", "control-unit-journal", "control-unit-information",
}


def _app(*robots: FakeRobot, task_service=None, start_task_dispatcher=True):
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return create_app(FleetConsole(endpoints, list(robots)),
                      task_service=task_service, start_task_dispatcher=start_task_dispatcher)


# --- 감시자 단위 ---

def test_dead_loop_is_marked_and_logged(caplog):
    async def boom():
        raise RuntimeError("expected loop death")

    async def exercise():
        supervisor = LoopSupervisor()
        with caplog.at_level(logging.ERROR, logger=SUPERVISION_LOGGER):
            task = supervisor.supervised("dummy", boom())
            while not task.done():
                await asyncio.sleep(0)
        return supervisor

    supervisor = asyncio.run(exercise())
    row = supervisor.status()["dummy"]
    assert row["state"] == DEAD and row["deaths"] == 1
    assert row["last_failure_type"] == "RuntimeError"
    assert any("'dummy' ended" in record.getMessage() for record in caplog.records)


def test_cancelled_or_stopping_loop_is_not_a_death():
    async def boom():
        raise RuntimeError("dies during shutdown")

    async def exercise():
        supervisor = LoopSupervisor()
        cancelled = supervisor.supervised("cancelled", asyncio.Event().wait())
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        supervisor.stopping()
        expected = supervisor.supervised("expected", asyncio.Event().wait())
        await asyncio.sleep(0)
        expected.cancel()
        with pytest.raises(asyncio.CancelledError):
            await expected
        ended = supervisor.supervised("ended-during-shutdown", boom())
        while not ended.done():
            await asyncio.sleep(0)
        return supervisor

    supervisor = asyncio.run(exercise())
    rows = supervisor.status()
    assert rows["cancelled"]["state"] == RUNNING and rows["cancelled"]["deaths"] == 0
    assert rows["expected"]["state"] == RUNNING and rows["expected"]["deaths"] == 0
    # stopping 뒤 예외로 끝난 루프도 예정된 종료다 — 죽음으로 세지 않는다 (변이: stopping 제거 시 red)
    assert rows["ended-during-shutdown"]["state"] == RUNNING
    assert rows["ended-during-shutdown"]["deaths"] == 0
    ready, loops = supervisor.ready()
    assert ready is True and loops["cancelled"]["state"] == RUNNING


def test_failure_logging_is_rate_limited_by_the_injected_clock(caplog):
    clock = FakeClock()
    supervisor = LoopSupervisor(clock=clock, failure_log_interval_s=30.0)

    with caplog.at_level(logging.ERROR, logger=SUPERVISION_LOGGER):
        supervisor.note_failure("x", ValueError("first"))
        supervisor.note_failure("x", ValueError("within window"))
        clock.advance(30.0)
        supervisor.note_failure("x", ValueError("after window"))
        supervisor.note_ok("x")
        clock.advance(30.0)
        supervisor.note_failure("x", ValueError("after reset"))

    row = supervisor.status()["x"]
    assert row["state"] == RUNNING
    assert row["consecutive_failures"] == 1  # note_ok reset, then one failure
    assert row["last_failure_type"] == "ValueError"
    logged = [r for r in caplog.records if "cycle failed" in r.getMessage()]
    assert len(logged) == 3  # first, after window, after reset


def test_empty_registry_is_not_ready_and_declarations_enumerate():
    supervisor = LoopSupervisor()
    assert supervisor.ready() == (False, {})

    supervisor.declare("optional-loop")
    ready, loops = supervisor.ready()
    assert ready is True
    assert loops["optional-loop"]["state"] == NOT_CONFIGURED


# --- 디스패치 루프 가시성 (무음 pass 제거) ---

def test_task_dispatch_failure_is_visible_and_leaves_work_queued(monkeypatch, caplog):
    queued = ["task-1"]
    dispatched = []
    sleeps = []

    async def exercise():
        clock = FakeClock()
        supervisor = LoopSupervisor(clock=clock, failure_log_interval_s=30.0)

        def expire_queued():
            raise RuntimeError("expected dispatch failure")

        task_service = SimpleNamespace(
            scheduler=SimpleNamespace(expire_queued=expire_queued),
            store=SimpleNamespace(queued_task_ids=lambda: list(queued)),
            dispatch_next=lambda available, dispatch=None: dispatched.append(available))
        console = SimpleNamespace(prune_task_queue_entries=lambda ids: None)

        async def cancel_after_three(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= 3:
                raise asyncio.CancelledError

        monkeypatch.setattr(background_workers.asyncio, "sleep", cancel_after_three)
        await background_workers._task_dispatch_loop(
            console, task_service, None, supervisor=supervisor)

    with caplog.at_level(logging.ERROR, logger=SUPERVISION_LOGGER), \
            pytest.raises(asyncio.CancelledError):
        asyncio.run(exercise())

    assert dispatched == [] and queued == ["task-1"]  # 가용성을 못 확정하면 작업은 큐에 둔다
    assert sleeps == [0.25, 0.25, 0.25]
    logged = [r for r in caplog.records if "task-dispatch" in r.getMessage()]
    assert logged, "디스패치 실패가 더 이상 무음이 아니어야 한다"


def _drain_loop(monkeypatch, results, *, robot_ids, sleeps_until_stop):
    """Run the dispatch loop over scripted dispatch_next results; return the trace."""
    events = []
    script = iter(results)

    async def no_reconcile(service, console):
        return None

    async def dispatch_next(available, dispatch=None):
        result = next(script, None)
        events.append("dispatch" if result is not None else "idle")
        return result

    async def record_sleep(seconds):
        events.append(seconds)
        if events.count(0.25) >= sleeps_until_stop:
            raise asyncio.CancelledError

    async def snapshot():
        return {"robots": []}

    monkeypatch.setattr("fleet.server.channel.execution.outcomes.reconcile.reconcile_tasks",
                        no_reconcile)
    monkeypatch.setattr(background_workers.asyncio, "sleep", record_sleep)
    task_service = SimpleNamespace(
        robot_ids=frozenset(robot_ids),
        scheduler=SimpleNamespace(expire_queued=lambda: None),
        store=SimpleNamespace(queued_task_ids=lambda: []),
        dispatch_next=dispatch_next)
    console = SimpleNamespace(snapshot=snapshot, prune_task_queue_entries=lambda ids: None)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers._task_dispatch_loop(console, task_service, None))
    return events


def test_task_dispatch_drains_without_the_idle_pause(monkeypatch):
    """D-271 Gate A: a dispatch starts the next cycle at once; only an idle cycle pauses."""
    events = _drain_loop(monkeypatch, [{"status": "ACCEPTED"}] * 2,
                         robot_ids={"r1", "r2", "r3"}, sleeps_until_stop=1)
    assert events == ["dispatch", "dispatch", "idle", 0.25]


def test_task_dispatch_drain_pauses_after_one_round_of_robots(monkeypatch):
    """A result that never leaves the queue cannot spin: pause after len(robot_ids) in a row."""
    events = _drain_loop(monkeypatch, [{"status": "QUEUED"}] * 10,
                         robot_ids={"r1", "r2"}, sleeps_until_stop=2)
    assert events == ["dispatch", "dispatch", 0.25, "dispatch", "dispatch", 0.25]


# --- 앱 표면: /readyz 와 /healthz 분리 ---

def test_readyz_enumerates_every_loop_and_distinguishes_states(tmp_path):
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_01"})
    app = _app(FakeRobot("rosy_01"), task_service=tasks)

    with TestClient(app) as client:
        ready = client.get("/readyz")
    assert ready.status_code == 200
    loops = ready.json()["loops"]
    assert set(loops) == EXPECTED_LOOPS
    running = {name for name, row in loops.items() if row["state"] == RUNNING}
    assert {"trip-runner", "identity", "lane-compliance", "tether-watch",
            "paths", "task-dispatch"} <= running
    assert loops["signals"]["state"] == NOT_CONFIGURED
    assert loops["stuck-resolver"]["state"] == NOT_CONFIGURED


def test_dead_loop_flips_readyz_but_not_healthz():
    async def boom():
        raise RuntimeError("expected loop death")

    async def make_dead_supervisor():
        supervisor = LoopSupervisor()
        task = supervisor.supervised("dummy", boom())
        while not task.done():
            await asyncio.sleep(0)
        return supervisor

    supervisor = asyncio.run(make_dead_supervisor())
    assert supervisor.status()["dummy"]["state"] == DEAD

    app = _app(FakeRobot("rosy_01"), start_task_dispatcher=False)
    app.state.loop_supervision = supervisor

    client = TestClient(app)
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json()["detail"]["code"] == "FLEET_LOOPS_NOT_READY"
    assert ready.json()["detail"]["loops"]["dummy"]["state"] == DEAD
    health = client.get("/healthz")
    assert health.status_code == 200 and health.json() == {"status": "ok"}


def test_readyz_without_supervisor_is_explicitly_not_configured():
    app = _app(FakeRobot("rosy_01"), start_task_dispatcher=False)
    del app.state.loop_supervision

    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "FLEET_LOOPS_NOT_SUPERVISED"


def test_readyz_without_lifespan_stays_ready_with_declared_names(tmp_path):
    app = _app(FakeRobot("rosy_01"), start_task_dispatcher=False)
    loops = TestClient(app).get("/readyz").json()["loops"]
    assert set(loops) == EXPECTED_LOOPS
    assert all(row["state"] == NOT_CONFIGURED for row in loops.values())


# --- 전체 옵션 구성: 선택 분기의 언랩 (계획 2026-10-27 후속) ---

def test_start_fleet_loops_enumerates_every_loop_when_all_services_are_configured(monkeypatch):
    """모든 선택 서비스가 켜진 구성에서 23개 루프 전부가 running으로 언랩되는지.

    루프 몸체는 각자의 시험이 소유한다 — 여기서는 스폰 배선(supervised/attach)만
    검증한다. 팩토리를 영원히 대기하는 코루틴으로 바꿔 몸체를 걸어 뺀다.
    (변이: 어느 선택 분기의 supervised/attach를 지워도 이 시험은 red —
    그 루프가 not_configured로 남는다.)
    """
    async def hang(*_args, **_kwargs):
        await asyncio.Event().wait()

    class Service:  # run()이 코루틴을 반환하는 선택 서비스 (supervised 대상)
        def run(self):
            return hang()

    class Tether:  # start()가 태스크를 반환하는 유일한 예외 (attach 대상, D-526)
        def start(self):
            return asyncio.ensure_future(hang())

    async def exercise():
        supervisor = LoopSupervisor()
        app = SimpleNamespace(state=SimpleNamespace(
            arm_transfer_dispatcher=Service(), stuck_resolver=Service(),
            trip_runner=Service(), charge_runtime=Service(), job_trips=Service(),
            tether_watch=Tether(), paths=Service(), lane_compliance=object()))
        console = SimpleNamespace(
            _signals=Service(), goal_leases=SimpleNamespace(ttl_s=4.0),
            prune_task_queue_entries=lambda ids: None)

        # 루프 몸체 걸어 빼기: 스폰 배선이 부르는 모든 팩토리를 대기 코루틴으로.
        for factory in ("goal_evidence_expiry_loop", "lane_compliance_loop",
                        "goal_lease_renew_loop", "proposal_expiry_loop",
                        "mission_dispatch_loop", "mission_feedback_schedule_loop",
                        "_task_dispatch_loop", "_mission_model_turn_worker_loop"):
            monkeypatch.setattr(loop_supervision, factory, hang)
        monkeypatch.setattr(loop_supervision, "start_control_unit_tasks",
                            lambda app: [asyncio.ensure_future(hang()) for _ in range(2)])
        monkeypatch.setattr(loop_supervision, "start_notification_worker",
                            lambda app, config: (None, asyncio.ensure_future(hang())))

        _started, _notification_http, background_tasks = loop_supervision.start_fleet_loops(
            app, console, supervisor=supervisor,
            task_service=SimpleNamespace(), drive_cancel=None,
            proposal_store=object(), mission_dispatcher=object(),
            cell_job_dispatcher=object(), goal_evidence_service=object(),
            mission_model_turn_scheduler=object(), mission_model_turn_worker=object(),
            localization_service=Service(), calibration_drift_watch=Service(),
            notification_config=object(), identity=Service(),
            log=logging.getLogger("test-loop-supervision"), lane_compliance_period_s=1.0)

        ready, loops = supervisor.ready()
        assert ready is True
        assert set(loops) == EXPECTED_LOOPS
        not_running = {name for name, row in loops.items() if row["state"] != RUNNING}
        assert not_running == set()

        supervisor.stopping()  # 정리: 남은 태스크가 경보로 흘러들지 않게
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        return None

    asyncio.run(exercise())
