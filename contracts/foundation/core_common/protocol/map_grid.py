"""Content identity shared by CORE map readback and native sensing."""
import hashlib
import json
from typing import Any


def occupancy_map_id(grid: dict[str, Any]) -> str:
    """Stable id for an occupancy grid so MAP-001 can name an unsaved map."""
    raw_res = grid.get("resolution")
    if isinstance(raw_res, (int, float)) and not isinstance(raw_res, bool):
        res: Any = round(float(raw_res), 6)  # ROS float32 0.05000000074505806 == 0.05
        res = 0.0 if res == 0.0 else res
    else:
        res = raw_res
    raw_origin = grid.get("origin") or {}
    origin = (
        {
            key: (float(val) + 0.0 if isinstance(val, (int, float)) and not isinstance(val, bool) else val)
            for key, val in raw_origin.items()  # -0.0 -> 0.0
        }
        if isinstance(raw_origin, dict)
        else raw_origin
    )
    payload = json.dumps(
        {
            "width": grid.get("width"),
            "height": grid.get("height"),
            "resolution": res,
            "origin": origin,
            "data": list(grid.get("data") or ()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"occupancy:{digest}"
