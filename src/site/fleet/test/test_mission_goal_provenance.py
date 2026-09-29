import time

import pytest

from fleet.server.goal_evidence import GoalEvidenceError
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.task_store import FleetTaskStore


def _evidence(*, observed_at, action_id="action-1", attempt_id="attempt-1", **changes):
    value = {
        "predicate_id": "block-in-tray", "object_id": "block-1",
        "destination_id": "tray-1", "evidence_source": "camera_observation",
        "evidence_id": "camera:post-action-1", "evidence_revision": "cal-4/tf-9",
        "producer_id": "registered-camera-evaluator", "observation_id": "obs-post-action",
        "observation_digest": "b" * 64, "evaluator_revision": "placement-check-v3",
        "action_id": action_id, "attempt_id": attempt_id,
        "gripper_state": "OPEN", "gripper_evidence_id": "gripper-readback-1",
        "gripper_evidence_revision": "gripper-driver-v2",
        "gripper_observed_at": observed_at, "observed_at": observed_at,
        "satisfied": True,
    }
    value.update(changes)
    return value


def _action_succeeded(tmp_path, *, verifier=None):
    database = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(database)
    generation = tasks.rearm_dispatch(expected_generation=0, actor_id="operator-1")["generation"]
    store = MissionStore(database)
    created = store.create_proposal(
        mission_id="mission-1", principal_id="operator-1", request_key="request-1",
        workcell_id="omx-1", instance_id="omx-1-control", action_kind="PICK_PLACE",
        plan={"observation_id": "obs-before", "image_sha256": "a" * 64,
              "source_evidence": {"observation_id": "obs-before", "frame_sha256": "a" * 64}},
        goal_predicate={"predicate_id": "block-in-tray", "condition": "object_in_destination",
                        "object_id": "block-1", "destination_id": "tray-1",
                        "evidence_source": "camera_observation"},
    )
    mission = created["mission"]
    admitted = store.admit(
        mission["mission_id"], actor_id="operator-1", expected_generation=generation,
        resources=[("workcell", "omx-1"), ("object", "block-1"), ("object", "tray-1")],
    )
    store.start_step(
        mission["mission_id"], action_id="action-1", attempt_id="attempt-1",
        expected_authority_epoch=admitted["authority_epoch"], expected_generation=generation,
    )
    store.record_action_result(
        mission["mission_id"], event_id="action-success-1", action_id="action-1",
        attempt_id="attempt-1", outcome="SUCCEEDED", result={"driver_goal_id": "goal-1"},
    )
    return store, MissionService(store, goal_evidence_verifier=verifier)


def _confirm(service, evidence):
    return service.confirm_goal(
        "mission-1", event_id="goal-evidence-1", evidence=evidence,
        now=evidence["observed_at"] + 0.1, max_age_s=2.0,
    )


def test_action_success_and_unverified_model_completion_do_not_complete_mission(tmp_path):
    store, service = _action_succeeded(tmp_path)
    assert store.get_mission("mission-1")["status"] == "ACTION_SUCCEEDED"

    with pytest.raises(GoalEvidenceError, match="trusted goal-evidence producer"):
        _confirm(service, _evidence(observed_at=time.time() + 1.0))

    assert store.get_mission("mission-1")["status"] == "HOLD"


@pytest.mark.parametrize("changes, reason", [
    ({"action_id": "old-action", "attempt_id": "old-attempt"}, "different Action attempt"),
    ({"observation_id": "obs-before", "observation_digest": "a" * 64}, "new post-action"),
    ({"gripper_state": "HOLDING"}, "gripper readback"),
    ({"producer_id": "unregistered-camera"}, "producer is not authenticated"),
    ({"evaluator_revision": ""}, "evaluator_revision"),
])
def test_goal_completion_refuses_uncorrelated_or_unsafe_evidence(tmp_path, changes, reason):
    store, service = _action_succeeded(
        tmp_path,
        verifier=lambda _mission, evidence: evidence.producer_id == "registered-camera-evaluator",
    )
    evidence = _evidence(observed_at=time.time() + 1.0, **changes)

    with pytest.raises(GoalEvidenceError, match=reason):
        _confirm(service, evidence)

    assert store.get_mission("mission-1")["status"] == "HOLD"


def test_oversized_rejected_evidence_is_bounded_before_audit_storage(tmp_path):
    store, service = _action_succeeded(tmp_path)
    oversized = "sensitive-" + "x" * 20_000

    with pytest.raises(GoalEvidenceError, match="producer_id"):
        _confirm(service, _evidence(observed_at=time.time() + 1.0,
                                    producer_id=oversized))

    detail = store.history("mission-1")[-1]["detail"]
    assert detail["reason"] == "GOAL_EVIDENCE_REJECTED"
    assert len(str(detail)) < 512
    assert detail["evidence"]["fields"]
    assert "sha256" in detail["evidence"]
    assert oversized not in str(detail)


def test_registered_current_producer_and_open_gripper_readback_confirm_matching_attempt(tmp_path):
    calls = []

    def verifier(mission, evidence):
        calls.append((mission["mission_id"], evidence.producer_id, evidence.evaluator_revision))
        return evidence.producer_id == "registered-camera-evaluator"

    store, service = _action_succeeded(tmp_path, verifier=verifier)
    completed = _confirm(service, _evidence(observed_at=time.time() + 1.0))

    assert completed["status"] == "GOAL_CONFIRMED"
    assert calls == [("mission-1", "registered-camera-evaluator", "placement-check-v3")]
    event = store.history("mission-1")[-1]
    assert event["event_type"] == "GOAL_PREDICATE_CONFIRMED"
    assert event["detail"]["observation_digest"] == "b" * 64
    assert event["detail"]["action_id"] == "action-1"
    assert event["detail"]["attempt_id"] == "attempt-1"
