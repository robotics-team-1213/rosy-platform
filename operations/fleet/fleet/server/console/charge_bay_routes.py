"""D-941 5/7: the active map's charge bays, shown only; Fleet does not dispatch from the plan yet.

Moved out of ``console_routes.py`` unchanged in behaviour (that file is at its size limit).
"""

from __future__ import annotations

import math

from fastapi import HTTPException

from fleet.charge_bays import ChargeBays, RobotView, bays_from_map, thresholds_of
from fleet.pipeline import resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_fleet_contract import CONTRACT_VERSION
from fleet.pipeline.station_zones import load_station_zones
from fleet.server.pipeline_routes import install_pipeline_routes, _storage_dir

# A saved cell claim follows a robot only while that robot is actually at the station.
CELL_CLAIM_RADIUS_M = 0.18
# These phases keep the claim wherever the robot is reported (an arm or a person is in the bed zone).
CLAIM_HOLD_PHASES = frozenset({"ARM_IN_BED_ZONE", "HUMAN_HOLD"})


def _at_station(xy, station_xy) -> bool:
    return math.hypot(xy[0] - station_xy[0], xy[1] - station_xy[1]) <= CELL_CLAIM_RADIUS_M


def _docked_fallback(cstate: dict, robots_by_id: dict, station_xy, hold: bool):
    """The saved docked robot, unless its trusted current pose is away from the station.

    A saved pose inside the radius does not keep the claim: it is the stale record being replaced.
    """
    docked = cstate.get("docked_robot")
    if docked is None or hold:
        return docked
    live = robots_by_id.get(docked.get("robot_id"))
    if live is None or live.pose is None or _at_station(live.pose, station_xy):
        return docked   # pose unknown or at the station: keep the claim (safe side)
    return None


def install_charge_bay_routes(app, console, gathered, read_guard):
    """Install ``GET /api/fleet/charge-bays`` and the feeding tick; returns ``bay_inputs`` for other readers."""
    map_pose = getattr(app.state, "map_pose", None)
    # D-941 5/7: the active map's charge bays, shown only; Fleet does not dispatch from the plan yet.
    bay_plan = app.state.charge_bays = ChargeBays(
        thresholds=lambda: thresholds_of(getattr(app.state, "site_maps", None)))

    def bay_view(row: dict, on_trip: set) -> RobotView:
        battery = (row.get("power_health") or {}).get("battery") or {}
        fresh = battery.get("evidence") == "fresh"
        pose = map_pose.arbitrated_pose(row["robot_id"]) if map_pose is not None else None
        localized = pose is not None and pose.state == "LOCALIZED"
        return RobotView(row["robot_id"], bool(row["online"]), battery.get("percent") if fresh else None,
                         battery.get("filtered_voltage") if fresh else None,
                         (pose.x, pose.y) if localized else None,
                         row["robot_id"] in on_trip,
                         getattr(pose, "yaw", None) if localized else None)

    async def bay_inputs():
        maps = getattr(app.state, "site_maps", None)
        active = maps.active() if maps is not None else None
        if active is None:
            return None, [], []
        runner = getattr(app.state, "trip_runner", None)
        on_trip = {trip["robot_id"] for trip in runner.open_trips()} if runner is not None else set()
        robots = [bay_view(row, on_trip) for row in (await gathered())["robots"]]
        return active, robots, bays_from_map(active[1])
    app.state.bay_inputs = bay_inputs
    app.state.bay_inputs = bay_inputs

    async def charge_bays_tick() -> None:
        """Feed the plan each period, so a voltage rise is seen with nobody on the page."""
        active, robots, bays = await bay_inputs()
        if active is not None and bays:
            bay_plan.observe(console._clock(), robots, bays)
    app.state.charge_bays_tick = charge_bays_tick

    @app.get("/api/fleet/charge-bays", dependencies=read_guard, tags=["fleet"])
    async def charge_bay_plan() -> dict:
        active, robots, bays = await bay_inputs()
        if active is None:
            raise HTTPException(404, detail={"code": "NO_ACTIVE_MAP"})
        maps = getattr(app.state, "site_maps", None)
        rules_store = getattr(maps, "rules", None)
        active_rules = rules_store.active_rules() if rules_store is not None else None
        cells = resolve_omx_cells(active[1], active[2])
        saved_cells = getattr(app.state, "omx_cell_states", None) or {}
        cell_evals = {}
        robots_by_id = {r.robot_id: r for r in robots}
        for cid, station in cells.items():
            cstate = saved_cells.get(cid, {})
            hold = cstate.get("phase") in CLAIM_HOLD_PHASES
            robot = robots_by_id.get(cstate.get("robot_id"))
            if robot is not None and not (hold or robot.pose is None or _at_station(robot.pose, station.station_xy)):
                robot = None   # a known pose away from the station releases a stale claim
            if robot is None:
                robot = next((r for r in robots if r.pose is not None and
                              _at_station(r.pose, station.station_xy)), None)
            docked_robot = ({"robot_id": robot.robot_id, "robot_kind": "pinky",
                             "pose": {"x": robot.pose[0], "y": robot.pose[1], "yaw": robot.yaw}}
                            if robot is not None and robot.pose is not None else
                            _docked_fallback(cstate, robots_by_id, station.station_xy, hold))
            cell_evals[cid] = evaluate_omx_cell_station(
                station, docked_robot=docked_robot, cell_state=cstate, map_version=active[0])
        plan_out = bay_plan.plan(robots, bays, graph=active[2], site_rules=active_rules)
        for cid, ceval in cell_evals.items():
            gate = ceval["gate"]
            if gate["amr_motion_inhibited"] and gate.get("robot_id"):
                act = next((action for action in plan_out["actions"]
                            if action["robot_id"] == gate["robot_id"]), None)
                if act is None:
                    plan_out["actions"].append({"robot_id": gate["robot_id"], "action": "wait",
                                                "reason": "locked_by_cell", "blocked_by_cell": True,
                                                "cell_id": cid})
                else:
                    act.update(blocked_by_cell=True, cell_id=cid, reason="locked_by_cell")
        hd = getattr(app.state, "human_detected", None) or {"cell_s": False, "cell_ab": False, "all": False}
        zones_data = load_station_zones(_storage_dir() / "station_zones.yaml")
        arm_live_fn = getattr(app.state, "get_arm_live_catalog", None)
        links_fn = getattr(app.state, "station_camera_links_for", None)
        return {"map_version": active[0],
                "contract_version": CONTRACT_VERSION, "omx_cells": cell_evals,
                "omx_cell_tasks": list((getattr(app.state, "omx_cell_tasks", None) or {}).values()),
                "pinky_tasks": list((getattr(app.state, "pinky_tasks", None) or {}).values()),
                "pipeline_decisions": list((getattr(app.state, "pipeline_decisions", None) or [])[-20:]),
                "cable_tangled": getattr(app.state, "cable_tangled", True),
                "human_safety": {"human_detected": dict(hd), "active_estop": any(bool(v) for v in hd.values())},
                "arm_holds": dict(getattr(app.state, "arm_holds", None) or {}),
                "arm_live_states": arm_live_fn() if callable(arm_live_fn) else dict(getattr(app.state, "arm_live_states", None) or {}),
                "station_camera_links": (links_fn(plan_out["bays"]) if callable(links_fn) else
                                         dict(getattr(app.state, "station_camera_links", None) or {})),
                "station_zones": {
                    "schema": zones_data["schema"],
                    "site_id": zones_data["site_id"],
                    "staging_bays": zones_data["staging_bays"],
                    "export_stations": zones_data["export_stations"],
                },
                **plan_out}
    install_pipeline_routes(
        app, console=console, site_maps=getattr(app.state, "site_maps", None), read_guard=read_guard,
        operator_guard=getattr(app.state, "operator_guard", None),
        proposer_guard=getattr(app.state, "proposer_guard", None),
    )
    return bay_inputs
