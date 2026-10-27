"""Touch survey: surface heights the top camera cannot see, measured by the arm (2026-10-27).

Closed jaws go straight down over each point in a descend_* chunk, so the runner's contact hold stops them at
the first touch; the forward kinematics of the held pose is the surface height there. retreat backs out along
the same path and clears the hold, so the next point needs no park. The touched points are saved as a
cell_calibration surface. Points the planner cannot reach are reported, never guessed.

  python touch_survey.py --config cell-pipeline.json --plan plan.json --name right_side --kind object \\
      --x=0.0,0.025 --y=-0.075,-0.1 [--top 0.10] [--bottom 0.02] [--plan-only]

(--y=... with "=": argparse reads a bare "-0.075,..." as an option.)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cell_calibration as cal  # noqa: E402
from grasp_planner import Planner, norm_to_rad  # noqa: E402

SPEED_M_S = 0.003  # the contact hold stops a 3 mm/s descent within about 2 mm of the first touch (2026-10-27)


def library(planner: Planner, points, top: float, bottom: float) -> tuple[dict, list, list]:
    """A library with above_<k> and descend_touch_<k> per reachable point; (library, kept points, skipped)."""
    base = planner.library()
    yaw, closed = planner.plan["pick"]["yaw_deg"], base["gripper_closed"]
    q5 = norm_to_rad(base["chunks"]["above_pick"][0][4])
    chunks, kept, skipped = {"home": base["chunks"]["home"]}, [], []
    for x, y in points:
        try:
            frames = planner.line((x, y, top), (x, y, bottom), SPEED_M_S, yaw, closed, q5)[0]
        except SystemExit as exc:  # the planner reports an unreachable pose this way
            skipped.append({"xy": [x, y], "why": str(exc)})
            continue
        k = len(kept)
        kept.append((x, y))
        chunks[f"above_{k}"], chunks[f"descend_touch_{k}"] = [frames[0]], frames
    return dict(base, chunks=chunks), kept, skipped


def survey(cell, planner: Planner, points, log=print) -> list:
    """Touch each point of the loaded survey library in turn; the touched [x, y, z] list. Parks at the end."""
    touched = []
    for k, (x, y) in enumerate(points):
        if not cell.act(f"goto above_{k}").get("ok"):
            log({"k": k, "stop": "goto refused"})
            break
        run = cell.act(f"run descend_touch_{k}")
        if not run.get("contact"):  # reached the bottom without a touch: nothing above it here
            log({"k": k, "xy": [x, y], "contact": False})
            continue
        pose = planner.kin.fk([norm_to_rad(v) for v in cell.act("state")["state"][:5]])
        touched.append([pose.x, pose.y, pose.z])
        log({"k": k, "xy": [x, y], "contact": True, "tcp_m": [round(v, 4) for v in touched[-1]]})
        if not cell.act("retreat").get("ok"):
            log({"k": k, "stop": "retreat failed"})
            break
    cell.act("park")
    return touched


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--kind", choices=cal.SURFACE_KINDS, required=True)
    parser.add_argument("--x", required=True)
    parser.add_argument("--y", required=True)
    parser.add_argument("--top", type=float, default=0.10)
    parser.add_argument("--bottom", type=float, default=0.02)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text())
    planner = Planner(json.loads(args.plan.read_text()))
    points = [(float(x), float(y)) for x in args.x.split(",") for y in args.y.split(",")]
    lib, kept, skipped = library(planner, points, args.top, args.bottom)
    for row in skipped:
        print(json.dumps({"skip": row}))
    path = args.config.parent / f"touch-survey-{args.name}.json"
    path.write_text(json.dumps(lib))
    print(json.dumps({"library": str(path), "points": len(kept)}))
    if args.plan_only or not kept:
        return 0
    from cell_pipeline import FifoCell

    cell = FifoCell(args.config.parent / config["io"], config.get("cameras", {}))
    loaded = cell.act(f"load {path}")
    if not loaded.get("ok"):  # e.g. no runner: the session ended on its motor-health log budget (2026-10-27)
        print(json.dumps({"stop": "load failed", "error": loaded.get("error")}))
        return 1
    touched = survey(cell, planner, kept, log=lambda row: print(json.dumps(row), flush=True))
    if touched:
        when = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
        cal.save_surface(Path(config["calibration_path"]).expanduser(), args.name,
                         cal.surface_record(touched, args.kind, when))
    print(json.dumps({"touched": len(touched), "saved": args.name if touched else None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
