#!/usr/bin/env python3
"""Post-calibration empty-arm X/Y target verification & bounded visit compensation (`cell_post_eval.py`).

Single Responsibility:
  - Isolate camera shift, movable-site shift, joint droop, scene motion, and map/bias residual.
  - Measure true X/Y TCP via opposing yaw pairs (or 1-yaw advisory fallback) with finger-identity validation (`source="visit"`).
  - Save bounded `kind="visit"` local bias (preserving `pivot` R/phi) only under `D-911` (`--commissioning --person-at-switch --apply`).
"""
from __future__ import annotations

import argparse, json, math, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts, cell_cal_monitor, cell_params as prm, cell_pivot, cell_pivot_bias as cpb, cell_remap_plan as rp, omx_tcp  # noqa: E402
from cell_pipeline_io import fold  # noqa: E402

SCHEMA = "rosy.omx-post-eval.v1"
PAIR_OFFSETS = ((0.0, 180.0), (-60.0, 120.0), (-40.0, 140.0), (-80.0, 100.0), (-90.0, 90.0), (-20.0, 160.0))
SINGLE_OFFSETS = (0.0, -40.0, 40.0, -80.0, 80.0, 120.0)


def _ang_diff_deg(a: float, b: float) -> float:
    return (float(a) - float(b) + 180.0) % 360.0 - 180.0


def _tcp_kw(config: dict) -> dict:
    tcp_x_m = omx_tcp.config_tcp(config, config.get("plan"))
    return {"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}


def select_visit_yaws(config: dict, site: str, point_m, z_view: float, *,
                      write_library_fn=None, work: Path | None = None) -> tuple[list[float], bool]:
    """Return `(yaws, geometry_dependent)` preferring an IK-valid opposing `(theta, theta+180)` pair."""
    import cell_pipeline as cp

    writer = write_library_fn or cp.write_library
    scoped = rp.scoped(config)
    base = float((config.get("sites") or {}).get(site, {}).get("yaw_deg", 0.0))
    view = {"x": float(point_m[0]), "y": float(point_m[1]),
            "z": round(float(z_view) - float((config.get("plan") or {}).get("approach_m", 0.04)), 4)}
    probe_dir = Path(work) if work is not None else Path(config.get("work_dir", ".")).expanduser()
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_path = probe_dir / "_post_eval_ik_probe.json"

    def ik_ok(yaw: float) -> bool:
        try:
            pose = dict(view, yaw_deg=yaw)
            writer(scoped, pose, pose, probe_path)
            return True
        except SystemExit:
            return False
        finally:
            probe_path.unlink(missing_ok=True)

    for d1, d2 in PAIR_OFFSETS:
        y1, y2 = base + d1, base + d2
        if ik_ok(y1) and ik_ok(y2):
            return [y1, y2], False
    for d in SINGLE_OFFSETS:
        y1 = base + d
        if ik_ok(y1):
            return [y1], True
    return [], True


def _clear_point_for_visit(frame, config: dict, calibration: dict, site: str, point_m) -> tuple[bool, str | None]:
    """Check top-view foreground around `point_m` so jaw opening cannot sweep neighbors."""
    site_cfg = (config.get("sites") or {}).get(site) or {}
    if frame is None or not (site_cfg.get("auto_roi") or site_cfg.get("surface_px")):
        return True, None
    import cv2
    import cell_calibrate_auto as cca
    import cell_objects
    from cell_observe import predicted_pixel

    roi = tuple(site_cfg.get("auto_roi") or (0, 0, frame.shape[1], frame.shape[0]))
    big = (max(0, roi[0] - 60), max(0, roi[1] - 60), min(frame.shape[1], roi[2] + 60), min(frame.shape[0], roi[3] + 60))
    mask = cell_objects.foreground(frame, big, params=config.get("params"),
                                   surface_px=site_cfg.get("surface_px"), surface_lab=site_cfg.get("surface_lab"))
    inside = np.zeros(frame.shape[:2], np.uint8)
    poly = site_cfg.get("surface_px") or [[0, 0], [frame.shape[1] - 1, 0],
                                          [frame.shape[1] - 1, frame.shape[0] - 1], [0, frame.shape[0] - 1]]
    cv2.fillPoly(inside, [np.asarray(poly, np.int32)], 1)
    found = cca.clear_point(point_m, mask, big, inside, lambda q: predicted_pixel(config, calibration, site, q), max_mm=0.0)
    return (True, None) if found is not None else (False, "no_room_or_off_surface")


def _finger_candidates(region: dict | None, config: dict) -> list[dict]:
    base = dict(region or (config.get("pivot") or {}).get("geometry") or {})
    if "phase_deg" not in base or "radius_mm" not in base:
        return []
    params = config.get("params")
    return [base, dict(base, phase_deg=float(base["phase_deg"]) + float(prm.get(params, "look.other_finger_deg")),
                       radius_mm=float(prm.get(params, "look.other_finger_mm")))]


def _expected_finger_pixels(config: dict, record: dict, site: str, tcp_xy, jaw_z: float, yaw_deg: float, region: dict | None) -> list:
    pts = []
    for f in _finger_candidates(region, config):
        a, r_m = math.radians(yaw_deg + float(f["phase_deg"])), float(f["radius_mm"]) / 1000.0
        try:
            pts.append(cell_pivot.mark_pixel(record, config, site, (tcp_xy[0] + r_m * math.cos(a), tcp_xy[1] + r_m * math.sin(a)), jaw_z))
        except Exception:
            pass
    return pts


def _finger_identity_ok(m1, m2, fk1_yaw: float, fk2_yaw: float, region: dict | None, config: dict) -> tuple[bool, float, float, str | None]:
    params = config.get("params")
    pair_err = abs(abs(_ang_diff_deg(fk2_yaw, fk1_yaw)) - 180.0)
    if pair_err > float(prm.get(params, "post.yaw_pair_tol_deg")):
        return False, pair_err, 0.0, "yaw_pair_gap"
    half_mm = 1000.0 * math.dist(m1, m2) / 2.0
    lo, hi = float(prm.get(params, "pivot.radius_lo_mm")), float(prm.get(params, "pivot.radius_hi_mm"))
    if not (lo <= half_mm <= hi):
        return False, pair_err, half_mm, "finger_identity"
    radii = [float(src["radius_mm"]) for src in (region or {}, (config.get("pivot") or {}).get("geometry") or {}) if src.get("radius_mm") is not None]
    if radii:
        radii.append(float(prm.get(params, "look.other_finger_mm")))
        if min(abs(half_mm - r) for r in radii) > float(prm.get(params, "post.finger_tol_mm")):
            return False, pair_err, half_mm, "finger_identity"
    return True, pair_err, half_mm, None


def _safe_lookup(bias_data: dict | None, bias_err: str | None, site: str, point_m, params, *, pivot_only: bool = False):
    if bias_data is None:
        return None, bias_err
    try:
        return cell_pivot.bias_at(bias_data, site, point_m, params=params, pivot_only=pivot_only), bias_err
    except ValueError as exc:
        return None, bias_err or str(exc)


def measure_point(cell, config: dict, calibration: dict, bias_data: dict | None, site: str, point_m, *,
                  work: Path, sleep=time.sleep, write_library_fn=None, bias_err: str | None = None,
                  scene_moved_fn=None) -> dict[str, Any]:
    """Visit one XY point cleanly, isolate droop/scene/finger checks, and log a `visit` monitor row."""
    import cell_look, cell_pipeline as cp, cell_scene_guard, joint_jitter

    params = config.get("params")
    rec = cell_pivot.map_record(calibration, site)
    if rec is None:
        return {"site": site, "point_m": list(point_m), "status": "skipped", "reason": "missing_map"}
    map_sha = cell_attempts.digest(rec)
    z_view = cell_pivot.pivot_z_view(config, site)
    yaws, geom_dep = select_visit_yaws(config, site, point_m, z_view, write_library_fn=write_library_fn, work=work)
    if not yaws:
        return {"site": site, "point_m": list(point_m), "map_sha": map_sha, "status": "skipped", "reason": "no_ik"}
    used_reg, b_err = _safe_lookup(bias_data, bias_err, site, point_m, params)
    pivot_reg, _ = _safe_lookup(bias_data, bias_err, site, point_m, params, pivot_only=True)
    if geom_dep and not (pivot_reg or (config.get("pivot") or {}).get("geometry")):
        return {"site": site, "point_m": list(point_m), "map_sha": map_sha, "status": "skipped",
                "geometry_dependent": True, "reason": "needs_pivot_geometry"}

    before = cell.frame("top")
    clear_ok, clear_why = _clear_point_for_visit(before, config, calibration, site, point_m)
    if not clear_ok:
        return {"site": site, "point_m": list(point_m), "map_sha": map_sha, "status": "skipped", "reason": clear_why}

    writer, scoped = write_library_fn or cp.write_library, rp.scoped(config)
    approach_m, tcp_kw = float((config.get("plan") or {}).get("approach_m", 0.04)), _tcp_kw(config)
    droops, marks_arm, fks = [], [], []
    try:
        for idx, yaw in enumerate(yaws):
            pose = {"x": float(point_m[0]), "y": float(point_m[1]), "z": round(float(z_view) - approach_m, 4), "yaw_deg": yaw}
            lib = writer(scoped, pose, pose, work / f"visit-{site}-{idx}.json")
            for cmd in (f"load {lib}", "goto above_pick"):
                st = cell.act(cmd)
                if not st.get("ok"):
                    return {"site": site, "point_m": list(point_m), "map_sha": map_sha, "status": "stopped", "reason": f"{cmd}:{st.get('error')}"}
            st = joint_jitter.settled_state(cell, params) or {}
            state, commanded = st.get("state"), st.get("target")
            if state is None:
                return {"site": site, "point_m": list(point_m), "map_sha": map_sha, "status": "failed", "reason": "no_state"}
            fx, fy, fz, fyaw = cell_pivot.joints_tcp(state, **tcp_kw)
            if commanded is not None:
                cx, cy, _, _ = cell_pivot.joints_tcp(commanded, **tcp_kw)
                droops.append([round(1000.0 * (fx - cx), 2), round(1000.0 * (fy - cy), 2)])
            exp_px = _expected_finger_pixels(config, rec, site, (fx, fy), fz, fyaw, pivot_reg)
            near = (exp_px, float(prm.get(params, "pivot.follow_px")) + 40.0) if exp_px else None
            px = cell_pivot.mark_jaws(cell, config, sleep, near=near)
            if px is None:
                return {"site": site, "point_m": list(point_m), "map_sha": map_sha, "status": "failed", "reason": "mark_not_seen"}
            marks_arm.append(cell_pivot.mark_to_arm(rec, config, site, px, fz))
            fks.append((fx, fy, fz, fyaw))
    finally:
        fold(cell, sleep)

    scene_ok = not bool((scene_moved_fn or cell_scene_guard.scene_moved)(before, cell.frame("top")))
    mark_sig = float(prm.get(params, "verify.mark_sigma_mm"))
    droop_mm = [round(sum(d[0] for d in droops) / len(droops), 2), round(sum(d[1] for d in droops) / len(droops), 2)] if droops else None
    finger_ok, pair_err, half_mm, f_why = True, 0.0, None, None
    if not geom_dep and len(marks_arm) == 2:
        finger_ok, pair_err, half_mm, f_why = _finger_identity_ok(marks_arm[0], marks_arm[1], fks[0][3], fks[1][3], pivot_reg, config)
        tcp_map = ((marks_arm[0][0] + marks_arm[1][0]) / 2.0, (marks_arm[0][1] + marks_arm[1][1]) / 2.0)
        fk_xy = ((fks[0][0] + fks[1][0]) / 2.0, (fks[0][1] + fks[1][1]) / 2.0)
        sigma_mm = round(math.hypot(mark_sig / math.sqrt(2.0), (half_mm or 25.0) * abs(math.sin(math.radians(pair_err / 2.0)))), 2)
    else:
        cand = _finger_candidates(pivot_reg, config)
        exp_pts = [(fks[0][0] + (float(f["radius_mm"]) / 1000.0) * math.cos(math.radians(fks[0][3] + float(f["phase_deg"]))),
                    fks[0][1] + (float(f["radius_mm"]) / 1000.0) * math.sin(math.radians(fks[0][3] + float(f["phase_deg"])))) for f in cand]
        k = min(range(len(cand)), key=lambda i: math.dist(marks_arm[0], exp_pts[i]))
        tcp_map, fk_xy = cell_look.tcp_from_mark(marks_arm[0], fks[0][3], cand[k]), (fks[0][0], fks[0][1])
        sigma_mm = round(max(mark_sig, float((pivot_reg or {}).get("bias_sigma_mm") or mark_sig)), 2)

    raw_bias = [round(1000.0 * (tcp_map[0] - fk_xy[0]), 2), round(1000.0 * (tcp_map[1] - fk_xy[1]), 2)]
    used_bias = [float(used_reg["bias_mm"][0]), float(used_reg["bias_mm"][1])] if used_reg else [0.0, 0.0]
    resid = [round(raw_bias[0] - used_bias[0], 2), round(raw_bias[1] - used_bias[1], 2)]
    resid_mag, accepted, reason = round(math.hypot(*resid), 2), (scene_ok and finger_ok), ("scene_moved" if not scene_ok else f_why)
    tol_mm = float(prm.get(params, "post.tol_mm"))
    status = "rejected" if not accepted else ("advisory" if geom_dep else ("pass" if resid_mag <= max(tol_mm, 2.0 * sigma_mm) else "drift"))
    pt_r = [round(float(point_m[0]), 4), round(float(point_m[1]), 4)]
    cell_cal_monitor.record_observation(
        config, site=site, map_sha=map_sha, source="visit", raw_mm=raw_bias, residual_mm=resid,
        sigma_mm=sigma_mm, accepted=accepted, reason=reason,
        extra={"place_xy": pt_r, "yaw_pair": not geom_dep, "finger_ok": finger_ok, "scene_ok": scene_ok,
               "geometry_dependent": geom_dep, **({"droop_mm": droop_mm} if droop_mm is not None else {})},
    )
    return {"site": site, "point_m": pt_r, "map_sha": map_sha, "status": status, "reason": reason, "accepted": accepted,
            "geometry_dependent": geom_dep, "finger_ok": finger_ok, "scene_ok": scene_ok,
            "half_radius_mm": round(half_mm, 1) if half_mm is not None else None, "raw_bias_mm": raw_bias,
            "used_bias_mm": used_bias, "residual_mm": resid, "residual_mag_mm": resid_mag, "sigma_mm": sigma_mm,
            "droop_mm": droop_mm, "bias_error": b_err}


def _track_ok(cell, config: dict, calibration: dict, site: str) -> tuple[bool, dict | None]:
    if not ((config.get("sites") or {}).get(site) or {}).get("track"):
        return True, None
    import cell_site_track
    from cell_observe import predicted_pixel

    _, report = cell_site_track.follow(config, site, cell.frame("top"),
                                       lambda q: predicted_pixel(config, calibration, site, q), config.get("work_dir"))
    lim = float(prm.get(config.get("params"), "calibrate.max_shift_px"))
    return bool(report.get("tracked") and math.hypot(*report.get("shift_px", (0.0, 0.0))) <= lim), report


def _visit_common_shift(rows: list[dict[str, Any]], config: dict) -> tuple[bool, dict[str, Any]]:
    """Detect common-mode translation or 2D rigid/scale drift across distinct real sites in one post-eval run."""
    cfg_sites, vecs, pts_r, res_r = (config.get("sites") or {}), {}, [], []
    for r in rows:
        spec = cfg_sites.get(r.get("site") or "") or {}
        if r.get("accepted") and not spec.get("tier_of") and not spec.get("map_from") and isinstance(r.get("residual_mm"), list):
            v, pt = r["residual_mm"], r.get("point_m")
            if isinstance(pt, list) and len(pt) >= 2 and len(v) >= 2:
                pts_r.append(pt[:2])
                res_r.append(v[:2])
            if r.get("status") == "drift" and len(v) >= 2 and math.hypot(*v) > 0:
                vecs[f"{r.get('map_sha')}:{r['site']}"] = np.asarray(v, float)
    rigid = cpb.decompose_rigid_drift(pts_r, res_r, trans_tol_mm=float(prm.get((config or {}).get("params"), "post.tol_mm")))
    vals = list(vecs.values())
    pair_common = len(vals) >= 2 and all(
        float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))) > math.cos(math.radians(45.0))
        and max(np.linalg.norm(a), np.linalg.norm(b)) <= 2.0 * min(np.linalg.norm(a), np.linalg.norm(b))
        for i, a in enumerate(vals) for b in vals[i + 1:]
    )
    return bool(pair_common or rigid.get("global_drift")), rigid


def run_post_eval(cell, config: dict, calibration: dict, *, targets=None, apply: bool = False,
                  commissioning: bool = False, person_at_switch: bool = False, work: Path | None = None,
                  sleep=time.sleep, write_library_fn=None) -> dict[str, Any]:
    """Run D-911 pre-gated XY post-evaluation across sites and optionally apply bounded `visit` bias."""
    if not (commissioning and person_at_switch):
        return {"schema": SCHEMA, "verdict": "held", "held": "supervised commissioning required (--commissioning --person-at-switch)"}
    import cell_calibrate

    params = config.get("params")
    work_dir = Path(work or config.get("work_dir", ".")).expanduser() / "post_eval"
    work_dir.mkdir(parents=True, exist_ok=True)
    resolved = list(targets) if targets else [
        (n, (float((s.get("place") or s.get("start"))[0]), float((s.get("place") or s.get("start"))[1])))
        for n, s in (config.get("sites") or {}).items()
        if not s.get("tier_of") and isinstance(s.get("place") or s.get("start"), (list, tuple)) and len(s.get("place") or s.get("start")) >= 2
    ]
    chk = cell_calibrate.check(config, calibration, resolved, cell.frame("top"), params)
    if chk.get("camera_moved"):
        return {"schema": SCHEMA, "verdict": "escalate", "todo": ["remap"], "reason": "camera_moved", "check": chk}

    cal_path = Path(config["calibration_path"]).expanduser() if config.get("calibration_path") else None
    bias_data, bias_err = None, chk.get("bias_error")
    if cal_path and cpb.bias_path(cal_path).exists():
        try:
            bias_data = cpb.load_bias(cpb.bias_path(cal_path), params)
        except ValueError as exc:
            bias_err = str(exc)

    rows = []
    for site, pt in resolved:
        ok_track, track_rep = _track_ok(cell, config, calibration, site)
        if not ok_track:
            rows.append({"site": site, "point_m": list(pt), "status": "site_moved", "reason": "site_moved", "track": track_rep})
        else:
            rows.append(measure_point(cell, config, calibration, bias_data, site, pt, work=work_dir, sleep=sleep,
                                      write_library_fn=write_library_fn, bias_err=bias_err))

    drift = cell_cal_monitor.summarize(config, calibration)
    v_common, rigid = _visit_common_shift(rows, config)
    common_shift = drift.get("pattern") == "common" or v_common
    applied, escalated = (["remap"] if rigid.get("global_drift") else []), []
    applied, escalated = [], list(applied)
    learn_lim, tol_mm = float(prm.get(params, "auto.bias_learn_max_mm")), float(prm.get(params, "post.tol_mm"))
    for row in rows:
        if row.get("status") != "drift":
            continue
        mag = float(row.get("residual_mag_mm") or 0.0)
        if common_shift or mag > learn_lim:
            escalated.append("remap" if common_shift else f"pivot-near {row['site']}:{row['point_m'][0]},{row['point_m'][1]}")
        elif apply and cal_path and not row.get("geometry_dependent") and row.get("accepted") and mag > tol_mm:
            if bias_err:
                escalated.append(f"fix_over_limit_bias:{row['site']}")
                continue
            region = {"site": row["site"], "kind": "visit", "point_m": row["point_m"], "bias_mm": row["raw_bias_mm"],
                      "centre_sigma_mm": round(float(row.get("sigma_mm") or 3.0), 2), "n": 1,
                      "map_sha": row["map_sha"], "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "source": "post-eval opposing-yaw visit"}
            try:
                cpb.save_bias(cpb.bias_path(cal_path), region, params)
                applied.append(region)
            except ValueError as exc:
                escalated.append(f"bias_refused:{row['site']}:{exc}")

    lateral = lateral_summary(config, calibration)
    return {"schema": SCHEMA, "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": rows,
            "applied": applied, "escalated": list(dict.fromkeys(escalated)), "drift": drift, "rigid_drift": rigid,
            "lateral_xy": lateral, "verdict": "escalate" if escalated else lateral["verdict"]}


def lateral_summary(config: dict, calibration: dict | None, *, rows: list[dict[str, Any]] | None = None,
                    now_ts: float | None = None) -> dict[str, Any]:
    """Pure monitor-backed summary for `cell_cal_eval`: true only when fresh opposing-yaw visits pass."""
    params = (config or {}).get("params")
    now, max_age, tol_mm = (float(now_ts) if now_ts is not None else time.time()), float(prm.get(params, "post.max_age_s")), float(prm.get(params, "post.tol_mm"))
    if rows is None:
        rows = cell_cal_monitor.load_observations(cell_cal_monitor.monitor_path(config), arm_id=(config or {}).get("arm_id"))
    visits = [r for r in rows if r.get("source") == "visit" and (now - float(r.get("ts") or 0.0)) <= max_age]
    sites_out, cal = {}, calibration or {"sites": {}}
    for name, spec in ((config or {}).get("sites") or {}).items():
        if (spec or {}).get("tier_of"):
            continue
        rec = cell_pivot.map_record(cal, name)
        sha = cell_attempts.digest(rec) if rec else None
        matched = [r for r in visits if sha is not None and r.get("site") == name and r.get("map_sha") == sha]
        if not matched:
            continue
        latest = matched[-1]
        res = latest.get("residual_mm") or [0.0, 0.0]
        mag, lim = round(math.hypot(float(res[0]), float(res[1])), 2), max(tol_mm, 2.0 * float(latest.get("sigma_mm") or 3.0))
        if not latest.get("accepted") or not latest.get("scene_ok", True) or not latest.get("finger_ok", True):
            st = "fail"
        elif latest.get("geometry_dependent") or not latest.get("yaw_pair", True):
            st = "advisory"
        else:
            st = "pass" if mag <= lim else "fail"
        sites_out[name] = {"status": st, "residual_mm": res, "residual_mag_mm": mag, "sigma_mm": latest.get("sigma_mm"),
                           "geometry_dependent": bool(latest.get("geometry_dependent")), "n": len(matched), "map_sha": sha}
    if not sites_out:
        return {"lateral_xy_verified": False, "verdict": "unmeasured", "sites": {}, "visit_count": 0}
    statuses = [v["status"] for v in sites_out.values()]
    verdict = "fail" if "fail" in statuses else ("advisory" if "advisory" in statuses else "pass")
    return {"lateral_xy_verified": verdict == "pass", "verdict": verdict, "sites": sites_out, "visit_count": sum(v["n"] for v in sites_out.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for opt, kw in (("--config", {"required": True, "type": Path}), ("--targets", {"nargs": "*", "default": []}),
                    ("--apply", {"action": "store_true"}), ("--commissioning", {"action": "store_true"}),
                    ("--person-at-switch", {"action": "store_true"})):
        ap.add_argument(opt, **kw)
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not (args.commissioning and args.person_at_switch):
        print(json.dumps({"held": "supervised commissioning required (--commissioning --person-at-switch)"}))
        return 2
    import cell_pipeline as cp

    config["params"] = prm.load(config.get("params_path"))["values"]
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text(encoding="utf-8"))
    cal_path = Path(config["calibration_path"]).expanduser()
    cal_data = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {"sites": {}}
    targets = [(t.split(":")[0], tuple(float(v) for v in t.split(":")[1].split(","))) for t in args.targets] if args.targets else None
    report = run_post_eval(cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"]), config, cal_data,
                           targets=targets, apply=args.apply, commissioning=args.commissioning, person_at_switch=args.person_at_switch)
    print(json.dumps(report, indent=1, default=str))
    return 2 if report.get("verdict") in ("held", "escalate", "fail") else 0


if __name__ == "__main__":
    raise SystemExit(main())
