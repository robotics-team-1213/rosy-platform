"""D-965 over HTTP: an app proposes ARM work at R, the cell owns it, only the cell's ARM admit approves."""

import asyncio
from hashlib import sha256

from fastapi import FastAPI
import httpx
import pytest

from fleet.server.arm_transfer_job_routes import DelegatedArmJobs
from fleet.server.arm_transfer_relay_routes import install_arm_transfer_relay_routes
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_routes import install_control_unit_routes
from fleet.server.control_unit_runtime import ControlUnitConfig, ControlUnitPeer, ControlUnitPeers
from fleet.server.control_unit_service import ControlUnitService
from fleet.server.control_unit_store import ControlUnitStore
from fleet.server.mission_store import MissionConflict
from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_physical_transfer_store import admit, installation, rig  # noqa: F401

MANIFEST = {"revision": "v1", "units": [
    {"id": "R", "resources": ["robot:p1"]},
    {"id": "CELL-A", "parent": "R", "resources": ["workcell:w-1"]}]}
TOKENS = [("harbor-token", "harbor", "service"), ("other-token", "other-app", "service"),
          ("op-token", "operator-2", "operator"), ("peer-R", "control-unit:R", "service"),
          ("peer-CELL-A", "control-unit:CELL-A", "service")]
HARBOR, OTHER, OPERATOR = ({"Authorization": "Bearer " + t} for t in ("harbor-token", "other-token", "op-token"))
JOBS = "http://R/api/fleet/arm-transfers/jobs"


def transfer(installation, key):
    policy = installation.policy
    return {"request_key": key, "workcell_id": policy.primary[0], "instance_id": policy.primary[1],
            "object_ref": policy.object_ref, "source": installation.source, "target": installation.target}


def site(tmp_path, rig):
    path, _, control, store = rig
    topology = ControlUnitTopology.from_mapping(MANIFEST)
    principals = {sha256(t.encode()).hexdigest(): SitePrincipal(i, r) for t, i, r in TOKENS}
    paths = {"R": tmp_path / "r.db", "CELL-A": path}
    nodes, apps = {}, {}
    for unit, jobs in [("R", None), ("CELL-A", DelegatedArmJobs(store, None))]:
        robots = {r[6:] for r in topology.unit(unit).resources if r.startswith("robot:")}
        tasks = FleetTaskService(FleetTaskStore(paths[unit]), robot_ids=robots)
        node = ControlUnitService(topology, ControlUnitStore(paths[unit], unit_id=unit), tasks,
                                  None, peer=None, arm_jobs=lambda jobs=jobs: jobs)
        app = FastAPI()
        authorize = build_authorize(None, principals, tasks)
        viewer, _, named, proposer = build_role_guards(authorize, principals)
        install_control_unit_routes(app, node, authorize=authorize, require_viewer=viewer,
                                    require_named_operator=named)
        if unit == "R":
            install_arm_transfer_relay_routes(app, control=node, require_viewer=viewer, require_proposer=proposer)
        nodes[unit], apps[unit] = node, app

    class Network(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await httpx.ASGITransport(app=apps[request.url.host.upper()]).handle_async_request(request)

    network = httpx.AsyncClient(transport=Network())
    for unit, node in nodes.items():
        peer = "CELL-A" if unit == "R" else "R"
        node.peer = ControlUnitPeers(ControlUnitConfig(unit, topology, {peer: ControlUnitPeer(
            "http://" + peer, "peer-" + unit)}), network)
    return nodes, network, store, control


async def refresh(nodes):
    await nodes["CELL-A"].refresh()
    await nodes["R"].refresh()


def test_app_proposal_reaches_the_cell_store_and_only_the_cell_admit_approves(tmp_path, rig, installation):
    async def exercise():
        nodes, network, store, control = site(tmp_path, rig)
        async with network:
            body = transfer(installation, "harbor:move-1")
            created = await network.post(JOBS, headers=HARBOR, json=body)
            assert created.status_code == 200, created.text
            job = created.json()["job"]
            assert (job["status"], job["proposal_principal_id"]) == ("PROPOSED", "harbor")
            cell_job = store.peek(job["mission_id"])
            assert cell_job["proposal_principal_id"] == "control-unit:R"
            again = await network.post(JOBS, headers=HARBOR, json=body)
            assert again.json()["job"]["mission_id"] == job["mission_id"]

            delegation = nodes["CELL-A"].store.list()[0]
            refused = await network.post(
                f"http://CELL-A/api/fleet/control-unit/delegations/R/{delegation['delegation_id']}/approve",
                headers=OPERATOR, json={"expected_revision": delegation["revision"]})
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "CONTROL_UNIT_ARM_ADMIT_AT_CELL"
            assert (await network.get(JOBS + "/" + job["mission_id"], headers=OTHER)).status_code == 403

            admit(store, cell_job, control)
            await refresh(nodes)
            read = await network.get(JOBS + "/" + job["mission_id"], headers=HARBOR)
            assert read.status_code == 200, read.text
            assert (read.json()["job"]["status"], read.json()["job"]["approved_by"]) == ("READY", "operator-2")
            receipt = await network.get(JOBS + "/" + job["mission_id"] + "/physical-receipt", headers=HARBOR)
            assert receipt.status_code == 409
    asyncio.run(exercise())


def test_app_cancel_before_admit_withdraws_the_cell_proposal_for_good(tmp_path, rig, installation):
    async def exercise():
        nodes, network, store, control = site(tmp_path, rig)
        async with network:
            job = (await network.post(JOBS, headers=HARBOR, json=transfer(installation, "harbor:move-2"))).json()["job"]
            canceled = await network.post(JOBS + "/" + job["mission_id"] + "/cancel", headers=HARBOR,
                                          json={"reason": "plan changed"})
            assert canceled.status_code == 200, canceled.text
            assert (canceled.json()["job"]["status"], canceled.json()["job"]["reason"]) == ("HOLD", "control-unit-cancel")
            assert nodes["R"].store.list()[0]["status"] == "CANCELED"
            with pytest.raises(MissionConflict):
                admit(store, store.peek(job["mission_id"]), control)
    asyncio.run(exercise())
