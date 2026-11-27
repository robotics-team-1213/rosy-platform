"""Nav2 road route sampling: tight curves are sampled finely
(2026-11-27 live run: rosy_45 cut 10-12 cm inside the 0.135 m U-turn after each cancel and resend)."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

from fleet.server.nav2_route_sampling import (
    NAV2_CURVE_STEP_M, NAV2_ROUTE_STEP_M, sample_nav2_route)

R = 0.135


def _line(x0, y0, yaw, length):
    return NS(length_m=length, point_at=lambda s: (x0 + s * math.cos(yaw), y0 + s * math.sin(yaw), yaw))


def _uturn(cx, cy):  # right-hand half circle entered heading +x at (cx, cy - R)
    return NS(length_m=math.pi * R, point_at=lambda s: (
        cx + R * math.sin(s / R), cy - R * math.cos(s / R), s / R))


def _track():
    arcs = {"in:fwd": _line(0.0, -R, 0.0, 0.6), "turn:fwd": _uturn(0.6, 0.0), "out:fwd": _line(0.6, R, math.pi, 0.6)}
    segs = [{"edge_id": name, "forward": True, "s_from": 0.0, "s_to": arcs[name + ":fwd"].length_m}
            for name in ("in", "turn", "out")]
    return NS(arcs=arcs), segs


def _on_turn(p):
    return p[0] > 0.6 + 1e-6


def test_a_tight_curve_is_sampled_finely_and_a_straight_keeps_the_road_step():
    graph, segs = _track()
    pts = sample_nav2_route(graph, segs, 0, 0.0, 2)
    gaps = [(math.dist(a[:2], b[:2]), _on_turn(a) and _on_turn(b)) for a, b in zip(pts, pts[1:])]
    assert max(gap for gap, turn in gaps if turn) <= NAV2_CURVE_STEP_M + 1e-6
    assert sum(1 for _gap, turn in gaps if turn) >= 7  # 0.42 m of arc
    assert any(abs(gap - NAV2_ROUTE_STEP_M) < 1e-6 for gap, turn in gaps if not turn)
    # chord sagitta on the arc stays far inside the 0.043 m lane margin
    assert all(R - math.sqrt(R * R - (gap / 2) ** 2) < 0.003 for gap, turn in gaps if turn)
    assert pts[-1][3] == "stop"
    # start and end are 0.27 m apart, so one mid point is a stop (_split_closed_loop); it stays off the curve
    assert [p[3] for p in pts[:-1]].count("stop") == 1 and not any(_on_turn(p) for p in pts[:-1] if p[3] == "stop")


def test_a_resend_from_the_curve_keeps_its_first_kept_point_close():
    graph, segs = _track()
    pts = sample_nav2_route(graph, segs, 1, 0.2 * math.pi * R, 2)  # resent from on the U-turn
    start = graph.arcs["turn:fwd"].point_at(0.2 * math.pi * R)[:2]
    kept = next(p for p in pts if math.dist(p[:2], start) > 0.09)  # Nav2 drops goals within 0.09 m of the robot
    assert math.dist(kept[:2], start) <= 0.09 + NAV2_CURVE_STEP_M


def test_dense_curves_that_do_not_fit_fall_back_to_one_even_spacing():
    graph, segs = _track()
    pts = sample_nav2_route(graph, segs, 0, 0.0, 2, max_points=14)
    assert len(pts) <= 14 and pts[-1][3] == "stop"
    assert math.dist(pts[-1][:2], graph.arcs["out:fwd"].point_at(0.6)[:2]) < 1e-9
    assert max(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:])) <= 0.16
