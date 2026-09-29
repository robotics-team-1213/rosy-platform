from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


def _client(tmp_path, *, transport, instances):
    robot = FakeRobot("rosy_01")
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})
    token = "operator-token"
    app = create_app(
        FleetConsole([RobotEndpoint("rosy_01", "http://robot.local", "rest-token")],
                     [robot]),
        task_service=service,
        site_users={sha256(token.encode()).hexdigest(): {
            "principal_id": "operator-1", "role": "operator",
        }},
        start_task_dispatcher=False,
        omx_instances=instances,
        omx_stop_transport=transport,
    )
    return TestClient(app), service, robot


def test_fleet_estop_fans_out_current_epoch_and_generation_to_local_stop(tmp_path):
    calls = []

    class Transport:
        def stop(self, **kwargs):
            calls.append(kwargs)
            return {"state": "LOCAL_LATCHED", "reason": "FLEET_ESTOP"}

    client, service, robot = _client(
        tmp_path, transport=Transport(), instances={"omx-1": "omx-1-control"},
    )
    response = client.post("/api/fleet/estop",
                           headers={"Authorization": "Bearer operator-token"})

    assert response.status_code == 200
    assert ("estop",) in robot.calls
    assert calls[0]["authority_epoch"] == service.store.dispatch_control()["authority_epoch"]
    assert calls[0]["dispatch_generation"] == service.store.dispatch_control()["generation"]
    assert response.json()["omx_local_stop"]["state"] == "LOCAL_LATCHED"
    assert response.json()["omx_local_stop"]["instances"][0]["instance_id"] == "omx-1-control"


def test_local_stop_fanout_failure_is_unknown_while_robot_stop_continues(tmp_path):
    class Transport:
        def stop(self, **_kwargs):
            raise TimeoutError("socket unavailable")

    client, _, robot = _client(
        tmp_path, transport=Transport(), instances={"omx-1": "omx-1-control"},
    )
    response = client.post("/api/fleet/estop",
                           headers={"Authorization": "Bearer operator-token"})

    assert response.status_code == 200
    assert ("estop",) in robot.calls
    assert response.json()["omx_local_stop"]["state"] == "UNKNOWN"
    assert response.json()["omx_local_stop"]["instances"][0]["reason"] == "TimeoutError"


def test_unconfigured_omx_stop_fanout_is_explicit(tmp_path):
    client, _, _ = _client(tmp_path, transport=None, instances={})

    response = client.post("/api/fleet/estop",
                           headers={"Authorization": "Bearer operator-token"})

    assert response.status_code == 200
    assert response.json()["omx_local_stop"] == {"state": "NOT_CONFIGURED", "instances": []}


def test_failed_local_rearm_recloses_fleet_dispatch(tmp_path):
    class Transport:
        def __init__(self):
            self.stops = []

        def rearm(self, **_kwargs):
            return {"state": "UNKNOWN", "reason": "LOCAL_REARM_REFUSED"}

        def stop(self, **kwargs):
            self.stops.append(kwargs)
            return {"state": "LOCAL_LATCHED", "reason": "OMX_REARM_ROLLBACK"}

    transport = Transport()
    client, service, _ = _client(
        tmp_path, transport=transport, instances={"omx-1": "omx-1-control"},
    )
    before = service.store.dispatch_control()
    response = client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": before["generation"]},
        headers={"Authorization": "Bearer operator-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LOCAL_WORKCELL_REARM_FAILED"
    assert service.store.dispatch_control()["dispatch_enabled"] is False
    assert len(transport.stops) == 1
