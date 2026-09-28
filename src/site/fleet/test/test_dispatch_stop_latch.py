import pytest
import asyncio

from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore, InvalidTaskTransition


def _queue(store, task_id="task-1", robot_id="rosy_01"):
    store.create_task(
        task_id=task_id, robot_id=robot_id, task_type="navigate",
        source="operator", actor_id="operator", request_key=task_id,
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue(task_id, priority_class=0)


def test_stop_generation_invalidates_pre_dispatch_claim_atomically(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    initial = store.dispatch_control()
    assert initial == {
        "generation": 0, "dispatch_enabled": False, "reason": "STARTUP_HOLD",
        "queued_tasks": 0, "unresolved_actions": 0, "rearm_available": True,
    }
    store.rearm_dispatch(expected_generation=0, actor_id="operator")
    _queue(store)
    scheduler = FleetTaskScheduler(store, worker_id="worker-a")
    assert scheduler.claim_next({"rosy_01"})["task_id"] == "task-1"

    stopped = store.trip_stop_latch(actor_id="operator", reason="SITE_STOP")

    assert stopped["generation"] == 2
    assert stopped["dispatch_enabled"] is False
    assert scheduler.claim_next({"rosy_01"}) is None
    assert store.resource_claims(resource_kind="robot", resource_id="rosy_01") == []
    with pytest.raises(InvalidTaskTransition):
        scheduler.begin_dispatch("task-1")


def test_stop_generation_survives_reopen_and_stale_rearm_is_rejected(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = FleetTaskStore(path)
    stopped = store.trip_stop_latch(actor_id="operator", reason="SITE_STOP")
    restarted = FleetTaskStore(path)

    assert restarted.dispatch_control() == stopped
    with pytest.raises(InvalidTaskTransition, match="generation changed"):
        restarted.rearm_dispatch(expected_generation=0, actor_id="operator")


def test_stop_clears_unsent_generic_claims_and_rejects_new_ones(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    rearmed = store.rearm_dispatch(expected_generation=0, actor_id="operator")
    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-ready", generation=rearmed["generation"],
        resources=[("workcell", "cell-a")],
    ) is True

    stopped = store.trip_stop_latch(actor_id="operator", reason="SITE_STOP")

    assert store.resource_claims(resource_kind="workcell", resource_id="cell-a") == []
    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-next", generation=stopped["generation"],
        resources=[("workcell", "cell-a")],
    ) is False


def test_service_startup_closes_dispatch_and_keeps_queued_work(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = FleetTaskStore(path)
    store.rearm_dispatch(expected_generation=0, actor_id="operator")
    _queue(store)
    store.claim_next(worker_id="previous-worker", available_robot_ids={"rosy_01"})
    store.release_resources(owner_kind="task", owner_id="task-1", generation=0)

    service = FleetTaskService(FleetTaskStore(path), robot_ids={"rosy_01"})

    assert service.store.dispatch_control()["dispatch_enabled"] is False
    assert service.store.get_task("task-1")["status"] == "QUEUED"
    assert service.scheduler.claim_next({"rosy_01"}) is None


def test_stop_between_claim_and_send_prevents_callback_and_releases_claim(tmp_path):
    service = FleetTaskService(
        FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"},
    )
    service.store.rearm_dispatch(expected_generation=1, actor_id="operator")
    _queue(service.store)
    original_check = service.store.dispatch_generation_is_current

    def stop_before_send(generation):
        service.store.trip_stop_latch(actor_id="operator", reason="SITE_STOP")
        return original_check(generation)

    service.store.dispatch_generation_is_current = stop_before_send
    sent = []

    async def dispatch(attempt):
        sent.append(attempt)
        return {"accepted": True}

    result = asyncio.run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))

    assert sent == []
    assert result["dispatch_phase"] == "READY"
    assert result["reason"] == "STOP_GENERATION_CHANGED_BEFORE_SEND"
    assert service.store.resource_claims(resource_kind="robot", resource_id="rosy_01") == []
