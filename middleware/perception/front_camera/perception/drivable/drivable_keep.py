"""Subject: line_observer's keep-mode glue for the drivable steering (D-597 amendments 2-3), ROS-free.

keep_step     one camera frame: crosswalk hold trigger, the drivable steer on the newest way (or the
              straight crosswalk crossing / a hold without a way), and the keep_debug fields.
scan_summary  one LaserScan's ranges -> (wall ahead in the body strip, base_link x; nearest wall
              beside the robot per side; nearest return in CORE's +-45 deg front sector) with the URDF body (D-424).
"""

from __future__ import annotations

import math

import numpy as np
from core_common.robot_body import NOMINAL_BODY
from core_common.protocol.lane_route_guide import SelectedRoutePrior

from .drivable_preview import way_runs
from .drivable_steer import LOOKAHEAD_M, _to_current
from ..learned.expected_path import ExpectedPath, _valid_pose

#: The newest drivable way steers while its frame is at most this old (odometry moves its target;
#: one inference every learned_paint_every_n frames at ~8 Hz plus ~0.3 s on a Pi).
WAY_MAX_AGE_S = 1.5
#: Crosswalk-class pixels (same inference) at or below this frame row (~0.35 m ahead) that mean
#: "at a crosswalk" for the drivable heading hold.
CROSSWALK_NEAR_ROW = 120
CROSSWALK_MIN_PX = 150
#: A LiDAR wall reading older than this against the camera frame is not used.
WALL_MAX_AGE_S = 0.5


#: A route guide older than this (by the camera stamp) is not used.
GUIDE_MAX_AGE_S = 3.0   # the guide prior carries gaps up to 3 s (architect 2026-10-10)
#: Map distance from the lane centre beyond which keep refuses to drive on: half lane + half tape + half
#: body (architect context rule c1; g8-9dfk NW corridor: 905/905 frames were 0.21-0.26 m off map v5).
OFF_ROUTE_HOLD_M = 0.162
ROUTE_SIDE_M = 0.03   # D-769 rev 2: off the route centre by more than this picks the way on the route's side
#: the driving context is fresh while the Fleet pose is this young (confidence exp(-age/2)·exp(-ds/0.3))
CONTEXT_FRESH_S = 1.0


def parse_guide(raw, now):
    """(heading_ahead_deg, stamp, pivot_ok, heading_here_deg, off_route_m) from a line/lane_guide JSON
    {heading_ahead_deg, stamp, pivot_ok (the body's sweep circle fits here per the map; default true),
    heading_here_deg, off_route_m (map distance to the route centre line; optional), s (route progress)}, or None."""
    import json, math
    try:
        data = json.loads(raw)
        deg, stamp, ok = float(data["heading_ahead_deg"]), float(data.get("stamp", now)), data.get("pivot_ok", True) is not False
        here = float(data.get("heading_here_deg", deg))
        off = None if data.get("off_route_m") is None else float(data["off_route_m"])
        s = None if data.get("s") is None else float(data["s"])
    except (ValueError, TypeError, KeyError):
        return None
    return (deg, stamp, ok, here, off, s) if math.isfinite(deg) and math.isfinite(here) and abs(deg) <= 180.0 else None


#: a corridor side needs this many near edge rows; fewer is a corner of floor, not a line
CORRIDOR_MIN_POINTS = 5


def way_corridor(near_edges, source, current):
    """keep_debug boundaries for CORE's corridor (lane_containment) from the way's near edges
    (way_target near_edges_m), moved from the way's frame to this one: one straight fit per seen
    side, `edge_m` (the drivable edge itself, not a paint centre)."""
    out = []
    for side, points in (near_edges or {}).items():
        if len(points) < CORRIDOR_MIN_POINTS:
            continue
        xy = np.array([_to_current(p, source, current) for p in points])
        if np.ptp(xy[:, 0]) < 0.02:
            continue
        (slope, offset), cov = np.polyfit(xy[:, 0], xy[:, 1], 1, cov=True)
        ends = [[round(float(x), 3), round(float(slope * x + offset), 3)] for x in (xy[:, 0].min(), xy[:, 0].max())]
        out.append(dict(side=side, selected=True, edge_m=True, ends_m=ends,
                        slope_sd=float(math.sqrt(max(cov[0, 0], 0.0))), offset_sd=float(math.sqrt(max(cov[1, 1], 0.0)))))
    return out


def _path_of(steer, half):
    path = getattr(steer, "_expected_path", None)
    if path is None:
        path = ExpectedPath(half, error_for_target=steer.pursuit_error)
        steer._expected_path = path
    return path


def _remember_path(last, view):
    last["expected_path_state"] = view["state"]
    last["expected_path_s_m"] = view["s_m"]
    path_m = view["path_m"]
    last["expected_path_m"] = None if path_m is None else [[float(point[0]), float(point[1])] for point in path_m]


def _aligned_guide(guide, stamp, pose_at):
    """Express a source-relative route prior in the consuming camera's body frame."""
    if guide is None or not 0.0 <= stamp - guide[1] < GUIDE_MAX_AGE_S:
        return None
    if len(guide) > 6 and guide[6] + 1e-6 < LOOKAHEAD_M:
        return None  # A destination-close tangent is not the full pursuit preview.
    then, current = pose_at(guide[1]), pose_at(stamp)
    if not _valid_pose(then, guide[1]) or not _valid_pose(current, stamp):
        return None
    yaw_change = math.degrees(current[2] - then[2])
    wrap = lambda angle: (angle + 180.0) % 360.0 - 180.0
    return (wrap(guide[0] - yaw_change), guide[1], guide[2],
            wrap(guide[3] - yaw_change), guide[4], guide[5])


def _route_transition(steer, identity):
    """Forget guide-dependent decisions, retaining observed boundaries and crosswalks."""
    previous = getattr(steer, '_route_identity', None)
    steer._route_identity = identity
    if previous == identity:
        return
    steer._last_out = steer._pending = steer._smoothed = None
    steer._side = steer._pivot = steer._pivot_yaw = steer._route_exit = None
    steer._misaligned_since = None
    steer._expected_path = None


def keep_step(steer, worker, last, ground, x_offset, half, pose_at, stamp, wall, guide=None, *, guide_generation=None):
    """(error, confidence) or None for this frame, and whether the drivable path decided it.
    `last` is the keeper's keep_debug dict (updated in place); pose_at(stamp) is odometry."""
    last.pop('route_guide', None)
    route_prior = guide if isinstance(guide, SelectedRoutePrior) else None
    # D-769 rev 2: drifted off the route centre beyond ROUTE_SIDE_M, the next way starts from the seen run on the
    # route's side of the image centre (a line under the robot; r36 followed the strip beyond the lane's left line)
    left = getattr(route_prior, 'off_route_left_m', None) if route_prior and route_prior.source_stamp_s <= stamp < route_prior.valid_until_s else None
    worker.route_side = None if left is None or abs(left) <= ROUTE_SIDE_M else ('right' if left > 0 else 'left')
    if isinstance(guide, SelectedRoutePrior):
        if guide.source_stamp_s <= stamp < guide.valid_until_s:
            last['route_guide'] = guide.model_dump()
            guide = (guide.heading_ahead_deg, guide.source_stamp_s, False,
                     guide.heading_here_deg, guide.off_route_m, guide.s_m, guide.ahead_m)
        else:
            guide = None
    aligned = _aligned_guide(guide, stamp, pose_at)
    identity = None if route_prior is None or aligned is None else (
        route_prior.leg_id, route_prior.map_id, route_prior.map_revision, guide_generation)
    _route_transition(steer, identity)
    path = _path_of(steer, half)
    bars = worker.used_crosswalk
    if last.get('crosswalk') is not None or (bars is not None and int(bars[CROSSWALK_NEAR_ROW:].sum()) >= CROSSWALK_MIN_PX):
        steer.crosswalk(pose_at(stamp))
    latest = worker.latest_way(WAY_MAX_AGE_S)
    # The keeper's junction sighting (its paint is the way's boundary here) stays in keep_debug: CORE
    # carries out Fleet's junction instruction only on a sighting, and an instruction never carried
    # out kept CORE busy, so Fleet could not send the next junction and stopped the trip at it
    # (v2 Gazebo lap r18: NE armed until NW, junction_no_window).
    if (guide is not None and 0.0 <= stamp - guide[1] <= CONTEXT_FRESH_S
            and guide[4] is not None and guide[4] > OFF_ROUTE_HOLD_M):
        _remember_path(last, path.update(None, stamp, {}))
        last.update(strategy='none', reason='off_route_hold', error=None, confidence=None, target_m=None,
                    drivable_steer=dict(off_route_m=round(guide[4], 3)))
        return None, True
    guide = aligned
    if latest is not None:
        way, way_stamp = latest
        extra = {} if wall is None or abs(stamp - wall[1]) >= WALL_MAX_AGE_S else dict(
            wall_ahead_m=wall[0], side_clear_m=wall[2], front_sector_m=wall[3] if len(wall) > 3 else None)
        if guide is not None and abs(stamp - guide[1]) < GUIDE_MAX_AGE_S:
            age = abs(stamp - guide[1])
            then, now = pose_at(guide[1]), pose_at(stamp)
            ds = 0.0 if then is None or now is None else math.hypot(now[0] - then[0], now[1] - then[1])
            fresh = age <= CONTEXT_FRESH_S
            s = None if guide[5] is None else guide[5] + ds
            last['context'] = dict(s=None if s is None else round(s, 3), age_s=round(age, 2),
                                   confidence=round(math.exp(-age / 2.0) * math.exp(-ds / 0.3), 3))
            extra.update(guide_s=s, guide_fresh=fresh)
            extra['guide_deg'], extra['guide_pivot_ok'], extra['guide_here_deg'] = guide[0], guide[2], guide[3]
        source = pose_at(way_stamp)
        current = pose_at(stamp)
        if not _valid_pose(source, way_stamp) or not _valid_pose(current, stamp):
            _remember_path(last, path.update(None, stamp, {}))
            last.update(strategy='none', reason='drivable_odometry_unavailable', error=None,
                        confidence=None, target_m=None)
            return None, True
        error, confidence, info = steer.update(way, way_stamp, ground, x_offset, half,
            source, current, observed_only=route_prior is not None, current_stamp=stamp, **extra)
        # Missing source odometry drops the hypothesis; cached inferences count once.
        _remember_path(last, path.update(source, stamp, info, observation_stamp=way_stamp,
                                        current_pose=current))
        last.update(strategy=info['strategy'], drivable_steer=info, reason=info.get('reason'),
                    error=None if error is None else round(error, 3), confidence=confidence,
                    target_m=list(info.get('target_now_m') or info['target_m'] or []) or None,
                    # the corridor CORE checks the body against is the way's, not the tape keeper's fit
                    boundaries=way_corridor(info.get('near_edges_m'), source, current))
        last['drivable_way'] = way_runs(way, stamp - way_stamp)   # the preview draws what steered (sampled)
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
    held = path.hold(pose, stamp)
    _remember_path(last, held)
    steer.lost(stamp)
    if held is not None and held["error"] is not None:
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
    # CORE's front sector (motion_limits front_half_width_deg 45) as CORE measures it: LiDAR range, from the mount
    lx, ly = body.lidar_x_m, body.lidar_y_m
    front = min((math.hypot(x - lx, y - ly) for x, y in view.points
                 if x > lx and abs(math.atan2(y - ly, x - lx)) <= math.pi / 4), default=None)
    return ahead, side, front
