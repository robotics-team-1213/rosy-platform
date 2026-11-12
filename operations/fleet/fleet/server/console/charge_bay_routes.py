"""D-941 5/7: the active map's charge bays, shown only; Fleet does not dispatch from the plan yet.

Moved out of ``console_routes.py`` unchanged in behaviour (that file is at its size limit).
"""

from __future__ import annotations

from fastapi import HTTPException

from fleet.charge_bays import ChargeBays, RobotView, bays_from_map, thresholds_of
from fleet.pipeline import resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_fleet_contract import CONTRACT_VERSION
from fleet.server.pipeline_routes import install_pipeline_routes


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
        for cid, station in cells.items():
            cstate = saved_cells.get(cid, {})
            robot = next((r for r in robots if cstate.get("robot_id") == r.robot_id), None)
            if robot is None:
                robot = next((r for r in robots if r.pose is not None and
                              ((r.pose[0] - station.station_xy[0]) ** 2 +
                               (r.pose[1] - station.station_xy[1]) ** 2) ** 0.5 <= 0.18), None)
            docked_robot = ({"robot_id": robot.robot_id, "robot_kind": "pinky",
                             "pose": {"x": robot.pose[0], "y": robot.pose[1], "yaw": robot.yaw}}
                            if robot is not None and robot.pose is not None else
                            cstate.get("docked_robot"))
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
        return {"map_version": active[0],
                "contract_version": CONTRACT_VERSION, "omx_cells": cell_evals,
                "omx_cell_tasks": list((getattr(app.state, "omx_cell_tasks", None) or {}).values()),
                "pinky_tasks": list((getattr(app.state, "pinky_tasks", None) or {}).values()),
                **plan_out}
    install_pipeline_routes(app, console=console, site_maps=getattr(app.state, "site_maps", None), read_guard=read_guard)
    return bay_inputs
