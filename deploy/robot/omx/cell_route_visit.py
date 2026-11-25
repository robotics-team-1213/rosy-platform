"""Reuse post-eval visits at their measured height. A hover cannot measure a slot's support XYZ."""
import json
import math
import uuid
import time
from pathlib import Path

import cv2

import cell_attempts
import cell_cal_monitor
import cell_params as prm
import cell_pivot
import cell_preflight
import cell_site_target
import omx_tcp


def _vector(values, size):
    return (isinstance(values, (list, tuple)) and len(values) == size
            and all(type(v) in (int, float) and math.isfinite(v) for v in values))


def _map(config, calibration, site):
    specs, maps = config.get("sites") or {}, calibration.get("sites") or {}
    spec = specs.get(site) or {}
    parent = spec.get("tier_of", site)
    if not isinstance(parent, str):
        return None
    parent_spec = specs.get(parent) or {}
    base = parent_spec.get("map_from", parent)
    if not isinstance(base, str) or spec.get("map_from", base) != base:
        return None
    record = cell_pivot.map_record(calibration, base)
    if not record or any(k in maps and maps[k] != record for k in (parent, site)):
        return None
    return record


def _bound_calibration(config, calibration, site):
    """A runtime tier alias is an in-memory copy; validate the persisted reference against its own maps."""
    path = config.get("calibration_path")
    if not path:
        return calibration
    try:
        stored = json.loads(Path(path).expanduser().read_bytes())
    except (OSError, TypeError, ValueError):
        return {}
    if (not isinstance(stored, dict) or any(stored.get(k) != calibration.get(k)
            for k in ("reference_top_sha256", "reference_map_sha", "reference_geometry_sha"))
            or _map(config, stored, site) != _map(config, calibration, site)):
        return {}
    return stored


def _attempt_path(config, site, xy, map_sha):
    wd = config.get("work_dir")
    if not wd:
        return None
    key = cell_attempts.digest([config["arm_id"], site, list(xy), map_sha])
    return Path(wd).expanduser() / "route-visit-attempts" / (key + ".json")


def begin_visit(config, calibration, site, xy):
    """Invalidate a previous visit even if this attempt stops before it obtains a jaw observation."""
    if not _context(config, calibration, site):
        return None
    record = _map(config, calibration, site)
    path = _attempt_path(config, site, xy, cell_attempts.digest(record)) if record else None
    if path is None:
        return None
    token = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix("." + token + ".tmp")
    tmp.write_text(json.dumps({"source": "visit_attempt", "id": token}), encoding="utf-8")
    tmp.replace(path)
    return token


def _context(config, calibration, site):
    top_rois = (config.get("zone_rois") or {}).get("top")
    if not isinstance(top_rois, dict) or not top_rois:
        return None
    canon = cell_site_target.resolve_cell_ab_site(site)
    if not canon or canon["is_legacy_pallet"] or config.get("arm_id") not in canon["arms"]:
        return None
    roi = top_rois.get(canon["base_site"])
    tcp = omx_tcp.config_tcp(config)
    reference = calibration.get("reference_top_sha256")
    if (not _vector(roi, 4) or not (0 <= roi[0] < roi[2] <= 640 and 0 <= roi[1] < roi[3] <= 480)
            or tcp is None or not math.isfinite(tcp) or not reference):
        return None
    top = (config.get("cameras") or {}).get("top") or {}
    return {"roi": list(roi), "reference_sha256": reference, "tcp_x_m": tcp,
            "top_geometry": {k: top.get(k) for k in ("height_m", "center_px", "K", "normal")}}


def visit_evidence(config, calibration, site, before, point_m, pixels, fks):
    """Attach actual jaw pixels and settled FK from the visit, without issuing another command."""
    context = _context(config, calibration, site)
    path = (config.get("preflight") or {}).get("reference_top")
    if not context or not path or len(pixels) != 2 or len(fks) != 2:
        return {}
    from cell_auto_evidence import bound_reference_image
    ref, error = bound_reference_image(_bound_calibration(config, calibration, site), config, Path(path).expanduser())
    if error:
        return {}
    try:
        current = before if before.ndim == 2 else cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        shift = cell_preflight.camera_shift_px(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), current)
    except (cv2.error, AttributeError, ValueError):
        return {}
    return {"route_visit": {"attempt_id": config.get("_route_visit_id"), "context": context, "shift": shift, "requested_xy_m": list(point_m),
                            "jaw_pixels": [list(map(float, p)) for p in pixels],
                            "fk_xyzyaw": [list(map(float, v)) for v in fks]}}


def exact_visit(config, calibration, name, xy):
    """Report a matched observation separately from independent verification of the support centre."""
    result = {"verified": False, "verified_at_visit_height": False, "status": "unavailable",
              "reason": "missing exact visit target"}
    if not _vector(xy, 2) or not config.get("arm_id"):
        return result
    specs = config.get("sites") or {}
    if name not in specs and "surface_z" in (specs.get(name.rsplit("-l", 1)[0]) or {}):
        from cell_place_fit import with_tiers
        config, _ = with_tiers(config)
    record = _map(config, calibration or {}, name)
    if not record:
        return {**result, "reason": "missing site map"}
    sha = cell_attempts.digest(record)
    rows = cell_cal_monitor.load_observations(cell_cal_monitor.monitor_path(config), arm_id=config["arm_id"])
    point = [round(v, 4) for v in xy]  # precision of the legacy monitor's place_xy
    exact = [r for r in rows if r.get("schema") == cell_cal_monitor.SCHEMA and r.get("source") == "visit"
             and r.get("site") == name and r.get("map_sha") == sha and r.get("place_xy") == point
             and r.get("post_apply") is not True]
    if not exact:
        return {**result, "reason": "no visit for this site, point and map"}
    row = exact[-1]  # an old success cannot replace the latest exact visit's refusal
    result.update(status="candidate", map_sha=sha, place_xy=point, ts=row.get("ts"))
    params = config.get("params")
    stamp = row.get("ts")
    if not _vector([stamp], 1) or not 0 <= time.time() - stamp <= prm.get(params, "post.max_age_s"):
        return {**result, "reason": "exact visit expired or has an invalid timestamp"}
    if (not all(row.get(k) is True for k in ("accepted", "scene_ok", "finger_ok", "yaw_pair"))
            or row.get("geometry_dependent") is not False):
        return {**result, "reason": "visit lacks accepted opposing-yaw scene and finger observations"}
    data = row.get("route_visit")
    if not isinstance(data, dict):
        return {**result, "reason": "legacy visit lacks bound jaw pixels, settled FK and slot footprint"}
    attempt = _attempt_path(config, name, xy, sha)
    try:
        latest = json.loads(attempt.read_bytes()) if attempt else {}
    except (OSError, TypeError, ValueError):
        latest = {}
    if not isinstance(latest, dict) or not latest.get("id") or data.get("attempt_id") != latest["id"]:
        return {**result, "reason": "latest visit attempt has no matching completed observation"}
    residual, sigma = row.get("residual_mm"), row.get("sigma_mm")
    if (not _vector(residual, 2) or not _vector([sigma], 1) or sigma <= 0
            or math.hypot(*residual) > max(prm.get(params, "post.tol_mm"), 2 * sigma)):
        return {**result, "reason": "visit residual exceeds the post-eval tolerance or is missing"}
    context = _context(config, calibration, name)
    if not context or data.get("context") != context or data.get("requested_xy_m") != list(xy):
        return {**result, "reason": "requested point, camera, TCP or footprint changed"}
    from cell_auto_evidence import bound_map_error
    ref_path = (config.get("preflight") or {}).get("reference_top")
    try:
        reference = Path(ref_path).expanduser().read_bytes()
    except (OSError, TypeError):
        return {**result, "reason": "current map reference unavailable"}
    if error := bound_map_error(_bound_calibration(config, calibration, name), config, reference):
        return {**result, "reason": error}
    shift = data.get("shift") or {}
    if (not isinstance(shift, dict) or shift.get("ok") is not True or not _vector([shift.get("max_px")], 1)
            or not 0 <= shift["max_px"] <= prm.get(params, "calibrate.max_shift_px")):
        return {**result, "reason": "camera was not registered during visit"}
    pixels, fks = data.get("jaw_pixels"), data.get("fk_xyzyaw")
    sides = row.get("jaw_sides")
    if (not isinstance(pixels, list) or len(pixels) != 2 or not all(_vector(v, 2) for v in pixels)
            or not all(0 <= u < 640 and 0 <= v < 480 for u, v in pixels)
            or not isinstance(fks, list) or len(fks) != 2 or not all(_vector(v, 4) for v in fks)
            or sides not in (["ref", "ref"], ["other", "other"])):
        return {**result, "reason": "two identified same-jaw pixel and FK observations required"}
    yaw_gap = abs((fks[0][3] - fks[1][3] + 180) % 360 - 180)
    if 180 - yaw_gap > prm.get(params, "post.yaw_pair_tol_deg"):
        return {**result, "reason": "observed wrist yaws are not opposing"}
    try:
        marks = [cell_pivot.mark_to_arm(record, config, name, px, fk[2]) for px, fk in zip(pixels, fks)]
        center = [(a + b) / 2 for a, b in zip(*marks)]
        error_mm = 1000 * math.dist(center, xy)
        fk_errors_mm = [1000 * math.dist(fk[:2], xy) for fk in fks]
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return {**result, "reason": "cannot replay jaw pixels through the site map"}
    radius_mm = 500 * math.dist(*marks)
    if not prm.get(params, "pivot.radius_lo_mm") <= radius_mm <= prm.get(params, "pivot.radius_hi_mm"):
        return {**result, "reason": "observed jaw radius outside the calibrated interval"}
    if not _vector([error_mm, *fk_errors_mm], 3):
        return {**result, "reason": "nonfinite remapped observations"}
    result.update(observed_xy_m=center, observed_z_m=[fk[2] for fk in fks],
                  center_error_mm=error_mm, fk_errors_mm=fk_errors_mm)
    tol = prm.get(params, "post.tol_mm")
    if max(error_mm, *fk_errors_mm) > tol:
        return {**result, "reason": "observed jaw centre or settled FK missed the requested XY"}
    return {**result, "verified_at_visit_height": True, "status": "observed_at_visit_height",
            "reason": "hover XY observed; slot support centre needs an independent measurement"}
