"""Subject: line_observer's keep-mode glue for the drivable steering (D-597 amendments 2-3), ROS-free.

keep_step     one camera frame: crosswalk hold trigger, the drivable steer on the newest way (or the
              straight crosswalk crossing / a hold without a way), and the keep_debug fields.
scan_summary  one LaserScan's ranges -> (wall ahead in the body strip, base_link x; nearest wall
              beside the robot per side) with the URDF body (D-424).
"""

from __future__ import annotations

from core_common.robot_body import NOMINAL_BODY

from .learned.expected_path import ExpectedPath

#: The newest drivable way steers while its frame is at most this old (odometry moves its target;
#: one inference every learned_paint_every_n frames at ~8 Hz plus ~0.3 s on a Pi).
WAY_MAX_AGE_S = 1.5
#: Crosswalk-class pixels (same inference) at or below this frame row (~0.35 m ahead) that mean
#: "at a crosswalk" for the drivable heading hold.
CROSSWALK_NEAR_ROW = 120
CROSSWALK_MIN_PX = 150
#: A LiDAR wall reading older than this against the camera frame is not used.
WALL_MAX_AGE_S = 0.5


def _path_of(steer, half):
    path = getattr(steer, "_expected_path", None)
    if path is None:
        path = ExpectedPath(half)
        steer._expected_path = path
    return path


def _remember_path(last, view):
    last["expected_path_state"] = view["state"]
    last["expected_path_s_m"] = view["s_m"]
    path_m = view["path_m"]
    last["expected_path_m"] = None if path_m is None else [[float(point[0]), float(point[1])] for point in path_m]


def keep_step(steer, worker, last, ground, x_offset, half, pose_at, stamp, wall):
    """(error, confidence) or None for this frame, and whether the drivable path decided it.
    `last` is the keeper's keep_debug dict (updated in place); pose_at(stamp) is odometry."""
    path = _path_of(steer, half)
    bars = worker.used_crosswalk
    if last.get('crosswalk') is not None or (bars is not None and int(bars[CROSSWALK_NEAR_ROW:].sum()) >= CROSSWALK_MIN_PX):
        steer.crosswalk(pose_at(stamp))
    latest = worker.latest_way(WAY_MAX_AGE_S)
    last.pop('junction_ahead_m', None)   # the way chose the branch: the tape keeper's junction HOLD does not apply
    if latest is not None:
        way, way_stamp = latest
        extra = {} if wall is None or abs(stamp - wall[1]) >= WALL_MAX_AGE_S else dict(wall_ahead_m=wall[0], side_clear_m=wall[2])
        source = pose_at(way_stamp)
        error, confidence, info = steer.update(way, way_stamp, ground, x_offset, half,
                                               source, pose_at(stamp), **extra)
        if source is not None:
            # near_centre_m is the way frame's body point, so the hypothesis uses that pose.
            # The stamp is this frame's, so a later hold cannot look like time running backwards.
            _remember_path(last, path.update(source, stamp, info))
        last.update(strategy=info['strategy'], drivable_steer=info, reason=info.get('reason'),
                    error=None if error is None else round(error, 3), confidence=confidence,
                    target_m=list(info.get('target_now_m') or info['target_m'] or []) or None)
        return (None if error is None else (error, confidence)), True
    pose = pose_at(stamp)
    if steer._in_crosswalk(pose):
        # bars (not drivable) fill the near view at a crosswalk: straight across (CORE D-573 gate).
        # That crossing is not a straight corridor, so the next empty frame must not extend it.
        if pose is not None:
            _remember_path(last, path.update(pose, stamp, {
                "strategy": "drivable_crosswalk_straight", "ahead_m": 0.0,
                "near_centre_m": (0.0, 0.0), "straddle": None, "reason": None}))
        last.update(strategy='drivable_crosswalk_straight', reason=None, error=0.0, confidence=0.6)
        return (0.0, 0.6), True
    # No fresh way. A committed straight corridor is republished from odometry.
    # Otherwise the tape keeper must not steer in between
    # (its corners and one-sided targets fought the way, 8kcn 20261009T234748Z).
    held = path.hold(pose, stamp) if pose is not None else None
    steer.lost(stamp)
    if held is not None and held["error"] is not None:
        _remember_path(last, held)
        target = held["target_m"]
        last.update(strategy='expected_path_held', reason=None,
                    error=round(held["error"], 3), confidence=held["confidence"],
                    target_m=None if target is None else [float(target[0]), float(target[1])])
        return (held["error"], held["confidence"]), True
    last.update(strategy='none', reason='drivable_way_stale', error=None, confidence=None, target_m=None)
    return None, False


def scan_summary(ranges, angle_min, angle_increment, range_min, range_max, body=NOMINAL_BODY):
    """(wall ahead base_link x or None, {'left'|'right': nearest wall beside or None}). The wall ahead
    is the nearest return in the body strip with 2 more within 0.02 m (a speck is no wall). A side
    wall is returns within 0.20 m laterally and 0.35 m ahead spanning >= 0.10 m along x (the signal
    posts at the ring entries are a few cm wide, 9dfk 20261010T010701Z_rosy_41)."""
    view = body.scan_view(dict(ranges=list(ranges), angle_min=angle_min, angle_increment=angle_increment,
                               range_min=range_min, range_max=range_max))
    strip = sorted(x for x, y in view.points if x > body.front_x_m and abs(y) <= body.half_width_m)
    ahead = next((x for i, x in enumerate(strip) if i + 2 < len(strip) and strip[i + 2] - x <= 0.02), None)
    near = {'left': [], 'right': []}
    for x, y in view.points:
        if 0.0 <= x <= 0.35 and body.half_width_m <= abs(y) <= 0.20:
            near['left' if y > 0 else 'right'].append((x, abs(y)))
    side = {k: (min(p[1] for p in v) if v and max(p[0] for p in v) - min(p[0] for p in v) >= 0.10 else None)
            for k, v in near.items()}
    return ahead, side
