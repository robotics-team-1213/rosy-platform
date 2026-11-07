"""D-941 5/7: the active map's charge bays, shown only; Fleet does not dispatch from the plan yet.

Moved out of ``console_routes.py`` unchanged in behaviour (that file is at its size limit).
"""

from __future__ import annotations

from fastapi import HTTPException

from fleet.charge_bays import ChargeBays, RobotView, bays_from_map


def install_charge_bay_routes(app, console, gathered, read_guard):
    """Install ``GET /api/fleet/charge-bays`` and the feeding tick; returns ``bay_inputs`` for other readers."""
    map_pose = getattr(app.state, "map_pose", None)
    # D-941 5/7: the active map's charge bays, shown only; Fleet does not dispatch from the plan yet.
    bay_plan = app.state.charge_bays = ChargeBays()

    def bay_view(row: dict, on_trip: set) -> RobotView:
        battery = (row.get("power_health") or {}).get("battery") or {}
        fresh = battery.get("evidence") == "fresh"
        pose = map_pose.arbitrated_pose(row["robot_id"]) if map_pose is not None else None
        return RobotView(row["robot_id"], bool(row["online"]), battery.get("percent") if fresh else None,
                         battery.get("filtered_voltage") if fresh else None,
                         (pose.x, pose.y) if pose is not None and pose.state == "LOCALIZED" else None,
                         row["robot_id"] in on_trip)

    async def bay_inputs():
        maps = getattr(app.state, "site_maps", None)
        active = maps.active() if maps is not None else None
        if active is None:
            return None, [], []
        runner = getattr(app.state, "trip_runner", None)
        on_trip = {trip["robot_id"] for trip in runner.open_trips()} if runner is not None else set()
        robots = [bay_view(row, on_trip) for row in (await gathered())["robots"]]
        return active, robots, bays_from_map(active[1])

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
        return {"map_version": active[0], **bay_plan.plan(robots, bays)}
    return bay_inputs
