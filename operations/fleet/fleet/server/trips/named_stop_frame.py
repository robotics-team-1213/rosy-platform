"""Where a named stop's site pose lands in the robot's own Nav2 frame (D-1051, D-1022 binding).

The safety-tagged dispatch helper (ledger/task_dispatch_helpers.py) reaches this through
``app.state.named_stop_frame`` instead of importing map binding and trip geometry itself (D-430 §3).
"""

from __future__ import annotations

from fastapi import HTTPException

from fleet.localization.map_binding import bound_pose
from fleet.server.trip_geometry import robot_frame_goal


def bind(site_maps, robot_id: str, state: dict, active, local_pose: tuple):
    """(site pose, stop binding, fit) from the approved binding of this robot; 409 without one."""
    site_id = (active[1].map_id, active[0])
    binding = site_maps.map_bindings.active(robot_id)
    fit, reason = site_maps.map_bindings.matching_fit(robot_id, state, site_id)
    if fit is None or binding is None:
        raise HTTPException(409, detail={"code": reason or "MAP_BINDING_REQUIRED"})
    if site_maps.map_bindings.active(robot_id) != binding:
        raise HTTPException(409, detail={"code": "MAP_BINDING_CHANGED"})
    stop_binding = {
        "binding_id": binding["binding_id"], "map_grid_id": state["map_grid_id"],
        "site_map_id": site_id[0], "site_map_version": site_id[1],
    }
    return bound_pose(fit, local_pose), stop_binding, fit


def to_nav2(goal: tuple, state: dict, stop_binding: dict, fit) -> tuple:
    return tuple(round(v, 4) for v in robot_frame_goal(goal, None, state, stop_binding["site_map_id"], (fit, "")))
