"""The status message the ingest server sends each phone source (overhead-ingest v1)."""
from __future__ import annotations


def status_message(snap: dict, corners_seen: list, robots_seen: list, field, now: float, ttl_s: float) -> dict:
    """``field`` is the source's (report, monotonic time) pair or None; ``now`` is monotonic."""
    # A field_boundary source calibrates from the floor boundary (D-484), not four
    # corner markers: report its calibration state so the phone stops asking for markers.
    field_state = field[0].get("state") if field is not None and now - field[1] <= ttl_s else None
    return {
        "type": "status",
        "corners_seen": corners_seen,
        "corners_needed": 0 if field_state is not None else 4,
        "robots_seen": robots_seen,
        "rx_fps": snap["rx_fps"],
        "dropped": snap["dropped_bad_header"] + snap["oversize"],
        "field_state": field_state,
    }
