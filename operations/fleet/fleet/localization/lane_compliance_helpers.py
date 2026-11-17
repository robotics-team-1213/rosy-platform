"""D-511 / D-1013: pure geometry and return-sample helpers for ``fleet.localization.lane_compliance``."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional
from rosy.world.state.projections.map_pose import wrap_angle as _wrap


@dataclass(frozen=True)
class ReturnSample:
    """One raw (undebounced) classification. Angles in degrees. ``side`` is where the lane centre
    is, seen from the robot (``left``/``right``); None when on the lane."""

    state: str
    edge_id: Optional[str] = None
    offset_m: Optional[float] = None
    side: Optional[str] = None
    bearing_deg: Optional[float] = None       # to the re-entry point, robot frame (left +)
    lane_heading_deg: Optional[float] = None  # allowed direction of the nearest lane, map frame
    turn_deg: Optional[float] = None          # lane direction minus robot heading (left +)
    entry: Optional[tuple] = None             # re-entry point (x, y), map frame
    crosswalk: Optional[str] = None
    #: D-491/D-573 zone ``{id, near_m, far_m, uncertainty_m, source}`` of the crosswalk ahead (or under
    #: the body) along the lane from base_footprint; None when none is near.
    crosswalk_ahead: Optional[dict] = None
    #: D-511 rev 2: ``{ahead_m, heading_ahead_deg, curvature_1pm, to_end_m, next_place_id, ring}``.
    guide: Optional[dict] = None
    #: D-511 rev 4: the body is on a configured turn spot (a WRONG_WAY may turn here).
    turn_spot: bool = False
    #: rev 6: the nearest arc and the distance along it (for the lap context).
    arc_id: Optional[str] = None
    s_m: Optional[float] = None
    #: D-1013 / D-941: Fleet's charging-bay centerline evaluation while on or entering a bay edge.
    docking: Optional[dict] = None


#: Nominal distance from base_link to rear charging contacts (m, D-1013 / body_rear_x_m).
BAY_REAR_CONTACT_M = 0.076
#: Lateral offset thresholds on the extracted sub-pixel bay centerline (m).
BAY_ALIGNED_OFFSET_M = 0.015
BAY_DRIFT_MAX_OFFSET_M = 0.028
BAY_CONTACT_MAX_OFFSET_M = 0.020
#: Heading error thresholds relative to reverse-in target heading tangent + pi (deg).
BAY_ALIGNED_YAW_DEG = 4.0
BAY_DRIFT_MAX_YAW_DEG = 8.0
BAY_CONTACT_MAX_YAW_DEG = 5.0
BAY_TURN_ENTRY_S_M = 0.08
BAY_TURN_ENTRY_YAW_DEG = 25.0
#: Remaining distance along bay centerline to C_i where contact stop triggers (m).
BAY_CONTACT_STOP_M = 0.025
#: Continuous P gains for Fleet centerline steering recommendation (rad/(s*m), rad/(s*rad), rad/s).
BAY_GAIN_LATERAL = 8.0
BAY_GAIN_HEADING = 0.6
BAY_MAX_STEER_RAD_S = 0.5
#: Walk step along the lane for the crosswalk zone (m); the zone is this coarse.
XW_STEP_M = 0.01


def _bay_inward_arcs(graph) -> list:
    if graph is None:
        return []
    places = getattr(graph, "places", None) or {}
    return [
        arc for arc in graph.arcs.values()
        if getattr(arc, "forward", True)
        and (getattr(places.get(arc.end_place), "kind", None) == "charge"
             or str(arc.edge_id).startswith("bay_"))
    ]


def evaluate_bay_dock(x: float, y: float, yaw: Optional[float],
                      travel: Optional[float] = None, graph=None) -> Optional[dict]:
    """Evaluate reverse-in docking alignment against the active site map's extracted bay centerlines."""
    bay_arcs = _bay_inward_arcs(graph)
    if not bay_arcs:
        return None
    projected = [(arc, *arc.project(x, y)) for arc in bay_arcs]
    arc, dist, s, tangent = min(projected, key=lambda item: item[1])
    if dist > arc.width_m / 2.0:
        return None
    px, py, _ = arc.point_at(s)
    left = math.cos(tangent) * (y - py) - math.sin(tangent) * (x - px)
    offset_m = math.copysign(dist, left)
    to_end_m = max(0.0, arc.length_m - s)
    target_yaw = _wrap(tangent + math.pi)
    yaw_err_rad = 0.0 if yaw is None else _wrap(yaw - target_yaw)
    yaw_err_deg = math.degrees(yaw_err_rad)
    rear_offset_m = offset_m + BAY_REAR_CONTACT_M * math.sin(yaw_err_rad)
    converging = (offset_m * yaw_err_rad) < 0.0 and abs(yaw_err_deg) <= 16.0 and to_end_m > 0.12
    max_yaw_deg = 16.0 if converging else BAY_DRIFT_MAX_YAW_DEG
    if s <= BAY_TURN_ENTRY_S_M and yaw is not None and abs(yaw_err_deg) > BAY_TURN_ENTRY_YAW_DEG:
        verdict = "TURN_AT_ENTRY"
    elif to_end_m <= BAY_CONTACT_STOP_M:
        if (abs(offset_m) <= BAY_CONTACT_MAX_OFFSET_M
                and abs(rear_offset_m) <= BAY_CONTACT_MAX_OFFSET_M + 0.004
                and (yaw is None or abs(yaw_err_deg) <= BAY_CONTACT_MAX_YAW_DEG)):
            verdict = "CONTACT_STOP"
        else:
            verdict = "RETRY_FROM_P"
    elif (abs(offset_m) > BAY_DRIFT_MAX_OFFSET_M
          or abs(rear_offset_m) > BAY_DRIFT_MAX_OFFSET_M + 0.008
          or (yaw is not None and s > BAY_TURN_ENTRY_S_M and abs(yaw_err_deg) > max_yaw_deg)):
        verdict = "RETRY_FROM_P"
    elif (abs(offset_m) <= BAY_ALIGNED_OFFSET_M
          and (yaw is None or abs(yaw_err_deg) <= BAY_ALIGNED_YAW_DEG)):
        verdict = "BACKING_ALIGNED"
    else:
        verdict = "BACKING_DRIFT"
    steer = -(BAY_GAIN_LATERAL * offset_m + BAY_GAIN_HEADING * yaw_err_rad)
    steer_cmd = max(-BAY_MAX_STEER_RAD_S, min(BAY_MAX_STEER_RAD_S, steer))
    return {
        "bay_id": arc.end_place,
        "edge_id": arc.edge_id,
        "verdict": verdict,
        "s_m": round(s, 4),
        "to_end_m": round(to_end_m, 4),
        "offset_m": round(offset_m, 4),
        "rear_offset_m": round(rear_offset_m, 4),
        "yaw_err_deg": round(yaw_err_deg, 2),
        "steer_cmd_rad_s": round(steer_cmd, 4),
    }


def map_bounds(graph, pad_m: float) -> Optional[tuple]:
    """The lanes' bounding box grown by ``pad_m``: (x0, y0, x1, y1), or None without lanes."""
    points = [p for arc in graph.arcs.values() for p in arc.polyline] if graph is not None else []
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs) - pad_m, min(ys) - pad_m, max(xs) + pad_m, max(ys) + pad_m


def crosswalk_ahead(arc, s: float, crosswalks, horizon_m: float, behind_m: float,
                    uncertainty_m: float) -> Optional[dict]:
    """D-491/D-573 zone from the map: the first crosswalk polygon the lane centreline is in between
    ``behind_m`` behind and ``horizon_m`` ahead of base_footprint, as ``{id, near_m, far_m,
    uncertainty_m, source}`` along the lane from base_footprint (near < 0 once inside).
    ponytail: walks this arc only; a crosswalk past the arc's end shows once on the next arc."""
    from fleet.site_map import _inside
    for cid, polygon in crosswalks:
        polygon = list(polygon)
        hit = None
        along = s - behind_m
        while along <= min(s + horizon_m, arc.length_m) + 1e-9:
            x, y, _ = arc.point_at(max(along, 0.0))
            inside = _inside((x, y), polygon)
            if inside and hit is None:
                hit = along
            elif not inside and hit is not None:
                break
            along += XW_STEP_M
        if hit is not None and hit - s <= horizon_m and min(along, arc.length_m) - s > 0.0:  # base not past it
            return {"id": cid, "near_m": round(hit - s, 3), "far_m": round(min(along, arc.length_m) - s, 3),
                    "uncertainty_m": uncertainty_m, "source": "fleet_map"}
    return None
