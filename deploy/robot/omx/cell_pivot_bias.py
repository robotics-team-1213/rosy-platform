"""Pivot bias record persistence and lookup (`<map>.bias.json`, rosy.omx-cell-bias.v1)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402

SCHEMA = "rosy.omx-cell-bias.v1"
BIAS_REACH_MM = prm.default("pivot.bias_reach_mm")  # a region's bias is trusted this far from its pivot point
_BIAS_CACHE: dict = {}  # (path, mtime_ns, size, max_bias_mm) -> validated bias file
KINDS = ("pivot", "known_geometry", "place_look", "visit")


def is_pivot_region(region: dict) -> bool:
    """True when the region carries a pivot circle (`radius_mm`/`phase_deg`) or known-geometry marker."""
    return "radius_mm" in region or region.get("kind") in ("pivot", "known_geometry")


def yaw_arc_deg(yaws_deg) -> float:
    """Span of achieved FK yaws around the circle (360 minus the largest empty gap)."""
    angles = sorted(y % 360.0 for y in yaws_deg)
    if len(angles) < 2:
        return 0.0
    gaps = [b - a for a, b in zip(angles, angles[1:])] + [360.0 - angles[-1] + angles[0]]
    return 360.0 - max(gaps)


def fit_pivot_yaw(marks_m, yaws_fk_deg, *, mark_sigma_mm: float = 3.0, out_k: float = 2.5) -> dict:
    """Yaw-coupled linear fit `m_i = c + Rot(theta_i) @ g` with outlier trimming (prior-scaled)."""
    import numpy as np

    m = np.asarray(marks_m, float).reshape(-1, 2)
    th = np.radians(np.asarray(yaws_fk_deg, float).ravel())
    if len(m) != len(th) or len(m) < 3 or mark_sigma_mm <= 0:
        return {"result": "refused", "why": "fewer than 3 marks", "dropped": 0}
    if not (np.all(np.isfinite(m)) and np.all(np.isfinite(th))):
        return {"result": "refused", "why": "non-finite marks or yaws", "dropped": 0}
    keep = np.ones(len(m), dtype=bool)
    p = JtJinv = s2 = None
    for _ in range(3):
        idx = np.flatnonzero(keep)
        if len(idx) < 3:
            return {"result": "refused", "why": f"{len(idx)} marks agree", "dropped": int((~keep).sum())}
        J = np.zeros((2 * len(idx), 4), float)
        c, s = np.cos(th[idx]), np.sin(th[idx])
        J[0::2] = np.c_[np.ones_like(c), np.zeros_like(c), c, -s]
        J[1::2] = np.c_[np.zeros_like(c), np.ones_like(c), s, c]
        try:
            p, *_ = np.linalg.lstsq(J, m[idx].ravel(), rcond=None)
            JtJinv = np.linalg.inv(J.T @ J)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            return {"result": "refused", "why": "degenerate yaws", "dropped": int((~keep).sum())}
        res = (J @ p - m[idx].ravel()).reshape(-1, 2)
        dof = 2 * len(idx) - 4
        s2 = max((mark_sigma_mm / 1000.0) ** 2, float(np.sum(res ** 2)) / dof if dof > 0 else 0.0)
        bad = np.hypot(res[:, 0], res[:, 1]) > out_k * math.sqrt(2.0) * (mark_sigma_mm / 1000.0)
        if not bad.any() or dof <= 0:
            break
        keep[idx[bad]] = False
    dropped = int((~keep).sum())
    if keep.sum() < 3:
        return {"result": "refused", "why": f"{int(keep.sum())} marks agree", "dropped": dropped}
    if dropped and dropped * 3 >= len(m):
        return {"result": "refused", "why": "finger switch suspected: marks split", "dropped": dropped}
    kept_idx = [int(i) for i in np.flatnonzero(keep)]
    cx, cy, gx, gy = (float(p[0]), float(p[1]), float(p[2]), float(p[3]))
    radius_m = math.hypot(gx, gy)
    phase_deg = math.degrees(math.atan2(gy, gx))
    cov = s2 * JtJinv
    eig = max(0.0, float(max(np.linalg.eigvalsh(cov[:2, :2]))))
    fit_rms_m = math.sqrt(float(np.mean(np.sum(res ** 2, axis=1))))
    radial_rms_m = float(np.sqrt(np.mean((np.hypot(m[keep, 0] - cx, m[keep, 1] - cy) - radius_m) ** 2)))
    return {
        "result": "fitted", "centre_m": [cx, cy], "radius_m": radius_m, "radius_mm": round(1000.0 * radius_m, 1),
        "phase_deg": round(phase_deg, 1), "centre_sigma_mm": round(1000.0 * math.sqrt(eig), 2),
        "rms_m": fit_rms_m, "radial_rms_m": radial_rms_m, "rms_mm": round(1000.0 * fit_rms_m, 1),
        "dropped": dropped, "n": len(kept_idx), "kept_indices": kept_idx,
    }


def circle_center_sigma_mm(points, cx: float, cy: float, rms_m: float, mark_sigma_mm: float = 3.0) -> float | None:
    """Linearized Cramér-Rao 1-sigma uncertainty (mm, largest axis) of fitted circle centre `(cx, cy)`."""
    import numpy as np

    p = np.asarray(points, float).reshape(-1, 2)
    if len(p) < 3 or not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(rms_m)):
        return None
    if not np.all(np.isfinite(p)):
        return None
    d = p - (cx, cy)
    rho = np.hypot(d[:, 0], d[:, 1])
    if np.any(rho < 1e-9):
        return None
    J = np.column_stack([-d / rho[:, None], -np.ones(len(p))])
    jtj = J.T @ J
    if not np.all(np.isfinite(jtj)) or np.linalg.cond(jtj) > 1e8:
        return None
    s2 = (mark_sigma_mm / 1000.0) ** 2
    if len(p) > 3:
        s2 = max(s2, (len(p) * float(rms_m) ** 2) / (len(p) - 3))
    try:
        cov = np.linalg.inv(jtj) * s2
        eig = max(0.0, float(max(np.linalg.eigvalsh(cov[:2, :2]))))
        return round(1000.0 * math.sqrt(eig), 2)
    except np.linalg.LinAlgError:
        return None


def bias_path(calibration_path) -> Path:
    return Path(calibration_path).with_suffix(".bias.json")


def validate_bias(region: dict, params=None) -> None:
    for key in ("point_m", "bias_mm"):
        values = region.get(key)
        if (not isinstance(values, (list, tuple)) or len(values) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
            raise ValueError(f"bias refused: {key} must have two finite coordinates")
    limit = prm.get(params, "pivot.max_bias_mm")
    if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
        raise ValueError("bias refused: pivot.max_bias_mm must be finite and positive")
    if math.hypot(*region["bias_mm"]) > limit:
        raise ValueError("bias refused: magnitude is past pivot.max_bias_mm")
    if region.get("kind") is not None and region.get("kind") not in KINDS:
        raise ValueError(f"bias refused: unknown kind {region.get('kind')!r}")
    if region.get("kind") == "visit" and ("radius_mm" in region or "phase_deg" in region):
        raise ValueError("bias refused: visit region must not carry pivot radius_mm or phase_deg")


def load_bias(path, params=None) -> dict:
    path = Path(path)
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size, prm.get(params, "pivot.max_bias_mm"))
    except OSError:
        key = None
    if key in _BIAS_CACHE:
        data = _BIAS_CACHE[key]
        return {**data, "regions": list(data["regions"])}  # a copy: callers rebind regions (save_bias) without touching the cache
    data = json.loads(path.read_text()) if path.exists() else {"schema": SCHEMA, "regions": []}
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: not a {SCHEMA} file")
    for region in data["regions"]:
        validate_bias(region, params)
    if key is not None:
        _BIAS_CACHE[key] = data
    return {**data, "regions": list(data["regions"])}


def save_bias(path, bias: dict, params=None) -> None:
    """Keep one region per site and place within 10 mm; place_look/visit never erase a pivot circle region."""
    validate_bias(bias, params)
    data = load_bias(path, params)
    is_local = bias.get("kind") in ("place_look", "visit")
    data["regions"] = [
        r for r in data["regions"]
        if r["site"] != bias["site"]
        or math.dist(r["point_m"], bias["point_m"]) > 0.010
        or (is_local and is_pivot_region(r))
    ] + [bias]
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)
    _BIAS_CACHE.clear()


def bias_at(data: dict, site: str, point_m, reach_mm: float | None = None, params=None, *,
            pivot_only: bool = False, blend: bool = False):
    """The nearest region's bias (dx, dy mm) within reach of the point (ties prefer pivot circles), or IDW blend when `blend=True`."""
    if blend and not pivot_only:
        return blend_bias_at(data, site, point_m, reach_mm=reach_mm, params=params)
    reach_mm = prm.get(params, "pivot.bias_reach_mm", BIAS_REACH_MM) if reach_mm is None else reach_mm
    for region in data["regions"]:
        validate_bias(region, params)
    near = [r for r in data["regions"]
            if r["site"] == site and (not pivot_only or "radius_mm" in r) and 1000 * math.dist(r["point_m"], point_m) <= reach_mm]
    return min(near, key=lambda r: (round(math.dist(r["point_m"], point_m), 4), 0 if is_pivot_region(r) else 1), default=None)


def blend_bias_at(data: dict, site: str, point_m, reach_mm: float | None = None, params=None) -> dict | None:
    """Smooth inverse-distance + inverse-variance (`1/sigma^2`) blended bias across regions within `reach_mm`."""
    reach_mm = prm.get(params, "pivot.bias_reach_mm", BIAS_REACH_MM) if reach_mm is None else reach_mm
    for region in data["regions"]:
        validate_bias(region, params)
    near = [r for r in data["regions"] if r["site"] == site and 1000.0 * math.dist(r["point_m"], point_m) <= reach_mm]
    if not near:
        return None
    anchor = min(near, key=lambda r: (round(math.dist(r["point_m"], point_m), 4), 0 if is_pivot_region(r) else 1))
    if len(near) == 1:
        return {**anchor, "blended_n": 1}
    wx = wy = wsum = 0.0
    for r in near:
        d_mm = max(5.0, 1000.0 * math.dist(r["point_m"], point_m))
        sig = max(1.0, float(r.get("centre_sigma_mm") or r.get("bias_sigma_mm") or r.get("rms_mm") or 3.0))
        w = (2.0 if is_pivot_region(r) else 1.0) / ((d_mm ** 2) * (sig ** 2))
        wx += w * float(r["bias_mm"][0])
        wy += w * float(r["bias_mm"][1])
        wsum += w
    piv = min((r for r in near if is_pivot_region(r)), key=lambda r: math.dist(r["point_m"], point_m), default=None)
    base = {**anchor, **({"radius_mm": piv["radius_mm"], "phase_deg": piv.get("phase_deg", 0.0)} if piv and "radius_mm" in piv else {})}
    return {**base, "bias_mm": [round(wx / wsum, 2), round(wy / wsum, 2)], "blended_n": len(near)}


def decompose_rigid_drift(points_m, residuals_mm, *, min_points: int = 3, rot_tol_deg: float = 0.8,
                          scale_tol: float = 0.015, explain_ratio: float = 0.70, trans_tol_mm: float = 3.5) -> dict:
    """Decompose multi-site XY residuals into global 2D similarity drift (translation + small rotation/scale)."""
    import numpy as np

    pts = np.asarray(points_m, float).reshape(-1, 2) * 1000.0
    res = np.asarray(residuals_mm, float).reshape(-1, 2)
    if len(pts) != len(res) or len(pts) < min_points or not (np.all(np.isfinite(pts)) and np.all(np.isfinite(res))):
        return {"global_drift": False, "reason": "insufficient_points", "n": len(pts)}
    dp = pts - pts.mean(axis=0)
    if float(np.linalg.svd(dp, compute_uv=False)[-1]) < 15.0:
        return {"global_drift": False, "reason": "collinear_points", "n": len(pts)}
    A = np.zeros((2 * len(pts), 4), float)
    A[0::2] = np.c_[np.ones(len(pts)), np.zeros(len(pts)), dp[:, 0], -dp[:, 1]]
    A[1::2] = np.c_[np.zeros(len(pts)), np.ones(len(pts)), dp[:, 1], dp[:, 0]]
    p, *_ = np.linalg.lstsq(A, res.ravel(), rcond=None)
    tx, ty, s, theta = (float(p[0]), float(p[1]), float(p[2]), float(p[3]))
    tot_ss = float(np.sum(res ** 2))
    err_ss = float(np.sum((res.ravel() - A @ p) ** 2))
    explained = max(0.0, 1.0 - err_ss / tot_ss) if tot_ss > 1e-6 else 0.0
    rot_deg, t_mag = math.degrees(theta), math.hypot(tx, ty)
    rot_or_scale = abs(rot_deg) >= rot_tol_deg or abs(s) >= scale_tol
    is_global = explained >= explain_ratio and (rot_or_scale or t_mag >= trans_tol_mm)
    return {
        "global_drift": bool(is_global), "kind": "rotation_or_scale" if rot_or_scale else ("translation" if is_global else "local"),
        "translation_mm": [round(tx, 2), round(ty, 2)], "rot_deg": round(rot_deg, 3),
        "scale_drift": round(s, 4), "explained_ratio": round(explained, 3), "n": len(pts),
    }
