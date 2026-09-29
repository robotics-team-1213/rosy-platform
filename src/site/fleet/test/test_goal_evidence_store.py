from __future__ import annotations

import pytest

from fleet.server.goal_evidence_store import GoalEvidenceConflict, GoalEvidenceStore


def _evidence(**overrides):
    value = {
        "evidence_id": "evidence-1",
        "producer_id": "top-camera-evaluator",
        "predicate_id": "red-block-in-green-tray",
        "action_id": "action-1",
        "attempt_id": "attempt-1",
        "satisfied": True,
    }
    value.update(overrides)
    return value


def test_goal_evidence_store_is_idempotent_and_records_receive_time(tmp_path):
    store = GoalEvidenceStore(tmp_path / "fleet.sqlite3")

    first = store.submit(_evidence(), received_at=1790726400.0)
    retry = store.submit(_evidence(), received_at=1790726401.0)

    assert first["created"] is True
    assert first["received_at"] == 1790726400.0
    assert retry == {**first, "created": False}
    assert store.get("evidence-1")["evidence"]["action_id"] == "action-1"


def test_goal_evidence_store_rejects_replay_with_changed_content(tmp_path):
    store = GoalEvidenceStore(tmp_path / "fleet.sqlite3")
    store.submit(_evidence(), received_at=1790726400.0)

    with pytest.raises(GoalEvidenceConflict, match="reused with different"):
        store.submit(_evidence(satisfied=False), received_at=1790726401.0)


def test_goal_evidence_store_rejects_invalid_or_nonfinite_input(tmp_path):
    store = GoalEvidenceStore(tmp_path / "fleet.sqlite3")

    with pytest.raises(ValueError):
        store.submit({"evidence_id": "evidence-1", "raw": float("nan")}, received_at=1.0)
    with pytest.raises(ValueError):
        store.submit(_evidence(evidence_id=" "), received_at=1.0)


def test_goal_evidence_store_survives_reopen(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    GoalEvidenceStore(path).submit(_evidence(), received_at=1790726400.0)

    assert GoalEvidenceStore(path).get("evidence-1")["evidence"]["producer_id"] == (
        "top-camera-evaluator"
    )
