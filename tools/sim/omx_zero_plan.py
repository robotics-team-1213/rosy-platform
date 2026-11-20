"""Pick 12-16 reported-joint poses for the OMX joint-zero capture (offline; moves nothing).

A pose is kept when the gripper marker is seen by every camera at the prior zero AND at random zero errors of +-5 deg
(so a wrong prior does not push it out of view), the tool stays 30 mm above the table, and every joint sits inside
the arm's cell-config joint_min/joint_max. Poses are then picked greedily to minimise the worst per-joint 1-sigma the
fit would give: the Fisher information of the corner pixels over the zeros AND a 6-DOF camera per camera name (at
its base-marker seed), plus the base-marker corner rows and any stated camera prior, with the camera block
marginalised out. A fixed camera is optimistic exactly on j1, which trades against the camera yaw (panel C), so the
plan gates on the same 0.25 deg as the solve at an assumed 1 px noise and the CLI exits 2 when the gate fails.
Units out: `q_norm` (the cell config's `.pos` unit, what the supervised capture sends) and `q_deg` (= q_norm x 1.8).
"""
from __future__ import annotations

import numpy as np

from omx_zero_model import (JOINT_RANGE_DEG, JOINTS, NORM_DEG, PRIOR_DEG, PRIOR_SIGMA_DEG, cf, camera_of,
                            marker_points_mm, pixels, view_ok)
from omx_zero_solve import MAX_SIGMA_DEG, bumped

PLAN_PX = 1.0  # marker noise the plan assumes for the predicted sigma (averaged frames, see fit)
PRIOR_CAM_SIGMA = (2.0, 20.0)  # a stated mounting is a weak prior: deg on the rotation, mm on the shift
ROT_STEP, SHIFT_STEP = 0.05, 0.5  # bump sizes for the numeric camera differential (basemk.py sizes)


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


def jac_zero(q, marker, record, origin_mm=(0.0, 0.0, 0.0), zero=PRIOR_DEG, h=0.05):
    """d(corner pixels)/d(zero deg) at q, 8 x 5, by central difference (FK is unrounded here). The fixed-camera
    optimist; kept so the marginalisation test can compare against it."""
    cam, cols = camera_of(record), []
    for j in range(5):
        d = np.zeros(5)
        d[j] = h
        up, dn = (pixels(marker_points_mm(q, zero + s * d, marker), record, cam, origin_mm).ravel() for s in (1, -1))
        cols.append((up - dn) / (2 * h))
    return np.array(cols).T


def _bumps():
    out = []
    for j in range(6):
        d = np.zeros(6)
        d[j] = ROT_STEP if j < 3 else SHIFT_STEP
        out.append(d)
    return out


def jac_pose(q, marker, record, cam, origin_mm, zero=PRIOR_DEG):
    """d(corner px)/d([zero 5, camera 6]) at pose q, 8 x 11; camera bumps in deg/mm (diff_step-sized)."""
    cols = []
    for j in range(5):
        d = np.zeros(5)
        d[j] = 0.05
        up, dn = (pixels(marker_points_mm(q, zero + s * d, marker), record, cam, origin_mm).ravel() for s in (1, -1))
        cols.append((up - dn) / 0.1)
    for d in _bumps():
        up, dn = (pixels(marker_points_mm(q, zero, marker), record, bumped(cam, s * d), origin_mm).ravel() for s in (1, -1))
        cols.append((up - dn) / (2 * d[np.flatnonzero(d)[0]]))
    return np.array(cols).T


def jac_base(record, cam):
    """d(base-marker corner px)/d(camera 6), (8*n_base) x 6, at the seed camera; the rows that pin the camera yaw."""
    pts = np.array([c for i in record["base"] for c in record["markers"][str(i)]], float)
    cols = []
    for d in _bumps():
        h = d[np.flatnonzero(d)[0]]
        up, dn = (np.array([cf.project(c, record["K"], record["dist"], bumped(cam, s * d)) for c in pts])
                  for s in (1, -1))
        cols.append(((up - dn) / (2 * h)).ravel())
    return np.array(cols).T


def jac_prior(cam):
    """d([height mm, tilt deg])/d(camera 6), 2 x 6: a stated mounting enters the Fisher as its own weak rows."""

    def val(c):
        return np.array([c[1][2] * 1000.0, np.degrees(np.arccos(np.clip(-c[0][2, 2], -1.0, 1.0)))])

    cols = []
    for d in _bumps():
        cols.append((val(bumped(cam, d)) - val(bumped(cam, -d))) / (2 * d[np.flatnonzero(d)[0]]))
    return np.array(cols).T / np.array(PRIOR_CAM_SIGMA)


def _block(J, k, n_cam):
    """An 8 x 11 pose jac placed into the global [zero 5, camera 6 x N] column layout."""
    G = np.zeros((J.shape[0], 5 + 6 * n_cam))
    G[:, :5], G[:, 5 + 6 * k:11 + 6 * k] = J[:, :5], J[:, 5:]
    return G


def fisher(pose_Gs, base_Gs, prior_rows, px=PLAN_PX):
    """Fisher over [zero 5, camera 6 x N]: corner rows (gripper poses + base markers, both / px^2), the zero prior
    and the camera prior rows (already sigma-scaled)."""
    n_cam = len(base_Gs)
    F = np.zeros((5 + 6 * n_cam, 5 + 6 * n_cam))
    for G in pose_Gs:
        F += G.T @ G / px ** 2
    for G in base_Gs:
        F[5:, 5:] += G.T @ G / px ** 2
    F[:5, :5] += np.eye(5) / PRIOR_SIGMA_DEG ** 2
    for k, J in enumerate(prior_rows):
        if J is not None:
            F[5 + 6 * k:11 + 6 * k, 5 + 6 * k:11 + 6 * k] += J.T @ J
    return F


def sigma_zero(F):
    """Zero 1-sigma from the Fisher with the camera block marginalised (Schur complement); the fixed-camera value
    is inv(F)[:5,:5] and marginalising can only widen it."""
    if F.shape[0] == 5:
        return np.sqrt(np.diag(np.linalg.inv(F)))
    z = np.s_[0:5]
    S = F[z, z] - F[z, 5:] @ np.linalg.solve(F[5:, 5:], F[5:, z])
    return np.sqrt(np.diag(np.linalg.inv(S)))


def worst_sigma(jacs, px=PLAN_PX):
    """Fixed-camera worst-case sigma (the old optimistic way; kept for the marginalisation comparison)."""
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


def _quads_overlap(a, b, gap=10.0):
    return not (a[:, 0].max() + gap < b[:, 0].min() or b[:, 0].max() + gap < a[:, 0].min()
                or a[:, 1].max() + gap < b[:, 1].min() or b[:, 1].max() + gap < a[:, 1].min())


def _base_free(q, zero, marker, records, origin_mm):
    """A pose whose gripper marker covers a base marker kills that frame's PnP seed and its own detection."""
    for rec in records.values():
        if not rec.get("base"):
            continue
        cam = camera_of(rec)
        grip = pixels(marker_points_mm(q, zero, marker), rec, cam, origin_mm)
        if any(_quads_overlap(grip, np.array([cf.project(c, rec["K"], rec["dist"], cam) for c in rec["markers"][str(i)]]))
               for i in rec["base"]):
            return False
    return True


def plan(records, marker, config=None, n=14, origin_mm=(0.0, 0.0, 0.0), seed=0, pool=500, start_norm=None, priors=None):
    if not 12 <= n <= 16:
        raise ValueError("12 to 16 poses (the sim needs >= 12 for the 0.5 deg budget)")
    for nm, rec in records.items():
        if "camera_in_base" not in rec:
            raise ValueError(f"camera {nm} has no camera_in_base: a plan needs a camera record "
                             "(fit can seed from the base markers instead)")
    priors = priors or {}
    rng, win, cands = np.random.default_rng(seed), window_deg(config), []
    wobble = [PRIOR_DEG + rng.uniform(-5, 5, 5) for _ in range(6)]
    for _ in range(40000):
        if len(cands) >= pool:
            break
        q = np.round(rng.uniform(win[:, 0], win[:, 1]) / NORM_DEG, 2) * NORM_DEG  # the capture sends .pos to 0.01
        if all(view_ok(q, z, marker, rec, origin_mm) for rec in records.values() for z in [PRIOR_DEG, *wobble]) \
                and _base_free(q, PRIOR_DEG, marker, records, origin_mm):
            cands.append(q)
    if len(cands) < n:
        raise ValueError(f"only {len(cands)} poses see the marker in every camera inside the joint window; "
                         "check the marker face/offset, camera records and joint_min/joint_max")
    n_cam = len(records)
    cand_G = [np.vstack([_block(jac_pose(q, marker, rec, camera_of(rec), origin_mm), k, n_cam)
                         for k, rec in enumerate(records.values())]) for q in cands]
    base_G, prior_rows = [], []
    for nm, rec in records.items():
        base_G.append(jac_base(rec, camera_of(rec)) if rec.get("base") else np.zeros((0, 6)))
        prior_rows.append(jac_prior(camera_of(rec)) if nm in priors else None)
    base_F = fisher([], base_G, prior_rows)
    contrib = [G.T @ G / PLAN_PX ** 2 for G in cand_G]
    chosen = []
    for _ in range(n):
        best = min((k for k in range(len(cands)) if k not in chosen),
                   key=lambda k: sigma_zero(base_F + sum(contrib[i] for i in chosen) + contrib[k]).max())
        chosen.append(best)
    qs = np.array([cands[k] for k in chosen])
    start = win.mean(axis=1) if start_norm is None else np.asarray(start_norm, float) * NORM_DEG
    order = order_poses(qs, start)
    qs = qs[order]
    uv = [np.mean([pixels(marker_points_mm(q, PRIOR_DEG, marker), rec, camera_of(rec), origin_mm).mean(0)
                   for rec in records.values()], 0) for q in qs]
    sig = sigma_zero(base_F + sum(contrib[i] for i in chosen))
    bad = [int(j) + 1 for j in np.flatnonzero(sig > MAX_SIGMA_DEG)]
    return {"schema": "rosy.omx-zero-plan.v1", "unit": "norm", "joint_names": list(JOINTS), "arm_zero_prior_deg": PRIOR_DEG.tolist(),
            "assumed_marker_px": PLAN_PX, "predicted_sigma_deg": sig.round(3).tolist(),
            "gate": "FAIL" if bad else "PASS",
            "gate_reasons": [] if not bad else [f"predicted 1-sigma over {MAX_SIGMA_DEG} deg at {PLAN_PX:.0f} px: joints {bad}"
                                                " (widen the base-marker span, lower the corner noise, or state a camera prior)"],
            "travel_deg": {"ordered": round(travel(np.vstack([start, qs]), range(len(qs) + 1)), 0),
                           "as_picked": round(travel(np.vstack([start, qs[np.argsort(order)]]), range(len(qs) + 1)), 0)},
            "start_norm": (start / NORM_DEG).round(2).tolist(),
            "poses": [{"i": i, "q_norm": (q / NORM_DEG).round(2).tolist(), "q_deg": q.round(3).tolist(),
                       "marker_px": u.round(0).tolist()} for i, (q, u) in enumerate(zip(qs, uv))]}
