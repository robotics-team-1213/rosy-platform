import sqlite3

import pytest

from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_store import FleetTaskStore, InvalidTaskTransition


def _queue(store, task_id="task-1", robot_id="rosy_01"):
    control = store.dispatch_control()
    if not control["dispatch_enabled"]:
        store.rearm_dispatch(expected_generation=control["generation"], actor_id="test-operator")
    store.create_task(
        task_id=task_id, robot_id=robot_id, task_type="navigate",
        source="operator", actor_id="operator", request_key=task_id,
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue(task_id, priority_class=0)


def test_existing_robot_reservation_is_backfilled_into_generic_claims(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = FleetTaskStore(path)
    _queue(store)
    assert store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE fleet_action_claims")

    migrated = FleetTaskStore(path)
    claims = migrated.resource_claims(resource_kind="robot", resource_id="rosy_01")

    assert claims == [{
        "resource_kind": "robot",
        "resource_id": "rosy_01",
        "owner_kind": "task",
        "owner_id": "task-1",
        "generation": 1,
        "phase": "CLAIMED",
    }]
    assert migrated.get_task("task-1")["task_id"] == "task-1"
    assert [row["status"] for row in migrated.history("task-1")] == ["REQUESTED", "QUEUED"]


def test_mission_candidate_and_navigation_task_share_the_same_robot_claim(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    _queue(store)

    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-1", generation=1,
        resources=[("robot", "rosy_01")],
    ) is True

    assert FleetTaskScheduler(store, worker_id="worker-a").claim_next({"rosy_01"}) is None


def test_conflicting_multi_resource_claim_is_atomic(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    control = store.dispatch_control()
    store.rearm_dispatch(expected_generation=control["generation"], actor_id="test-operator")
    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-1", generation=control["generation"] + 1,
        resources=[("workcell", "cell-a")],
    ) is True

    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-2", generation=control["generation"] + 1,
        resources=[("robot", "rosy_01"), ("workcell", "cell-a")],
    ) is False
    assert store.reserve_resources(
        owner_kind="task", owner_id="task-1", generation=control["generation"] + 1,
        resources=[("robot", "rosy_01")],
    ) is True


def test_direct_action_and_mission_candidates_contend_for_object_and_workcell(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    control = store.dispatch_control()
    enabled = store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")

    assert store.reserve_resources(
        owner_kind="direct_action", owner_id="action-1", generation=enabled["generation"],
        resources=[("workcell", "omx_01"), ("object", "block-1")],
    )
    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-2", generation=enabled["generation"],
        resources=[("robot", "rosy_01"), ("object", "block-1")],
    ) is False
    assert store.resource_claims(resource_kind="robot", resource_id="rosy_01") == []


def test_new_claim_cannot_forge_inflight_phase_and_restore_requires_dispatch_closed(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    control = store.dispatch_control()
    enabled = store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")

    with pytest.raises(ValueError, match="CLAIMED"):
        store.reserve_resources(
            owner_kind="direct_action", owner_id="action-inflight", generation=enabled["generation"],
            resources=[("workcell", "omx_01")], phase="UNKNOWN",
        )
    with pytest.raises(ValueError, match="closed"):
        store.restore_unresolved_action_claim(
            owner_kind="direct_action", owner_id="action-inflight", generation=enabled["generation"],
            resources=[("workcell", "omx_01")], phase="UNKNOWN",
        )

    stopped = store.trip_stop_latch(actor_id="operator")
    assert store.restore_unresolved_action_claim(
        owner_kind="direct_action", owner_id="action-inflight", generation=enabled["generation"],
        resources=[("workcell", "omx_01")], phase="UNKNOWN",
    )
    assert store.dispatch_control()["unresolved_actions"] == 1
    with pytest.raises(InvalidTaskTransition, match="unresolved"):
        store.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator")


def test_unknown_dispatch_keeps_robot_claim_until_explicit_release(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    _queue(store)
    store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})
    store.mark_dispatching("task-1", worker_id="worker-a")
    store.transition("task-1", "UNKNOWN", actor_id="operator", source="operator",
                     reason="COMMAND_RESULT_UNKNOWN")

    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-1", generation=1,
        resources=[("robot", "rosy_01")],
    ) is False
    assert store.release_resources(owner_kind="task", owner_id="task-1", generation=1) is True
    assert store.reserve_resources(
        owner_kind="mission", owner_id="mission-1", generation=1,
        resources=[("robot", "rosy_01")],
    ) is True


def test_terminal_task_result_releases_its_resource_claim(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    _queue(store)
    store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})
    attempt = store.mark_dispatching("task-1", worker_id="worker-a")
    store.project_core_event(
        robot_id="rosy_01", event_id="event-1", seq=1, event_type="nav.failed",
        correlation_id=attempt["attempt_id"],
    )

    assert store.get_task("task-1")["status"] == "FAILED"
    assert store.resource_claims(resource_kind="robot", resource_id="rosy_01") == []
