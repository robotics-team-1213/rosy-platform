"""Read the approved SLAM pose specifically for surveyed stop trips."""

import math

from core_common.protocol.evidence import STALE_POSE_S
from fleet.localization.map_binding import bound_pose
from fleet.server.trip_ports import TripError
from rosy.world.state.projections.map_pose import LOCALIZED, MapPose
from rosy.world.state.projections.map_pose_samples import odom_from_snapshot, parse_utc


def commissioned_stop(graph, target):
    stop = graph.places.get(target) if isinstance(target, str) else None
    return stop if stop is not None and stop.precision_stop is not None else None


async def read_precision_pose(runner, robot_id, site_version, binding_id=None):
    active = runner._store.active()
    reader = runner.named_stop_state or runner._robot_state
    if active is None or active[0] != site_version or reader is None:
        return None
    try:
        state = await runner._call(reader(robot_id), "TRIP_POSE_UNTRUSTED")
    except (KeyError, TripError):
        return None
    if not isinstance(state, dict) or state.get("pose_frame") != "map":
        return None
    current = runner._store.active()
    if current is None or current[0] != site_version:
        return None
    bindings = runner._store.map_bindings
    chosen = bindings.active(robot_id)
    if chosen is None or (binding_id is not None and chosen["binding_id"] != binding_id):
        return None
    fit, _ = bindings.matching_fit(robot_id, state, (active[1].map_id, site_version))
    pose = state.get("pose") or {}
    evidence = (state.get("evidence") or {}).get("pose") or {}
    stamp = parse_utc(evidence.get("received_at"))
    odom = odom_from_snapshot(state)
    now = runner._clock()
    if (fit is None or bindings.active(robot_id) != chosen or evidence.get("evidence") != "fresh"
            or stamp is None or not 0 <= now - stamp < STALE_POSE_S
            or odom is None or not 0 <= now - odom.stamp < STALE_POSE_S
            or not all(type(pose.get(axis)) in (int, float) and math.isfinite(pose[axis])
                       for axis in ("x", "y", "yaw"))):
        return None
    x, y, yaw = bound_pose(fit, (pose["x"], pose["y"], pose["yaw"]))
    return (MapPose(x, y, yaw, LOCALIZED, "approved_slam", 0., now - stamp,
                    anchor_age_s=now - stamp, map_id=active[1].map_id, odom_stamp=odom.stamp),
            chosen["binding_id"])


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
