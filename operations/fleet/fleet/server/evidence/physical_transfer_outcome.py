"""Advisory post-action task assessment; never admission or claim release."""
from dataclasses import dataclass

from .physical_transfer_evidence import (
    PhysicalEvidenceRejected, _pose_matches, validate_transfer_bindings, validate_transfer_clearance,
)


@dataclass(frozen=True)
class TransferOutcome:
    action_outcome: str
    task_outcome: str
    reason: str | None


def assess_transfer_outcome(policy, context, samples, *, action_state, now_ns, authenticated_producer_id):
    if action_state not in {"SUCCEEDED", "FAILED", "UNKNOWN", "HOLD", "CANCEL_REQUESTED", "RUNNING"}:
        raise ValueError("unsupported action state")
    policy, context = validate_transfer_bindings(policy, context, samples, now_ns=now_ns,
                                                authenticated_producer_id=authenticated_producer_id)
    if context.phase != "POST_ACTION":
        raise ValueError("task assessment requires post-action observations")
    if action_state != "SUCCEEDED":
        return TransferOutcome(action_state, "unknown", "ACTION_NOT_SUCCEEDED")
    if any(sample.object_pose is None for sample in samples):
        return TransferOutcome(action_state, "unknown", "OBJECT_POSE_UNKNOWN")
    try:
        validate_transfer_clearance(policy, samples)
    except PhysicalEvidenceRejected as exc:
        return TransferOutcome(action_state, "unknown", str(exc))
    matched = [_pose_matches(sample.object_pose, policy.target_pose, policy) for sample in samples]
    if all(matched):
        return TransferOutcome(action_state, "succeeded", None)
    if any(matched) or not _pose_matches(samples[0].object_pose, samples[1].object_pose, policy):
        return TransferOutcome(action_state, "unknown", "OBJECT_OBSERVATIONS_CONFLICT")
    return TransferOutcome(action_state, "failed", "TARGET_NOT_REACHED")
