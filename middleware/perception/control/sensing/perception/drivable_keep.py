"""Subject: line_observer's keep-mode glue for the drivable steering (D-597 amendments 2-3), ROS-free.

keep_step     one camera frame: crosswalk hold trigger, the drivable steer on the newest way (or the
              straight crosswalk crossing / a hold without a way), and the keep_debug fields.
scan_summary  one LaserScan's ranges -> (wall ahead in the body strip, base_link x; nearest wall
              beside the robot per side) with the URDF body (D-424).
"""

from __future__ import annotations

from core_common.robot_body import NOMINAL_BODY

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


def parse_guide(raw, now):
    """(heading_ahead_deg, stamp, pivot_ok, heading_here_deg) from a line/lane_guide JSON {heading_ahead_deg, stamp,
    pivot_ok (the body's sweep circle fits here per the map; default true)}, or None."""
    import json, math
    try:
        data = json.loads(raw)
        deg, stamp, ok = float(data["heading_ahead_deg"]), float(data.get("stamp", now)), data.get("pivot_ok", True) is not False
        here = float(data.get("heading_here_deg", deg))
    except (ValueError, TypeError, KeyError):
        return None
    return (deg, stamp, ok, here) if math.isfinite(deg) and math.isfinite(here) and abs(deg) <= 180.0 else None


def keep_step(steer, worker, last, ground, x_offset, half, pose_at, stamp, wall, guide=None):
    """(error, confidence) or None for this frame, and whether the drivable path decided it.
    `last` is the keeper's keep_debug dict (updated in place); pose_at(stamp) is odometry."""
    bars = worker.used_crosswalk
    if last.get('crosswalk') is not None or (bars is not None and int(bars[CROSSWALK_NEAR_ROW:].sum()) >= CROSSWALK_MIN_PX):
        steer.crosswalk(pose_at(stamp))
    latest = worker.latest_way(WAY_MAX_AGE_S)
    last.pop('junction_ahead_m', None)   # the way chose the branch: the tape keeper's junction HOLD does not apply
    if latest is not None:
        way, way_stamp = latest
        extra = {} if wall is None or abs(stamp - wall[1]) >= WALL_MAX_AGE_S else dict(wall_ahead_m=wall[0], side_clear_m=wall[2])
        if guide is not None and abs(stamp - guide[1]) < GUIDE_MAX_AGE_S:
            extra['guide_deg'], extra['guide_pivot_ok'], extra['guide_here_deg'] = guide[0], guide[2], guide[3]
        error, confidence, info = steer.update(way, way_stamp, ground, x_offset, half,
                                               pose_at(way_stamp), pose_at(stamp), **extra)
        last.update(strategy=info['strategy'], drivable_steer=info, reason=info.get('reason'),
                    error=None if error is None else round(error, 3), confidence=confidence,
                    target_m=list(info.get('target_now_m') or info['target_m'] or []) or None)
        return (None if error is None else (error, confidence)), True
    if steer._in_crosswalk(pose_at(stamp)):
        # bars (not drivable) fill the near view at a crosswalk: straight across (CORE D-573 gate)
        last.update(strategy='drivable_crosswalk_straight', reason=None, error=0.0, confidence=0.6)
        return (0.0, 0.6), True
    # No fresh way: hold. The tape keeper on the boundary strips must not steer in between
    # (its corners and one-sided targets fought the way, 8kcn 20261009T234748Z).
    steer.lost(stamp)
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
