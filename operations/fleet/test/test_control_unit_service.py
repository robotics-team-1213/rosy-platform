"""Control-unit orchestration uses the real durable Fleet task admission path."""

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
            return node.reply(origin, identity)

        nodes[unit_id] = ControlUnitService(topology, ControlUnitStore(path, unit_id=unit_id),
                                           tasks, Console(), peer=peer)
    return nodes, disconnected


@pytest.mark.asyncio
async def test_three_levels_forward_one_identity_and_only_leaf_creates_task(tmp_path):
    nodes, _ = cluster(tmp_path)
    request = ControlWorkRequest.model_validate(WORK)
    await nodes["R"].submit(request)
    await nodes["R"].submit(request)
    leaf = nodes["A1"]
    row = leaf.store.get("R", "job-1")
    assert row["local_task_id"] is None
    await leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=row["revision"])
    task_id = leaf.store.get("R", "job-1")["local_task_id"]
    assert leaf.tasks.store.get_task(task_id)["actor_id"] == "operator-a1"
    assert len(leaf.tasks.store.history(task_id)) == 2
    await nodes["R"].refresh()
    assert nodes["R"].store.get("R", "job-1")["result"]["task_id"] == task_id
    for unit in ["R", "A", "B"]:
        assert nodes[unit].store.list()[0]["local_task_id"] is None if unit != "B" else not nodes[unit].store.list()


@pytest.mark.asyncio
async def test_parent_cannot_approve_leaf_and_sibling_scope_is_refused(tmp_path):
    nodes, _ = cluster(tmp_path)
    await nodes["R"].submit(ControlWorkRequest.model_validate(WORK))
    with pytest.raises(ValueError, match="LOCAL"):
        await nodes["R"].approve("R", "job-1", actor_id="root-op", expected_revision=1)
    with pytest.raises(ValueError, match="SCOPE"):
        await nodes["B"].submit(ControlWorkRequest.model_validate(WORK))
    incoming = ControlIngressRequest.model_validate(dict(WORK, origin_id="R", config_revision="v1"))
    with pytest.raises(ValueError, match="PARENT"):
        await nodes["A1"].receive(incoming, parent_id="R")


@pytest.mark.asyncio
async def test_disconnected_parent_blocks_new_approval_then_cancel_closes_candidate(tmp_path):
    nodes, disconnected = cluster(tmp_path)
    await nodes["R"].submit(ControlWorkRequest.model_validate(WORK))
    leaf = nodes["A1"]
    row = leaf.store.get("R", "job-1")
    disconnected.add("A")
    with pytest.raises(ConnectionError):
        await leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=row["revision"])
    assert leaf.store.get("R", "job-1")["local_actor"] is None
    await nodes["R"].cancel("R", "job-1")
    disconnected.clear()
    await nodes["R"].refresh()
    await nodes["A"].refresh()
    assert leaf.store.get("R", "job-1")["status"] == "CANCELED"
    with pytest.raises(ValueError):
        await leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=row["revision"])


@pytest.mark.asyncio
async def test_stale_approval_and_changed_identity_never_admit(tmp_path):
    nodes, _ = cluster(tmp_path)
    await nodes["R"].submit(ControlWorkRequest.model_validate(WORK))
    with pytest.raises(ValueError, match="REVISION"):
        await nodes["A1"].approve("R", "job-1", actor_id="operator-a1", expected_revision=99)
    with pytest.raises(ValueError, match="CONFLICT"):
        await nodes["R"].submit(ControlWorkRequest.model_validate(dict(WORK, goal={"x": 4.0, "y": 2.0})))


def test_active_recovery_does_not_starve_behind_recent_terminal_history(tmp_path):
    store = ControlUnitStore(tmp_path / "unit.db", unit_id="A")
    body = {"target_unit": "A", "robot_id": "a", "goal": {"x": 1.0, "y": 2.0}}
    store.create("A", "old", body, owner_unit="A", config_revision="v1")
    for index in range(105):
        identity = "done-" + str(index)
        store.create("A", identity, body, owner_unit="A", config_revision="v1")
        store.project("A", identity, owner_unit="A", owner_revision=1, status="COMPLETED", result={})
    assert [row["delegation_id"] for row in store.active()] == ["old"]
