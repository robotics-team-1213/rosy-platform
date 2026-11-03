"""D-965: R delegates arm work to the owning cell; the cell's ARM admit is the only approval."""

import asyncio
from types import SimpleNamespace

import pytest

from core_common.protocol.control_units import ControlArmIngressRequest, ControlArmWorkRequest
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_store import ControlUnitStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


MANIFEST = {"revision": "v1", "units": [
    {"id": "R", "resources": ["robot:p1"]},
    {"id": "CELL-A", "parent": "R", "resources": ["workcell:arm_a"]}]}
TRANSFER = {"request_key": "harbor:move-1", "workcell_id": "arm_a", "instance_id": "arm_a",
            "object_ref": "box-1", "source": "slot-1", "target": "slot-2"}
WORK = {"delegation_id": "arm-1", "target_unit": "CELL-A", "transfer": TRANSFER}
PARENT = SimpleNamespace(principal_id="control-unit:R", role="service")


class ArmJobs:
    """Same create/peek contract as PhysicalTransferStore: one job per (principal, request_key)."""

    def __init__(self):
        self.jobs, self.calls = {}, []

    def create(self, *, principal, request_key, request):
        if principal is None:
            raise PermissionError("a configured named principal is required")
        self.calls.append((principal.principal_id, request_key, request))
        key = (principal.principal_id, request_key)
        self.jobs.setdefault(key, {"mission_id": "physical-" + str(len(self.jobs) + 1),
                                   "status": "PROPOSED", "reason": None})
        return self.jobs[key]

    def peek(self, mission_id):
        return next((job for job in self.jobs.values() if job["mission_id"] == mission_id), None)


def cluster(tmp_path, arm_jobs):
    from fleet.server.control_unit_service import ControlUnitService
    topology = ControlUnitTopology.from_mapping(MANIFEST)
    nodes = {}

    async def peer(unit, method, path, body=None):
        node = nodes[unit]
        if path == "inbox":
            return await node.receive(ControlArmIngressRequest.model_validate(body), parent_id="R", principal=PARENT)
        origin, identity = path.split("/")
        return await node.read(origin, identity, for_child="R" if method == "GET" else None)

    for unit_id, jobs in [("R", None), ("CELL-A", arm_jobs)]:
        path = tmp_path / (unit_id + ".db")
        robots = {r[6:] for r in topology.unit(unit_id).resources if r.startswith("robot:")}
        nodes[unit_id] = ControlUnitService(
            topology, ControlUnitStore(path, unit_id=unit_id), FleetTaskService(FleetTaskStore(path), robot_ids=robots),
            SimpleNamespace(trip_refusal=lambda robots: None), peer=peer, arm_jobs=lambda jobs=jobs: jobs)
    return nodes


def test_cell_proposes_once_under_the_parent_service_and_r_sees_the_projection(tmp_path):
    jobs = ArmJobs()
    nodes = cluster(tmp_path, jobs)
    request = ControlArmWorkRequest.model_validate(WORK)
    asyncio.run(nodes["R"].submit(request))
    asyncio.run(nodes["R"].submit(request))
    cell = nodes["CELL-A"].store.get("R", "arm-1")
    assert cell["local_task_id"] == "physical-1" and cell["status"] == "QUEUED"
    assert {call[:2] for call in jobs.calls} == {("control-unit:R", "harbor:move-1")}
    assert "request_key" not in jobs.calls[0][2]
    root = nodes["R"].store.get("R", "arm-1")
    assert root["owner_unit"] == "CELL-A" and root["local_task_id"] is None
    assert root["status"] == "QUEUED" and root["result"]["mission_id"] == "physical-1"

    jobs.jobs[("control-unit:R", "harbor:move-1")]["status"] = "GOAL_CONFIRMED"
    asyncio.run(nodes["CELL-A"].refresh())
    asyncio.run(nodes["R"].refresh())
    assert nodes["R"].store.get("R", "arm-1")["status"] == "COMPLETED"


def test_delegation_approve_is_refused_for_arm_work(tmp_path):
    nodes = cluster(tmp_path, ArmJobs())
    asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(WORK)))
    revision = nodes["CELL-A"].store.get("R", "arm-1")["revision"]
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_ADMIT_AT_CELL"):
        asyncio.run(nodes["CELL-A"].approve("R", "arm-1", actor_id="operator-a", expected_revision=revision))


def test_workcell_outside_the_target_scope_is_refused(tmp_path):
    nodes = cluster(tmp_path, ArmJobs())
    other = dict(WORK, transfer=dict(TRANSFER, workcell_id="arm_b", instance_id="arm_b"))
    with pytest.raises(ValueError, match="CONTROL_UNIT_RESOURCE_OUTSIDE_SCOPE"):
        asyncio.run(nodes["R"].submit(ControlArmWorkRequest.model_validate(other)))


def test_missing_arm_jobs_or_principal_creates_no_binding(tmp_path):
    nodes = cluster(tmp_path, None)
    incoming = ControlArmIngressRequest.model_validate(dict(WORK, origin_id="R", config_revision="v1"))
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_JOBS_UNAVAILABLE"):
        asyncio.run(nodes["CELL-A"].receive(incoming, parent_id="R", principal=PARENT))
    assert nodes["CELL-A"].store.get("R", "arm-1")["local_task_id"] is None
    (tmp_path / "second").mkdir()
    nodes = cluster(tmp_path / "second", ArmJobs())
    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_PROPOSAL_FORBIDDEN"):
        asyncio.run(nodes["CELL-A"].receive(incoming, parent_id="R", principal=None))
