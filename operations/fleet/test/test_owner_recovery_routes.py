"""D-442 recovery uses named operator authentication and durable Fleet audit."""

from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


class Transport:
    def __init__(self):
        self.calls = []
    def owner_state(self, *, workcell_id, instance_id):
        return {"version": 1, "status": 200, "workcell_id": workcell_id, "instance_id": instance_id,
                "owner": {"state": "hold", "observed_sequence": 11}}
    def recover_owner(self, **kwargs):
        self.calls.append(kwargs)
        return {"version": 1, "status": 200, "workcell_id": kwargs["workcell_id"],
                "instance_id": kwargs["instance_id"], "actor_id": kwargs["actor_id"],
                "observed_sequence": kwargs["observed_sequence"],
                "decision": {"accepted": True, "state": "ready", "reason": "recovered"}}


def client_for(tmp_path, *, named=True, transport=None):
    store = FleetTaskStore(tmp_path / "fleet.db")
    tasks = FleetTaskService(store, robot_ids=())
    transport = transport or Transport()
    users = {sha256(b"op-token").hexdigest(): {"principal_id": "operator-a", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "viewer-a", "role": "viewer"}} if named else None
    app = create_app(FleetConsole([], []), task_service=tasks, site_users=users,
                     omx_instances={"cell-1": "arm-1"}, omx_stop_transport=transport,
                     start_task_dispatcher=False)
    store.rearm_dispatch(expected_generation=store.dispatch_control()["generation"], actor_id="operator-a")
    return TestClient(app), store, transport


PATH = "/api/fleet/workcells/cell-1/owner/recover"
OP = {"Authorization": "Bearer op-token"}
VIEW = {"Authorization": "Bearer viewer-token"}


def body(store):
    return {"operator_confirmed": True, "observed_sequence": 11,
            "expected_generation": store.dispatch_control()["generation"]}


def test_named_operator_confirmation_is_audited_and_sent_once(tmp_path):
    client, store, transport = client_for(tmp_path)
    result = client.post(PATH, headers=OP, json=body(store))
    assert result.status_code == 200 and len(transport.calls) == 1
    assert transport.calls[0]["actor_id"] == "operator-a"
    assert transport.calls[0]["operator_confirmed"] is True
    audit = store.api_audit()
    assert {row["event_type"] for row in audit} == {"INTENT", "RESULT"}
    assert all(row["principal_id"] == "operator-a" and row["path"] == PATH for row in audit)


def test_viewer_and_anonymous_operator_cannot_recover(tmp_path):
    client, store, transport = client_for(tmp_path / "named")
    assert client.post(PATH, headers=VIEW, json=body(store)).status_code == 403
    assert transport.calls == []
    client, store, transport = client_for(tmp_path / "anonymous", named=False)
    assert client.post(PATH, json=body(store)).status_code == 403
    assert transport.calls == []


@pytest.mark.parametrize("patch", [{"operator_confirmed": False}, {"operator_confirmed": 1},
                                   {"observed_sequence": True}, {"expected_generation": True}])
def test_confirmation_and_freshness_fields_are_strict(tmp_path, patch):
    client, store, transport = client_for(tmp_path)
    assert client.post(PATH, headers=OP, json={**body(store), **patch}).status_code == 422
    assert transport.calls == []


def test_stale_generation_and_audit_failure_block_transport(tmp_path):
    client, store, transport = client_for(tmp_path)
    assert client.post(PATH, headers=OP, json={**body(store), "expected_generation": 0}).status_code == 409
    def fail_audit(**kwargs):
        raise OSError("audit storage offline")
    store.begin_api_audit = fail_audit
    assert client.post(PATH, headers=OP, json=body(store)).status_code == 503
    assert transport.calls == []


def test_named_http_to_actual_uds_dispatcher_and_owner_recovers_without_motion(tmp_path):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    for relative in ("middleware/apps/device/omx/adapter", "middleware/apps/device/omx/adapter/test"):
        sys.path.insert(0, str(root / relative))
    from omx_adapter.action_api import ActionApi
    from omx_adapter.action_store import ActionStore
    from omx_adapter.local_stop import LocalStopController
    from omx_adapter.owner_recovery_api import OwnerRecoveryApi
    from fleet.server.local_stop_transport import UnixLocalStopTransport
    from test_omx_command_owner import make_config, make_state, owner_at

    owner, action = owner_at([100.0], make_config(workcell_id="cell-1", instance_id="arm-1"))
    owner.observe_joint_state(make_state())
    owner.preempt("manual_priority")
    owner.observe_joint_state(make_state(sequence=11))
    journal = ActionStore(tmp_path / "local-owner.db")
    stop = LocalStopController(journal.path, workcell_id="cell-1", instance_id="arm-1")
    fleet_store = []
    def current_fence(epoch, generation):
        state = fleet_store[0].dispatch_control()
        return state["dispatch_enabled"] and (epoch, generation) == (state["authority_epoch"], state["generation"])
    recovery = OwnerRecoveryApi(owner, stop, journal, allowed_peer_uids={1001}, current_fence=current_fence)
    dispatcher = ActionApi(object(), recovery_api=recovery)
    transport = UnixLocalStopTransport(tmp_path / "sockets")
    frames = []
    def exchange(instance_id, request):
        frames.append(request)
        return dispatcher.dispatch(request, peer_uid=1001)  # Substitute OS peer credentials only.
    transport._exchange = exchange
    client, store, _ = client_for(tmp_path / "site", transport=transport)
    fleet_store.append(store)
    control = store.dispatch_control()
    stop.rearm(authority_epoch=control["authority_epoch"], dispatch_generation=control["generation"],
               operator_confirmed=True, fleet_fence_current=current_fence)
    state = client.get("/api/fleet/workcells/cell-1/owner", headers=VIEW)
    assert state.status_code == 200 and state.json()["owner"]["state"] == "hold"
    result = client.post(PATH, headers=OP, json=body(store))
    assert result.status_code == 200 and result.json()["decision"]["reason"] == "recovered"
    assert owner.state == "ready" and action.commands == []
    assert [frame["operation"] for frame in frames] == ["GetOwnerState", "RecoverOwner"]
    assert frames[-1]["actor_id"] == "operator-a"
    assert {row["event_type"] for row in store.api_audit()} == {"INTENT", "RESULT"}
