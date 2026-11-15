"""Read-only engine snapshot builder for Calibration profile management and '모눈종이' grid view (D-951).

Reads profile registries (arm_a, arm_b, arm_s, ...) and computes:
- per-point leave-one-out (LOO) residuals, dropped mark errors, and planned-vs-hit coverage
- parallax-projected site start/place coordinates (z_view vs surface_z)
- pivot-near bias staleness (map_sha vs active homography digest)
- reference-top map binding & optional camera shift
- operating_profile hygiene checks & live FK TCP / hold status

Never opens hardware connections and never writes config, calibration, bias, or request files.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
for _extra in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_extra) not in sys.path:
        sys.path.append(str(_extra))

import cell_attempts  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pivot  # noqa: E402

try:
    from cell_auto_evidence import bound_map_error  # noqa: E402
except ImportError:
    bound_map_error = None  # type: ignore[assignment]

DEFAULT_MAP_POINTS = [
    [-0.12, 0.17], [-0.10, 0.19], [-0.08, 0.17], [-0.06, 0.19], [-0.04, 0.17], [-0.10, 0.15],
    [-0.06, 0.15], [-0.02, 0.19], [0.02, 0.19], [0.066, 0.195], [0.06, 0.18], [0.04, 0.17],
]
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _read_json(path: Path | None) -> tuple[dict | None, str | None]:
    if path is None or not str(path) or not path.is_file():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data if isinstance(data, dict) else None), (None if isinstance(data, dict) else "not-object")
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def load_profile_registry(registry_path: Path | None) -> list[dict[str, Any]]:
    """Load profile entries from a JSON file (`[{id, config_path, ...}]` or `{'profiles': [...]}`)."""
    if registry_path is None or not registry_path.is_file():
        return []
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    items = raw.get("profiles") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("profiles registry must be a list or {'profiles': [...]}")
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("config_path"):
            raise ValueError("each profile entry requires 'id' and 'config_path'")
        out.append(dict(item))
    return out


def is_allowed_frame_url(url: str | None) -> bool:
    """Only allow HTTP(S) loopback URLs unless explicitly opted in as trusted local camera endpoints."""
    if not isinstance(url, str) or not url.strip():
        return False
    parts = urlsplit(url.strip())
    return parts.scheme in {"http", "https"} and (parts.hostname or "").lower() in LOOPBACK_HOSTS


def resolve_frame_target(entry: dict[str, Any], source: str) -> dict[str, Any]:
    """Resolve a server-side reference file path or live frame source for `profile_id`."""
    cfg_path = Path(entry["config_path"])
    config, _ = _read_json(cfg_path)
    config = config or {}
    if source == "reference":
        ref_str = entry.get("reference_top_path") or (config.get("preflight") or {}).get("reference_top") or ""
        return {"kind": "file", "path": Path(ref_str) if ref_str else None}
    if source == "live":
        if entry.get("live_top_path"):
            return {"kind": "file", "path": Path(entry["live_top_path"])}
        url = entry.get("live_frame_url") or ((config.get("cameras") or {}).get("top") or {}).get("url")
        return {"kind": "url", "url": url}
    return {"kind": "none"}


def _image_size(path: Path | None) -> list[int] | None:
    if path is None or not path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as img:
            return [int(img.width), int(img.height)]
    except Exception:
        return None


def _camera_shift(ref_path: Path | None, live_path: Path | None) -> dict | None:
    if not (ref_path and ref_path.is_file() and live_path and live_path.is_file()):
        return None
    try:
        import cv2
        import cell_preflight
        ref = cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE)
        cur = cv2.imread(str(live_path), cv2.IMREAD_GRAYSCALE)
        if ref is None or cur is None:
            return None
        return cell_preflight.camera_shift_px(ref, cur)
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}


def _project_point(record: dict | None, camera: dict, arm_xy: list[float] | None, target_z: float | None) -> dict:
    if not arm_xy or len(arm_xy) < 2 or not record or not record.get("homography"):
        return {"arm_m": arm_xy, "pixel_z_view": None, "pixel_surface_z": None}
    h = record["homography"]
    try:
        u_zv, v_zv = cal.to_pixel(h, arm_xy[:2])
        px_zv = [round(float(u_zv), 2), round(float(v_zv), 2)]
    except Exception:
        return {"arm_m": arm_xy, "pixel_z_view": None, "pixel_surface_z": None}
    px_sz = None
    fit_z = record.get("z_view")
    if target_z is not None and fit_z is not None and camera.get("center_px") and camera.get("height_m"):
        try:
            us, vs = cal.parallax((u_zv, v_zv), float(fit_z), float(target_z), camera)
            px_sz = [round(float(us), 2), round(float(vs), 2)]
        except Exception:
            px_sz = None
    return {"arm_m": [float(arm_xy[0]), float(arm_xy[1])], "pixel_z_view": px_zv, "pixel_surface_z": px_sz}


def _build_map_detail(record: dict | None, planned_pts: list[list[float]], config: dict, target_z: float | None) -> dict | None:
    if not record or not record.get("homography"):
        return None
    h = record["homography"]
    camera = (config.get("cameras") or {}).get("top") or {}
    raw_points = record.get("points") or []
    pts = [(tuple(p["pixel"]), tuple(p["arm_m"])) for p in raw_points if p.get("pixel") and p.get("arm_m")]

    inliers = []
    for i, (px, arm_pt) in enumerate(pts):
        pred_full = cal.to_arm(h, px)
        fit_dx = round((pred_full[0] - arm_pt[0]) * 1000.0, 2)
        fit_dy = round((pred_full[1] - arm_pt[1]) * 1000.0, 2)
        loo_res = None
        loo_dist = None
        if len(pts) >= 4:
            try:
                h_i = cal.fit(pts[:i] + pts[i + 1:])
                pred_i = cal.to_arm(h_i, px)
                lx = round((pred_i[0] - arm_pt[0]) * 1000.0, 2)
                ly = round((pred_i[1] - arm_pt[1]) * 1000.0, 2)
                loo_res = [lx, ly]
                loo_dist = round(math.hypot(lx, ly), 2)
            except ValueError:
                loo_res = None
                loo_dist = None
        inliers.append({
            "index": i,
            "pixel": [round(float(px[0]), 2), round(float(px[1]), 2)],
            "arm_m": [float(arm_pt[0]), float(arm_pt[1])],
            "loo_residual_mm": loo_res,
            "loo_dist_mm": loo_dist,
            "fit_residual_mm": [fit_dx, fit_dy],
            "fit_dist_mm": round(math.hypot(fit_dx, fit_dy), 2),
        })

    dropped = []
    for d in record.get("dropped_marks") or []:
        px, arm_pt = d.get("pixel"), d.get("arm_m")
        if not (px and arm_pt):
            continue
        pred_arm = cal.to_arm(h, px)
        pred_px = cal.to_pixel(h, arm_pt)
        dx = round((pred_arm[0] - arm_pt[0]) * 1000.0, 2)
        dy = round((pred_arm[1] - arm_pt[1]) * 1000.0, 2)
        dropped.append({
            "pixel": [round(float(px[0]), 2), round(float(px[1]), 2)],
            "arm_m": [float(arm_pt[0]), float(arm_pt[1])],
            "pred_pixel": [round(float(pred_px[0]), 2), round(float(pred_px[1]), 2)],
            "pred_arm_m": [round(float(pred_arm[0]), 5), round(float(pred_arm[1]), 5)],
            "err_mm": [dx, dy],
            "err_dist_mm": round(math.hypot(dx, dy), 2),
            "err_px": round(math.hypot(px[0] - pred_px[0], px[1] - pred_px[1]), 2),
        })

    inlier_arms = [p["arm_m"] for p in inliers]
    dropped_arms = [d["arm_m"] for d in dropped]
    near = lambda pt, pool: any(math.hypot(pt[0] - q[0], pt[1] - q[1]) <= 5e-4 for q in pool)
    planned = []
    for pt in planned_pts:
        status = "inlier" if near(pt, inlier_arms) else ("dropped" if near(pt, dropped_arms) else "missed")
        proj = _project_point(record, camera, pt, target_z)
        planned.append({
            "arm_m": [float(pt[0]), float(pt[1])],
            "status": status,
            "pixel_z_view": proj["pixel_z_view"],
            "pixel_surface_z": proj["pixel_surface_z"],
        })

    return {
        "homography": h,
        "z_view": record.get("z_view"),
        "coarse": bool(record.get("coarse")),
        "measured": record.get("measured") or "",
        "note": record.get("note") or "",
        "digest": cell_attempts.digest(record),
        "loo_error_mm": record.get("loo_error_mm"),
        "inlier_count": len(inliers),
        "dropped_count": len(dropped),
        "planned_count": len(planned),
        "points": inliers,
        "dropped_marks": dropped,
        "planned_points": planned,
    }


def _parse_live(live: dict | None, config: dict, plan: dict | None, ref_record: dict | None,
                now_ts: float | None = None) -> dict:
    if not live:
        return {"present": False, "stale": True, "age_s": None}
    t = live.get("t")
    now = now_ts if now_ts is not None else time.time()
    age_s = round(now - float(t), 2) if isinstance(t, (int, float)) else None
    stale = True if age_s is None else age_s > 2.0
    state = live.get("state")
    tcp = None
    tcp_pixel = None
    tcp_x_m = config.get("tcp_x_m") if config.get("tcp_x_m") is not None else (plan or {}).get("tcp_x_m")
    if isinstance(state, list) and len(state) >= 5:
        try:
            x, y, z, yaw = cell_pivot.joints_tcp(state, tcp_x_m)
            tcp = {"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(z), 4),
                   "yaw_deg": round(float(yaw), 1)}
            camera = (config.get("cameras") or {}).get("top") or {}
            if ref_record and ref_record.get("homography"):
                u, v = cal.to_pixel(ref_record["homography"], (x, y))
                if ref_record.get("z_view") is not None and camera.get("center_px") and camera.get("height_m"):
                    u, v = cal.parallax((u, v), float(ref_record["z_view"]), float(z), camera)
                tcp_pixel = [round(float(u), 2), round(float(v), 2)]
        except (Exception, SystemExit):  # resolve_tcp calls sys.exit/SystemExit when tcp_x_m is absent
            tcp = None
    return {
        "present": True, "stale": stale, "age_s": age_s, "t": t,
        "chunk": live.get("chunk"), "lag": live.get("lag"), "fault": live.get("fault"),
        "state": state, "target": live.get("target"), "tcp": tcp, "tcp_pixel": tcp_pixel,
        "health": live.get("health") or {},
    }


def _check_operating_profile(op_prof: dict | None, op_err: str | None, config: dict, arm_id: str,
                             hygiene: list[dict[str, str]]) -> None:
    if op_prof is None:
        hygiene.append({"level": "warning", "code": "operating_profile_missing",
                        "message": f"operating_profile_path 없음 ({op_err})"})
        return
    if op_prof.get("device_id") != arm_id:
        hygiene.append({"level": "error", "code": "profile_device_mismatch",
                        "message": f"operating_profile device_id={op_prof.get('device_id')} != arm_id={arm_id}"})
    if op_prof.get("work_dir") != config.get("work_dir"):
        hygiene.append({"level": "warning", "code": "profile_workdir_mismatch",
                        "message": f"operating_profile work_dir({op_prof.get('work_dir')}) != config.work_dir({config.get('work_dir')})"})
    env_p = op_prof.get("operating_envelope_path")
    if env_p and not Path(env_p).exists():
        hygiene.append({"level": "warning", "code": "envelope_missing_on_host",
                        "message": f"operating_envelope_path 미확인/누락: {Path(env_p).name}"})


def _build_cross_verify(
    sites_out: dict[str, dict[str, Any]], depth_verify: dict | None, regions_out: list[dict],
    live_info: dict, bind_err: str | None,
) -> dict[str, Any]:
    dv_sites = (depth_verify or {}).get("sites") or {}
    any_depth = bool(depth_verify and any(s.get("depth_surface_z") is not None for s in sites_out.values()))
    depth_bad = any("depth_diff_gt_6mm" in s.get("cross_verify_flags", []) or "place_vs_start_step_gt_8mm" in s.get("cross_verify_flags", []) for s in sites_out.values())
    depth_v = "fail" if depth_bad else ("pass" if any_depth else ("warn" if depth_verify else "unmeasured"))

    touch_diffs = [abs(s["touch_diff_mm"]) for s in sites_out.values() if s.get("touch_diff_mm") is not None]
    touch_count = sum(1 for s in sites_out.values() if s.get("touch_surface_z") is not None)
    touch_bad = any(d > 5.0 for d in touch_diffs)
    touch_v = "fail" if touch_bad else ("pass" if touch_count else "unmeasured")

    loos = [s["map"]["loo_error_mm"]["max"] for s in sites_out.values()
            if not s.get("extra") and (s.get("map") or {}).get("loo_error_mm") and s["map"]["loo_error_mm"].get("max") is not None]
    max_loo = round(max(loos), 2) if loos else None
    loo_limit = float(prm.default("calibrate.max_loo_mm"))
    map_v = "fail" if (max_loo is not None and max_loo > loo_limit) else ("warn" if (bind_err or max_loo is None) else "pass")

    fresh_bias = sum(1 for r in regions_out if not r.get("stale_map"))
    bias_v = "fail" if (regions_out and fresh_bias < len(regions_out)) else ("pass" if regions_out else "warn")

    fk_fresh = bool(live_info.get("present") and not live_info.get("stale") and live_info.get("tcp"))
    fk_v = "pass" if fk_fresh else ("warn" if live_info.get("present") else "unmeasured")

    sub = (depth_v, touch_v, map_v)
    overall = "fail" if "fail" in sub or bias_v == "fail" else ("warn" if "warn" in (*sub, bias_v) else ("pass" if (any_depth or touch_count) else "unmeasured"))
    cam_top = dict((depth_verify or {}).get("camera_top") or {})
    return {
        "present": bool(depth_verify or touch_count or dv_sites),
        "depth_verify_present": bool(depth_verify),
        "measured": (depth_verify or {}).get("measured"),
        "verdict": overall,
        "depth": {"verdict": depth_v, **cam_top},
        "touch": {"verdict": touch_v, "sites_measured": touch_count, "max_diff_mm": round(max(touch_diffs), 1) if touch_diffs else None},
        "map": {"verdict": map_v, "max_loo_mm": max_loo, "map_bound": not bind_err},
        "bias": {"verdict": bias_v, "fresh_regions": fresh_bias, "total_regions": len(regions_out)},
        "fk": {"verdict": fk_v, "present": bool(live_info.get("present")), "fresh": fk_fresh, "tcp_z_m": (live_info.get("tcp") or {}).get("z")},
    }


def _attach_site_cross_verify(name: str, is_extra: bool, surface_z, dv_site: dict, touch: dict | None,
                              hygiene: list[dict[str, str]]) -> dict[str, Any]:
    depth_z = dv_site.get("depth_surface_z_m")
    depth_diff = round((float(depth_z) - float(surface_z)) * 1000.0, 1) if (depth_z is not None and surface_z is not None) else dv_site.get("depth_diff_mm")
    step_mm = dv_site.get("place_vs_start_step_mm")
    touch_z = touch.get("surface_z") if (touch and touch.get("result") in (None, "touched") and touch.get("surface_z") is not None) else dv_site.get("touch_surface_z_m")
    touch_diff = round((float(touch_z) - float(surface_z)) * 1000.0, 1) if (touch_z is not None and surface_z is not None) else dv_site.get("touch_diff_mm")
    flags = list(dv_site.get("flags") or [])
    if depth_diff is not None and abs(depth_diff) > 6.0 and "depth_diff_gt_6mm" not in flags:
        flags.append("depth_diff_gt_6mm")
    if step_mm is not None and abs(step_mm) > 8.0 and "place_vs_start_step_gt_8mm" not in flags:
        flags.append("place_vs_start_step_gt_8mm")
    if touch_diff is not None and abs(touch_diff) > 5.0 and "touch_diff_gt_5mm" not in flags:
        flags.append("touch_diff_gt_5mm")
    if not is_extra:
        if "depth_diff_gt_6mm" in flags:
            hygiene.append({"level": "warning", "code": f"depth_diff:{name}",
                            "message": f"{name}: D435 depth({depth_z}) vs surface_z({surface_z}) = {depth_diff:+.1f} mm"})
        if "place_vs_start_step_gt_8mm" in flags:
            hygiene.append({"level": "warning", "code": f"place_step:{name}",
                            "message": f"{name}: place vs start 높이차 {step_mm:+.1f} mm (적재물/단차 의심)"})
        if "touch_diff_gt_5mm" in flags:
            hygiene.append({"level": "error", "code": f"touch_diff:{name}",
                            "message": f"{name}: touch({touch_z}) vs surface_z({surface_z}) = {touch_diff:+.1f} mm"})
    crit = any(f in ("depth_diff_gt_6mm", "place_vs_start_step_gt_8mm", "touch_diff_gt_5mm") for f in flags)
    status = "fail" if crit else ("pass" if (depth_z is not None or touch_z is not None) else "unmeasured")
    return {
        "depth_surface_z": depth_z, "depth_diff_mm": depth_diff, "place_vs_start_step_mm": step_mm,
        "touch_surface_z": touch_z, "touch_measured": (touch or {}).get("measured") or dv_site.get("touch_measured"),
        "touch_diff_mm": touch_diff, "cross_verify_flags": flags, "cross_verify_status": status,
    }


def build_profile_snapshot(entry: dict[str, Any], *, now_ts: float | None = None) -> dict[str, Any]:
    """Build a read-only calibration & status snapshot for one profile registry entry."""
    cfg_path = Path(entry["config_path"])
    config, cfg_err = _read_json(cfg_path)
    if config is None:
        return {"id": entry["id"], "label": entry.get("label", entry["id"]), "error": f"config {cfg_err}"}

    arm_id = config.get("arm_id", entry["id"])
    cal_str = str(entry.get("calibration_path") or config.get("calibration_path") or "")
    cal_path = Path(cal_str) if cal_str else None
    bias_str = str(entry.get("bias_path") or (cell_pivot.bias_path(cal_path) if cal_path else ""))
    bias_path = Path(bias_str) if bias_str else None
    op_str = str(entry.get("operating_profile_path") or config.get("operating_profile_path") or "")
    op_path = Path(op_str) if op_str else None
    plan_str = str(entry.get("plan_path") or config.get("plan_path") or "")
    plan_path = Path(plan_str) if plan_str else None
    live_str = str(entry.get("live_path") or (Path(config["io"]) / "live.json" if config.get("io") else ""))
    live_path = Path(live_str) if live_str else None
    ref_str = str(entry.get("reference_top_path") or (config.get("preflight") or {}).get("reference_top") or "")
    ref_path = Path(ref_str) if ref_str else None
    live_img_path = Path(entry["live_top_path"]) if entry.get("live_top_path") else None
    inc_path = Path(entry["incident_path"]) if entry.get("incident_path") else None
    raw_wd = Path(config["work_dir"]).expanduser() if config.get("work_dir") else None
    work_dir = raw_wd if (raw_wd is None or raw_wd.is_absolute() or raw_wd.exists()) else (cfg_path.parent / raw_wd)
    dv_path = Path(entry["depth_verify_path"]) if entry.get("depth_verify_path") else (work_dir / "depth-verify.json" if work_dir else None)

    calibration, cal_err = _read_json(cal_path)
    bias, bias_err = _read_json(bias_path)
    op_prof, op_err = _read_json(op_path)
    plan, _ = _read_json(plan_path)
    live, _ = _read_json(live_path)
    incident, _ = _read_json(inc_path)
    depth_verify, _ = _read_json(dv_path)

    calibration = calibration or {"schema": cal.SCHEMA, "sites": {}}
    bias = bias or {"schema": cell_pivot.SCHEMA, "regions": []}
    with_maps = cell_pivot.with_site_maps(config, calibration) if calibration.get("sites") else calibration
    planned_pts = (config.get("calibrate") or {}).get("map_points") or DEFAULT_MAP_POINTS
    map_sites = (config.get("calibrate") or {}).get("map_sites") or []
    camera_top = dict((config.get("cameras") or {}).get("top") or {})
    frame_size = _image_size(ref_path) or _image_size(live_img_path) or [640, 480]
    shift = _camera_shift(ref_path, live_img_path)

    hygiene: list[dict[str, str]] = []
    if cal_err:
        hygiene.append({"level": "error", "code": "calibration_missing", "message": f"calibration.json: {cal_err}"})
    if bias_err and bias_err != "missing":
        hygiene.append({"level": "warning", "code": "bias_error", "message": f"bias.json: {bias_err}"})
    _check_operating_profile(op_prof, op_err, config, arm_id, hygiene)

    raw_ref = ref_path.read_bytes() if ref_path and ref_path.is_file() else b""
    if raw_ref and bound_map_error is not None:
        bind_err = bound_map_error(calibration, config, raw_ref)
    else:
        bind_err = "reference_top unavailable" if not raw_ref else None
    if bind_err:
        hygiene.append({"level": "warning", "code": "map_binding", "message": f"지도-기준프레임 결속 경고: {bind_err}"})
    if shift and shift.get("ok") and shift.get("max_px", 0) > prm.default("calibrate.max_shift_px"):
        hygiene.append({"level": "error", "code": "camera_shifted",
                        "message": f"기준 프레임 대비 카메라 이동 {shift['max_px']} px (inliers {shift.get('inliers')})"})

    sites_out: dict[str, dict[str, Any]] = {}
    cfg_sites = config.get("sites") or {}
    cal_sites = calibration.get("sites") or {}
    for name in list(cfg_sites.keys()) + [k for k in cal_sites.keys() if k not in cfg_sites]:
        is_extra = name not in cfg_sites
        spec = cfg_sites.get(name) or {}
        rec = None if is_extra else cell_pivot.map_record(with_maps, name)
        if rec is None and name in cal_sites:
            rec = cal_sites[name]
        surface_z = spec.get("surface_z")
        note = spec.get("note") or ""
        if not is_extra:
            if surface_z is None:
                hygiene.append({"level": "error", "code": f"missing_surface_z:{name}", "message": f"{name}: surface_z 미측정"})
            elif "copied from" in note.lower() or "until measured" in note.lower():
                hygiene.append({"level": "warning", "code": f"copied_surface_z:{name}",
                                "message": f"{name}: surface_z={surface_z} (복사값, 실측 필요)"})
        else:
            hygiene.append({"level": "warning", "code": f"extra_cal_site:{name}",
                            "message": f"calibration.json에 config.sites에 없는 잔여 키 '{name}' 존재"})

        map_detail = _build_map_detail(rec, planned_pts, config, surface_z)
        if map_detail and map_detail.get("loo_error_mm"):
            lmax = map_detail["loo_error_mm"].get("max", 0)
            if lmax > prm.default("calibrate.max_loo_mm"):
                hygiene.append({"level": "warning", "code": f"high_loo:{name}",
                                "message": f"{name}: LOO max {lmax} mm > {prm.default('calibrate.max_loo_mm')} mm"})

        dv_site = ((depth_verify or {}).get("sites") or {}).get(name) or {}
        touch_dir = Path(entry["surface_receipts_dir"]) if entry.get("surface_receipts_dir") else work_dir
        touch_data, _ = _read_json(touch_dir / f"surface-{name}.json" if touch_dir and not is_extra else None)
        cv_fields = _attach_site_cross_verify(name, is_extra, surface_z, dv_site, touch_data, hygiene)

        sites_out[name] = {
            "name": name, "extra": is_extra, "in_map_sites": name in map_sites,
            "map_from": spec.get("map_from"), "tier_of": spec.get("tier_of"),
            "map_source_key": spec.get("map_from") or name,
            "surface_z": surface_z, "z": spec.get("z"), "yaw_deg": spec.get("yaw_deg"), "note": note,
            "surface_px": spec.get("surface_px"), "auto_roi": spec.get("auto_roi"),
            "detect_roi": spec.get("detect_roi"), "markings_px": spec.get("markings_px"),
            "start": _project_point(rec, camera_top, spec.get("start"), surface_z),
            "place": _project_point(rec, camera_top, spec.get("place"), surface_z),
            "map": map_detail,
            **cv_fields,
        }

    bias_reach_mm = float(prm.default("calibrate.bias_near_mm"))
    regions_out = []
    for r in bias.get("regions") or []:
        site = r.get("site")
        site_obj = sites_out.get(site) or {}
        rec = None if site_obj.get("extra") else cell_pivot.map_record(with_maps, site)
        actual_sha = cell_attempts.digest(rec) if rec else None
        stale_map = (actual_sha is None) or (r.get("map_sha") != actual_sha)
        if stale_map:
            hygiene.append({"level": "warning", "code": f"stale_bias:{site}", "message": f"bias region ({site}): map_sha 불일치"})
        pt = r.get("point_m")
        bmm = r.get("bias_mm") or [0.0, 0.0]
        target_z = site_obj.get("surface_z")
        fk_proj = _project_point(rec, camera_top, pt, target_z)
        map_pt = [pt[0] + bmm[0] / 1000.0, pt[1] + bmm[1] / 1000.0] if pt else None
        map_proj = _project_point(rec, camera_top, map_pt, target_z)
        regions_out.append({
            **r, "stale_map": stale_map, "actual_map_sha": actual_sha, "reach_mm": bias_reach_mm,
            "fk_pixel_z_view": fk_proj["pixel_z_view"], "fk_pixel_surface_z": fk_proj["pixel_surface_z"],
            "map_point_m": map_pt, "map_pixel_z_view": map_proj["pixel_z_view"],
            "map_pixel_surface_z": map_proj["pixel_surface_z"],
        })
    if not regions_out:
        hygiene.append({"level": "warning", "code": "no_bias", "message": "bias.json regions 비어 있음 (pivot-near 미완료)"})

    limits = (plan or {}).get("limits") or {}
    ref_site = next((s for s in map_sites if s in sites_out and sites_out[s]["map"]), None)
    ref_record = cell_pivot.map_record(with_maps, ref_site) if ref_site else None
    live_info = _parse_live(live, config, plan, ref_record, now_ts=now_ts)
    cross_verify = _build_cross_verify(sites_out, depth_verify, regions_out, live_info, bind_err)

    return {
        "schema": "rosy.calibration-profile-view.v1",
        "id": entry["id"], "label": entry.get("label", arm_id), "arm_id": arm_id,
        "zone_side": config.get("zone_side"), "zone_peer": config.get("zone_peer"),
        "tcp_x_m": config.get("tcp_x_m") if config.get("tcp_x_m") is not None else (plan or {}).get("tcp_x_m"),
        "map_sites": map_sites,
        "paths": {
            "config_path": str(cfg_path), "calibration_path": cal_str, "bias_path": bias_str,
            "operating_profile_path": op_str, "work_dir": str(config.get("work_dir", "")),
            "io": str(config.get("io", "")), "reference_top": ref_str,
            "live_frame_url": entry.get("live_frame_url") or camera_top.get("url"),
        },
        "camera_top": {
            "url": camera_top.get("url"), "height_m": camera_top.get("height_m"),
            "center_px": camera_top.get("center_px"), "frame_size": frame_size,
            "has_reference": bool(ref_path and ref_path.is_file()),
            "has_live": bool((live_img_path and live_img_path.is_file()) or is_allowed_frame_url(entry.get("live_frame_url") or camera_top.get("url"))),
            "shift": shift,
        },
        "limits": {
            "max_reach_m": (config.get("calibrate") or {}).get("max_reach_m") or limits.get("max_reach_m"),
            "park_reach_m": limits.get("park_reach_m"),
            "singularity_radius_m": limits.get("singularity_radius_m"),
            "workspace_min_m": limits.get("workspace_min_m"),
            "workspace_max_m": limits.get("workspace_max_m"),
            "low_zones": limits.get("low_zones") or [],
        },
        "hygiene": hygiene, "sites": sites_out,
        "cross_verify": cross_verify,
        "bias": {"schema": bias.get("schema"), "reach_mm": bias_reach_mm, "regions": regions_out},
        "operating_profile": op_prof,
        "robot_status": {
            "incident": incident or {"arm": arm_id, "local_held": None, "fleet_held": None, "incident_ids": []},
            "live": live_info,
        },
    }


def build_bundle(entries: list[dict[str, Any]], *, now_ts: float | None = None) -> dict[str, Any]:
    """Build the full profiles snapshot payload for calibration_web."""
    return {
        "schema": "rosy.calibration-profiles-bundle.v1",
        "configured": bool(entries),
        "profiles": [build_profile_snapshot(e, now_ts=now_ts) for e in entries],
    }
