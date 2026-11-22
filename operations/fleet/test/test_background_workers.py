"""Periodic workers keep cadence, error recovery and task cancellation."""
import asyncio
from types import SimpleNamespace
import pytest
from fleet.server import background_workers

@pytest.mark.parametrize('failure', [None, OSError, ValueError])
def test_goal_evidence_expiry_keeps_one_second_cadence_and_cancellation(monkeypatch, failure):
    calls = []
    errors = []
    def hold_expired():
        calls.append('hold')
        if failure is not None:
            raise failure('expected transient failure')
    async def cancel_at_sleep(seconds):
        calls.append(seconds)
        raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', cancel_at_sleep)
    logger = SimpleNamespace(exception=lambda message: errors.append(message))
    with pytest.raises(asyncio.CancelledError):
        service = SimpleNamespace(hold_expired_without_evidence=hold_expired)
        asyncio.run(background_workers.goal_evidence_expiry_loop(service, logger))
    assert calls == ['hold', 1.0]
    assert len(errors) == (0 if failure is None else 1)


def _off_the_loop():
    with pytest.raises(RuntimeError):  # a blocking store call here would hold every heartbeat reply
        asyncio.get_running_loop()


def test_goal_evidence_expiry_does_not_hold_the_event_loop(monkeypatch):
    calls = []
    async def cancel_at_sleep(seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', cancel_at_sleep)
    service = SimpleNamespace(hold_expired_without_evidence=lambda: (_off_the_loop(), calls.append('hold')))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers.goal_evidence_expiry_loop(service, SimpleNamespace(exception=print)))
    assert calls == ['hold']


def test_task_expiry_write_does_not_hold_the_event_loop(monkeypatch):
    calls = []
    def expire():
        _off_the_loop()
        calls.append('expire')
    async def cancel_at_sleep(seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', cancel_at_sleep)
    # The rest of the cycle fails on this bare stub and is reported; the expiry write already ran.
    task_service = SimpleNamespace(scheduler=SimpleNamespace(expire_queued=expire), robot_ids=('rosy_01',))
    supervisor = SimpleNamespace(note_ok=lambda name: None, note_failure=lambda name, error: None)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers._task_dispatch_loop(SimpleNamespace(), task_service, None, supervisor=supervisor))
    assert calls == ['expire']


@pytest.mark.parametrize('wake_at, warned', [(0.25 + 0.49, 0), (0.25 + 0.5, 1)])
def test_event_loop_lag_is_logged_only_past_the_limit(monkeypatch, wake_at, warned):
    warnings = []
    times = iter([0.0, wake_at])
    sleeps = []
    async def sleep_then_cancel(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(background_workers.asyncio, 'sleep', sleep_then_cancel)
    logger = SimpleNamespace(warning=lambda *message: warnings.append(message))
    clock = lambda: next(times, 99.0)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers.event_loop_lag_loop(logger, clock=clock))
    assert len(warnings) == warned


def _run_one_dispatch_cycle(monkeypatch, *, row, console_extras=None, now=20.0):
    seen = []

    async def no_reconcile(service, console):
        return None

    async def snapshot():
        return {"robots": [row]}

    async def dispatch_next(available, dispatch=None):
        seen.append(set(available))
        return None

    async def cancel_at_sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr("fleet.server.channel.execution.outcomes.reconcile.reconcile_tasks", no_reconcile)
    monkeypatch.setattr(background_workers.asyncio, "sleep", cancel_at_sleep)
    console = SimpleNamespace(
        snapshot=snapshot,
        prune_task_queue_entries=lambda _ids: None,
        trip_busy=lambda _rid: False,
        **(console_extras or {}),
    )
    task_service = SimpleNamespace(
        robot_ids=frozenset({row["robot_id"]}),
        scheduler=SimpleNamespace(expire_queued=lambda: None),
        store=SimpleNamespace(queued_task_ids=lambda: ["task-1"]),
        dispatch_next=dispatch_next,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_workers._task_dispatch_loop(console, task_service, None, clock=lambda: now))
    assert len(seen) == 1
    return seen[0]


def _ready_row(**overrides):
    row = {
        "robot_id": "rosy_01",
        "online": True,
        "queued": None,
        "yielding": None,
        "goal": {"x": 1.0, "y": 2.0, "yaw": 0.0},
        "state": {
            "navigation": "ARRIVED",
            "mode": "NAVIGATION",
            "capabilities_degraded": False,
            "safety": {"estop": False},
        },
    }
    row.update(overrides)
    return row


def test_task_dispatch_dispatches_when_console_retains_arrived_goal(monkeypatch):
    available = _run_one_dispatch_cycle(
        monkeypatch,
        row=_ready_row(),
        console_extras={"trip_goal_sent_at": {"rosy_01": 10.0}},
        now=15.0,
    )
    assert available == {"rosy_01"}


@pytest.mark.parametrize("extras,row_patch", [
    ({"trip_goal_sent_at": {"rosy_01": 10.0}}, {}),
    ({"_goal_busy": {"rosy_01"}}, {}),
    ({"goal_leases": SimpleNamespace(pending={"rosy_01": 1})}, {}),
    ({}, {"yielding": {"for": "rosy_02"}}),
    ({}, {"state": {"navigation": "NAVIGATING", "mode": "NAVIGATION",
                    "capabilities_degraded": False, "safety": {"estop": False}}}),
])
def test_task_dispatch_skips_robot_with_fresh_or_in_flight_goal(monkeypatch, extras, row_patch):
    available = _run_one_dispatch_cycle(
        monkeypatch,
        row=_ready_row(**row_patch),
        console_extras=extras,
        now=11.0,
    )
    assert available == set()
