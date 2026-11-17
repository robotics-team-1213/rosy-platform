from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_control_unit_runtime import config_file


def application(tmp_path, *, share=False):
    console = FleetConsole([RobotEndpoint("a1", "http://robot.invalid", "device-token")], [FakeRobot("a1")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids={"a1"})
    tasks.store.create_task(task_id="private-task", robot_id="a1", task_type="navigate",
        source="operator", actor_id="synthetic-private-actor", request_key="private-request",
        request={"note": "synthetic-private-request"}, evidence={"note": "synthetic-private-evidence"})
    users = {sha256(token.encode()).hexdigest(): {"principal_id": identity, "role": role}
             for token, identity, role in [
                 ("human-token", "operator-a1", "operator"),
                 ("viewer-token", "viewer-a1", "viewer"),
                 ("parent-token", "control-unit:A", "service"),
                 ("cell-token", "cell-service", "service")
             ]}
    return create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False,
        mission_service=MissionService(MissionStore(tasks.store.path)), proposal_store=ProposalStore(tasks.store.path),
        control_unit_config=config_file(tmp_path, **({"share_information_with_parent": True,
                                                    "accept_parent_stop": True} if share else {})))


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/fleet/tasks/private-task"), ("GET", "/api/fleet/state"),
    ("GET", "/api/fleet/dispatch-control"), ("GET", "/api/fleet/work"),
    ("POST", "/api/fleet/proposals"), ("POST", "/api/fleet/estop"),
    ("POST", "/api/fleet/dispatch/rearm"),
])
def test_dedicated_neighbor_cannot_escape_to_generic_fleet_endpoints(tmp_path, method, path):
    with TestClient(application(tmp_path)) as client:
        response = client.request(method, path, headers={"Authorization": "Bearer parent-token"},
                                  **({"json": {}} if method == "POST" else {}))
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "CONTROL_UNIT_CREDENTIAL_SCOPE_REQUIRED"


def test_neighbor_scope_keeps_explicit_projection_and_other_roles_read_access(tmp_path):
    with TestClient(application(tmp_path, share=True)) as client:
        parent = {"Authorization": "Bearer parent-token"}
        assert client.get("/api/fleet/control-unit/overview", headers=parent).status_code == 200
        detail = client.get("/api/fleet/control-unit/units/A1", headers=parent)
        assert detail.status_code == 200 and "synthetic-private" not in detail.text
        local = client.get("/api/fleet/tasks/private-task", headers={"Authorization": "Bearer viewer-token"})
        assert local.status_code == 200 and "synthetic-private-actor" in local.text
        for token in ["human-token", "viewer-token", "cell-token"]:
            response = client.get("/api/fleet/dispatch-control", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200, response.text
        response = client.post("/api/fleet/proposals", headers={"Authorization": "Bearer cell-token"}, json={})
        assert response.status_code == 422  # Generic Cell service still reaches ordinary body validation.


def test_similar_prefix_does_not_pass_authorization_boundary(tmp_path):
    from fastapi import Depends
    from fleet.server.site_auth import SitePrincipal, build_authorize

    app = application(tmp_path)
    principal = SitePrincipal("control-unit:A", "service")
    authorize = build_authorize(None, {sha256(b"parent-token").hexdigest(): principal}, app.state.task_service)

    @app.get("/api/fleet/control-unit-other")
    def lookalike(actor=Depends(authorize)):
        raise AssertionError("dedicated credential escaped its path component")

    with TestClient(app) as client:
        response = client.get("/api/fleet/control-unit-other", headers={"Authorization": "Bearer parent-token"})
        assert response.status_code == 403


def test_state_names_the_instance_by_its_control_unit(tmp_path):
    # D-974: R and ARM-CELL share fleet_name on one host; the header tells them apart by unit.
    with TestClient(application(tmp_path)) as client:
        fleet = client.get("/api/fleet/state", headers={"Authorization": "Bearer viewer-token"}).json()["fleet"]
    assert (fleet["unit"], fleet["root"]) == ("A1", False)
    # D-960 §4: the screen hides what this unit does not own; A1 drives a1 and has no arm or child.
    assert fleet["scope"] == {"role": "cell", "drive": True, "arms": False, "children": False, "enrollment": False}


def test_unit_scope_reads_the_manifest_and_standalone_keeps_everything():
    from fleet.server.control_unit_config import ControlUnitTopology, unit_scope
    from test_control_unit_service import MANIFEST

    topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": [
        *MANIFEST["units"], {"id": "ARM-CELL", "parent": "R", "resources": ["workcell:arm_a"]}]})
    assert unit_scope(topology, "R") == {"role": "root", "drive": False, "arms": False, "children": True,
                                         "enrollment": False}
    assert unit_scope(topology, "ARM-CELL")["arms"] is True
    assert unit_scope(topology, "B", has_arms=True)["arms"] is True  # an OMX wired to this instance
    assert unit_scope() == {"role": "standalone", "drive": True, "arms": True, "children": False,
                            "enrollment": True}
