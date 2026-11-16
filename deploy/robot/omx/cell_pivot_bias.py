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
KINDS = ("pivot", "known_geometry", "place_look")


def is_pivot_region(region: dict) -> bool:
    """True when the region carries a pivot circle (`radius_mm`/`phase_deg`) or known-geometry marker."""
    return "radius_mm" in region or region.get("kind") in ("pivot", "known_geometry")


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
    """Keep one region per site and place within 10 mm; place_look never erases a pivot circle region."""
    validate_bias(bias, params)
    data = load_bias(path, params)
    is_place = bias.get("kind") == "place_look"
    data["regions"] = [
        r for r in data["regions"]
        if r["site"] != bias["site"]
        or math.dist(r["point_m"], bias["point_m"]) > 0.010
        or (is_place and is_pivot_region(r))
    ] + [bias]
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)
    _BIAS_CACHE.clear()


def bias_at(data: dict, site: str, point_m, reach_mm: float | None = None, params=None, *, pivot_only: bool = False):
    """The nearest region's bias (dx, dy mm) within reach of the point (ties prefer pivot circles), else None."""
    reach_mm = prm.get(params, "pivot.bias_reach_mm", BIAS_REACH_MM) if reach_mm is None else reach_mm
    for region in data["regions"]:
        validate_bias(region, params)
    near = [r for r in data["regions"]
            if r["site"] == site and (not pivot_only or "radius_mm" in r) and 1000 * math.dist(r["point_m"], point_m) <= reach_mm]
    return min(near, key=lambda r: (round(math.dist(r["point_m"], point_m), 4), 0 if is_pivot_region(r) else 1), default=None)
