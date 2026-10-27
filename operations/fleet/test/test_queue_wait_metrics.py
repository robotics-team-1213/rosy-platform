"""Durable total queue wait: ``first_queued_at`` origin and its metrics.

``queued_at`` is rewritten when a traffic wait is released, so the monotonic-based
``queue_wait_seconds`` only sees the latest stay. The durable first origin keeps
the total (plan 2026-10-27-fleet-queue-first-queued-at).
"""
import logging
import sqlite3
from datetime import datetime, timedelta

from fakes import run
from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


def _store(tmp_path) -> FleetTaskStore:
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    control = store.dispatch_control()
    if not control["dispatch_enabled"]:
        store.rearm_dispatch(expected_generation=control["generation"], actor_id="test-operator")
    return store


def _queue(store, task_id="task-1", robot_id="rosy_01") -> dict:
    store.create_task(
        task_id=task_id, robot_id=robot_id, task_type="navigate",
        source="operator", actor_id="site-console", request_key=task_id,
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    return store.enqueue(task_id, priority_class=0)


def test_the_ledger_has_a_first_queued_at_column(tmp_path):
    _store(tmp_path)
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(fleet_tasks)")}
    assert "first_queued_at" in columns


def test_enqueue_records_first_queued_at_equal_to_queued_at(tmp_path):
    queued = _queue(_store(tmp_path))
    assert queued["first_queued_at"] is not None
    assert queued["first_queued_at"] == queued["queued_at"]


def test_re_enqueued_tasks_keep_the_earliest_first_queued_at(tmp_path):
    store = _store(tmp_path)
    first = _queue(store)["first_queued_at"]
    with sqlite3.connect(store.path) as connection:
        # A re-request of the same task id: back to REQUESTED, origin already recorded.
        connection.execute(
            "UPDATE fleet_tasks SET status='REQUESTED', queued_at='2000-01-01T00:00:00+00:00' "
            "WHERE task_id='task-1'"
        )

    requeued = store.enqueue("task-1", priority_class=0)

    assert requeued["queued_at"] > "2000-01-01T00:00:00+00:00"
    assert requeued["first_queued_at"] == first


def test_traffic_release_rewrites_queued_at_but_not_first_queued_at(tmp_path):
    store = _store(tmp_path)
    first = _queue(store)["first_queued_at"]
    store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})
    store.mark_dispatching("task-1", worker_id="worker-a")
    store.wait_for_traffic(
        "task-1", worker_id="worker-a", reason="ROUTE_CONFLICT", blocked_by="rosy_02",
        waiting_on=["rosy_02"], dispatch_attempted=True, cancel_confirmed=True,
    )

    released = store.release_traffic_wait("task-1")

    assert released["queued_at"] > first  # fresh eligibility for queue ordering
    assert released["first_queued_at"] == first  # the total's origin survives


def test_claim_reports_total_queue_wait_from_the_durable_origin(tmp_path):
    store = _store(tmp_path)
    first = datetime.fromisoformat(_queue(store)["first_queued_at"])
    ticks = iter((10.0, 15.0))
    scheduler = FleetTaskScheduler(store, worker_id="worker-a",
                                   monotonic=lambda: next(ticks),
                                   wall_clock=lambda: first + timedelta(seconds=90))
    scheduler.note_queued("task-1")

    claimed = scheduler.claim_next({"rosy_01"})

    assert claimed["queue_wait_seconds"] == 5.0  # the latest stay only
    assert claimed["total_queue_wait_seconds"] == 90.0  # since the first entry


def test_total_queue_wait_is_none_without_a_durable_origin(tmp_path):
    store = _store(tmp_path)
    _queue(store)
    with sqlite3.connect(store.path) as connection:
        # Rows queued before the column existed have no origin; never fabricate one.
        connection.execute("UPDATE fleet_tasks SET first_queued_at=NULL WHERE task_id='task-1'")

    claimed = FleetTaskScheduler(store, worker_id="worker-a").claim_next({"rosy_01"})

    assert claimed["total_queue_wait_seconds"] is None


def test_dispatch_claim_logs_both_waits_once(tmp_path, caplog):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    service.store.rearm_dispatch(expected_generation=1, actor_id="test-operator")
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="k1"))

    async def accepted(_task):
        return {"accepted": True}

    with caplog.at_level(logging.INFO, logger="fleet.server.task_service"):
        run(service.dispatch_next({"rosy_01"}, dispatch=accepted))

    lines = [record.getMessage() for record in caplog.records
             if "fleet task dispatch claimed" in record.getMessage()]
    assert len(lines) == 1
    assert f"task={task['task_id']}" in lines[0]
    assert "robot=rosy_01" in lines[0]
    assert "queue_wait_s=" in lines[0]
    assert "total_queue_wait_s=" in lines[0]
    assert "total_queue_wait_s=None" not in lines[0]
