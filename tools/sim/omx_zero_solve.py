"""Fit the five OMX joint zeros (+ optional table offset) with a 6-DOF camera per camera name, and say PASS or FAIL.

Observations are per camera: pixels of FK(q_reported - zero) gripper-marker corners against the observed ones, plus
each camera's pooled base-marker corners as their own rows (the ruler error `base_sigma_mm` inflates them: a base
coordinate error is a bias on the camera yaw, the panel's real limit). A weak zero prior (sigma 4 deg) and, with a
ruled touch, a table prior (-8.3 +- 2 mm) and the touch height (+-0.5 mm) close the system. Cameras are seeded by
base-marker PnP (omx_zero_frames.session_camera); with `base` each stays six unknowns (small turn + shift from that
seed) tied by the base rows, so camera uncertainty lands inside the zero sigmas instead of trading off silently —
j1 against the camera yaw is exactly the pair that trade. `base=None` keeps every camera at its seed.

Gate (D-947 + the 0.5 deg budget at 2 sigma): >= 12 usable poses, held-out reprojection median <= 3 px per camera,
every joint 1-sigma <= 0.25 deg, optimiser converged, estimates within 3 prior sigma (12 deg), and every stated
camera prior (height +- 20 mm, tilt +- 2 deg) matching the fitted camera. 1-sigma = sqrt(diag((J'J)^-1)) x
max(1, sqrt(chi2/dof)) so a model that fits worse than its stated pixel noise widens the sigma instead of hiding it.
Pure functions of the inputs; the only thing the CLI writes is the report.
"""
from __future__ import annotations

import cv2
import numpy as np
from omx_zero_lsq import least_squares

from omx_zero_model import (cf, PRIOR_DEG, PRIOR_SIGMA_DEG, TABLE_PRIOR_MM, TABLE_SIGMA_MM, marker_points_mm, pixels,
                            tcp_z_mm)

MIN_POSES, MAX_HELD_PX, MAX_SIGMA_DEG, FOLDS = 12, 3.0, 0.25, 4
TOUCH_SIGMA_MM, PX_FLOOR = 0.5, 0.5  # ruler; systematic print/lens error the frame average cannot remove
PRIOR_HEIGHT_MM, PRIOR_TILT_DEG = 20.0, 2.0  # a stated mounting wider off than this is a wrong record, not noise


def pose_sigma(p, floor=PX_FLOOR):
    return max(floor, (p["std_px"] or floor) / np.sqrt(p["n"]))


def bumped(camera, d):
    """camera_in_base turned by rotation vector d[:3] (deg, about the base axes) and shifted by d[3:] (mm); degrees
    and mm keep least_squares' relative step (diff_step) sensible for these parameters."""
    return cv2.Rodrigues(np.radians(d[:3]))[0] @ camera[0], camera[1] + d[3:] / 1000.0


def base_sigma_px(record, seed, floor, base_sigma_mm):
    """Pooled-corner sigma of a base row: the frame floor plus the ruler error projected through the focal length
    (0.3 mm at 650 mm with f 900 is ~0.4 px, not negligible against a 0.5 px floor)."""
    f = (record["K"][0][0] + record["K"][1][1]) / 2
    pts = np.array([record["markers"][str(i)] for i in record["base"]], float).reshape(-1, 3)
    depth_mm = 1000.0 * float(np.linalg.norm(seed[1] - pts.mean(0)))
    return float(np.hypot(floor, base_sigma_mm * f / depth_mm))


def _cam_block(x, k, n0):
    return x[n0 + 6 * k:n0 + 6 * k + 6]


def _residual_fn(cam_poses, marker, records, origin_mm, touch, with_table, tcp_x_mm, floor, base, base_sigma_mm):
    names = list(cam_poses)
    n0 = 6 if with_table else 5
    seeds = {nm: cam_poses[nm][0]["camera"] for nm in names}
    bpx = {nm: base_sigma_px(records[nm], seeds[nm], floor, base_sigma_mm) for nm in names}

    def residual(x):
        zero, table = x[:5], (x[5] if with_table else 0.0)
        r = []
        for k, nm in enumerate(names):
            record = records[nm]
            cam = bumped(seeds[nm], _cam_block(x, k, n0)) if base else seeds[nm]
            r += [((pixels(marker_points_mm(p["q_deg"], zero, marker), record, cam, origin_mm) - p["corners"])
                   / pose_sigma(p, floor)).ravel() for p in cam_poses[nm]]
            if base:
                r += [((np.array([cf.project(c, record["K"], record["dist"], cam) for c in record["markers"][str(i)]])
                        - obs) / bpx[nm]).ravel() for i, obs in base[nm].items()]
        r.append((zero - PRIOR_DEG) / PRIOR_SIGMA_DEG)
        if with_table:
            r.append(np.array([(table - TABLE_PRIOR_MM) / TABLE_SIGMA_MM]))
            if touch is not None:
                r.append(np.array([(tcp_z_mm(touch["q_deg"], zero, table, tcp_x_mm) - touch["z_mm"]) / TOUCH_SIGMA_MM]))
        return np.concatenate(r)
    return residual


def fit_once(cam_poses, marker, records, origin_mm=(0, 0, 0), touch=None, with_table=False, tcp_x_mm=74.1,
             floor=PX_FLOOR, base=None, base_sigma_mm=0.3):
    f = _residual_fn(cam_poses, marker, records, origin_mm, touch, with_table, tcp_x_mm, floor, base, base_sigma_mm)
    # table starts at its prior, not 0 (relative step); x in degrees, diff_step 1e-2 as in omx_zero_fit
    x0 = np.append(PRIOR_DEG, TABLE_PRIOR_MM) if with_table else PRIOR_DEG.copy()
    if base:
        x0 = np.append(x0, np.zeros(6 * len(cam_poses)))
    return least_squares(f, x0, diff_step=1e-2, x_scale="jac", xtol=1e-10, ftol=1e-10)


def held_out_px(cam_poses, marker, records, origin_mm, **kw):
    """Fold i%FOLDS held out per camera: {name: distance px of each held-out corner from FK with the other poses}."""
    out = {}
    for nm, poses in cam_poses.items():
        d = []
        for k in range(FOLDS):
            train = [p for i, p in enumerate(poses) if i % FOLDS != k]
            test = [p for i, p in enumerate(poses) if i % FOLDS == k]
            x = fit_once({nm: train}, marker, records, origin_mm, **kw).x
            seed = cam_poses[nm][0]["camera"]
            cam = bumped(seed, x[-6:]) if kw.get("base") else seed
            d += [np.linalg.norm(pixels(marker_points_mm(p["q_deg"], x[:5], marker), records[nm], cam, origin_mm)
                                 - p["corners"], axis=1) for p in test]
        out[nm] = np.concatenate(d)
    return out


def _prior_mismatch(name, cam, prior):
    h_mm, tilt = float(cam[1][2] * 1000.0), float(np.degrees(np.arccos(np.clip(-cam[0][2, 2], -1.0, 1.0))))
    why = []
    if abs(h_mm - prior[0]) > PRIOR_HEIGHT_MM:
        why.append(f"height {h_mm:.0f} vs {prior[0]:.0f} mm")
    if abs(tilt - prior[1]) > PRIOR_TILT_DEG:
        why.append(f"tilt {tilt:.2f} vs {prior[1]:.2f} deg")
    return why


def solve(cam_poses, marker, records, origin_mm=(0, 0, 0), touch=None, tcp_x_mm=74.1, floor=PX_FLOOR, base=None,
          base_sigma_mm=0.3, priors=None):
    """Report dict. `cam_poses`: {camera name: [pose dicts (q_deg, corners, camera seed, n, std_px)]}. `records`:
    {camera name: calibration record}. `base`: {camera name: {marker id: pooled 4x2 px}} frees the cameras, None
    keeps the seeds. `priors`: {camera name: (height_mm, tilt_deg)} stated mountings, checked not fitted."""
    priors = priors or {}
    with_table = touch is not None
    n0 = 6 if with_table else 5
    kw = dict(touch=touch, with_table=with_table, tcp_x_mm=tcp_x_mm, floor=floor, base=base, base_sigma_mm=base_sigma_mm)
    n_poses = len({tuple(np.round(p["q_deg"], 3)) for ps in cam_poses.values() for p in ps})
    fails = []
    if n_poses < MIN_POSES:
        return {"verdict": "FAIL", "reasons": [f"{n_poses} usable poses, need >= {MIN_POSES}"], "poses": n_poses}
    res = fit_once(cam_poses, marker, records, origin_mm, **kw)
    m, p = len(res.fun), len(res.x)
    scale = max(1.0, float(np.sqrt((res.fun ** 2).sum() / max(1, m - p))))
    sigma = np.sqrt(np.diag(np.linalg.inv(res.jac.T @ res.jac))) * scale
    held = held_out_px(cam_poses, marker, records, origin_mm, **kw)
    zero_sigma = sigma[:5]
    worst_held = max(float(np.median(h)) for h in held.values())
    if worst_held > MAX_HELD_PX:
        fails.append(f"held-out reprojection median {worst_held:.2f} px > {MAX_HELD_PX}")
    if (zero_sigma > MAX_SIGMA_DEG).any():
        fails.append("1-sigma over %.2f deg: joints %s" % (MAX_SIGMA_DEG, [int(j) + 1 for j in np.flatnonzero(zero_sigma > MAX_SIGMA_DEG)]))
    if not res.success:
        fails.append(f"optimiser did not converge: {res.message}")
    if (np.abs(res.x[:5] - PRIOR_DEG) > 3 * PRIOR_SIGMA_DEG).any():
        fails.append("a zero moved more than 3 prior sigma: marker offset, face, yaw or frame origin is probably wrong")
    names, cam_fits = list(cam_poses), {}
    for k, nm in enumerate(names):
        seed = cam_poses[nm][0]["camera"]
        cam_fits[nm] = bumped(seed, _cam_block(res.x, k, n0)) if base else seed
        if nm in priors:
            why = _prior_mismatch(nm, cam_fits[nm], priors[nm])
            if why:
                fails.append(f"camera {nm} disagrees with its stated prior: {'; '.join(why)}"
                             " (marker misdetection or wrong mounting record)")
    out = {"verdict": "FAIL" if fails else "PASS", "reasons": fails, "poses": n_poses,
           "zero_deg": res.x[:5].round(3).tolist(), "sigma_deg": zero_sigma.round(3).tolist(),
           "shift_from_prior_deg": (res.x[:5] - PRIOR_DEG).round(3).tolist(),
           "held_out_px": {nm: {"median": round(float(np.median(h)), 2), "p90": round(float(np.percentile(h, 90)), 2),
                                "n": len(h)} for nm, h in held.items()},
           "chi2_scale": round(scale, 2),
           "gate": {"held_out_px": MAX_HELD_PX, "sigma_deg": MAX_SIGMA_DEG, "min_poses": MIN_POSES}}
    if base:
        out["camera_shift"] = {nm: {"deg": round(float(np.linalg.norm(_cam_block(res.x, k, n0)[:3])), 3),
                                    "mm": round(float(np.linalg.norm(_cam_block(res.x, k, n0)[3:])), 1)}
                               for k, nm in enumerate(names)}
    if with_table:
        out["table_offset_mm"], out["table_sigma_mm"] = round(float(res.x[5]), 2), round(float(sigma[5]), 2)
    return out
