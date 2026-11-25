"""Content identity shared by CORE map readback and native sensing."""
import hashlib
import json
from typing import Any


def occupancy_map_id(grid: dict[str, Any]) -> str:
    """Stable id for an occupancy grid so MAP-001 can name an unsaved map."""
    payload = json.dumps(
        {
            "width": grid.get("width"),
            "height": grid.get("height"),
            "resolution": grid.get("resolution"),
            "origin": grid.get("origin") or {},
            "data": list(grid.get("data") or ()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"occupancy:{digest}"
