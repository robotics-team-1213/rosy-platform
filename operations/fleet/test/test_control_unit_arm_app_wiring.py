"""D-965 through create_app: R without an ARM installation relays; the cell's control unit sees its ARM jobs.

Control units install before the ARM routes, so this pins the install order the relay and the cell facade rely on.
"""
import asyncio
from hashlib import sha256

import httpx
import yaml

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_physical_transfer_store import installation  # noqa: F401

MANIFEST = {"revision": "v1", "units": [
    {"id": "R", "resources": ["robot:p1"]},
    {"id": "CELL-A", "parent": "R", "resources": ["workcell:w-1"]}]}
HARBOR = {"Authorization": "Bearer harbor-token"}
OPERATOR = {"Authorization": "Bearer op-token"}
JOBS = "http://r.test/api/fleet/arm-transfers/jobs"


class StopPort:
    def stop(self, **scope):
        return {"state": "LOCAL_LATCHED"}

    def rearm(self, **scope):
        return {"state": "OPEN"}


def users(*entries):
    return {sha256(token.encode()).hexdigest(): {"principal_id": identity, "role": role}
            for token, identity, role in entries}


def config(tmp_path, unit, peer, url):
    (tmp_path / (unit + ".token")).write_text("peer-" + unit, encoding="utf-8")
    path = tmp_path / (unit + ".yaml")
    path.write_text(yaml.safe_dump({"unit_id": unit, "manifest": MANIFEST,
                                    "peers": {peer: {"url": url, "token_file": unit + ".token"}}}), encoding="utf-8")
    return path


def site(tmp_path, monkeypatch, installation):
    apps, seen = {}, []

    class Network(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen.append((request.url.host, request.method, request.url.path, request.headers.get("authorization")))
            return await httpx.ASGITransport(app=apps[request.url.host]).handle_async_request(request)

    real = httpx.AsyncClient
    monkeypatch.setattr("fleet.server.control_unit_runtime.httpx.AsyncClient",
                        lambda *args, **kwargs: real(transport=Network()))
    r_db, cell_db = tmp_path / "r.sqlite3", tmp_path / "cell.sqlite3"
    console = FleetConsole([RobotEndpoint("p1", "http://robot.invalid", "device-token")], [FakeRobot("p1")])
    apps["r.test"] = create_app(
        console, task_service=FleetTaskService(FleetTaskStore(r_db), robot_ids=console.robot_ids),
        start_task_dispatcher=False, control_unit_config=config(tmp_path, "R", "CELL-A", "http://cell.test"),
        site_users=users(("harbor-token", "harbor", "service"), ("op-token", "operator-r", "operator"),
                         ("peer-CELL-A", "control-unit:CELL-A", "service")))
    apps["cell.test"] = create_app(
        FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(cell_db), robot_ids=()),
        mission_service=MissionService(MissionStore(cell_db)), proposal_store=ProposalStore(cell_db),
        start_task_dispatcher=False, deployment_profile="simulation", arm_transfer_installation=installation,
        omx_stop_transport=StopPort(), control_unit_config=config(tmp_path, "CELL-A", "R", "http://r.test"),
        site_users=users(("op-token", "operator-a", "operator"), ("peer-R", "control-unit:R", "service")))
    apps["seen"] = seen
    return apps


def transfer(installation, key):
    policy = installation.policy
    return {"request_key": key, "workcell_id": policy.primary[0], "instance_id": policy.primary[1],
            "object_ref": policy.object_ref, "source": installation.source, "target": installation.target}


def test_real_apps_relay_at_r_and_propose_in_the_cell_store(tmp_path, monkeypatch, installation):
    apps = site(tmp_path, monkeypatch, installation)
    assert apps["r.test"].state.arm_transfer_job_store is None
    assert apps["cell.test"].state.arm_transfer_delegate is not None

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps["r.test"])) as r:
            created = await r.post(JOBS, headers=HARBOR, json=transfer(installation, "harbor:wired-1"))
            assert created.status_code == 200, created.text
            job = created.json()["job"]
            assert (job["status"], job["proposal_principal_id"]) == ("PROPOSED", "harbor")
            assert job["delegated_by"] == {"origin_unit": "R", "requested_by": "harbor"}
            evidence = await r.get(JOBS + "/" + job["mission_id"] + "/physical-evidence", headers=HARBOR)
            assert evidence.status_code == 503  # this cell has no observer; the request still reached its delegation
            delegation = apps["cell.test"].state.control_unit.store.list()[0]["delegation_id"]
            assert ("cell.test", "GET", f"/api/fleet/control-unit/delegations/R/{delegation}/arm/physical-evidence",
                    "Bearer peer-R") in apps["seen"]
            cell_job = apps["cell.test"].state.arm_transfer_job_store.peek(job["mission_id"])
            assert cell_job["proposal_principal_id"] == "control-unit:R"
            admit = await r.post(JOBS + "/" + job["mission_id"] + "/admit", headers=OPERATOR,
                                 json={"expected_proposal_digest": "a" * 64, "expected_generation": 0})
            assert admit.status_code in {404, 405}
            canceled = await r.post(JOBS + "/" + job["mission_id"] + "/cancel", headers=HARBOR,
                                    json={"reason": "plan changed"})
            assert canceled.status_code == 200, canceled.text
            assert canceled.json()["job"]["status"] == "HOLD"
            assert apps["cell.test"].state.arm_transfer_job_store.peek(job["mission_id"])["status"] == "HOLD"
    asyncio.run(exercise())
