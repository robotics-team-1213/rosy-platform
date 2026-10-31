#!/usr/bin/env python3
"""The cell's calibration as one tool: decide what is stale and redo only that, with the arm, no person.

2026-10-28/29 this was done by hand, step by step, after each surprise: the top camera was re-mounted (every map
stale), a pivot was needed next to each target (map error grows far from its points), a surface height was a guess,
a pivot beside a tall object was garbage. Here the same steps are code, in the order they depend on each other:

  check       top view against the map's reference frame (moved?), bias regions near targets, surface heights
  remap       hover the empty jaws over a grid, mark them (open/close difference), fit the map, keep a new
              reference frame; the image regions (polygons, ROIs) follow the camera move by image matching
  pivot-near  find a clear point near a target (empty of objects in the mask, on the surface polygon, in reach)
              and run the pivot there; a circle that is not a circle is refused (cell_pivot)
  surface     touch the surface with closed jaws where a site has none
  auto        check, then only what is needed, then check again; prints what it did and why

  cell_calibrate.py --config cell-auto.json auto [--targets floor:-0.032,0.172 pinky:0.0376,0.2204]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pivot  # noqa: E402

MAP_POINTS = [[-0.12, 0.17], [-0.10, 0.19], [-0.08, 0.17], [-0.06, 0.19], [-0.04, 0.17], [-0.10, 0.15], [-0.06, 0.15],
              [-0.02, 0.19], [0.02, 0.19], [0.066, 0.195], [0.06, 0.18], [0.04, 0.17]]  # the 2026-10-28 remap grid


def clear_point(near_xy, mask, roi, inside, to_px, radius_px: int = 36, max_mm: float = 72.0, reach_m: float = 0.23):
    """The nearest arm point to near_xy whose pivot circle (radius_px around its pixel) is empty in the mask and fully
    on the surface (inside: full-image 0/1 array), within max_mm and reach. None when there is none."""
    best = None
    for dx in np.arange(-max_mm, max_mm + 1, 5.0):
        for dy in np.arange(-max_mm, max_mm + 1, 5.0):
            d = math.hypot(dx, dy)
            p = (near_xy[0] + dx / 1000, near_xy[1] + dy / 1000)
            if d > max_mm or math.hypot(*p) > reach_m or (best and d >= best[0]):
                continue
            px = to_px(p)
            if px is None:
                continue
            x, y, r = int(round(px[0])), int(round(px[1])), radius_px
            if x - r < roi[0] or y - r < roi[1] or x + r >= roi[2] or y + r >= roi[3]:
                continue
            if inside[y - r:y + r, x - r:x + r].min() == 1 and not mask[y - r - roi[1]:y + r - roi[1], x - r - roi[0]:x + r - roi[0]].any():
                best = (d, [round(p[0], 4), round(p[1], 4)])
    return best and best[1]


def stale(check: dict) -> list:
    """The steps a check result asks for, in dependency order (a moved camera makes every bias and region stale)."""
    if check.get("camera_moved"):
        return ["remap", "regions"] + [f"pivot-near {t}" for t in check.get("targets", [])]
    steps = [f"pivot-near {t}" for t in check.get("missing_bias", [])]
    steps += [f"surface {s}" for s in check.get("missing_surface", [])]
    return steps


def check(config: dict, calibration: dict, targets: list, frame, params=None) -> dict:
    """What is stale: camera pose against the reference frame, bias regions near each target, surface heights."""
    import cv2
    import cell_preflight

    out = {"targets": [f"{s}:{x},{y}" for s, (x, y) in targets], "missing_bias": [], "missing_surface": []}
    ref = (config.get("preflight") or {}).get("reference_top")
    if ref and Path(ref).expanduser().exists():
        shift = cell_preflight.camera_shift_px(cv2.imread(str(Path(ref).expanduser()), cv2.IMREAD_GRAYSCALE),
                                               cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        out["camera_shift"] = shift
        out["camera_moved"] = not shift["ok"] or shift["max_px"] > prm.get(params, "calibrate.max_shift_px")
    else:
        out["camera_moved"] = False
        out["no_reference"] = True
    bias = cell_pivot.load_bias(cell_pivot.bias_path(config["calibration_path"]))
    for site, xy in targets:
        # the pick uses a region within pivot.bias_reach_mm, but an accurate pick needs one this close: 44 mm away the
        # floor estimate was 8-10 mm off and every descent met the box (2026-10-29)
        if not cell_pivot.bias_at(bias, site, xy, reach_mm=prm.get(params, "calibrate.bias_near_mm"), params=params):
            out["missing_bias"].append(f"{site}:{xy[0]},{xy[1]}")
    for name, site in config["sites"].items():
        if "surface_z" not in site:
            out["missing_surface"].append(name)
    return out


def remap(cell, config: dict, points: list, work: Path, log=print) -> dict:
    """Hover the empty jaws at each point (z_view), mark them, fit the map; None marks are skipped."""
    import cell_pipeline as cp

    z_view, yaw, marks = config["coarse"]["z_view"], config["sites"]["floor"]["yaw_deg"], []
    for i, (x, y) in enumerate(points):
        view = {"x": x, "y": y, "z": round(z_view - config["plan"]["approach_m"], 4), "yaw_deg": yaw}
        try:
            lib = cp.write_library(config, view, view, work / f"remap-{i}.json")
        except SystemExit as exc:
            log({"point": [x, y], "skipped": str(exc)[:100]})
            continue
        for command in (f"load {lib}", "goto above_pick"):
            if not cell.act(command).get("ok"):
                cell.act("park")
                raise SystemExit(f"remap stopped at {command} for {[x, y]}")
        mark = cell_pivot.mark_jaws(cell, config)
        log({"point": [x, y], "mark": mark})
        if mark:
            marks.append((mark, (x, y)))
    cell.act("park")
    if len(marks) < 5:
        raise SystemExit(f"remap: only {len(marks)} marks")
    return {"homography": cal.fit(marks).round(9).tolist(), "z_view": z_view, "coarse": True,
            "points": [{"pixel": list(p), "arm_m": list(a)} for p, a in marks], "loo_error_mm": cal.loo_error_mm(marks),
            "measured": time.strftime("%Y-%m-%dT%H:%M:%S")}


def move_regions(config: dict, reference, current) -> dict:
    """Carry every image region (site polygons and ROIs) from the reference frame to the current one (ORB + RANSAC)."""
    import cv2

    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(reference, None)
    k2, d2 = orb.detectAndCompute(current, None)
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:600]
    H, _ = cv2.findHomography(np.float32([k1[x.queryIdx].pt for x in m]), np.float32([k2[x.trainIdx].pt for x in m]), cv2.RANSAC, 3.0)
    tp = lambda pts: [[int(round(float(v))) for v in q] for q in cv2.perspectiveTransform(np.float32([pts]), H)[0]]  # noqa: E731
    for site in config["sites"].values():
        if site.get("surface_px"):
            site["surface_px"] = tp(site["surface_px"])
        if site.get("auto_roi"):
            r = site["auto_roi"]
            q = np.array(tp([[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]))
            site["auto_roi"] = [int(max(0, q[:, 0].min())), int(max(0, q[:, 1].min())), int(min(639, q[:, 0].max())), int(min(479, q[:, 1].max()))]
    return config


# --- calibration the pick pipeline runs by itself (moved from cell_auto_pick, 600-line limit) ---

def auto_pivot_point(cell, config, calibration, site, target_xy):
    """clear_point on the live top view: empty of objects, on the site's surface, near the target."""
    import cv2
    import cell_objects
    from cell_observe import predicted_pixel

    img = cell.frame("top")
    roi = tuple(config["sites"][site].get("auto_roi") or (0, 0, img.shape[1], img.shape[0]))
    big = (max(0, roi[0] - 60), max(0, roi[1] - 60), min(img.shape[1], roi[2] + 60), min(img.shape[0], roi[3] + 60))
    mask = cell_objects.foreground(img, big, params=config.get("params"))
    inside = np.zeros(img.shape[:2], np.uint8)
    poly = config["sites"][site].get("surface_px") or [[0, 0], [img.shape[1] - 1, 0], [img.shape[1] - 1, img.shape[0] - 1], [0, img.shape[0] - 1]]
    cv2.fillPoly(inside, [np.asarray(poly, np.int32)], 1)
    return clear_point(target_xy, mask, big, inside, lambda q: predicted_pixel(config, calibration, site, q))


def carried(region: dict) -> bool:
    """A region copied from another site or point, never measured where it stands."""
    return bool(region.get("carried_from")) or str(region.get("source", "")).startswith("carried")


def self_calibrate(cell, config, calibration, calibration_path, site, target_xy, objects, work, bias_data, sleep, log):
    """The bias region near `target_xy`: saved, or a pivot circle at a clear configured point (not in dry runs).
    A carried region never stands in for a measurement: the Pinky tray's, copied from the floor, skipped the pivot
    and the 22:29 pick came down on the box top, >= 16 mm off with the arm within 4 mm of its plan (2026-10-30)."""
    p = config.get("params")
    bias_data = {**bias_data, "regions": [r for r in bias_data["regions"] if not carried(r)]}
    # a region this close is accurate enough to pick with; a farther one was 8-10 mm off (2026-10-29)
    if cell_pivot.bias_at(bias_data, site, target_xy, reach_mm=prm.get(p, "calibrate.bias_near_mm"), params=p):
        return bias_data, None
    pivot = config.get("pivot", {})
    clear_mm, base = pivot.get("clear_mm", prm.get(p, "auto.clear_mm")), config["sites"][site]["yaw_deg"]
    points = [q for q in pivot.get("points", [])
              if 1000 * math.dist(q, target_xy) <= 0.9 * prm.get(p, "pivot.bias_reach_mm", cell_pivot.BIAS_REACH_MM)
              and all(1000 * math.dist(q, o["raw_m"]) >= clear_mm for o in objects)]
    z_view, s_z = cell_pivot.pivot_z_view(config, site), config["sites"][site].get("surface_z")
    if (prm.get(p, "pivot.over_target") and cell is not None and s_z is not None
            and 1000 * (z_view - s_z) - prm.get(p, "pivot.over_top_mm") >= prm.get(p, "pivot.over_clear_mm")):
        # 2026-10-29: floor biases 3.5-5.7 cm apart read 16.9, 6.1 and 4.2 mm and every pick missed; the jaws hover
        # above the box, so they are marked right over it (frame differencing sees the jaws on any background)
        points = [tuple(target_xy)]
    if not points and cell is not None:  # no configured point: find a clear one next to the target in the top view
        found = auto_pivot_point(cell, config, calibration, site, target_xy)
        have = cell_pivot.bias_at(bias_data, site, target_xy, params=p)
        if found and have and math.dist(have["point_m"], target_xy) <= math.dist(found, target_xy) + 0.005:
            return bias_data, None  # a pivot there would not be nearer than the region already measured
        points = [found] if found else []
    if not points:
        if cell_pivot.bias_at(bias_data, site, target_xy, params=p):
            return bias_data, None  # a farther region is still better than none
        return bias_data, "no clear pivot point within reach of the object"
    chosen = min(points, key=lambda q: math.dist(q, target_xy))
    if any(r["site"] == site and math.dist(r["point_m"], chosen) <= 0.010 for r in bias_data["regions"]):
        return bias_data, None  # already measured there (this run or before): measuring again changes nothing
    if cell is None:
        return bias_data, f"needs a pivot at {chosen}"
    yaws = pivot.get("yaws", [base + d for d in (-80, -40, 0, 40, 80, 120)])
    result = cell_pivot.pivot_calibrate(cell, config, chosen, yaws,
                                        calibration, site, work, sleep, log)
    if result["result"] != "calibrated":
        return bias_data, f"pivot: {result['result']}"
    cell_pivot.save_bias(cell_pivot.bias_path(calibration_path), result["bias"])
    return cell_pivot.load_bias(cell_pivot.bias_path(calibration_path)), None


def learn_bias(config: dict, calibration_path, site: str, place_xy, verify: dict) -> dict | None:
    """The arm just set the box at place_xy and the top camera saw it at raw + bias: that difference is the map's bias
    at this surface and object height. 2026-10-28: the Pinky tray reused a bias measured 7 cm higher and the next pick
    from the tray missed by 7.4 mm, onto the box's top edge. A sighting far from the bias in use is not learned (a box
    that slid, or another object)."""
    p = config.get("params")
    if not prm.get(p, "auto.bias_from_place") or not verify.get("found") or "seen_bias_mm" not in verify:
        return None
    seen, used = verify["seen_bias_mm"], verify["used_bias_mm"]
    if math.dist(seen, used) > prm.get(p, "auto.bias_learn_max_mm"):
        return None
    region = {"site": site, "point_m": list(place_xy), "bias_mm": seen, "measured": time.strftime("%Y-%m-%d"),
              "source": "place-and-look: the arm set the box here and the top camera saw it"}
    cell_pivot.save_bias(cell_pivot.bias_path(calibration_path), region)
    return region







def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("step", choices=["check", "auto"])
    ap.add_argument("--targets", nargs="*", default=[], help="site:x,y points the next picks need a bias near")
    ap.add_argument("--commissioning", action="store_true", help="auto: a supervised calibration stage (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    import cv2
    import cell_objects
    import cell_pipeline as cp
    from cell_observe import predicted_pixel

    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["params"] = prm.load(config.get("params_path"))["values"]
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    cal_path = Path(config["calibration_path"]).expanduser()
    calibration = json.loads(cal_path.read_text())
    targets = [(t.split(":")[0], tuple(float(v) for v in t.split(":")[1].split(","))) for t in args.targets]
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    work = Path(config["work_dir"]).expanduser() / "calibrate"
    work.mkdir(parents=True, exist_ok=True)
    found = check(config, calibration, targets, cell.frame("top"), config["params"])
    todo = stale(found)
    print(json.dumps({"check": found, "todo": todo}, default=str), flush=True)
    if args.step == "check" or not todo:
        return 0
    if not (args.commissioning and args.person_at_switch):  # the map, pivot and touch steps move the arm
        print(json.dumps({"held": "supervised commissioning required (--commissioning --person-at-switch)", "todo": todo}))
        return 2
    done = []
    for step in todo:
        if step == "remap":
            ref_path = Path(config["preflight"]["reference_top"]).expanduser()
            record = remap(cell, config, config.get("calibrate", {}).get("map_points", MAP_POINTS), work)
            current = cell.frame("top")
            for site in ("floor", "pinky", "belt"):
                if site in config["sites"]:
                    calibration["sites"][site] = dict(record, note="remap by cell_calibrate")
            cal_path.write_text(json.dumps(calibration))
            cell_pivot.bias_path(cal_path).write_text(json.dumps({"schema": cell_pivot.SCHEMA, "regions": []}))
            move_regions(config, cv2.imread(str(ref_path), cv2.IMREAD_GRAYSCALE), cv2.cvtColor(current, cv2.COLOR_BGR2GRAY))
            cv2.imwrite(str(ref_path), current)
            done.append({"remap": record["loo_error_mm"]})
        elif step == "regions":
            continue  # moved with the remap above
        elif step.startswith("pivot-near"):
            site, xy = step.split()[1].split(":")
            near = tuple(float(v) for v in xy.split(","))
            img = cell.frame("top")
            roi = tuple(config["sites"][site].get("auto_roi") or (0, 0, 640, 480))
            big = (max(0, roi[0] - 60), max(0, roi[1] - 60), min(640, roi[2] + 60), min(480, roi[3] + 60))
            mask = cell_objects.foreground(img, big, params=config["params"])
            inside = np.zeros(img.shape[:2], np.uint8)
            cv2.fillPoly(inside, [np.asarray(config["sites"][site].get("surface_px") or [[0, 0], [639, 0], [639, 479], [0, 479]], np.int32)], 1)
            point = clear_point(near, mask, big, inside, lambda p: predicted_pixel(config, calibration, site, p))
            if point is None:
                done.append({step: "no clear point near the target"})
                continue
            base = config["sites"][site]["yaw_deg"]
            result = cell_pivot.pivot_calibrate(cell, config, point, [base + d for d in (-80, -40, 0, 40, 80, 120)],
                                                calibration, site, work, time.sleep, lambda row: None)
            if result["result"] == "calibrated":
                cell_pivot.save_bias(cell_pivot.bias_path(cal_path), result["bias"])
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
