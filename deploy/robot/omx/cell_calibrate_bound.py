"""Writers for the calibration map and the camera reference it is bound to (split out of `cell_calibrate`).

Single Responsibility: carry image regions to a new frame, and publish a remap together with the
actual reference JPEG bytes so an interrupted pair always fails the reader binding.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402


_REF_GRAY_CACHE: dict[str, tuple[int, int, np.ndarray]] = {}


def _load_ref_gray(path: Path):
    import cv2

    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    cached = _REF_GRAY_CACHE.get(key)
    if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]
    img = cv2.imread(key, cv2.IMREAD_GRAYSCALE)
    if img is not None:
        _REF_GRAY_CACHE[key] = (st.st_mtime_ns, st.st_size, img)
    return img


def _finite_float(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _valid_pair(pair) -> tuple[float, float] | None:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    x, y = _finite_float(pair[0]), _finite_float(pair[1])
    return (x, y) if x is not None and y is not None else None


def _site_mapped_points(config: dict, calibration: dict, name: str, site: dict, req_z: float) -> list[tuple[float, float]]:
    import cell_objects
    import cell_pivot

    pts: list[tuple[float, float]] = []
    rec = cell_pivot.map_record(calibration, name)
    if rec is None and isinstance(site.get("map_from"), str):
        rec = cell_pivot.map_record(calibration, site["map_from"])
    top_cam, spx = (config.get("cameras") or {}).get("top"), site.get("surface_px")
    if rec is not None and isinstance(top_cam, dict) and isinstance(spx, (list, tuple)) and len(spx) >= 3:
        poly_px = [p for p in (_valid_pair(q) for q in spx) if p is not None]
        if len(poly_px) >= 3:
            edges = [((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) for a, b in zip(poly_px, poly_px[1:] + poly_px[:1])]
            centre = (sum(p[0] for p in poly_px) / len(poly_px), sum(p[1] for p in poly_px) / len(poly_px))
            arr_m = cell_objects.to_mm(np.asarray([*poly_px, *edges, centre], float), rec, top_cam, req_z) / 1000.0
            pts.extend((float(q[0]), float(q[1])) for q in arr_m)
    for key in ("start", "place"):
        if (xy := _valid_pair(site.get(key))) is not None:
            pts.append(xy)
    return pts


def low_zone_gaps(config: dict, calibration: dict) -> list[dict]:
    """Report mapped low sites (`z < workspace_min_m[2]`) whose coordinates fall outside `plan.limits.low_zones`."""
    plan = config.get("plan")
    if not isinstance(plan, dict) and config.get("plan_path"):
        try:
            plan = json.loads(Path(config["plan_path"]).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    limits = (plan or {}).get("limits") if isinstance(plan, dict) else None
    wmin = limits.get("workspace_min_m") if isinstance(limits, dict) else None
    if not isinstance(wmin, (list, tuple)) or len(wmin) < 3 or (floor_z := _finite_float(wmin[2])) is None:
        return []
    low_zones = limits.get("low_zones") or []
    if not isinstance(low_zones, (list, tuple)):
        return []

    def covered(x: float, y: float, z: float) -> bool:
        if z >= floor_z:
            return True
        for zone in low_zones:
            if not isinstance(zone, dict):
                continue
            xr, yr, z_min = _valid_pair(zone.get("x")), _valid_pair(zone.get("y")), _finite_float(zone.get("z_min_m"))
            if xr is None or yr is None or z_min is None:
                continue
            if xr[0] <= x <= xr[1] and yr[0] <= y <= yr[1]:
                return min(z_min, floor_z) <= z
        return False

    gaps = []
    for name, site in (config.get("sites") or {}).items():
        if not isinstance(site, dict) or site.get("tier_of"):
            continue
        req_z = _finite_float(site.get("z"))
        if req_z is None and (sz := _finite_float(site.get("surface_z"))) is not None:
            req_z = sz + 0.015
        if req_z is None or req_z >= floor_z:
            continue
        pts = _site_mapped_points(config, calibration, name, site, req_z)
        if not pts:
            continue
        missed = [(x, y) for x, y in pts if not covered(x, y, req_z)]
        if missed:
            gaps.append({
                "site": name,
                "z_m": round(req_z, 4),
                "floor_z_m": round(floor_z, 4),
                "uncovered": len(missed),
                "total": len(pts),
                "mapped_x_m": [round(min(p[0] for p in pts), 4), round(max(p[0] for p in pts), 4)],
                "mapped_y_m": [round(min(p[1] for p in pts), 4), round(max(p[1] for p in pts), 4)],
                "uncovered_x_m": [round(min(p[0] for p in missed), 4), round(max(p[0] for p in missed), 4)],
                "uncovered_y_m": [round(min(p[1] for p in missed), 4), round(max(p[1] for p in missed), 4)],
            })
    return gaps


def coverage_advisories(config: dict, calibration: dict, bias: dict | None, params=None) -> dict:
    """Strictly advisory bias-reach gaps (never alters `stale()`) and per-site map extrapolation warnings."""
    import cell_calibrate_auto as auto
    import cell_map_fit
    import cell_params as prm
    import cell_pivot

    top_cam = (config.get("cameras") or {}).get("top") or {}
    reach_mm = float(prm.get(params, "pivot.bias_reach_mm", cell_pivot.BIAS_REACH_MM))
    sigma_limit = float(prm.get(params, "verify.map_sigma_max_mm"))
    bias_gaps, lev_warns = [], []
    regions = (bias or {}).get("regions") if isinstance(bias, dict) else None
    for name, site in (config.get("sites") or {}).items():
        if not isinstance(site, dict) or site.get("tier_of"):
            continue
        rec = cell_pivot.map_record(calibration, name)
        if rec is None and isinstance(site.get("map_from"), str):
            rec = cell_pivot.map_record(calibration, site["map_from"])
        if rec is None:
            continue
        anchors = [xy for k in ("start", "place") if (xy := _valid_pair(site.get(k))) is not None]
        if isinstance(regions, list):
            cov_pts = list(anchors)
            if not cov_pts:
                tz = _finite_float(site.get("z")) or _finite_float(site.get("surface_z")) or 0.0
                if mapped := _site_mapped_points(config, calibration, name, site, tz):
                    cov_pts = [(sum(p[0] for p in mapped) / len(mapped), sum(p[1] for p in mapped) / len(mapped))]
            if cov_pts:
                map_sha = cell_attempts.digest(rec)
                fresh = [
                    r for r in regions
                    if r.get("site") == name and not auto.carried(r) and (r.get("map_sha") is None or r.get("map_sha") == map_sha)
                ]
                missed = [pt for pt in cov_pts if not any(1000.0 * math.dist(r["point_m"], pt) <= reach_mm for r in fresh)]
                if missed:
                    bias_gaps.append({
                        "site": name, "uncovered": len(missed), "total": len(cov_pts),
                        "suggested_pivot": [round(missed[0][0], 4), round(missed[0][1], 4)],
                    })
        if anchors:
            tz = _finite_float(site.get("z"))
            summary = cell_map_fit.site_sigma_summary(rec, anchors, top_cam, tz)
            if summary and summary["max_mm"] > sigma_limit:
                lev_warns.append({"site": name, **summary, "limit_mm": sigma_limit})
    out: dict = {}
    if bias_gaps:
        out["bias_coverage_gaps"] = bias_gaps
    if lev_warns:
        out["map_leverage_warn"] = lev_warns
    return out


RECT_REGIONS = ("auto_roi", "detect_roi", "moving_px")  # [x0, y0, x1, y1] per site


def move_regions(config: dict, reference, current) -> dict:
    """Carry every image region (site polygons and ROIs) from the reference frame to the current one (ORB + RANSAC)."""
    import cv2

    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(reference, None)
    k2, d2 = orb.detectAndCompute(current, None)
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:600]
    H, _ = cv2.findHomography(
        np.float32([k1[x.queryIdx].pt for x in m]), np.float32([k2[x.trainIdx].pt for x in m]), cv2.RANSAC, 3.0
    )
    tp = lambda pts: [[int(round(float(v))) for v in q] for q in cv2.perspectiveTransform(np.float32([pts]), H)[0]]  # noqa: E731
    def rect(r):
        q = np.array(tp([[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]))
        return [int(max(0, q[:, 0].min())), int(max(0, q[:, 1].min())), int(min(639, q[:, 0].max())), int(min(479, q[:, 1].max()))]

    # 2026-11-27 arm_s: only surface_px and auto_roi moved, so belt.detect_roi stayed above the belt and every pick saw 0 objects
    for site in config["sites"].values():
        if site.get("surface_px"):
            site["surface_px"] = tp(site["surface_px"])
        for key in RECT_REGIONS:
            if site.get(key):
                site[key] = rect(site[key])
                if key != "auto_roi" and (site[key][0] >= site[key][2] or site[key][1] >= site[key][3]):
                    del site[key]  # moved out of the frame: readers fall back to auto_roi rather than an empty box
        if site.get("markings_px"):
            site["markings_px"] = [tp(p) for p in site["markings_px"]]
        if site.get("home_jaws_px"):
            site["home_jaws_px"] = tp([site["home_jaws_px"]])[0]
    for holder in (config, config.get("calibrate") or {}):
        if holder.get("scene_ignore_px"):
            holder["scene_ignore_px"] = [rect(r) for r in holder["scene_ignore_px"]]
    return config


MAP_GEOMETRY = ("auto_roi", "surface_px", "map_from")


def geometry_sha(config: dict) -> str:
    """The site geometry a bound map was measured with (cell_auto_evidence.bound_map_error checks the same digest)."""
    return cell_attempts.digest({name: {key: site.get(key) for key in MAP_GEOMETRY}
                                 for name, site in config["sites"].items() if not site.get("tier_of")})


def sync_siblings(config_path, config: dict, cal_path, old_sha) -> dict:
    """After a remap rebinds the shared map to this config's moved geometry, give the same geometry to every other config of
    the arm that reads the same calibration file (stack and policy profiles) and still matched the replaced binding. A sibling
    that had drifted from that binding is left as it is (its runs stay held on the binding check) and named in "held"."""
    import cell_config_io

    me, cal = Path(config_path).resolve(), Path(cal_path).expanduser().resolve()
    out: dict = {"synced": [], "held": []}
    for path in sorted(me.parent.glob("cell-arm-*.json")):
        try:
            sib = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if path.resolve() == me or not isinstance(sib, dict) or not isinstance(sib.get("calibration_path"), str) \
                or Path(sib["calibration_path"]).expanduser().resolve() != cal:
            continue
        with cell_config_io.locked(path):
            raw = path.resolve().read_bytes()
            sib = json.loads(raw.decode("utf-8"))
            if not old_sha or set(sib.get("sites") or {}) != set(config["sites"]) or geometry_sha(sib) != old_sha:
                out["held"].append(path.name)
                continue
            for name, site in config["sites"].items():
                for key in MAP_GEOMETRY:
                    if key in site:
                        sib["sites"][name][key] = site[key]
                    else:
                        sib["sites"][name].pop(key, None)
            cell_config_io.atomic_write(path, cell_config_io.dump(sib, 1), cell_config_io.sha256_bytes(raw))
        out["synced"].append(path.name)
    return out


def save_bound_map_reference(cal_path: Path, ref_path: Path, calibration: dict, config: dict, image, raw: bytes | None = None) -> None:
    """Publish a remap and its actual JPEG bytes so an interrupted pair always fails the reader binding.

    raw: the bound JPEG bytes to keep as they are (no re-encode) when only the binding changes."""
    import cv2
    import cell_map_followers

    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_tmp = ref_path.with_name(ref_path.stem + ".pending" + ref_path.suffix)
    if raw is not None:
        ref_tmp.write_bytes(raw)
    elif not cv2.imwrite(str(ref_tmp), image):
        raise OSError("map reference JPEG write failed")
    raw = ref_tmp.read_bytes()
    if not raw:
        raise OSError("map reference JPEG is empty")
    calibration["reference_top_sha256"] = hashlib.sha256(raw).hexdigest()
    calibration["reference_map_sha"] = cell_attempts.digest(calibration["sites"])
    calibration["reference_geometry_sha"] = geometry_sha(config)
    calibration["reference_geometry_sites"] = cell_map_followers.site_digests(
        cell_map_followers.site_geometry(config), calibration["reference_geometry_sha"])
    import cell_cal_history

    cell_cal_history.keep([cal_path, ref_path, Path(cal_path).with_suffix(".bias.json")], "map")
    cal_tmp = cal_path.with_suffix(".pending.json")
    with cal_tmp.open("w", encoding="utf-8") as stream:
        json.dump(calibration, stream)
        stream.flush()
        os.fsync(stream.fileno())
    ref_tmp.replace(ref_path)
    cal_tmp.replace(cal_path)


def map_sites(config: dict) -> list:
    """The sites one remap serves: calibrate.map_sites, else arm A's floor/pinky/belt."""
    return config.get("calibrate", {}).get("map_sites") or [
        s for s in ("floor", "pinky", "belt") if s in config["sites"]
    ]


def _map_write_sites(config: dict) -> list:
    """Configured map_sites plus any site whose `map_from` mirrors one of them (so followers never go stale)."""
    sites = list(map_sites(config))
    seen = set(sites)
    for name, site in (config.get("sites") or {}).items():
        if isinstance(site, dict) and not site.get("tier_of") and site.get("map_from") in seen and name not in seen:
            sites.append(name)
            seen.add(name)
    return sites
