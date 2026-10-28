"""Capture a selected-trip direction at the exact pose used for authority."""

import math

from core_common.protocol.lane_route_guide import AuthorityRouteGuide
from fleet.routing.direction import route_direction
from fleet.server.trip_geometry import record_bend_candidate

MAX_AGE_S = 1.
#: D-573 rev 8: map walls within this along the lane ahead and this far across, near parallel to it
WALL_AHEAD_M, WALL_ACROSS_M, WALL_SKEW_SIN = 1., .4, math.sin(math.radians(20.))


def wall_sides(walls, fx, fy, tangent, half_width):
    """(left, right, ahead): across the lane from its centre point (fx, fy) to the nearest map wall face beside
    it, each the face's outermost point over [0, ahead], and ahead = how far along the lane the named walls run
    (at most WALL_AHEAD_M; CORE clips only that far, so an opening past a wall's end is looked at). A turned
    wall reads farther, never nearer. None = no such wall: none starting at the robot, or one reaching into the
    lane. shortcut: one segment per side, joined segments are not chained."""
    c, s = math.cos(tangent), math.sin(tangent)
    sides, reach = {1: None, -1: None}, {}
    for wall in walls:
        (u1, v1), (u2, v2) = ((c * (x - fx) + s * (y - fy), -s * (x - fx) + c * (y - fy)) for x, y in wall.face)
        length = math.hypot(u2 - u1, v2 - v1)
        if abs(v2 - v1) > WALL_SKEW_SIN * length or min(u1, u2) > 0. or max(u1, u2) <= 0.:
            continue
        end = min(max(u1, u2), WALL_AHEAD_M)
        at = [v1 + (v2 - v1) * (u - u1) / (u2 - u1) for u in (0., end)]
        near, far = min(map(abs, at)), max(map(abs, at))
        side = 1 if at[0] > 0 else -1
        if at[0] * at[1] > 0 and near >= half_width and far <= WALL_ACROSS_M and (sides[side] is None or far < sides[side]):
            sides[side], reach[side] = far, end
    ahead = min(reach.values(), default=None)
    return sides[1], None if sides[-1] is None else -sides[-1], ahead


def _context(live):
    return (live.route_rev, live.trim_m, live.view['map_version'], live.at,
            tuple((s['edge_id'], s['forward'], s['s_from'], s['s_to']) for s in live.segments))


def route_guided(live):
    """A route-guided robot (line_follow_route_guide) takes bends and branches from the selected-route
    prior on its authority, keeping right without one; CORE never carries out a bend or turn instruction
    for it, so one stayed armed and the next junction stopped the trip without a window (v2 Gazebo lap
    r18/r19 at NW). Fleet sends it stops only."""
    return (live.view.get('caps') or {}).get('line_follow_route_guide') is True


def _skip(live, reason):
    """Why no route prior was captured or sent this step, shown in the trip view (diagnostics only)."""
    if (live.view.get('caps') or {}).get('line_follow_route_guide') is True:
        detail = live.view.setdefault('detail', {})
        detail['route_guide_skip'] = reason
        counts = detail.setdefault('route_guide_skips', {})   # per reason kind, for a run's whole story
        counts[reason.split(' ')[0]] = counts.get(reason.split(' ')[0], 0) + 1


def record_trip_guidance(live, pose, active, index, s, now):
    record_bend_candidate(live, pose, active, index, s)
    live.route_guide_sample = None
    if ((live.view.get('caps') or {}).get('line_follow_route_guide') is not True
            or live.view.get('hold') is not None or active is None
            or active[0] != live.view['map_version'] or pose.map_id != active[1].map_id
            or pose.state != 'LOCALIZED' or pose.odom_stamp != live.at_stamp):
        return _skip(live, 'hold' if live.view.get('hold') is not None else 'pose_or_map')
    values = (pose.x, pose.y, pose.yaw, pose.age_s, pose.odom_stamp, now, live.view.get('pose_observed_at'))
    if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
        return _skip(live, 'nonfinite')
    age = pose.age_s + (now - live.view['pose_observed_at'])
    if not 0. <= pose.age_s <= age < MAX_AGE_S:
        return _skip(live, f'pose_age {age:.2f}')
    direction = route_direction(live.graph, live.segments, index, s, pose.yaw)
    if direction is None or direction['ahead_m'] <= 0.:
        return _skip(live, f'no_direction {index}:{s:.3f}')
    arc = live.arc(index)
    off, along, _ = arc.project(pose.x, pose.y)
    fx, fy, tangent = arc.point_at(along)   # D-769 rev 2: signed, + left of the travel direction
    left = math.cos(tangent) * (pose.y - fy) - math.sin(tangent) * (pose.x - fx)
    # D-573 rev 8: walls across the lane direction CORE uses (pose yaw + heading_here), from the lane centre
    lane = pose.yaw + math.radians(direction['heading_here_deg'])
    across = math.cos(lane) * (pose.y - fy) - math.sin(lane) * (pose.x - fx)
    edge = next((e for e in active[1].edges if e.id == live.segments[index]['edge_id']), None)
    wall_l, wall_r, ahead = wall_sides(active[1].walls, fx, fy, lane, edge.width_m / 2) if edge else (None,) * 3
    walls = dict(wall_left_m=None if wall_l is None or not 0. < wall_l - across <= 2. else round(wall_l - across, 4),
                 wall_right_m=None if wall_r is None or not -2. <= wall_r - across < 0. else round(wall_r - across, 4))
    if ahead is None or ahead < 1e-3:   # a wall ending at the robot names nothing (contract: ahead > 0)
        walls = dict(wall_left_m=None, wall_right_m=None)
    elif walls['wall_left_m'] is not None or walls['wall_right_m'] is not None:
        walls['wall_ahead_m'] = round(ahead, 4)
    guide = AuthorityRouteGuide(map_id=pose.map_id, map_revision=active[0], off_route_m=off,
        off_route_left_m=round(max(-2., min(2., left)), 4), max_age_s=MAX_AGE_S, **walls, **direction)
    live.route_guide_sample = (_context(live), pose.odom_stamp, now, age, guide.model_dump())
    live.view.get('detail', {}).pop('route_guide_skip', None)


def guide_for_authority(live, stamp, now):
    sample = getattr(live, 'route_guide_sample', None)
    if (sample is None or not live.open or live.view.get('hold') is not None
            or (live.view.get('caps') or {}).get('line_follow_route_guide') is not True):
        return None
    context, source, captured, age, guide = sample
    if (context != _context(live) or stamp != source or live.at_stamp != source
            or not 0. <= now - captured < MAX_AGE_S - age):
        _skip(live, 'send: ' + ('context' if context != _context(live) else 'stamp' if stamp != source or live.at_stamp != source
                                else f'aged {now - captured + age:.2f}'))
        return None
    return dict(guide)
