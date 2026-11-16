#!/usr/bin/env python3
"""The cell's calibration as one tool: decide what is stale and redo only that, with the arm, no person.

Single Responsibility:
  - Offline / supervised cell calibration (`check`, `stale`, `remap`, `move_regions`, `consensus`, `main`).
  - Online self-calibration (`self_calibrate`, `auto_pivot_point`, `learn_bias`, `clear_point`) lives in
    `cell_calibrate_auto.py` and is re-exported here unchanged.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_calibrate_auto import (  # noqa: E402,F401  (re-exported)
    auto_pivot_point,
    carried,
    clear_point,
    learn_bias,
    map_agrees,
    over_target,
    pivot_near_yaws,
    self_calibrate,
)
from cell_calibrate_bound import move_regions, save_bound_map_reference  # noqa: E402,F401  (re-exported)
import cell_calibration as cal  # noqa: E402
from cell_intrinsics_frames import POSE_LOO_SLACK_MM, fitted_map  # noqa: E402,F401  (re-exported)
from cell_map_fit import consensus, enough_agree, predicted, repair_record  # noqa: E402,F401  (re-exported)
import cell_params as prm  # noqa: E402
from cell_pipeline_io import fold  # noqa: E402
import cell_pivot  # noqa: E402
import cell_remap_plan as rp  # noqa: E402

MAP_POINTS = [
    [-0.12, 0.17], [-0.10, 0.19], [-0.08, 0.17], [-0.06, 0.19], [-0.04, 0.17], [-0.10, 0.15],
    [-0.06, 0.15], [-0.02, 0.19], [0.02, 0.19], [0.066, 0.195], [0.06, 0.18], [0.04, 0.17],
]  # the 2026-10-28 remap grid
AT_STOP_S = 1.5  # the most a refused remap move waits for its stop evidence before it folds


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


def stale(check: dict) -> list:
    """The steps a check result asks for, in dependency order."""
    if check.get("camera_moved") or check.get("missing_map"):
        return ["remap", "regions"] + [f"pivot-near {t}" for t in check.get("targets", [])]
    steps = ["consensus-repair"] if check.get("consensus_repairable") else []
    steps += [f"pivot-near {t}" for t in check.get("missing_bias", [])]
    steps += [f"surface {s}" for s in check.get("missing_surface", [])]
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
        out["camera_moved"] = (bool(out.get("map_binding_error")) or out.get("reference_mismatch", False)
                               or not shift["ok"] or shift["max_px"] > prm.get(params, "calibrate.max_shift_px"))
    else:
        out["camera_moved"] = bool(out.get("map_binding_error")) or out.get("reference_mismatch", False)
        out["no_reference"] = True
    try:
        bias = cell_pivot.load_bias(cell_pivot.bias_path(config["calibration_path"]), params)
        for site, xy in targets:
            if not cell_pivot.bias_at(bias, site, xy, reach_mm=prm.get(params, "calibrate.bias_near_mm"), params=params):
                out["missing_bias"].append(f"{site}:{xy[0]},{xy[1]}")
    except ValueError as exc:
        out["bias_error"] = str(exc)
        out["missing_bias"].extend(f"{site}:{xy[0]},{xy[1]}" for site, xy in targets)
    out["missing_map"] = [s for s in map_sites(config) if s not in calibration.get("sites", {})]
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

    drift = cell_cal_monitor.summarize(config, calibration)
    if drift["alarmed_sites"]:
        out["drift"] = drift
        out["advisory_todo"] = drift["suggested_advisory"]
    return out


def map_sites(config: dict) -> list:
    """The sites one remap serves: calibrate.map_sites, else arm A's floor/pinky/belt."""
    return config.get("calibrate", {}).get("map_sites") or [
        s for s in ("floor", "pinky", "belt") if s in config["sites"]
    ]


def remap(cell, config: dict, points: list, work: Path, log=print, at_stop=None) -> dict:
    """Hover the empty jaws at each point (z_view), mark them, fit the map; None marks are skipped.

    at_stop(state, status) runs when a move is refused, before the fold hides what the arm met: the carry path's
    stop evidence (cell_hooks.stills). 2026-11-14: arm_b's first remap goto stopped on contact at wrist_flex 59.3
    and nothing but the runner's one line said what it met."""
    import cv2
    import cell_pipeline as cp
    import cell_scene_guard

    z_view, yaw, marks = config["coarse"]["z_view"], config["sites"][map_sites(config)[0]]["yaw_deg"], []
    frames = work / "remap-frames" / time.strftime("%Y%m%d-%H%M%S")
    frames.mkdir(parents=True, exist_ok=True)
    before = cell.frame("top")
    cv2.imwrite(str(frames / "before.jpg"), before)
    for i, (x, y) in enumerate(sorted(points, key=lambda q: math.hypot(*q))):
        view = {"x": x, "y": y, "z": round(z_view - config["plan"]["approach_m"], 4), "yaw_deg": yaw}
        try:
            lib = cp.write_library(rp.scoped(config), view, view, work / f"remap-{i}.json")
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
            if at_stop is not None:  # evidence never stands between a stop and the fold: a stuck camera's
                import threading      # frame() could hold the arm in contact for ~60 s, so it gets AT_STOP_S

                def grab():
                    try:
                        at_stop(status.get("state"), status)
                    except BaseException:
                        pass
                grabber = threading.Thread(target=grab, daemon=True)
                grabber.start()
                grabber.join(timeout=AT_STOP_S)
            if not fold(cell).get("ok"):
                raise SystemExit(f"remap stopped at {failed} for {[x, y]} and the park failed")
            log({"point": [x, y], "stopped": failed, "error": status.get("error"), "state": status.get("state")})
            break
        kept = consensus(marks, prm.get(config.get("params"), "calibrate.consensus_px"))
        cv2.imwrite(str(frames / f"{i:02d}.jpg"), cell.frame("top"))
        near = predicted(kept, (x, y)) if len(kept) >= 4 else None
        report = {}
        mark = cell_pivot.mark_jaws(
            cell, config, near=near and ([near], prm.get(config.get("params"), "pivot.follow_px")),
            keep=frames / f"{i:02d}", report=report,
        )
        row = {"point": [x, y], "mark": mark, "near": near}
        if mark is None and report.get("reason"):
            row["why"] = report["reason"]
        log(row)
        if mark:
            marks.append((mark, (x, y)))
    cell.act("park")
    after = cell.frame("top")
    cv2.imwrite(str(frames / "after.jpg"), after)
    moved = cell_scene_guard.scene_moved(before, after)
    if moved:
        raise SystemExit(f"remap: the scene changed during it, no map saved: {moved}; views in {frames}")
    seen, marks = marks, consensus(marks, prm.get(config.get("params"), "calibrate.consensus_px"))
    dropped = [{"pixel": list(p), "arm_m": list(a)} for p, a in seen if (p, a) not in marks]
    if dropped:
        log({"dropped_marks": dropped})
    if not enough_agree(len(marks), len(seen)):
        raise SystemExit(f"remap: only {len(marks)} marks agree of {len(seen)}")
    return dict(fitted_map(config, marks, z_view), **{
        "z_view": z_view,
        "coarse": True,
        "dropped_marks": dropped,
        "points": [{"pixel": list(p), "arm_m": list(a)} for p, a in marks],
        "loo_error_mm": cal.loo_error_mm(marks),
        "measured": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("step", choices=["check", "auto"])
    ap.add_argument("--targets", nargs="*", default=[], help="site:x,y points the next picks need a bias near")
    ap.add_argument("--commissioning", action="store_true", help="auto: a supervised calibration stage (D-911)")
    ap.add_argument("--plan-only", action="store_true", help="print each remap point's IK and verdict; opens no port or camera")
    ap.add_argument("--only", nargs="+", choices=["remap", "regions", "pivot-near", "surface", "consensus-repair"], help="auto: run only these step kinds (remap, regions, pivot-near, "
                    "surface, consensus-repair); a reviewed plan for one step must not run the others. 2026-11-15: a "
                    "scratch config copied after a remap found the map fresh and ran unreviewed surface touches")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    import cv2
    import cell_pipeline as cp

    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["params"] = prm.load(config.get("params_path"))["values"]
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    points = config.get("calibrate", {}).get("map_points", MAP_POINTS)
    if args.plan_only:
        import cell_map_fit

        rows = rp.plan(config, points)
        refused = rp.refusal(rows)
        lev = cell_map_fit.plan_leverage(points, config.get("sites") or {})
        print(json.dumps({"plan_only": rows, "refused": refused, "reach": rp.reach_note(config), "leverage": lev}), flush=True)
        return 2 if refused else 0
    cal_path = Path(config["calibration_path"]).expanduser()
    calibration = json.loads(cal_path.read_text()) if cal_path.exists() else {"schema": cal.SCHEMA, "sites": {}}
    targets = [(t.split(":")[0], tuple(float(v) for v in t.split(":")[1].split(","))) for t in args.targets]
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    work = Path(config["work_dir"]).expanduser() / "calibrate"
    work.mkdir(parents=True, exist_ok=True)
    found = check(config, calibration, targets, cell.frame("top"), config["params"])
    todo = stale(found)
    if args.only:
        todo = [step for step in todo if step.split()[0] in args.only]
    print(json.dumps({"check": found, "todo": todo}, default=str), flush=True)
    if args.step == "check" or not todo:
        return 0
    refused = rp.refusal(rp.plan(config, points)) if "remap" in todo else None  # before any move: one bad point refuses the run
    if refused:
        print(json.dumps({"refused": refused, "todo": todo}))
        return 2
    if not (args.commissioning and args.person_at_switch):
        print(json.dumps({"held": "supervised commissioning required (--commissioning --person-at-switch)", "todo": todo}))
        return 2
    done = []
    for step in todo:
        if step == "remap":
            ref_path = Path(config["preflight"]["reference_top"]).expanduser()
            import cell_hooks

            stills = cell_hooks.stills(cell, config)
            try:
                record = remap(cell, config, points, work, at_stop=stills)
            finally:
                stills.close()
            if not map_agrees(record, config["params"]):
                done.append({"remap": record["loo_error_mm"], "refused": "marks disagree; map not saved"})
                break
            current = cell.frame("top")
            for site in map_sites(config):
                calibration["sites"][site] = dict(record, note="remap by cell_calibrate")
            if ref_path.exists():
                move_regions(
                    config,
                    cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE),
                    cv2.cvtColor(current, cv2.COLOR_BGR2GRAY),
                )
            save_bound_map_reference(cal_path, ref_path, calibration, config, current)
            cell_pivot.bias_path(cal_path).write_text(json.dumps({"schema": cell_pivot.SCHEMA, "regions": []}))
            done.append({"remap": record["loo_error_mm"]})
        elif step == "regions":
            continue
        elif step == "consensus-repair":
            from cell_auto_evidence import bound_reference_image

            ref_name = (config.get("preflight") or {}).get("reference_top")
            ref_path = Path(ref_name).expanduser() if ref_name else None
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
            save_bound_map_reference(cal_path, ref_path, calibration, config, reference)
            done.append({"consensus-repair": calibration["sites"][map_sites(config)[0]]["loo_error_mm"]})
        elif step.startswith("pivot-near"):
            site, xy = step.split()[1].split(":")
            near = tuple(float(v) for v in xy.split(","))
            point = list(near) if over_target(config, site) else auto_pivot_point(cell, config, calibration, site, near)
            if point is None:
                done.append({step: "no clear point near the target"})
                continue
            result = cell_pivot.pivot_calibrate(
                cell, config, point, pivot_near_yaws(config, site), calibration, site, work, time.sleep, lambda row: None
            )
            if result["result"] == "calibrated":
                cell_pivot.save_bias(cell_pivot.bias_path(cal_path), result["bias"], config.get("params"))
            done.append({step: result["result"], "at": point, "bias": result.get("bias", {}).get("bias_mm")})
        elif step.startswith("surface"):
            import cell_surface

            site = step.split()[1]
            s = config["sites"][site]
            if not s.get("place"):
                done.append({step: "no place point to touch"})
                continue
            tcp_x_m = config["tcp_x_m"] if config.get("tcp_x_m") is not None else config["plan"].get("tcp_x_m")
            lib = work / f"surface-{site}.json"
            lib.write_text(json.dumps(cell_surface.probe_library(
                config["plan"], *s["place"], s["yaw_deg"], 0.10, 0.010, tcp_x_m=tcp_x_m)))
            touched = cell_surface.touch(cell, lib, tcp_x_m=tcp_x_m)
            if touched["result"] == "touched":
                s["surface_z"] = touched["surface_z"]
            done.append({step: touched["result"], "surface_z": touched.get("surface_z")})
    args.config.write_text(json.dumps({k: v for k, v in config.items() if k not in ("params", "plan")}, indent=1))
    print(json.dumps({"done": done}, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
