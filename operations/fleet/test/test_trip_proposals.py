"""D-908: neutral trip proposals are durable and claim nothing; a different named operator admits them."""
from contextlib import closing
from hashlib import sha256
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server import trip_proposal_routes
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_job_trip_steps import Rig, R, TWO
from fleet.server.trip_candidates import create_candidate_trip_job

ROBOT = "rosy_01"
PATH = "/api/fleet/trip-proposals"
USERS = {"harbor-secret": ("harbor", "service"), "other-secret": ("other", "service"),
         "op1-secret": ("operator-1", "operator"), "op2-secret": ("operator-2", "operator"),
         "viewer-secret": ("viewer-1", "viewer")}
BODY = {"candidate_robot_ids": [ROBOT], "request_key": "harbor/move-1", "steps": [{"to": "B", "via": []}]}


def headers(who):
    return {"Authorization": "Bearer " + who + "-secret"} if who else {}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskService(FleetTaskStore(path), robot_ids=(ROBOT,))
    users = {sha256(token.encode()).hexdigest(): {"principal_id": pid, "role": role}
             for token, (pid, role) in USERS.items()}
    app = create_app(
        FleetConsole([RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "robot-token")], [FakeRobot(ROBOT)]),
        task_service=tasks, site_users=users, deployment_profile="simulation",
        mission_service=MissionService(MissionStore(path)), proposal_store=ProposalStore(path))
    tasks.store.rearm_dispatch(expected_generation=tasks.store.dispatch_control()["generation"], actor_id="operator-1")
    app.state.job_trips.runner._store.active = lambda: (1, None, SimpleNamespace(places={"B", "C"}))
    made = []

    async def fake_create(jobs, candidates, steps, principal_id, request_key, **kwargs):
        made.append((candidates, steps, principal_id, request_key, kwargs))
        return {"mission_id": "mission-1"}
    monkeypatch.setattr(trip_proposal_routes, "create_candidate_trip_job", fake_create)
    return TestClient(app), tasks, made


def propose(rig, who="harbor", **changes):
    return rig[0].post(PATH, headers=headers(who), json={**BODY, **changes})


def args(rig, proposal, **changes):
    return {"expected_proposal_digest": proposal["proposal_digest"],
            "expected_generation": rig[1].store.dispatch_control()["generation"], **changes}


def test_proposal_is_durable_scoped_idempotent_and_claims_nothing(rig):
    client, _, made = rig
    first = propose(rig)
    assert first.status_code == 200
    proposal = first.json()["proposal"]
    assert proposal["status"] == "PROPOSED" and proposal["approved_by"] is None and proposal["mission_id"] is None
    assert propose(rig).json() == first.json()
    assert propose(rig, steps=[{"to": "C", "via": []}]).status_code == 409
    assert client.get(PATH, params={"request_key": BODY["request_key"]}, headers=headers("harbor")).json() == first.json()
    assert client.get(PATH, params={"request_key": BODY["request_key"]}, headers=headers("other")).status_code == 404
    url = PATH + "/" + proposal["proposal_id"]
    assert client.get(url, headers=headers("op1")).json() == first.json()
    assert client.get(url, headers=headers("other")).status_code == 403
    jobs = client.app.state.job_trips
    assert made == [] and jobs.runner.lease.jobs == {} and jobs.rows.ids(("READY", "RUNNING", "HOLD")) == []
    assert client.app.state.cell_job_store.resource_claims() == []


@pytest.mark.parametrize("who,status", [(None, 401), ("viewer", 403)])
def test_only_the_existing_proposer_roles_may_propose(rig, who, status):
    assert propose(rig, who=who).status_code == status


@pytest.mark.parametrize("changes", [{"robot_id": ROBOT}, {"cargo_id": "c1"}, {"candidate_robot_ids": [ROBOT, ROBOT]},
                                     {"steps": []}, {"request_key": " "}])
def test_cargo_business_and_malformed_fields_are_rejected(rig, changes):
    assert propose(rig, **changes).status_code == 422


def test_unknown_robot_or_place_is_refused_before_a_record_exists(rig):
    assert propose(rig, candidate_robot_ids=["nope"]).status_code == 404
    assert propose(rig, steps=[{"to": "Z", "via": []}]).json()["detail"]["code"] == "TRIP_UNKNOWN_PLACE"
    assert rig[0].get(PATH, params={"request_key": BODY["request_key"]}, headers=headers("harbor")).status_code == 404


def test_service_and_proposer_cannot_admit_and_nothing_is_created(rig):
    client, _, made = rig
    proposal = propose(rig).json()["proposal"]
    url = PATH + "/" + proposal["proposal_id"] + "/admit"
    assert client.post(url, headers=headers("harbor"), json=args(rig, proposal)).status_code == 403
    assert client.post(url, headers=headers("viewer"), json=args(rig, proposal)).status_code == 403
    own = propose(rig, who="op1", request_key="own").json()["proposal"]
    assert client.post(PATH + "/" + own["proposal_id"] + "/admit", headers=headers("op1"),
                       json=args(rig, own)).status_code == 403
    assert client.post(PATH + "/unknown/admit", headers=headers("op2"), json=args(rig, proposal)).status_code == 404
    bad_origin = {**headers("op2"), "Origin": "https://untrusted.invalid"}
    assert client.post(url, headers=bad_origin, json=args(rig, proposal)).status_code == 403
    assert made == []


@pytest.mark.parametrize("change", ["digest", "generation"])
def test_digest_or_generation_mismatch_is_rejected_and_the_proposal_stays_open(rig, change):
    client, tasks, made = rig
    proposal = propose(rig).json()["proposal"]
    wrong = {"expected_proposal_digest": "0" * 64} if change == "digest" else {
        "expected_generation": tasks.store.dispatch_control()["generation"] + 1}
    url = PATH + "/" + proposal["proposal_id"] + "/admit"
    assert client.post(url, headers=headers("op2"), json=args(rig, proposal, **wrong)).status_code == 409
    assert made == []
    assert client.get(PATH + "/" + proposal["proposal_id"], headers=headers("harbor")).json()["proposal"]["status"] == "PROPOSED"


def test_a_different_named_operator_admits_once_and_a_lost_response_is_recoverable(rig):
    client, tasks, made = rig
    proposal = propose(rig).json()["proposal"]
    url = PATH + "/" + proposal["proposal_id"] + "/admit"
    done = client.post(url, headers=headers("op2"), json=args(rig, proposal))
    assert done.status_code == 200
    admitted = done.json()["proposal"]
    assert admitted["status"] == "ADMITTED" and admitted["approved_by"] == "operator-2"
    assert admitted["mission_id"] == "mission-1"
    assert admitted["dispatch_generation"] == tasks.store.dispatch_control()["generation"]
    assert made[0][2:4] == ("harbor", BODY["request_key"]) and made[0][4]["approved_by"] == "operator-2"
    assert client.post(url, headers=headers("op1"), json=args(rig, proposal)).json() == done.json()
    assert propose(rig).json() == done.json()  # the original key still finds the record
    assert client.get(PATH, params={"request_key": BODY["request_key"]}, headers=headers("harbor")).json() == done.json()
    assert len(made) == 1


def test_a_closed_dispatch_does_not_admit(rig):
    client, tasks, made = rig
    proposal = propose(rig).json()["proposal"]
    tasks.store.trip_stop_latch(actor_id="operator-1")
    assert client.post(PATH + "/" + proposal["proposal_id"] + "/admit", headers=headers("op2"),
                       json=args(rig, proposal)).status_code == 409
    assert made == []


@pytest.mark.parametrize("profile", ["production"])
def test_routes_answer_unavailable_outside_the_simulation_profile(tmp_path, profile):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskService(FleetTaskStore(path), robot_ids=(ROBOT,))
    users = {sha256(t.encode()).hexdigest(): {"principal_id": p, "role": r} for t, (p, r) in USERS.items()}
    client = TestClient(create_app(
        FleetConsole([RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "robot-token")], [FakeRobot(ROBOT)]),
        task_service=tasks, site_users=users, deployment_profile=profile,
        mission_service=MissionService(MissionStore(path)), proposal_store=ProposalStore(path)))
    assert client.post(PATH, headers=headers("harbor"), json=BODY).status_code == 503
    assert client.get(PATH, params={"request_key": "k"}, headers=headers("harbor")).status_code == 503
    assert client.post(PATH + "/x/admit", headers=headers("op2"), json={
        "expected_proposal_digest": "0" * 64, "expected_generation": 0}).status_code == 503


def test_admission_makes_the_same_trip_ledger_job_as_the_operator_path(tmp_path):
    rig = Rig(tmp_path)
    job = rig.do(create_candidate_trip_job(rig.jobs, [R], TWO, "harbor", "k", approved_by="operator-2"))
    assert job["proposal_principal_id"] == "harbor" and job["status"] == "READY"
    assert rig.runner.lease.jobs[R].view["job_id"] == job["mission_id"]
    with closing(rig.store._connect()) as connection:
        actor = connection.execute("SELECT actor_id FROM fleet_cell_events WHERE mission_id=? AND "
                                   "event_type='CELL_JOB_ADMITTED'", (job["mission_id"],)).fetchone()[0]
    assert actor == "operator-2"
    assert rig.jobs.rows.read("harbor", request_key="k")["mission_id"] == job["mission_id"]
