#!/usr/bin/env python3
"""Carry catalogue objects from one site to another, one cell_auto_pick carry after another, until the source has
nothing left, a carry does not end placed, or --max carries are done (2026-11-02).

Every carry goes through the reviewed operating envelope (D-911): a carry that is not a reviewed task is held before
motion, and that ends the run. There is no --commissioning here, since a supervised trial is one carry and never
an automatic cycle (D-911 4); use cell_auto_pick for that. The carry count is the reviewer's, so --max has no
default. The top view is checked before each carry (a dark or blinded camera ends the run before motion).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_auto_pick as ap  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_objects  # noqa: E402


def carry(run_one, maximum: int, dark=lambda: []) -> dict:
    """Up to `maximum` carries; `run_one()` is one run_auto result. Stops at the first one not placed."""
    carries = []
    for _ in range(maximum):
        problems = dark()
        if problems:
            return {"carries": carries, "placed": len(carries), "result": "refused: " + "; ".join(problems)}
        result = run_one()
        if result["result"] != "placed":
            last = (result.get("attempts") or [{}])[-1]
            empty = last.get("observed") == 0 and last.get("error") == "no usable object"
            return {"carries": carries, "placed": len(carries), "last": result,
                    "result": "source empty" if empty else result["result"]}
        carries.append(result)
    return {"carries": carries, "placed": len(carries), "result": f"done: {maximum} carries"}


def main(argv=None):
    import cell_choices
    import cell_preflight
    from cell_auto_setup import open_cell, parser

    p = parser(__doc__)
    p.add_argument("--max", type=int, required=True, help="the reviewed number of carries in this run")
    args = p.parse_args(argv)
    if args.max < 1:
        raise SystemExit("--max must be at least 1")
    config, cell, calibration_path, work = open_cell(args)
    catalog, choices = cell_objects.load_catalog(args.catalog), cell_choices.Choices(work / "choices.json")
    if args.dry_run:  # one plan: nothing moves, so a second carry would see the same scene
        args.max = 1
    result = carry(lambda: ap.run_auto(cell, config, cal.load(calibration_path), calibration_path, catalog, args.roi,
                                       args.source, args.dest, work, choices, args.dry_run),
                   args.max, dark=lambda: cell_preflight.ready(cell.frame, config))
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["result"].startswith(("done", "source empty")) or result.get("last", {}).get("result") == "planned" else 1


if __name__ == "__main__":
    sys.exit(main())
