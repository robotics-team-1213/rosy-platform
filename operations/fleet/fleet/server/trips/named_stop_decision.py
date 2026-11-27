"""Classify named stop alignment from the commissioned site tolerances and live pose."""

import math

from core_common.stop_pose import stop_error
from fleet.localization.map_binding import bound_pose
from fleet.server.named_stop_topview import KEY as TOPVIEW_KEY, current_verdict


def named_stop_decision(place, fit, state):
    if state.get("pose_frame") != "map":
        return {"decision": "WAIT", "reason": "map_pose_required"}
    limits = place.precision_stop
    pose = state.get("pose") or {}
    evidence = state.get("evidence") or {}
    if (any((evidence.get(key) or {}).get("evidence") != "fresh"
            for key in ("pose", "velocity"))
            or any(type(pose.get(axis)) not in (int, float) or not math.isfinite(pose[axis])
                   for axis in ("x", "y", "yaw"))):
        return {"decision": "WAIT", "reason": "fresh_pose_and_velocity_required"}

    x, y, yaw = bound_pose(fit, (pose["x"], pose["y"], pose["yaw"]))
    dx, dy = place.x - x, place.y - y
    error = stop_error((place.x, place.y, place.yaw), (x, y, yaw))
    longitudinal, lateral, heading = error["longitudinal_m"], error["lateral_m"], error["heading_rad"]
    margin = limits.position_uncertainty_m + fit.max
    result = {"error": error, "evidence_ref": limits.evidence_ref}
    if abs(heading) + limits.heading_uncertainty_rad > limits.heading_rad:
        return {**result, "decision": "HOLD", "reason": "heading_outside_limits"}
    if abs(lateral) + margin > limits.lateral_m:
        return {**result, "decision": "HOLD", "reason": "lateral_outside_limits"}
    if abs(longitudinal) + margin <= limits.longitudinal_m:
        return {**result, "decision": "IN_TOLERANCE"}
    forward = math.cos(yaw) * dx + math.sin(yaw) * dy
    if (abs(longitudinal) - margin <= limits.longitudinal_m
            or not 0.005 <= abs(forward) <= limits.max_correction_m
            or abs(longitudinal - forward * math.cos(heading)) + margin > limits.longitudinal_m
            or abs(lateral - forward * math.sin(heading)) + margin > limits.lateral_m):
        return {**result, "decision": "HOLD", "reason": "straight_correction_unverified"}
    return {**result, "decision": "REPARK", "forward_m": forward}


def still_aligned(store, live, evidence, place, snapshot, clock=None):
    current = store.active_view()
    robot = live.view["robot_id"]
    bindings = store.map_bindings
    binding = bindings.active(robot) or {}
    fit, _ = bindings.matching_fit(robot, snapshot, (evidence["map_id"], evidence["map_version"]))
    return (live.open and current is not None and current["sha256"] == evidence["map_sha256"]
            and binding.get("binding_id") == evidence["binding_id"] and fit is not None
            and snapshot.get("mode") in ("NAVIGATION", "IDLE")
            and _aligned(live, place, fit, snapshot, clock))


def _aligned(live, place, fit, snapshot, clock):
    from fleet.site_map import SitePlace

    record = live.view["detail"].get(TOPVIEW_KEY)  # a cell top-view verdict replaces the SLAM one for its stop
    if record is not None and record.get("place") == place["id"]:
        verdict = current_verdict(record, snapshot, clock() if clock else None, place["id"])
        return verdict is not None and verdict["decision"] == "IN_TOLERANCE"
    return named_stop_decision(SitePlace.model_validate(place), fit, snapshot)["decision"] == "IN_TOLERANCE"


async def check_repark_decision(runner, live, evidence, place, decision):
    from fleet.hub.hub import HubError

    if decision["decision"] != "REPARK" or runner.check_named_correction is None:
        return decision
    try:
        candidate = await runner.check_named_correction(live, evidence, place)
    except HubError as exc:
        return {**decision, "decision": "HOLD", "reason": str(exc)}
    return {**candidate, "decision": "REPARK", "path_preview": True}


async def confirm_precision_arrival(runner, live, operation, evidence, place):
    if runner.confirm_named_precision is None:
        return True
    ready = lambda snapshot: still_aligned(runner._store, live, evidence, place, snapshot, runner._clock)
    result = await runner.confirm_named_precision(live.view["robot_id"], operation, ready=ready)
    if isinstance(result, dict):
        live.view["detail"]["named_stop_repark_completion"] = result
    return bool(result)
