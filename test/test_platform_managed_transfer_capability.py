"""Actual registered factory and canonical journal, without ROS/device activation."""
from contextlib import closing
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import time

import pytest

from test_platform_arm_transfer_owner import _setup, kin, profile  # noqa: F401
from omx_adapter.action_api import ActionApi, UnixActionServer
from omx_adapter.journal_identity import journal_identity
from omx_adapter.action_runner import action_grant_digest


FRAME = {"version": 2, "operation": "GetTransferCapability"}


def _api(tmp_path, kin, profile, *, managed=True, install=True):
    grant, store, driver, runner, port, states, installation = _setup(
        tmp_path, kin, profile, managed=managed, install=install)
    identity = dict(workcell_id=grant.workcell_id, instance_id=grant.instance_id,
                    journal_id=journal_identity(store.path), simulation=True)
    return ActionApi(runner, identity=identity), grant, store, port, installation


def test_capability_is_derived_from_registered_factory_and_has_no_action_side_effect(tmp_path, kin, profile):
    api, grant, store, _, installation = _api(tmp_path, kin, profile)
    reply = api.dispatch(FRAME, peer_uid=1001)
    assert reply["status"] == 200, reply
    assert reply["capability"] == dict(action_kind="ARM_TRANSFER", control_mode="fleet_managed",
        workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        journal_id=api.identity["journal_id"], owner_session_id=api.runner.control_admission.owner.session_id,
        catalog_digest=installation.bindings.catalog.digest, bindings_digest=installation.bindings.revision,
        resource_policy_digest=installation.resource_policy_digest,
        capability_revision=installation.capability_revision, config_revision=installation.config_revision)
    assert store.unresolved_actions() == []


@pytest.mark.parametrize("fault", ["unmanaged", "uninstalled", "static-only", "disabled", "port-owner",
                                    "session", "journal", "scope", "admission"])
def test_unproven_or_changed_installation_does_not_advertise_a_capability(tmp_path, kin, profile, fault):
    api, _, store, port, _ = _api(tmp_path, kin, profile, managed=fault != "unmanaged",
                                 install=fault not in {"uninstalled", "static-only"})
    if fault == "static-only":
        api.identity["transfer_capability"] = {"control_mode": "fleet_managed"}
    elif fault == "disabled":
        api.runner.enabled = False
    elif fault == "port-owner":
        port.command_owner = object()
    elif fault == "session":
        api.runner.control_admission.owner.session_id = "replacement-session"
    elif fault in {"journal", "scope"}:
        table = "omx_journal_identity" if fault == "journal" else "omx_managed_transfer_scope"
        with closing(sqlite3.connect(store.path)) as connection:
            connection.execute(f"UPDATE {table} SET journal_id='replacement-journal'")
            connection.commit()
    elif fault == "admission":
        api.runner.control_admission = None
    reply = api.dispatch(FRAME, peer_uid=1001)
    assert reply["status"] == 503, reply
    assert reply["error"]["code"] == "ARM_TRANSFER_CAPABILITY_UNAVAILABLE"
    assert not port.submissions and store.unresolved_actions() == []


@pytest.mark.parametrize("frame,uid,status", [
    ({**FRAME, "version": 1}, 1001, 400), ({**FRAME, "extra": 1}, 1001, 400),
    (FRAME, 2002, 403),
])
def test_capability_uses_the_fleet_peer_role_and_exact_v2_frame(tmp_path, kin, profile, frame, uid, status):
    api, _, store, _, _ = _api(tmp_path, kin, profile)
    assert api.dispatch(frame, peer_uid=uid)["status"] == status
    assert store.unresolved_actions() == []


@pytest.mark.parametrize("field", ["owner_journal_id", "owner_session_id"])
def test_wrong_owner_target_is_rejected_before_any_action_journal(tmp_path, kin, profile, field):
    api, grant, store, port, _ = _api(tmp_path, kin, profile)
    body = grant.model_dump(mode="json")
    body.update(owner_journal_id=api.identity["journal_id"],
                owner_session_id=api.runner.control_admission.owner.session_id)
    body[field] = "other-owner"
    body["request_digest"] = action_grant_digest(body)
    reply = api.dispatch({"version": 2, "operation": "SubmitAction", "grant": body}, peer_uid=1001)
    assert reply["status"] == 403, reply
    assert not store.unresolved_actions() and not port.submissions


def test_arm_receipt_uses_the_actual_journal_and_past_session_remains_readable(tmp_path, kin, profile):
    api, grant, _, _, _ = _api(tmp_path, kin, profile)
    canonical = api.identity["journal_id"]
    api.identity["journal_id"] = "stale-static-journal"
    submitted = api.dispatch({"version": 2, "operation": "SubmitAction",
                              "grant": grant.model_dump(mode="json")}, peer_uid=1001)
    assert submitted["status"] == 200, submitted
    assert submitted["receipt"]["journal_id"] == canonical
    api.runner.control_admission.owner.session_id = "replacement-session"
    read = api.dispatch({"version": 2, "operation": "GetAction", "action_id": grant.action_id}, peer_uid=1001)
    assert read["status"] == 200 and read["receipt"]["journal_id"] == canonical


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="real UDS requires Linux peer credentials")
def test_fleet_reads_the_actual_installed_capability_over_uds(tmp_path, kin, profile):
    from fleet.server.local_action_transport import UnixLocalActionTransport

    api, grant, store, _, _ = _api(tmp_path, kin, profile)
    api.runner.allowed_peer_uids = frozenset({os.getuid()})
    with tempfile.TemporaryDirectory(prefix="arm-cap-") as temporary:
        root = Path(temporary)
        (root / grant.instance_id).mkdir()
        server = UnixActionServer(api, root / grant.instance_id / "control.sock")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.is_serving and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.is_serving
            client = UnixLocalActionTransport(root)
            read = getattr(client, "transfer_capability", None)
            assert read is not None, "Fleet capability query is missing"
            value = read(grant.instance_id, workcell_id=grant.workcell_id)
            assert value.journal_id == api.identity["journal_id"]
            assert value.owner_session_id == api.runner.control_admission.owner.session_id
            assert not store.unresolved_actions()
        finally:
            server.stop()
            thread.join(timeout=3)
