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
