"""D-965: R delegates arm work to the owning cell; the cell's ARM admit is the only approval."""

import asyncio
from contextlib import closing
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core_common.protocol.control_units import ControlArmIngressRequest, ControlArmWorkRequest
from fleet.server.arm_transfer_relay_routes import delegation_id
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_store import ControlUnitStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


MANIFEST = {"revision": "v1", "units": [
    {"id": "R", "resources": ["robot:p1"]},
    {"id": "ARM-CELL", "parent": "R", "resources": ["workcell:arm_a"]}]}
TRANSFER = {"request_key": "harbor:move-1", "workcell_id": "arm_a", "instance_id": "arm_a",
            "object_ref": "box-1", "source": "slot-1", "target": "slot-2"}
WORK = {"delegation_id": "arm-1", "target_unit": "ARM-CELL", "transfer": TRANSFER}
PARENT = SimpleNamespace(principal_id="control-unit:R", role="service")
HARBOR = SimpleNamespace(principal_id="harbor", role="service")
OTHER = SimpleNamespace(principal_id="other-app", role="service")
DIGEST = "a" * 64


class ArmJobs:
    """Same create/view/receipt/cancel contract as DelegatedArmJobs: one job per (principal, request_key)."""

    def __init__(self):
        self.jobs, self.calls, self.cancels, self.receipts = {}, [], [], {}

    def create(self, *, principal, request_key, request, bind=None):
        if principal is None:
            raise PermissionError("a configured named principal is required")
        self.calls.append((principal.principal_id, request_key, request))
        key = (principal.principal_id, request_key)
        self.jobs.setdefault(key, {
            "mission_id": "physical-" + str(len(self.jobs) + 1), "action_kind": "ARM_TRANSFER",
            "proposal_principal_id": principal.principal_id, "request_key": request_key,
            "request_digest": DIGEST, "proposal_digest": DIGEST, "transfer": request,
            "resource_policy_digest": DIGEST, "status": "PROPOSED", "authority_epoch": None,
            "dispatch_generation": None, "approved_by": None, "reason": None})
        if bind is not None:
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.row_factory = sqlite3.Row
                bind(connection, self.jobs[key]["mission_id"])
        return self.jobs[key]

    def view(self, mission_id):
        return next((dict(job) for job in self.jobs.values() if job["mission_id"] == mission_id), None)

    def receipt(self, mission_id):
        return self.receipts.get(mission_id)

    def cancel(self, mission_id, *, reason):
        self.cancels.append((mission_id, reason))
        for job in self.jobs.values():
            if job["mission_id"] == mission_id and job["status"] == "PROPOSED":
                job.update(status="HOLD", reason=reason)

    def evidence(self, mission_id):
        return {"evidence": {"mission_id": mission_id}}

    def request_recheck(self, mission_id, recheck_key, *, principal_id):
        self.rechecks = getattr(self, "rechecks", []) + [(mission_id, recheck_key, principal_id)]
        return {"recheck": {"mission_id": mission_id, "recheck_key": recheck_key}}

    def read_recheck(self, mission_id, recheck_key):
        return {"recheck": {"mission_id": mission_id, "recheck_key": recheck_key}}

    def set(self, **changes):
        next(iter(self.jobs.values())).update(changes)


def cluster(tmp_path, arm_jobs):
    from fleet.server.control_unit_service import ControlUnitService
    topology = ControlUnitTopology.from_mapping(MANIFEST)
    nodes = {}

    async def peer(unit, method, path, body=None):
        node = nodes[unit]
        if path == "inbox":
            return await node.receive(ControlArmIngressRequest.model_validate(body), parent_id="R", principal=PARENT)
        origin, identity = path.split("/")
        if method == "POST":
            await node.cancel(origin, identity, reason=(body or {}).get("reason"))
        return await node.read(origin, identity, for_child="R" if method == "GET" else None)

    for unit_id, jobs in [("R", None), ("ARM-CELL", arm_jobs)]:
        path = tmp_path / (unit_id + ".db")
        if jobs is not None:
            jobs.path = path
        robots = {r[6:] for r in topology.unit(unit_id).resources if r.startswith("robot:")}
        nodes[unit_id] = ControlUnitService(
            topology, ControlUnitStore(path, unit_id=unit_id), FleetTaskService(FleetTaskStore(path), robot_ids=robots),
            SimpleNamespace(trip_refusal=lambda robots: None), peer=peer, arm_jobs=lambda jobs=jobs: jobs)
    return nodes


def refresh(nodes):
    asyncio.run(nodes["ARM-CELL"].refresh())
    asyncio.run(nodes["R"].refresh())


def test_cell_proposes_once_under_the_parent_service_and_r_sees_the_projection(tmp_path):
    jobs = ArmJobs()
    nodes = cluster(tmp_path, jobs)
    request = ControlArmWorkRequest.model_validate(WORK)
    asyncio.run(nodes["R"].submit(request))
    asyncio.run(nodes["R"].submit(request))
    cell = nodes["ARM-CELL"].store.get("R", "arm-1")
    assert cell["local_task_id"] == "physical-1" and cell["status"] == "QUEUED"
    assert {call[0] for call in jobs.calls} == {"control-unit:R"}
    assert len({call[1] for call in jobs.calls}) == 1
    assert jobs.calls[0][1].startswith("control:")
    assert jobs.calls[0][1] != TRANSFER["request_key"]
    assert "request_key" not in jobs.calls[0][2]
    root = nodes["R"].store.get("R", "arm-1")
    assert root["owner_unit"] == "ARM-CELL" and root["local_task_id"] is None
    assert root["status"] == "QUEUED" and root["result"]["job"]["mission_id"] == "physical-1"
    assert root["result"]["job"]["request_key"] == "harbor:move-1"

    jobs.set(status="GOAL_CONFIRMED", approved_by="operator-a", authority_epoch=1, dispatch_generation=1)
    jobs.receipts["physical-1"] = {"receipt_id": "r-1"}
    refresh(nodes)
    root = nodes["R"].store.get("R", "arm-1")
    assert root["status"] == "COMPLETED" and root["result"]["receipt"] == {"receipt_id": "r-1"}


def test_delegation_approve_is_refused_for_arm_work(tmp_path):
    nodes = cluster(tmp_path, ArmJobs())
    asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(WORK)))
    revision = nodes["ARM-CELL"].store.get("R", "arm-1")["revision"]
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_ADMIT_AT_CELL"):
        asyncio.run(nodes["ARM-CELL"].approve("R", "arm-1", actor_id="operator-a", expected_revision=revision))


def test_cancel_before_admit_ends_canceled_and_after_admit_reaches_the_arm_once(tmp_path):
    jobs = ArmJobs()
    nodes = cluster(tmp_path, jobs)
    asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(WORK)))
    asyncio.run(nodes["R"].cancel("R", "arm-1"))
    assert nodes["ARM-CELL"].store.get("R", "arm-1")["status"] == "CANCELED"
    root = nodes["R"].store.get("R", "arm-1")
    assert root["status"] == "CANCELED" and root["result"]["job"]["status"] == "HOLD"
    assert root["result"]["job"]["reason"] == "control-unit-cancel"

    jobs = ArmJobs()
    (tmp_path / "admitted").mkdir()
    nodes = cluster(tmp_path / "admitted", jobs)
    asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(WORK)))
    jobs.set(status="RUNNING", approved_by="operator-a", authority_epoch=1, dispatch_generation=1)
    asyncio.run(nodes["R"].cancel("R", "arm-1"))
    refresh(nodes)
    assert jobs.cancels == [("physical-1", "control-unit-cancel")]
    root = nodes["R"].store.get("R", "arm-1")
    assert root["status"] == "RUNNING" and root["result"]["cancel_sent"] is True


def test_workcell_outside_the_target_scope_is_refused(tmp_path):
    nodes = cluster(tmp_path, ArmJobs())
    other = dict(WORK, transfer=dict(TRANSFER, workcell_id="arm_b", instance_id="arm_b"))
    with pytest.raises(ValueError, match="CONTROL_UNIT_RESOURCE_OUTSIDE_SCOPE"):
        asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(other)))


def test_missing_arm_jobs_or_principal_creates_no_binding(tmp_path):
    nodes = cluster(tmp_path, None)
    incoming = ControlArmIngressRequest.model_validate(dict(WORK, origin_id="R", config_revision="v1"))
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_JOBS_UNAVAILABLE"):
        asyncio.run(nodes["ARM-CELL"].receive(incoming, parent_id="R", principal=PARENT))
    assert nodes["ARM-CELL"].store.get("R", "arm-1")["local_task_id"] is None
    (tmp_path / "second").mkdir()
    nodes = cluster(tmp_path / "second", ArmJobs())
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_PROPOSAL_FORBIDDEN"):
        asyncio.run(nodes["ARM-CELL"].receive(incoming, parent_id="R", principal=None))


def relay(tmp_path, jobs):
    from fleet.server.arm_transfer_relay_routes import install_arm_transfer_relay_routes
    nodes = cluster(tmp_path, jobs)
    app, who = FastAPI(), {"principal": HARBOR}
    install_arm_transfer_relay_routes(app, control=nodes["R"], require_viewer=lambda: who["principal"],
                                      require_proposer=lambda: who["principal"])
    peer, forwarded = nodes["R"].peer, []

    class Peer:
        async def __call__(self, *args, **kwargs):
            return await peer(*args, **kwargs)

        async def arm_job(self, unit, method, origin, identity, tail, body=None):
            forwarded.append((unit, method, origin, identity, tail, body))
            return 404, {"detail": {"code": "ARM_TRANSFER_JOB_NOT_FOUND"}}
    nodes["R"].peer = Peer()
    who["forwarded"] = forwarded
    return TestClient(app), nodes, who


def test_r_relays_create_read_receipt_and_cancel_for_the_proposing_app_only(tmp_path):
    jobs = ArmJobs()
    client, nodes, who = relay(tmp_path, jobs)
    created = client.post("/api/fleet/arm-transfers/jobs", json=TRANSFER)
    assert created.status_code == 200, created.text
    job = created.json()["job"]
    assert job["mission_id"] == "physical-1" and job["proposal_principal_id"] == "harbor"
    assert jobs.view("physical-1")["proposal_principal_id"] == "control-unit:R"
    assert client.post("/api/fleet/arm-transfers/jobs", json=TRANSFER).json()["job"] == job
    assert len(jobs.jobs) == 1
    assert client.get("/api/fleet/arm-transfers/jobs", params={"request_key": "harbor:move-1"}).json()["job"] == job
    assert client.get("/api/fleet/arm-transfers/jobs/physical-1").json()["job"] == job
    pending = client.get("/api/fleet/arm-transfers/jobs/physical-1/physical-receipt")
    assert pending.status_code == 409 and pending.json()["detail"]["code"] == "ARM_TRANSFER_PHYSICAL_RECEIPT_PENDING"

    who["principal"] = SimpleNamespace(principal_id="operator-a", role="operator")
    assert client.get("/api/fleet/arm-transfers/jobs/physical-1").json()["job"]["proposal_principal_id"] == "control-unit:R"
    who["principal"] = OTHER
    assert client.get("/api/fleet/arm-transfers/jobs/physical-1").status_code == 403
    assert client.get("/api/fleet/arm-transfers/jobs", params={"request_key": "harbor:move-1"}).status_code == 404
    assert client.post("/api/fleet/arm-transfers/jobs/physical-1/cancel", json={"reason": "x"}).status_code == 403

    assert client.post("/api/fleet/arm-transfers/jobs/physical-1/rechecks", json={"recheck_key": "r-1"}).status_code == 403

    who["principal"] = HARBOR
    assert nodes["ARM-CELL"].store.list()[0]["request"]["requested_by"] == "harbor"
    evidence = client.get("/api/fleet/arm-transfers/jobs/physical-1/physical-evidence")
    assert evidence.status_code == 404 and evidence.json()["detail"]["code"] == "ARM_TRANSFER_JOB_NOT_FOUND"
    assert client.post("/api/fleet/arm-transfers/jobs/physical-1/rechecks", json={"recheck_key": "r-1"}).status_code == 404
    assert client.get("/api/fleet/arm-transfers/jobs/physical-1/rechecks/r-1").status_code == 404
    identity = delegation_id("harbor", "harbor:move-1")
    assert who["forwarded"] == [("ARM-CELL", "GET", "R", identity, "physical-evidence", None),
                                ("ARM-CELL", "POST", "R", identity, "rechecks", {"recheck_key": "r-1"}),
                                ("ARM-CELL", "GET", "R", identity, "rechecks/r-1", None)]
    canceled = client.post("/api/fleet/arm-transfers/jobs/physical-1/cancel", json={"reason": "operator changed plan"})
    assert canceled.status_code == 200 and canceled.json()["job"]["status"] == "HOLD"
    assert nodes["R"].store.list()[0]["status"] == "CANCELED"
    assert nodes["ARM-CELL"].store.list()[0]["cancel_reason"] == "operator changed plan"
    assert jobs.cancels == [("physical-1", "operator changed plan")]


@pytest.mark.parametrize("other_object", ["box-1", "box-2"])
def test_app_request_keys_remain_separate_at_the_cell(tmp_path, other_object):
    jobs = ArmJobs()
    client, _, who = relay(tmp_path, jobs)
    first = client.post("/api/fleet/arm-transfers/jobs", json=TRANSFER)
    assert first.status_code == 200, first.text
    first = first.json()["job"]
    assert client.post("/api/fleet/arm-transfers/jobs", json=TRANSFER).json()["job"] == first

    who["principal"] = OTHER
    body = dict(TRANSFER, object_ref=other_object)
    second = client.post("/api/fleet/arm-transfers/jobs", json=body)
    assert second.status_code == 200, second.text
    second = second.json()["job"]
    assert second["mission_id"] != first["mission_id"]
    assert first["request_key"] == second["request_key"] == TRANSFER["request_key"]
    assert client.post("/api/fleet/arm-transfers/jobs", json=body).json()["job"] == second
    assert len(jobs.jobs) == 2

    who["principal"] = HARBOR
    canceled = client.post("/api/fleet/arm-transfers/jobs/" + first["mission_id"] + "/cancel",
                          json={"reason": "origin canceled"})
    assert canceled.status_code == 200
    assert jobs.view(first["mission_id"])["status"] == "HOLD"
    assert jobs.view(second["mission_id"])["status"] == "PROPOSED"


def test_r_refuses_a_workcell_no_child_owns_and_reports_an_unreachable_cell(tmp_path):
    client, nodes, _ = relay(tmp_path, ArmJobs())
    other = dict(TRANSFER, workcell_id="arm_z", instance_id="arm_z")
    response = client.post("/api/fleet/arm-transfers/jobs", json=other)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "ARM_TRANSFER_WORKCELL_NOT_DELEGATED"

    async def down(*args, **kwargs):
        raise ConnectionError("cell offline")
    nodes["R"].peer = down
    response = client.post("/api/fleet/arm-transfers/jobs", json=TRANSFER)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "ARM_TRANSFER_JOB_UNAVAILABLE"


def test_a_lost_cell_link_reports_the_last_projection_without_serving_it_as_current(tmp_path):
    client, nodes, _ = relay(tmp_path, ArmJobs())
    assert client.post("/api/fleet/arm-transfers/jobs", json=TRANSFER).status_code == 200

    async def down(*args, **kwargs):
        raise ConnectionError("cell offline")
    nodes["R"].peer = down
    asyncio.run(nodes["R"].refresh())
    response = client.get("/api/fleet/arm-transfers/jobs/physical-1")
    assert response.status_code == 503
    assert response.json()["detail"]["last_projection"]["job_status"] == "PROPOSED"


def test_cell_serves_evidence_and_rechecks_only_for_a_bound_arm_delegation(tmp_path):
    jobs = ArmJobs()
    nodes = cluster(tmp_path, jobs)
    asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(WORK)))
    cell = nodes["ARM-CELL"]
    assert asyncio.run(cell.arm_detail("R", "arm-1", "evidence")) == {"evidence": {"mission_id": "physical-1"}}
    asyncio.run(cell.arm_detail("R", "arm-1", "request_recheck", key="r-1", principal_id="control-unit:R"))
    assert jobs.rechecks == [("physical-1", "r-1", "control-unit:R")]
    assert asyncio.run(cell.arm_detail("R", "arm-1", "read_recheck", key="r-1"))["recheck"]["recheck_key"] == "r-1"
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_JOB_NOT_BOUND"):
        asyncio.run(nodes["R"].arm_detail("R", "arm-1", "evidence"))  # R owns no ARM job
