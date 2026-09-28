import pytest

from fleet.server.mission_store import MissionConflict, MissionStore
from fleet.server.task_store import FleetTaskStore


# Deliberately not named `setup`. pytest 7.4 (what CI runs) still honours the
# nose convention and, when a module-level `setup` accepts one argument, calls
# it with the **test module** — so `tmp_path / "fleet.sqlite3"` evaluated as
# `module / "fleet.sqlite3"` and every test here errored at setup. pytest 8
# dropped that support, so the collision only shows on the older interpreter.
def _stores(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(path)
    state = tasks.dispatch_control()
    enabled = tasks.rearm_dispatch(expected_generation=state["generation"], actor_id="operator-1")
    missions = MissionStore(path)
    return tasks, missions, enabled["generation"]


def proposal(store, mission_id="mission-1", plan=None):
    return store.create_proposal(
        mission_id=mission_id, principal_id="operator-1", request_key=mission_id,
        action_kind="PICK_PLACE", workcell_id="omx_01", instance_id="omx_01_control",
        plan=plan or {"source": "block-1", "destination": "tray-1", "observation_id": "obs-44"},
        goal_predicate={
            "predicate_id": "block-in-tray", "condition": "object_in_destination",
            "object_id": "block-1", "destination_id": "tray-1",
            "evidence_source": "camera_observation",
        },
    )


def test_mission_proposal_is_idempotent_and_goal_predicate_is_immutable(tmp_path):
    _, store, _ = _stores(tmp_path)
    first = proposal(store)
    duplicate = proposal(store, plan={
        "observation_id": "obs-44", "destination": "tray-1", "source": "block-1",
    })

    assert first["created"] is True
    assert duplicate["created"] is False
    assert first["mission"]["mission_id"] == duplicate["mission"]["mission_id"]
    with pytest.raises(MissionConflict):
        proposal(store, plan={"source": "block-2", "destination": "tray-1",
                              "observation_id": "obs-44"})


def test_admission_and_shared_resource_claim_are_atomic(tmp_path):
    tasks, store, generation = _stores(tmp_path)
    mission = proposal(store)["mission"]
    assert tasks.reserve_resources(
        owner_kind="direct_action", owner_id="other-action", generation=generation,
        resources=[("object", "block-1")],
    )

    with pytest.raises(MissionConflict, match="resource"):
        store.admit(mission["mission_id"], actor_id="operator-1",
                    expected_generation=generation,
                    resources=[("robot", "rosy_01"), ("workcell", "omx_01"),
                               ("object", "block-1")])
    assert store.get_mission(mission["mission_id"])["status"] == "PROPOSED"
    assert tasks.resource_claims(resource_kind="robot", resource_id="rosy_01") == []


def test_step_start_requires_generation_and_a_live_claim(tmp_path):
    tasks, store, generation = _stores(tmp_path)
    mission = proposal(store)["mission"]
    admitted = store.admit(mission["mission_id"], actor_id="operator-1",
                           expected_generation=generation,
                           resources=[("workcell", "omx_01"), ("object", "block-1")])
    assert admitted["status"] == "READY"
    tasks.trip_stop_latch(actor_id="operator-1")

    with pytest.raises(MissionConflict, match="stop generation"):
        store.start_step(mission["mission_id"], action_id="action-1",
                         attempt_id="attempt-1", expected_generation=generation)
    assert store.get_mission(mission["mission_id"])["status"] == "HOLD"
    assert tasks.resource_claims(resource_kind="object", resource_id="block-1") == []
    assert store.history(mission["mission_id"])[-1]["event_type"] == "STEP_HELD_BEFORE_SUBMISSION"


def test_step_start_rejects_boolean_generation_even_when_it_compares_equal(tmp_path):
    _, store, generation = _stores(tmp_path)
    mission = proposal(store)["mission"]
    store.admit(mission["mission_id"], actor_id="operator-1", expected_generation=generation,
                resources=[("workcell", "omx_01"), ("object", "block-1")])
    with pytest.raises(ValueError, match="non-negative integer"):
        store.start_step(mission["mission_id"], action_id="action-1",
                         attempt_id="attempt-1", expected_generation=True)


def test_driver_action_success_does_not_confirm_goal_and_goal_evidence_releases_claim(tmp_path):
    tasks, store, generation = _stores(tmp_path)
    mission = proposal(store)["mission"]
    store.admit(mission["mission_id"], actor_id="operator-1", expected_generation=generation,
                resources=[("workcell", "omx_01"), ("object", "block-1")])
    store.start_step(mission["mission_id"], action_id="action-1",
                     attempt_id="attempt-1", expected_generation=generation)

    action_succeeded = store.record_action_result(
        mission["mission_id"], event_id="event-action-final", action_id="action-1",
        attempt_id="attempt-1", outcome="SUCCEEDED", result={"driver_result": "SUCCEEDED"},
    )
    assert action_succeeded["status"] == "ACTION_SUCCEEDED"
    assert tasks.resource_claims(resource_kind="object", resource_id="block-1")

    from fleet.server.mission_service import MissionService
    completed = MissionService(store).confirm_goal(
        mission["mission_id"], event_id="event-goal-evidence", evidence={
            "predicate_id": "block-in-tray", "object_id": "block-1",
            "destination_id": "tray-1", "evidence_source": "camera_observation",
            "evidence_id": "camera:frame-55", "evidence_revision": "cal-v3/tf-v7",
            "observed_at": 10.0, "satisfied": True,
        }, now=10.2, max_age_s=0.5,
    )
    assert completed["status"] == "GOAL_CONFIRMED"
    assert tasks.resource_claims(resource_kind="object", resource_id="block-1") == []
    assert [event["event_type"] for event in store.history(mission["mission_id"])] == [
        "MISSION_PROPOSED", "MISSION_ADMITTED", "STEP_SUBMITTED",
        "ACTION_TERMINAL_RESULT", "GOAL_PREDICATE_CONFIRMED",
    ]


def test_unknown_action_and_stale_goal_keep_claim_held_across_restart(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    tasks, store, generation = _stores(tmp_path)
    mission = proposal(store)["mission"]
    store.admit(mission["mission_id"], actor_id="operator-1", expected_generation=generation,
                resources=[("workcell", "omx_01"), ("object", "block-1")])
    store.start_step(mission["mission_id"], action_id="action-1",
                     attempt_id="attempt-1", expected_generation=generation)
    held = store.record_action_result(
        mission["mission_id"], event_id="event-action-unknown", action_id="action-1",
        attempt_id="attempt-1", outcome="UNKNOWN", result={"reason": "result_missing"},
    )
    assert held["status"] == "HOLD"
    assert MissionStore(path).get_mission(mission["mission_id"])["status"] == "HOLD"
    assert tasks.resource_claims(resource_kind="object", resource_id="block-1")
