#!/usr/bin/env python3
"""CLI entrypoint for `cell_two_arm.py` (`cell_two_arm_cli.py`)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None, *, two=None) -> int:
    import cv2
    import cell_calibration as cal
    import cell_pipeline as cp
    import cell_pivot
    import cell_zones
    from cell_auto_setup import load_config
    if two is None:
        import cell_two_arm as two

    ap = argparse.ArgumentParser(description=two.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", nargs="+", required=True, metavar=("CELL", "LIBRARY"))
    ap.add_argument("--b", nargs="+", required=True, metavar=("CELL", "LIBRARY"))
    ap.add_argument("--margin", type=float, default=0.05)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fail-at", help="ARM:SEGMENT, act as a failure after it: tries the coupled stop")
    ap.add_argument("--plan-only", action="store_true", help="print the schedule; nothing moves")
    ap.add_argument("--carry", action="store_true", help="one library per arm, the whole carry with the box, not the hovers")
    ap.add_argument("--commissioning", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    if not args.plan_only and not (args.commissioning and args.person_at_switch):
        raise SystemExit("this moves two arms: --commissioning --person-at-switch (D-911)")
    fail_at = None
    if args.fail_at:
        name, segment = args.fail_at.split(":")
        fail_at = (name, int(segment))
    jobs = dict(a=args.a, b=args.b)
    if args.carry and any(len(jobs[n]) != 2 for n in two.ORDER):
        raise SystemExit("--carry takes one library per arm")
    configs = {n: two.attest(load_config(Path(jobs[n][0])), args.commissioning and args.person_at_switch)
               for n in two.ORDER}
    calibrations = {
        n: cell_pivot.with_site_maps(configs[n], cal.load(Path(configs[n]["calibration_path"]).expanduser()))
        for n in two.ORDER
    }
    libraries = {n: [(p, json.loads(Path(p).read_text())) for p in jobs[n][1:]] for n in two.ORDER}
    for n in two.ORDER:
        zones = cell_zones.Zones(configs[n], calibrations[n])
        for path, library in libraries[n]:
            for point in [library["source"][k] for k in (("pick", "place") if args.carry else ("pick",))]:
                if zones.zone_of((point["x"], point["y"])) != configs[n]["zone_side"]:
                    raise SystemExit(f"{path}: outside arm {n}'s own zone ({configs[n]['zone_side']})")
    kin, _, _ = two.load_kinematics(None)
    rigids = {"a": two.rigid_of(calibrations["a"], calibrations["b"], "pallet", "pallet"), "b": (0.0, 0.0, 0.0)}
    tips = {n: float(configs[n].get("fingertip_m", 0.0)) for n in two.ORDER}
    routes = {
        n: two.carry_route(*libraries[n][0], kin, rigids[n], tips[n])
        if args.carry else two.route(libraries[n], kin, rigids[n], tips[n])
        for n in two.ORDER
    }
    schedule = two.plan(routes["a"][0], routes["b"][0], args.margin)
    names = {n: [s.name for s in routes[n][0]] for n in two.ORDER}
    print(json.dumps({"schedule": schedule, "segments": names}, indent=1))
    if schedule is None:
        print("refused: no order keeps the margin")
        return 1
    two.admit(schedule, libraries)
    if args.plan_only:
        return 0
    cells = two.open_cells(configs, cp.FifoCell)
    away = two.away_from_home(cells, {n: libraries[n][0][1] for n in two.ORDER})
    if away:
        raise SystemExit(f"not folded home: arm {', '.join(away)}: the schedule was cleared from home")
    run = args.out / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=False)
    lock, stream = threading.Lock(), (run / "log.jsonl").open("w")

    def log(row):
        with lock:
            stream.write(json.dumps({"t": round(time.time(), 3), **row}) + "\n")
            stream.flush()
            print(row, flush=True)

    sequences = {n: two.FOLDED if args.carry else tuple(c for sends in routes[n][1] for c in sends) for n in two.ORDER}
    cells = two.open_gates(cells, configs, calibrations, libraries, sequences, run)
    before = cells["b"].frame("top")
    cv2.imwrite(str(run / "before.jpg"), before)
    moved_out = two.execute(cells, {n: routes[n][1] for n in two.ORDER}, schedule["steps"], fail_at, log)
    outcome = {**moved_out, "fold": None}
    if moved_out["failed"]:
        outcome["fold"] = two.safe_fold(
            cells, {n: libraries[n][-1][1] for n in two.ORDER}, kin, rigids, tips, args.margin, log, moved_out)
    elif args.carry:
        outcome["still_holding"] = two.still_holding(cells, {n: libraries[n][-1][1] for n in two.ORDER})
    after = cells["b"].frame("top")
    cv2.imwrite(str(run / "after.jpg"), after)
    outcome["scene_moved"] = two.scene_moved(before, after)
    log({"result": outcome})
    ok = (not moved_out["failed"] and not outcome.get("still_holding")) or (
        fail_at is not None and moved_out["failed"]["error"] == "injected" and outcome["fold"]["folded"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
