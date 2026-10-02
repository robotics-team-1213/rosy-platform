"""Platform contracts preserve evidence, process revisions and D-18 identities."""

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sys

import pytest
from core_common.protocol.schemas import (
    DeviceActionReceipt,
    DeviceActionState,
    FleetActionGrant,
    ResolvedTargetEvidence,
)
from rosy.execution.api import AttemptIdentity, GrantBinding, PlanBundle, PlanStep, ReceiptBinding
from rosy.skills.api import SkillContract, SkillInvocation
from rosy.world.api import ObservationSnapshot, SnapshotValidity

ROOT = Path(__file__).resolve().parents[1]
CELL_ROOT = ROOT / "src" / "site" / "cell"
if str(CELL_ROOT) not in sys.path:
    sys.path.insert(0, str(CELL_ROOT))
OMX_ADAPTER_ROOT = ROOT / "src" / "products" / "omx" / "adapter"
if str(OMX_ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(OMX_ADAPTER_ROOT))

from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from rosy_cell.compiler import Job, Step  # noqa: E402


def test_platform_api_packages_have_declared_build_metadata():
    package_files = (
        ROOT / "modules/world/pyproject.toml",
        ROOT / "modules/skills/api/pyproject.toml",
        ROOT / "modules/execution/pyproject.toml",
    )
    assert all(path.is_file() for path in package_files)


def _evidence(object_id: str) -> ResolvedTargetEvidence:
    return ResolvedTargetEvidence(
        object_id=object_id,
        observation_id="camera-observation-17",
        frame_sha256="a" * 64,
        camera_identity="overhead-camera",
        optical_frame_id="camera_optical_frame",
        calibration_revision="cal-12",
        transform_revision="tf-34",
        capture_time_ns=1_700_000_000_000_000_123,
        selector_kind="object_id",
        image_bbox_xyxy=(10, 20, 30, 50),
    )


def test_observation_snapshot_preserves_wire_evidence_units_and_provenance():
    wire = _evidence("box-1")
    received = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    snapshot = ObservationSnapshot(
        snapshot_id=wire.observation_id,
        source=wire.camera_identity,
        captured_at_ns=wire.capture_time_ns,
        received_at=received,
        frame_id=wire.optical_frame_id,
        calibration_revision=wire.calibration_revision,
        transform_revision=wire.transform_revision,
        evidence_refs=(wire.frame_sha256, wire.object_id),
        validity=SnapshotValidity.UNKNOWN,
    )
    assert snapshot.captured_at_ns == wire.capture_time_ns
    assert snapshot.received_at == received
    assert snapshot.frame_id == wire.optical_frame_id
    assert snapshot.calibration_revision == wire.calibration_revision
    assert snapshot.transform_revision == wire.transform_revision
    assert snapshot.evidence_refs == (wire.frame_sha256, wire.object_id)
    assert snapshot.validity is SnapshotValidity.UNKNOWN


def test_observation_snapshot_rejects_missing_or_ambiguous_evidence():
    with pytest.raises(ValueError, match="nanosecond"):
        ObservationSnapshot("snap", "camera", True, datetime.now(timezone.utc), "frame", "cal", ("ref",),
                            SnapshotValidity.UNKNOWN)
    with pytest.raises(ValueError, match="timezone"):
        ObservationSnapshot("snap", "camera", 1, datetime(2026, 10, 2), "frame", "cal", ("ref",),
                            SnapshotValidity.UNKNOWN)
    with pytest.raises(ValueError, match="unique"):
        ObservationSnapshot("snap", "camera", 1, datetime.now(timezone.utc), "frame", "cal", ("ref", "ref"),
                            SnapshotValidity.UNKNOWN)


def _skill_contract() -> SkillContract:
    return SkillContract(
        skill_id="pallet.transfer",
        version="1.0.0",
        input_schema_id="rosy.pallet.transfer-input.v1",
        preconditions=("owner-ready", "fresh-joint-state"),
        completion_conditions=("gripper-evidence", "target-observed"),
        resources=("omx-arm",),
        cancellation_contract="rosy.action-cancel.v1",
        result_evidence=("action-receipt", "goal-observation"),
    )


def test_skill_contract_records_lifecycle_and_freezes_invocation_inputs():
    contract = _skill_contract()
    nested = {"target": {"frame_id": "robot_base", "xyz_m": [0.1, 0.2, 0.3]}}
    invocation = SkillInvocation("pallet.transfer", "1.0.0", nested)
    contract.validate_invocation(invocation)
    nested["target"]["xyz_m"][0] = 9.0
    assert invocation.inputs["target"]["xyz_m"] == (0.1, 0.2, 0.3)
    with pytest.raises(TypeError):
        invocation.inputs["target"]["frame_id"] = "map"
    with pytest.raises(ValueError, match="ID/version"):
        contract.validate_invocation(SkillInvocation("pallet.transfer", "2.0.0", {}))
    with pytest.raises(ValueError, match="finite"):
        SkillInvocation("pallet.transfer", "1.0.0", {"distance_m": float("nan")})


def test_plan_bundle_binds_job_hashes_and_order_without_authority_fields():
    recipe_digest = sha256(b"recipe").hexdigest()
    cell_digest = sha256(b"cell").hexdigest()
    job = Job(
        recipe_hash=recipe_digest,
        cell_hash=cell_digest,
        carry_z=0.42,
        steps=(Step("pallet_done", "", "pallet-1", None, None, None),),
    )
    invocation = SkillInvocation("pallet.transfer", "1.0.0", {"item": "box-1"})
    steps = (PlanStep(0, invocation),)
    plan = PlanBundle.from_job(
        job,
        process_artifact_digest=sha256(b"compiler").hexdigest(),
        recipe_digest=recipe_digest,
        cell_digest=cell_digest,
        steps=steps,
        verification_refs=("cell-profile:7",),
    )
    assert plan.recipe_digest == job.recipe_hash
    assert plan.cell_digest == job.cell_hash
    assert plan.steps == steps
    assert not {"principal", "approval", "authority_epoch", "grant"} & set(plan.__dataclass_fields__)
    with pytest.raises(ValueError, match="does not match"):
        PlanBundle.from_job(
            job,
            process_artifact_digest=sha256(b"compiler").hexdigest(),
            recipe_digest="0" * 64,
            cell_digest=cell_digest,
            steps=steps,
        )
    with pytest.raises(ValueError, match="does not match"):
        PlanBundle.from_job(
            job,
            process_artifact_digest=sha256(b"compiler").hexdigest(),
            recipe_digest=recipe_digest,
            cell_digest="0" * 64,
            steps=steps,
        )
    with pytest.raises(ValueError, match="unsupported"):
        PlanBundle(sha256(b"compiler").hexdigest(), recipe_digest, cell_digest, steps,
                   schema_version="rosy.plan.v2")
    with pytest.raises(ValueError, match="contiguous"):
        PlanBundle(sha256(b"compiler").hexdigest(), recipe_digest, cell_digest,
                   (PlanStep(1, invocation),))


def _wire_grant() -> FleetActionGrant:
    common = dict(
        observation_id="observation-1",
        frame_sha256="b" * 64,
        camera_identity="camera-1",
        optical_frame_id="camera_optical",
        calibration_revision="cal-1",
        transform_revision="tf-1",
        capture_time_ns=1_700_000_000_000_000_001,
        selector_kind="object_id",
        image_bbox_xyxy=(1, 2, 3, 4),
    )
    return FleetActionGrant(
        mission_id="mission-1",
        step_id="step-1",
        action_id="action-1",
        attempt_id="attempt-1",
        request_digest="c" * 64,
        workcell_id="cell-1",
        instance_id="omx-1",
        action_kind="PICK_PLACE",
        source_evidence=ResolvedTargetEvidence(object_id="object-1", **common),
        destination_evidence=ResolvedTargetEvidence(object_id="object-2", **common),
        capability_revision="cap-2",
        config_revision="config-3",
        observation_revision="obs-4",
        authority_epoch=5,
        dispatch_generation=6,
        issued_at=datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 10, 2, 1, 1, tzinfo=timezone.utc),
    )


def test_grant_and_receipt_mapping_preserves_identity_revision_and_request_digest():
    unsigned = _wire_grant()
    grant = unsigned.model_copy(update={"request_digest": action_grant_digest(unsigned)})
    grant_binding = GrantBinding.from_wire(grant)
    receipt = DeviceActionReceipt(
        mission_id=grant.mission_id,
        step_id=grant.step_id,
        action_id=grant.action_id,
        attempt_id=grant.attempt_id,
        workcell_id=grant.workcell_id,
        instance_id=grant.instance_id,
        request_digest=grant.request_digest,
        authority_epoch=grant.authority_epoch,
        dispatch_generation=grant.dispatch_generation,
        state=DeviceActionState.PREPARED,
        journal_event_id=1,
        observed_at=datetime(2026, 10, 2, 1, 0, 1, tzinfo=timezone.utc),
    )
    receipt_binding = ReceiptBinding.from_wire(receipt)
    assert grant_binding.identity == receipt_binding.identity
    assert grant_binding.identity.request_digest == grant.request_digest
    assert grant_binding.identity.authority_epoch == grant.authority_epoch
    assert grant_binding.identity.dispatch_generation == grant.dispatch_generation
    assert (grant_binding.capability_revision, grant_binding.config_revision,
            grant_binding.observation_revision) == ("cap-2", "config-3", "obs-4")
    assert receipt_binding.state == "PREPARED"
    assert receipt_binding.journal_event_id == receipt.journal_event_id
    assert grant_binding.identity.request_digest == action_grant_digest(grant)
    tampered = grant.model_copy(update={"authority_epoch": grant.authority_epoch + 1})
    assert action_grant_digest(tampered) != tampered.request_digest
    with pytest.raises(ValueError, match="only the existing"):
        replace(grant_binding, action_kind="CELL_TRANSFER")


def test_attempt_identity_rejects_changed_or_malformed_digest_and_ids():
    common = dict(
        mission_id="mission-1", step_id="step-1", action_id="action-1", attempt_id="attempt-1",
        workcell_id="cell-1", instance_id="omx-1", request_digest="d" * 64,
        authority_epoch=0, dispatch_generation=0,
    )
    assert AttemptIdentity(**common).request_digest == "d" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        AttemptIdentity(**{**common, "request_digest": "D" * 64})
    with pytest.raises(ValueError, match="distinct"):
        AttemptIdentity(**{**common, "attempt_id": "action-1"})
