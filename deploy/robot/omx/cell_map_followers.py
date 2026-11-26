"""Bind map_from follower sites added after a remap, without moving the arm or refitting any map.

2026-11-27 arm A: six ship sites added with map_from "pallet" broke the geometry binding and asked for a full
supervised remap. When the only change is added followers of unchanged mapped parents, the bound reference image
is the same and the camera has not shifted, copying the parent records and re-binding is enough.
"""
from __future__ import annotations

from pathlib import Path

import cell_attempts

GEOMETRY_CHANGED = "top camera map site geometry changed"


def site_geometry(config: dict) -> dict:
    """The per-site geometry the map binding covers (non-tier sites only)."""
    return {name: {key: site.get(key) for key in ("auto_roi", "surface_px", "map_from")}
            for name, site in config["sites"].items() if not site.get("tier_of")}


def site_digests(geometry: dict, geometry_sha: str) -> dict:
    """The per-site record saved beside reference_geometry_sha; tied to that sha so a stale record is ignored."""
    return {"geometry_sha": geometry_sha, "sites": {name: cell_attempts.digest(geo) for name, geo in geometry.items()}}


def added_followers(calibration: dict, config: dict, reference_bytes: bytes, shift, limit_px: float) -> list:
    """The added follower sites when they are the only binding change, else [] (keep today's remap)."""
    from cell_auto_evidence import bound_map_error

    record = calibration.get("reference_geometry_sites")
    if not (isinstance(record, dict) and record.get("geometry_sha") == calibration.get("reference_geometry_sha")
            and isinstance(record.get("sites"), dict)):
        return []  # older calibration without the per-site record
    if bound_map_error(calibration, config, reference_bytes) != GEOMETRY_CHANGED:
        return []  # image or map changed too, or nothing changed
    if not (shift and shift.get("ok") and shift.get("max_px", float("inf")) <= limit_px):
        return []
    bound, now = record["sites"], {n: cell_attempts.digest(g) for n, g in site_geometry(config).items()}
    if any(now.get(name) != sha for name, sha in bound.items()):
        return []  # a bound site was removed or changed
    mapped = calibration.get("sites") or {}
    added = sorted(set(now) - set(bound))
    for name in added:
        parent = config["sites"][name].get("map_from")
        if not (isinstance(parent, str) and parent in bound and (mapped.get(parent) or {}).get("homography")):
            return []
    return added


def rebind(config: dict, calibration: dict, cal_path: Path, found: dict, limit_px: float) -> dict:
    """Copy each parent record to its new follower and re-save the binding with the same reference bytes."""
    from cell_calibrate_bound import save_bound_map_reference

    ref_path = Path((config.get("preflight") or {}).get("reference_top") or "").expanduser()
    try:
        raw = ref_path.read_bytes()
    except OSError:
        return {"rebind-followers": "reference unavailable; remap required"}
    added = added_followers(calibration, config, raw, found.get("camera_shift"), limit_px)
    if not added or added != sorted(found.get("rebind_followers") or []):
        return {"rebind-followers": "binding changed since check; run check again"}
    for name in added:
        calibration["sites"][name] = dict(calibration["sites"][config["sites"][name]["map_from"]])
    save_bound_map_reference(cal_path, ref_path, calibration, config, None, raw=raw)
    return {"rebind-followers": added}
