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
    """Keep one region per site and place: a new one within 10 mm replaces the older."""
    validate_bias(bias, params)
    data = load_bias(path, params)
    data["regions"] = [r for r in data["regions"] if r["site"] != bias["site"]
                       or math.dist(r["point_m"], bias["point_m"]) > 0.010] + [bias]
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)
    _BIAS_CACHE.clear()


def bias_at(data: dict, site: str, point_m, reach_mm: float | None = None, params=None):
    """The nearest region's bias (dx, dy mm) within reach of the point, else None."""
    reach_mm = prm.get(params, "pivot.bias_reach_mm", BIAS_REACH_MM) if reach_mm is None else reach_mm
    for region in data["regions"]:
        validate_bias(region, params)
    near = [r for r in data["regions"] if r["site"] == site and 1000 * math.dist(r["point_m"], point_m) <= reach_mm]
    return min(near, key=lambda r: math.dist(r["point_m"], point_m), default=None)
