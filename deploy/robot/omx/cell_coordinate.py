#!/usr/bin/env python3
"""Offline: how two arms' real carries can share the cell (omx_adapter.coordination). Reads files only, moves nothing.

  cell_coordinate.py --a cell-a.json lib-a.json --b cell-b.json lib-b.json [--margin 0.03]

Prints the schedule and the time one-after-the-other would take.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_calibration import _inv3x3  # noqa: E402
from grasp_planner import load_kinematics, norm_to_rad  # noqa: E402
from omx_adapter.chunk_library import NAMES, park_path, transit_path  # noqa: E402
from omx_adapter.coordination import Segment, clearance, moved, plan, rendezvous, rigid_between, thinned  # noqa: E402
from omx_adapter.swept_volume import capsules  # noqa: E402

FOLDED = ("goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick", "park",
          "goto above_place", "run descend_place", "run release_place", "run lift_place", "park")
HELD = {"run lift_pick", "park#0", "goto above_place", "run descend_place"}
STEP_M, ITEM = 0.02, (0.0, 0.048)  # a 90 mm box at the TCP, as a ball around its middle


def command_frames(library: dict, command: str, target: list) -> list:
    """The frames chunk_runner would play for this command, built by the same functions."""
    chunks, closed, fps = library["chunks"], library["gripper_closed"], library["fps"]
    transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None
    speed = library.get("transit_speed", 0.85)
    verb, *rest = command.split()
    if verb == "goto":
        return transit_path(target, chunks[rest[0]][0], closed, fps, transit, speed)
    if verb == "park":
        return park_path(target, chunks["home"][-1], closed, fps, transit, speed)
    return chunks[rest[0]]


def segments_of(library: dict, kin, rigid: tuple, piece_s: float = 0.0, home_pan: float | None = None, tip_m: float = 0.0) -> list:
    """One segment per command, or per `piece_s` seconds of it. `home_pan` tries the fold turned aside (a candidate, not on the arm)."""
    library = {**library, "chunks": dict(library["chunks"])}
    if home_pan is not None:
        library["chunks"]["home"] = [[home_pan, *library["chunks"]["home"][-1][1:]]]
    out, target, parks = [], list(library["chunks"]["home"][-1]), 0
    for command in FOLDED:
        frames = command_frames(library, command, target)
        label = f"park#{parks}" if command == "park" else command
        parks += command == "park"
        item = ITEM if label in HELD else None
        size = int(piece_s * library["fps"]) or len(frames)
        for start in range(0, len(frames), size):
            # tip_m 0: the kinematics already end at the TCP (ROSY_OMX_TCP_X_M)
            poses = [moved(capsules(kin, [norm_to_rad(v) for v in f[:5]], fingertip_m=tip_m, item=item), rigid)
                     for f in frames[start:start + size + 1]]
            out.append(Segment(label, min(size, len(frames) - start) / library["fps"], thinned(poses, STEP_M)))
        target = list(frames[-1])
    return out


_GRID_PTS_A = tuple((x, y, 1.0) for x in (0.05, 0.1, 0.15, 0.2) for y in (-0.05, 0.05, 0.1, 0.15))


def rigid_of(cal_a: dict, cal_b: dict, site_a: str, site_b: str) -> tuple:
    """arm_a's frame to arm_b's, through the top camera both maps share (a homography maps a pixel to the arm's x, y)."""
    import numpy as np

    to_pixel_a = np.array(_inv3x3(cal_a["sites"][site_a]["homography"]))
    h_b = np.array(cal_b["sites"][site_b]["homography"])
    pts_a = np.asarray(_GRID_PTS_A, dtype=float)
    pixels = pts_a @ to_pixel_a.T
    pixels /= pixels[:, 2:3]
    pts_b = pixels @ h_b.T
    pts_b = pts_b[:, :2] / pts_b[:, 2:3]
    return rigid_between(pts_a[:, :2], pts_b)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", nargs=2, required=True, metavar=("CELL", "LIBRARY"))
    ap.add_argument("--b", nargs=2, required=True, metavar=("CELL", "LIBRARY"))
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--piece-s", type=float, default=10.0, help="split each command into pieces this long; 0 keeps whole commands")
    ap.add_argument("--home-pan-a", type=float)
    ap.add_argument("--home-pan-b", type=float)
    args = ap.parse_args(argv)
    cells = [json.loads(Path(p).read_text()) for p in (args.a[0], args.b[0])]
    libraries = [json.loads(Path(p).read_text()) for p in (args.a[1], args.b[1])]
    calibrations = [json.loads(Path(c["calibration_path"]).read_text()) for c in cells]
    kin, _, _ = load_kinematics(None)
    rigid = rigid_of(calibrations[0], calibrations[1], "pallet", "pallet")
    a = segments_of(libraries[0], kin, rigid, args.piece_s, args.home_pan_a)
    b = segments_of(libraries[1], kin, (0.0, 0.0, 0.0), args.piece_s, args.home_pan_b)
    schedule, meets = plan(a, b, args.margin), rendezvous(a, b, args.margin)
    print(json.dumps({
        "rigid_a_to_b": [round(v, 4) for v in rigid],
        "home_gap_m": round(clearance(a[0].poses[:1], b[0].poses[:1]), 3),
        "closest_any_time_m": round(min(clearance(x.poses, y.poses) for x in a for y in b), 3),
        "one_after_other_s": round(sum(s.duration_s for s in a + b), 1),
        "free_flow_s": round(max(sum(s.duration_s for s in x) for x in (a, b)), 1),
        "makespan_s": schedule and schedule["makespan_s"],
        "barrier_meets": meets and {"count": len(meets["meets"]), "makespan_s": meets["makespan_s"]},
        "steps": schedule and [{"a": a[s["a"]].name if s["a"] is not None else None,
                                "b": b[s["b"]].name if s["b"] is not None else None} for s in schedule["steps"]],
    }, indent=1))
    return 0 if schedule else 1


if __name__ == "__main__":
    raise SystemExit(main())
