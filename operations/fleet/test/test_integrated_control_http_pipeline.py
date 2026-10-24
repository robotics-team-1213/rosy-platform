"""Synthetic four-node HTTP/ASGI proof; no CORE, OMX, devices, TCP or TLS acceptance."""

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import sqlite3
import time
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from fleet.server.control_stop_store import ControlStopStore
from fleet.server.control_unit_collection import ControlUnitCollection
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_information import LocalControlInformation
from fleet.server.control_unit_information_routes import install_control_information_routes
from fleet.server.control_unit_runtime import ControlUnitConfig, ControlUnitPeer, ControlUnitPeers
from fleet.server.control_unit_stop_routes import install_control_stop_routes
from fleet.server.control_unit_stops import ControlUnitStops
from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap


PREFIX = "/api/fleet/control-unit"
UNITS = ("R", "A", "A1", "B")
MANIFEST = {"revision": "v1", "units": [
    {"id": "R", "resources": ["robot:r"]},
    {"id": "A", "parent": "R", "resources": ["robot:a"]},
    {"id": "A1", "parent": "A", "resources": ["robot:a1"]},
    {"id": "B", "parent": "R", "resources": ["robot:b"]},
]}


def auth(token):
    return {"Authorization": "Bearer " + token}


def edge(sender, receiver):
    return "synthetic-edge-" + sender + "-to-" + receiver


class SharedSnapshot:
    """Fake SharedGather with actual process clocks and one immutable raw state per read."""
    def __init__(self, unit):
        self.unit, self.gathered_at, self.reads = unit, 0.0, 0

    async def __call__(self):
        self.reads += 1
        self.gathered_at = time.time()
        return {"robots": [{"robot_id": self.unit.lower(), "online": True,
                            "_state_mono": time.monotonic(), "gather_source": "hub",
                            "state": {"mode": "IDLE", "map_id": "map-" + self.unit,
                                      "pose": {"x": 1.0, "y": 2.0, "yaw": 0.0},
                                      "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                                      "battery": {"percent": 75.0}, "safety": {"estop": False},
                                      "evidence": {channel: {"evidence": "fresh"}
                                                   for channel in ("pose", "battery", "safety")}}}]}


class Cluster:
    def __init__(self, tmp_path):
        self.path, self.topology = tmp_path, ControlUnitTopology.from_mapping(MANIFEST)
        self.nodes, self.apps, self.calls = {}, {}, []
        self.down, self.drop_reply, self.overrides = set(), set(), {}
        self.stop_calls = {unit: [] for unit in UNITS}
        self.stop_modes, self.gates = {}, {}
        self.network = httpx.AsyncClient(transport=self.Transport(self), trust_env=False)
        for unit in UNITS:
            neighbors = {other.unit_id for other in self.topology.units.values() if other.parent == unit}
            parent = self.topology.unit(unit).parent
            if parent:
                neighbors.add(parent)
            config = ControlUnitConfig(unit, self.topology, {
                peer: ControlUnitPeer("http://" + peer, edge(unit, peer)) for peer in neighbors},
                share_information_with_parent=True, accept_parent_stop=True)
            assert {edge(unit, peer) for peer in neighbors}.isdisjoint(edge(peer, unit) for peer in neighbors)
            store = FleetTaskStore(tmp_path / (unit + ".sqlite3"))
            for robot_id in (unit.lower(), "foreign"):
                store.create_task(task_id="task-" + unit + "-" + robot_id, robot_id=robot_id,
                                  task_type="navigate", source="operator", actor_id="private-actor",
                                  request_key=robot_id, request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}},
                                  evidence={"private": "metadata"})
            self.build(unit, config, store)

    class Transport(httpx.AsyncBaseTransport):
        def __init__(self, cluster):
            self.cluster = cluster

        async def handle_async_request(self, request):
            cluster, destination = self.cluster, request.url.host.upper()
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            sender = next((unit for unit in UNITS if bearer == edge(unit, destination)), "human")
            cluster.calls.append((sender, destination, request.method, request.url.path))
            if destination in cluster.down:
                raise httpx.ConnectError("synthetic disconnected unit", request=request)
            response = await httpx.ASGITransport(app=cluster.apps[destination]).handle_async_request(request)
            if destination in cluster.drop_reply and request.url.path == PREFIX + "/stop-inbox":
                cluster.drop_reply.remove(destination)
                await response.aclose()
                raise httpx.ReadError("synthetic reply loss after durable execution", request=request)
            override = cluster.overrides.get((destination, request.url.path))
            if override is not None and response.status_code == 200:
                body = response.json() if response.is_stream_consumed else None
                if body is None:
                    await response.aread()
                    body = response.json()
                await response.aclose()
                return httpx.Response(200, json=override(body), request=request)
            return response

    def build(self, unit, config, task_store):
        tasks = FleetTaskService(task_store, robot_ids={unit.lower()})
        journal = ControlStopStore(task_store, unit_id=unit, config_revision=self.topology.revision)
        journal.recover()
        peer = ControlUnitPeers(config, self.network)
        gather = SharedSnapshot(unit)
        model = SiteMap.model_validate({"map_id": "map-" + unit,
            "places": [{"id": "start", "name": unit + " start", "x": 0.0, "y": 0.0},
                       {"id": "end", "name": unit + " end", "x": 1.0, "y": 1.0}],
            "edges": [{"id": "lane", "from": "start", "to": "end",
                       "polyline": [[0.0, 0.0], [1.0, 1.0]], "width_m": 0.4, "speed_cap_mps": 0.2}]})
        local = LocalControlInformation(config, gather=gather, tasks=task_store,
                                        map_snapshot=lambda: (1, model, None, None), clock=time.monotonic,
                                        sampled_at=lambda: gather.gathered_at, pending_stops=journal.pending_count)
        collection = ControlUnitCollection(config, local, peer)

        async def local_stop(dispatch, actor):
            self.stop_calls[unit].append((dispatch, actor))
            with task_store._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM fleet_control_stop_deliveries").fetchone()[0] > 0
            if unit in self.gates:
                started, release = self.gates[unit]
                started.set()
                await release.wait()
            if self.stop_modes.get(unit) == "unknown":
                return {"robots": [], "omx_local_stop": {"state": "UNKNOWN"}}
            return {"robots": [{"robot_id": unit.lower(), "stopped": True}],
                    "omx_local_stop": {"state": "NOT_CONFIGURED"}}

        stops = ControlUnitStops(config, journal, peer, local_stop)
        principals = {sha256(token.encode()).hexdigest(): SitePrincipal(identity, role)
                      for token, identity, role in [
                          ("operator-" + unit, "named-" + unit, "operator"),
                          ("viewer-" + unit, "reader-" + unit, "viewer"),
                          ("ai-" + unit, "observer-" + unit, "ai_observer")]
                      + [(edge(other, unit), "control-unit:" + other, "service") for other in config.peers]}
        authorize = build_authorize(None, principals, tasks)
        viewer, _, named, _ = build_role_guards(authorize, principals)
        app = FastAPI()
        install_control_information_routes(app, collection, authorize=authorize, require_viewer=viewer)
        install_control_stop_routes(app, stops, authorize=authorize, require_viewer=viewer,
                                    require_named_operator=named)
        self.nodes[unit] = SimpleNamespace(config=config, tasks=tasks, journal=journal,
                                           collection=collection, stops=stops, gather=gather)
        self.apps[unit] = app

    async def restart(self, unit):
        old = self.nodes[unit]
        await old.stops.aclose()
        self.build(unit, old.config, FleetTaskStore(old.tasks.store.path))

    async def warm(self):
        for unit in ("A1", "A", "B", "R"):
            await self.nodes[unit].collection.refresh()

    def body(self, target="R", identity="stop-1"):
        scope = {target}
        for unit in UNITS:
            if unit != target:
                try:
                    self.topology.next_hop(target, unit)
                except ValueError:
                    continue
                scope.add(unit)
        return dict(stop_id=identity, target_unit=target, config_revision="v1", expected_controls={
            unit: {key: self.nodes[unit].tasks.store.dispatch_control()[key]
                   for key in ("authority_epoch", "generation")} for unit in sorted(scope)})

    async def get(self, unit, suffix, token=None):
        return await self.network.get("http://" + unit + PREFIX + "/" + suffix,
                                      headers=auth(token or "viewer-" + unit))

    async def post(self, unit, suffix, body, token=None):
        return await self.network.post("http://" + unit + PREFIX + "/" + suffix, json=body,
                                       headers=auth(token or "operator-" + unit))

    async def close(self):
        for _, release in self.gates.values():
            release.set()
        await asyncio.gather(*(node.stops.aclose() for node in self.nodes.values()))
        await self.network.aclose()


@asynccontextmanager
async def cluster(tmp_path):
    value = Cluster(tmp_path)
    try:
        yield value
    finally:
        await value.close()


def remote_posts(cluster):
    return [(source, target) for source, target, method, path in cluster.calls
            if source != "human" and method == "POST" and path == PREFIX + "/stop-inbox"]


def test_nested_producer_collection_http_keeps_unit_robot_task_and_map_ownership(tmp_path):
    async def exercise():
        async with cluster(tmp_path) as c:
            await c.warm()
            overview = await c.get("R", "overview")
            assert overview.status_code == 200, overview.text
            rows = {row["unit_id"]: row for row in overview.json()["units"]}
            assert set(rows) == set(UNITS) and all(row["availability"] == "AVAILABLE" for row in rows.values())
            assert all(row["tasks_active"] == 1 and row["robots_total"] == 1 for row in rows.values())
            assert all(row["sampled_at"].endswith("Z") or "+00:00" in row["sampled_at"] for row in rows.values())
            detail = await c.get("R", "units/A1")
            assert detail.status_code == 200, detail.text
            assert detail.json()["unit_id"] == "A1" and detail.json()["config_revision"] == "v1"
            assert [row["robot_id"] for row in detail.json()["robots"]] == ["a1"]
            assert [row["task_id"] for row in detail.json()["tasks"]] == ["task-A1-a1"]
            assert "private" not in detail.text and "foreign" not in detail.text
            geometry = await c.get("R", "units/A1/map")
            assert geometry.status_code == 200 and geometry.json()["unit_id"] == "A1"
            assert geometry.json()["map"] == {"map_id": "map-A1", "version": 1, "frame": "unit_local"}
            assert ("R", "A", "GET", PREFIX + "/units/A1") in c.calls
            assert ("A", "A1", "GET", PREFIX + "/units/A1") in c.calls
            assert all(source != "R" or target != "A1" for source, target, _, _ in c.calls)
            assert (await c.get("A", "units/B", edge("R", "A"))).status_code == 404
            assert (await c.get("A", "overview", edge("R", "B"))).status_code == 401
            assert (await c.get("A1", "overview", edge("R", "A"))).status_code == 401
            assert (await c.get("R", "overview", edge("B", "R"))).status_code == 403
    asyncio.run(exercise())


def test_parent_information_and_stop_require_opt_in_and_directional_credentials(tmp_path):
    async def exercise():
        async with cluster(tmp_path) as c:
            node = c.nodes["A"]
            default = ControlUnitConfig(node.config.unit_id, node.config.topology, node.config.peers)
            assert default.share_information_with_parent is default.accept_parent_stop is False
            node.collection.config = node.stops.config = default
            assert edge("R", "A") != edge("R", "B") != edge("A", "R")
            assert edge("A", "A1") != edge("R", "A")
            assert (await c.get("A", "overview", edge("R", "A"))).status_code == 403
            body = c.body("A") | {"origin_id": "R"}
            assert (await c.post("A", "stop-inbox", body, edge("R", "A"))).status_code == 403
            assert (await c.get("A", "overview", "viewer-A")).status_code == 200
            assert all(not calls for calls in c.stop_calls.values())
    asyncio.run(exercise())


def test_partial_information_failure_and_spoofed_projection_preserve_other_units(tmp_path):
    async def exercise():
        async with cluster(tmp_path) as c:
            await c.warm()
            c.down.add("A")
            await c.nodes["R"].collection.refresh()
            rows = {row["unit_id"]: row for row in (await c.get("R", "overview")).json()["units"]}
            assert rows["A"]["availability"] == rows["A1"]["availability"] == "STALE"
            assert rows["B"]["availability"] == rows["R"]["availability"] == "AVAILABLE"
            assert rows["A"]["dispatch"] is None and rows["B"]["dispatch"] is not None
            c.down.clear()
            c.overrides[("B", PREFIX + "/overview")] = lambda body: body | {"config_revision": "wrong"}
            await c.nodes["R"].collection.refresh()
            rows = {row["unit_id"]: row for row in c.nodes["R"].collection.overview().model_dump(mode="json")["units"]}
            assert rows["B"]["availability"] == "STALE" and rows["A1"]["availability"] == "AVAILABLE"
            c.overrides[("B", PREFIX + "/units/B")] = lambda body: body | {"robots": [
                body["robots"][0] | {"robot_id": "a1"}]}
            assert (await c.get("R", "units/B")).status_code == 503
            c.overrides[("B", PREFIX + "/units/B/map")] = lambda body: body | {"unit_id": "A"}
            assert (await c.get("R", "units/B/map")).status_code == 503
    asyncio.run(exercise())


@pytest.mark.parametrize("restart_unit", ["R", "A", "A1"])
def test_targeted_stop_lost_reply_restart_uses_get_only_and_keeps_identity(tmp_path, restart_unit):
    async def exercise():
        async with cluster(tmp_path) as c:
            body = c.body("A")
            c.drop_reply.add("A")
            response = await c.post("R", "stops", body)
            assert response.status_code == 200, response.text
            assert remote_posts(c) == [("R", "A"), ("A", "A1")]
            assert {row["unit_id"] for row in response.json()["results"]} == {"A", "A1"}
            assert any(row["state"] == "UNKNOWN" for row in response.json()["results"])
            assert [len(c.stop_calls[unit]) for unit in UNITS] == [0, 1, 1, 0]
            await c.restart(restart_unit)
            c.calls.clear()
            readback = await c.get("R", "stops/R/stop-1")
            assert readback.status_code == 200, readback.text
            assert all(row["state"] == "ACKNOWLEDGED" and row["physical_stop"] == "UNVERIFIED"
                       for row in readback.json()["results"])
            assert remote_posts(c) == []
            assert ("R", "A", "GET", PREFIX + "/stops/R/stop-1") in c.calls
            assert ("A", "A1", "GET", PREFIX + "/stops/R/stop-1") in c.calls
            for unit in ("A", "A1"):
                store = c.nodes[unit].tasks.store
                store.rearm_dispatch(expected_generation=store.dispatch_control()["generation"],
                                     actor_id="named-" + unit)
            duplicate = await c.post("R", "stops", body)
            assert duplicate.status_code == 200 and remote_posts(c) == []
            assert [len(c.stop_calls[unit]) for unit in UNITS] == [0, 1, 1, 0]
            conflict = body | {"expected_controls": c.body("A")["expected_controls"]}
            assert (await c.post("R", "stops", conflict)).status_code == 409
            assert (await c.get("A", "stops", "viewer-A")).status_code == 200
            assert (await c.get("A", "stops", "ai-A")).status_code == 403
            assert (await c.get("A", "stops", edge("R", "A"))).status_code == 403
    asyncio.run(exercise())


def test_journal_failure_before_claim_causes_no_local_or_child_fanout(tmp_path, monkeypatch):
    async def exercise():
        async with cluster(tmp_path) as c:
            def unavailable(*args, **kwargs):
                raise sqlite3.OperationalError("private database path")

            monkeypatch.setattr(c.nodes["R"].journal, "claim", unavailable)
            response = await c.post("R", "stops", c.body())
            assert response.status_code == 503 and "private" not in response.text
            assert remote_posts(c) == [] and all(not calls for calls in c.stop_calls.values())
    asyncio.run(exercise())


def test_partial_stop_child_does_not_erase_successful_independent_units(tmp_path):
    async def exercise():
        async with cluster(tmp_path) as c:
            c.down.add("A")
            response = await c.post("R", "stops", c.body())
            assert response.status_code == 200, response.text
            rows = {row["unit_id"]: row for row in response.json()["results"]}
            assert rows["R"]["state"] == rows["B"]["state"] == "ACKNOWLEDGED"
            assert rows["A"]["state"] == rows["A1"]["state"] == "UNKNOWN"
            assert [len(c.stop_calls[unit]) for unit in UNITS] == [1, 0, 0, 1]
            assert all(row["physical_stop"] == "UNVERIFIED" for row in rows.values())
    asyncio.run(exercise())


def test_unknown_local_stop_blocks_rearm_and_only_named_local_attestation_reconciles(tmp_path):
    async def exercise():
        async with cluster(tmp_path) as c:
            c.stop_modes["A1"] = "unknown"
            response = await c.post("R", "stops", c.body("A1"))
            assert response.status_code == 200 and response.json()["results"][0]["state"] == "UNKNOWN"
            await c.warm()
            rows = {row["unit_id"]: row for row in (await c.get("R", "overview")).json()["units"]}
            assert rows["R"]["stop_pending"] == rows["A"]["stop_pending"] == rows["A1"]["stop_pending"] == 1
            assert rows["B"]["stop_pending"] == 0
            store = c.nodes["A1"].tasks.store
            generation = store.dispatch_control()["generation"]
            with pytest.raises(ValueError):
                store.rearm_dispatch(expected_generation=generation, actor_id="named-A1")
            body = dict(expected_generation=generation, receiver_channels_terminated=True,
                        receivers_recommissioned=True, affected_units=["A1"],
                        evidence="Synthetic named operator recommissioning attestation")
            suffix = "stops/R/stop-1/reconcile"
            assert (await c.post("A1", suffix, body, "viewer-A1")).status_code == 403
            assert (await c.post("A1", suffix, body, edge("A", "A1"))).status_code == 403
            assert (await c.post("R", suffix, body)).status_code == 409
            assert (await c.post("A1", suffix, body | {"receivers_recommissioned": False})).status_code == 422
            reconciled = await c.post("A1", suffix, body)
            assert reconciled.status_code == 200, reconciled.text
            assert reconciled.json()["results"][0]["state"] == "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"
            assert store.dispatch_control()["generation"] == generation
            assert not store.dispatch_control()["dispatch_enabled"]
            observed = await c.get("R", "stops/R/stop-1")
            assert observed.json()["results"][0]["state"] == "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"
            await c.warm()
            assert all(row["stop_pending"] == 0 for row in (await c.get("R", "overview")).json()["units"])
            store.rearm_dispatch(expected_generation=generation, actor_id="named-A1")
            assert len(c.stop_calls["A1"]) == 1
    asyncio.run(exercise())


def test_live_local_send_cannot_be_overridden_by_reconciliation_http(tmp_path):
    async def exercise():
        async with cluster(tmp_path) as c:
            started, release = asyncio.Event(), asyncio.Event()
            c.gates["A1"] = started, release
            pending = asyncio.create_task(c.post("A1", "stops", c.body("A1")))
            assert await asyncio.wait_for(started.wait(), 3.0) is True
            store = c.nodes["A1"].tasks.store
            generation = store.dispatch_control()["generation"]
            body = dict(expected_generation=generation, receiver_channels_terminated=True,
                        receivers_recommissioned=True, affected_units=["A1"],
                        evidence="Synthetic attestation while a send is still alive")
            refused = await c.post("A1", "stops/A1/stop-1/reconcile", body)
            assert refused.status_code == 409
            with pytest.raises(ValueError):
                store.rearm_dispatch(expected_generation=generation, actor_id="named-A1")
            release.set()
            assert (await pending).status_code == 200
            assert len(c.stop_calls["A1"]) == 1
    asyncio.run(exercise())
