"""Owner-reported phases and advisory next steps, without physical cause inference."""
from core_common.protocol.device_actions import DeviceActionReceipt

from .action_receipts import verify_phase_receipt


def assess_transfer_execution(grant, response, *, job_status, task_outcome):
    if job_status not in {"RUNNING", "HOLD", "ACTION_SUCCEEDED", "GOAL_CONFIRMED"}:
        raise ValueError("unsupported transfer job status")
    if task_outcome not in {"succeeded", "failed", "unknown"}:
        raise ValueError("unsupported task outcome")
    raw = response.model_dump(mode="json") if isinstance(response, DeviceActionReceipt) else response
    receipt = verify_phase_receipt(grant, raw, phase_ids=("approach", "grasp", "transfer", "release"))
    phases = receipt.phase_summaries
    state = receipt.state.value
    failed = [phase for phase in phases if phase.state == "FAILED"]
    failure_phase = None
    if (state == "FAILED" and len(failed) == 1 and failed[0] == phases[-1]
            and all(phase.state == "SUCCEEDED" for phase in phases[:-1])):
        failure_phase = failed[0].phase_id
    if state in {"UNKNOWN", "CANCEL_REQUESTED"}:
        next_step = "reconcile_action"
    elif job_status == "HOLD" or state in {"FAILED", "HOLD"}:
        next_step = "operator_review"
    elif state != "SUCCEEDED":
        next_step = "wait_for_action_result"
    elif job_status == "GOAL_CONFIRMED" and task_outcome == "succeeded":
        next_step = "none"
    elif job_status == "ACTION_SUCCEEDED":
        next_step = "verify_completion" if task_outcome == "succeeded" else "reobserve_object"
    else:
        next_step = "operator_review"
    return dict(schema="rosy.transfer-execution-review/1", scope="owner_reported_execution_only",
        action_id=receipt.action_id, attempt_id=receipt.attempt_id, action_outcome=state,
        owner_journal_id=receipt.journal_id, journal_event_id=receipt.journal_event_id,
        observed_at=receipt.observed_at.isoformat(), owner_reason=receipt.reason,
        phase_summaries=[phase.model_dump(mode="json") for phase in phases],
        failure_phase=failure_phase, last_reported_phase=phases[-1].phase_id if phases else None,
        task_outcome=task_outcome, physical_failure_cause=None,
        recovery=dict(next_step=next_step, execution_authorized=False, automatic_retry_allowed=False))
