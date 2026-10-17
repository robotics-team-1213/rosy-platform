"""D-779 §7 / D-780: optional pair and barrier fields on the CELL_TRANSFER grant."""

from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from pydantic import ValidationError

from core_common.protocol import cell_transfer
from core_common.protocol.schemas import (
    CellTransferPayload,
    FleetCellTransferGrant,
    LocalStopSnapshot,
    StopRequestSource,
)
from core_common.protocol.workcell_barrier import (
    BarrierQuery,
    BarrierReleaseRequest,
    BarrierState,
    CoordinatorStopReason,
)

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
POSE = {"x": 0.1, "y": 0.2, "z": 0.3, "yaw": 0.0}


def _grant(**overrides):
    value = {
        "mission_id": "mission-cell-01", "step_id": "step-cell-01", "action_id": "action-cell-01",
        "attempt_id": "attempt-cell-01", "request_digest": "c" * 64, "workcell_id": "omx-cell-01",
        "instance_id": "omx-left", "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": "job-cell-01", "recipe_sha256": "a" * 64, "cell_sha256": "b" * 64,
            "step_index": 0, "item": "box", "pallet": "pallet-01", "layer": 0, "frame": "robot_base",
            "home": POSE, "pick": POSE, "place": {**POSE, "x": 0.4},
            "pick_approach_z": 0.5, "place_approach_z": 0.5, "carry_z": 0.6,
        },
        "capability_revision": "cell-transfer-v1", "config_revision": "omx-config-r4",
        "authority_epoch": 3, "dispatch_generation": 19,
        "issued_at": NOW, "expires_at": NOW + timedelta(seconds=5),
    }
    value.update(overrides)
    return value


def _paired(barriers=None, coupling="tight", **overrides):
    value = _grant(arm_role="left", pair_id="pair-01", partner_instance_id="omx-right",
                   coupling=coupling, **overrides)
    if barriers is not None:
        value["cell_transfer"] = {**value["cell_transfer"], "barriers": barriers}
    return value


BARRIERS = [
    {"barrier_id": "both_ready", "before_first_phase": True, "coupling_after": "loose", "max_wait_s": 5.0},
    {"barrier_id": "both_grasped", "after_phase": "grasp", "coupling_after": "tight", "max_wait_s": 3.0},
]


def _digest(document):
    document = dict(document)
    document.pop("request_digest")
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def test_single_arm_grant_serializes_and_digests_exactly_as_before():
    raw = _grant()
    grant = FleetCellTransferGrant.model_validate(raw)
    dumped = grant.model_dump(mode="json")
    assert set(dumped) == set(raw)
    assert set(dumped["cell_transfer"]) == set(raw["cell_transfer"])
    # The legacy document (no new keys at all) and the parsed model hash identically.
    legacy = json.loads(json.dumps(raw, default=lambda value: value.isoformat()))
    legacy["issued_at"], legacy["expires_at"] = dumped["issued_at"], dumped["expires_at"]
    assert _digest(dumped) == _digest(legacy)
    assert FleetCellTransferGrant.model_validate(dumped) == grant


def test_pair_grant_with_barriers_roundtrips_and_the_digest_covers_the_new_fields():
    grant = FleetCellTransferGrant.model_validate(_paired(BARRIERS))
    dumped = grant.model_dump(mode="json")
    assert (dumped["arm_role"], dumped["pair_id"], dumped["partner_instance_id"], dumped["coupling"]) == (
        "left", "pair-01", "omx-right", "tight")
    assert dumped["cell_transfer"]["barriers"][0] == BARRIERS[0]
    assert "before_first_phase" not in dumped["cell_transfer"]["barriers"][1]
    assert FleetCellTransferGrant.model_validate(dumped) == grant
    assert [barrier.gated_phase for barrier in grant.cell_transfer.barriers] == ["approach", "transfer"]
    loosened = _paired([dict(BARRIERS[0]), {**BARRIERS[1], "max_wait_s": 4.0}])
    assert _digest(FleetCellTransferGrant.model_validate(loosened).model_dump(mode="json")) != _digest(dumped)


@pytest.mark.parametrize("change", [
    {"pair_id": None},
    {"partner_instance_id": None},
    {"partner_instance_id": "omx-left"},
    {"coupling": "loose"},
    {"coupling": None},
    {"arm_role": "Left Arm"},
])
def test_pair_fields_are_checked_together(change):
    raw = _paired(BARRIERS)
    raw.update(change)
    raw = {key: value for key, value in raw.items() if value is not None}
    with pytest.raises(ValidationError):
        FleetCellTransferGrant.model_validate(raw)


def test_coupling_without_pair_and_barriers_without_pair_are_rejected():
    with pytest.raises(ValidationError):
        FleetCellTransferGrant.model_validate(_grant(coupling="independent"))
    raw = _grant()
    raw["cell_transfer"] = {**raw["cell_transfer"], "barriers": BARRIERS}
    with pytest.raises(ValidationError):
        FleetCellTransferGrant.model_validate(raw)


def test_independent_pair_without_barriers_is_valid():
    grant = FleetCellTransferGrant.model_validate(_paired(coupling="independent"))
    assert grant.cell_transfer.barriers is None and grant.cell_transfer.strongest_coupling() == "independent"


@pytest.mark.parametrize("barriers", [
    [],
    [{**BARRIERS[0], "after_phase": "grasp"}],
    [{"barrier_id": "x", "coupling_after": "tight", "max_wait_s": 1.0}],
    [{**BARRIERS[1], "after_phase": "release"}],
    [BARRIERS[1], {**BARRIERS[1], "barrier_id": "other"}],
    [BARRIERS[1], BARRIERS[0]],
    [{**BARRIERS[0], "barrier_id": "both_grasped"}, BARRIERS[1]],
    [{**BARRIERS[0], "max_wait_s": 0}],
    [{**BARRIERS[0], "max_wait_s": cell_transfer.MAX_BARRIER_WAIT_S + 1}],
    [{**BARRIERS[0], "before_first_phase": False}],
])
def test_barrier_lists_are_bounded_ordered_and_unique(barriers):
    with pytest.raises(ValidationError):
        FleetCellTransferGrant.model_validate(_paired(barriers))


def test_schemas_reexports_the_split_models():
    assert CellTransferPayload is cell_transfer.CellTransferPayload
    assert FleetCellTransferGrant is cell_transfer.FleetCellTransferGrant


def test_coordinator_stop_source_and_reason_codes():
    assert StopRequestSource("coordinator") is StopRequestSource.COORDINATOR
    assert {reason.value for reason in CoordinatorStopReason} == {
        "PARTNER_FAILED", "PARTNER_UNKNOWN", "PARTNER_LINK_LOST", "BARRIER_TIMEOUT"}
    snapshot = LocalStopSnapshot(workcell_id="omx-cell-01", instance_id="omx-left", authority_epoch=3,
                                 dispatch_generation=19, state="LOCAL_LATCHED", source="coordinator",
                                 observed_at=NOW, reason="PARTNER_FAILED")
    assert snapshot.model_dump(mode="json")["source"] == "coordinator"
    assert {state.value for state in BarrierState} == {"not_reached", "waiting", "released", "expired"}


def test_barrier_request_bodies_reject_extra_fields_and_untrimmed_ids():
    assert BarrierQuery.model_validate({}).action_id is None
    release = {"action_id": "a-1", "pair_id": "pair-01", "barrier_id": "both_grasped",
               "authority_epoch": 3, "dispatch_generation": 19,
               "partner_arrival": {"instance_id": "omx-right", "action_id": "a-2", "arrived_at": "t"}}
    assert BarrierReleaseRequest.model_validate(release).barrier_id == "both_grasped"
    for bad in ({**release, "extra": 1}, {**release, "pair_id": " pair"}, {**release, "authority_epoch": True}):
        with pytest.raises(ValidationError):
            BarrierReleaseRequest.model_validate(bad)
