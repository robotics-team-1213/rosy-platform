"""Real Fleet/OMX JSON producer-consumer contract; no socket or physical driver."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core_common.protocol.schemas import FleetActionGrant
from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport


@pytest.fixture
def exchange(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "src/products/omx/adapter"))
    from omx_adapter.action_api import ActionApi, action_grant_digest
    from omx_adapter.action_runner import ActionRunner, DriverSubmission
    from omx_adapter.action_store import ActionStore
    from omx_adapter.local_stop import LocalStopController

    now = datetime.now(timezone.utc)
    source = {
        "object_id": "block-1", "observation_id": "obs-1", "frame_sha256": "b" * 64,
        "camera_identity": "cam-1", "optical_frame_id": "cam_optical",
        "calibration_revision": "cal-1", "transform_revision": "tf-1",
        "capture_time_ns": 1760000000000000000, "selector_kind": "point",
        "image_bbox_xyxy": [1, 2, 3, 4],
    }
    document = {
        "mission_id": "mission-1", "step_id": "step-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "request_digest": "0" * 64,
        "workcell_id": "omx-1", "instance_id": "omx-1-control", "action_kind": "PICK_PLACE",
        "source_evidence": source, "destination_evidence": {**source, "object_id": "tray-1"},
        "capability_revision": "pick-place-v1", "config_revision": "cfg-1",
        "observation_revision": "obs-1", "authority_epoch": 2, "dispatch_generation": 8,
        "issued_at": now, "expires_at": now + timedelta(minutes=5),
    }
    document["request_digest"] = action_grant_digest(document)
    grant = FleetActionGrant.model_validate(document)
    submissions, cancellations = [], []

    class Driver:
        def submit(self, request):
            submissions.append((request.action_id, request.attempt_id))
            return DriverSubmission(accepted=True, driver_goal_id="driver-goal-1")

        def cancel(self, action):
            cancellations.append((action["action_id"], action["attempt_id"]))
            return True

    store = ActionStore(tmp_path / "actions.sqlite3")
    stop = LocalStopController(store.path, workcell_id=grant.workcell_id, instance_id=grant.instance_id)

    def current(epoch, generation):
        return (epoch, generation) == (2, 8)

    stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
               fleet_fence_current=current)
    runner = ActionRunner(
        store, Driver(), workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={1001},
        current_fence=current, capability_current=lambda request: True,
        submission_fence=stop, enabled=True,
    )
    api = ActionApi(runner)

    class LocalTransport(UnixLocalActionTransport):
        def _exchange(self, instance_id, request):
            # Only the socket is replaced. Both wire producer and consumer are real.
            return json.loads(json.dumps(api.dispatch(json.loads(json.dumps(request)), peer_uid=1001)))

    return LocalTransport(tmp_path), grant, runner, submissions, cancellations


def test_submit_queries_and_cancel_share_one_action_attempt(exchange):
    transport, grant, runner, submissions, cancellations = exchange
    accepted = transport.submit(grant)
    duplicate = transport.submit(grant)
    reads = [transport.get(grant), transport.get(grant)]
    canceled = transport.cancel(grant, reason="operator request")
    for receipt in [accepted, duplicate, *reads, canceled]:
        assert (receipt.action_id, receipt.attempt_id) == (grant.action_id, grant.attempt_id)
    assert submissions == [(grant.action_id, grant.attempt_id)]
    assert cancellations == [(grant.action_id, grant.attempt_id)]
    assert canceled.state.value == "CANCEL_REQUESTED"  # Cancel ACK is not physical stop.
    assert reads[0].journal_event_id == reads[1].journal_event_id


@pytest.mark.parametrize("field,value", [
    ("attempt_id", "attempt-other"), ("mission_id", "mission-other"),
    ("step_id", "step-other"), ("dispatch_generation", 9),
    ("authority_epoch", 3), ("request_digest", "c" * 64),
])
def test_action_lookup_rejects_receipt_for_a_different_expected_scope(exchange, field, value):
    transport, grant, _, submissions, _ = exchange
    transport.submit(grant)
    different = FleetActionGrant.model_validate({**grant.model_dump(), field: value})
    with pytest.raises(LocalActionUnavailable, match="does not match"):
        transport.get(different)
    assert submissions == [(grant.action_id, grant.attempt_id)]


def test_terminal_readback_keeps_action_identity(exchange):
    transport, grant, runner, submissions, _ = exchange
    transport.submit(grant)
    runner.record_terminal(
        grant.action_id, grant.attempt_id, driver_goal_id="driver-goal-1", outcome="SUCCEEDED",
        result_source="fake-driver", result_observed_at=datetime.now(timezone.utc).isoformat(),
        result={}, peer_uid=1001,
    )
    receipt = transport.get(grant)
    assert receipt.state.value == "SUCCEEDED"
    assert receipt.action_id == grant.action_id
    assert submissions == [(grant.action_id, grant.attempt_id)]
