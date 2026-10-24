"""Every installed physical participant shares site stop/rearm, including a shared workcell."""
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.local_stop_transport import UnixLocalStopTransport
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_dispatch_routes import fanout_local_omx_stops
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import installation

HEADERS = {"Authorization": "Bearer operator-secret", "Idempotency-Key": "stop-both"}


class StopPort:
    def __init__(self, *, failed_rearm=None):
        self.stops, self.rearms = [], []
        self.failed_rearm = failed_rearm

    def stop(self, **scope):
        self.stops.append(scope)
        return {"state": "LOCAL_LATCHED"}

    def rearm(self, **scope):
        self.rearms.append(scope)
        return {"state": "UNKNOWN" if scope["instance_id"] == self.failed_rearm else "OPEN"}


def client(tmp_path, installation, *, transport, legacy=None):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(path)
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(tasks, robot_ids=()),
        mission_service=MissionService(MissionStore(path)), proposal_store=ProposalStore(path),
        site_users={sha256(b"operator-secret").hexdigest(): {"principal_id": "operator", "role": "operator"}},
        deployment_profile="simulation", arm_transfer_installation=installation,
        omx_instances=legacy or {}, omx_stop_transport=transport)
    return TestClient(app), tasks


@pytest.mark.parametrize("intent", [False, True])
def test_http_and_intent_estop_stop_both_physical_owners_once_in_one_workcell(tmp_path, installation, intent):
    port = StopPort()
    app, tasks = client(tmp_path, installation, transport=port, legacy={"w-1": "arm-1"})
    response = app.post("/api/fleet/do" if intent else "/api/fleet/estop", headers=HEADERS,
                        **({"json": {"do": "estop"}} if intent else {}))
    assert response.status_code == 200
    assert [(s["workcell_id"], s["instance_id"]) for s in port.stops] == [("w-1", "arm-1"), ("w-1", "arm-2")]
    control = tasks.dispatch_control()
    assert all(s["authority_epoch"] == control["authority_epoch"] and s["dispatch_generation"] == control["generation"]
               for s in port.stops)
    assert app.app.state.omx_instances == {"w-1": "arm-1"}


@pytest.mark.parametrize("failure", [None, "arm-2"])
def test_physical_only_rearm_covers_both_owners_and_any_failure_stops_everyone(tmp_path, installation, failure):
    port = StopPort(failed_rearm=failure)
    app, tasks = client(tmp_path, installation, transport=port)
    response = app.post("/api/fleet/dispatch/rearm", headers=HEADERS,
                        json={"expected_generation": tasks.dispatch_control()["generation"]})
    assert response.status_code == (200 if failure is None else 409)
    assert [(s["workcell_id"], s["instance_id"]) for s in port.rearms] == [("w-1", "arm-1"), ("w-1", "arm-2")]
    if failure:
        assert tasks.dispatch_control()["dispatch_enabled"] is False
        assert [(s["workcell_id"], s["instance_id"]) for s in port.stops] == [("w-1", "arm-1"), ("w-1", "arm-2")]
        assert all(s["dispatch_generation"] == tasks.dispatch_control()["generation"] for s in port.stops)
    else:
        assert tasks.dispatch_control()["dispatch_enabled"] is True and port.stops == []


def test_physical_only_installation_gets_a_default_stop_transport(tmp_path, installation):
    app, _ = client(tmp_path, installation, transport=None)
    assert isinstance(app.app.state.omx_stop_transport, UnixLocalStopTransport)


def test_one_instance_cannot_be_bound_to_conflicting_legacy_and_physical_workcells(tmp_path, installation):
    with pytest.raises(ValueError, match="workcell"):
        client(tmp_path, installation, transport=StopPort(), legacy={"different": "arm-1"})


def test_missing_control_or_transport_reports_every_physical_target_as_unknown():
    result = fanout_local_omx_stops({}, None, None, reason="SITE_STOP",
                                  targets=(("w-1", "arm-1"), ("w-1", "arm-2")))
    assert result["state"] == "UNKNOWN"
    assert [(s["workcell_id"], s["instance_id"]) for s in result["instances"]] == [("w-1", "arm-1"), ("w-1", "arm-2")]
