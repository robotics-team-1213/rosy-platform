"""Stage review preserves owner reports without inventing physical failure causes."""
from importlib import import_module
import json

import pytest

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, installation, rig, claims, connect, create, admit
from test_physical_transfer_submission import prepared, authorize
from test_physical_transfer_outcomes import submitted, receipt, observe


def phase_receipt(submitted, state="FAILED", phases=("SUCCEEDED", "FAILED"), **changes):
    base = receipt(submitted)
    prefix = tuple(phase.model_copy(update={"state": result})
                   for phase, result in zip(base.phase_summaries, phases))
    return receipt(submitted, state=state, phase_summaries=prefix, **changes)


def review(submitted, response, *, job_status="HOLD", task_outcome="unknown"):
    grant = FleetArmTransferGrant.model_validate(submitted[5]["grant"])
    return import_module("fleet.server.physical_transfer_review").assess_transfer_execution(
        grant, response, job_status=job_status, task_outcome=task_outcome)


def test_reported_grasp_failure_is_not_a_physical_miss_or_retry_permission(submitted):
    result = review(submitted, phase_receipt(submitted, reason="controller_error"))
    assert result["failure_phase"] == "grasp"
    assert result["last_reported_phase"] == "grasp"
    assert result["owner_reason"] == "controller_error"
    assert result["task_outcome"] == "unknown" and result["physical_failure_cause"] is None
    assert result["recovery"]["next_step"] == "operator_review"
    assert result["recovery"]["execution_authorized"] is False
    assert result["recovery"]["automatic_retry_allowed"] is False


@pytest.mark.parametrize("phase_state", ["CANCELED", "UNKNOWN", "RUNNING", "SUCCEEDED"])
def test_cancel_uncertainty_or_success_is_not_labelled_a_failed_phase(submitted, phase_state):
    result = review(submitted, phase_receipt(submitted, state="HOLD",
        phases=("SUCCEEDED", phase_state), reason="object_hold_unconfirmed"))
    assert result["failure_phase"] is None
    assert result["owner_reason"] == "object_hold_unconfirmed"
    assert result["physical_failure_cause"] is None


@pytest.mark.parametrize("state,job,task,next_step", [
    ("UNKNOWN", "HOLD", "unknown", "reconcile_action"),
    ("CANCEL_REQUESTED", "HOLD", "unknown", "reconcile_action"),
    ("RUNNING", "RUNNING", "unknown", "wait_for_action_result"),
    ("SUCCEEDED", "ACTION_SUCCEEDED", "unknown", "reobserve_object"),
    ("SUCCEEDED", "ACTION_SUCCEEDED", "failed", "reobserve_object"),
    ("SUCCEEDED", "ACTION_SUCCEEDED", "succeeded", "verify_completion"),
    ("SUCCEEDED", "HOLD", "succeeded", "operator_review"),
    ("SUCCEEDED", "GOAL_CONFIRMED", "succeeded", "none"),
])
def test_next_step_uses_both_execution_and_current_task_state(submitted, state, job, task, next_step):
    result = review(submitted, receipt(submitted, state=state), job_status=job, task_outcome=task)
    assert result["recovery"]["next_step"] == next_step
    assert not result["recovery"]["execution_authorized"]


def test_inconsistent_phase_prefix_has_no_unambiguous_failure_stage(submitted):
    result = review(submitted, phase_receipt(submitted, phases=("FAILED", "FAILED")))
    assert result["failure_phase"] is None


def test_other_attempt_or_invalid_phase_order_cannot_supply_execution_review(submitted):
    with pytest.raises(ValueError):
        review(submitted, phase_receipt(submitted, attempt_id="another-attempt"))
    response = phase_receipt(submitted)
    with pytest.raises(ValueError):
        review(submitted, response.model_copy(update={"phase_summaries": response.phase_summaries[::-1]}))


def test_failed_action_without_endpoint_evidence_can_be_exported_without_state_changes(submitted, tmp_path):
    path, _, store, execution, job, _ = submitted
    value = phase_receipt(submitted)
    observe(submitted, value)
    before, occupied = execution.snapshot(job["mission_id"]), claims(path)
    output = tmp_path / "failure-review.json"
    exporter = import_module("fleet.server.physical_transfer_outcomes").export_transfer_outcomes
    result = exporter(store, job["mission_id"], output)
    assert json.loads(output.read_text()) == result
    assert result["schema"] == "rosy.transfer-outcome-export/2"
    assert result["outcomes"] == []
    assert result["execution_review"]["action_outcome"] == "FAILED"
    assert result["execution_review"]["failure_phase"] == "grasp"
    assert result["execution_review"]["phase_summaries"] == [
        phase.model_dump(mode="json") for phase in value.phase_summaries]
    assert result["scope"] == "unreviewed_metadata_only" and not result["behavior_training_eligible"]
    assert execution.snapshot(job["mission_id"]) == before and claims(path) == occupied


def test_export_rejects_replaced_owner_receipt_before_publishing(submitted, tmp_path):
    path, _, store, _, job, _ = submitted
    observe(submitted, phase_receipt(submitted))
    with connect(path) as connection:
        connection.execute("UPDATE fleet_cell_events SET detail_json=json_set(detail_json, "
            "'$.receipt.attempt_id','another-attempt') WHERE event_type='PHYSICAL_TRANSFER_RECEIPT'")
        connection.commit()
    output = tmp_path / "invalid-review.json"
    with pytest.raises(ValueError):
        import_module("fleet.server.physical_transfer_outcomes").export_transfer_outcomes(
            store, job["mission_id"], output)
    assert not output.exists()


@pytest.mark.parametrize("ttl,max_age_ns", [(1.5, 500_000_000), (30.0, 20_000_000_000)])
def test_export_uses_the_retained_grant_lifetime(rig, tmp_path, ttl, max_age_ns):
    from test_physical_transfer_preparation import prepare
    from fleet.server.physical_transfer_execution import PhysicalTransferExecution

    path, tasks, control, store = rig
    configured = store.installation.policy.model_copy(update={"max_age_ns": max_age_ns})
    caps = tuple(cap.model_copy(update={"resource_policy_digest": configured.digest})
                 for cap in store.installation.capabilities)
    store.installation = store.installation.model_copy(update={"policy": configured, "capabilities": caps})
    executor = PhysicalTransferExecution(store, grant_ttl_s=ttl)
    job = admit(store, create(store), control)
    row = prepare(executor, job["mission_id"], store)
    store._clock_ns = lambda: NOW + 350_000_000
    state = (path, tasks, store, executor, job, row)
    authorize(state)
    store._clock_ns = lambda: NOW + 400_000_000
    observe(state, phase_receipt(state))
    result = import_module("fleet.server.physical_transfer_outcomes").export_transfer_outcomes(
        store, job["mission_id"], tmp_path / "configured-grant.json")
    assert result["execution_review"]["failure_phase"] == "grasp"
