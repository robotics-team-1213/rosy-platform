"""Capture a selected-trip direction at the exact pose used for authority."""

import math

from core_common.protocol.lane_route_guide import AuthorityRouteGuide
from fleet.routing.direction import route_direction
from fleet.server.trip_ports import record_bend_candidate

MAX_AGE_S = 1.


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
        live.view.setdefault('detail', {})['route_guide_skip'] = reason


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
    guide = AuthorityRouteGuide(map_id=pose.map_id, map_revision=active[0], off_route_m=off,
        off_route_left_m=round(max(-2., min(2., left)), 4), max_age_s=MAX_AGE_S, **direction)
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
