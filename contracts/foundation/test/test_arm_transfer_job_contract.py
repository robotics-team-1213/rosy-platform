"""D-856 closed physical job HTTP shapes expose execution facts, not business completion."""
from importlib import import_module
import json
from pathlib import Path

import pytest


def api():
    try:
        return import_module("core_common.protocol.arm_transfer_jobs")
    except ModuleNotFoundError:
        pytest.fail("neutral ARM job wire contract is missing")


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/arm_transfer_job_v1.json").read_text())


def test_canonical_exports_and_frozen_json_round_trip():
    module = api()
    schemas = import_module("core_common.protocol.schemas")
    for name in ("ArmTransferRequest", "ArmTransferJobCreate", "ArmTransferJobAdmit",
                 "ArmTransferJobSnapshot", "ArmTransferJobResponse"):
        assert getattr(schemas, name) is getattr(module, name)
    data = fixture()
    request = module.ArmTransferJobCreate.model_validate(data["create"])
    assert request.model_dump(mode="json") == data["create"]
    response = module.ArmTransferJobResponse(job=data["proposed"])
    assert response.model_dump(mode="json") == {"job": data["proposed"]}
    assert module.ArmTransferJobAdmit.model_validate(data["admit"]).model_dump() == data["admit"]
    with pytest.raises(ValueError):
        request.target = "changed"


@pytest.mark.parametrize("changes", [
    {"resources": []}, {"capabilities": []}, {"claim_released": True}, {"satisfied": True},
    {"owner_journal_id": "caller-selected"}, {"grant": {}}, {"recipe": {}}, {"workflow": "UNLOAD"},
    {"request_key": " bad "}, {"source": "target"}, {"object_ref": True}, {"request_key": ""},
])
def test_request_cannot_install_authority_or_application_process_fields(changes):
    with pytest.raises(ValueError):
        api().ArmTransferJobCreate.model_validate({**fixture()["create"], **changes})


@pytest.mark.parametrize("changes", [{"expected_generation": True}, {"expected_generation": -1},
    {"expected_proposal_digest": "unknown"}, {"resources": []}, {"approved_by": "operator"}])
def test_admission_body_only_names_exact_snapshot_and_generation(changes):
    with pytest.raises(ValueError):
        api().ArmTransferJobAdmit.model_validate({**fixture()["admit"], **changes})


def test_snapshot_preserves_two_person_approval_and_nullable_fence_pair():
    data = fixture()["proposed"]
    snapshot = api().ArmTransferJobSnapshot
    assert snapshot(**{**data, "status": "READY", "approved_by": "operator",
                       "authority_epoch": 2, "dispatch_generation": 3}).status == "READY"
    for changes in ({"status": "READY"}, {"approved_by": "operator"},
                    {"authority_epoch": 1}, {"dispatch_generation": True},
                    {"status": "READY", "approved_by": "harbor", "authority_epoch": 2, "dispatch_generation": 3},
                    {"status": "BUSINESS_COMPLETED"}, {"satisfied": True}):
        with pytest.raises(ValueError):
            snapshot(**{**data, **changes})


def test_existing_task_status_export_keeps_its_single_enum_owner():
    try:
        leaf = import_module("core_common.protocol.task_state")
    except ModuleNotFoundError:
        pytest.fail("task-state enum has not been separated from the budgeted facade")
    schemas = import_module("core_common.protocol.schemas")
    assert schemas.FleetTaskStatus is leaf.FleetTaskStatus
    assert [item.value for item in leaf.FleetTaskStatus] == [
        "REQUESTED", "QUEUED", "ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "UNKNOWN", "HOLD", "CANCELED", "EXPIRED"]
