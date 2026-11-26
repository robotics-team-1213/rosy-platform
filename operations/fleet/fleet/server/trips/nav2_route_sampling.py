"""Sample site road segments for a native Nav2 route."""
import math

from fleet.routing.execute import arc_id
from fleet.server.trip_geometry import _wall_clearance

NAV2_ROUTE_STEP_M = 0.12
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
) -> list[tuple[float, float, float, str]]:
    """Sample road-centerline ``pass`` points ending with one ``stop`` point along ``segments[index..end_index]``."""
    spans = []
    for k in range(index, end_index + 1):
        seg = segments[k]
        arc = graph.arcs[arc_id(seg)]
        cur_s = min(max(seg["s_from"], s), seg["s_to"]) if k == index else seg["s_from"]
        if seg["s_to"] - cur_s > 1e-6:
            spans.append((arc, cur_s, seg["s_to"]))
    if not spans:
        last_seg = segments[end_index]
        fx, fy, fyaw = graph.arcs[arc_id(last_seg)].point_at(last_seg["s_to"])
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

    pts: list[tuple[float, float, float, str]] = []
    d = spacing
    while d < total_m - NAV2_ROUTE_MIN_GAP_M and len(pts) < max_points - 1:
        px, py, pyaw = point_at_distance(d)
        if not pts or math.hypot(px - pts[-1][0], py - pts[-1][1]) >= NAV2_ROUTE_MIN_GAP_M:
            pts.append((px, py, pyaw, "pass"))
        d += spacing
    fx, fy, fyaw = spans[-1][0].point_at(spans[-1][2])
    while pts and math.hypot(fx - pts[-1][0], fy - pts[-1][1]) < NAV2_ROUTE_MIN_GAP_M:
        pts.pop()
    pts.append((fx, fy, fyaw, "stop"))
    _split_closed_loop(pts, start_xy, walls=walls)
    return pts
