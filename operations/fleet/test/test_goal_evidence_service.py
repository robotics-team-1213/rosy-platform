from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml

from fleet.server.goal_evidence_registry import load_goal_evidence_registry
from fleet.server.goal_evidence_service import (
    GoalEvidenceService, GoalEvidenceSubmissionError,
)
from fleet.server.goal_evidence_store import GoalEvidenceStore


class _Missions:
    def __init__(self):
        self.goal_evidence_verifier = None
        self.mission = {
            "mission_id": "mission-1", "status": "READY", "workcell_id": "omx_01",
            "action_id": "action-1", "attempt_id": "attempt-1",
            "goal_predicate": {
                "predicate_id": "red-block-in-green-tray",
                "condition": "object_in_destination", "object_id": "red-block-1",
                "destination_id": "green-tray-1", "evidence_source": "camera_observation",
            },
        }

    def get(self, mission_id):
        return self.mission if mission_id == "mission-1" else None


class _MissionStore:
    def __init__(self, rows):
        self.rows = rows
        self.held = []

    def missions_awaiting_goal_evidence(self):
        return self.rows

    def hold_mission(self, mission_id, **kwargs):
        self.held.append((mission_id, kwargs))
        return {"mission_id": mission_id, "status": "HOLD"}


def _config(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"producers": [{
        "producer_id": "top-camera-evaluator", "token_env": "GOAL_TOKEN",
        "workcell_id": "omx_01", "predicate_id": "red-block-in-green-tray",
        "object_id": "red-block-1", "destination_id": "green-tray-1",
        "evidence_source": "camera_observation", "max_age_s": 5,
        "grace_s": 10, "evaluator_revisions": ["placement-v1"],
        "valid_until": "2026-10-01T00:00:00+00:00",
    }]}), encoding="utf-8")
    return path


def _evidence(**updates):
    value = {
        "predicate_id": "red-block-in-green-tray", "object_id": "red-block-1",
        "destination_id": "green-tray-1", "evidence_source": "camera_observation",
        "evidence_id": "evidence-1", "evidence_revision": "revision-1",
        "producer_id": "top-camera-evaluator", "observation_id": "observation-2",
        "observation_digest": "a" * 64, "evaluator_revision": "placement-v1",
        "action_id": "action-1", "attempt_id": "attempt-1", "gripper_state": "OPEN",
        "gripper_evidence_id": "gripper-1", "gripper_evidence_revision": "gripper-r1",
        "gripper_observed_at": 1790726400.0, "observed_at": 1790726400.0,
        "satisfied": True,
    }
    value.update(updates)
    return value


def _service(tmp_path, missions=None):
    missions = missions or _Missions()
    registry = load_goal_evidence_registry(
        _config(tmp_path), environ={"GOAL_TOKEN": "source-secret"},
    )
    service = GoalEvidenceService(
        missions, registry, GoalEvidenceStore(tmp_path / "evidence.sqlite3"),
        now=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp(),
    )
    return service, missions


def test_registered_evidence_is_accepted_and_waits_for_terminal_action(tmp_path):
    service, missions = _service(tmp_path)

    result = service.submit(token="source-secret", mission_id="mission-1",
                            raw_evidence=_evidence())

    assert result["state"] == "PENDING_ACTION_TERMINAL"
    assert result["created"] is True
    assert callable(missions.goal_evidence_verifier)


def test_evidence_authentication_scope_revision_and_freshness_fail_closed(tmp_path):
    service, _ = _service(tmp_path)

    with pytest.raises(GoalEvidenceSubmissionError) as unauthorized:
        service.submit(token="wrong", mission_id="mission-1", raw_evidence=_evidence())
    assert unauthorized.value.status_code == 401
    for payload in (
        _evidence(evaluator_revision="unapproved"),
        _evidence(object_id="other-object"),
        _evidence(observed_at=1790726390.0),
    ):
        with pytest.raises(GoalEvidenceSubmissionError):
            service.submit(token="source-secret", mission_id="mission-1", raw_evidence=payload)


def test_evidence_replay_with_changed_content_is_conflict(tmp_path):
    service, _ = _service(tmp_path)
    service.submit(token="source-secret", mission_id="mission-1", raw_evidence=_evidence())

    with pytest.raises(GoalEvidenceSubmissionError) as conflict:
        service.submit(token="source-secret", mission_id="mission-1",
                       raw_evidence=_evidence(evidence_revision="revision-2"))
    assert conflict.value.code == "EVIDENCE_ID_CONFLICT"


def test_missing_evidence_moves_successful_action_to_hold_after_registered_grace(tmp_path):
    service, missions = _service(tmp_path)
    terminal_mission = {
        **missions.mission,
        "status": "ACTION_SUCCEEDED",
        "action_terminal_at": "2026-09-29T23:59:30+00:00",
    }
    missions.store = _MissionStore([terminal_mission])

    held_count = service.hold_expired_without_evidence()

    assert held_count == 1
    assert missions.store.held[0][1]["reason"] == "GOAL_EVIDENCE_TIMEOUT"
