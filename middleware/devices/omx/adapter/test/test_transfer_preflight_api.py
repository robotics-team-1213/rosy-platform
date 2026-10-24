"""Peer/scoped read-only owner API; calculation never admits an Action."""
from importlib import import_module
from dataclasses import replace
from types import SimpleNamespace

import pytest

from omx_adapter.action_api import ActionApi
from omx_adapter.command_owner import JointStateSnapshot
from test_transfer_preflight import _catalog, _service
from test_omx_pose_plan import _state, kin, profile  # noqa: F401


def _module(name):
    try:
        return import_module(name)
    except ModuleNotFoundError:
        pytest.fail(f"neutral arm preflight API {name} is missing")


def _request(catalog, **changes):
    return {"version": 2, "operation": "CheckTransfer", "transfer": {
        "workcell_id": catalog.workcell_id, "instance_id": catalog.instance_id,
        "catalog_digest": catalog.digest, "source": "p1", "target": "p2", "geometry": "g1", **changes}}


def _owner_api(kin, profile):
    service = _service(kin, profile)
    api = _module("omx_adapter.transfer_preflight_api").TransferPreflightApi(
        service, allowed_peer_uids={1000}, journal_id="owner-journal-1")
    return ActionApi(object(), transfer_preflight_api=api), service


def test_owner_checks_a_transfer_without_runner_or_journal_side_effects(kin, profile):
    api, service = _owner_api(kin, profile)
    request = _request(service.catalog)
    response = api.dispatch(request, peer_uid=1000)
    assert response["status"] == 200 and response["version"] == 2
    assert response["check"]["request"] == request["transfer"]
    assert response["check"]["journal_id"] == "owner-journal-1"
    assert response["check"]["source_state_sequence"] == 7
    assert response["check"]["simulation"] is True and response["check"]["collision_checked"] is False


def test_peer_and_scope_are_checked_before_measured_state(kin, profile):
    api, service = _owner_api(kin, profile)
    service.execution_state = lambda: pytest.fail("unauthorized/mismatched request read owner state")
    request = _request(service.catalog)
    assert api.dispatch(request, peer_uid=1001)["status"] == 403
    assert api.dispatch({**request, "version": 1}, peer_uid=1000)["status"] == 400
    assert api.dispatch(_request(service.catalog, instance_id="arm-b"), peer_uid=1000)["status"] == 404
    changed = api.dispatch(_request(service.catalog, catalog_digest="0" * 64), peer_uid=1000)
    assert changed["status"] == 409 and changed["error"]["code"] == "ARM_CATALOG_CHANGED"


def test_old_owner_keeps_new_operation_closed():
    api = ActionApi(object())
    assert api.dispatch({"version": 2, "operation": "CheckTransfer", "transfer": {}}, peer_uid=1000)["status"] != 200


def test_missing_owner_state_is_a_read_failure_not_an_execution_or_generic_exception(kin, profile):
    api, service = _owner_api(kin, profile)
    service.execution_state = lambda: None
    response = api.dispatch(_request(service.catalog), peer_uid=1000)
    assert response["status"] == 409
    assert response["error"] == {"code": "ARM_STATE_UNAVAILABLE", "reason": "STATE_INVALID"}


def test_composition_reads_admitted_state_and_preserves_its_calibration(kin, profile):
    catalog = _catalog(kin, profile)
    state = _state(kin, profile)
    measured = JointStateSnapshot(state.joint_positions, state.sequence, state.observed_at_monotonic_s,
                                  state.calibration_revision)
    runtime = SimpleNamespace(owner=SimpleNamespace(joint_state=measured,
        config=SimpleNamespace(workcell_id="arm-cell", instance_id="arm-a")),
        latest_joint_state=SimpleNamespace(sequence=999), monotonic=lambda: 100.01)
    build = _module("omx_adapter.transfer_preflight_owner").build_transfer_preflight_api
    api = build(runtime, catalog=catalog, profile=profile, kinematics=kin,
                transform_revision="tf-sim-1", journal_id="owner-journal-1", allowed_peer_uids={1000})
    assert api.dispatch(_request(catalog), peer_uid=1000)["check"]["source_state_sequence"] == 7
    runtime.owner.joint_state = JointStateSnapshot(measured.positions, 8, 100.0, "different-calibration")
    assert api.dispatch(_request(catalog), peer_uid=1000)["error"]["code"] == "ARM_STATE_UNAVAILABLE"


def test_composition_rejects_a_catalog_for_another_installed_transform(kin, profile):
    catalog = replace(_catalog(kin, profile), transform_revision="uninstalled-transform")
    runtime = SimpleNamespace(owner=SimpleNamespace(joint_state=None,
        config=SimpleNamespace(workcell_id="arm-cell", instance_id="arm-a")), monotonic=lambda: 100.01)
    build = _module("omx_adapter.transfer_preflight_owner").build_transfer_preflight_api
    with pytest.raises(ValueError, match="transform"):
        build(runtime, catalog=catalog, profile=profile, kinematics=kin,
              transform_revision="tf-sim-1", journal_id="owner-journal-1", allowed_peer_uids={1000})
