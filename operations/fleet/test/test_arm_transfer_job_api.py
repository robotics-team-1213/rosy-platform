"""HTTP proposal/admission uses named principals, installed snapshots and host SDK reads."""
from hashlib import sha256
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.local_action_transport import LocalActionUnavailable
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import installation

PATH = "/api/fleet/arm-transfers/jobs"


class CapabilityPort:
    def __init__(self, installation, path):
        self.capabilities = list(installation.capabilities)
        self.calls = []
        self.error = None
        self.path = path

    def transfer_capability(self, instance_id, *, workcell_id):
        self.calls.append((workcell_id, instance_id))
        # No network I/O is allowed while an admission transaction holds the writer.
        with sqlite3.connect(self.path, timeout=.05) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        if self.error:
            raise self.error
        return next(c for c in self.capabilities if (c.workcell_id, c.instance_id) == (workcell_id, instance_id))


def headers(who):
    return {"Authorization": "Bearer " + who + "-secret"} if who else {}


@pytest.fixture
def rig(tmp_path, installation):
    db = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(db)
    port = CapabilityPort(installation, db)
    users = {sha256((name + "-secret").encode()).hexdigest(): {"principal_id": name, "role": role}
             for name, role in (("harbor", "service"), ("other", "service"), ("operator", "operator"),
                                ("viewer", "viewer"), ("observer", "ai_observer"), ("policy-admin", "policy-admin"))}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(tasks, robot_ids=()),
        mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db),
        site_users=users, deployment_profile="simulation", omx_action_transport=port,
        arm_transfer_installation=installation)
    tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()["generation"], actor_id="operator")
    return TestClient(app), tasks, port, installation


def body(installation):
    return dict(request_key="move-1", workcell_id=installation.policy.primary[0], instance_id=installation.policy.primary[1],
                object_ref=installation.policy.object_ref, source=installation.source, target=installation.target)


def create(rig, who="harbor", **changes):
    client, _, _, installed = rig
    return client.post(PATH, headers=headers(who), json={**body(installed), **changes})


def claims(rig):
    return rig[0].app.state.cell_job_store.resource_claims()


def test_create_is_scoped_idempotent_and_does_not_query_or_submit_to_an_owner(rig):
    client, tasks, port, installed = rig
    response = create(rig)
    assert response.status_code == 200
    job = response.json()["job"]
    assert job["action_kind"] == "ARM_TRANSFER" and job["status"] == "PROPOSED"
    assert job["transfer"] == {k: v for k, v in body(installed).items() if k != "request_key"}
    assert not {"resources", "installation", "capabilities", "job_id", "recipe_digest"} & set(job)
    assert create(rig).json() == response.json()
    assert create(rig, target="other").status_code == 409
    assert client.get(PATH, params={"request_key": "move-1"}, headers=headers("harbor")).json() == response.json()
    assert client.get(PATH + "/" + job["mission_id"], headers=headers("operator")).json() == response.json()
    assert client.get(PATH + "/" + job["mission_id"], headers=headers("other")).status_code == 403
    assert client.get(PATH, params={"request_key": "move-1"}, headers=headers("other")).status_code == 404
    assert port.calls == [] and claims(rig) == []
    assert client.app.state.cell_job_store.get(job["mission_id"]) is None


def test_approval_reads_every_current_capability_then_atomically_claims_without_submit(rig):
    client, tasks, port, installed = rig
    job = create(rig).json()["job"]
    args = {"expected_proposal_digest": job["proposal_digest"], "expected_generation": tasks.dispatch_control()["generation"]}
    url = PATH + "/" + job["mission_id"] + "/admit"
    ready = client.post(url, headers=headers("operator"), json=args)
    assert ready.status_code == 200
    assert ready.json()["job"]["status"] == "READY" and ready.json()["job"]["approved_by"] == "operator"
    expected = [(p.workcell_id, p.instance_id) for p in installed.policy.participants]
    assert port.calls == expected
    assert len(claims(rig)) == len(installed.policy.resources)
    assert client.post(url, headers=headers("operator"), json=args).json() == ready.json()
    assert port.calls == expected + expected
    audit = tasks.api_audit()
    assert any(r["path"] == url and r["status_code"] == 200 and r["principal_id"] == "operator" for r in audit)
    assert "-secret" not in json.dumps(audit)


@pytest.mark.parametrize("who,status", [(None, 401), ("viewer", 403), ("observer", 403), ("policy-admin", 403)])
def test_proposals_reuse_existing_auth_roles_before_owner_io(rig, who, status):
    assert create(rig, who=who).status_code == status
    assert rig[2].calls == [] and claims(rig) == []


@pytest.mark.parametrize("field,value", [("resources", []), ("capabilities", []), ("grant", {}),
    ("satisfied", True), ("producer_id", "caller"), ("recipe", {})])
def test_extra_authority_or_process_fields_are_rejected(rig, field, value):
    assert create(rig, **{field: value}).status_code == 422
    assert claims(rig) == []


def test_service_self_approval_bad_origin_and_unknown_job_do_not_query_the_owner(rig):
    client, tasks, port, _ = rig
    job = create(rig).json()["job"]
    args = {"expected_proposal_digest": job["proposal_digest"], "expected_generation": tasks.dispatch_control()["generation"]}
    assert client.post(PATH + "/" + job["mission_id"] + "/admit", headers=headers("harbor"), json=args).status_code == 403
    own = create(rig, who="operator", request_key="operator-move").json()["job"]
    assert client.post(PATH + "/" + own["mission_id"] + "/admit", headers=headers("operator"),
                       json={**args, "expected_proposal_digest": own["proposal_digest"]}).status_code == 403
    assert client.post(PATH + "/unknown/admit", headers=headers("operator"), json=args).status_code == 404
    assert client.post(PATH, headers={**headers("harbor"), "Origin": "https://untrusted.invalid"}, json=body(rig[3])).status_code == 403
    assert client.post(PATH + "/" + job["mission_id"] + "/admit",
                       headers={**headers("operator"), "Origin": "https://untrusted.invalid"}, json=args).status_code == 403
    assert port.calls == [] and claims(rig) == []


@pytest.mark.parametrize("failure,status", [("unavailable", 503), ("changed", 409), ("disabled", 409)])
def test_unavailable_or_changed_owners_and_closed_control_preserve_the_proposal(rig, failure, status):
    client, tasks, port, _ = rig
    job = create(rig).json()["job"]
    args = {"expected_proposal_digest": job["proposal_digest"], "expected_generation": tasks.dispatch_control()["generation"]}
    if failure == "unavailable":
        port.error = LocalActionUnavailable("unavailable")
    elif failure == "changed":
        port.capabilities[1] = port.capabilities[1].model_copy(update={"owner_session_id": "different"})
    else:
        tasks.trip_stop_latch(actor_id="operator")
    response = client.post(PATH + "/" + job["mission_id"] + "/admit", headers=headers("operator"), json=args)
    assert response.status_code == status and claims(rig) == []
    assert client.get(PATH + "/" + job["mission_id"], headers=headers("harbor")).json()["job"]["status"] == "PROPOSED"


def test_unbound_routes_return_unavailable_instead_of_false_absence(tmp_path):
    tasks = FleetTaskStore(tmp_path / "fleet.sqlite3")
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(tasks, robot_ids=()))
    client = TestClient(app)
    assert client.get(PATH, params={"request_key": "move-1"}).status_code == 503
    assert client.get(PATH + "/unknown").status_code == 503


def test_physical_profile_cannot_be_installed_in_a_production_application(installation):
    with pytest.raises(ValueError, match="simulation"):
        create_app(FleetConsole([], []), deployment_profile="production", arm_transfer_installation=installation)
