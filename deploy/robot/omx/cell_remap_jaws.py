"""Which jaw each remap mark is, so the remap maps the TCP (the jaws' middle), not one jaw (`calibrate.tcp_marks`).

A remap mark is one jaw (or both), not the TCP; the 2026-11-15 arm_a map followed one jaw 28 mm off the TCP and every
pivot bias then held that offset. With the TCP the jaws' middle, the reference jaw stands at TCP - o/2 and the other at
TCP + o/2 (o = jaw_side.other_mm at FK yaw + other_deg). A second blob of the same try that the map puts within
other_mm/2 of the opposite jaw makes the point a pair: (middle of both blobs, TCP). Labelling, in order:
1. pairs: 3+ points not on one line whose try saw exactly two blobs give the map from their middles; every mark is the
   jaw the map puts it nearer, refused when the two are within pivot.side_agree_mm of each other;
2. at most MAX_REMAP marks: every mark tried as either jaw (2**n affine fits), most confirmed pairs then lowest rms;
   choices as confirmed and within side_agree_mm rms whose maps differ by more than that at any mark are refused;
3. more marks (the real arm_a 17:47 remap: 14, its 3 pairs on one line): step 2 on MAX_REMAP of them (the pairs, then
   the most spread), then step 1's nearest-jaw rule for all from that map.
`cell_jaw_side` re-exports `remap_marks` and `tcp_geometry`.
"""
from __future__ import annotations

import math

import numpy as np

import cell_params as prm

MAX_REMAP = 12  # remap points labelled jointly by brute force (2**12 affine fits)


def tcp_geometry(params=None) -> dict:
    """The reference jaw about the TCP when the TCP is the jaws' middle: half of jaw_side.other_mm, opposite the other
    jaw (a `pivot.geometry` for maps whose marks are the TCP, record "marks": "tcp")."""
    return {"radius_mm": prm.get(params, "jaw_side.other_mm") / 2, "phase_deg": prm.get(params, "jaw_side.other_deg") + 180.0}


def _setup(points, params):
    other_m, other_deg = prm.get(params, "jaw_side.other_mm") / 1000, prm.get(params, "jaw_side.other_deg")
    o = np.array([(other_m * math.cos(math.radians(q["yaw"] + other_deg)), other_m * math.sin(math.radians(q["yaw"] + other_deg)))
                  for q in points])
    tcp = np.array([q["tcp"] for q in points], float)
    A = np.array([[q["pixel"][0], q["pixel"][1], 1.0] for q in points], float)
    others = [[b for b in q.get("blobs") or [] if math.dist(b[:2], q["pixel"]) > 1.0] for q in points]
    return other_m, o, tcp, A, others


def _partners(coef, s, o, tcp, others, other_m) -> dict:
    """{i: blob} for the points whose second blob the map puts within other_mm/2 of the opposite jaw."""
    out = {}
    for i, blobs in enumerate(others):
        gaps = [(math.dist(np.array([b[0], b[1], 1.0]) @ coef, tcp[i] - s[i] * o[i]), b) for b in blobs]
        gap, b = min(gaps, key=lambda g: g[0], default=(math.inf, None))
        if gap <= other_m / 2:
            out[i] = b
    return out


def _brute(points, params):
    """(refusal or None, sides as -0.5/+0.5, coef, record) over every choice of jaw per mark."""
    from itertools import product

    other_m, o, tcp, A, others = _setup(points, params)
    pinv, fits = np.linalg.pinv(A), []
    for choice in product((-0.5, 0.5), repeat=len(points)):
        s = np.array(choice)
        coef = pinv @ (tcp + s[:, None] * o)  # 3x2: arm = [u v 1] @ coef
        rms = math.sqrt(float(np.mean(np.sum((A @ coef - (tcp + s[:, None] * o)) ** 2, axis=1))))
        fits.append((-len(_partners(coef, s, o, tcp, others, other_m)), rms, s, coef))
    tol = prm.get(params, "pivot.side_agree_mm") / 1000
    fits.sort(key=lambda f: (f[0], f[1]))
    best = fits[0]
    near = [f for f in fits if f[0] == best[0] and f[1] <= best[1] + tol]
    spread = max(float(np.max(np.linalg.norm(A @ f[3] - A @ best[3], axis=1))) for f in near)
    record = {"next_rms_mm": [round(1000 * f[1], 2) for f in fits[1:4]], "map_spread_mm": round(1000 * spread, 1)}
    if spread > tol:
        return (f"jaw sides ambiguous: {len(near)} labellings with {-best[0]} seen pairs within {1000 * tol:.0f} mm rms "
                f"put the map {1000 * spread:.1f} mm apart"), None, None, record
    return None, best[2], best[3], record


def _nearest(points, coef, params):
    """(refusal or None, sides): each mark is the jaw the map puts it nearer."""
    _, o, tcp, A, _ = _setup(points, params)
    tol, sides = prm.get(params, "pivot.side_agree_mm") / 1000, []
    for i, seen in enumerate(A @ coef):
        d_ref, d_other = math.dist(seen, tcp[i] - o[i] / 2), math.dist(seen, tcp[i] + o[i] / 2)
        if abs(d_ref - d_other) <= tol:
            return f"jaw sides ambiguous: mark at {tuple(points[i]['tcp'])} within {1000 * tol:.0f} mm of both jaws", None
        sides.append(-0.5 if d_ref < d_other else 0.5)
    return None, np.array(sides)


def _pair_map(points, params):
    """The map from the middles of 3+ two-blob tries not on one line, or None."""
    _, _, tcp, _, others = _setup(points, params)
    idx = [i for i, b in enumerate(others) if len(b) == 1]
    if len(idx) < 3 or np.linalg.matrix_rank(np.c_[tcp[idx], np.ones(len(idx))], tol=1e-4) < 3:
        return None
    mid = np.array([[(points[i]["pixel"][0] + others[i][0][0]) / 2, (points[i]["pixel"][1] + others[i][0][1]) / 2, 1.0] for i in idx])
    return np.linalg.lstsq(mid, tcp[idx], rcond=None)[0]


def _spread_subset(points, others) -> list:
    """MAX_REMAP indices: the two-blob points first, then each next the farthest (arm) from those chosen."""
    chosen = [i for i, b in enumerate(others) if b][:MAX_REMAP] or [0]
    while len(chosen) < MAX_REMAP:
        chosen.append(max((i for i in range(len(points)) if i not in chosen),
                          key=lambda i: min(math.dist(points[i]["tcp"], points[j]["tcp"]) for j in chosen)))
    return sorted(chosen)


def remap_marks(points: list, params=None):
    """(refusal or None, [(pixel, arm_m)], record) for `points` [{"tcp", "yaw", "pixel", "blobs"}] (module doc)."""
    n = len(points)
    if n < 3:
        return None, [(tuple(q["pixel"]), tuple(q["tcp"])) for q in points], None  # too few for a map; the caller refuses
    other_m, o, tcp, A, others = _setup(points, params)
    if np.linalg.matrix_rank(A) < 3:
        return "remap marks degenerate (collinear or repeated)", None, None
    record, coef = {}, _pair_map(points, params)
    if coef is not None:
        record["path"] = "pairs"
        why, s = _nearest(points, coef, params)
    elif n <= MAX_REMAP:
        record["path"] = "brute"
        why, s, coef, extra = _brute(points, params)
        record.update(extra)
    else:
        sub = _spread_subset(points, others)
        record.update(path="anchored", anchors=sub)
        why, _, coef, extra = _brute([points[i] for i in sub], params)
        record.update(extra)
        if not why:
            why, s = _nearest(points, coef, params)
    if why:
        return why, None, record
    target = tcp + s[:, None] * o
    coef = np.linalg.lstsq(A, target, rcond=None)[0]  # the refit on all marks
    pairs = _partners(coef, s, o, tcp, others, other_m)
    marks = [(((q["pixel"][0] + pairs[i][0]) / 2, (q["pixel"][1] + pairs[i][1]) / 2), tuple(q["tcp"])) if i in pairs
             else (tuple(q["pixel"]), tuple(float(v) for v in target[i])) for i, q in enumerate(points)]
    rms = math.sqrt(float(np.mean(np.sum((A @ coef - target) ** 2, axis=1))))
    record.update(sides=["ref" if v < 0 else "other" for v in s], pairs=sorted(pairs), rms_mm=round(1000 * rms, 2))
    return None, marks, record
