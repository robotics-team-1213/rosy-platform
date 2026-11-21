"""Traffic checks for a prepared named-stop path in the active site frame."""

import asyncio
import math
import sys
from uuid import UUID

from core_common.robot_body import nominal_body_for
from fleet.hub.hub import HubError
from fleet.server.rightofway import traffic
from fleet.site_map import MAX_POINTS, _point_segment, _polyline_polygon_gap


# Polygon intersection multiplies two cross products of coordinate differences.
_MAX_GEOMETRY_COORD = math.sqrt(math.sqrt(sys.float_info.max)) / 4


def _geometry_point(point):
    return len(point) == 2 and all(type(v) in (int, float) and abs(v) <= _MAX_GEOMETRY_COORD for v in point)


def checked_plan(payload, grid_id):
    try:
        plan_id = str(UUID(payload["plan_id"]))
        points = payload["points"]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PLAN_UNVERIFIED") from exc
    if (payload.get("frame") != "map" or payload.get("map_grid_id") != grid_id
            or not isinstance(points, list) or not 0 < len(points) <= MAX_POINTS
            or any(not isinstance(point, list) or not _geometry_point(point) for point in points)):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PLAN_UNVERIFIED")
    return plan_id, [tuple(point) for point in points]


async def read_peers(console, mover):
    clients = {rid: client for rid, client in console.clients().items() if rid != mover}
    if set(console.robot_ids) - {mover} != clients.keys():
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_STATE_UNVERIFIED")

    results = await asyncio.gather(*(client.state() for client in clients.values()), return_exceptions=True)
    if not all(isinstance(value, dict) for value in results):
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_STATE_UNVERIFIED")
    return clients, dict(zip(clients, results))


def _point(state):
    pose = state.get("pose") or {}
    xy = (pose.get("x"), pose.get("y"))
    if not all(type(value) in (int, float) and math.isfinite(value) for value in xy):
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_POSE_UNVERIFIED")
    return xy


def _fresh_stopped(state):
    evidence = state.get("evidence") or {}
    if any((evidence.get(channel) or {}).get("evidence") != "fresh" for channel in ("pose", "velocity")):
        return False
    velocity = state.get("velocity") or {}
    return all(type(velocity.get(axis)) in (int, float) and velocity[axis] == 0.0
               for axis in ("linear", "angular"))


def _inside_corridor(path, centerline, margin):
    """Certify each path span in a union of convex capsules about the centerline."""
    if not math.isfinite(margin) or margin <= 0:
        return False
    spans = tuple(zip(centerline, centerline[1:]))
    pairs_left = MAX_POINTS

    def covers(a, b, depth):
        nonlocal pairs_left
        pairs_left -= len(spans)
        if pairs_left < 0:
            raise HubError("COMMAND_REJECTED", "NAMED_STOP_PATH_TOO_COMPLEX")
        distances = [(_point_segment(a, p, q), _point_segment(b, p, q)) for p, q in spans]
        if any(max(pair) <= margin for pair in distances):
            return True
        if depth == 0 or not all(any(pair[i] <= margin for pair in distances) for i in (0, 1)):
            return False
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        return covers(a, mid, depth - 1) and covers(mid, b, depth - 1)

    return all(covers(a, b, 12) for a, b in zip(path, path[1:]))


def _check_terminal(maps, site, scope, path, fit_error, *, check_walls=False):
    active = maps.active()
    terminal = scope.get("terminal") or {}
    body = nominal_body_for(terminal.get("robot_kind", ""))
    arc = active[2].arcs.get(terminal.get("arc_id")) if active is not None else None
    start, end = terminal.get("s_from"), terminal.get("s_to")
    if (active is None or (active[1].map_id, active[0]) != site
            or arc is None or arc.drive_mode != "free" or body is None
            or not all(type(s) in (int, float) and math.isfinite(s) for s in (start, end))
            or not 0 <= start < end <= arc.length_m):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_TERMINAL_UNVERIFIED")
    centerline = [arc.point_at(start)[:2], *(point for knot, point in zip(arc.knots, arc.polyline)
                                             if start < knot < end), arc.point_at(end)[:2]]
    if not all(map(_geometry_point, centerline)):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_TERMINAL_UNVERIFIED")
    footprint = body.rotation_clear_m() + fit_error
    if not _inside_corridor(path, centerline, arc.width_m / 2 - footprint):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PATH_OUTSIDE_TERMINAL")
    if check_walls:
        for wall in active[1].walls:
            points = list(wall.face)
            if not all(map(_geometry_point, points)) or _polyline_polygon_gap(path, points) <= footprint:
                raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_WALL")
    crossing_areas = [area for crosswalk in active[1].crosswalks for area in (crosswalk.polygon, *crosswalk.approach)]
    if len(path) * sum(map(len, crossing_areas)) > MAX_POINTS:
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PATH_TOO_COMPLEX")
    if any(not all(map(_geometry_point, area)) for area in crossing_areas):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_TERMINAL_UNVERIFIED")
    if any(_polyline_polygon_gap(path, area) <= footprint for area in crossing_areas):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PATH_CROSSWALK")


def site_corridor(console, mover, mover_state, stop_binding, scope, goal, peers, *, route, correction_padding=None):
    clients, observed = peers
    current = {rid: client for rid, client in console.clients().items() if rid != mover}
    if (set(console.robot_ids) - {mover} != clients.keys() or current.keys() != clients.keys()
            or any(current[rid] is not client for rid, client in clients.items())):
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_ROSTER_CHANGED")
    bindings = console._named_stop_site_maps.map_bindings
    site = (stop_binding["site_map_id"], stop_binding["site_map_version"])

    def fit_for(robot, snapshot):
        fit, reason = bindings.matching_fit(robot, snapshot, site)
        if fit is None:
            raise HubError("COMMAND_REJECTED", reason)
        return fit

    fit = fit_for(mover, mover_state)
    if not _fresh_stopped(mover_state):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_MOVER_STATE_UNVERIFIED")
    start = fit.apply(_point(mover_state))
    if (scope is not None and correction_padding is None
            and math.dist(start, scope["staging_xy"]) + fit.max > scope["staging_radius_m"]):
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_STAGING_POSE_CHANGED")
    path = [start, *(fit.apply(p) for p in route), fit.apply(goal)]
    if not all(map(_geometry_point, path)):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PLAN_UNVERIFIED")
    if scope is not None:
        _check_terminal(console._named_stop_site_maps, site, scope, path, fit.max + (correction_padding or 0.0),
                        check_walls=correction_padding is not None)
    if len(path) * len(observed) > MAX_POINTS:
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_PATH_TOO_COMPLEX")
    for robot, state in observed.items():
        line = state.get("line_follow") or {}
        if (robot in console.goal_leases.pending or robot in console._goal_busy
                or state.get("navigation") not in ("IDLE", "ARRIVED", "CANCELED", "FAILED")
                or state.get("mode") not in ("IDLE", "EMERGENCY") or line.get("mode") != "OFF"
                or not _fresh_stopped(state)):
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_MOTION_UNVERIFIED")
        peer_fit = fit_for(robot, state)
        position = peer_fit.apply(_point(state))
        if not _geometry_point(position):
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_POSE_UNVERIFIED")
        clearance = console._clearance_m + fit.max + peer_fit.max + traffic.SAMPLE_STEP_M / 2 + (correction_padding or 0.0)
        if any(_point_segment(position, a, b) < clearance for a, b in zip(path, path[1:])):
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_ROUTE_OCCUPIED")
