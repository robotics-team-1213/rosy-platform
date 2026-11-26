"""Fleet routes to the selected staging place and CORE executes its commissioned rear dock."""
from __future__ import annotations

import asyncio
import math
from uuid import UUID

from core_common.protocol.evidence import STALE_POSE_S
from core_common.protocol.native_operation import NativeOperation
from fleet.server.channel.execution.outcomes.evidence import safe_proof
from fleet.server.ledger.berth_parking_helpers import BAY_DOCK_SPECS
from fleet.server.trip_ports import TripError
from fleet.hub.hub import HubError
from fleet.swarm.dispatch_guard import dispatch_guard


def rear_bay(graph, destination):
    place = graph.places.get(destination) if isinstance(destination, str) else None
    spec = BAY_DOCK_SPECS.get(destination) if place is not None and place.kind == "charge" else None
    if spec is None:
        return None
    staging = spec["staging_place_id"]
    if staging not in graph.places or not any(
            (arc.start_place, arc.end_place) == (staging, destination) for arc in graph.arcs.values()):
        raise TripError(422, "CHARGE_BAY_APPROACH_UNAVAILABLE", {"bay_id": destination, "staging_place_id": staging})
    return {"bay_id": destination, "staging_place_id": staging, "dock_id": spec["dock_id"],
            "owner": "core_docking", "terminal_motion": "rear_dock"}


class RearBayPort:
    def __init__(self, console, unresolved=()):
        self.console = console
        self.claims = {}
        for trip in unresolved:
            info = trip["detail"].get("parking_handoff") or {}
            if info.get("phase") in {"submitting", "docking"} and info.get("claim"):
                self.claims[trip["robot_id"]] = info["claim"]
        console.rear_bay_claims = self.claims

    def client(self, robot):
        client = self.console.clients().get(robot)
        if client is None:
            raise TripError(409, "CHARGE_BAY_OWNER_UNAVAILABLE")
        return client

    async def target(self, robot, info):
        client = self.client(robot)
        docks = await client._get("/api/v1/docking/docks")
        dock = next((d for d in docks.get("docks", []) if d.get("id") == info["dock_id"]), None)
        if not dock or not all(type(dock.get(k)) in (int, float) and math.isfinite(dock[k]) for k in ("x", "y", "yaw")):
            raise TripError(409, "CHARGE_BAY_TARGET_NOT_TAUGHT", info)
        types = await client._get("/api/v1/docking/types")
        kind = next((d for d in types.get("types", []) if d.get("name") == dock.get("type")), {})
        if kind.get("approach") not in ("line", "rear"):
            raise TripError(409, "CHARGE_BAY_REAR_TYPE_REQUIRED", info)
        offset = kind.get("staging_offset_m")
        if type(offset) not in (int, float) or not math.isfinite(offset) or offset <= 0:
            raise TripError(409, "CHARGE_BAY_REAR_TYPE_REQUIRED", info)
        return dock, offset

    async def clearance(self, runner, live, client, info, target, offset):
        from fleet.server.handoff_traffic import _inside_corridor, read_peers, site_corridor
        robot = live.view["robot_id"]
        stop = self.console.goal_leases.stop_token(robot)
        started = runner._clock()
        other_ids = set(self.console.robot_ids) - {robot}
        versions = self.console.goal_leases.peer_wire_state(other_ids)
        snapshot, peers = await asyncio.gather(client.state(), read_peers(self.console, robot))
        store = runner._store
        active = store.active()
        site = active[1].map_id, live.view["map_version"]
        fit, _reason = store.map_bindings.matching_fit(robot, snapshot, site)
        if (active[0] != site[1] or fit is None or (store.map_bindings.active(robot) or {}).get("binding_id")
                != live.view["detail"].get("nav2_binding_id")):
            raise TripError(409, "CHARGE_BAY_TARGET_FRAME_UNVERIFIED")
        goal = target["x"], target["y"]
        staging = goal[0] - offset * math.cos(target["yaw"]), goal[1] - offset * math.sin(target["yaw"])
        binding = {"site_map_id": site[0], "site_map_version": site[1]}
        site_corridor(self.console, robot, snapshot, binding, None, goal, peers, route=[staging])
        native = [(snapshot["pose"]["x"], snapshot["pose"]["y"]), staging, goal]
        route = (site[0], [fit.apply(point) for point in native])
        nearest = min((p for p in live.graph.places.values() if p.kind == "charge"),
                      key=lambda p: math.dist(route[1][-1], (p.x, p.y)))
        approach = next((arc for arc in live.graph.arcs.values() if (arc.start_place, arc.end_place)
                         == (info["staging_place_id"], info["bay_id"])), None)
        if (nearest.id != info["bay_id"] or approach is None
                or not _inside_corridor(route[1], approach.polyline, approach.width_m / 2 - fit.max)):
            raise TripError(409, "CHARGE_BAY_TAUGHT_POSE_MISMATCH")
        blocker, _ = self.console._claim_blocker(robot, native, site_route=route)
        if blocker is not None:
            raise TripError(409, "CHARGE_BAY_ROUTE_OCCUPIED", {"robot_id": blocker})
        if (self.console.goal_leases.stop_token(robot) != stop or runner._clock() - started > STALE_POSE_S
                or self.console.clients().get(robot) is not client or runner.bay_cable_inhibited(robot)):
            raise TripError(409, "CHARGE_BAY_ADMISSION_CHANGED")
        def clear_at_wire():
            if (set(self.console.robot_ids) - {robot} != other_ids or any(count for _, count in versions.values())
                    or self.console.goal_leases.peer_wire_state(other_ids) != versions
                    or runner._clock() - started > STALE_POSE_S):
                raise TripError(409, "CHARGE_BAY_PEER_CHANGED")
            if self.console._claim_blocker(robot, native, site_route=route)[0] is not None:
                raise TripError(409, "CHARGE_BAY_ROUTE_OCCUPIED")
            site_corridor(self.console, robot, snapshot, binding, None, goal, peers, route=[staging])
        clear_at_wire()
        return snapshot, route, clear_at_wire

    async def step(self, runner, live):
        info = live.view["detail"]["parking_handoff"]
        robot, plan_id = live.view["robot_id"], live.view["trip_id"]
        client = self.client(robot)
        if info["phase"] in {"staging_confirmed", "waiting_for_commission", "waiting_for_clearance"}:
            if runner._clock() < info.get("next_check_at", 0):
                return
            try:
                target, offset = await self.target(robot, info)
            except TripError as exc:
                if exc.code not in {"CHARGE_BAY_TARGET_NOT_TAUGHT", "CHARGE_BAY_REAR_TYPE_REQUIRED"}:
                    raise
                info.update(phase="waiting_for_commission", reason=exc.code, next_check_at=runner._clock() + 3)
                return
            pose = await runner._progress_pose(live, robot)
            view = await client.docking_status()
            if view.get("operation_cancel_supported") is not True:
                info.update(phase="waiting_for_commission", reason="CHARGE_BAY_SCOPED_CANCEL_UNSUPPORTED",
                            next_check_at=runner._clock() + 3)
                return
            try:
                snapshot, route, clear_at_wire = await self.clearance(runner, live, client, info, target, offset)
            except (TripError, HubError) as exc:
                reason = str(exc) if isinstance(exc, HubError) else exc.code
                info.update(phase="waiting_for_clearance", reason=reason, next_check_at=runner._clock() + 1)
                return
            state_map, grid = snapshot.get("map_id"), snapshot.get("map_grid_id")
            epoch = (target.get("metadata") or {}).get("map_epoch")
            if (not grid or not state_map or target.get("map_id") not in (state_map, grid)
                    or (epoch is not None and epoch not in (grid, state_map))):
                raise TripError(409, "CHARGE_BAY_TARGET_FRAME_UNVERIFIED", {"dock_id": info["dock_id"]})
            sx, sy = live.graph.place_xy(info["staging_place_id"])
            velocity = snapshot.get("velocity") or {}
            if (pose is None or pose.state != "LOCALIZED" or math.dist((pose.x, pose.y), (sx, sy)) > runner.config.arrive_free_m
                    or velocity.get("linear") != 0 or velocity.get("angular") != 0
                    or snapshot.get("navigation") not in ("IDLE", "ARRIVED")
                    or (snapshot.get("line_follow") or {}).get("mode") != "OFF"):
                raise TripError(409, "CHARGE_BAY_STAGING_STOP_UNVERIFIED")
            owner = view.get("owner") or {}
            if owner.get("owner_run_id", "unknown") is not None or type(owner.get("owner_generation")) is not int:
                raise TripError(409, "CHARGE_BAY_DOCK_OWNER_BUSY")
            # The last asynchronous read precedes the local stop fence and the native owner compare-and-set.
            if not live.open:
                return
            runner._check_human_hold()
            runner._graph_for(live.view["map_version"])
            info.pop("reason", None)
            info.pop("next_check_at", None)
            token = self.console.goal_leases.stop_token(robot)
            def check():
                try:
                    clear_at_wire()
                    if (not live.open or self.console.goal_leases.stop_token(robot) != token or runner.bay_cable_inhibited(robot)
                            or self.console.clients().get(robot) is not client or self.claims.get(robot) != route):
                        raise TripError(409, "CHARGE_BAY_ADMISSION_CHANGED")
                    runner._check_human_hold()
                    runner._graph_for(live.view["map_version"])
                except (TripError, HubError) as exc:
                    if self.claims.get(robot) == route:
                        self.claims.pop(robot, None)
                    info.pop("claim", None)
                    if live.open:
                        reason = exc.code if isinstance(exc, TripError) else str(exc)
                        info.update(phase="waiting_for_clearance", reason=reason, next_check_at=runner._clock() + 1)
                    raise
            self.claims[robot] = route
            info.update(phase="submitting", submitted_at=runner._clock(), claim=route)
            runner._save(live)
            with dispatch_guard(check, paths={"/api/v1/docking/dock"}):
                check()
                receipt = await client._post("/api/v1/docking/dock", {
                    "dock": info["dock_id"], "correlation_id": plan_id, "expected_boot_id": str(UUID(owner["boot_id"])),
                    "expected_owner_generation": owner["owner_generation"]})
            op = NativeOperation.model_validate(receipt.get("operation")).model_dump(mode="json")
            if (op["kind"], op["correlation_id"], op["boot_id"]) != ("dock", plan_id, owner["boot_id"]):
                raise TripError(409, "CHARGE_BAY_DOCK_RECEIPT_UNVERIFIED")
            info.update(phase="docking", operation=op)
            if not live.open:
                await self.halt(live.view)
            return
        if info["phase"] != "docking":
            raise TripError(409, "CHARGE_BAY_DOCK_SUBMISSION_UNKNOWN")
        expected = info["operation"]
        view = await client.docking_status(expected["run_id"])
        op = view.get("operation") or {}
        if view.get("lookup") != "FOUND" or any(op.get(k) != expected[k] for k in ("kind","run_id","boot_id","correlation_id")):
            raise TripError(409, "CHARGE_BAY_DOCK_READBACK_UNVERIFIED")
        if op.get("phase") != "TERMINAL":
            if runner._clock() - info["submitted_at"] > 420:
                raise TripError(409, "CHARGE_BAY_DOCK_TIMEOUT")
            return
        if op.get("result") != "SUCCEEDED":
            raise TripError(409, "CHARGE_BAY_DOCK_FAILED", {"result": op.get("result"), "reason": op.get("reason")})
        if view.get("state") != "DOCKED" or view.get("dock_id") != info["dock_id"] or not safe_proof(view, op):
            raise TripError(409, "CHARGE_BAY_DOCK_TERMINAL_UNVERIFIED")
        if live.open:
            self.claims.pop(robot, None)
            info.pop("claim", None)
            info.update(phase="docked", operation=op)
            live.view.update(state="arrived", reason=None)

    async def halt(self, trip):
        info = trip["detail"]["parking_handoff"]
        if info["phase"] in {"staging_confirmed", "waiting_for_commission", "waiting_for_clearance"}:
            return {"stop_sent": True}
        client = self.client(trip["robot_id"])
        run_id = (info.get("operation") or {}).get("run_id")
        current = await client.docking_status(run_id)
        op = current.get("operation") or {}
        if op.get("kind") == "dock" and op.get("correlation_id") == trip["trip_id"] and op.get("phase") != "TERMINAL":
            owner = current.get("owner") or {}
            if owner.get("owner_run_id") == op.get("run_id") and op.get("boot_id") == owner.get("boot_id"):
                current = await client._post("/api/v1/docking/cancel-operation", {
                    "run_id": op["run_id"], "expected_boot_id": owner["boot_id"],
                    "expected_owner_generation": owner["owner_generation"]})
                op = current.get("operation") or {}
        if (op.get("kind") == "dock" and op.get("correlation_id") == trip["trip_id"]
                and (run_id is None or op.get("run_id") == run_id)
                and safe_proof(current, op)):
            self.claims.pop(trip["robot_id"], None)
            return {"stop_sent": True}
        return {"stop_sent": False, "error": "DOCK_CANCEL_UNCONFIRMED"}
