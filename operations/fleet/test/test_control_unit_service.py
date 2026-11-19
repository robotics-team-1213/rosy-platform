import asyncio
from types import SimpleNamespace
import pytest

from core_common.protocol.control_units import ControlWorkRequest, ControlIngressRequest
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_store import ControlUnitStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


MANIFEST = {"revision": "v1", "units": [
    {"id": "R"}, {"id": "A", "parent": "R"},
    {"id": "B", "parent": "R", "resources": ["robot:b"]},
    {"id": "A1", "parent": "A", "resources": ["robot:a1"]}]}
WORK = {"delegation_id": "job-1", "target_unit": "A1", "robot_id": "a1",
        "goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}


class Console:
    def trip_refusal(self, robots):
        return None

    def discard_task_queue_entries(self, task_ids):
        pass


def cluster(tmp_path):
    from fleet.server.control_unit_service import ControlUnitService
    nodes, disconnected = {}, set()
    topology = ControlUnitTopology.from_mapping(MANIFEST)
    for unit_id in topology.units:
        path = tmp_path / (unit_id + ".db")
        robots = {r[6:] for r in topology.unit(unit_id).resources if r.startswith("robot:")}
        tasks = FleetTaskService(FleetTaskStore(path), robot_ids=robots)

        async def peer(unit, method, path, body=None, *, sender=unit_id):
            if unit in disconnected or sender in disconnected:
                raise ConnectionError("test disconnect")
            node = nodes[unit]
            if path == "inbox":
                return await node.receive(ControlIngressRequest.model_validate(body), parent_id=sender)
            origin, identity = path.split("/")
            if method == "POST":
                await node.cancel(origin, identity)
            return await node.read(origin, identity, for_child=sender if method == "GET" else None)

        nodes[unit_id] = ControlUnitService(topology, ControlUnitStore(path, unit_id=unit_id),
                                           tasks, Console(), peer=peer)
    return nodes, disconnected


def test_three_levels_forward_one_identity_and_only_leaf_creates_task(tmp_path):
    nodes, _ = cluster(tmp_path)
    request = ControlWorkRequest.model_validate(WORK)
    asyncio.run(nodes["R"].submit(request))
    asyncio.run(nodes["R"].submit(request))
    leaf = nodes["A1"]
    row = leaf.store.get("R", "job-1")
    assert row["local_task_id"] is None
    asyncio.run(leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=row["revision"]))
    task_id = leaf.store.get("R", "job-1")["local_task_id"]
    assert leaf.tasks.store.get_task(task_id)["actor_id"] == "operator-a1"
    assert len(leaf.tasks.store.history(task_id)) == 2
    asyncio.run(nodes["A"].refresh())
    asyncio.run(nodes["R"].refresh())
    assert nodes["R"].store.get("R", "job-1")["result"]["task_id"] == task_id
    for unit in ["R", "A"]:
        assert nodes[unit].store.list()[0]["local_task_id"] is None
    assert not nodes["B"].store.list()


def test_parent_cannot_approve_leaf_and_sibling_scope_is_refused(tmp_path):
    nodes, _ = cluster(tmp_path)
    asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(WORK)))
    with pytest.raises(ValueError, match="LOCAL"):
        asyncio.run(nodes["R"].approve("R", "job-1", actor_id="root-op", expected_revision=1))
    with pytest.raises(ValueError, match="SCOPE"):
        asyncio.run(nodes["B"].submit(ControlWorkRequest.model_validate(WORK)))
    incoming = ControlIngressRequest.model_validate(dict(WORK, origin_id="R", config_revision="v1"))
    with pytest.raises(ValueError, match="PARENT"):
        asyncio.run(nodes["A1"].receive(incoming, parent_id="R"))


def test_disconnected_parent_blocks_new_approval_then_cancel_closes_candidate(tmp_path):
    nodes, disconnected = cluster(tmp_path)
    asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(WORK)))
    leaf = nodes["A1"]
    row = leaf.store.get("R", "job-1")
    disconnected.add("A")
    with pytest.raises(ConnectionError):
        asyncio.run(leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=row["revision"]))
    assert leaf.store.get("R", "job-1")["local_actor"] is None
    asyncio.run(nodes["R"].cancel("R", "job-1"))
    disconnected.clear()
    asyncio.run(nodes["R"].refresh())
    asyncio.run(nodes["A"].refresh())
    assert leaf.store.get("R", "job-1")["status"] == "CANCELED"
    with pytest.raises(ValueError):
        asyncio.run(leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=row["revision"]))


def test_stale_approval_and_changed_identity_never_admit(tmp_path):
    nodes, _ = cluster(tmp_path)
    asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(WORK)))
    with pytest.raises(ValueError, match="REVISION"):
        asyncio.run(nodes["A1"].approve("R", "job-1", actor_id="operator-a1", expected_revision=99))
    with pytest.raises(ValueError, match="CONFLICT"):
        asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(dict(WORK, goal={"x": 4.0, "y": 2.0}))))


def test_active_recovery_does_not_starve_behind_recent_terminal_history(tmp_path):
    store = ControlUnitStore(tmp_path / "unit.db", unit_id="A")
    body = {"target_unit": "A", "robot_id": "a", "goal": {"x": 1.0, "y": 2.0}}
    store.create("A", "old", body, owner_unit="A", config_revision="v1")
    for index in range(105):
        identity = "done-" + str(index)
        store.create("A", identity, body, owner_unit="A", config_revision="v1")
        store.project("A", identity, owner_unit="A", owner_revision=1, status="COMPLETED", result={})
    assert [row["delegation_id"] for row in store.active()] == ["old"]


def test_active_capacity_preserves_retries_and_terminal_history(tmp_path):
    store = ControlUnitStore(tmp_path / "unit.db", unit_id="A")
    for index in range(256):
        store.create("A", str(index), {}, owner_unit="A", config_revision="v1")
    with pytest.raises(ValueError, match="CAPACITY"):
        store.create("A", "overflow", {}, owner_unit="A", config_revision="v1")
    assert store.create("A", "0", {}, owner_unit="A", config_revision="v1")["revision"] == 1
    store.project("A", "0", owner_unit="A", owner_revision=1, status="CANCELED", result={})
    store.create("A", "overflow", {}, owner_unit="A", config_revision="v1")
    assert len(store.active()) == 256


def test_disconnected_ancestor_also_blocks_leaf_admission(tmp_path):
    nodes, disconnected = cluster(tmp_path)
    asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(WORK)))
    disconnected.add("R")
    with pytest.raises((ValueError, ConnectionError)):
        asyncio.run(nodes["A1"].approve("R", "job-1", actor_id="operator-a1", expected_revision=1))
    assert nodes["A1"].store.get("R", "job-1")["local_task_id"] is None


@pytest.mark.parametrize("failure", ["refused", "timeout"])
def test_scoped_cancel_failure_marks_only_its_row_stale_and_recovery_continues(tmp_path, failure):
    import httpx
    from fleet.swarm.transport import RobotApiError
    nodes, _ = cluster(tmp_path)
    asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(WORK)))
    leaf = nodes["A1"]
    asyncio.run(leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=1))
    task_id = leaf.store.get("R", "job-1")["local_task_id"]
    operation = {"boot_id": "00000000-0000-0000-0000-000000000001",
                 "run_id": "00000000-0000-0000-0000-000000000002", "correlation_id": "attempt-1"}
    leaf.tasks.store.transition(task_id, "ACCEPTED", actor_id="core", source="operator",
                                receipt={"accepted": True, "operation": operation})
    async def failed_cancel(**scope):
        assert scope["run_id"] == operation["run_id"]
        if failure == "refused":
            raise RobotApiError("a1", 409, "NAVIGATION_SCOPE_CHANGED", "scope changed")
        raise httpx.ReadTimeout("test timeout")
    leaf.console._client = lambda robot: SimpleNamespace(navigation_cancel_scoped=failed_cancel)
    leaf.store.request_cancel("R", "job-1")
    leaf.store.create("A1", "later", WORK | {"target_unit": "A1"}, owner_unit="A1", config_revision="v1")
    leaf.store.request_cancel("A1", "later")
    asyncio.run(leaf.refresh())
    assert leaf.reply("R", "job-1")["stale"] is True
    assert leaf.store.get("A1", "later")["status"] == "CANCELED"


def test_cached_owner_projection_expires_and_fresh_reconciliation_restores_admission(tmp_path, monkeypatch):
    import fleet.server.control_unit_service as module
    now = [10.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0], raising=False)
    nodes, _ = cluster(tmp_path)
    asyncio.run(nodes["R"].submit(ControlWorkRequest.model_validate(WORK)))
    assert nodes["R"].reply("R", "job-1")["stale"] is False
    now[0] += 6
    assert nodes["R"].reply("R", "job-1")["stale"] is True
    with pytest.raises(ValueError):
        asyncio.run(nodes["A1"].approve("R", "job-1", actor_id="operator-a1", expected_revision=1))
    asyncio.run(nodes["R"].refresh())
    assert nodes["R"].reply("R", "job-1")["stale"] is False
    asyncio.run(nodes["A1"].approve("R", "job-1", actor_id="operator-a1", expected_revision=1))
    now[0] += 6
    assert nodes["A1"].reply("R", "job-1")["stale"] is True


def test_standalone_unit_admits_and_cancels_its_own_work_without_any_peer(tmp_path):
    from fleet.server.control_unit_service import ControlUnitService
    topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": [{"id": "A", "resources": ["robot:a"]}]})
    path = tmp_path / "standalone.db"
    tasks = FleetTaskService(FleetTaskStore(path), robot_ids={"a"})
    async def unexpected_peer(*args):
        raise AssertionError("standalone unit must not contact a peer")
    service = ControlUnitService(topology, ControlUnitStore(path, unit_id="A"), tasks, Console(), peer=unexpected_peer)
    work = ControlWorkRequest.model_validate(dict(WORK, target_unit="A", robot_id="a"))
    asyncio.run(service.submit(work))
    approved = asyncio.run(service.approve("A", "job-1", actor_id="operator-a", expected_revision=1))
    task_id = approved["delegation"]["local_task_id"]
    assert tasks.native_required(task_id)
    assert tasks.store.get_task(task_id)["status"] == "QUEUED"
    canceled = asyncio.run(service.cancel("A", "job-1"))
    assert canceled["delegation"]["status"] == "CANCELED"
    assert tasks.store.get_task(task_id)["status"] == "CANCELED"


def test_control_unit_arm_coordinator_preserves_depth_one_and_cell_admit_boundary(tmp_path):
    from pathlib import Path
    from fleet.server.arm_transfer_http import call_arm_transfer_domain, require_write_origin
    from fleet.server.control_unit_arm_coordinator import ControlUnitArmCoordinator

    app_py = Path(__file__).resolve().parents[1] / "fleet/server/app.py"
    assert len(app_py.read_text(encoding="utf-8").splitlines()) <= 480
    assert callable(require_write_origin) and callable(call_arm_transfer_domain)
    assert hasattr(ControlUnitArmCoordinator, "check_arm_admission")


def test_arm_relay_depth_two_projects_job_and_receipt_while_guarding_direct_child_hop(tmp_path):
    from contextlib import closing
    import sqlite3
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core_common.protocol.control_units import ControlArmIngressRequest, ControlArmWorkRequest
    from fleet.server.arm_transfer_relay_routes import delegation_id, install_arm_transfer_relay_routes
    from fleet.server.control_unit_arm_coordinator import ControlUnitArmCoordinator, is_direct_child_arm_owner
    from fleet.server.control_unit_service import ControlUnitService

    manifest = {"revision": "v1", "units": [
        {"id": "R"}, {"id": "A", "parent": "R"},
        {"id": "A1", "parent": "A", "resources": ["workcell:arm_a1"]}]}
    topology = ControlUnitTopology.from_mapping(manifest)
    digest = "a" * 64
    transfer = {"request_key": "harbor:move-depth2", "workcell_id": "arm_a1", "instance_id": "arm_a1",
                "object_ref": "box-1", "source": "slot-1", "target": "slot-2"}
    job_row = {"mission_id": "physical-1", "action_kind": "ARM_TRANSFER",
               "proposal_principal_id": "control-unit:A", "request_key": "control:depth2",
               "request_digest": digest, "proposal_digest": digest,
               "transfer": {k: v for k, v in transfer.items() if k != "request_key"},
               "resource_policy_digest": digest, "status": "GOAL_CONFIRMED",
               "authority_epoch": 1, "dispatch_generation": 1, "approved_by": "op-a1", "reason": None}
    receipt_row = {
        "receipt_id": "r-depth2", "mission_id": "physical-1", "action_id": "act-1",
        "attempt_id": "att-1", "request_digest": digest,
        "workcell_id": "arm_a1", "instance_id": "arm_a1",
        "policy_digest": digest, "evidence_digest": digest,
        "object_ref": "box-1", "source": "slot-1", "target": "slot-2",
        "authority_epoch": 1, "dispatch_generation": 1,
        "validated_at_ns": 2, "physical_status": "AT_TARGET_AND_CLEAR",
    }
    nodes, forwarded = {}, []

    class LeafJobs:
        def create(self, *, principal, request_key, request, bind=None):
            with closing(sqlite3.connect(tmp_path / "A1.db")) as conn, conn:
                conn.row_factory = sqlite3.Row
                bind(conn, "physical-1")
            return job_row

        def view(self, mission_id):
            return dict(job_row) if mission_id == "physical-1" else None

        def receipt(self, mission_id):
            return dict(receipt_row) if mission_id == "physical-1" else None

        def evidence(self, mission_id):
            return {"mission_id": mission_id, "evidence": {"status": "AT_TARGET_AND_CLEAR"}}

        def request_recheck(self, mission_id, key, *, principal_id=None):
            return {"mission_id": mission_id, "recheck_key": key, "principal_id": principal_id, "status": "QUEUED"}

        def read_recheck(self, mission_id, key):
            return {"mission_id": mission_id, "recheck_key": key, "status": "CONFIRMED"}

    for unit_id in ("R", "A", "A1"):
        path = tmp_path / (unit_id + ".db")
        tasks = FleetTaskService(FleetTaskStore(path), robot_ids=set())

        async def call_peer(unit, method, route, body=None, *, sender=unit_id):
            node = nodes[unit]
            if route == "inbox":
                return await node.receive(
                    ControlArmIngressRequest.model_validate(body),
                    parent_id=sender,
                    principal=SimpleNamespace(principal_id="control-unit:" + sender, role="service"))
            origin, identity = route.split("/")
            return await node.read(origin, identity, for_child=sender if method == "GET" else None)

        class Peer:
            def __init__(self, fn, sender_id):
                self._fn = fn
                self._sender = sender_id

            async def __call__(self, *args, **kwargs):
                return await self._fn(*args, **kwargs)

            async def arm_job(self, unit, method, origin, identity, tail, body=None):
                forwarded.append((unit, method, origin, identity, tail, body))
                node = nodes[unit]
                if not node.allow_intermediate_arm_hop and unit != "A1":
                    return 200, {"forwarded_to": unit, "tail": tail}
                kind, key = (
                    ("evidence", None) if tail == "physical-evidence"
                    else ("request_recheck", (body or {}).get("recheck_key")) if method == "POST" and tail == "rechecks"
                    else ("read_recheck", tail.split("/", 1)[1]))
                return 200, await node.arm_detail(origin, identity, kind, key=key,
                                                  principal_id="control-unit:" + self._sender)

        nodes[unit_id] = ControlUnitService(
            topology, ControlUnitStore(path, unit_id=unit_id), tasks, Console(),
            peer=Peer(call_peer, unit_id), arm_jobs=(lambda: LeafJobs()) if unit_id == "A1" else (lambda: None))

    harbor = SimpleNamespace(principal_id="harbor", role="service")
    app = FastAPI()
    install_arm_transfer_relay_routes(app, control=nodes["R"], require_viewer=lambda: harbor,
                                      require_proposer=lambda: harbor)
    client = TestClient(app)
    created = client.post("/api/fleet/arm-transfers/jobs", json=transfer)
    assert created.status_code == 200, created.text
    identity = delegation_id("harbor", transfer["request_key"])
    root_row = nodes["R"].store.get("R", identity)
    child_row = nodes["A"].store.get("R", identity)
    assert root_row["owner_unit"] == "A" and root_row["request"]["target_unit"] == "A1"
    assert not is_direct_child_arm_owner(root_row)
    assert is_direct_child_arm_owner(child_row)

    assert client.get("/api/fleet/arm-transfers/jobs/physical-1").status_code == 200
    receipt_res = client.get("/api/fleet/arm-transfers/jobs/physical-1/physical-receipt")
    assert receipt_res.status_code == 200 and receipt_res.json()["receipt"]["receipt_id"] == "r-depth2"

    ev_res = client.get("/api/fleet/arm-transfers/jobs/physical-1/physical-evidence")
    assert ev_res.status_code == 409 and ev_res.json()["detail"]["code"] == "ARM_TRANSFER_RELAY_DEPTH"
    rc_res = client.post("/api/fleet/arm-transfers/jobs/physical-1/rechecks", json={"recheck_key": "rk-1"})
    assert rc_res.status_code == 409 and rc_res.json()["detail"]["code"] == "ARM_TRANSFER_RELAY_DEPTH"
    assert forwarded == []

    with pytest.raises(ValueError, match="CONTROL_UNIT_ARM_JOB_NOT_BOUND"):
        asyncio.run(ControlUnitArmCoordinator(nodes["R"]).arm_detail("R", identity, "evidence"))
    hop = ControlUnitArmCoordinator(nodes["R"], allow_intermediate_hop=True)
    assert asyncio.run(hop.arm_detail("R", identity, "evidence")) == {
        "forwarded_to": "A", "tail": "physical-evidence"}
    assert forwarded == [("A", "GET", "R", identity, "physical-evidence", None)]

    forwarded.clear()
    for uid in ("R", "A"):
        nodes[uid] = ControlUnitService(
            topology, nodes[uid].store, nodes[uid].tasks, Console(),
            peer=nodes[uid].peer, arm_jobs=nodes[uid].arm_jobs, allow_intermediate_arm_hop=True)
        assert nodes[uid].allow_intermediate_arm_hop is True
    app = FastAPI()
    install_arm_transfer_relay_routes(app, control=nodes["R"], require_viewer=lambda: harbor,
                                      require_proposer=lambda: harbor)
    client = TestClient(app)
    ev_hop = client.get("/api/fleet/arm-transfers/jobs/physical-1/physical-evidence")
    assert ev_hop.status_code == 200 and ev_hop.json() == {
        "mission_id": "physical-1", "evidence": {"status": "AT_TARGET_AND_CLEAR"}}
    rc_hop = client.post("/api/fleet/arm-transfers/jobs/physical-1/rechecks", json={"recheck_key": "rk-1"})
    assert rc_hop.status_code == 200 and rc_hop.json() == {
        "mission_id": "physical-1", "recheck_key": "rk-1", "principal_id": "control-unit:A", "status": "QUEUED"}
    rc_read = client.get("/api/fleet/arm-transfers/jobs/physical-1/rechecks/rk-1")
    assert rc_read.status_code == 200 and rc_read.json() == {
        "mission_id": "physical-1", "recheck_key": "rk-1", "status": "CONFIRMED"}
    assert [(u, m, t) for u, m, _, _, t, _ in forwarded] == [
        ("A", "GET", "physical-evidence"), ("A1", "GET", "physical-evidence"),
        ("A", "POST", "rechecks"), ("A1", "POST", "rechecks"),
        ("A", "GET", "rechecks/rk-1"), ("A1", "GET", "rechecks/rk-1"),
    ]


