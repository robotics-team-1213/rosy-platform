"""Selected-trip geometry for a direction prior; never a movement permission.

The caller owns MapPose freshness/frame validation and transport lifetime. This
function uses only the plan's directed arcs, never nearest-lane selection.
"""

import math

from fleet.routing.execute import arc_id

# plan_trip serializes segment stations to four decimal places (metres).
STATION_ROUNDING_M = .000050001


def _selected(graph, segment):
    arc = graph.arcs[arc_id(segment)]
    start, end = segment["s_from"], segment["s_to"]
    if type(end) in (int, float) and abs(end - arc.length_m) <= STATION_ROUNDING_M:
        end = arc.length_m
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (start, end)) or not 0 <= start < end <= arc.length_m:
        raise ValueError("invalid selected segment")
    return arc, start, end


def route_direction(graph, segments, index, s, yaw, lookahead_m=.25):
    """Relative here/ahead headings and plan station, or None for invalid geometry.

    Preview ends at a partial destination or before free-space driving. It may
    cross only the selected contiguous lane segments. It supplies neither pivot
    permission nor evidence that the intervening floor is visible or traversable.
    """
    if (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(segments)
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                       for v in (s, yaw, lookahead_m)) or not 0 < lookahead_m <= 2.):
        return None
    try:
        arc, start, end = _selected(graph, segments[index])
        if arc.drive_mode != "lane" or not start - STATION_ROUNDING_M <= s <= end + STATION_ROUNDING_M:
            return None
        s = min(end, max(start, s))
        station = s - start
        for segment in segments[:index]:
            _, previous_start, previous_end = _selected(graph, segment)
            station += previous_end - previous_start
        here = arc.point_at(s)[2]
        remaining, travelled, cursor = lookahead_m, 0., s
        while True:
            step = min(remaining, end - cursor)
            travelled += step
            remaining -= step
            ahead = arc.point_at(cursor + step)[2]
            if remaining <= 1e-9 or index + 1 == len(segments):
                break
            following, next_start, next_end = _selected(graph, segments[index + 1])
            if following.drive_mode != "lane":
                break
            if (abs(end - arc.length_m) > 1e-6 or abs(next_start) > 1e-6
                    or arc.end_place != following.start_place
                    or math.dist(arc.polyline[-1], following.polyline[0]) > 1e-6):
                return None
            index += 1
            arc, cursor, end = following, next_start, next_end
        relative = lambda angle: math.degrees(math.atan2(math.sin(angle - yaw), math.cos(angle - yaw)))
        return dict(heading_here_deg=relative(here), heading_ahead_deg=relative(ahead),
                    ahead_m=travelled, s_m=station)
    except (KeyError, TypeError, ValueError, IndexError):
        return None
