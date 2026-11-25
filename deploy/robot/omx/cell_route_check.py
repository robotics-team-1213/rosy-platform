"""Read-only configuration checks for a named A/B transfer's depth measurements."""
import math

from cell_site_target import arm_refusal, resolve_cell_ab_site
from cell_zone_verification import _target, _zone_rois


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def route_check(config, source, dest):
    zones, error = _zone_rois(config)
    zones = zones or {}
    floor = bool(zones.get("floor")) and all(_finite(v) for v in zones["floor_depth_mm"])
    report = {}
    for role, name in (("source", source), ("destination", dest)):
        canon = resolve_cell_ab_site(name, allow_belt_temp=False)
        sites = config.get("sites")
        entry = sites.get(name) if isinstance(sites, dict) else None
        target, reason = (_target(config, name) if canon and isinstance(entry, dict)
                          else (None, "missing named site or calibration entry"))
        xy = entry.get("place") if target else None
        pose = (isinstance(xy, (list, tuple)) and len(xy) == 2 and all(map(_finite, xy))
                and _finite(entry.get("surface_z")))
        base = canon["base_site"] if canon and not canon["is_legacy_pallet"] else None
        roi = (zones.get("top") or {}).get(base)
        report[role] = {"site": name, "tier": canon["tier"] if canon else None, "target_error": reason,
                        "site_geometry": bool(target and base and pose), "named_top_roi": roi}
    a, b = (site["named_top_roi"] for site in report.values())
    distinct = a and b and (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
    arm_error = arm_refusal(source, dest, config.get("arm_id", ""))
    return {"sites": report, "arm_error": arm_error,
            "zone_error": error, "floor_reference_configured": floor,
            "depth_inputs_configured": bool(not arm_error and distinct and floor and all(
                site["site_geometry"] and site["named_top_roi"] for site in report.values()))}
