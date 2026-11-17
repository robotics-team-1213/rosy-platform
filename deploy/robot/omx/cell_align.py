#!/usr/bin/env python3
"""Arm-only alignment (정렬) as one pipeline: the cell's own measurements choose the next step, one motion per call.

2026-11-01: three 3-cell columns stood 4 mm apart and no pick had finger room. By hand it took a lengthwise push
(off-centre, so the jaw face missed the neighbour), a pivot over the column for the push lane, then a grasp near
the freed end. A tangled pile (2026-11-13) is slid as the one blob it is when its path is clear,
else it is locked (hold, type locked_pile). Here that order is code:

  plan   observe and print the next step and why (no motion)
  next   run exactly that step (--commissioning --person-at-switch), then print the step after it

The step is a pick when one is planned (cell_auto_pick measures its own bias first); else a push that frees a
packed long box (cell_push), after a pivot over it when no bias region is near (cell_calibrate); else hold.
A person confirms every motion: there is no loop that runs the steps unattended (D-911).

  cell_align.py --config cell.json --catalog object-catalog.json --roi X0 Y0 X1 Y1 --from col1 \\
                    --push-site pallet --dest col2top plan
shortcut: layer heights come from the sites (--from is the top layer's surface, --push-site the floor); take them
from cell_depth per footprint once a stack's height is read reliably on every frame.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_auto_pick as auto  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_decisions as cd  # noqa: E402
import cell_objects  # noqa: E402
import cell_params as prm  # noqa: E402
import cell_pivot  # noqa: E402
import cell_push  # noqa: E402
from cell_observe import predicted_pixel  # noqa: E402


def free_push(objects: list, mask, roi, to_px, params, miss_mm: float, surface_px=None) -> dict | None:
    """A lengthwise push that leaves one end of a packed long box clear for the fingers: the push line is shifted
    sideways (never so far that less than the box face minus align.face_short_mm meets the jaws) until the jaws'
    lane misses the neighbour, and long enough that the grasp point near the far end passes the neighbour's end
    (boxes of a row stand flush). The narrow push (one 20 mm finger pad leading, cell_push --narrow) is tried first:
    it fits inside a 30 mm face, so its lane clears a neighbour 4 mm away where the 42 mm face cannot (2026-11-02).
    None when no direction and offset leaves the path clear."""
    poly = np.asarray(surface_px, np.float32) if surface_px else None
    for o, narrow in ((o, n) for o in objects for n in (True, False)):
        face, back = cell_push.jaw_shape(params, narrow)
        gap = prm.get(params, "push.gap_mm") + back
        length, width = o["length_mm"], o["width_mm"]
        u = math.radians(o["long_axis_deg"])
        along, side, c = np.array([math.cos(u), math.sin(u)]), np.array([-math.sin(u), math.cos(u)]), np.asarray(o["raw_m"])
        reach = prm.get(params, "grasp.end_frac") * (length - width) / 2
        mm = round(length / 2 - reach + prm.get(params, "align.free_margin_mm"), 1)
        # narrow: the pad stays on the box face; wide: at most face_short_mm of the face may miss the jaws
        most = width / 2 - face if narrow else face - width / 2 + prm.get(params, "align.face_short_mm")
        for sign in (1, -1):
            for off in sorted({s * k for k in range(int(most) + 1) for s in (1, -1)}, key=lambda v: (abs(v), v)):
                at = c + side * off / 1000
                if not cell_push.path_clear(mask, roi, to_px, at, sign * along, length / 2, mm, gap, poly,
                                            face + miss_mm, width / 2, 2 * back, stop_on_first=True):
                    return {"object": o.get("object"), "centre_mm": o["centre_mm"], "at": [round(v, 4) for v in at],
                            "along_deg": round(math.degrees(math.atan2(*(sign * along)[::-1])), 1),
                            "offset_mm": round(float(off), 1), "mm": mm, "half_mm": length / 2, "half_width_mm": width / 2,
                            "narrow": narrow}
    return None


def next_step(cell, config, calibration, calibration_path, catalog, roi, source, push_site, dest, work, packed=None) -> dict:
    """What the cell needs next, from what the top camera shows now. No motion. `packed`: centres (mm) already known to need
    a push, though they look free (cell_recovery: a lift stalled there)."""
    import cell_choices

    refused = []
    if packed is None:
        dry = auto.run_auto(cell, config, calibration, calibration_path, catalog, roi, source, dest, work,
                            cell_choices.Choices(work / "choices.json"), dry_run=True)
        if dry["result"] == "planned":
            return {"step": "pick", "why": "a box has finger room and a plan", "chosen": dry["attempts"][-1].get("chosen")}
        refused = (dry.get("attempts") or [{}])[-1].get("refused", [])
        packed = [r["centre_mm"] for r in refused if str(r["why"]).startswith("no finger room")]
    tangled = [r["centre_mm"] for r in refused if r["why"] == "tangled blob"]
    if not packed and not tangled:
        return {"step": "hold", "why": dry["result"], "refused": refused}
    _, _, objects, error = auto.observe(cell, config, calibration, source, roi, catalog)
    entries = {e["id"]: e for e in catalog}  # its catalogue size: a 2-layer column's top view adds its side faces
    long_packed = [dict(o, length_mm=entries[o["object"]]["length_mm"], width_mm=entries[o["object"]]["width_mm"])
                   for o in objects if o.get("object") in entries  # a fresh frame: the same box within 10 mm
                   and any(math.dist(o["centre_mm"], c) <= 10 for c in packed)
                   and entries[o["object"]]["length_mm"] > entries[o["object"]]["width_mm"]]
    if error or not (long_packed or tangled):
        return {"step": "hold", "why": error or "no finger room, and no long box to slide", "refused": refused}
    p, site = config.get("params"), config["sites"][push_site]
    mask = cell_objects.foreground(cell.frame("top"), roi, params=p, surface_px=site.get("surface_px"),
                                   surface_lab=site.get("surface_lab"))
    to_px = lambda q: predicted_pixel(config, calibration, push_site, q)  # noqa: E731
    bias = cell_pivot.load_bias(cell_pivot.bias_path(calibration_path), p)
    for o in long_packed:
        region = cell_pivot.bias_at(bias, push_site, o["raw_m"], params=p)
        if region and region.get("rms_mm") is not None:
            miss = region["rms_mm"]
        else:  # no measurement here: the map's worst error, as cell_push itself will plan the lane
            miss = (cell_pivot.map_record(calibration, push_site) or {}).get("loo_error_mm", {}).get("max", 0.0)
        push = free_push([o], mask, roi, to_px, p, miss, site.get("surface_px"))
        if push:
            return {"step": "push", "why": "packed: slide it along its length so one end clears", "push": push,
                    "miss_mm": miss}
        if region is None and free_push([o], mask, roi, to_px, p, prm.get(p, "pivot.max_rms_mm"), site.get("surface_px")):
            return {"step": "pivot", "why": "a push fits only with the error measured here", "at": o["raw_m"]}
    if tangled:
        miss = (cell_pivot.map_record(calibration, push_site) or {}).get("loo_error_mm", {}).get("max", 0.0)
        found = pile_push(objects, tangled, lambda o: free_push([o], mask, roi, to_px, p, miss, site.get("surface_px")))
        if found:
            return {"step": "push", "type": "pile", "why": "a tangled pile: slide its nearest free piece clear, then look again",
                    "push": found, "miss_mm": miss}
        return {"step": "hold", "type": "locked_pile", "why": "a tangled pile, and no piece of it has a clear push", "refused": refused}
    return {"step": "hold", "why": "packed, and no lengthwise push has a clear path", "refused": refused}


def pile_push(objects: list, tangled: list, try_push) -> dict | None:
    """2026-11-13 (arm_s): a box's end lay on another box and the pile leaned on the arm plate. Boxes that touch merge into one
    blob in the top view, so the pile is the tangled blob itself: it moves at its measured size when its push path is clear,
    and a box seen apart is no part of it (moving one would hide a locked pile, review). The next look re-plans."""
    pile = [o for o in objects if o.get("tangled") and any(math.dist(o["centre_mm"], c) <= 10 for c in tangled)]
    return next((push for o in pile if (push := try_push(o))), None)


def run_step(step: dict, args) -> int:
    """The one motion the step names, through its own supervised tool (each keeps its decision rows)."""
    base = ["--config", str(args.config), "--commissioning", "--person-at-switch"]
    if step["step"] == "pick":
        return auto.main(base + ["--catalog", args.catalog, "--roi", *map(str, args.roi), "--from", args.source,
                                 "--dest", args.dest])
    if step["step"] == "pivot":
        import cell_calibrate
        return cell_calibrate.main(base[:2] + ["auto", "--targets", f"{args.push_site}:{step['at'][0]},{step['at'][1]}"]
                                   + base[2:])
    if step["step"] == "push":
        q = step["push"]
        return cell_push.main(base + ["--site", args.push_site, "--roi", *map(str, args.roi), "--catalog", args.catalog,
                                      "--at", f"{q['at'][0]},{q['at'][1]}", "--along", str(q["along_deg"]),
                                      "--mm", str(q["mm"]), "--half-mm", str(q["half_mm"]),
                                      "--half-width-mm", str(q["half_width_mm"])] + (["--narrow"] if q["narrow"] else []))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--roi", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--from", dest="source", required=True, help="site of the layer to pick from")
    ap.add_argument("--push-site", help="site of the floor a packed box slides on (default --from)")
    ap.add_argument("--dest", required=True)
    ap.add_argument("action", choices=["plan", "next"])
    ap.add_argument("--commissioning", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    args.push_site = args.push_site or args.source
    if args.action == "next" and not (args.commissioning and args.person_at_switch):
        raise SystemExit("next moves the arm: --commissioning --person-at-switch (one supervised step, D-911)")
    config = auto.load_config(args.config)
    work = Path(config["work_dir"]).expanduser()
    calibration_path = Path(config["calibration_path"]).expanduser()
    catalog = cell_objects.load_catalog(args.catalog)
    cell = auto.cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    step = next_step(cell, config, cal.load(calibration_path), calibration_path, catalog, args.roi, args.source,
                     args.push_site, args.dest, work)
    print(json.dumps({"next": step}, default=str))
    if args.action == "plan" or step["step"] == "hold":
        return 0 if step["step"] != "hold" else 1
    cd.start(work / "decisions.jsonl", knowledge=config.get("knowledge"))
    cd.emit("align", {k: v for k, v in step.items() if k != "step"}, ["pick", "push", "pivot", "hold"], step["step"],
            "rule", step["why"])
    code = run_step(step, args)
    after = next_step(cell, config, cal.load(calibration_path), calibration_path, catalog, args.roi, args.source,
                      args.push_site, args.dest, work)
    print(json.dumps({"done": step["step"], "exit": code, "next": after}, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
