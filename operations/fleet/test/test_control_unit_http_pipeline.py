"""Actual HTTP producer/consumer chain with a lost ACK and durable restart."""

import asyncio

import httpx

from fleet.server.control_unit_runtime import ControlUnitConfig, ControlUnitPeer, ControlUnitPeers
from fleet.server.control_unit_service import ControlUnitService
from fleet.server.control_unit_store import ControlUnitStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_control_unit_routes import client_for
from test_control_unit_service import cluster, WORK


def test_nested_http_pipeline_survives_lost_reply_and_leaf_restart_without_new_task(tmp_path):
    async def exercise():
        nodes, _ = cluster(tmp_path)
        apps = {unit: client_for(nodes, unit).app for unit in nodes}
        drop = {"A1"}
        calls = []

        class Network(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                unit = request.url.host.upper()
                calls.append((unit, request.method, request.url.path))
                response = await httpx.ASGITransport(app=apps[unit]).handle_async_request(request)
                if unit in drop and request.url.path.endswith("/inbox"):
                    drop.remove(unit)
                    await response.aclose()
                    raise httpx.ReadError("reply lost after durable inbox commit")
                return response

        async with httpx.AsyncClient(transport=Network()) as network:
            for unit, node in nodes.items():
                neighbors = {u.unit_id for u in node.topology.units.values() if u.parent == unit}
                if node.unit.parent:
                    neighbors.add(node.unit.parent)
                config = ControlUnitConfig(unit, node.topology,
                    {peer: ControlUnitPeer("http://" + peer, "peer-" + unit) for peer in neighbors})
                node.peer = ControlUnitPeers(config, network)
            operator = {"Authorization": "Bearer op-token"}
            submitted = await network.post("http://R/api/fleet/control-unit/delegations", headers=operator, json=WORK)
            assert submitted.status_code == 200 and submitted.json()["stale"]
            await nodes["R"].refresh()
            assert len(nodes["A1"].store.list()) == 1
            approved = await network.post("http://A1/api/fleet/control-unit/delegations/R/job-1/approve",
                                           headers=operator, json={"expected_revision": 1})
            assert approved.status_code == 200, approved.text
            task_id = approved.json()["delegation"]["local_task_id"]
            old = nodes["A1"]
            tasks = FleetTaskService(FleetTaskStore(old.store.path), robot_ids={"a1"})
            restarted = ControlUnitService(old.topology, ControlUnitStore(old.store.path, unit_id="A1"),
                                            tasks, old.console, peer=old.peer)
            nodes["A1"] = restarted
            apps["A1"] = client_for(nodes, "A1").app
            await nodes["R"].refresh()
            replay = await network.post("http://R/api/fleet/control-unit/delegations", headers=operator, json=WORK)
            assert replay.json()["delegation"]["result"]["task_id"] == task_id
            assert restarted.store.get("R", "job-1")["local_task_id"] == task_id
            assert tasks.native_required(task_id) is True
            assert tasks.store.get_task(task_id)["actor_id"] == "operator-A1"
            assert all(host != "B" for host, _, _ in calls)
            assert tasks.store.dispatch_control()["dispatch_enabled"] is False
    asyncio.run(exercise())
