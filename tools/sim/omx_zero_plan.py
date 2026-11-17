"""Pick 12-16 reported-joint poses for the OMX joint-zero capture (offline; moves nothing).

A pose is kept when the gripper marker is seen by the top camera at the prior zero AND at random zero errors of +-5 deg
(so a wrong prior does not push it out of view), the tool stays 30 mm above the table, and every joint sits inside
the arm's cell-config joint_min/joint_max. Poses are then picked greedily to minimise the worst per-joint 1-sigma the fit
would give (Fisher information of the corner pixels + the zero prior), so wrist pitch (j4) and roll (j5) vary as much as
the window allows, and ordered by nearest neighbour + 2-opt on summed joint travel.
Units out: `q_norm` (the cell config's `.pos` unit, what the supervised capture sends) and `q_deg` (= q_norm x 1.8).
"""
from __future__ import annotations

import numpy as np

from omx_zero_model import (JOINT_RANGE_DEG, JOINTS, NORM_DEG, PRIOR_DEG, PRIOR_SIGMA_DEG, camera_of, marker_points_mm,
                            pixels, view_ok)

PLAN_PX = 1.0  # marker noise the plan assumes for the predicted sigma (averaged frames, see fit)


def window_deg(config=None):
    """[lo, hi] deg per joint: the sim's range cut by config joint_min/joint_max (given in `.pos` norm units)."""
    win = np.array(JOINT_RANGE_DEG, float)
    for key, col in (("joint_min", 0), ("joint_max", 1)):
        for name, v in ((config or {}).get(key) or {}).items():
            if name in JOINTS:
                win[JOINTS.index(name), col] = max(win[JOINTS.index(name), 0], v * NORM_DEG) if col == 0 \
                    else min(win[JOINTS.index(name), 1], v * NORM_DEG)
    if (win[:, 0] >= win[:, 1]).any():
        raise ValueError(f"joint window empty after the cell config limits: {win.tolist()}")
    return win


def jac_zero(q, marker, record, origin_mm, zero=PRIOR_DEG, h=0.05):
    """d(corner pixels)/d(zero deg) at q, 8 x 5, by central difference (FK is unrounded here)."""
    cam, cols = camera_of(record), []
    for j in range(5):
        d = np.zeros(5)
        d[j] = h
        up, dn = (pixels(marker_points_mm(q, zero + s * d, marker), record, cam, origin_mm).ravel() for s in (1, -1))
        cols.append((up - dn) / (2 * h))
    return np.array(cols).T


def worst_sigma(jacs, px=PLAN_PX):
    m = np.eye(5) / PRIOR_SIGMA_DEG ** 2 + sum(j.T @ j for j in jacs) / px ** 2
    return np.sqrt(np.diag(np.linalg.inv(m)))


def travel(qs, order):
    return float(sum(np.abs(qs[a] - qs[b]).sum() for a, b in zip(order, order[1:])))


def order_poses(qs, start):
    """Nearest neighbour from `start` then 2-opt on summed |delta q| (deg); returns indices into qs."""
    pts = np.vstack([start, qs])
    n, left, order = len(qs), set(range(1, len(qs) + 1)), [0]
    while left:
        nxt = min(left, key=lambda k: np.abs(pts[order[-1]] - pts[k]).sum())
        order.append(nxt)
        left.remove(nxt)
    improved = True
    while improved:
        improved = False
        for i in range(1, n):
            for j in range(i + 1, n + 1):
                new = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if travel(pts, new) < travel(pts, order) - 1e-9:
                    order, improved = new, True
    return [k - 1 for k in order[1:]]


def plan(record, marker, config=None, n=14, origin_mm=(0.0, 0.0, 0.0), seed=0, pool=500, start_norm=None):
    if not 12 <= n <= 16:
        raise ValueError("12 to 16 poses (the sim needs >= 12 for the 0.5 deg budget)")
    rng, win, cands = np.random.default_rng(seed), window_deg(config), []
    wobble = [PRIOR_DEG + rng.uniform(-5, 5, 5) for _ in range(6)]
    for _ in range(40000):
        if len(cands) >= pool:
            break
        q = np.round(rng.uniform(win[:, 0], win[:, 1]) / NORM_DEG, 2) * NORM_DEG  # the capture sends .pos to 0.01
        if view_ok(q, PRIOR_DEG, marker, record, origin_mm) and all(view_ok(q, z, marker, record, origin_mm) for z in wobble):
            cands.append(q)
    if len(cands) < n:
        raise ValueError(f"only {len(cands)} poses see the marker in the top camera inside the joint window; "
                         "check the marker face/offset, camera record and joint_min/joint_max")
    jacs = [jac_zero(q, marker, record, origin_mm) for q in cands]
    chosen = []
    for _ in range(n):
        best = min((k for k in range(len(cands)) if k not in chosen),
                   key=lambda k: worst_sigma([jacs[i] for i in chosen] + [jacs[k]]).max())
        chosen.append(best)
    qs = np.array([cands[k] for k in chosen])
    start = win.mean(axis=1) if start_norm is None else np.asarray(start_norm, float) * NORM_DEG
    order = order_poses(qs, start)
    qs, js = qs[order], [jacs[chosen[k]] for k in order]
    uv = [pixels(marker_points_mm(q, PRIOR_DEG, marker), record, camera_of(record), origin_mm).mean(0) for q in qs]
    sig = worst_sigma(js)
    return {"schema": "rosy.omx-zero-plan.v1", "unit": "norm", "joint_names": list(JOINTS), "arm_zero_prior_deg": PRIOR_DEG.tolist(),
            "assumed_marker_px": PLAN_PX, "predicted_sigma_deg": sig.round(3).tolist(),
            "travel_deg": {"ordered": round(travel(np.vstack([start, qs]), range(len(qs) + 1)), 0),
                           "as_picked": round(travel(np.vstack([start, qs[np.argsort(order)]]), range(len(qs) + 1)), 0)},
            "start_norm": (start / NORM_DEG).round(2).tolist(),
            "poses": [{"i": i, "q_norm": (q / NORM_DEG).round(2).tolist(), "q_deg": q.round(3).tolist(),
                       "marker_px": u.round(0).tolist()} for i, (q, u) in enumerate(zip(qs, uv))]}
