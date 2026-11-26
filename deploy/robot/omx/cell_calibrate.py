#!/usr/bin/env python3
"""The cell's calibration as one tool: decide what is stale and redo only that, with the arm, no person.

Single Responsibility:
  - Offline / supervised cell calibration (`check`, `stale`, `remap`, `move_regions`, `consensus`, `main`).
  - Online self-calibration (`self_calibrate`, `auto_pivot_point`, `learn_bias`, `clear_point`) lives in
    `cell_calibrate_auto.py` and is re-exported here unchanged.
"""
from __future__ import annotations

import argparse, itertools, json, math, sys, time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_calibrate_auto import auto_pivot_point, carried, clear_point, learn_bias, log_json, map_agrees, over_target, pivot_near, pivot_near_yaws, pivot_point, self_calibrate  # noqa: E402,F401
from cell_calibrate_bound import coverage_advisories, low_zone_gaps, move_regions, save_bound_map_reference, sync_siblings  # noqa: E402,F401
from cell_calibrate_bound import _load_ref_gray, _map_write_sites, map_sites
import cell_calibrate_args, cell_diagnose, cell_map_followers
import cell_calibration as cal, cell_config_io, cell_params as prm, cell_pivot, cell_remap_plan as rp  # noqa: E402  (cell_config_io: one locked writer for every config rewrite)
from cell_intrinsics_frames import POSE_LOO_SLACK_MM, fitted_map  # noqa: E402,F401
from cell_map_fit import consensus, enough_agree, predicted, repair_record  # noqa: E402,F401
from cell_pipeline_io import fold  # noqa: E402
from cell_remap_plan import MAP_POINTS  # noqa: E402
from cell_depth import capture_top_depth_z16 as depth_capture  # noqa: E402

AT_STOP_S = 1.5  # the most a refused remap move waits for its stop evidence before it folds


def stale(check: dict) -> list:
    """The steps a check result asks for, in dependency order."""
    bootstrap = check.get("initial_commissioning") and check.get("missing_map")
    if check.get("camera_issue") not in (None, "camera_moved") and not bootstrap:
        return ["review-camera-reference"]
    if check.get("camera_moved") or check.get("missing_map"):
        steps = ["remap", "regions"] + [f"pivot-near {t}" for t in check.get("targets", [])]
    else:
        steps = (["rebind-followers"] if check.get("rebind_followers") else []) + (["consensus-repair"] if check.get("consensus_repairable") else [])
        steps += [f"pivot-near {t}" for t in check.get("missing_bias", [])]
        steps += [f"surface {s}" for s in check.get("missing_surface", [])]
    if check.get("unverified_xy"):
        steps.append("post-eval")
    if check.get("missing_depth_verify"):
        steps.append("depth-verify")
    return steps


def check(config: dict, calibration: dict, targets: list, frame, params=None) -> dict:
    """What is stale: camera pose against the reference frame, bias regions near each target, surface heights."""
    import cv2
    import cell_preflight

    out = {"targets": [f"{s}:{x},{y}" for s, (x, y) in targets], "missing_bias": [], "missing_surface": []}
    ref = (config.get("preflight") or {}).get("reference_top")
    ref_path = Path(ref).expanduser() if ref else None
    ref_gray = _load_ref_gray(ref_path) if (ref_path and ref_path.exists()) else None
    if config.get("calibration_path"):
        from cell_auto_evidence import bound_map_error
        try:
            raw_reference = ref_path.read_bytes() if ref_path else b""
        except OSError:
            raw_reference = b""
        out["map_binding_error"] = bound_map_error(calibration, config, raw_reference)
    elif (expected_ref_hash := (config.get("preflight") or {}).get("reference_sha256")):
        out["reference_mismatch"] = not cell_preflight.reference_matches(ref_path, expected_ref_hash)
    if ref_gray is not None:
        shift = cell_preflight.camera_shift_px(
            ref_gray,
            frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
        )
        out["camera_shift"] = shift
    else:
        out["no_reference"] = True
        out["initial_commissioning"] = (calibration.get("sites") == {} and set(calibration) <= {"schema", "sites"}
                                       and calibration.get("schema") in (None, cal.SCHEMA)
                                       and not (config.get("preflight") or {}).get("reference_sha256")
                                       and not (ref_path and (ref_path.exists() or ref_path.is_symlink())))
    if out.get("map_binding_error") == cell_map_followers.GEOMETRY_CHANGED and (added := cell_map_followers.added_followers(
            calibration, config, raw_reference, out.get("camera_shift"), prm.get(params, "calibrate.max_shift_px"))):
        out.update(map_binding_error=None, rebind_followers=added)  # only new map_from followers: bind them, no remap
    out.update(cell_diagnose.camera_reference(out, prm.get(params, "calibrate.max_shift_px")))
    try:
        bias = cell_pivot.load_bias(cell_pivot.bias_path(config["calibration_path"]), params)
        for site, xy in targets:
            if not cell_pivot.bias_at(bias, site, xy, reach_mm=prm.get(params, "calibrate.bias_near_mm"), params=params):
                out["missing_bias"].append(f"{site}:{xy[0]},{xy[1]}")
    except ValueError as exc:
        bias, out["bias_error"] = None, str(exc)
        out["missing_bias"].extend(f"{site}:{xy[0]},{xy[1]}" for site, xy in targets)
    out["missing_map"] = rp.missing_maps(config, calibration, map_sites(config))
    cal_sites = calibration.get("sites") or {}
    for name, site in (config.get("sites") or {}).items():
        if not isinstance(site, dict) or site.get("tier_of"):
            continue
        parent = site.get("map_from")
        if isinstance(parent, str) and name in cal_sites and parent in cal_sites:
            if cal_sites[name].get("homography") != cal_sites[parent].get("homography") and name not in out["missing_map"]:
                out["missing_map"].append(name)
    for s in map_sites(config):
        rec = (calibration.get("sites") or {}).get(s) or {}
        if rec.get("loo_error_mm") and not map_agrees(rec, params) and len(rec.get("points") or []) >= 5:
            pts = [(tuple(p["pixel"]), tuple(p["arm_m"])) for p in rec["points"]]
            kept = consensus(pts, prm.get(params, "calibrate.consensus_px"))
            if enough_agree(len(kept), len(pts)) and repair_record(config, rec, kept)["loo_error_mm"]["max"] <= prm.get(
                params, "calibrate.max_loo_mm"
            ):
                out["consensus_repairable"] = True
                break
    for name, site in config["sites"].items():
        if "surface_z" not in site:
            out["missing_surface"].append(name)
    import cell_cal_monitor
    import cell_post_eval

    drift = cell_cal_monitor.summarize(config, calibration)
    if drift["alarmed_sites"]:
        out["drift"] = drift
        out["advisory_todo"] = drift["suggested_advisory"]
    lat = cell_post_eval.lateral_summary(config, calibration)
    out["lateral_xy"] = lat["verdict"]
    cal_cfg = config.get("calibrate") or {}
    if cal_cfg.get("verify_xy") or lat["verdict"] == "fail":
        out["unverified_xy"] = not lat["lateral_xy_verified"]
    if cal_cfg.get("verify_depth") and not (Path(config.get("work_dir", ".")).expanduser() / "depth-verify.json").exists():
        out["missing_depth_verify"] = True
    gaps = low_zone_gaps(config, calibration)
    if gaps:
        out["low_zone_gaps"] = gaps
    out.update(coverage_advisories(config, calibration, bias, params))
    return out


def remap(cell, config: dict, points: list, work: Path, log=log_json, at_stop=None) -> dict:
    """Hover the empty jaws at each point (z_view), mark them, fit the map; None marks are skipped.

    at_stop(state, status) runs when a move is refused, before the fold hides what the arm met: the carry path's
    stop evidence (cell_hooks.stills). 2026-11-14: arm_b's first remap goto stopped on contact at wrist_flex 59.3
    and nothing but the runner's one line said what it met."""
    import cv2
    import cell_pipeline as cp, cell_scene_guard

    z_view, yaw, marks = config["coarse"]["z_view"], config["sites"][map_sites(config)[0]]["yaw_deg"], []
    tcp_marks, seen_jaws = bool((config.get("calibrate") or {}).get("tcp_marks")), []
    motion = rp.scoped(config)
    visits, stop = [], None
    frames = work / "remap-frames" / time.strftime("%Y%m%d-%H%M%S")
    frames.mkdir(parents=True, exist_ok=True)
    if not fold(cell).get("ok"):
        raise SystemExit("remap: initial park failed")
    before = cell.frame("top")
    cv2.imwrite(str(frames / "before.jpg"), before)
    for i, (x, y) in enumerate(rp.remap_order(config, points)):
        view = {"x": x, "y": y, "z": round(z_view - config["plan"]["approach_m"], 4), "yaw_deg": yaw}
        try:
            lib = cp.write_library(motion, view, view, work / f"remap-{i}.json")
        except SystemExit as exc:
            log({"point": [x, y], "skipped": str(exc)[:100]})
            continue
        failed, status = None, {}
        for command in (f"load {lib}", "goto above_pick"):
            status = cell.act(command)
            if not status.get("ok"):
                failed = command
                break
        if failed:
            try:
                rp.record_stop(status, failed, [x, y], speed=motion["plan"].get("transit_speed", 0.85),
                               log=log, at_stop=at_stop, timeout=AT_STOP_S)
            finally:
                if not fold(cell).get("ok"):
                    raise SystemExit(f"remap stopped at {failed} for {[x, y]} and the park failed")
            stop = f"remap stopped at {failed} for {[x, y]}: {status.get('error') or 'refused'}"
            break
        cv2.imwrite(str(frames / f"{i:02d}.jpg"), cell.frame("top"))
        # tcp_marks holds unlabelled single-jaw pixels (~70 px apart > follow_px) until remap_marks labels them
        kept = [] if tcp_marks else consensus(marks, prm.get(config.get("params"), "calibrate.consensus_px"))
        near = predicted(kept, (x, y)) if len(kept) >= 4 else None
        report = {}
        mark = cell_pivot.mark_jaws(
            cell, config, near=near and ([near], prm.get(config.get("params"), "pivot.follow_px")),
            keep=frames / f"{i:02d}", report=report,
        )
        row = {"point": [x, y], "mark": mark, "near": near}
        visit = {"point": [x, y], "status": "observed" if mark is not None else "missed", "pixel": mark}
        visits.append(visit)
        if mark is None and report.get("reason"):
            row["why"] = report["reason"]
        if mark:
            fk_x, fk_y, fk_z, fk_yaw = rp.measured_tcp_yaw(cell, config, lib, (x, y))
            if fk_z is not None:
                visit["measured_tcp_m"] = [fk_x, fk_y, fk_z]
            if tcp_marks and fk_yaw is None:
                row["why"], mark = "no planned FK yaw for the jaw labelling", None
            elif tcp_marks:
                seen_jaws.append({"tcp": (fk_x, fk_y), "yaw": fk_yaw, "pixel": tuple(mark), "blobs": report.get("blobs") or []})
        log(row)
        if mark:
            marks.append((mark, (fk_x, fk_y)))
    cell.act("park")
    after = cell.frame("top")
    cv2.imwrite(str(frames / "after.jpg"), after)
    moved = cell_scene_guard.scene_moved(before, after, ignore=rp.scene_ignore(config))
    rp.save_observations(frames, z_view=z_view, tcp_marks=tcp_marks, marks=marks, seen_jaws=seen_jaws, scene_moved=moved)
    if moved:
        raise SystemExit(f"{stop + '; ' if stop else ''}remap: the scene changed during it, no map saved: {moved}; views in {frames}")
    record = rp.fit_naming_stop(stop, config, z_view, tcp_marks=tcp_marks, marks=marks, seen_jaws=seen_jaws, frames_dir=frames, log=log)
    return {**record, "planned_visits": visits}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("step", choices=["check", "auto"])
    ap.add_argument("--route", nargs=2, metavar=("SOURCE", "DEST"), help="check named A/B depth inputs")
    ap.add_argument("--cad-image-evidence", type=Path, help="read an offline CAD observation file for --route")
    ap.add_argument("--targets", nargs="*", default=[], help="site:x,y points the next picks need a bias near")
    ap.add_argument("--remeasure-surface", metavar="SITE", help="repeat a registered surface measurement, even with a saved height")
    ap.add_argument("--surface-clear", action="store_true", help="the named fixed support and the arm path are visibly clear")
    ap.add_argument("--commissioning", action="store_true", help="auto: a supervised calibration stage (D-911)")
    ap.add_argument("--plan-only", action="store_true", help="print each remap point's IK and verdict; opens no port or camera")
    ap.add_argument("--replay-frames", type=Path, help="check: replay a saved remap-frames dir offline; opens no port or camera and writes no calibration")
    ap.add_argument("--only", nargs="+", choices=["remap", "regions", "pivot-near", "surface", "rebind-followers", "consensus-repair", "post-eval", "depth-verify"],
                    help="auto: run only the reviewed step kinds")
    ap.add_argument("--verify", action="store_true", help="auto: chain post-eval XY visit and depth-verify after calibration steps")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    ap.add_argument("--obstacle-mm", type=float, default=None, help="override obstacle height (mm above table) for remap z_view clearance")
    ap.add_argument("--remeasure-map", action="store_true", help="auto --only remap: remap even when check finds the map current")
    args = ap.parse_args(argv)
    if refused := cell_calibrate_args.argument_error(args):
        ap.error(refused)
    import cv2
    import cell_pipeline as cp

    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["params"] = prm.load(config.get("params_path"))["values"]
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    points = config.get("calibrate", {}).get("map_points", MAP_POINTS)
    if args.plan_only:
        out = rp.plan_only(config, points, args.obstacle_mm)  # the IK rows, the refusal, reach, leverage and the z_view record
        print(json.dumps(out), flush=True)
        return 2 if out["refused"] else 0
    if args.replay_frames is not None:
        if args.step != "check":
            raise SystemExit("--replay-frames is offline read-only and only allowed with step 'check'")
        record = rp.replay_observations(args.replay_frames, config, log=lambda row: None)
        agrees = map_agrees(record, config["params"])
        print(json.dumps({"replay": record["loo_error_mm"], "agrees": agrees, "record": record}, default=str), flush=True)
        return 0 if agrees else 2
    cal_path = Path(config["calibration_path"]).expanduser()
    calibration = json.loads(cal_path.read_text()) if cal_path.exists() else {"schema": cal.SCHEMA, "sites": {}}
    targets = [(t.split(":")[0], tuple(float(v) for v in t.split(":")[1].split(","))) for t in args.targets]
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    work = Path(config["work_dir"]).expanduser() / "calibrate"
    if args.step != "check":
        work.mkdir(parents=True, exist_ok=True)
    from cell_shared_pallet import fixture_check_frame, shared_pallet
    top_frame, fixture_report = fixture_check_frame(cell, config, calibration, args.step, args.config)
    found = check(config, calibration, targets, top_frame, config["params"])
    found.update(fixture_report)
    if args.step == "check":
        from cell_route_calibration import include_route_report
        include_route_report(config, calibration, found, args, ap)
    todo = stale(found)
    if args.remeasure_surface is not None:
        import cell_surface
        refused = cell_surface.surface_selection_error(config, calibration, found, args.remeasure_surface)
        if refused:
            print(json.dumps({"held": refused, "site": args.remeasure_surface}), flush=True)
            return 2
        todo = [f"surface {args.remeasure_surface}"]
    if todo == ["review-camera-reference"]:
        print(json.dumps({"check": found, "todo": todo, "held": found["camera_advice"]}), flush=True)
        return 0 if args.step == "check" else 2
    todo = cell_calibrate_args.with_remeasure(todo, args.remeasure_map)
    if args.verify:
        for vstep in ("post-eval", "depth-verify"):
            if vstep not in todo:
                todo.append(vstep)
    if args.only:
        todo = [step for step in todo if step.split()[0] in args.only]
    print(json.dumps({"check": found, "todo": todo}, default=str), flush=True)
    if args.step == "check" or not todo:
        return 0
    remap_config, z_info = (config, None) if "remap" not in todo else rp.remap_view(config, top_frame, args.obstacle_mm, depth_capture, depth_config=rp.regions_now(config, found, top_frame))
    depth_bad = f"obstacle not measured: {z_info['depth_error']}; fix the D435 or pass --obstacle-mm" if z_info and z_info.get("depth_error") else None
    refused = depth_bad or (rp.refusal(rp.plan(remap_config, points)) if "remap" in todo else None)  # before any move: one bad point refuses the run
    if refused:
        print(json.dumps({"refused": refused, "todo": todo, **({"z_view": z_info} if z_info else {})}), flush=True)
        return 2
    if not set(todo) <= {"depth-verify", "rebind-followers"} and not (args.commissioning and args.person_at_switch):  # no-motion steps
        print(json.dumps({"held": "supervised commissioning required (--commissioning --person-at-switch)", "todo": todo, **({"z_view": z_info} if z_info else {})}), flush=True)
        return 2
    done, config_dirty, old_geometry = [], False, None
    for step in todo:
        if step == "remap":
            ref_path = Path(remap_config["preflight"]["reference_top"]).expanduser()
            import cell_hooks, cell_pivot_bias

            stills = cell_hooks.stills(cell, remap_config)
            try:
                record = remap(cell, remap_config, points, work, at_stop=stills)
            finally:
                stills.close()
            if not map_agrees(record, remap_config["params"]):
                done.append({"remap": record["loo_error_mm"], "refused": "marks disagree; map not saved"})
                break
            current = cell.frame("top")
            for site in _map_write_sites(remap_config):
                calibration["sites"][site] = dict(record, note="remap by cell_calibrate")
            if ref_path.exists():
                move_regions(
                    config,
                    cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE),
                    cv2.cvtColor(current, cv2.COLOR_BGR2GRAY),
                )
                config_dirty = True
            if config.get("arm_id") in ("arm_a", "arm_b") and "map_binding_error" in found and found["map_binding_error"] is None:
                comparison = shared_pallet(config, calibration, candidate_frame=current)
                if comparison["status"] == "mismatch":
                    done.append({"remap": record["loo_error_mm"], "refused": "shared pallet work surfaces disagree",
                                 "shared_pallet_surface": comparison})
                    print(json.dumps({"done": done}), flush=True)
                    return 2  # the geometry, map, reference and bias on disk still belong to the previous generation
            old_geometry = calibration.get("reference_geometry_sha") or ""  # the binding this remap replaces
            save_bound_map_reference(cal_path, ref_path, calibration, remap_config, current)
            bp = cell_pivot.bias_path(cal_path)
            if bp.exists():
                bp.with_suffix(".json.bak").write_bytes(bp.read_bytes())
            bp_tmp = bp.with_suffix(".tmp")
            bp_tmp.write_text(json.dumps({"schema": cell_pivot.SCHEMA, "regions": []}), encoding="utf-8")
            bp_tmp.replace(bp)
            cell_pivot_bias._BIAS_CACHE.clear()
            done.append({"remap": record["loo_error_mm"], **({"z_view": z_info} if z_info else {})})
        elif step == "regions":
            continue
        elif step == "rebind-followers":
            done.append(cell_map_followers.rebind(config, calibration, cal_path, found, prm.get(config["params"], "calibrate.max_shift_px"), args.config))
        elif step == "consensus-repair":
            from cell_auto_evidence import bound_reference_image
            ref_path = Path(ref_name).expanduser() if (ref_name := (config.get("preflight") or {}).get("reference_top")) else None
            reference, error = bound_reference_image(calibration, config, ref_path)
            if error:
                done.append({"consensus-repair": error})
                break
            for s in map_sites(config):
                rec = (calibration.get("sites") or {}).get(s) or {}
                pts = [(tuple(p["pixel"]), tuple(p["arm_m"])) for p in (rec.get("points") or [])]
                if len(pts) >= 5:
                    kept = consensus(pts, prm.get(config.get("params"), "calibrate.consensus_px"))
                    if enough_agree(len(kept), len(pts)):
                        calibration["sites"][s] = repair_record(config, rec, kept)
            for name, site in (config.get("sites") or {}).items():
                if isinstance(site, dict) and not site.get("tier_of") and (p := site.get("map_from")) in (calibration.get("sites") or {}):
                    calibration["sites"][name] = dict(calibration["sites"][p])
            save_bound_map_reference(cal_path, ref_path, calibration, config, reference)
            done.append({"consensus-repair": calibration["sites"][map_sites(config)[0]]["loo_error_mm"]})
        elif step.startswith("pivot-near"):
            done.append(pivot_near(cell, config, calibration, cal_path, step, work))  # pivot_precheck before any motion
        elif step.startswith("surface"):
            import cell_surface
            if args.remeasure_surface is not None:
                res = cell_surface.remeasure_surface(cell, config, calibration, step, work)
                if res.get(step) != "touched":
                    print(json.dumps({"held": res}), flush=True)
                    return 2
            else:
                res = cell_surface.run_surface_step(cell, config, step, work)
            done.append(res)
            if res.get(step) == "touched":
                config_dirty = True
        elif step == "post-eval":
            import cell_post_eval
            rep = cell_post_eval.run_post_eval(
                cell, config, calibration, targets=targets or None, apply=True,
                commissioning=args.commissioning, person_at_switch=args.person_at_switch, work=work,
            )
            done.append({"post-eval": rep.get("verdict"), "applied": len(rep.get("applied") or []), "escalated": rep.get("escalated")})
        elif step == "depth-verify":
            import cell_cal_eval
            bias_d = cell_pivot.load_bias(cell_pivot.bias_path(cal_path), config.get("params")) if cell_pivot.bias_path(cal_path).exists() else None
            # 2026-11-17 panel: this step never passed depth, so it always reported missing_depth on the D435 cells
            depth = depth_capture() if cell_cal_eval.top_has_depth(config) else None
            rep = cell_cal_eval.verify_profile_depth(config, calibration, bias_d, depth=depth, colour=cell.frame("top"))
            if config.get("work_dir"):
                (Path(config["work_dir"]).expanduser() / "depth-verify.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
            done.append({"depth-verify": rep.get("verdict"), "eval_verdict": rep.get("eval_verdict")})
    if config_dirty:
        if err := cell_config_io.write_config_checked(args.config, {k: v for k, v in config.items() if k not in ("params", "plan")}, 1, done):
            print(json.dumps({"config_write_failed": err, "done": done}, default=str), flush=True)
            return 2
    if old_geometry is not None:  # the stack and policy profiles share one map: carry the moved geometry to the other
        done.append({"siblings": sync_siblings(args.config, config, cal_path, old_geometry)})
    print(json.dumps({"done": done}, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
