"""D-403 §2 / D-336: typed CELL_TRANSFER v2 frames between the real Fleet producer and OMX consumer.

Only the socket is replaced; the Fleet UDS client and the OMX ActionApi/ActionRunner are real.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core_common.protocol.schemas import FleetActionGrant, FleetCellTransferGrant
from fleet.server.local_action_transport import (
    LocalActionRejected, LocalActionUnavailable, UnixLocalActionTransport,
)

OMX_ROOT = Path(__file__).resolve().parents[1] / "src/products/omx/adapter"


def _cell_grant_document(now):
    return {
        "mission_id": "cell-mission-1", "step_id": "cell-mission-1:step-1",
        "action_id": "cell-action-1", "attempt_id": "cell-attempt-1",
        "request_digest": "0" * 64, "workcell_id": "omx-1",
        "instance_id": "omx-1-control", "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": "a" * 64, "cell_sha256": "b" * 64,
            "step_index": 0, "item": "box", "pallet": "pallet-1", "layer": 0,
            "frame": "robot_base",
            "home": {"x": 0.1, "y": 0.0, "z": 0.2, "yaw": 0.0},
            "pick": {"x": 0.2, "y": 0.0, "z": 0.04, "yaw": 0.0},
            "place": {"x": 0.3, "y": 0.0, "z": 0.04, "yaw": 0.0},
            "pick_approach_z": 0.12, "place_approach_z": 0.12, "carry_z": 0.18,
        },
        "capability_revision": "cell-transfer-v1", "config_revision": "cfg-1",
        "authority_epoch": 2, "dispatch_generation": 8,
        "issued_at": now, "expires_at": now + timedelta(minutes=5),
    }


@pytest.fixture
def cell_exchange(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(OMX_ROOT))
    from omx_adapter.action_api import ActionApi, action_grant_digest
    from omx_adapter.action_runner import ActionRunner
    from omx_adapter.action_store import ActionStore
    from omx_adapter.local_stop import LocalStopController

    document = _cell_grant_document(datetime.now(timezone.utc))
    document["request_digest"] = action_grant_digest(document)
    grant = FleetCellTransferGrant.model_validate(document)
    seen, frames = [], []

    class Phases:
        def __init__(self, recorder):
            self.recorder = recorder
            self.active_phase_id = None

        def start(self):
            self.active_phase_id = "approach"
            self.recorder.begin_phase(phase_id="approach", ordinal=0, command_digest="a" * 64)
            self.recorder.record_first_submission(
                phase_id="approach", accepted=True, driver_goal_id="ros-goal-approach")

        def cancel_current(self):
            self.recorder.request_cancel(phase_id=self.active_phase_id)
            return {"phase_id": self.active_phase_id, "state": "CANCEL_REQUESTED"}

    class NoDirectDriver:
        def submit(self, request):
            raise AssertionError("CELL_TRANSFER must never reach the direct driver path")

        def cancel(self, action):
            raise AssertionError("CELL_TRANSFER cancel goes to the exact phase goal")

    store = ActionStore(tmp_path / "actions.sqlite3")
    stop = LocalStopController(store.path, workcell_id="omx-1", instance_id="omx-1-control")

    def current(epoch, generation):
        return (epoch, generation) == (2, 8)

    stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
               fleet_fence_current=current)
    runner = ActionRunner(
        store, NoDirectDriver(), workcell_id="omx-1", instance_id="omx-1-control",
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={1001},
        current_fence=current, capability_current=lambda request: True,
        submission_fence=stop, enabled=True,
        phase_runner_factories={"CELL_TRANSFER": lambda received, recorder: (
            seen.append(received) or Phases(recorder))},
    )
    api = ActionApi(runner)

    class LocalTransport(UnixLocalActionTransport):
        def _exchange(self, instance_id, request):
            wire = json.loads(json.dumps(request))
            frames.append(wire)
            return json.loads(json.dumps(api.dispatch(wire, peer_uid=1001)))

    return LocalTransport(tmp_path), grant, api, seen, frames, store


def test_typed_cell_transfer_submit_is_a_v2_frame_parsed_as_the_cell_grant(cell_exchange):
    transport, grant, _, seen, frames, store = cell_exchange

    receipt = transport.submit(grant)

    assert frames[0]["version"] == 2
    assert frames[0]["grant"]["action_kind"] == "CELL_TRANSFER"
    assert frames[0]["grant"]["cell_transfer"]["cell_sha256"] == "b" * 64
    assert "source_evidence" not in frames[0]["grant"]
    assert len(seen) == 1 and isinstance(seen[0], FleetCellTransferGrant)
    assert seen[0] == grant
    assert receipt.state.value == "ACCEPTED"
    assert [phase.phase_id for phase in receipt.phase_summaries] == ["approach"]
    assert store.get_action(grant.action_id)["action_kind"] == "CELL_TRANSFER"


def test_cell_transfer_get_and_cancel_use_v2_and_keep_the_attempt(cell_exchange):
    transport, grant, _, _, frames, _ = cell_exchange
    transport.submit(grant)

    read = transport.get(grant)
    canceled = transport.cancel(grant, reason="operator stop")

    assert [frame["version"] for frame in frames] == [2, 2, 2]
    assert (read.action_id, read.attempt_id) == (grant.action_id, grant.attempt_id)
    assert read.phase_summaries is not None
    assert (canceled.action_id, canceled.attempt_id) == (grant.action_id, grant.attempt_id)
    assert canceled.phase_summaries[0].state == "CANCEL_REQUESTED"


def test_omx_consumer_rejects_a_v1_cell_transfer_frame_before_journaling(cell_exchange):
    _, grant, api, seen, _, store = cell_exchange

    response = api.dispatch({"version": 1, "operation": "SubmitAction",
                             "grant": grant.model_dump(mode="json")}, peer_uid=1001)

    assert response["status"] == 400
    assert response["version"] == 1
    assert response["error"]["code"] == "UNSUPPORTED_VERSION"
    assert seen == [] and store.get_action(grant.action_id) is None


def test_v1_reply_to_a_cell_transfer_is_not_trusted(cell_exchange):
    transport, grant, _, _, _, _ = cell_exchange
    receipt = transport.submit(grant).model_dump(mode="json")
    with pytest.raises(LocalActionUnavailable, match="version"):
        transport._parse_receipt(grant, {"version": 1, "status": 200, "receipt": receipt})


def test_explicit_cell_rejection_is_a_4xx_rejection(cell_exchange):
    transport, grant, _, seen, _, _ = cell_exchange
    stale = grant.model_dump(mode="json")
    stale["dispatch_generation"] = 9
    from omx_adapter.action_api import action_grant_digest
    stale["request_digest"] = action_grant_digest(stale)
    with pytest.raises(LocalActionRejected, match="GRANT_REJECTED"):
        transport.submit(FleetCellTransferGrant.model_validate(stale))
    assert seen == []


def test_unknown_kind_is_refused_before_any_frame(tmp_path):
    transport = UnixLocalActionTransport(tmp_path)
    now = datetime.now(timezone.utc)
    source = {
        "object_id": "block-1", "observation_id": "obs-1", "frame_sha256": "b" * 64,
        "camera_identity": "cam-1", "optical_frame_id": "cam_optical",
        "calibration_revision": "cal-1", "transform_revision": "tf-1",
        "capture_time_ns": 1, "selector_kind": "point", "image_bbox_xyxy": [1, 2, 3, 4],
    }
    pick_place = FleetActionGrant.model_validate({
        "mission_id": "m", "step_id": "s", "action_id": "a", "attempt_id": "t",
        "request_digest": "0" * 64, "workcell_id": "omx-1", "instance_id": "omx-1-control",
        "action_kind": "PICK_PLACE", "source_evidence": source,
        "destination_evidence": {**source, "object_id": "tray-1"},
        "capability_revision": "c", "config_revision": "c", "observation_revision": "o",
        "authority_epoch": 0, "dispatch_generation": 0,
        "issued_at": now, "expires_at": now + timedelta(seconds=5),
    })
    unknown = pick_place.model_copy(update={"action_kind": "PICK"})
    with pytest.raises(ValueError, match="action kind"):
        transport.submit(unknown)


def test_owner_reports_its_simulation_identity_over_uds(tmp_path, monkeypatch):
    """C4b 1b C3 (D-390 §5): Fleet reads the owner's own identity before opening dispatch."""
    monkeypatch.syspath_prepend(str(OMX_ROOT))
    from omx_adapter.action_api import ActionApi

    identity = {"workcell_id": "omx-1", "instance_id": "omx-1-control", "simulation": True,
                "profile": "omx-cell-sim"}
    apis = {"sim": ActionApi(object(), identity=identity), "plain": ActionApi(object())}

    class LocalTransport(UnixLocalActionTransport):
        def __init__(self, api):
            super().__init__(tmp_path)
            self.api = api

        def _exchange(self, instance_id, request):
            return json.loads(json.dumps(self.api.dispatch(json.loads(json.dumps(request)), peer_uid=1001)))

    assert LocalTransport(apis["sim"]).owner_identity("omx-1-control") == identity
    with pytest.raises(LocalActionRejected, match="UNKNOWN_OPERATION"):
        LocalTransport(apis["plain"]).owner_identity("omx-1-control")
