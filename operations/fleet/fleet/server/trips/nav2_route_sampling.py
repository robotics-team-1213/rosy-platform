"""Sample site road segments for a native Nav2 route."""
import math

from fleet.routing.execute import arc_id
from fleet.server.trip_geometry import _wall_clearance

NAV2_ROUTE_STEP_M = 0.12
#: A curve tighter than this radius is sampled every NAV2_CURVE_STEP_M: on the 0.135 m U-turn a 0.12 m chord
#: cuts 14 mm inside the lane centre, a 0.05 m chord 2 mm (2026-11-27 live run, rosy_45 on loop_right). After a
#: resend the first leg is the chord to the first point Nav2 keeps (RemovePassedGoals 0.09 m): 0.09-0.21 m with
#: the road step, 0.09-0.14 m with this one.
NAV2_CURVE_RADIUS_M = 0.30
NAV2_CURVE_STEP_M = 0.05
#: Off the lane centre by more than NAV2_ROUTE_MIN_GAP_M the first route point lies this far ahead of the robot
#: plus twice the offset (at most NAV2_RECENTRE_MAX_M), so it rejoins at a shallow angle, never by a turn on the
#: spot at its own projection. On a tight curve only the base distance: farther ahead cuts the arc again.
NAV2_RECENTRE_AHEAD_M = 0.10
NAV2_RECENTRE_MAX_M = 0.20
NAV2_ROUTE_MAX_POINTS = 64
NAV2_ROUTE_MIN_GAP_M = 0.03
NAV2_CLOSED_LOOP_SPLIT_M = 0.60
NAV2_SPLIT_MIN_SPAN_M = 0.25
NAV2_SPLIT_WALL_CLEAR_M = 0.22


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _split_closed_loop(pts: list[tuple[float, float, float, str]], start_xy: tuple[float, float], walls=()) -> None:
    """Promote one straight-segment waypoint to ``stop`` so Nav2 cannot short-circuit a closed loop."""
    if len(pts) < 2:
        return
    end_xy = (pts[-1][0], pts[-1][1])
    if math.hypot(end_xy[0] - start_xy[0], end_xy[1] - start_xy[1]) >= NAV2_CLOSED_LOOP_SPLIT_M:
        return
    spans = [
        min(
            math.hypot(p[0] - start_xy[0], p[1] - start_xy[1]),
            math.hypot(p[0] - end_xy[0], p[1] - end_xy[1]),
        )
        for p in pts[:-1]
    ]
    max_span = max(spans)
    if max_span < NAV2_SPLIT_MIN_SPAN_M:
        return
    min_req = max(NAV2_SPLIT_MIN_SPAN_M, 0.5 * max_span)
    cands = [i for i in range(len(pts) - 1) if spans[i] >= min_req]

    def rank(i: int) -> tuple[bool, bool, float, float]:
        lo, hi = max(0, i - 2), min(len(pts) - 1, i + 2)
        turn = max(abs(_wrap_angle(pts[k + 1][2] - pts[k][2])) for k in range(lo, hi))
        tight = bool(walls) and _wall_clearance(pts[i][0], pts[i][1], walls) < NAV2_SPLIT_WALL_CLEAR_M
        return (tight, turn > 0.25, round(turn, 2), -spans[i])

    mid = min(cands, key=rank)
    mx, my, myaw, _ = pts[mid]
    pts[mid] = (mx, my, myaw, "stop")


def sample_nav2_route(
    graph,
    segments: list[dict],
    index: int,
    s: float,
    end_index: int,
    *,
    step_m: float = NAV2_ROUTE_STEP_M,
    max_points: int = NAV2_ROUTE_MAX_POINTS,
    walls=(),
    curve_step_m: float = NAV2_CURVE_STEP_M,
    here: tuple[float, float] | None = None,
    end_s: float | None = None,
    recentre: bool = False,
) -> list[tuple[float, float, float, str]]:
    """Sample road-centerline ``pass`` points ending with one ``stop`` point along ``segments[index..end_index]``.

    ``here`` is the robot's site position: off the centreline the first pass point moves ahead (NAV2_RECENTRE_*).
    ``end_s`` ends the last segment mid-edge (a table-cut hold point) instead of at its ``s_to``.
    ``recentre`` moves the first point ahead even within NAV2_ROUTE_MIN_GAP_M of the centreline (a recovery resend,
    or any caller that must rejoin at a shallow angle from a small offset, such as a charge-bay re-approach)."""
    spans = []
    for k in range(index, end_index + 1):
        seg = segments[k]
        arc = graph.arcs[arc_id(seg)]
        stop_s = min(seg["s_to"], end_s) if k == end_index and end_s is not None else seg["s_to"]
        cur_s = min(max(seg["s_from"], s), stop_s) if k == index else seg["s_from"]
        if stop_s - cur_s > 1e-6:
            spans.append((arc, cur_s, stop_s))
    if not spans:
        last_seg = segments[end_index]
        stop_s = last_seg["s_to"] if end_s is None else min(last_seg["s_to"], end_s)  # never past a hold point
        fx, fy, fyaw = graph.arcs[arc_id(last_seg)].point_at(stop_s)
        return [(fx, fy, fyaw, "stop")]
    start_xy = spans[0][0].point_at(spans[0][1])[:2]
    total_m = sum(s1 - s0 for _arc, s0, s1 in spans)
    spacing = max(step_m, total_m / max(1, max_points - 1))

    def point_at_distance(dist: float) -> tuple[float, float, float]:
        rem = dist
        for arc, s0, s1 in spans:
            length = s1 - s0
            if rem <= length + 1e-9:
                return arc.point_at(min(s0 + rem, s1))
            rem -= length
        arc, _s0, s1 = spans[-1]
        return arc.point_at(s1)

    def sampled(curve: float) -> tuple[list, bool]:
        def step_after(d: float, yaw: float) -> float:
            ahead = point_at_distance(min(d + spacing, total_m))[2]
            return min(curve, spacing) if abs(_wrap_angle(ahead - yaw)) * NAV2_CURVE_RADIUS_M > spacing else spacing

        out: list[tuple[float, float, float, str]] = []
        sx, sy, syaw = point_at_distance(0.0)
        d = step_after(0.0, syaw)
        if here is not None:
            ahead = (sx - here[0]) * math.cos(syaw) + (sy - here[1]) * math.sin(syaw)  # < 0: progress lags the robot
            lat = abs((sy - here[1]) * math.cos(syaw) - (sx - here[0]) * math.sin(syaw))
            if lat > NAV2_ROUTE_MIN_GAP_M or recentre:
                # judged from the lane itself: the even-spacing fallback has no curve step to tell it by
                tight = abs(_wrap_angle(point_at_distance(min(spacing, total_m))[2] - syaw)) * NAV2_CURVE_RADIUS_M > spacing
                reach = NAV2_RECENTRE_AHEAD_M if tight else min(NAV2_RECENTRE_AHEAD_M + 2 * lat, NAV2_RECENTRE_MAX_M)
                d = max(d, reach - ahead)
        while d < total_m - NAV2_ROUTE_MIN_GAP_M and len(out) < max_points - 1:
            px, py, pyaw = point_at_distance(d)
            if not out or math.hypot(px - out[-1][0], py - out[-1][1]) >= NAV2_ROUTE_MIN_GAP_M:
                out.append((px, py, pyaw, "pass"))
            d += step_after(d, pyaw)
        return out, d < total_m - NAV2_ROUTE_MIN_GAP_M

    pts, cut = sampled(curve_step_m)
    if cut:  # shortcut: one even spacing when dense curves do not fit max_points; split the route to go finer
        pts, _ = sampled(spacing)
    fx, fy, fyaw = spans[-1][0].point_at(spans[-1][2])
    while pts and math.hypot(fx - pts[-1][0], fy - pts[-1][1]) < NAV2_ROUTE_MIN_GAP_M:
        pts.pop()
    pts.append((fx, fy, fyaw, "stop"))
    _split_closed_loop(pts, start_xy, walls=walls)
    return pts
