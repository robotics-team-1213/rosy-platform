"""Traffic checks for a prepared named-stop path in the active site frame."""

import asyncio
import math
import sys
from uuid import UUID

from core_common.robot_body import nominal_body_for
from fleet.hub.hub import HubError
from fleet.server import traffic
from fleet.server.console_view import trip_caps
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
    marker_clearance = getattr(console, "_site_marker_clearance", None)
    missing = set(console.robot_ids) - {mover} - clients.keys()
    if missing and marker_clearance is None:
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_STATE_UNVERIFIED")

    results = await asyncio.gather(*(client.state() for client in clients.values()), return_exceptions=True)
    observed = {rid: None for rid in missing}
    for rid, value in zip(clients, results):
        if isinstance(value, dict):
            observed[rid] = value
        elif marker_clearance is not None:
            observed[rid] = None
        else:
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_STATE_UNVERIFIED")
    return clients, observed


def _point(state):
    pose = state.get("pose") or {}
    xy = (pose.get("x"), pose.get("y"))
    if not all(type(value) in (int, float) and math.isfinite(value) for value in xy):
        raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_POSE_UNVERIFIED")
    return xy


#: The nominal base's tray corner sweeps this radius in an in-place turn (docking model, panel B 2026-11-21); the body
#: circle alone (0.0826) leaves the tray out. Fleet must not import the CORE docking model, so the value is kept here.
TRAY_TURN_RADIUS_M = 0.144
#: Keep-out around an in-place turning point: the mover's tray sweep (0.144) plus a standing peer's body circle
#: (0.0826), rounded up. Both trays were counted before (0.288), more than the 0.226 m bay spacing; a standing
#: peer does not sweep its tray (safety-distance panel and user decision 2026-11-27). Only for a peer whose state
#: proves it stands; a peer known from a camera marker alone keeps both tray sweeps (its heading is not checked).
TURN_KEEP_OUT_M = 0.23


def _turn_keep_out(mover, peer):
    return max(TURN_KEEP_OUT_M, max(mover.rotation_radius_m, TRAY_TURN_RADIUS_M) + peer.rotation_radius_m)


def _body(console, robot):
    """Nominal body of the robot's advertised kind from the kept capability read, or None (unknown)."""
    display = getattr(console, "_capability_display", None)
    caps = display._kept(robot, console.clients().get(robot)) if display is not None else None
    trip = trip_caps(caps) if caps else None
    return nominal_body_for(trip.kind) if trip is not None else None


def _fresh_stopped(state):
    evidence = state.get("evidence") or {}
    if any((evidence.get(channel) or {}).get("evidence") != "fresh" for channel in ("pose", "velocity")):
        return False
    velocity = state.get("velocity") or {}
    return (all(type(velocity.get(axis)) in (int, float) and math.isfinite(velocity[axis])
                for axis in ("linear", "angular"))
            and abs(velocity["linear"]) < 0.01 and abs(velocity["angular"]) <= 0.02)


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


def site_corridor(console, mover, mover_state, stop_binding, scope, goal, peers, *, route, correction_padding=None, held_by_fleet=frozenset()):
    # held_by_fleet: peers Fleet itself holds (traffic_hold waiting_for the mover); it releases them only after the mover is done.
    clients, observed = peers
    marker_clearance = getattr(console, "_site_marker_clearance", None)
    current = {rid: client for rid, client in console.clients().items() if rid != mover}
    if (set(console.robot_ids) - {mover} != observed.keys() or not clients.keys() <= current.keys()
            or any(current.get(rid) is not client for rid, client in clients.items())):
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
        if state is None:
            if marker_clearance is None:
                raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_STATE_UNVERIFIED")
            mover_body = _body(console, mover)
            keep_out = ((mover_body.half_width_m + mover_body.rotation_radius_m + (correction_padding or 0.0))
                        if mover_body is not None else console._clearance_m + (correction_padding or 0.0) + traffic.SAMPLE_STEP_M / 2)
            cleared = marker_clearance.clear(console, robot, (site[0], path), keep_out, None)
            decision = (marker_clearance.evidence(robot) or {}) if hasattr(marker_clearance, "evidence") else {}
            if cleared is not True:
                code = ("LINE_HANDOFF_ROUTE_OCCUPIED" if decision.get("reason") == "keep_out_intersection"
                        else "LINE_HANDOFF_PEER_STATE_UNVERIFIED")
                raise HubError("COMMAND_REJECTED", code)
            turn_need = ((2 * max(mover_body.rotation_radius_m, TRAY_TURN_RADIUS_M) + (correction_padding or 0.0))
                         if mover_body is not None else keep_out)
            for obs in decision.get("observations") or ():
                if any(math.dist((obs["x"], obs["y"]), pt) < turn_need + obs.get("uncertainty_m", 0.0) for pt in path[:-1]):
                    raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_ROUTE_OCCUPIED")
            continue
        line = state.get("line_follow") or {}
        if (robot in console.goal_leases.pending or robot in console._goal_busy
                or state.get("navigation") not in ("IDLE", "ARRIVED", "CANCELED", "FAILED")
                or state.get("mode") not in (("IDLE", "EMERGENCY", "NAVIGATION") if robot in held_by_fleet else ("IDLE", "EMERGENCY"))
                or line.get("mode") != "OFF"
                or not _fresh_stopped(state)):
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_MOTION_UNVERIFIED")
        peer_fit = fit_for(robot, state)
        position = peer_fit.apply(_point(state))
        if not _geometry_point(position):
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_POSE_UNVERIFIED")
        # Robots bound to the same grid by the same transform share its error: their relative distance does not.
        shared = ((fit.yaw, fit.tx, fit.ty) == (peer_fit.yaw, peer_fit.tx, peer_fit.ty)
                  and mover_state.get("map_grid_id") is not None and mover_state.get("map_grid_id") == state.get("map_grid_id"))
        error = (0.0 if shared else fit.max + peer_fit.max) + (correction_padding or 0.0)
        bodies = _body(console, mover), _body(console, robot)
        if None in bodies:  # unknown geometry keeps the general traffic clearance
            lane = turn = console._clearance_m + error + traffic.SAMPLE_STEP_M / 2
        else:
            # The peer passed the stopped/bound checks above, so it is a fixed body: the mover's swept half width
            # along the path and its tray-inclusive turn radius at the turning points must clear it. Bays are
            # 0.226 m apart, so the lane term leaves ~1 cm: CORE keeps the body inside its lane and stops on LiDAR.
            lane = bodies[0].half_width_m + bodies[1].rotation_radius_m + error
            turn = _turn_keep_out(*bodies) + error  # the standing peer's tray does not sweep
        if (any(_point_segment(position, a, b) < lane for a, b in zip(path, path[1:]))
                or any(math.dist(position, point) < turn for point in path[:-1])):
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_ROUTE_OCCUPIED")
