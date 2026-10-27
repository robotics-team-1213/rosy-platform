from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path

import pytest

NAMES = ("ArmTransferRecoveryCreate", "ArmTransferRecoveryApprove", "ArmTransferRecoveryRequestSnapshot",
    "ArmTransferRecoveryRequestResponse", "ArmTransferRecoveryPreview", "ArmTransferRecoveryPreviewResponse",
    "ArmTransferRecoveryOwnerContext", "ArmTransferRecoveryEvidenceContext", "ArmTransferRecoveryContext",
    "ArmTransferRecoveryContextResponse", "ArmTransferRecoveryObservationRequest",
    "ArmTransferRecoveryObservationReply", "ArmTransferExecutionReview")
DIGEST = "a" * 64


def api():
    try:
        return import_module("core_common.protocol.arm_transfer_recovery")
    except ModuleNotFoundError:
        pytest.fail("shared recovery wire contract is missing")


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/arm_transfer_observation_v1.json").read_text())


def preview():
    return dict(parent_mission_id="parent", recovery_limit=1, child_mission_id=None, status="AVAILABLE",
        context_digest=DIGEST, request_id=None, proposal_digest=None, evidence_digest=None,
        proposed_by=None, expected_generation=2, can_request=True, can_approve=False, reason=None,
        execution_authorized=False, execution_review=None)


def capture():
    old = fixture()["context"]
    keys = ("producer_id", "evaluator_revision", "frame_id", "policy_digest", "catalog_digest",
            "bindings_digest", "object_ref", "object_origin_id", "min_separation_ns", "max_age_ns")
    owner_keys = ("workcell_id", "instance_id", "journal_id", "owner_session_id")
    return dict(mission_id=old["mission_id"], request_id="recovery-one", proposal_digest=DIGEST,
        purpose="RECOVERY_RESET", execution_authorized=False,
        context={**{k: old[k] for k in ("action_id", "attempt_id", "phase", "not_before_ns")},
                 "owners": [{k: owner[k] for k in owner_keys} for owner in old["owners"]]},
        **{k: old[k] for k in keys})


def test_canonical_exports_and_json_round_trips():
    module = api()
    facade = import_module("core_common.protocol.schemas")
    assert all(getattr(facade, name) is getattr(module, name) for name in NAMES)
    raw = capture()
    model = module.ArmTransferRecoveryContext.model_validate(raw)
    assert model.model_dump(mode="json") == raw
    assert module.ArmTransferRecoveryContextResponse(context=None).model_dump() == {"context": None}
    with pytest.raises(ValueError):
        model.execution_authorized = True
    snapshot = dict(request_id="recovery-one", request_key="request-one", proposal_digest=DIGEST,
                    context_digest=DIGEST, proposed_by="proposer", requested_at_ns=1)
    assert module.ArmTransferRecoveryRequestResponse(request=snapshot).model_dump(mode="json") == {"request": snapshot}
    assert module.ArmTransferRecoveryPreviewResponse(recovery=preview()).recovery.can_request
    assert module.ArmTransferRecoveryObservationReply(evidence_digest=DIGEST).evidence_digest == DIGEST


@pytest.mark.parametrize("changes", [dict(proposed_by="forged"), dict(request_key=" padded "),
    dict(expected_context_digest="bad"), dict(request_key="x" * 161)])
def test_create_is_closed_and_cannot_choose_an_actor(changes):
    model = api().ArmTransferRecoveryCreate
    raw = dict(request_key="request-one", expected_context_digest=DIGEST)
    assert model(**raw).request_key == "request-one"
    with pytest.raises(ValueError):
        model(**{**raw, **changes})


@pytest.mark.parametrize("changes", [dict(approved_by="forged"), dict(expected_generation=True),
    dict(expected_generation=-1), dict(expected_evidence_digest="bad"), dict(execution_authorized=True)])
def test_approval_binds_exact_proposal_proof_and_generation(changes):
    model = api().ArmTransferRecoveryApprove
    raw = dict(expected_proposal_digest=DIGEST, expected_evidence_digest=DIGEST, expected_generation=2)
    assert model(**raw).expected_generation == 2
    with pytest.raises(ValueError):
        model(**{**raw, **changes})


@pytest.mark.parametrize("change", ["purpose", "missing-purpose", "one", "three", "authority"])
def test_observations_require_recovery_purpose_and_exactly_two_closed_facts(change):
    model = api().ArmTransferRecoveryObservationRequest
    raw = dict(purpose="RECOVERY_RESET", expected_proposal_digest=DIGEST,
               observations=fixture()["request"]["observations"])
    assert model(**raw).model_dump(mode="json") == raw
    if change == "purpose": raw["purpose"] = "POST_ACTION"
    if change == "missing-purpose": del raw["purpose"]
    if change == "one": raw["observations"].pop()
    if change == "three": raw["observations"].append(deepcopy(raw["observations"][0]))
    if change == "authority": raw["observations"][0]["execution_authorized"] = True
    with pytest.raises(ValueError):
        model(**raw)


@pytest.mark.parametrize("change", ["extra-owner", "duplicate-owner", "phase", "truth", "authority"])
def test_capture_has_only_supported_owner_scope_and_no_truth_or_authority(change):
    raw = capture()
    if change == "extra-owner": raw["context"]["owners"][0]["model_digest"] = DIGEST
    if change == "duplicate-owner": raw["context"]["owners"].append(deepcopy(raw["context"]["owners"][0]))
    if change == "phase": raw["context"]["phase"] = "POST_ACTION"
    if change == "truth": raw["expected_object_pose"] = [0, 0, 0]
    if change == "authority": raw["execution_authorized"] = True
    with pytest.raises(ValueError):
        api().ArmTransferRecoveryContext.model_validate(raw)


@pytest.mark.parametrize("changes", [dict(status="RECOVERED"), dict(recovery_limit=True),
    dict(recovery_limit=2), dict(can_approve=True), dict(status="READY_FOR_APPROVAL"),
    dict(status="CHILD_CREATED"), dict(child_mission_id="child"), dict(execution_authorized=True)])
def test_preview_cannot_claim_success_or_approval_without_bound_facts(changes):
    with pytest.raises(ValueError):
        api().ArmTransferRecoveryPreview.model_validate({**preview(), **changes})


def test_ready_and_child_created_are_separate_from_physical_success():
    model = api().ArmTransferRecoveryPreview
    ready = {**preview(), "status": "READY_FOR_APPROVAL", "request_id": "recovery-one",
             "proposal_digest": DIGEST, "evidence_digest": DIGEST, "proposed_by": "proposer", "can_approve": True}
    assert model(**ready).can_approve
    child = {**preview(), "status": "CHILD_CREATED", "child_mission_id": "child", "can_request": False}
    assert not model(**child).execution_authorized
    for change in (dict(can_request=True), dict(can_approve=True), dict(child_mission_id="parent")):
        with pytest.raises(ValueError):
            model(**{**child, **change})


def test_review_preserves_owner_reason_but_cannot_invent_physical_cause():
    model = api().ArmTransferExecutionReview
    raw = dict(scope="owner_reported_execution_only", action_outcome="FAILED", owner_reason="",
        phase_summaries=[], failure_phase=None, last_reported_phase=None,
        task_outcome="unknown", physical_failure_cause=None)
    assert model.model_validate_json(json.dumps(raw)).model_dump(mode="json") == raw
    assert model.model_validate_json(json.dumps({**raw, "owner_reason": "x" * 256})).owner_reason
    for change in (dict(physical_failure_cause="dropped"), dict(execution_authorized=True),
                   dict(owner_reason="x" * 257), dict(action_outcome="PHYSICAL_SUCCESS")):
        with pytest.raises(ValueError):
            model.model_validate_json(json.dumps({**raw, **change}))
