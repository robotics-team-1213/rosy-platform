"""Cell goal recovery needs durable success of the exact current attempt."""

import pytest

from fleet.server.cell_job_store import CellJobStore
from fleet.server.mission_store import MissionConflict
from test_cell_job_store import _create, _goal, _grant, _stores


def _started(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    grant = _grant(ready, 0)
    store.start_step("cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0", grant=grant)
    return path, tasks, store


def _outcome(store, state, event_id):
    return store.record_action_result(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        event_id=event_id, outcome=state, result={"local_state": state},
    )


def _confirm(store, evidence_id="goal-0"):
    return store.confirm_step_goal(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        evidence=_goal("action-0", "attempt-0", evidence_id),
    )


def test_reopened_cell_hold_needs_late_success_and_independent_goal(tmp_path):
    path, tasks, store = _started(tmp_path)
    _outcome(store, "UNKNOWN", "lost-reply")
    reopened = CellJobStore(path)
    with pytest.raises(MissionConflict):
        _confirm(reopened)
    _outcome(reopened, "SUCCEEDED", "late-success")
    assert reopened.get("cell-mission-1")["status"] == "HOLD"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    confirmed = _confirm(reopened)
    assert confirmed["status"] == "READY" and confirmed["current_step_index"] == 1
    assert confirmed["steps"][0]["status"] == "GOAL_CONFIRMED"
    assert confirmed["steps"][1]["status"] == "READY"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    assert _confirm(reopened) == confirmed


@pytest.mark.parametrize("terminal", [None, "FAILED", "UNKNOWN", "HOLD"])
def test_forged_success_projection_cannot_replace_terminal_proof(tmp_path, terminal):
    _, tasks, store = _started(tmp_path)
    if terminal is not None:
        _outcome(store, terminal, "device-terminal")
    with store._connect() as connection:
        connection.execute("UPDATE fleet_cell_jobs SET status='ACTION_SUCCEEDED'")
        connection.execute("UPDATE fleet_cell_steps SET status='ACTION_SUCCEEDED' WHERE step_index=0")
        connection.commit()
    previous = store.get("cell-mission-1")
    with pytest.raises(MissionConflict, match="terminal Action success"):
        _confirm(store)
    assert store.get("cell-mission-1") == previous
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1")


def test_newer_unknown_outcome_supersedes_an_earlier_success(tmp_path):
    _, tasks, store = _started(tmp_path)
    _outcome(store, "UNKNOWN", "lost-reply")
    _outcome(store, "SUCCEEDED", "late-success")
    _outcome(store, "UNKNOWN", "conflicting-readback")
    with pytest.raises(MissionConflict, match="terminal Action success"):
        _confirm(store)
    assert store.get("cell-mission-1")["status"] == "HOLD"
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1")


def test_goal_confirmation_after_stop_preserves_next_step_fence(tmp_path):
    path, tasks, store = _started(tmp_path)
    _outcome(store, "SUCCEEDED", "device-terminal")
    tasks.trip_stop_latch(actor_id="operator-1")
    confirmed = _confirm(CellJobStore(path))
    assert confirmed["status"] == "HOLD" and confirmed["reason"] == "SITE_AUTHORITY_CHANGED"
    assert confirmed["steps"][0]["status"] == "GOAL_CONFIRMED"
    assert confirmed["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    with pytest.raises(MissionConflict, match="current READY"):
        store.start_step("cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
                         grant=_grant(confirmed, 1))


def test_duplicate_goal_is_idempotent_and_different_evidence_cannot_rewrite_it(tmp_path):
    _, _, store = _started(tmp_path)
    _outcome(store, "SUCCEEDED", "device-terminal")
    confirmed = _confirm(store)
    assert _confirm(CellJobStore(store.path)) == confirmed
    with pytest.raises(MissionConflict):
        _confirm(store, "different-goal")
    assert store.get("cell-mission-1") == confirmed


@pytest.mark.parametrize("field", ["producer_id", "evidence_id", "gripper_evidence_id"])
def test_empty_goal_provenance_does_not_advance_the_cell_job(tmp_path, field):
    _, tasks, store = _started(tmp_path)
    _outcome(store, "SUCCEEDED", "device-terminal")
    evidence = _goal("action-0", "attempt-0", "goal-0")
    evidence[field] = ""
    with pytest.raises(ValueError):
        store.confirm_step_goal("cell-mission-1", step_index=0, action_id="action-0",
                                attempt_id="attempt-0", evidence=evidence)
    assert store.get("cell-mission-1")["status"] == "ACTION_SUCCEEDED"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_previous_attempt_success_cannot_confirm_a_different_attempt(tmp_path):
    _, tasks, store = _started(tmp_path)
    _outcome(store, "SUCCEEDED", "device-terminal")
    with store._connect() as connection:
        connection.execute("UPDATE fleet_cell_steps SET attempt_id='different-attempt' WHERE step_index=0")
        connection.commit()
    with pytest.raises(MissionConflict, match="terminal Action success"):
        store.confirm_step_goal("cell-mission-1", step_index=0, action_id="action-0",
                                attempt_id="different-attempt",
                                evidence=_goal("action-0", "different-attempt", "goal-0"))
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_final_held_success_releases_claims_only_after_both_independent_goals(tmp_path):
    path, tasks, store = _started(tmp_path)
    _outcome(store, "SUCCEEDED", "device-terminal")
    first_confirmed = _confirm(store)
    grant = _grant(first_confirmed, 1)
    store.start_step("cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1", grant=grant)
    store.record_action_result("cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
                               event_id="lost-reply-1", outcome="UNKNOWN", result={"state": "UNKNOWN"})
    tasks.trip_stop_latch(actor_id="operator-1")
    reopened = CellJobStore(path)
    reopened.record_action_result("cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
                                  event_id="late-success-1", outcome="SUCCEEDED", result={"state": "SUCCEEDED"})
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    assert reopened.get("cell-mission-1")["status"] == "HOLD"
    evidence = _goal("action-1", "attempt-1", "goal-1")
    confirmed = reopened.confirm_step_goal("cell-mission-1", step_index=1, action_id="action-1",
                                           attempt_id="attempt-1", evidence=evidence)
    assert confirmed["status"] == "GOAL_CONFIRMED"
    assert all(step["status"] == "GOAL_CONFIRMED" for step in confirmed["steps"])
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01") == []
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1") == []
    assert tasks.dispatch_control()["dispatch_enabled"] is False
    assert reopened.confirm_step_goal("cell-mission-1", step_index=1, action_id="action-1",
                                      attempt_id="attempt-1", evidence=evidence) == confirmed
