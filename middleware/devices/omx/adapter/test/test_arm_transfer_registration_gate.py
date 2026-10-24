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
        owner_journal_id="journal-1", owner_session_id="session-1",
        request_digest="0" * 64, workcell_id="w-1", instance_id="arm-1",
        action_kind="ARM_TRANSFER", arm_transfer=dict(
            object_ref="o-1", source="p-1", target="p-2", catalog_digest="a" * 64,
            bindings_digest="b" * 64, resource_policy_digest="c" * 64),
        capability_revision="cap-1", config_revision="cfg-1", authority_epoch=1,
        dispatch_generation=1, issued_at=now, expires_at=now + timedelta(seconds=30))


@pytest.mark.parametrize("as_json", [False, True])
def test_parsing_a_model_does_not_install_an_owner_executor(tmp_path, as_json):
    from test_omx_action_api import _runner

    value = grant()
    parsed = parse_action_grant(value.model_dump(mode="json") if as_json else value)
    store, driver, runner = _runner(tmp_path)
    with pytest.raises(PermissionError, match="no admitted executor"):
        runner.submit(parsed, peer_uid=1001)
    assert store.get_action(value.action_id) is None and not driver.submissions
    assert value.action_kind in PHASE_RUNNER_KINDS
    assert value.action_kind not in DIRECT_DRIVER_KINDS


@pytest.mark.parametrize("version", [1, 2])
def test_uninstalled_owner_ipc_refuses_before_journal_or_driver(tmp_path, version):
    from test_omx_action_api import _runner

    store, driver, runner = _runner(tmp_path)
    value = grant()
    reply = ActionApi(runner).dispatch(dict(
        version=version, operation="SubmitAction", grant=value.model_dump(mode="json")), peer_uid=1001)
    assert reply["status"] == (400 if version == 1 else 403)
    assert store.get_action(value.action_id) is None and not driver.submissions
