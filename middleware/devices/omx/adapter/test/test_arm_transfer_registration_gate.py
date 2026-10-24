"""A registered DTO must not accidentally activate an uninstalled execution kind."""
from datetime import datetime, timedelta, timezone

import pytest

from core_common.protocol.schemas import FleetArmTransferGrant
from omx_adapter.action_api import ActionApi
from omx_adapter.action_runner import DIRECT_DRIVER_KINDS, PHASE_RUNNER_KINDS, parse_action_grant


def grant():
    now = datetime.now(timezone.utc)
    return FleetArmTransferGrant(
        mission_id="m-1", step_id="s-1", action_id="a-1", attempt_id="t-1",
        request_digest="0" * 64, workcell_id="w-1", instance_id="arm-1",
        action_kind="ARM_TRANSFER", arm_transfer=dict(
            object_ref="o-1", source="p-1", target="p-2", catalog_digest="a" * 64,
            bindings_digest="b" * 64, resource_policy_digest="c" * 64),
        capability_revision="cap-1", config_revision="cfg-1", authority_epoch=1,
        dispatch_generation=1, issued_at=now, expires_at=now + timedelta(seconds=30))


@pytest.mark.parametrize("as_json", [False, True])
def test_owner_parser_does_not_admit_a_model_without_its_execution_contract(as_json):
    value = grant()
    with pytest.raises(ValueError):
        parse_action_grant(value.model_dump(mode="json") if as_json else value)
    assert value.action_kind not in PHASE_RUNNER_KINDS
    assert value.action_kind not in DIRECT_DRIVER_KINDS


@pytest.mark.parametrize("version", [1, 2])
def test_ipc_submit_refuses_before_journal_or_driver(version):
    class NoSubmitRunner:
        def submit(self, *args, **kwargs):
            raise AssertionError("uninstalled kind reached journal/driver")

    reply = ActionApi(NoSubmitRunner()).dispatch(dict(
        version=version, operation="SubmitAction", grant=grant().model_dump(mode="json")), peer_uid=1000)
    assert reply["status"] == 400
    assert reply["error"]["code"] == "INVALID_REQUEST"
