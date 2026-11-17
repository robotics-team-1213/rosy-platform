#!/usr/bin/env python3
"""Can an OMX arm's five joint zeros be fitted with the 6-DOF camera solved alongside them? (offline, synthetic)

Design: docs/workspace-records/2026-11-18/zero-procedure-all-arms-panel.md. Per cell (S: USB camera 650 mm vertical;
A/B: one shared D435 at 596 mm tilted 13.1 deg) the camera starts from a base-marker PnP seed; the fit solves the
five zeros (+ optional table offset) together with 6 camera degrees of freedom, tied by two ruler-measured base
markers (placement error --base-err-mm) and their own corner noise --base-px. The question stays numeric: does the
residual zero error stay inside the 0.5 deg per joint budget the IK and policy runs need?

Nothing here moves an arm; observations are synthesised from the same FK.

usage: python tools/sim/omx_zero_fit.py --cell S A B --poses 16 --px 1 --seeds 8 [--out result.json]
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
BASE_SIZE_MM = 25.0  # the print sheet's base markers (arm_pdf)
# Cell PC configs read 2026-11-18: S is a USB camera 0.65 m vertical, f~600; A/B share one D435 at 596 mm tilted
# 13.1 deg, f 618.5, plumb pixels (309,373)/(297,361). tilt_az 180 leans the axis back over the base, the stern-side
# mounting, so the workspace sits in the upper image; --tilt-az sweeps the other three mountings.
CELLS = {
    "S": {"height_mm": 650.0, "tilt_deg": 0.0, "tilt_az_deg": 180.0, "f_px": 600.0, "centre_px": (320.0, 240.0), "base_xy_mm": (150.0, 0.0)},
    "A": {"height_mm": 596.0, "tilt_deg": 13.1, "tilt_az_deg": 180.0, "f_px": 618.5, "centre_px": (309.0, 373.0), "base_xy_mm": (150.0, 0.0)},
    "B": {"height_mm": 596.0, "tilt_deg": 13.1, "tilt_az_deg": 180.0, "f_px": 618.5, "centre_px": (297.0, 361.0), "base_xy_mm": (150.0, 0.0)},
}


def camera(height_mm=650.0, tilt_deg=0.0, tilt_az_deg=180.0, K=None, centre_px=(320.0, 240.0), base_xy_mm=(150.0, 0.0)):
    """(R world->camera, camera centre mm, K): the optical axis tilted `tilt_deg` from straight down toward
    `tilt_az_deg` (0 = +x); the principal point is set so the link0 origin's plumb line lands on `centre_px`
    (what the cell configs record). `K` supplies only the focal lengths."""
    t, a = np.radians(tilt_deg), np.radians(tilt_az_deg)
    fx, fy = (np.asarray(K, float)[0, 0], np.asarray(K, float)[1, 1]) if K is not None else (615.0, 615.0)
    z_c = np.array([np.sin(t) * np.cos(a), np.sin(t) * np.sin(a), -np.cos(t)])
    x_c = np.array([-np.sin(a), np.cos(a), 0.0])
    R = np.array([x_c, np.cross(z_c, x_c), z_c])
    c = np.array([base_xy_mm[0], base_xy_mm[1], height_mm], float)
    pc = R @ -c
    K_eff = np.array([[fx, 0.0, centre_px[0] - fx * pc[0] / pc[2]],
                      [0.0, fy, centre_px[1] - fy * pc[1] / pc[2]], [0.0, 0.0, 1.0]])
    return R, c, K_eff


def cell_camera(cell, tilt_az_deg=None):
    cc = dict(CELLS[cell])
    if tilt_az_deg is not None:
        cc["tilt_az_deg"] = float(tilt_az_deg)
    f = cc["f_px"]
    return camera(cc["height_mm"], cc["tilt_deg"], cc["tilt_az_deg"], np.array([[f, 0, 0], [0, f, 0], [0, 0, 1.0]]),
                  cc["centre_px"], cc["base_xy_mm"])


def base_corners(span_mm=90.0, x_mm=-50.0, z_mm=13.0, size_mm=BASE_SIZE_MM):
    """The two ruler-measured base markers: squares on the base plate (top z 13 mm), `span_mm` apart in y; the
    span, not the marker count, is what pins the camera yaw against j1 (panel A)."""
    h = size_mm / 2
    return np.array([[x_mm + dx, y + dy, z_mm] for y in (-span_mm / 2, span_mm / 2)
                     for dx, dy in ((-h, -h), (h, -h), (h, h), (-h, h))], float)


def measured_base(rng, base, err_mm):
    """Each marker's whole quad shifts by one fixed ruler error per session: a systematic bias, not noise."""
    if err_mm <= 0:
        return base.copy()
    quads = base.reshape(-1, 4, 3).copy()
    quads += rng.normal(0, err_mm, (len(quads), 1, 3))
    return quads.reshape(-1, 3)


def landmarks(q_deg, zero_deg, table_mm=0.0):
    lm = fk_landmarks_mm(q_deg, unit="deg", joint_zero_offset_deg=zero_deg, table_z_offset_mm=table_mm)["landmarks_xyz_mm"]
    return np.array([lm[k] for k in MARKERS], float)


def project(points, cam):
    r, c, k = cam
    pc = (points - c) @ r.T
    uv = pc @ k.T
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


def sample_poses(rng, n, zero_deg, cams, tries=40000):
    poses = []
    for _ in range(tries):
        if len(poses) == n:
            break
        q = np.array([rng.uniform(lo, hi) for lo, hi in JOINT_RANGE_DEG])
        if visible(q, zero_deg, cams):
            poses.append(q)
    if len(poses) < n:
        raise ValueError(f"only {len(poses)} of {n} poses visible in the camera(s); check the cell camera geometry")
    return np.array(poses)


TOUCH_POSE = np.array([0.0, 37.0, -10.0, 50.0, 0.0])  # jaw tip pointing down about 5 mm above the table; its height is ruled
TABLE_PRIOR_MM, TABLE_SIGMA_MM = -8.3, 2.0  # default_table_fk_offset_mm, +-2 mm (design 3.4)


def observe(rng, poses, zero_true, cams, px, q_noise, table_true, base_meas=None, base_px=1.0):
    obs = [[project(landmarks(q, zero_true), cam)[0] + rng.normal(0, px, (len(MARKERS), 2)) for cam in cams] for q in poses]
    base_obs = None
    if base_meas is not None:
        base_obs = [project(base_meas, cam)[0] + rng.normal(0, base_px, base_meas[:, :2].shape) for cam in cams]
    reported = poses + rng.normal(0, q_noise, poses.shape)
    touch_z = landmarks(TOUCH_POSE, zero_true, table_true)[1, 2] + rng.normal(0, 0.5)  # tcp height, ruler +-0.5 mm
    return reported, obs, touch_z, base_obs


def bumped(cam, d):
    """Camera turned by rotation vector d[:3] (deg, about the world axes) and shifted by d[3:] mm; degrees and mm
    keep least_squares' relative step (diff_step) sensible for these parameters."""
    from scipy.spatial.transform import Rotation as Ro

    return Ro.from_rotvec(np.radians(d[:3])).as_matrix() @ cam[0], cam[1] + d[3:], cam[2]


def fit(reported, obs, cams, px, base_obs=None, base_meas=None, base_px=1.0, cam_prior=(None, None), touch_z=None,
        with_table=False):
    """Solve [zero 5 (+table) + 6 camera DOF per camera] when `base_obs` is given (the tool's way), else the zeros
    only against fixed cameras (the old sim). `cam_prior`: (sigma deg, sigma mm) on the camera deltas, or None."""
    from scipy.optimize import least_squares

    free = base_obs is not None
    n0 = 6 if with_table else 5

    def cam_at(ci, x):
        return bumped(cams[ci], x[n0 + 6 * ci:n0 + 6 * ci + 6]) if free else cams[ci]

    def residual(x):
        zero, table = x[:5], (x[5] if with_table else 0.0)
        r = [((project(landmarks(q, zero), cam_at(ci, x))[0] - o) / px).ravel()
             for q, per_cam in zip(reported, obs) for ci, o in enumerate(per_cam)]
        if free:
            for ci in range(len(cams)):
                r.append(((project(base_meas, cam_at(ci, x))[0] - base_obs[ci]) / base_px).ravel())
            if cam_prior and cam_prior[0]:
                d = x[n0:].reshape(-1, 6)
                r += [(d[:, :3] / cam_prior[0]).ravel(), (d[:, 3:] / cam_prior[1]).ravel()]
        r.append((zero - PRIOR_DEG) / PRIOR_SIGMA_DEG)
        if touch_z is not None:
            r.append(np.array([(landmarks(TOUCH_POSE, zero, table)[1, 2] - touch_z) / 0.5]))
        if with_table:
            r.append(np.array([(table - TABLE_PRIOR_MM) / TABLE_SIGMA_MM]))
        return np.concatenate(r)

    # start at the priors, not 0 (least_squares' relative step is 0 at exactly x = 0 and the table never moved);
    # diff_step 1e-2: FK rounds to 1 um, a smaller step would differentiate the rounding
    x0 = np.append(PRIOR_DEG, TABLE_PRIOR_MM) if with_table else PRIOR_DEG.copy()
    if free:
        x0 = np.append(x0, np.zeros(6 * len(cams)))
    return least_squares(residual, x0, diff_step=1e-2, x_scale="jac", xtol=1e-10, ftol=1e-10)


def sigma_deg(res):
    m, p = len(res.fun), len(res.x)
    scale = max(1.0, float(np.sqrt((res.fun ** 2).sum() / max(1, m - p))))
    return np.sqrt(np.diag(np.linalg.inv(res.jac.T @ res.jac)))[:5] * scale


def trial(seed, n_poses, px, cam, span_mm=90.0, base_px=1.0, base_err_mm=0.0, cam_prior=(None, None),
          zero_sigma=2.0, q_noise=0.05, with_table=False):
    """One synthetic session against one `cam`: (|zero error| per joint, |error| <= 2 sigma per joint)."""
    rng = np.random.default_rng(seed)
    zero_true = PRIOR_DEG + rng.normal(0, zero_sigma, 5)
    table_true = TABLE_PRIOR_MM + rng.normal(0, TABLE_SIGMA_MM) if with_table else 0.0
    poses = sample_poses(rng, n_poses, zero_true, [cam])
    base = measured_base(rng, base_corners(span_mm), base_err_mm)
    reported, obs, touch_z, base_obs = observe(rng, poses, zero_true, [cam], px, q_noise, table_true, base, base_px)
    res = fit(reported, obs, [cam], px, base_obs=base_obs, base_meas=base, base_px=base_px, cam_prior=cam_prior,
              touch_z=touch_z if with_table else None, with_table=with_table)
    err = np.abs(res.x[:5] - zero_true)
    return err, err <= 2 * sigma_deg(res)


def sweep(cells=("S", "A", "B"), seeds=20, poses_list=(16,), px_list=(1.0,), tilt_az=None, spans=(90.0,),
          base_px=1.0, errs=(0.0,), priors=("none",), zero_sigmas=(2.0,), with_table=False):
    rows = []
    for cell in cells:
        for az in (tilt_az if tilt_az else [None]):
            cam = cell_camera(cell, az)
            for n in poses_list:
                for px in px_list:
                    for span in spans:
                        for err in errs:
                            for prior in priors:
                                for zs in zero_sigmas:
                                    cp = None if prior == "none" else tuple(float(v) for v in prior.split(","))
                                    out = [trial(s, n, px, cam, span, base_px, err, cp, zs, with_table=with_table)
                                           for s in range(seeds)]
                                    e, cov = np.array([o[0] for o in out]), np.array([o[1] for o in out])
                                    rows.append({"cell": cell, "tilt_az_deg": az, "poses": n, "px": px,
                                                 "base_span_mm": span, "base_px": base_px, "base_err_mm": err,
                                                 "camera_prior": prior, "zero_sigma_deg": zs,
                                                 "median_deg": np.median(e, 0).round(3).tolist(),
                                                 "p90_deg": np.percentile(e, 90, 0).round(3).tolist(),
                                                 "cover2sigma": round(float(cov.mean()), 3),
                                                 "within_budget": bool(np.percentile(e, 90, 0).max() <= BUDGET_DEG)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cell", nargs="+", default=["S", "A", "B"], choices=sorted(CELLS))
    ap.add_argument("--tilt-az", type=float, nargs="+", help="override the cell's tilt azimuth (deg)")
    ap.add_argument("--base-span-mm", type=float, nargs="+", default=[90.0])
    ap.add_argument("--base-px", type=float, default=1.0)
    ap.add_argument("--base-err-mm", type=float, nargs="+", default=[0.0])
    ap.add_argument("--camera-prior", nargs="+", default=["none"], help="none or SIGMA_DEG,SIGMA_MM (e.g. 1,5 2,20)")
    ap.add_argument("--zero-sigma", type=float, nargs="+", default=[2.0])
    ap.add_argument("--poses", type=int, nargs="+", default=[16])
    ap.add_argument("--px", type=float, nargs="+", default=[1.0])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = sweep(a.cell, a.seeds, a.poses, a.px, a.tilt_az, a.base_span_mm, a.base_px, a.base_err_mm,
                 a.camera_prior, a.zero_sigma, a.table)
    for r in rows:
        print(f"{r['cell']} az{r['tilt_az_deg']} span{r['base_span_mm']:.0f} err{r['base_err_mm']} prior{r['camera_prior']}"
              f" zs{r['zero_sigma_deg']} poses {r['poses']} px {r['px']:.1f}  median {r['median_deg']}"
              f" p90 {r['p90_deg']} cover2s {r['cover2sigma']:.3f}  {'within' if r['within_budget'] else 'OVER'} {BUDGET_DEG}")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
