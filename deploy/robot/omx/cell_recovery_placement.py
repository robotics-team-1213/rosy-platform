"""Select the shortest admissible loaded-arm route before incident-bound homing."""
from __future__ import annotations

import math


def _path_length(candidate):
    """Measure the entire planned approach and descent in the calibrated arm-base frame."""
    if not isinstance(candidate, dict) or not isinstance(candidate.get("target"), str) or not candidate["target"]:
        return None
    path = candidate.get("path_xyz_m")
    if not isinstance(path, (tuple, list)) or len(path) < 2:
        return None
    for point in path:
        if not isinstance(point, (tuple, list)) or len(point) != 3:
            return None
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in point):
            return None
    length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
    return length if math.isfinite(length) else None


def place_nearest(backend, *, holding, journal, incident_id):
    """Run at most one placement. The backend owns observed occupancy, geometric fit,
    immobility, planning, workspace leases and guarded motion through verified retreat.
    """
    if holding is not True:
        return {"result": "held", "reason": "GRASP_UNCONFIRMED"}
    ranked = []
    for candidate in backend.candidates():
        length = _path_length(candidate)
        if length is not None:
            ranked.append((length, candidate))
    ranked.sort(key=lambda item: (item[0], item[1]["target"]))
    for length, candidate in ranked:
        if backend.available(candidate) is not True or backend.reserve(candidate) is not True:
            continue
        if backend.available(candidate) is not True:
            backend.release(candidate)
            continue
        selected = {"target": candidate["target"], "path_length_m": length}
        if journal.begin(incident_id, candidate["target"]) is not True:
            backend.release(candidate)
            return {"result": "held", "reason": "PLACEMENT_ALREADY_PENDING", **selected}
        # After issuing motion, an uncertain result leaves the reservation to its TTL.
        try:
            receipt = backend.place(candidate)
        except (OSError, RuntimeError, ValueError) as exc:
            return {"result": "held", "reason": "PLACEMENT_UNVERIFIED", "error": str(exc), **selected}
        if isinstance(receipt, dict):
            selected["placement_receipt"] = receipt
        if not isinstance(receipt, dict) or not all(
            receipt.get(field) is True for field in ("supported", "released", "verified", "retreated")
        ):
            result = {"result": "held", "reason": "PLACEMENT_UNVERIFIED", **selected}
            if isinstance(receipt, dict) and isinstance(receipt.get("reason"), str):
                result["placement_reason"] = receipt["reason"]
            return result
        if journal.verified(incident_id, candidate["target"]) is not True:
            return {"result": "held", "reason": "PLACEMENT_UNVERIFIED", **selected}
        backend.release(candidate)
        return {"result": "placed", **selected}
    result = {"result": "held", "reason": "NO_AVAILABLE_PLACEMENT"}
    if diagnostics := getattr(backend, "diagnostics", None):
        result["candidates"] = diagnostics
    return result
