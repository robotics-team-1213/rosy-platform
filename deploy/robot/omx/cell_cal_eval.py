"""Unified post-calibration cross-verification & evaluation (`cell_cal_eval.py`, `rosy.omx-cal-eval.v1`).

Single Responsibility:
  - Compare D435 depth heights, surface touch receipts, map LOO / predictive sigma, pivot bias,
    live FK, and drift monitor observations against shared `verify.*` parameters (`cell_params.py`).
  - Shared single evaluator for `cell_depth.py verify` and `cell_calibration_view.py` (D-951 read-only).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_cal_monitor  # noqa: E402
import cell_depth  # noqa: E402
import cell_map_fit  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pivot  # noqa: E402
import omx_tcp  # noqa: E402

SCHEMA = "rosy.omx-cal-eval.v1"
LEGACY_DEPTH_SCHEMA = "rosy.omx-cell-depth-verify.v1"


def load_json_opt(path: Path | None) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if (path and path.is_file()) else None
    except (OSError, ValueError):
        return None


def _num2(p) -> bool:
    return isinstance(p, (list, tuple)) and len(p) >= 2 and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))


def _poly_center_px(px):
    if _num2(px):
        return [float(px[0]), float(px[1])]
    pts = [p for p in (px or ()) if _num2(p)] if isinstance(px, (list, tuple)) else []
    return [round(sum(float(p[0]) for p in pts) / len(pts), 2), round(sum(float(p[1]) for p in pts) / len(pts), 2)] if pts else None


def project_site_px(rec: dict | None, cam_top: dict, arm_xy, fit_z: float | None, target_z: float | None):
    if not arm_xy or len(arm_xy) < 2 or not rec or not rec.get("homography"):
        return None
    try:
        u, v = cal.to_pixel(rec["homography"], arm_xy[:2])
        if target_z is not None and fit_z is not None and cam_top.get("center_px") and cam_top.get("height_m"):
            u, v = cal.parallax((u, v), float(fit_z), float(target_z), cam_top)
        return [round(float(u), 2), round(float(v), 2)]
    except Exception:
        return None


def _finite_height(heights, to_depth, px) -> float | None:
    if isinstance(px, (list, tuple)) and len(px) >= 3 and isinstance(px[0], (list, tuple)):
        import cv2
        pts = [np.round(to_depth @ [float(p[0]), float(p[1]), 1.0])[:2] for p in px if _num2(p)]
        if len(pts) >= 3:
            mask = np.zeros(heights.shape, dtype=np.uint8)
            cv2.fillPoly(mask, [np.asarray(pts, dtype=np.int32)], 1)
            if mask.any():
                vals = heights[(mask == 1) & np.isfinite(heights)]
                return round(float(np.median(vals)), 2) if vals.size else None
        px = _poly_center_px(px)
    val = cell_depth.height_at(heights, to_depth, px) if _num2(px) else float("nan")
    return round(float(val), 2) if np.isfinite(val) else None


def fetch_colour_frame(url: str):
    import cv2, urllib.error, urllib.parse, urllib.request

    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        return None
    try:
        with urllib.request.urlopen(url, timeout=2.0) as res:
            arr = np.frombuffer(res.read(5 * 1024 * 1024), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def parse_live(live: dict | None, config: dict, plan: dict | None, ref_record: dict | None,
               now_ts: float | None = None, *, joints_tcp_fn=None) -> dict:
    if not live:
        return {"present": False, "stale": True, "age_s": None}
    fresh_s = float(prm.get(config.get("params"), "verify.live_fresh_s"))
    t = live.get("t")
    now = now_ts if now_ts is not None else time.time()
    age_s = round(now - float(t), 2) if isinstance(t, (int, float)) else None
    stale = True if age_s is None else age_s > fresh_s
    state = live.get("state")
    tcp = tcp_pixel = None
    tcp_x_m = omx_tcp.config_tcp(config, plan)
    jtcp = joints_tcp_fn or cell_pivot.joints_tcp
    if isinstance(state, list) and len(state) >= 5:
        try:
            x, y, z, yaw = jtcp(state, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))
            tcp = {"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(z), 4), "yaw_deg": round(float(yaw), 1)}
            camera = (config.get("cameras") or {}).get("top") or {}
            if ref_record and ref_record.get("homography"):
                u, v = cal.to_pixel(ref_record["homography"], (x, y))
                if ref_record.get("z_view") is not None and camera.get("center_px") and camera.get("height_m"):
                    u, v = cal.parallax((u, v), float(ref_record["z_view"]), float(z), camera)
                tcp_pixel = [round(float(u), 2), round(float(v), 2)]
        except (Exception, SystemExit):
            tcp = None
    return {
        "present": True, "stale": stale, "age_s": age_s, "t": t, "chunk": live.get("chunk"),
        "lag": live.get("lag"), "fault": live.get("fault"), "state": state, "target": live.get("target"),
        "tcp": tcp, "tcp_pixel": tcp_pixel, "health": live.get("health") or {},
    }


def check_operating_profile(op_prof: dict | None, op_err: str | None, config: dict, arm_id: str,
                            hygiene: list[dict[str, str]]) -> None:
    if op_prof is None:
        hygiene.append({"level": "warning", "code": "operating_profile_missing", "message": f"operating_profile_path 없음 ({op_err})"})
        return
    if op_prof.get("device_id") != arm_id:
        hygiene.append({"level": "error", "code": "profile_device_mismatch",
                        "message": f"operating_profile device_id={op_prof.get('device_id')} != arm_id={arm_id}"})
    if op_prof.get("work_dir") != config.get("work_dir"):
        hygiene.append({"level": "warning", "code": "profile_workdir_mismatch",
                        "message": f"operating_profile work_dir({op_prof.get('work_dir')}) != config.work_dir({config.get('work_dir')})"})
    env_p = op_prof.get("operating_envelope_path")
    if env_p and not Path(env_p).exists():
        hygiene.append({"level": "warning", "code": "envelope_missing_on_host", "message": f"operating_envelope_path 미확인/누락: {Path(env_p).name}"})


def attach_site_cross_verify(name: str, is_extra: bool, surface_z, dv_site: dict, touch: dict | None,
                             hygiene: list[dict[str, str]], *, params=None, rec: dict | None = None,
                             config: dict | None = None) -> dict[str, Any]:
    d_lim = float(prm.get(params, "verify.depth_diff_mm"))
    s_lim = float(prm.get(params, "verify.step_mm"))
    t_lim = float(prm.get(params, "verify.touch_diff_mm"))
    depth_z = dv_site.get("depth_surface_z_m")
    depth_diff = round((float(depth_z) - float(surface_z)) * 1000.0, 1) if (depth_z is not None and surface_z is not None) else dv_site.get("depth_diff_mm")
    step_mm = dv_site.get("place_vs_start_step_mm")
    touch_z = touch.get("surface_z") if (touch and touch.get("result") in (None, "touched") and touch.get("surface_z") is not None) else dv_site.get("touch_surface_z_m")
    touch_diff = round((float(touch_z) - float(surface_z)) * 1000.0, 1) if (touch_z is not None and surface_z is not None) else dv_site.get("touch_diff_mm")
    flags = list(dv_site.get("flags") or [])
    if depth_diff is not None and abs(depth_diff) > d_lim and "depth_diff_gt_6mm" not in flags:
        flags.append("depth_diff_gt_6mm")
    if step_mm is not None and abs(step_mm) > s_lim and "place_vs_start_step_gt_8mm" not in flags:
        flags.append("place_vs_start_step_gt_8mm")
    if touch_diff is not None and abs(touch_diff) > t_lim and "touch_diff_gt_5mm" not in flags:
        flags.append("touch_diff_gt_5mm")
    sigma_summary = None
    if not is_extra and rec and config:
        spec = (config.get("sites") or {}).get(name) or {}
        cam_top = (config.get("cameras") or {}).get("top") or {}
        sigma_summary = cell_map_fit.site_sigma_summary(rec, [p for p in (spec.get("start"), spec.get("place")) if p], cam_top, surface_z)
        sig_lim = float(prm.get(params, "verify.map_sigma_max_mm"))
        if sigma_summary and sigma_summary["max_mm"] > sig_lim:
            hygiene.append({"level": "warning", "code": f"map_sigma:{name}",
                            "message": f"{name}: 외삽 예측 오차 σ={sigma_summary['max_mm']} mm > {sig_lim} mm (D-933 pose 또는 포인트 확장 검토)"})
    if not is_extra:
        if "depth_diff_gt_6mm" in flags:
            hygiene.append({"level": "warning", "code": f"depth_diff:{name}", "message": f"{name}: D435 depth({depth_z}) vs surface_z({surface_z}) = {depth_diff:+.1f} mm"})
        if "place_vs_start_step_gt_8mm" in flags:
            hygiene.append({"level": "warning", "code": f"place_step:{name}", "message": f"{name}: place vs start 높이차 {step_mm:+.1f} mm (적재물/단차 의심)"})
        if "touch_diff_gt_5mm" in flags:
            hygiene.append({"level": "error", "code": f"touch_diff:{name}", "message": f"{name}: touch({touch_z}) vs surface_z({surface_z}) = {touch_diff:+.1f} mm"})
    crit = any(f in ("depth_diff_gt_6mm", "place_vs_start_step_gt_8mm", "touch_diff_gt_5mm") for f in flags)
    status = "fail" if crit else ("pass" if (depth_z is not None or touch_z is not None) else "unmeasured")
    return {
        "depth_surface_z": depth_z, "depth_diff_mm": depth_diff, "place_vs_start_step_mm": step_mm,
        "touch_surface_z": touch_z, "touch_measured": (touch or {}).get("measured") or dv_site.get("touch_measured"),
        "touch_diff_mm": touch_diff, "map_sigma_mm": sigma_summary, "cross_verify_flags": flags, "cross_verify_status": status,
    }


def build_cross_verify(sites_out: dict[str, dict[str, Any]], depth_verify: dict | None, regions_out: list[dict],
                       live_info: dict, bind_err: str | None, *, params=None, drift: dict | None = None) -> dict[str, Any]:
    t_lim = float(prm.get(params, "verify.touch_diff_mm"))
    loo_limit = float(prm.get(params, "calibrate.max_loo_mm"))
    bias_sig_lim = float(prm.get(params, "verify.bias_sigma_max_mm"))
    any_depth = bool(depth_verify and any(s.get("depth_surface_z") is not None for s in sites_out.values()))
    depth_bad = any("depth_diff_gt_6mm" in s.get("cross_verify_flags", []) or "place_vs_start_step_gt_8mm" in s.get("cross_verify_flags", []) for s in sites_out.values())
    depth_v = "fail" if depth_bad else ("pass" if any_depth else ("warn" if depth_verify else "unmeasured"))

    touch_diffs = [abs(s["touch_diff_mm"]) for s in sites_out.values() if s.get("touch_diff_mm") is not None]
    touch_count = sum(1 for s in sites_out.values() if s.get("touch_surface_z") is not None)
    touch_bad = any(d > t_lim for d in touch_diffs)
    touch_v = "fail" if touch_bad else ("pass" if touch_count else "unmeasured")

    loos = [s["map"]["loo_error_mm"]["max"] for s in sites_out.values()
            if not s.get("extra") and (s.get("map") or {}).get("loo_error_mm") and s["map"]["loo_error_mm"].get("max") is not None]
    max_loo = round(max(loos), 2) if loos else None
    map_v = "fail" if (max_loo is not None and max_loo > loo_limit) else ("warn" if (bind_err or max_loo is None) else "pass")

    fresh_bias = sum(1 for r in regions_out if not r.get("stale_map"))
    over_bias = sum(1 for r in regions_out if r.get("over_limit"))
    bias_sig_warn = any((r.get("bias_sigma_mm") or 0.0) > bias_sig_lim for r in regions_out)
    bias_v = "fail" if (over_bias or (regions_out and fresh_bias < len(regions_out))) else ("pass" if (regions_out and not bias_sig_warn) else ("warn" if regions_out else "unmeasured"))

    fk_fresh = bool(live_info.get("present") and not live_info.get("stale") and live_info.get("tcp"))
    fk_v = "pass" if fk_fresh else ("warn" if live_info.get("present") else "unmeasured")
    sub = (depth_v, touch_v, map_v)
    drift_alarm = bool((drift or {}).get("alarmed_sites"))
    overall = "fail" if ("fail" in sub or bias_v == "fail") else ("warn" if ("warn" in (*sub, bias_v) or drift_alarm) else ("pass" if (any_depth or touch_count) else "unmeasured"))
    eval_v = "hold" if overall == "fail" else ("unknown" if overall == "unmeasured" else ("advisory" if (overall == "warn" or drift_alarm or bias_sig_warn or bias_v == "unmeasured") else "pass"))
    cam_top = dict((depth_verify or {}).get("camera_top") or {})
    return {
        "schema": SCHEMA, "present": bool(depth_verify or touch_count or (depth_verify or {}).get("sites")),
        "depth_verify_present": bool(depth_verify), "measured": (depth_verify or {}).get("measured"),
        "verdict": overall, "eval_verdict": eval_v, "lateral_xy_verified": False,
        "depth": {"verdict": depth_v, **cam_top},
        "touch": {"verdict": touch_v, "sites_measured": touch_count, "max_diff_mm": round(max(touch_diffs), 1) if touch_diffs else None},
        "map": {"verdict": map_v, "max_loo_mm": max_loo, "map_bound": not bind_err},
        "bias": {"verdict": bias_v, "fresh_regions": fresh_bias, "over_limit_regions": over_bias, "total_regions": len(regions_out), "sigma_advisory": bias_sig_warn},
        "fk": {"verdict": fk_v, "present": bool(live_info.get("present")), "fresh": fk_fresh, "tcp_z_m": (live_info.get("tcp") or {}).get("z")},
        **({"drift": drift} if drift else {}),
    }


def verify_profile_depth(config: dict, calibration: dict | None, bias: dict | None = None, *,
                         depth=None, colour=None, live: dict | None = None,
                         touch_receipts: dict[str, dict] | None = None, now_ts: float | None = None) -> dict:
    """Read-only post-calibration cross-verification across D435 depth, touch receipts, map LOO/sigma, bias, FK, and drift."""
    params = (config or {}).get("params")
    d_lim = float(prm.get(params, "verify.depth_diff_mm"))
    s_lim = float(prm.get(params, "verify.step_mm"))
    t_lim = float(prm.get(params, "verify.touch_diff_mm"))
    fresh_s = float(prm.get(params, "verify.live_fresh_s"))
    max_loo_limit = float(prm.get(params, "calibrate.max_loo_mm"))

    now = float(now_ts) if now_ts is not None else time.time()
    work_dir = Path(config["work_dir"]).expanduser() if config.get("work_dir") else None
    try:
        with_maps = cell_pivot.with_site_maps(config, calibration) if (calibration and calibration.get("sites")) else (calibration or {"sites": {}})
    except SystemExit:
        with_maps = calibration or {"sites": {}}

    cam_top = (config.get("cameras") or {}).get("top") or {}
    cfg_height_m = cam_top.get("height_m")
    flags: list[str] = []
    cam_report: dict = dict.fromkeys(("cam_to_table_mm", "height_diff_mm", "plate_mm", "cam_to_plate_mm",
                                      "align_scale", "align_shift", "align_edge_px"))
    cam_report["config_height_m"] = cfg_height_m
    cam_report["lateral_xy_verified"] = False

    heights = to_depth = plate_mm = None
    if depth is not None and colour is not None:
        plane = cell_depth.table_plane(depth)
        cam_mm = round(abs(float(plane[1])), 2)
        heights = cell_depth.height_map(depth, plane)
        to_depth, edge_px = cell_depth.align_edges(colour, heights)
        cam_report.update({
            "cam_to_table_mm": cam_mm, "align_scale": round(float(to_depth[0, 0]), 3),
            "align_shift": [round(float(to_depth[0, 2]), 1), round(float(to_depth[1, 2]), 1)],
            "align_edge_px": round(float(edge_px), 2),
            "height_diff_mm": round(cam_mm - float(cfg_height_m) * 1000.0, 1) if cfg_height_m is not None else None,
        })
        base_px = cam_top.get("plate_px")
        if base_px is None:
            for sname in list((config.get("calibrate") or {}).get("map_sites") or list(config.get("sites") or [])) + list((with_maps.get("sites") or {}).keys()):
                rec = cell_pivot.map_record(with_maps, sname)
                if rec and rec.get("homography"):
                    fit_z = rec.get("z_view", ((config.get("sites") or {}).get(sname) or {}).get("z"))
                    base_px = project_site_px(rec, cam_top, (0.0, 0.0), fit_z, 0.0)
                    if base_px is not None:
                        break
        plate_mm = cell_depth.plate_top(heights, to_depth, base_px) if base_px is not None else None
        if plate_mm is not None:
            plate_mm = round(float(plate_mm), 2)
            cam_report.update({"plate_mm": plate_mm, "cam_to_plate_mm": round(cam_mm - plate_mm, 2)})
        else:
            flags.append("plate_not_found")
    else:
        flags.append("missing_depth")

    sites_report: dict[str, dict] = {}
    bias_regions = (bias or {}).get("regions") or []
    for name, spec in (config.get("sites") or {}).items():
        rec = cell_pivot.map_record(with_maps, name)
        surface_z = spec.get("surface_z")
        fit_z = (rec or {}).get("z_view", spec.get("z"))
        target_z = surface_z if surface_z is not None else spec.get("z")
        site_flags: list[str] = []
        place_px = project_site_px(rec, cam_top, spec.get("place"), fit_z, target_z) or _poly_center_px(spec.get("surface_px"))
        start_px = project_site_px(rec, cam_top, spec.get("start"), fit_z, target_z)
        place_mm = _finite_height(heights, to_depth, place_px) if heights is not None else None
        start_mm = _finite_height(heights, to_depth, start_px) if heights is not None else None
        surf_px_mm = _finite_height(heights, to_depth, spec.get("surface_px")) if heights is not None else None
        site_mm = next((v for v in (place_mm, surf_px_mm, start_mm) if v is not None), None)
        depth_z = round((site_mm - plate_mm) / 1000.0, 4) if (site_mm is not None and plate_mm is not None) else None
        depth_diff_mm = round((depth_z - float(surface_z)) * 1000.0, 1) if (depth_z is not None and surface_z is not None) else None
        step_mm = round(place_mm - start_mm, 1) if (place_mm is not None and start_mm is not None) else None
        if depth_diff_mm is not None and abs(depth_diff_mm) > d_lim:
            site_flags.append("depth_diff_gt_6mm")
        if step_mm is not None and abs(step_mm) > s_lim:
            site_flags.append("place_vs_start_step_gt_8mm")
        receipt = (touch_receipts or {}).get(name) or (load_json_opt(work_dir / f"surface-{name}.json") if (touch_receipts is None and work_dir) else None)
        touch_z = receipt.get("surface_z") if (receipt and receipt.get("result") in (None, "touched") and receipt.get("surface_z") is not None) else None
        touch_diff_mm = round((float(touch_z) - float(surface_z)) * 1000.0, 1) if (touch_z is not None and surface_z is not None) else None
        if touch_diff_mm is not None and abs(touch_diff_mm) > t_lim:
            site_flags.append("touch_diff_gt_5mm")
        loo_max = ((rec or {}).get("loo_error_mm") or {}).get("max")
        if loo_max is not None and float(loo_max) > max_loo_limit:
            site_flags.append("high_loo")
        rec_sha = cell_attempts.digest(rec) if rec else None
        site_bias = [r for r in bias_regions if r.get("site") == name]
        bias_fresh = all(rec_sha is not None and r.get("map_sha") == rec_sha for r in site_bias) if site_bias else None
        if bias_fresh is False:
            site_flags.append("stale_bias")
        sigma_sum = cell_map_fit.site_sigma_summary(rec, [p for p in (spec.get("start"), spec.get("place")) if p], cam_top, target_z)
        flags.extend(f"{name}:{fl}" for fl in site_flags)
        sites_report[name] = {
            "surface_z": surface_z, "place_mm": place_mm, "start_mm": start_mm, "surface_px_mm": surf_px_mm,
            "depth_surface_z_m": depth_z, "depth_diff_mm": depth_diff_mm, "place_vs_start_step_mm": step_mm,
            "touch_surface_z_m": touch_z, "touch_measured": (receipt or {}).get("measured"), "touch_diff_mm": touch_diff_mm,
            "loo_max_mm": loo_max, "map_sigma_mm": sigma_sum, "bias_fresh": bias_fresh, "flags": site_flags,
        }

    live_data = live if live is not None else (load_json_opt(Path(config["io"]).expanduser() / "live.json") if config.get("io") else None)
    fk_report: dict = {"present": bool(live_data), "fresh": False, "age_s": None, "tcp": None, "within_reach": None}
    if live_data:
        t = live_data.get("t")
        age_s = round(now - float(t), 2) if isinstance(t, (int, float)) else None
        fk_report.update({"age_s": age_s, "fresh": age_s is not None and age_s <= fresh_s})
        state = live_data.get("state")
        if isinstance(state, list) and len(state) >= 5:
            plan = load_json_opt(Path(config["plan_path"]).expanduser()) if config.get("plan_path") else None
            tcp_x_m = omx_tcp.config_tcp(config, plan)
            max_reach = (config.get("calibrate") or {}).get("max_reach_m") or ((plan or {}).get("limits") or {}).get("max_reach_m")
            try:
                x, y, z, yaw = cell_pivot.joints_tcp(state, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))
                fk_report["tcp"] = {"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(z), 4), "yaw_deg": round(float(yaw), 1)}
                fk_report["within_reach"] = (math.hypot(x, y) <= float(max_reach) + 1e-6) if max_reach is not None else None
            except (Exception, SystemExit):
                fk_report["tcp"] = None

    drift = cell_cal_monitor.summarize(config, calibration) if calibration else {"sites": {}, "alarmed_sites": [], "pattern": "none", "suggested_advisory": []}
    crit_tags = ("depth_diff_gt_6mm", "touch_diff_gt_5mm", "place_vs_start_step_gt_8mm", "stale_bias", "high_loo")
    verdict = "fail" if any(any(tag in fl for tag in crit_tags) for fl in flags) else ("warn" if (flags or not sites_report) else "pass")
    eval_verdict = "hold" if verdict == "fail" else ("advisory" if (drift["alarmed_sites"] or (verdict == "warn" and flags != ["missing_depth"])) else ("unknown" if flags == ["missing_depth"] else "pass"))
    return {
        "schema": LEGACY_DEPTH_SCHEMA, "eval_schema": SCHEMA, "arm_id": config.get("arm_id"),
        "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict, "eval_verdict": eval_verdict, "ok": verdict == "pass", "flags": flags,
        "camera_top": cam_report, "sites": sites_report, "live_fk": fk_report, "drift": drift,
    }


def verify_main(argv: list[str], capture_fn=None) -> int:
    import cv2

    ap = argparse.ArgumentParser(description="Verify calibrated sites against D435 depth, touch receipts, and live FK")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--depth", type=Path, help="raw Z16, 640x480 mm")
    ap.add_argument("--colour", type=Path, help="top camera colour frame")
    ap.add_argument("--capture", action="store_true", help="capture fresh Z16 depth (and colour from cameras.top.url)")
    ap.add_argument("--write", action="store_true", help="write work_dir/depth-verify.json atomically")
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    cal_p = Path(config["calibration_path"]).expanduser() if config.get("calibration_path") else None
    cal_data, bias = load_json_opt(cal_p), (load_json_opt(cell_pivot.bias_path(cal_p)) if cal_p else None)
    cam_top = (config.get("cameras") or {}).get("top") or {}
    dev = str(cam_top.get("device") or "").lower()
    url = str(cam_top.get("url") or "")
    has_depth = cam_top.get("has_depth") is not False and (
        bool(cam_top.get("depth_device"))
        or ((not dev or "d435" in dev or "depth" in dev) and not url.lower().endswith("/arm_s_top.jpg"))
    )
    cap = capture_fn or cell_depth.capture_top_depth_z16
    depth = np.fromfile(args.depth, np.uint16).reshape(480, 640) if args.depth else (cap() if (args.capture and has_depth) else None)
    colour = cv2.imread(str(args.colour)) if args.colour else None
    if colour is None and args.capture and url:
        colour = fetch_colour_frame(url)
    report = verify_profile_depth(config, cal_data, bias, depth=depth, colour=colour)
    if args.capture and not args.depth and not has_depth:
        report["camera_top"]["depth_capture_skipped"] = "rgb_only_top_camera"
    if args.write and config.get("work_dir"):
        work = Path(config["work_dir"]).expanduser()
        work.mkdir(parents=True, exist_ok=True)
        tmp, out = work / "depth-verify.tmp", work / "depth-verify.json"
        tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        tmp.replace(out)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(verify_main(sys.argv[1:]))
