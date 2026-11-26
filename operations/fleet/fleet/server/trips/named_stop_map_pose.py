"""Read an approved SLAM pose for surveyed stop and bound Nav2 trips."""

import math
from typing import Optional

from core_common.protocol.evidence import STALE_POSE_S
from fleet.localization.map_binding import bound_pose
from fleet.server.trip_ports import TripError
from rosy.world.state.projections.map_pose import LOCALIZED, MapPose
from rosy.world.state.projections.map_pose_samples import odom_from_snapshot, parse_utc


def commissioned_stop(graph, target):
    stop = graph.places.get(target) if isinstance(target, str) else None
    return stop if stop is not None and stop.precision_stop is not None else None


async def read_precision_pose_status(runner, robot_id, site_version, binding_id=None) -> tuple[Optional[tuple], dict]:
    active = runner._store.active()
    reader = runner.named_stop_state or runner._robot_state
    if active is None or active[0] != site_version or reader is None:
        return None, {"pose_reason": "MAP_VERSION_MISMATCH" if active is not None else "NO_ACTIVE_MAP"}
    try:
        state = await runner._call(reader(robot_id), "TRIP_POSE_UNTRUSTED")
    except (KeyError, TripError) as exc:
        return None, {"pose_reason": "ROBOT_STATE_UNAVAILABLE", "state_err": getattr(exc, "code", None)}
    current = runner._store.active()
    if current is None or current[0] != site_version:
        return None, {"pose_reason": "MAP_VERSION_CHANGED"}
    bindings = runner._store.map_bindings
    chosen = bindings.active(robot_id)
    loc = (state or {}).get("localization") or {}
    safety = (state or {}).get("safety") or {}
    base_diag = {
        "loc_state": loc.get("state"),
        "loc_reason": loc.get("reason"),
        "robot_grid_id": (state or {}).get("map_grid_id"),
        "binding_grid_id": None if chosen is None else chosen.get("robot_grid_id"),
        "binding_id": None if chosen is None else chosen.get("binding_id"),
        "navigation": (state or {}).get("navigation"),
        "mode": (state or {}).get("mode"),
        "estop": bool(safety.get("estop")),
    }
    if chosen is None or (binding_id is not None and chosen["binding_id"] != binding_id):
        return None, {**base_diag, "pose_reason": "MAP_BINDING_CHANGED" if chosen else "MAP_BINDING_REQUIRED"}
    now = runner._clock()
    sample = fresh_native_slam(state, now)
    fit, reason = bindings.matching_fit(robot_id, state, (active[1].map_id, site_version))
    if fit is None or bindings.active(robot_id) != chosen:
        return None, {**base_diag, "pose_reason": reason or "MAP_BINDING_CHANGED"}
    if sample is None:
        return None, {**base_diag, "pose_reason": "SLAM_POSE_STALE"}
    native_pose, age_s, odom_stamp = sample
    x, y, yaw = bound_pose(fit, native_pose)
    return (MapPose(x, y, yaw, LOCALIZED, "approved_slam", 0., age_s,
                    anchor_age_s=age_s, map_id=active[1].map_id, odom_stamp=odom_stamp), chosen["binding_id"]), base_diag


async def read_precision_pose(runner, robot_id, site_version, binding_id=None):
    bound, _diag = await read_precision_pose_status(runner, robot_id, site_version, binding_id)
    return bound


def fresh_native_slam(state, now):
    if not isinstance(state, dict) or state.get("pose_frame") != "map":
        return None
    pose = state.get("pose") or {}
    evidence = (state.get("evidence") or {}).get("pose") or {}
    stamp = parse_utc(evidence.get("received_at"))
    odom = odom_from_snapshot(state)
    if (evidence.get("evidence") != "fresh" or stamp is None or not 0 <= now - stamp < STALE_POSE_S
            or odom is None or not 0 <= now - odom.stamp < STALE_POSE_S
            or not all(type(pose.get(axis)) in (int, float) and math.isfinite(pose[axis])
                       for axis in ("x", "y", "yaw"))):
        return None
    return (pose["x"], pose["y"], pose["yaw"]), now - stamp, odom.stamp


async def precision_map_pose(runner, robot_id, scope):
    bound = await read_precision_pose(runner, robot_id, *scope)
    return bound[0] if bound is not None else None


def precision_line_fence(runner, live, pose):
    """Build the synchronous line-start check used at the mutating HTTP boundary."""
    robot_id = live.view["robot_id"]
    version = live.view["map_version"]
    binding_id = live.view["detail"]["precision_binding_id"]
    pose_stamp = runner._clock() - pose.age_s

    def check():
        active = runner._store.active()
        binding = runner._store.map_bindings.active(robot_id) or {}
        if (not live.open or active is None or active[0] != version or binding.get("binding_id") != binding_id
                or not 0 <= runner._clock() - pose_stamp < STALE_POSE_S
                or not 0 <= runner._clock() - pose.odom_stamp < STALE_POSE_S):
            raise RuntimeError("APPROVED_SLAM_POSE_REQUIRED")

    return check
