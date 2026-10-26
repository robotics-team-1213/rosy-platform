"""Fleet preflight is authenticated planning with no dispatcher/Cell requirement."""
from datetime import datetime
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.local_action_transport import UnixLocalActionTransport, LocalActionUnavailable
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


PATH = "/api/fleet/arm-transfers/preflight"
BODY = dict(workcell_id="arm-cell", instance_id="arm-a", catalog_digest="c" * 64,
            source="p1", target="p2", geometry="g1")


def check_result(body=BODY):
    return dict(request=dict(body), journal_id="owner-journal-1", profile_revision="a" * 64,
                kinematics_revision="b" * 64, calibration_revision="cal-1", transform_revision="tf-1",
                planning_scene_revision="kin:" + "b" * 64, source_state_sequence=7, state_age_s=0.01,
                simulation=True, collision_checked=False)


class ReadPort:
    def __init__(self):
        self.calls = []
        self.reply = check_result()

    def check_transfer(self, request):
        self.calls.append(request.model_dump())
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def client_for(tmp_path, port, profile="simulation"):
    users = {sha256(role.encode()).hexdigest(): {"principal_id": role + "-principal", "role": role}
             for role in ("operator", "service", "viewer", "policy-admin")}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"),
                     robot_ids=()), site_users=users, deployment_profile=profile,
                     omx_instances={"arm-cell": "arm-a"}, omx_action_transport=port)
    return TestClient(app)


def post(client, body=BODY, role="operator"):
    return client.post(PATH, json=body, headers={"Authorization": "Bearer " + role} if role else {})


@pytest.mark.parametrize("role", ["operator", "service"])
def test_preflight_reuses_installation_and_proposal_authorization_without_dispatch(tmp_path, role):
    port = ReadPort()
    client = client_for(tmp_path, port)
    response = post(client, role=role)
    assert response.status_code == 200
    assert response.json()["check"] == check_result()
    assert datetime.fromisoformat(response.json()["received_at"]).utcoffset().total_seconds() == 0
    assert port.calls == [BODY]
    assert client.app.state.cell_job_store is None
    assert client.app.state.mission_dispatcher is None


@pytest.mark.parametrize("role,status", [(None, 401), ("viewer", 403), ("policy-admin", 403)])
def test_read_planning_is_not_public_or_viewer_authority(tmp_path, role, status):
    port = ReadPort()
    assert post(client_for(tmp_path, port), role=role).status_code == status
    assert port.calls == []


def test_profile_and_target_fail_before_owner_io(tmp_path):
    port = ReadPort()
    assert post(client_for(tmp_path, port, "production")).status_code == 503
    assert post(client_for(tmp_path, port), {**BODY, "instance_id": "arm-b"}).status_code == 404
    assert post(client_for(tmp_path, port), {**BODY, "pallet": "pallet-1"}).status_code == 422
    assert port.calls == []


@pytest.mark.parametrize("reply", [TimeoutError(), check_result({**BODY, "target": "p3"}),
                                    {**check_result(), "simulation": False}])
def test_uncertain_or_substituted_result_never_becomes_a_check(tmp_path, reply):
    port = ReadPort()
    port.reply = reply
    response = post(client_for(tmp_path, port))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ARM_PREFLIGHT_UNAVAILABLE"
    assert len(port.calls) == 1


def test_existing_bounded_transport_binds_the_full_typed_request(tmp_path):
    from core_common.protocol import schemas
    request_model = getattr(schemas, "ArmTransferCheckRequest", None)
    assert request_model is not None, "typed neutral arm request is missing"
    request = request_model.model_validate(BODY)
    port = UnixLocalActionTransport(tmp_path)
    calls = []
    def exchange(instance, frame):
        calls.append((instance, frame))
        return {"version": 2, "status": 200, "check": check_result()}
    port._exchange = exchange
    assert port.check_transfer(request).request == request
    assert calls == [("arm-a", {"version": 2, "operation": "CheckTransfer", "transfer": BODY})]
    port._exchange = lambda *_: {"version": 2, "status": 200, "check": check_result({**BODY, "source": "p3"})}
    with pytest.raises(LocalActionUnavailable):
        port.check_transfer(request)
