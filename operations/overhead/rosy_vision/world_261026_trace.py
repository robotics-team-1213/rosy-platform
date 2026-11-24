"""Sub-pixel map graph tracer on a rectified ``world_261026`` plane."""

from __future__ import annotations

import math

import numpy as np


def trace_world_261026_graph(
    white_p: np.ndarray, pink_p: np.ndarray, yellow_p: np.ndarray,
    min_x: float, max_y: float, ppm: float, out_h: int,
) -> tuple[list[dict], list[dict]]:
    def px_to_map(u, v):
        return min_x + (u + 0.5) / ppm, max_y - (v + 0.5) / ppm

    v_bar_lo, v_bar_hi = int((max_y - 0.055) * ppm), int((max_y - (-0.005)) * ppm)
    bar_xs, bar_ys = [], []
    for x0, x1 in [(-0.56, -0.45), (-0.36, -0.24), (-0.14, -0.02), (0.08, 0.19)]:
        u0, u1 = int((x0 - min_x) * ppm), int((x1 - min_x) * ppm)
        ys_b, xs_b = np.nonzero(pink_p[v_bar_lo:v_bar_hi, u0:u1])
        if len(ys_b) >= 10:
            mx, my = px_to_map(np.median(xs_b) + u0, np.median(ys_b) + v_bar_lo)
            bar_xs.append(mx)
            bar_ys.append(my)
    poly_bar_y = np.polyfit(bar_xs, bar_ys, 1) if len(bar_xs) >= 2 else np.array([0.0, 0.025])

    def _fit_pink_leg(x_lo: float, x_hi: float, default_x0: float, default_slope: float) -> np.ndarray:
        u0, u1 = int((x_lo - min_x) * ppm), int((x_hi - min_x) * ppm)
        lx, ly = [], []
        for ym in np.linspace(-0.002, -0.10, 16):
            v = int(round((max_y - ym) * ppm))
            xs = np.nonzero(pink_p[max(0, v - 1):min(out_h, v + 2), u0:u1])[1]
            if len(xs) >= 3:
                lx.append(min_x + (float(np.median(xs)) + u0 + 0.5) / ppm)
                ly.append(ym)
        return np.polyfit(ly, lx, 1) if len(ly) >= 4 else np.array([default_slope, default_x0])

    leg_l_poly = _fit_pink_leg(-0.68, -0.56, -0.607, 0.49)
    leg_r_poly = _fit_pink_leg(0.19, 0.30, 0.238, -0.45)

    x_elbow_l = round(float(np.polyval(leg_l_poly, round(float(np.polyval(poly_bar_y, -0.596)), 4))), 4)
    y_elbow_l = round(float(np.polyval(poly_bar_y, x_elbow_l)), 4)
    x_elbow_r = round(float(np.polyval(leg_r_poly, round(float(np.polyval(poly_bar_y, 0.228)), 4))), 4)
    y_elbow_r = round(float(np.polyval(poly_bar_y, x_elbow_r)), 4)
    y_tip_l = y_tip_r = -0.048
    x_tip_l = round(float(np.polyval(leg_l_poly, y_tip_l)), 4)
    x_tip_r = round(float(np.polyval(leg_r_poly, y_tip_r)), 4)

    bay_P, bay_C, bay_polylines = [], [], []
    for x_nom, y_hi in [(-0.414, 0.21), (-0.190, 0.21), (0.032, 0.46)]:
        u0, u1 = int((x_nom - 0.040 - min_x) * ppm), int((x_nom + 0.040 - min_x) * ppm)
        v0, v1 = int((max_y - y_hi) * ppm), int((max_y - 0.06) * ppm)
        ys_s, xs_s = np.nonzero(pink_p[v0:v1, u0:u1])
        y_p = round(float(np.polyval(poly_bar_y, x_nom)), 4)
        if len(xs_s) >= 20:
            mxs, mys = px_to_map(xs_s + u0, ys_s + v0)
            x_med, y_ref = float(np.median(mxs)), float(np.median(mys))
            slope = float(np.clip(np.polyfit(mys, mxs, 1)[0], -0.008, 0.008))
            x_p, x_c = round(x_med + slope * (y_p - y_ref), 4), round(x_med + slope * (0.470 - y_ref), 4)
        else:
            x_p = x_c = x_nom
        bay_P.append((x_p, y_p))
        bay_C.append((x_c, 0.470))
        bay_polylines.append([[round(x_p + (x_c - x_p) * t, 4), round(y_p + (0.470 - y_p) * t, 4)]
                              for t in (0.0, 0.33, 0.67, 1.0)])

    def fit_road_curve(x_samples, y_lo_b, y_hi_b):
        xs_c, ys_c = [], []
        v0, v1 = int((max_y - y_hi_b) * ppm), int((max_y - y_lo_b) * ppm)
        for xs_val in x_samples:
            u0, u1 = int((xs_val - 0.02 - min_x) * ppm), int((xs_val + 0.02 - min_x) * ppm)
            ys_w, xs_w = np.nonzero(white_p[v0:v1, u0:u1])
            if len(ys_w) >= 6:
                mx, my = px_to_map(np.median(xs_w) + u0, np.median(ys_w) + v0)
                xs_c.append(mx)
                ys_c.append(my)
        return np.polyfit(xs_c, ys_c, 2) if len(xs_c) >= 5 else np.array([0.0, 0.0, 0.5 * (y_lo_b + y_hi_b)])

    poly_top_w = fit_road_curve(
        [x for x in np.linspace(-1.0, 1.0, 41) if not (-0.82 < x < -0.55 or 0.16 < x < 0.44)], -0.175, -0.105)
    poly_div_w = fit_road_curve(np.linspace(-0.88, 0.88, 37), -0.40, -0.33)
    poly_bot_w = fit_road_curve(np.linspace(-1.0, 1.0, 41), -0.62, -0.55)
    poly_upper_lane, poly_lower_lane = 0.5 * (poly_top_w + poly_div_w), 0.5 * (poly_div_w + poly_bot_w)

    y_up = lambda x: round(float(np.polyval(poly_upper_lane, x)), 4)
    y_lo = lambda x: round(float(np.polyval(poly_lower_lane, x)), 4)
    y_top_line = lambda x: round(float(np.polyval(poly_top_w, x)), 4)

    s1_y = y_top_line(-0.680)
    s1_x = round(float(np.polyval(leg_l_poly, s1_y)), 4)
    s2_y = y_top_line(0.280)
    s2_x = round(float(np.polyval(leg_r_poly, s2_y)), 4)

    def _stop_x(mask_s: np.ndarray, x0: float, x1: float, y_hi: float, y_lo_b: float, default: float) -> float:
        u0, u1 = int((x0 - min_x) * ppm), int((x1 - min_x) * ppm)
        v0, v1 = int((max_y - y_hi) * ppm), int((max_y - y_lo_b) * ppm)
        xs = np.nonzero(mask_s[v0:v1, u0:u1])[1]
        return round(float(px_to_map(np.median(xs) + u0, 0)[0]), 4) if len(xs) >= 15 else default

    s3_x = _stop_x(yellow_p, 0.64, 0.75, -0.15, -0.35, 0.6987)
    s4_x = _stop_x(yellow_p, 0.10, 0.22, -0.40, -0.54, 0.1562)
    s5_x = _stop_x(yellow_p, 0.86, 0.97, -0.41, -0.54, -1.0)
    if s5_x < 0.0:
        s5_x = _stop_x(white_p, 0.86, 0.97, -0.41, -0.54, 0.9212)
    s3_y, s4_y, s5_y = y_up(s3_x), y_lo(s4_x), y_lo(s5_x)

    places = [
        {"id": "S1", "kind": "stop", "name": "S1 주차장 출구·수동 적재 정지선", "x": s1_x, "y": s1_y, "yaw": None},
        {"id": "S2", "kind": "stop", "name": "S2 주차장 입구 정지선", "x": s2_x, "y": s2_y, "yaw": None},
        {"id": "S3", "kind": "stop", "name": "S3 상단 하역 정지선 (cell_s)", "x": s3_x, "y": s3_y, "yaw": None},
        {"id": "S4", "kind": "stop", "name": "S4 하단 중앙 대기 정지선", "x": s4_x, "y": s4_y, "yaw": None},
        {"id": "S5", "kind": "stop", "name": "S5 하단 U턴 전 대기 정지선", "x": s5_x, "y": s5_y, "yaw": None},
        {"id": "J_in", "kind": "junction", "name": "주차장 입구 분기", "x": s2_x, "y": y_up(s2_x), "yaw": None},
        {"id": "J_out", "kind": "junction", "name": "주차장 출구 합류", "x": s1_x, "y": y_up(s1_x), "yaw": None},
        {"id": "P1", "kind": "junction", "name": "칸 1 앞", "x": bay_P[0][0], "y": bay_P[0][1], "yaw": None},
        {"id": "P2", "kind": "junction", "name": "칸 2 앞", "x": bay_P[1][0], "y": bay_P[1][1], "yaw": None},
        {"id": "P3", "kind": "junction", "name": "칸 3 앞", "x": bay_P[2][0], "y": bay_P[2][1], "yaw": None},
        {"id": "C1", "kind": "charge", "name": "충전 칸 1", "x": bay_C[0][0], "y": bay_C[0][1], "yaw": -1.5708},
        {"id": "C2", "kind": "charge", "name": "충전 칸 2", "x": bay_C[1][0], "y": bay_C[1][1], "yaw": -1.5708},
        {"id": "C3", "kind": "charge", "name": "충전 칸 3", "x": bay_C[2][0], "y": bay_C[2][1], "yaw": -1.5708},
    ]

    def _arc(cx, cy, rx, ry, start, step, n=12):
        return [[round(cx + rx * math.cos(start + step * i / n), 4),
                 round(cy + ry * math.sin(start + step * i / n), 4)] for i in range(n + 1)]

    def _edge(eid, frm, to, name, poly, speed=0.15, width=0.2, direction="one_way"):
        return {"id": eid, "from": frm, "to": to, "direction": direction, "drive_mode": "lane",
                "name": name, "polyline": poly, "robot_kinds": None, "speed_cap_mps": speed, "width_m": width}

    y_r_mid, ry_r = round(0.5 * (y_up(0.926) + y_lo(0.926)), 4), round(0.5 * (y_up(0.926) - y_lo(0.926)), 4)
    y_l_mid, ry_l = round(0.5 * (y_up(-0.926) + y_lo(-0.926)), 4), round(0.5 * (y_up(-0.926) - y_lo(-0.926)), 4)
    edges = [
        _edge("loop_right", "S5", "S3", "오른쪽 U턴",
              [[s5_x, s5_y], *_arc(0.926, y_r_mid, 0.131, ry_r, -math.pi / 2, math.pi), [s3_x, s3_y]]),
        _edge("upper_east", "S3", "J_in", "위 차선 (하역 후 분기)",
              [[round(float(x), 4), y_up(float(x))] for x in np.linspace(s3_x, s2_x, 6)]),
        _edge("upper_west", "J_in", "J_out", "위 차선 (주차장 앞 순환)",
              [[round(float(x), 4), y_up(float(x))] for x in np.linspace(s2_x, s1_x, 10)]),
        _edge("loop_left", "J_out", "S4", "왼쪽 U턴·아래 서쪽 차선 (S4 정지선까지)",
              [[s1_x, y_up(s1_x)], *_arc(-0.926, y_l_mid, 0.131, ry_l, math.pi / 2, math.pi),
               *[[round(float(x), 4), y_lo(float(x))] for x in np.linspace(-0.85, s4_x, 9)]]),
        _edge("lower_east", "S4", "S5", "아래 동쪽 차선 (S4 -> S5 정지선)",
              [[round(float(x), 4), y_lo(float(x))] for x in np.linspace(s4_x, s5_x, 7)]),
        _edge("park_gate_in", "J_in", "S2", "주차장 진입", [[s2_x, y_up(s2_x)], [s2_x, s2_y]], 0.08, 0.15),
        _edge("park_in", "S2", "P3", "분홍 유도선 (입구)",
              [[s2_x, s2_y], [x_tip_r, y_tip_r], [x_elbow_r, y_elbow_r], [bay_P[2][0], bay_P[2][1]]], 0.08, 0.15),
        _edge("bar_32", "P3", "P2", "분홍 유도선", [[bay_P[2][0], bay_P[2][1]], [bay_P[1][0], bay_P[1][1]]], 0.08, 0.15),
        _edge("bar_21", "P2", "P1", "분홍 유도선", [[bay_P[1][0], bay_P[1][1]], [bay_P[0][0], bay_P[0][1]]], 0.08, 0.15),
        _edge("park_out", "P1", "S1", "분홍 유도선 (출구)",
              [[bay_P[0][0], bay_P[0][1]], [x_elbow_l, y_elbow_l], [x_tip_l, y_tip_l], [s1_x, s1_y]], 0.08, 0.15),
        _edge("park_gate_out", "S1", "J_out", "주차장 합류", [[s1_x, s1_y], [s1_x, y_up(s1_x)]], 0.08, 0.15),
        _edge("bay_1", "P1", "C1", "칸 1 (후진 진입)", bay_polylines[0], 0.05, 0.18, "two_way"),
        _edge("bay_2", "P2", "C2", "칸 2 (후진 진입)", bay_polylines[1], 0.05, 0.18, "two_way"),
        _edge("bay_3", "P3", "C3", "칸 3 (후진 진입)", bay_polylines[2], 0.05, 0.18, "two_way"),
    ]
    return places, edges
