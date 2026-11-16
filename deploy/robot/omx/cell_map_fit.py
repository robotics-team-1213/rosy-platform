"""Shared map fitting, model-consistent LOO residuals, and prediction uncertainty (`cell_map_fit.py`).

Single Responsibility:
  - Consensus subset selection (`consensus`, `enough_agree`, `predicted`).
  - Model-consistent LOO residuals (`loo_residuals`) & pose-safe repair (`repair_record`).
  - Leverage / Jacobian predictive standard error (`predict_sigma_mm`, `site_sigma_summary`).
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402


def predicted(marks: list, point) -> list | None:
    """Where the jaws over `point` should show, from an affine fit of three or more (pixel, arm) marks not on one line."""
    arm = np.array([[a[0], a[1], 1.0] for _, a in marks])
    if len(marks) < 3 or np.linalg.matrix_rank(arm, tol=1e-3) < 3:
        return None
    coef, *_ = np.linalg.lstsq(arm, np.array([m for m, _ in marks], float), rcond=None)
    return [round(float(v), 1) for v in np.array([point[0], point[1], 1.0]) @ coef]


def consensus(marks: list, tol_px: float) -> list:
    """The largest set of marks one affine map explains."""
    n = len(marks)
    if n < 3:
        return list(marks)
    ax = np.array([a[0] for _, a in marks], dtype=np.float64)
    ay = np.array([a[1] for _, a in marks], dtype=np.float64)
    pu = np.array([m[0] for m, _ in marks], dtype=np.float64)
    pv = np.array([m[1] for m, _ in marks], dtype=np.float64)
    idx = np.array(list(itertools.combinations(range(n), 3)), dtype=np.intp)
    i, j, k = idx[:, 0], idx[:, 1], idx[:, 2]
    dx1, dy1 = ax[j] - ax[i], ay[j] - ay[i]
    dx2, dy2 = ax[k] - ax[i], ay[k] - ay[i]
    det = dx1 * dy2 - dx2 * dy1
    span = np.maximum(np.hypot(dx1, dy1), np.hypot(dx2, dy2))
    valid = np.abs(det) > np.maximum(1e-6, 1e-3 * span)
    if not valid.any():
        return list(marks)
    i, j, k = i[valid], j[valid], k[valid]
    dx1, dy1, dx2, dy2 = dx1[valid], dy1[valid], dx2[valid], dy2[valid]
    inv_det = 1.0 / det[valid]
    du1, dv1 = pu[j] - pu[i], pv[j] - pv[i]
    du2, dv2 = pu[k] - pu[i], pv[k] - pv[i]
    au = (dy2 * du1 - dy1 * du2) * inv_det
    bu = (-dx2 * du1 + dx1 * du2) * inv_det
    av = (dy2 * dv1 - dy1 * dv2) * inv_det
    bv = (-dx2 * dv1 + dx1 * dv2) * inv_det
    rx = ax[None, :] - ax[i, None]
    ry = ay[None, :] - ay[i, None]
    eu = pu[i, None] + au[:, None] * rx + bu[:, None] * ry - pu[None, :]
    ev = pv[i, None] + av[:, None] * rx + bv[:, None] * ry - pv[None, :]
    inliers = (eu * eu + ev * ev) <= (tol_px * tol_px)
    counts = inliers.sum(axis=1)
    best_idx = int(np.argmax(counts))
    if counts[best_idx] == 0:
        return list(marks)
    return [m for m, keep in zip(marks, inliers[best_idx]) if keep]


def enough_agree(kept: int, seen: int) -> bool:
    """Five marks fit a map, and the majority must agree."""
    return kept >= 5 and kept * 2 > seen


def _record_points(record: dict | None) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    raw = (record or {}).get("points") or []
    return [(tuple(p["pixel"]), tuple(p["arm_m"])) for p in raw if p.get("pixel") and p.get("arm_m")]


def repair_record(config: dict, record: dict, kept: list) -> dict:
    """Re-fit kept points using the same model family (`fitted_map`), avoiding stale pose metadata on affine fits."""
    from cell_intrinsics_frames import fitted_map

    z_view = record.get("z_view") if record.get("z_view") is not None else (config.get("coarse") or {}).get("z_view", 0.0)
    repaired = fitted_map(config, kept, z_view)
    base = {k: v for k, v in record.items()
            if k not in ("homography", "loo_error_mm", "camera_in_base", "rms_px", "upright", "affine_fit", "pose_fit", "pose_refused")}
    return {
        **base,
        **repaired,
        "z_view": z_view,
        "points": [{"pixel": [round(float(p[0]), 2), round(float(p[1]), 2)], "arm_m": [float(a[0]), float(a[1])]} for p, a in kept],
    }


def _pose_loo_errors(pts: list, z_view: float, config: dict) -> list[tuple[float, float] | None] | None:
    c = config.get("calibrate") or {}
    if not c.get("intrinsics") or c.get("up") is None:
        return None
    try:
        lens_path = Path(c["intrinsics"]).expanduser()
        if not lens_path.is_file():
            return None
        import cell_checkerboard as cb
        import cell_frame
        import cell_intrinsics_frames as cif

        lens = __import__("json").loads(lens_path.read_text(encoding="utf-8"))
        K = np.asarray(lens["K"], float)
        dist = np.asarray(lens.get("dist", [0.0] * 5), float)
        up = c["up"]
        cam_h = ((config.get("cameras") or {}).get("top") or {}).get("height_m")
        height = (float(cam_h) - float(z_view)) if cam_h is not None and float(cam_h) > float(z_view) else None
        rows: list[tuple[float, float] | None] = []
        for i, (px, arm) in enumerate(pts):
            sub = cif.plane_pose_map(pts[:i] + pts[i + 1:], z_view, K, dist, up, height)
            inv = (np.asarray(sub["camera_in_base"]["R"], float), np.asarray(sub["camera_in_base"]["t"], float))
            pose = cell_frame.inverse(inv)
            hit = cb.pixel_to_plane(px, K, dist, pose, float(z_view))
            rows.append((round((float(hit[0]) - arm[0]) * 1000.0, 2), round((float(hit[1]) - arm[1]) * 1000.0, 2)))
        return rows
    except Exception:
        return None


def loo_residuals(record: dict | None, config: dict | None = None) -> list[dict]:
    """Per-point fit and leave-one-out residuals consistent with the record's own model family."""
    pts = _record_points(record)
    if not record or not record.get("homography") or not pts:
        return []
    h = record["homography"]
    pose_errs = None
    if record.get("camera_in_base") and record.get("z_view") is not None and config and len(pts) >= 4:
        pose_errs = _pose_loo_errors(pts, float(record["z_view"]), config)
    out = []
    for i, (px, arm_pt) in enumerate(pts):
        pred_full = cal.to_arm(h, px)
        fit_dx = round((pred_full[0] - arm_pt[0]) * 1000.0, 2)
        fit_dy = round((pred_full[1] - arm_pt[1]) * 1000.0, 2)
        loo_res = loo_dist = None
        if pose_errs is not None:
            pair = pose_errs[i]
            if pair is not None:
                loo_res = [pair[0], pair[1]]
                loo_dist = round(math.hypot(pair[0], pair[1]), 2)
        elif len(pts) >= 4:
            try:
                h_i = cal.fit(pts[:i] + pts[i + 1:])
                pred_i = cal.to_arm(h_i, px)
                lx = round((pred_i[0] - arm_pt[0]) * 1000.0, 2)
                ly = round((pred_i[1] - arm_pt[1]) * 1000.0, 2)
                loo_res = [lx, ly]
                loo_dist = round(math.hypot(lx, ly), 2)
            except ValueError:
                pass
        out.append({
            "index": i,
            "pixel": [round(float(px[0]), 2), round(float(px[1]), 2)],
            "arm_m": [float(arm_pt[0]), float(arm_pt[1])],
            "loo_residual_mm": loo_res,
            "loo_dist_mm": loo_dist,
            "fit_residual_mm": [fit_dx, fit_dy],
            "fit_dist_mm": round(math.hypot(fit_dx, fit_dy), 2),
        })
    return out


def predict_sigma_mm(record: dict | None, pixel) -> float:
    """Leverage-aware 1-sigma map prediction uncertainty (mm) at `pixel`, floored by LOO mean / 0.5 mm."""
    if not record or not record.get("homography"):
        return 5.0
    loo_mean = float((record.get("loo_error_mm") or {}).get("mean") or 0.5)
    pts = _record_points(record)
    u, v = float(pixel[0]), float(pixel[1])
    if not (math.isfinite(u) and math.isfinite(v)):
        return round(max(0.5, loo_mean), 2)
    if record.get("camera_in_base"):
        # Pose model extrapolates linearly via perspective rays rather than quadratic affine leverage; scale by radial distance / span
        if len(pts) < 3:
            return round(max(0.5, loo_mean), 2)
        pxs = np.array([[p[0][0], p[0][1]] for p in pts], float)
        if not np.all(np.isfinite(pxs)):
            return round(max(0.5, loo_mean), 2)
        ctr = pxs.mean(axis=0)
        span = max(20.0, float(np.max(np.linalg.norm(pxs - ctr, axis=1))))
        dist_r = float(math.hypot(u - ctr[0], v - ctr[1]))
        sigma = loo_mean * math.sqrt(1.0 + 0.5 * max(0.0, dist_r / span - 1.0) ** 2)
        return round(max(0.5, sigma), 2) if math.isfinite(sigma) else round(max(0.5, loo_mean), 2)
    if len(pts) < 4:
        return round(max(0.5, loo_mean), 2)
    X = np.array([[p[0][0], p[0][1], 1.0] for p in pts], float)
    Y = np.array([[p[1][0], p[1][1]] for p in pts], float)
    try:
        h = record["homography"]
        pred_xy = np.array([cal.to_arm(h, p[0]) for p in pts], float)
        resid_mm = (pred_xy - Y) * 1000.0
        if not np.all(np.isfinite(resid_mm)):
            return round(max(0.5, loo_mean), 2)
        df = max(1, len(pts) - 3)
        s2 = max(loo_mean ** 2, float(np.sum(resid_mm ** 2) / df))
        # Center/scale columns for numerical conditioning on 640x480 coordinates
        u0, v0 = X[:, 0].mean(), X[:, 1].mean()
        su = max(1.0, float(X[:, 0].std()))
        sv = max(1.0, float(X[:, 1].std()))
        Z = np.column_stack([(X[:, 0] - u0) / su, (X[:, 1] - v0) / sv, np.ones(len(pts))])
        z0 = np.array([(u - u0) / su, (v - v0) / sv, 1.0])
        h0 = float(z0 @ np.linalg.pinv(Z.T @ Z) @ z0)
        sigma = math.sqrt(max(0.0, s2) * (1.0 + max(0.0, h0)))
        return round(max(0.5, loo_mean, sigma), 2) if math.isfinite(sigma) else round(max(0.5, loo_mean), 2)
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return round(max(0.5, loo_mean), 2)


def site_sigma_summary(record: dict | None, points_arm: list, cam_top: dict, target_z: float | None) -> dict | None:
    """Max/mean expected map error (mm, AprilCal MERE) across key site coordinates (`start`, `place`)."""
    if not record or not record.get("homography") or not points_arm:
        return None
    fit_z = record.get("z_view")
    sigmas = []
    for pt in points_arm:
        if not pt or len(pt) < 2:
            continue
        try:
            px = cal.to_pixel(record["homography"], pt[:2])
            if target_z is not None and fit_z is not None and cam_top.get("center_px") and cam_top.get("height_m"):
                px = cal.parallax(px, float(fit_z), float(target_z), cam_top)
            sigmas.append(predict_sigma_mm(record, px))
        except Exception:
            continue
    if not sigmas:
        return None
    return {"max_mm": round(max(sigmas), 2), "mean_mm": round(sum(sigmas) / len(sigmas), 2)}


def plan_leverage(points: list, sites: dict, sigma_mark_mm: float = 3.0) -> dict:
    """Estimate noise-only 1-sigma extrapolation (`sigma_mark_mm * sqrt(h0)`) across nominal `map_points`."""
    pts = [[float(p[0]), float(p[1])] for p in (points or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 4:
        return {"sigma_mark_mm": float(sigma_mark_mm), "sites": {}, "max_sigma_mm": None}
    xy = np.array(pts, float)
    if not np.all(np.isfinite(xy)):
        return {"sigma_mark_mm": float(sigma_mark_mm), "sites": {}, "max_sigma_mm": None}
    x0, y0 = xy[:, 0].mean(), xy[:, 1].mean()
    sx, sy = max(1e-4, float(xy[:, 0].std())), max(1e-4, float(xy[:, 1].std()))
    Z = np.column_stack([(xy[:, 0] - x0) / sx, (xy[:, 1] - y0) / sy, np.ones(len(xy))])
    cov_inv = np.linalg.pinv(Z.T @ Z)
    out: dict[str, dict] = {}
    for name, spec in (sites or {}).items():
        if not isinstance(spec, dict):
            continue
        vals: dict[str, float] = {}
        for key in ("start", "place"):
            pt = spec.get(key)
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                z0 = np.array([(float(pt[0]) - x0) / sx, (float(pt[1]) - y0) / sy, 1.0])
                h0 = max(0.0, float(z0 @ cov_inv @ z0))
                vals[f"{key}_sigma_mm"] = round(float(sigma_mark_mm) * math.sqrt(h0), 2)
        if vals:
            vals["max_sigma_mm"] = max(vals.values())
            out[name] = vals
    max_all = max((v["max_sigma_mm"] for v in out.values()), default=None)
    return {"sigma_mark_mm": float(sigma_mark_mm), "sites": out, "max_sigma_mm": max_all}
