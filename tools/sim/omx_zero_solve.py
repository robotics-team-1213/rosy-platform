"""Fit the five OMX joint zeros (+ optional table offset) from averaged gripper-marker corners, and say PASS or FAIL.

Residuals as in omx_zero_fit: pixels of FK(q_reported - zero) corners against the observed ones, a weak prior on the
zeros (sigma 4 deg) and, with a ruled touch, a table prior (-8.3 +- 2 mm) and the touch height (+-0.5 mm). Each pose uses
its own camera from the base markers, so the camera never trades off against the zeros. Pure functions of the inputs;
the only thing the CLI writes is the report.

Camera: a base-marker-only solve is soft sideways (0.1 px of marker noise moves it 3-4 mm, which parallaxes a marker
100 mm up by a pixel or more), so by default the camera is six more unknowns (small turn + shift from the base-marker
solve), tied to the pooled base-marker corners by their own residuals; the gripper views then pin it too and its
uncertainty is inside the zero sigmas. `free_camera=False` gives the sim's fixed camera.

Gate (D-947 + the 0.5 deg budget at 2 sigma): >= 12 usable poses, held-out reprojection median <= 3 px, every joint
1-sigma <= 0.25 deg, optimiser converged, estimates within 3 prior sigma. 1-sigma = sqrt(diag((J'J)^-1)) x max(1, sqrt(chi2/dof))
so a model that fits worse than its stated pixel noise widens the sigma instead of hiding it.
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy.optimize import least_squares

from omx_zero_model import (cf, PRIOR_DEG, PRIOR_SIGMA_DEG, TABLE_PRIOR_MM, TABLE_SIGMA_MM, marker_points_mm, pixels,
                            tcp_z_mm)

MIN_POSES, MAX_HELD_PX, MAX_SIGMA_DEG, FOLDS = 12, 3.0, 0.25, 4
TOUCH_SIGMA_MM, PX_FLOOR = 0.5, 0.5  # ruler; systematic print/lens error the frame average cannot remove


def pose_sigma(p, floor=PX_FLOOR):
    return max(floor, (p["std_px"] or floor) / np.sqrt(p["n"]))


def bumped(camera, d):
    """camera_in_base turned by rotation vector d[:3] (deg, about the base axes) and shifted by d[3:] (mm); degrees and
    mm keep least_squares' relative step (diff_step) sensible for these parameters."""
    return cv2.Rodrigues(np.radians(d[:3]))[0] @ camera[0], camera[1] + d[3:] / 1000.0


def _residual_fn(poses, marker, record, origin_mm, touch, with_table, tcp_x_mm, floor, base):
    n0 = 6 if with_table else 5
    cam0 = poses[0]["camera"]

    def residual(x):
        zero, table = x[:5], (x[5] if with_table else 0.0)
        cam = bumped(cam0, x[n0:n0 + 6]) if base else cam0
        r = [((pixels(marker_points_mm(p["q_deg"], zero, marker), record, cam, origin_mm) - p["corners"]) / pose_sigma(p, floor)).ravel()
             for p in poses]
        if base:
            r += [((np.array([cf.project(c, record["K"], record["dist"], cam) for c in record["markers"][str(i)]]) - obs) / floor).ravel()
                  for i, obs in base.items()]
        r.append((zero - PRIOR_DEG) / PRIOR_SIGMA_DEG)
        if with_table:
            r.append(np.array([(table - TABLE_PRIOR_MM) / TABLE_SIGMA_MM]))
            if touch is not None:
                r.append(np.array([(tcp_z_mm(touch["q_deg"], zero, table, tcp_x_mm) - touch["z_mm"]) / TOUCH_SIGMA_MM]))
        return np.concatenate(r)
    return residual


def fit_once(poses, marker, record, origin_mm=(0, 0, 0), touch=None, with_table=False, tcp_x_mm=74.1, floor=PX_FLOOR, base=None):
    f = _residual_fn(poses, marker, record, origin_mm, touch, with_table, tcp_x_mm, floor, base)
    # table starts at its prior, not 0 (relative step); x in degrees, diff_step 1e-2 as in omx_zero_fit
    x0 = np.append(PRIOR_DEG, TABLE_PRIOR_MM) if with_table else PRIOR_DEG.copy()
    if base:
        x0 = np.append(x0, np.zeros(6))
    return least_squares(f, x0, diff_step=1e-2, x_scale="jac", xtol=1e-10, ftol=1e-10)


def held_out_px(poses, marker, record, origin_mm, **kw):
    """Fold i%FOLDS held out in turn: distance (px) of each held-out corner from FK with the other poses' zeros."""
    d = []
    for k in range(FOLDS):
        train, test = [p for i, p in enumerate(poses) if i % FOLDS != k], [p for i, p in enumerate(poses) if i % FOLDS == k]
        x = fit_once(train, marker, record, origin_mm, **kw).x
        cam = bumped(poses[0]["camera"], x[-6:]) if kw.get("base") else poses[0]["camera"]
        d += [np.linalg.norm(pixels(marker_points_mm(p["q_deg"], x[:5], marker), record, cam, origin_mm) - p["corners"], axis=1)
              for p in test]
    return np.concatenate(d)


def solve(poses, marker, record, origin_mm=(0, 0, 0), touch=None, tcp_x_mm=74.1, floor=PX_FLOOR, base=None):
    """Report dict. `poses`: dicts with q_deg, corners (4x2), camera, n, std_px. `touch`: {"q_deg", "z_mm"} or None.
    `base`: {marker id: pooled 4x2 corners} frees the camera (see module doc); None keeps `poses[0]["camera"]` fixed."""
    with_table = touch is not None
    kw = dict(touch=touch, with_table=with_table, tcp_x_mm=tcp_x_mm, floor=floor, base=base)
    fails = []
    if len(poses) < MIN_POSES:
        return {"verdict": "FAIL", "reasons": [f"{len(poses)} usable poses, need >= {MIN_POSES}"], "poses": len(poses)}
    res = fit_once(poses, marker, record, origin_mm, **kw)
    m, p = len(res.fun), len(res.x)
    scale = max(1.0, float(np.sqrt((res.fun ** 2).sum() / max(1, m - p))))
    sigma = np.sqrt(np.diag(np.linalg.inv(res.jac.T @ res.jac))) * scale
    held = held_out_px(poses, marker, record, origin_mm, **kw)
    zero_sigma = sigma[:5]
    if float(np.median(held)) > MAX_HELD_PX:
        fails.append(f"held-out reprojection median {np.median(held):.2f} px > {MAX_HELD_PX}")
    if (zero_sigma > MAX_SIGMA_DEG).any():
        fails.append("1-sigma over %.2f deg: joints %s" % (MAX_SIGMA_DEG, [int(j) + 1 for j in np.flatnonzero(zero_sigma > MAX_SIGMA_DEG)]))
    if not res.success:
        fails.append(f"optimiser did not converge: {res.message}")
    if (np.abs(res.x[:5] - PRIOR_DEG) > 3 * PRIOR_SIGMA_DEG).any():
        fails.append("a zero moved more than 3 prior sigma: marker offset, face, yaw or frame origin is probably wrong")
    out = {"verdict": "FAIL" if fails else "PASS", "reasons": fails, "poses": len(poses),
           "zero_deg": res.x[:5].round(3).tolist(), "sigma_deg": zero_sigma.round(3).tolist(),
           "shift_from_prior_deg": (res.x[:5] - PRIOR_DEG).round(3).tolist(),
           "held_out_px": {"median": round(float(np.median(held)), 2), "p90": round(float(np.percentile(held, 90)), 2), "n": len(held)},
           "chi2_scale": round(scale, 2), "gate": {"held_out_px": MAX_HELD_PX, "sigma_deg": MAX_SIGMA_DEG, "min_poses": MIN_POSES}}
    if base:
        out["camera_shift"] = {"deg": round(float(np.linalg.norm(res.x[-6:-3])), 3), "mm": round(float(np.linalg.norm(res.x[-3:])), 1)}
    if with_table:
        out["table_offset_mm"], out["table_sigma_mm"] = round(float(res.x[5]), 2), round(float(sigma[5]), 2)
    return out
