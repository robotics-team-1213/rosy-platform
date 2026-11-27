"""Check an exact straight repark path against the approved terminal corridor."""

import asyncio
import math

import httpx

from core_common.protocol.evidence import STALE_POSE_S
from core_common.stop_pose import repark_within_limits
from fleet.hub.hub import HubError
from fleet.server.handoff_traffic import read_peers, site_corridor
from fleet.server.named_stop_decision import named_stop_decision
from fleet.server.named_stop_topview import KEY as TOPVIEW_KEY, current_verdict
from fleet.site_map import SitePlace


def correction_endpoint(state, forward, left=0.0):
    pose = state.get("pose") or {}
    if (type(forward) not in (int, float) or type(left) not in (int, float) or not repark_within_limits(forward, left)
            or not 0.005 <= max(abs(forward), abs(left))
            or any(type(pose.get(axis)) not in (int, float) or not math.isfinite(pose[axis])
                   for axis in ("x", "y", "yaw"))):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_POSE_UNVERIFIED")
    return (pose["x"] + forward * math.cos(pose["yaw"]) - left * math.sin(pose["yaw"]),
            pose["y"] + forward * math.sin(pose["yaw"]) + left * math.cos(pose["yaw"]))


async def check_correction_path(console, live, evidence, place_data, *, cable_inhibited):
    """Read-only preview. Cable and terminal traffic can veto a candidate."""
    robot = live.view["robot_id"]
    scope = live.view["detail"].get("named_stop_handoff_pending") or {}
    if not scope.get("terminal") or scope.get("correlation_id") != evidence["attempt_id"]:
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_TERMINAL_REQUIRED")
    if cable_inhibited(robot):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_CABLE_HOLD")
    client = console.clients().get(robot)
    if client is None:
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_ROBOT_UNAVAILABLE")
    stop = console.goal_leases.stop_token(robot)
    before = console._clock()
    try:
        state, peers = await asyncio.gather(client.state(), read_peers(console, robot))
    except (OSError, httpx.HTTPError) as exc:
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_STATE_UNAVAILABLE") from exc
    if (not live.open or console.clients().get(robot) is not client
            or stop != console.goal_leases.stop_token(robot) or console._clock() - before > STALE_POSE_S
            or cable_inhibited(robot) or state.get("mode") not in ("NAVIGATION", "IDLE")
            or (state.get("line_follow") or {}).get("mode") != "OFF"):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_ADMISSION_CHANGED")
    store = console._named_stop_site_maps
    active = store.active_view()
    site = evidence["map_id"], evidence["map_version"]
    fit, _ = store.map_bindings.matching_fit(robot, state, site)
    binding = store.map_bindings.active(robot) or {}
    if (active is None or active["sha256"] != evidence["map_sha256"] or fit is None
            or binding.get("binding_id") != evidence["binding_id"] or state.get("map_grid_id") != evidence["map_grid_id"]):
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_DISPATCH_FRAME_CHANGED")
    place = SitePlace.model_validate(place_data)
    record = live.view["detail"].get(TOPVIEW_KEY)  # a top-view stop is corrected from its own verdict only
    decision = (current_verdict(record, state, console._clock(), place.id)
                if record is not None and record.get("place") == place.id else named_stop_decision(place, fit, state))
    if decision is None or decision["decision"] != "REPARK":
        raise HubError("COMMAND_REJECTED", "NAMED_STOP_CORRECTION_POSE_CHANGED")
    left = decision.get("left_m", 0.0)
    goal = correction_endpoint(state, decision["forward_m"], left)
    limits = place.precision_stop
    padding = (limits.position_uncertainty_m + abs(left)
               + 2 * abs(decision["forward_m"]) * math.sin(limits.heading_uncertainty_rad / 2))
    site_corridor(console, robot, state, {"site_map_id": site[0], "site_map_version": site[1]},
                  scope, goal, peers, route=(), correction_padding=padding)
    return {**decision, "site_end": list(fit.apply(goal)), "terminal_arc": scope["terminal"]["arc_id"]}
