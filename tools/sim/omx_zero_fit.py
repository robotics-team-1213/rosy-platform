#!/usr/bin/env python3
"""Can an OMX arm's five joint zeros be fitted from gripper markers seen by a fixed camera? (offline, synthetic)

Design: D:/DevTemp/vla-act-roles-1117/problems-1117/zero-estimator-design.md (2026-11-17). The camera pose is taken as
solved per frame from the base marker (D-933 cell_frame), so it does not trade off against the zeros as the 2026-11-09
silhouette fit did. For each settled pose the reported joints and the pixels of gripper landmarks are recorded; the five
zeros d (and optionally the table offset) minimise the reprojection error of FK(q_reported - d), plus a weak prior and
one table touch. The question it answers is numeric: does the residual zero error stay inside the 0.5 deg per joint
budget the IK and policy runs need (vla-act-roles-and-real-arm-path.md 258-261)?

Nothing here moves an arm; observations are synthesised from the same FK.

usage: python tools/sim/omx_zero_fit.py --seeds 20 --poses 12 16 --px 1 3 [--side] [--table] [--out result.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "middleware/devices/omx/adapter"))
from omx_adapter.z_profile import OMX_AI_PROFILE_MM, fk_landmarks_mm  # noqa: E402

BUDGET_DEG = 0.5
# Gripper landmarks the markers stand in for: on the approach axis (pivot, tcp, stock tip) and off it (wrist camera
# mount, 45.8 mm above the axis), so the wrist roll j5 moves a marker too.
MARKERS = ("gripper_pivot", "tcp", "tcp_stock_91_93mm", "wrist_cam")
PRIOR_DEG = np.asarray(OMX_AI_PROFILE_MM["default_joint_zero_offset_deg"], float)  # twin-zero-20261109 candidate
PRIOR_SIGMA_DEG = 4.0
JOINT_RANGE_DEG = ((-60, 60), (-30, 50), (-60, 30), (-60, 60), (-90, 90))
K = np.array([[615.0, 0.0, 320.0], [0.0, 615.0, 240.0], [0.0, 0.0, 1.0]])  # D435 colour, 640x480 (factory ~618.5)


def camera(kind):
    """World(link0, mm) -> camera rotation and centre. top: 650 mm above the table looking straight down; side: level
    with the work, 450 mm to the arm's left, looking along +y."""
    if kind == "top":
        return np.array([[0.0, -1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, -1.0]]), np.array([150.0, 0.0, 650.0])
    return np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]), np.array([150.0, -450.0, 80.0])


def landmarks(q_deg, zero_deg, table_mm=0.0):
    lm = fk_landmarks_mm(q_deg, unit="deg", joint_zero_offset_deg=zero_deg, table_z_offset_mm=table_mm)["landmarks_xyz_mm"]
    return np.array([lm[k] for k in MARKERS], float)


def project(points, cam):
    r, c = cam
    pc = (points - c) @ r.T
    uv = (pc @ K.T)
    return uv[:, :2] / uv[:, 2:3], pc[:, 2]


def visible(q_deg, zero_deg, cams):
    pts = landmarks(q_deg, zero_deg)
    if pts[:, 2].min() < 20.0:  # stays above the table and the boxes
        return False
    for cam in cams:
        uv, depth = project(pts, cam)
        if (depth <= 50).any() or (uv < 10).any() or (uv[:, 0] > 630).any() or (uv[:, 1] > 470).any():
            return False
    return True


def sample_poses(rng, n, zero_deg, cams):
    poses = []
    while len(poses) < n:
        q = np.array([rng.uniform(lo, hi) for lo, hi in JOINT_RANGE_DEG])
        if visible(q, zero_deg, cams):
            poses.append(q)
    return np.array(poses)


TOUCH_POSE = np.array([0.0, 37.0, -10.0, 50.0, 0.0])  # jaw tip pointing down about 5 mm above the table; its height is ruled
TABLE_PRIOR_MM, TABLE_SIGMA_MM = -8.3, 2.0  # default_table_fk_offset_mm, +-2 mm (design 3.4)


def observe(rng, poses, zero_true, cams, px, q_noise, table_true):
    # the camera is solved from the base marker, so the table offset never moves the arm in the image; only the touch sees it
    obs = [[project(landmarks(q, zero_true), cam)[0] + rng.normal(0, px, (len(MARKERS), 2)) for cam in cams]
           for q in poses]
    reported = poses + rng.normal(0, q_noise, poses.shape)
    touch_z = landmarks(TOUCH_POSE, zero_true, table_true)[1, 2] + rng.normal(0, 0.5)  # tcp height, ruler +-0.5 mm
    return reported, obs, touch_z


def fit(reported, obs, cams, px, touch_z=None, with_table=False):
    from scipy.optimize import least_squares

    def residual(x):
        zero, table = x[:5], (x[5] if with_table else 0.0)
        r = [((project(landmarks(q, zero), cam)[0] - o) / px).ravel()
             for q, per_cam in zip(reported, obs) for cam, o in zip(cams, per_cam)]
        r.append((zero - PRIOR_DEG) / PRIOR_SIGMA_DEG)
        if touch_z is not None:
            r.append(np.array([(landmarks(TOUCH_POSE, zero, table)[1, 2] - touch_z) / 0.5]))
        if with_table:
            r.append(np.array([(table - TABLE_PRIOR_MM) / TABLE_SIGMA_MM]))
        return np.concatenate(r)

    # start the table at its prior, not 0: least_squares' relative step is 0 at exactly x = 0 and the table never moved
    x0 = np.append(PRIOR_DEG, TABLE_PRIOR_MM) if with_table else PRIOR_DEG.copy()
    # x in degrees and diff_step 1e-2: FK rounds to 1 um, so a smaller step would differentiate the rounding.
    res = least_squares(residual, x0, diff_step=1e-2, x_scale="jac", xtol=1e-10, ftol=1e-10)
    return res.x[:5], (res.x[5] if with_table else 0.0), res


def trial(seed, n_poses, px, cams, q_noise=0.05, with_table=False):
    rng = np.random.default_rng(seed)
    zero_true = PRIOR_DEG + rng.normal(0, 2.0, 5)
    table_true = TABLE_PRIOR_MM + rng.normal(0, TABLE_SIGMA_MM) if with_table else 0.0
    poses = sample_poses(rng, n_poses, zero_true, cams)
    reported, obs, touch_z = observe(rng, poses, zero_true, cams, px, q_noise, table_true)
    zero, table, _ = fit(reported, obs, cams, px, touch_z if with_table else None, with_table)
    return np.abs(zero - zero_true), abs(table - table_true)


def sweep(seeds, poses_list, px_list, side=False, with_table=False):
    cams = [camera("top")] + ([camera("side")] if side else [])
    rows = []
    for n in poses_list:
        for px in px_list:
            errs = np.array([trial(s, n, px, cams, with_table=with_table)[0] for s in range(seeds)])
            med, p90 = np.median(errs, 0), np.percentile(errs, 90, 0)
            rows.append({"poses": n, "px": px, "cameras": "top+side" if side else "top", "table": with_table,
                         "median_deg": med.round(3).tolist(), "p90_deg": p90.round(3).tolist(),
                         "within_budget": bool((p90 <= BUDGET_DEG).all())})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--poses", type=int, nargs="+", default=[12, 16])
    ap.add_argument("--px", type=float, nargs="+", default=[1.0, 3.0])
    ap.add_argument("--side", action="store_true", help="add the cell's side camera")
    ap.add_argument("--table", action="store_true", help="also fit the table offset from one touch")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = sweep(a.seeds, a.poses, a.px, a.side, a.table)
    for r in rows:
        print(f"{r['cameras']:8} poses {r['poses']:2} px {r['px']:.1f}  median {r['median_deg']}  p90 {r['p90_deg']}  "
              f"{'within' if r['within_budget'] else 'OVER'} {BUDGET_DEG} deg")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
