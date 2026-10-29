"""Real proposal HTTP/SQLite admission with fixture principals and simulated trip ports."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from fleet.server import trip_proposal_routes
from test_job_trip_steps import Rig, R, TWO

PATH = "/api/fleet/trip-proposals"


@pytest.fixture
def admission(tmp_path):
    rig, app = Rig(tmp_path), FastAPI()

    def principal(request: Request):
        actor = request.headers["X-Actor"]
        return SimpleNamespace(principal_id=actor, role="operator" if actor.startswith("operator") else "service",
                               permits_site=lambda *args: True)

    trip_proposal_routes.install_trip_proposal_routes(
        app, cell_job_store=rig.store, jobs=rig.jobs, check=lambda *args: None,
        require_proposer=principal, require_viewer=principal, require_named_operator=principal)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, rig


def propose(client, *, actor="proposer", key="proposal-key"):
    response = client.post(PATH, headers={"X-Actor": actor}, json={
        "candidate_robot_ids": [R], "steps": TWO, "request_key": key})
    assert response.status_code == 200
    return response.json()["proposal"]


def approve(client, rig, proposal, *, actor="operator-a", generation=None):
    return client.post(PATH + "/" + proposal["proposal_id"] + "/admit", headers={"X-Actor": actor}, json={
        "expected_proposal_digest": proposal["proposal_digest"],
        "expected_generation": rig.tasks.dispatch_control()["generation"] if generation is None else generation})


def test_stop_rearm_after_initial_check_cannot_refresh_an_old_approval(admission, monkeypatch):
    client, rig = admission
    proposal = propose(client)
    generation = rig.tasks.dispatch_control()["generation"]
    real_create = trip_proposal_routes.create_candidate_trip_job

    async def changed_before_candidate(*args, **kwargs):
        stopped = rig.tasks.trip_stop_latch(actor_id="operator-b")
        rig.tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-b")
        return await real_create(*args, **kwargs)

    monkeypatch.setattr(trip_proposal_routes, "create_candidate_trip_job", changed_before_candidate)
    response = approve(client, rig, proposal, generation=generation)

    assert response.status_code == 409
    assert rig.jobs.rows.ids(("READY", "RUNNING", "HOLD")) == []
    assert rig.store.resource_claims() == []
    assert rig.runner.lease.jobs == {}


def test_proposal_write_failure_rolls_back_job_steps_claims_and_admission(admission):
    client, rig = admission
    proposal = propose(client)
    with closing(rig.store._connect()) as connection, connection:
        connection.execute("CREATE TRIGGER reject_proposal_admission BEFORE UPDATE OF status ON fleet_trip_proposals "
                           "WHEN NEW.status='ADMITTED' BEGIN SELECT RAISE(ABORT, 'fixture proposal write failure'); END")

    response = approve(client, rig, proposal)

    assert response.status_code == 503
    with closing(rig.store._connect()) as connection:
        for table in ("fleet_cell_jobs", "fleet_cell_steps", "fleet_cell_events"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert rig.store.resource_claims() == []
    assert rig.runner.lease.jobs == {}


def test_concurrent_approvers_report_the_actor_of_the_committed_job(admission, monkeypatch):
    client, rig = admission
    proposal = propose(client)
    created, release = threading.Event(), threading.Event()
    real_create = trip_proposal_routes.create_candidate_trip_job

    async def pause_after_job(*args, **kwargs):
        job = await real_create(*args, **kwargs)
        if kwargs["approved_by"] == "operator-a":
            created.set()
            assert await asyncio.to_thread(release.wait, 10)
        return job

    monkeypatch.setattr(trip_proposal_routes, "create_candidate_trip_job", pause_after_job)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(approve, client, rig, proposal)
        try:
            assert created.wait(10)
            second = approve(client, rig, proposal, actor="operator-b")
        finally:
            release.set()
        first_response = first.result(timeout=10)
    assert first_response.status_code == second.status_code == 200
    assert first_response.json() == second.json()
    recorded = second.json()["proposal"]
    with closing(rig.store._connect()) as connection:
        actor = connection.execute("SELECT actor_id FROM fleet_cell_events WHERE mission_id=? "
                                   "AND event_type='CELL_JOB_ADMITTED'", (recorded["mission_id"],)).fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_jobs").fetchone()[0] == 1
    assert recorded["approved_by"] == actor == "operator-a"


def test_a_direct_job_cannot_be_relabelled_as_an_independent_proposal_approval(admission):
    client, rig = admission
    rig.do(trip_proposal_routes.create_candidate_trip_job(rig.jobs, [R], TWO, "operator-a", "shared-key"))
    proposal = propose(client, actor="operator-a", key="shared-key")

    response = approve(client, rig, proposal, actor="operator-b")

    assert response.status_code == 409
    read = client.get(PATH + "/" + proposal["proposal_id"], headers={"X-Actor": "operator-a"})
    assert read.json()["proposal"]["status"] == "PROPOSED"
