import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core_common.protocol.schemas import ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS
from core_common.protocol.schemas import MissionFeedbackTurnScope
from fleet.server.mission_model_turn_store import MissionModelTurnStore
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalRejected, ProposalStore
from fleet.server.task_store import FleetTaskStore


def _candidate(observation_id="obs-post-action", observed_at="2026-09-30T12:01:00+00:00"):
    return {
        "request_id": "feedback-turn-1",
        "source": "gemini_robotics_er2",
        "model_id": "gemini-robotics-er2",
        "provider_interaction_id": "interaction-1",
        "provider_call_id": "call-1",
        "instruction": "Move the red block to the green tray",
        "source_observation": {
            "observation_id": observation_id,
            "camera_id": "camera-top", "frame_id": "frame-8",
            "observed_at": observed_at,
            "image_sha256": "a" * 64,
            "coordinate_space": "image_normalized_yx_0_1000",
            "image_transform": {
                "source_width": 640, "source_height": 480,
                "crop_xyxy": [0, 0, 640, 480],
                "model_width": 640, "model_height": 480,
                "rotation_quadrants_clockwise": 0,
            },
            "calibration_revision": "cal-4", "transform_revision": "tf-9",
        },
        "target_selector": {"label": "red block", "point_yx_1000": [575, 664]},
        "destination_selector": {"label": "green tray", "point_yx_1000": [475, 305]},
    }


def _setup(tmp_path):
    db_path = tmp_path / "fleet.sqlite3"
    task_store = FleetTaskStore(db_path)
    mission_store = MissionStore(db_path)
    turn_store = MissionModelTurnStore(db_path)
    proposal_store = ProposalStore(db_path)
    created = mission_store.create_proposal(
        mission_id="mission-source", principal_id="operator-1",
        request_key="source-request", action_kind="PICK_PLACE",
        workcell_id="omx_01", instance_id="omx_01_control",
        plan={"instruction": "Move the red block to the green tray",
              "observation_id": "obs-initial", "image_sha256": "b" * 64},
        goal_predicate={"predicate_id": "block-in-tray",
                        "condition": "object_in_destination",
                        "object_id": "red-block", "destination_id": "green-tray",
                        "evidence_source": "camera_observation"},
    )
    mission = created["mission"]
    terminal_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE fleet_dispatch_control SET generation=4, dispatch_enabled=1, "
                   "reason='TEST_ENABLED' WHERE control_id=1")
        db.execute("UPDATE fleet_missions SET status='HOLD', reason='GOAL_NOT_SATISFIED', "
                   "dispatch_generation=4, action_id='action-1', attempt_id='attempt-1' "
                   "WHERE mission_id='mission-source'")
        db.execute(
            """INSERT INTO fleet_mission_events
               (event_source, source_event_id, mission_id, step_id, action_id, attempt_id,
                state, event_type, actor_id, detail_json, created_at)
               VALUES ('test', 'terminal', ?, ?, 'action-1', 'attempt-1',
                       'ACTION_SUCCEEDED', 'ACTION_TERMINAL_RESULT', 'test', '{}', ?)""",
            ("mission-source", mission["step_id"], terminal_at.isoformat()),
        )
        db.execute(
            """INSERT INTO fleet_mission_events
               (event_source, source_event_id, mission_id, step_id, action_id, attempt_id,
                state, event_type, actor_id, detail_json, created_at)
               VALUES ('test', 'unsatisfied', ?, ?, 'action-1', 'attempt-1',
                       'HOLD', 'GOAL_PREDICATE_UNSATISFIED', 'test', '{}', ?)""",
            ("mission-source", mission["step_id"],
             (terminal_at + timedelta(seconds=1)).isoformat()),
        )
    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-source", "action_id": "action-1",
        "attempt_id": "attempt-1", "dispatch_generation": 4,
        "event_watermark": 3, "model_policy_revision": "policy-v1",
        "outcome_policy": "STATUS_AND_REPLAN",
    })
    turn = turn_store.enqueue(scope=scope, trigger_event_id=3)["turn"]
    assert turn_store.claim(turn["turn_id"], worker_id="worker-1")
    assert turn_store.begin_submission_fenced(
        turn["turn_id"], worker_id="worker-1",
    )["state"] == "SUBMITTING"
    observed_at = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    observation = {
        "mission_id": "mission-source", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "based_on_event_id": 3,
        "observation_id": "obs-post-action",
        "observed_at": observed_at,
        "image_sha256": "a" * 64,
    }
    return db_path, task_store, mission_store, turn_store, proposal_store, turn, observation


def test_candidate_insert_and_stop_generation_check_share_one_transaction(tmp_path):
    db_path, task_store, _missions, _turns, proposals, turn, observation = _setup(tmp_path)
    task_store.trip_stop_latch(actor_id="operator-1", reason="TEST_STOP")

    with pytest.raises(ProposalRejected, match="STOP_FENCE_CLOSED"):
        proposals.create_feedback_candidate_fenced(
            turn_id=turn["turn_id"],
            candidate=_candidate(observed_at=observation["observed_at"]),
            observation=observation,
        )

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_proposals").fetchone()[0] == 0


def test_candidate_insert_is_idempotent_and_keeps_source_correlation(tmp_path):
    _db_path, _task_store, _missions, _turns, proposals, turn, observation = _setup(tmp_path)

    first = proposals.create_feedback_candidate_fenced(
        turn_id=turn["turn_id"], candidate=_candidate(observed_at=observation["observed_at"]), observation=observation,
    )
    replay = proposals.create_feedback_candidate_fenced(
        turn_id=turn["turn_id"], candidate=_candidate(observed_at=observation["observed_at"]), observation=observation,
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["proposal"]["proposal_id"] == first["proposal"]["proposal_id"]
    assert first["proposal"]["source_mission_id"] == "mission-source"
    assert first["proposal"]["source_action_id"] == "action-1"
    assert first["proposal"]["source_attempt_id"] == "attempt-1"
    assert first["proposal"]["source_event_watermark"] == 3
    assert first["proposal"]["supersedes_mission_id"] == "mission-source"


def test_feedback_candidate_resolution_creates_a_linked_successor_mission(tmp_path):
    _db_path, _task_store, missions, _turns, proposals, turn, observation = _setup(tmp_path)
    candidate = proposals.create_feedback_candidate_fenced(
        turn_id=turn["turn_id"],
        candidate=_candidate(observed_at=observation["observed_at"]),
        observation=observation,
    )["proposal"]

    _resolved, successor, created = proposals.finalize_resolution(
        missions, proposal_id=candidate["proposal_id"], principal_id="operator-1",
        resolution={"source": "operator-review"},
        mission_request={
            "plan": {"instruction": "Place the red block into the tray"},
            "goal_predicate": {
                "predicate_id": "block-in-tray", "condition": "object_in_destination",
                "object_id": "red-block", "destination_id": "green-tray",
                "evidence_source": "camera_observation",
            },
        },
    )

    assert created is True
    assert successor["mission_id"] == candidate["proposal_id"]
    assert successor["supersedes_mission_id"] == "mission-source"


def test_candidate_created_before_stop_becomes_non_resolvable_after_stop(tmp_path):
    _db_path, task_store, missions, _turns, proposals, turn, observation = _setup(tmp_path)
    candidate = proposals.create_feedback_candidate_fenced(
        turn_id=turn["turn_id"],
        candidate=_candidate(observed_at=observation["observed_at"]),
        observation=observation,
    )["proposal"]
    task_store.trip_stop_latch(actor_id="operator-1", reason="TEST_STOP")

    with pytest.raises(ProposalRejected, match="STOP_FENCE_CLOSED"):
        proposals.finalize_resolution(
            missions, proposal_id=candidate["proposal_id"], principal_id="operator-1",
            resolution={"source": "operator-review"},
            mission_request={
                "plan": {"instruction": "Place the red block into the tray"},
                "goal_predicate": {
                    "predicate_id": "block-in-tray", "condition": "object_in_destination",
                    "object_id": "red-block", "destination_id": "green-tray",
                    "evidence_source": "camera_observation",
                },
            },
        )

    assert proposals.get(candidate["proposal_id"])["state"] == "REJECTED"
    assert missions.get_mission(candidate["proposal_id"]) is None


@pytest.mark.parametrize("change, reason", [
    ("event", "EVENT_WATERMARK_STALE"),
    ("observation", "OBSERVATION_SCOPE_MISMATCH"),
])
def test_candidate_is_rejected_when_event_or_observation_scope_changes(tmp_path, change, reason):
    db_path, _task_store, _missions, _turns, proposals, turn, observation = _setup(tmp_path)
    if change == "event":
        with sqlite3.connect(db_path) as db:
            db.execute(
                """INSERT INTO fleet_mission_events
                   (event_source, source_event_id, mission_id, step_id, state,
                    event_type, actor_id, detail_json, created_at)
                   VALUES ('test', 'late', 'mission-source', 'mission-source:step-1',
                           'HOLD', 'LATE_EVENT', 'test', '{}', '2026-09-30T12:02:00+00:00')"""
            )
    else:
        observation["attempt_id"] = "different-attempt"

    with pytest.raises(ProposalRejected, match=reason):
        proposals.create_feedback_candidate_fenced(
            turn_id=turn["turn_id"],
            candidate=_candidate(observed_at=observation["observed_at"]),
            observation=observation,
        )


def test_candidate_requires_a_recent_post_action_observation(tmp_path):
    _db_path, _task_store, _missions, _turns, proposals, turn, observation = _setup(tmp_path)
    observation["observed_at"] = (
        datetime.now(timezone.utc)
        - timedelta(seconds=ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS + 1)
    ).isoformat()

    with pytest.raises(ProposalRejected, match="OBSERVATION_NOT_FRESH"):
        proposals.create_feedback_candidate_fenced(
            turn_id=turn["turn_id"],
            candidate=_candidate(observed_at=observation["observed_at"]),
            observation=observation,
        )
