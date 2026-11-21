"""Scope a non-actuating Nav2 plan to the live CORE map and starting state."""

import math

from core_api_web.api.deps import Mode, PlannedPathScope
from core_api_web.api.errors import ApiError
from core_common.protocol.evidence import STALE_POSE_S


def plan_scope(svc, body, auth, line_stop):
    grid_id, revision = svc.state.map_grid_context()
    if grid_id != body.expected_map_grid_id:
        raise ApiError("NAVIGATION_MAP_GRID_CHANGED", 409, "the loaded grid differs from the approved goal grid")
    epoch, mode = svc.modes.epoch, svc.modes.mode
    if mode not in (Mode.IDLE, Mode.NAVIGATION):
        raise ApiError("MODE_CONFLICT", 409, "the current mode cannot prepare a Nav2 path")
    line = ()
    if line_stop is not None:
        trip = getattr(svc, "trip_lease", None)
        status = svc.line_follow.status()
        junction = status.junction
        if trip is None or not trip.matches_nowait(
                lease_id=line_stop.lease_id, trip_id=line_stop.trip_id,
                job_id=line_stop.job_id, owner_id=auth.token_id):
            raise ApiError("NAVIGATION_HANDOFF_LEASE_CHANGED", 409, "the specified trip lease is no longer held")
        if (mode is not Mode.NAVIGATION or status.state != "HOLD" or status.reason != "junction_stop" or junction is None
                or (junction.seq, junction.place_id, junction.pending_action, junction.state)
                != (line_stop.junction_seq, line_stop.stop_place_id, "stop", "executing")):
            raise ApiError("NAVIGATION_HANDOFF_STOP_CHANGED", 409, "the specified trip stop is no longer held")
        line = (line_stop.lease_id, line_stop.trip_id, line_stop.job_id,
                line_stop.junction_seq, line_stop.stop_place_id)
    elif svc.line_follow.active:
        raise ApiError("LINE_FOLLOW_ACTIVE", 409, "a direct plan requires line following to be off")
    if svc.modes.epoch != epoch:
        raise ApiError("NAVIGATION_PLAN_CHANGED", 409, "the motion mode changed while checking the plan")
    return PlannedPathScope(auth.token_id, body.correlation_id, (grid_id, revision, mode, epoch, line))


def verify_plan_start(svc, plan):
    x, y, _, frame, age = svc.state.pose_sample()
    resolution = (svc.maps.get_map() or {}).get("resolution")
    if (frame != "map" or not 0 <= age <= STALE_POSE_S or not all(math.isfinite(v) for v in (x, y))
            or type(resolution) not in (int, float) or not math.isfinite(resolution) or resolution <= 0
            or not plan.points
            or not math.dist((x, y), plan.points[0]) <= resolution / math.sqrt(2) + 1e-9):
        raise ApiError("NAVIGATION_PLAN_START_CHANGED", 409, "the path no longer starts at the current map pose")
