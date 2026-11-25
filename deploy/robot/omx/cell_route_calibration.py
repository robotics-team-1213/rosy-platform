"""Describe reusable named-route calibration and the remaining measurements, without moving the arm."""
from __future__ import annotations

import numpy as np

from cell_attempts import digest
from cell_calibrate_auto import map_agrees
from cell_route_check import _finite, route_check
from cell_route_surface import contact_evidence
from cell_route_visit import exact_visit
from cell_site_target import resolve_cell_ab_site, temp_to_ship


def _map_context(config, calibration, name, entry, check, reference_current):
    sites = config.get("sites") or {}
    records = calibration.get("sites") or {}
    parent = entry.get("tier_of", name)
    parent_spec = sites.get(parent) if isinstance(parent, str) else None
    base = parent_spec.get("map_from", parent) if isinstance(parent_spec, dict) else None
    record = records.get(base) if isinstance(base, str) else None
    result = {"map_site": base, "tier_of": entry.get("tier_of"), "current": False}
    if not isinstance(record, dict):
        return {**result, "reason": "missing_site_map"}
    # Persisted tier aliases can be absent. Conflicting stored copies invalidate inheritance.
    for alias in (parent, name):
        if alias != base and alias in records and records[alias] != record:
            return {**result, "reason": "different_parent_map"}
    matrix = record.get("homography")
    try:
        matrix = np.asarray(matrix, dtype=float)
        usable = matrix.shape == (3, 3) and np.isfinite(matrix).all() and np.linalg.matrix_rank(matrix) == 3
    except (TypeError, ValueError, np.linalg.LinAlgError):
        usable = False
    residuals = record.get("loo_error_mm")
    error = residuals.get("max") if isinstance(residuals, dict) else None
    if not usable or not _finite(error) or error < 0 or not map_agrees(record, config.get("params")):
        return {**result, "reason": "map_fit_unverified"}
    if (config.get("calibrate") or {}).get("tcp_marks") and record.get("marks") != "tcp":
        return {**result, "reason": "tcp_marks_missing"}
    if any(site in (check.get("missing_map") or []) for site in (name, parent, base)):
        return {**result, "reason": "map_check_failed"}
    return {**result, "current": reference_current, "reason": None if reference_current else "reference_not_current"}


def _area_map_candidate(calibration, canonical):
    """A historical camera-to-arm fit may cover the fixture without locating a particular pocket."""
    if not canonical:
        return None
    base = canonical["base_site"]
    if base.startswith("ship-"):
        area = "pallet"
    elif base.startswith(("tmp-a-", "tmp-b-")):
        area = "temp_plate_" + base.split("-")[1]
    else:
        return None
    records = calibration.get("sites") or {}
    record = records.get(area)
    points = record.get("points") if isinstance(record, dict) else None
    if not isinstance(points, list) or not points:
        return None
    for point in points:
        if not isinstance(point, dict):
            return None
        for key in ("pixel", "arm_m"):
            pair = point.get(key)
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(map(_finite, pair)):
                return None
    return {"area_map_site": area, "point_count": len(points), "points_sha": digest(points),
            "sites_with_same_points": sorted(name for name, rec in records.items()
                                             if isinstance(rec, dict) and rec.get("points") == points),
            "z_view_m": record.get("z_view"), "loo_error_mm": record.get("loo_error_mm"),
            "status": "area_measurements_only"}


def route_calibration_report(config, calibration, check, source, destination):
    """Extend the static route check for diagnostic callers; runtime binding keeps its original contract."""
    route = route_check(config, source, destination)
    shift = check.get("camera_shift") or {}
    reference_current = ("map_binding_error" in check and check["map_binding_error"] is None
                         and not check.get("camera_issue") and not check.get("camera_moved")
                         and not check.get("reference_mismatch") and not check.get("no_reference")
                         and shift.get("ok") is True and _finite(shift.get("max_px"))
                         and _finite(check.get("max_shift_px")) and 0 <= shift["max_px"] <= check["max_shift_px"])
    gaps = []
    if route["arm_error"]:
        gaps.append({"action": "resolve_route_arm", "reason": route["arm_error"]})
    if not reference_current:
        gaps.append({"action": "check_camera_map_reference", "reason": check.get("camera_issue")
                     or check.get("map_binding_error") or "unverified_reference"})
    if route["zone_error"]:
        gaps.append({"action": "correct_zone_configuration", "reason": route["zone_error"]})
    endpoints = {}
    for role, site in route["sites"].items():
        name = site["site"]
        entry = (config.get("sites") or {}).get(name)
        entry = entry if isinstance(entry, dict) else {}
        canon = resolve_cell_ab_site(name, allow_belt_temp=False)
        xy = entry.get("place")
        xy = list(xy) if isinstance(xy, (list, tuple)) and len(xy) == 2 and all(map(_finite, xy)) else None
        surface_z = entry.get("surface_z")
        mapped = _map_context(config, calibration, name, entry, check, reference_current)
        candidate = _area_map_candidate(calibration, canon) if not mapped["current"] else None
        visit = exact_visit(config, calibration, name, xy) if canon and xy else {"verified": False, "reason": "missing_named_xy"}
        contact = contact_evidence(config, name, calibration) if canon else {"status": "missing", "reason": "unknown_site"}
        current_context = mapped["current"] and not site["target_error"] and not route["arm_error"]
        hover_current = current_context and visit.get("verified_at_visit_height") is True
        support_xy_current = current_context and visit.get("verified") is True
        contact_current = current_context and contact["status"] == "matched_contact"
        zones = entry if role == "source" and temp_to_ship(source, destination) else config
        floor = zones.get("zone_rois") or {}
        endpoint = {"map": mapped, "area_map_candidate": candidate, "xy_m": xy,
                    "xy_status": ("configured" if xy is not None else "invalid" if "place" in entry else "missing"), "visit": visit, "surface_z_m": surface_z if _finite(surface_z) else None,
                    "contact": contact, "visit_at_height_current": hover_current, "support_xy_current": support_xy_current,
                    "contact_current": contact_current,
                    "top_roi": site["named_top_roi"], "floor_reference": (
                        {"rois": floor["floor"], "optical_depth_mm": floor["floor_depth_mm"]}
                        if site["floor_reference_configured"] else None)}
        endpoints[role] = endpoint
        # These are advisory observations. Nothing in this list is passed to the commissioning executor.
        actions = [(site["target_error"], "resolve_named_site"), (not mapped["current"] and mapped["reason"] != "reference_not_current",
                    "verify_named_site_on_existing_map" if candidate else "validate_site_map"),
                   (xy is None, "review_invalid_named_xy" if "place" in entry else "measure_named_xy"),
                   (xy is not None and not visit.get("verified"),
                    "verify_slot_center_at_contact_height" if hover_current else "verify_named_xy"),
                   (xy is not None and not _finite(surface_z), "review_surface_evidence_at_named_xy"),
                   (xy is not None and _finite(surface_z) and contact["status"] != "matched_contact", "verify_surface_contact"),
                   (not site["named_top_roi"], "register_named_top_roi"),
                   (not site["floor_reference_configured"], "record_depth_floor_reference")]
        gaps.extend({"role": role, "site": name, "action": action} for missing, action in actions if missing)
    a, b = (site["named_top_roi"] for site in route["sites"].values())
    if a and b and not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]):
        gaps.append({"action": "separate_named_top_rois"})
    next_action = ("continue_to_existing_fresh_preflight" if reference_current and route["depth_inputs_configured"]
                   else gaps[0]["action"] if gaps else "review_route_configuration")
    route["calibration_evidence"] = {"reference_current": reference_current, "sites": endpoints,
                                     "gaps": gaps, "gaps_are_advisory": True, "next_machine_action": next_action,
                                     "scene": {"status": "not_sampled", "next": "capture_fresh_route_before_transfer"}}
    return route
