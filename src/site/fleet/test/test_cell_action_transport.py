"""CELL_TRANSFER uses the existing versioned phase receipt boundary."""

from datetime import datetime, timedelta, timezone

import pytest

from core_common.protocol.schemas import FleetCellTransferGrant
from fleet.server.step_action_kinds import step_grant_digest as cell_transfer_grant_digest
from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport


def _grant():
    now = datetime.now(timezone.utc)
    pose = {"x": 0.1, "y": 0.2, "z": 0.3, "yaw": 0.0}
    document = {
        "mission_id": "cell-mission", "step_id": "cell-step", "action_id": "cell-action",
        "attempt_id": "cell-attempt", "request_digest": "0" * 64,
        "workcell_id": "omx_01", "instance_id": "omx_01_control", "action_kind": "CELL_TRANSFER",
        "capability_revision": "cell-transfer-v1", "config_revision": "sim-config-v1",
        "authority_epoch": 1, "dispatch_generation": 2,
        "issued_at": now, "expires_at": now + timedelta(seconds=15),
        "cell_transfer": {
            "job_id": "a" * 64, "recipe_sha256": "b" * 64, "cell_sha256": "c" * 64,
            "step_index": 0, "item": "box", "pallet": "pallet-1", "layer": 0,
            "frame": "robot_base", "home": pose, "pick": pose, "place": pose,
            "pick_approach_z": 0.4, "place_approach_z": 0.4, "carry_z": 0.5,
        },
    }
    document["request_digest"] = cell_transfer_grant_digest(document)
    return FleetCellTransferGrant.model_validate(document)


def _response(grant, *, phases):
    return {"version": 2, "status": 200, "receipt": {
        **{field: getattr(grant, field) for field in (
            "mission_id", "step_id", "action_id", "attempt_id", "request_digest",
            "workcell_id", "instance_id", "authority_epoch", "dispatch_generation",
        )},
        "state": "ACCEPTED", "journal_event_id": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(), "driver_goal_id": "goal-1",
        "reason": None, "phase_summaries": phases,
    }}


@pytest.mark.parametrize("operation", ["submit", "get", "cancel"])
def test_cell_transfer_preserves_v2_phase_receipts_for_every_operation(tmp_path, operation):
    grant = _grant()
    client = UnixLocalActionTransport(tmp_path)
    requests = []

    def exchange(instance_id, request):
        requests.append((instance_id, request))
        return _response(grant, phases=[])

    client._exchange = exchange
    method = getattr(client, operation)
    receipt = method(grant, **({"reason": "SITE_STOP"} if operation == "cancel" else {}))
    assert requests[0][0] == grant.instance_id
    assert requests[0][1]["version"] == 2
    assert receipt.phase_summaries == ()
    assert receipt.action_id == grant.action_id and receipt.attempt_id == grant.attempt_id


@pytest.mark.parametrize("operation", ["submit", "get", "cancel"])
def test_cell_transfer_rejects_receipt_without_phase_summary(tmp_path, operation):
    grant = _grant()
    client = UnixLocalActionTransport(tmp_path)
    client._exchange = lambda _instance, _request: _response(grant, phases=None)
    with pytest.raises(LocalActionUnavailable, match="missing phase summaries"):
        getattr(client, operation)(grant, **({"reason": "SITE_STOP"} if operation == "cancel" else {}))
