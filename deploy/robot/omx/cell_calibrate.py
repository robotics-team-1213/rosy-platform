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
import cell_calibration as cal  # noqa: E402
import cell_params as prm  # noqa: E402
from cell_pipeline_io import fold  # noqa: E402
import cell_pivot  # noqa: E402

MAP_POINTS = [
    [-0.12, 0.17],
    [-0.10, 0.19],
    [-0.08, 0.17],
    [-0.06, 0.19],
    [-0.04, 0.17],
    [-0.10, 0.15],
    [-0.06, 0.15],
    [-0.02, 0.19],
    [0.02, 0.19],
    [0.066, 0.195],
    [0.06, 0.18],
    [0.04, 0.17],
]  # the 2026-10-28 remap grid


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
    if ref_gray is not None:
        shift = cell_preflight.camera_shift_px(
            ref_gray,
            frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
        )
        out["camera_shift"] = shift
        out["camera_moved"] = not shift["ok"] or shift["max_px"] > prm.get(params, "calibrate.max_shift_px")
    else:
        out["camera_moved"] = False
        out["no_reference"] = True
    bias = cell_pivot.load_bias(cell_pivot.bias_path(config["calibration_path"]), params)
    for site, xy in targets:
        if not cell_pivot.bias_at(bias, site, xy, reach_mm=prm.get(params, "calibrate.bias_near_mm"), params=params):
            out["missing_bias"].append(f"{site}:{xy[0]},{xy[1]}")
    out["missing_map"] = [s for s in map_sites(config) if s not in calibration.get("sites", {})]
    for s in map_sites(config):
        rec = (calibration.get("sites") or {}).get(s) or {}
        if rec.get("loo_error_mm") and not map_agrees(rec, params) and len(rec.get("points") or []) >= 5:
            pts = [(tuple(p["pixel"]), tuple(p["arm_m"])) for p in rec["points"]]
            kept = consensus(pts, prm.get(params, "calibrate.consensus_px"))
            if enough_agree(len(kept), len(pts)) and cal.loo_error_mm(kept)["max"] <= prm.get(
                params, "calibrate.max_loo_mm"
            ):
                out["consensus_repairable"] = True
                break
    for name, site in config["sites"].items():
        if "surface_z" not in site:
            out["missing_surface"].append(name)
    return out


def map_sites(config: dict) -> list:
    """The sites one remap serves: calibrate.map_sites, else arm A's floor/pinky/belt."""
    return config.get("calibrate", {}).get("map_sites") or [
        s for s in ("floor", "pinky", "belt") if s in config["sites"]
    ]


def predicted(marks: list, point) -> list | None:
    """Where the jaws over `point` should show, from an affine fit of three or more (pixel, arm) marks not on one line."""
    arm = np.array([[a[0], a[1], 1.0] for _, a in marks])
    if len(marks) < 3 or np.linalg.matrix_rank(arm, tol=1e-3) < 3:
        return None
    coef, *_ = np.linalg.lstsq(arm, np.array([m for m, _ in marks], float), rcond=None)
    return [round(float(v), 1) for v in np.array([point[0], point[1], 1.0]) @ coef]


def consensus(marks: list, tol_px: float) -> list:
    """The largest set of marks one affine map explains."""
    n = len(marks)
    if n < 3:
        return list(marks)
    ax = np.array([a[0] for _, a in marks], dtype=np.float64)
    ay = np.array([a[1] for _, a in marks], dtype=np.float64)
    pu = np.array([m[0] for m, _ in marks], dtype=np.float64)
    pv = np.array([m[1] for m, _ in marks], dtype=np.float64)
    idx = np.array(list(itertools.combinations(range(n), 3)), dtype=np.intp)
    i, j, k = idx[:, 0], idx[:, 1], idx[:, 2]
    dx1, dy1 = ax[j] - ax[i], ay[j] - ay[i]
    dx2, dy2 = ax[k] - ax[i], ay[k] - ay[i]
    det = dx1 * dy2 - dx2 * dy1
    span = np.maximum(np.hypot(dx1, dy1), np.hypot(dx2, dy2))
    valid = np.abs(det) > np.maximum(1e-6, 1e-3 * span)
    if not valid.any():
        return list(marks)
    i, j, k = i[valid], j[valid], k[valid]
    dx1, dy1, dx2, dy2 = dx1[valid], dy1[valid], dx2[valid], dy2[valid]
    inv_det = 1.0 / det[valid]
    du1, dv1 = pu[j] - pu[i], pv[j] - pv[i]
    du2, dv2 = pu[k] - pu[i], pv[k] - pv[i]
    au = (dy2 * du1 - dy1 * du2) * inv_det
    bu = (-dx2 * du1 + dx1 * du2) * inv_det
    av = (dy2 * dv1 - dy1 * dv2) * inv_det
    bv = (-dx2 * dv1 + dx1 * dv2) * inv_det
    rx = ax[None, :] - ax[i, None]
    ry = ay[None, :] - ay[i, None]
    eu = pu[i, None] + au[:, None] * rx + bu[:, None] * ry - pu[None, :]
    ev = pv[i, None] + av[:, None] * rx + bv[:, None] * ry - pv[None, :]
    inliers = (eu * eu + ev * ev) <= (tol_px * tol_px)
    counts = inliers.sum(axis=1)
    best_idx = int(np.argmax(counts))
    if counts[best_idx] == 0:
        return list(marks)
    mask = inliers[best_idx]
    return [m for m, keep in zip(marks, mask) if keep]


def enough_agree(kept: int, seen: int) -> bool:
    """Five marks fit a map, and the majority must agree."""
    return kept >= 5 and kept * 2 > seen


def remap(cell, config: dict, points: list, work: Path, log=print) -> dict:
    """Hover the empty jaws at each point (z_view), mark them, fit the map; None marks are skipped."""
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
            lib = cp.write_library(config, view, view, work / f"remap-{i}.json")
        except SystemExit as exc:
            log({"point": [x, y], "skipped": str(exc)[:100]})
            continue
        failed = next((c for c in (f"load {lib}", "goto above_pick") if not cell.act(c).get("ok")), None)
        if failed:
            if not fold(cell).get("ok"):
                raise SystemExit(f"remap stopped at {failed} for {[x, y]} and the park failed")
            log({"point": [x, y], "stopped": failed})
            break
        kept = consensus(marks, prm.get(config.get("params"), "calibrate.consensus_px"))
        cv2.imwrite(str(frames / f"{i:02d}.jpg"), cell.frame("top"))
        near = predicted(kept, (x, y)) if len(kept) >= 4 else None
        mark = cell_pivot.mark_jaws(
            cell, config, near=near and ([near], prm.get(config.get("params"), "pivot.follow_px"))
        )
        log({"point": [x, y], "mark": mark, "near": near})
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
    return {
        "homography": cal.fit(marks).round(9).tolist(),
        "z_view": z_view,
        "coarse": True,
        "dropped_marks": dropped,
        "points": [{"pixel": list(p), "arm_m": list(a)} for p, a in marks],
        "loo_error_mm": cal.loo_error_mm(marks),
        "measured": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


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
    for site in config["sites"].values():
        if site.get("surface_px"):
            site["surface_px"] = tp(site["surface_px"])
        if site.get("auto_roi"):
            r = site["auto_roi"]
            q = np.array(tp([[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]))
            site["auto_roi"] = [
                int(max(0, q[:, 0].min())),
                int(max(0, q[:, 1].min())),
                int(min(639, q[:, 0].max())),
                int(min(479, q[:, 1].max())),
            ]
    return config


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("step", choices=["check", "auto"])
    ap.add_argument("--targets", nargs="*", default=[], help="site:x,y points the next picks need a bias near")
    ap.add_argument("--commissioning", action="store_true", help="auto: a supervised calibration stage (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    import cv2
    import cell_pipeline as cp

    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["params"] = prm.load(config.get("params_path"))["values"]
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    cal_path = Path(config["calibration_path"]).expanduser()
    calibration = json.loads(cal_path.read_text()) if cal_path.exists() else {"schema": cal.SCHEMA, "sites": {}}
    targets = [(t.split(":")[0], tuple(float(v) for v in t.split(":")[1].split(","))) for t in args.targets]
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    work = Path(config["work_dir"]).expanduser() / "calibrate"
    work.mkdir(parents=True, exist_ok=True)
    found = check(config, calibration, targets, cell.frame("top"), config["params"])
    todo = stale(found)
    print(json.dumps({"check": found, "todo": todo}, default=str), flush=True)
    if args.step == "check" or not todo:
        return 0
    if not (args.commissioning and args.person_at_switch):
        print(json.dumps({"held": "supervised commissioning required (--commissioning --person-at-switch)", "todo": todo}))
        return 2
    done = []
    for step in todo:
        if step == "remap":
            ref_path = Path(config["preflight"]["reference_top"]).expanduser()
            record = remap(cell, config, config.get("calibrate", {}).get("map_points", MAP_POINTS), work)
            if not map_agrees(record, config["params"]):
                done.append({"remap": record["loo_error_mm"], "refused": "marks disagree; map not saved"})
                break
            current = cell.frame("top")
            for site in map_sites(config):
                calibration["sites"][site] = dict(record, note="remap by cell_calibrate")
            cal_path.write_text(json.dumps(calibration))
            cell_pivot.bias_path(cal_path).write_text(json.dumps({"schema": cell_pivot.SCHEMA, "regions": []}))
            if ref_path.exists():
                move_regions(
                    config,
                    cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE),
                    cv2.cvtColor(current, cv2.COLOR_BGR2GRAY),
                )
            cv2.imwrite(str(ref_path), current)
            done.append({"remap": record["loo_error_mm"]})
        elif step == "regions":
            continue
        elif step == "consensus-repair":
            for s in map_sites(config):
                rec = (calibration.get("sites") or {}).get(s) or {}
                pts = [(tuple(p["pixel"]), tuple(p["arm_m"])) for p in (rec.get("points") or [])]
                if len(pts) >= 5:
                    kept = consensus(pts, prm.get(config.get("params"), "calibrate.consensus_px"))
                    if enough_agree(len(kept), len(pts)):
                        rec["homography"] = cal.fit(kept).round(9).tolist()
                        rec["points"] = [{"pixel": list(p), "arm_m": list(a)} for p, a in kept]
                        rec["loo_error_mm"] = cal.loo_error_mm(kept)
            cal_path.write_text(json.dumps(calibration))
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
            lib = work / f"surface-{site}.json"
            lib.write_text(json.dumps(cell_surface.probe_library(config["plan"], *s["place"], s["yaw_deg"], 0.10, 0.010)))
            touched = cell_surface.touch(cell, lib)
            if touched["result"] == "touched":
                s["surface_z"] = touched["surface_z"]
            done.append({step: touched["result"], "surface_z": touched.get("surface_z")})
    args.config.write_text(json.dumps({k: v for k, v in config.items() if k not in ("params", "plan")}, indent=1))
    print(json.dumps({"done": done}, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
