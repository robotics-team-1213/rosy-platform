from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_store import FleetTaskStore


def _queue(store, task_id="task-1", robot_id="rosy_01", priority=0):
    store.create_task(
        task_id=task_id, robot_id=robot_id, task_type="navigate",
        source="operator", actor_id="site-console", request_key=task_id,
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue(task_id, priority_class=priority)


def test_two_dispatchers_cannot_claim_the_same_robot_task(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    _queue(store)
    barrier = Barrier(2)

    def claim(worker_id):
        barrier.wait()
        return FleetTaskScheduler(store, worker_id=worker_id).claim_next({"rosy_01"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("worker-a", "worker-b")))

    assert sum(result is not None for result in results) == 1
    assert store.get_task("task-1")["status"] == "QUEUED"


def test_scheduler_uses_monotonic_time_for_observed_queue_wait(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    _queue(store)
    ticks = iter((10.0, 13.25))
    scheduler = FleetTaskScheduler(store, worker_id="worker-a", monotonic=lambda: next(ticks))
    scheduler.note_queued("task-1")

    claimed = scheduler.claim_next({"rosy_01"})

    assert claimed["task_id"] == "task-1"
    assert claimed["queue_wait_seconds"] == 3.25
