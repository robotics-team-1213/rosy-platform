"""Compose read-only planning from the existing owner's admitted state; no ROS/process imports."""
from .manipulation_plan import ExecutionStateSnapshot
from .transfer_preflight import TransferPreflight
from .transfer_preflight_api import TransferPreflightApi


def build_transfer_preflight_api(runtime, *, catalog, profile, kinematics,
                                 journal_id: str, allowed_peer_uids: set[int]) -> TransferPreflightApi:
    config = runtime.owner.config
    if (catalog.workcell_id, catalog.instance_id) != (config.workcell_id, config.instance_id):
        raise ValueError("physical catalog must belong to this existing owner")

    def measured_state():
        state = runtime.owner.joint_state
        if state is None:
            return None
        return ExecutionStateSnapshot(
            sequence=state.sequence, joint_positions=state.positions,
            calibration_revision=state.calibration_revision,
            transform_revision=catalog.transform_revision,
            planning_scene_revision=kinematics.planning_scene_revision,
            observed_at_monotonic_s=state.received_at)

    service = TransferPreflight(catalog, profile, kinematics,
                                execution_state=measured_state, monotonic=runtime.monotonic)
    return TransferPreflightApi(service, allowed_peer_uids=allowed_peer_uids, journal_id=journal_id)
