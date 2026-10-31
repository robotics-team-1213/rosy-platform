#!/usr/bin/env python3
"""Free a touching container by pushing it with the closed jaws: go down behind it, slide it `mm` along a
direction, lift, fold home, then look again. 2026-10-28: the floor's three containers touched and every pick
refused the blob; a closed-jaw push at 1 cm/s, about 12 mm above the floor, moved a container cleanly, but a
push toward other objects dragged them along (the bundle turned 20 degrees), so the path must be clear.

The target is a top-camera pixel on the object and a direction in the image (the camera shows what touches
what); the move itself is planned in arm metres through the floor map and the measured map bias.
shortcut: the pixel and direction come from the caller (Claude reading the frame); pick them from the blob
outline automatically once more than one cluster shape has been pushed.

  cell_push.py --config cell-auto.json --site floor --px 228,330 --dir 0,-1 --mm 35 [--half-mm 15] [--dry-run]
               [--commissioning --person-at-switch]

A push moves the arm outside any reviewed carry and its commands do not pass the D-911 gate, so it moves only as a
supervised trial (--commissioning --person-at-switch), like a pivot; without them it plans and stops (2026-10-31).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_objects  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pipeline as cp  # noqa: E402
import cell_pivot  # noqa: E402
from cell_observe import KEEP, keep, predicted_pixel  # noqa: E402


def geometry(centre_raw, direction, half_mm: float, push_mm: float, gap_mm: float):
    """Jaw start (behind the object) and end (object moved push_mm), raw map metres."""
    d = np.asarray(direction, float) / np.linalg.norm(direction)
    c = np.asarray(centre_raw, float)
    start = c - d * (half_mm + gap_mm) / 1000
    return start, start + d * (push_mm + gap_mm) / 1000, d


def path_clear(mask, roi, to_px, centre_raw, d, half_mm: float, push_mm: float, gap_mm: float,
               surface_px=None) -> list:
    """Foreground pixels where the jaws go down (behind) or where the object's front sweeps (ahead); [] is clear.
    The object itself is skipped: ahead starts a gap past its top face (its side face shows below the top face in
    the top view, facts 28), and the side samples stay 6 mm inside its width (a neighbouring surface's edge, such
    as the board next to the floor, is not an obstacle). A point beyond `surface_px` is blocked: the mask is empty
    there by construction, and the jaws went down onto the raised Pinky tray's edge that way (2026-10-28)."""
    import cv2

    poly = np.asarray(surface_px, np.float32) if surface_px else None
    side = np.array([-d[1], d[0]])
    c, hits = np.asarray(centre_raw, float), []
    checks = [("behind", c - d * (half_mm + gap_mm) / 1000 + side * s / 1000) for s in (-6, 0, 6)]
    for t in np.arange(half_mm + gap_mm, half_mm + push_mm + 4, 4.0):
        checks += [("ahead", c + d * t / 1000 + side * s / 1000) for s in (-half_mm + 6, 0, half_mm - 6)]
    for where, p in checks:
        px = to_px(p)
        if px is None:
            hits.append((where, "off the map"))
            continue
        x, y = int(round(px[0])) - roi[0], int(round(px[1])) - roi[1]
        if poly is not None and cv2.pointPolygonTest(poly, (float(px[0]), float(px[1])), False) < 0:
            hits.append((where, "off the surface"))
        elif not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]):
            hits.append((where, "outside the view"))
        elif mask[y, x]:
            hits.append((where, [round(v * 1000, 1) for v in p]))
    return hits


def push_library(plan: dict, start, end, yaw: float, z: float, speed: float) -> dict:
    from grasp_planner import NAMES, Planner, norm_to_rad, rad_to_norm
    from motion_profile import retime
    from teach_trajectory import GUARD_UNITS_PER_S, slow

    planner, grip = Planner(plan), plan["grip_closed"]
    above = (start[0], start[1], z + plan["approach_m"])
    joints = planner.solve(*above, yaw, norm_to_rad(plan["home"][4]))
    pre = [round(rad_to_norm(q), 3) for q in joints] + [grip]
    down, q5 = planner.line(above, (start[0], start[1], z), plan["descend_m_s"], yaw, grip, joints[4])
    slide, q5 = planner.line((start[0], start[1], z), (end[0], end[1], z), speed, yaw, grip, q5)
    up, _ = planner.line((end[0], end[1], z), (end[0], end[1], z + plan["approach_m"]), plan["lift_m_s"], yaw, grip, q5)
    v = 0.85 * GUARD_UNITS_PER_S
    down = retime(down, plan["fps"], v, start=pre)
    slide = slow(slide, plan["fps"], start=down[-1])[1:]
    up = retime(up, plan["fps"], v, start=slide[-1])
    rnd = lambda frames: [[round(x, 3) for x in f] for f in frames]  # noqa: E731
    home = [round(x, 3) for x in plan["home"]] + [grip]
    return {"schema": "rosy.omx-chunk-library.v1", "names": NAMES, "fps": plan["fps"], "gripper_closed": grip,
            "chunks": {"above_push": [pre], "descend_push": rnd(down), "slide_push": rnd(slide), "lift_push": rnd(up),
                       "home": [home]},
            "transit": plan.get("transit", {}), "transit_speed": plan.get("transit_speed", 0.85)}


def run_push(cell, library_path: Path) -> dict:
    steps = []
    for command in (f"load {library_path}", "goto above_push", "run descend_push", "run slide_push", "run lift_push"):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if not status.get("ok"):
            if status.get("contact"):
                steps.append({"command": "retreat", "ok": cell.act("retreat").get("ok")})
            if not command.startswith("load"):
                steps.append({"command": "park", "ok": cell.act("park").get("ok")})
            return {"result": "contact" if status.get("contact") else "stopped", "at": command, "steps": steps}
    steps.append({"command": "park", "ok": cell.act("park").get("ok")})
    return {"result": "pushed", "steps": steps}


def look_first(cell, config, record, site, region, start_raw, slide, bias, yaw, z, speed, lib, work) -> dict:
    """cell_look before the descent: the jaws over the push start, measured against the start in the same image,
    since a carried bias left the push 1 cm off and the box did not move (2026-10-29). Off: the plan stands."""
    import cell_look

    if not prm.get(config.get("params"), "look.enabled") or not (region or {}).get("radius_mm"):
        return {"verdict": "pass", "why": "look off or no pivot circle here"}
    if not all(cell.act(c).get("ok") for c in (f"load {lib}", "goto above_push")):
        return {"verdict": "refuse", "why": "hover refused"}
    target = {"pick": {"x": float(start_raw[0] - bias[0]), "y": float(start_raw[1] - bias[1]), "z": z, "yaw_deg": yaw},
              "place": {}, "object": {"raw_m": [float(v) for v in start_raw]}, "bias_region": region}

    def write(_config, pick, _place, path):
        s = np.array([pick["x"], pick["y"]])
        path.write_text(json.dumps(push_library(config["plan"], s, s + slide, yaw, z, speed)))
        return path

    # a push keeps push.gap_mm from the box, so it needs less than a grasp: the field looks went 9.6 -> 6.8 -> 4.3 mm
    out = cell_look.look(cell, config, record, site, target, write, work, goto="goto above_push", name="push-look.json",
                         tol_mm=prm.get(config.get("params"), "push.look_tol_mm"))
    return {**out, "library": work / "push-look.json"} if out["total_mm"] else out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--site", default="floor")
    ap.add_argument("--catalog", type=Path, help="to list the objects seen after the push")
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--px", required=True, help="x,y top-camera pixel on the object to push")
    ap.add_argument("--dir", required=True, help="dx,dy push direction in the image")
    ap.add_argument("--mm", type=float, default=35.0)
    ap.add_argument("--half-mm", type=float, default=15.0, help="object half-extent along the push")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial of this one push (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    if args.commissioning != args.person_at_switch:
        raise SystemExit("--commissioning needs --person-at-switch (and the other way round)")
    if not (args.dry_run or args.commissioning):
        raise SystemExit("a push moves the arm outside the D-911 gate: --dry-run, or --commissioning --person-at-switch")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    params = config["params"] = prm.load(config.get("params_path"))["values"]
    plan = json.loads(Path(config["plan_path"]).expanduser().read_text())
    calibration_path = Path(config["calibration_path"]).expanduser()
    calibration = json.loads(calibration_path.read_text())
    record = cell_pivot.map_record(calibration, args.site)
    camera, site = config["cameras"]["top"], config["sites"][args.site]
    height = prm.get(params, "push.height_m")
    z = site["surface_z"] + height
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    work = Path(config["work_dir"]).expanduser() / "push"
    work.mkdir(parents=True, exist_ok=True)
    stamp, KEEP["dir"] = time.strftime("%Y%m%d-%H%M%S"), work

    img = cell.frame("top")
    keep("push-before", img)
    px = [float(v) for v in args.px.split(",")]
    dpx = [float(v) for v in args.dir.split(",")]
    top_z = site["surface_z"] + 0.030  # the container's top face, where the pixel lies
    a, b = cell_objects.to_mm([px, [px[0] + 40 * dpx[0], px[1] + 40 * dpx[1]]], record, camera, top_z) / 1000.0
    direction = b - a
    gap = prm.get(params, "push.gap_mm")
    start, end, d = geometry(a, direction, args.half_mm, args.mm, gap)
    mask = cell_objects.foreground(img, args.roi, params=params, surface_px=site.get("surface_px"), surface_lab=site.get("surface_lab"))
    hits = path_clear(mask, args.roi, lambda p: predicted_pixel(config, calibration, args.site, p), a, d,
                      args.half_mm, args.mm, gap, site.get("surface_px"))
    region = cell_pivot.bias_at(cell_pivot.load_bias(cell_pivot.bias_path(calibration_path)), args.site, a.tolist(),
                                params=params)
    bias = np.asarray(region["bias_mm"] if region else [0.0, 0.0]) / 1000
    yaw = float(np.degrees(np.arctan2(d[1], d[0]))) + 90.0  # jaws closed across the push: a flat face leads
    out = {"site": args.site, "px": px, "dir_px": dpx, "object_raw_mm": (a * 1000).round(1).tolist(),
           "start_m": (start - bias).round(4).tolist(), "end_m": (end - bias).round(4).tolist(), "z": round(z, 4),
           "yaw_deg": round(yaw, 1), "bias_mm": (bias * 1000).round(1).tolist(), "blocked": hits}
    if hits:
        out["result"] = "refused: path not clear"
    elif args.dry_run:
        out["result"] = "planned"
    else:
        lib = work / f"{stamp}-push.json"
        speed = prm.get(params, "push.speed_m_s")
        library, errors = None, []
        # closed jaws push with a flat face across or along the push; the wrist reaches only some yaws at a point
        for jaw_yaw in (yaw, yaw + 90):
            try:
                library = push_library(plan, start - bias, end - bias, ((jaw_yaw + 90) % 180) - 90, z, speed)
                out["yaw_deg"] = round(((jaw_yaw + 90) % 180) - 90, 1)
                break
            except SystemExit as exc:
                errors.append(str(exc)[:120])
        if library is None:
            out["result"] = f"refused: plan {errors}"
        else:
            lib.write_text(json.dumps(library))
            looked = look_first(cell, dict(config, plan=plan), record, args.site, region, start, end - start, bias,
                                out["yaw_deg"], z, speed, lib, work)
            out["look"] = looked
            out.update(run_push(cell, looked.get("library", lib)) if looked["verdict"] == "pass"
                       else {"result": f"refused: look {looked.get('why')}", "steps": [{"park": cell.act("park").get("ok")}]})
            after = cell.frame("top")
            keep("push-after", after)
            if args.catalog:
                objects = cell_objects.detect(after, args.roi, record, camera, cell_objects.load_catalog(args.catalog),
                                              site["surface_z"], params, site.get("surface_px"), site.get("surface_lab"),
                                              (config.get("objects") or {}).get("hsv"))
                out["after"] = [{"centre_mm": o["centre_mm"], "object": o.get("object"), "matched": o["matched"],
                                 "tangled": o.get("tangled", False)} for o in objects]
    (work / f"{stamp}-push.result.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "steps"}, default=str))
    return 0 if out.get("result") in ("pushed", "planned") else 1


if __name__ == "__main__":
    sys.exit(main())
