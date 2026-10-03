"""C4b 1b B5: one grant digest rule on the Fleet side, byte-identical to the OMX owner's."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core_common.protocol.schemas import FleetActionGrant, FleetCellTransferGrant
from fleet.server import cell_job_store
from fleet.server.mission_dispatcher import _grant_digest as pick_place_digest
from fleet.server.step_action_kinds import step_grant_digest

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
SOURCE = {"object_id": "block-1", "observation_id": "obs-1", "frame_sha256": "b" * 64,
          "camera_identity": "cam-1", "optical_frame_id": "cam_optical", "calibration_revision": "cal-1",
          "transform_revision": "tf-1", "capture_time_ns": 1, "selector_kind": "point",
          "image_bbox_xyxy": [1, 2, 3, 4]}
PICK_PLACE = FleetActionGrant.model_validate({
    "mission_id": "m", "step_id": "s", "action_id": "a", "attempt_id": "t", "request_digest": "0" * 64,
    "workcell_id": "omx-1", "instance_id": "omx-1-control", "action_kind": "PICK_PLACE",
    "source_evidence": SOURCE, "destination_evidence": {**SOURCE, "object_id": "tray-1"},
    "capability_revision": "c", "config_revision": "c", "observation_revision": "o",
    "authority_epoch": 0, "dispatch_generation": 0, "issued_at": NOW, "expires_at": NOW + timedelta(seconds=5)})
CELL = FleetCellTransferGrant.model_validate({
    "mission_id": "m", "step_id": "s", "action_id": "a", "attempt_id": "t", "request_digest": "0" * 64,
    "workcell_id": "omx-1", "instance_id": "omx-1-control", "action_kind": "CELL_TRANSFER",
    "cell_transfer": {"job_id": "j", "recipe_sha256": "a" * 64, "cell_sha256": "b" * 64, "step_index": 0,
                      "item": "box", "pallet": "p", "layer": 0, "frame": "robot_base",
                      "home": {"x": 0.1, "y": 0.0, "z": 0.2, "yaw": 0.0},
                      "pick": {"x": 0.2, "y": 0.0, "z": 0.04, "yaw": 0.0},
                      "place": {"x": 0.3, "y": 0.0, "z": 0.04, "yaw": 0.0},
                      "pick_approach_z": 0.12, "place_approach_z": 0.12, "carry_z": 0.18},
    "capability_revision": "c", "config_revision": "c", "authority_epoch": 0, "dispatch_generation": 0,
    "issued_at": NOW, "expires_at": NOW + timedelta(seconds=5)})
# Pinned before 1b: the PICK_PLACE digest a deployed owner already checks must not move.
PICK_PLACE_DIGEST = "0d96bce8d8c0d4cd97daef79d8d3b2bfed1e26e0c8da7de983275558d28dc853"


@pytest.fixture
def owner_digest(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "middleware/apps/device/omx/adapter"))
    from omx_adapter.action_runner import action_grant_digest
    return action_grant_digest


def test_pick_place_digest_is_unchanged_and_matches_the_owner(owner_digest):
    assert step_grant_digest(PICK_PLACE) == pick_place_digest(PICK_PLACE) == owner_digest(PICK_PLACE)
    assert step_grant_digest(PICK_PLACE) == PICK_PLACE_DIGEST


def test_cell_transfer_digest_is_the_owner_rule(owner_digest):
    assert step_grant_digest(CELL) == owner_digest(CELL)
    assert step_grant_digest(CELL.model_dump(mode="json")) == owner_digest(CELL)


def test_the_store_has_no_second_digest_function():
    assert not hasattr(cell_job_store, "cell_transfer_grant_digest")
