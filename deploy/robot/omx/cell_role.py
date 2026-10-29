#!/usr/bin/env python3
"""Supply arm S's role as code: look at every site, choose the next carry by the role's priorities, run it.

The role (user, 2026-10-29): the Pinky tray is where containers come and go.
  load      Pinky -> belt      what stands on the Pinky goes onto the conveyor
  retrieve  belt -> Pinky      a container on the belt comes back to the Pinky
  rescue    floor -> Pinky     a container that fell (or was left) on the floor is picked up and put back
Rescue comes first (a fallen container is in the way and lost from the flow), then load, then retrieve. The
priorities and the site of each step are data (ROLE below, or config["role"]); every choice is a "role" decision
row, and N failed carries in a row stop the loop for a person.

  cell_role.py --config cell-auto.json --catalog catalog.json [--rounds 6] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROLE = {"steps": [{"name": "rescue", "from": "floor", "to": "pinky"},
                  {"name": "load", "from": "pinky", "to": "belt"},
                  {"name": "retrieve", "from": "belt", "to": "pinky"}],
        "max_failures_in_a_row": 2}


def next_step(counts: dict, role: dict, last: str | None = None) -> dict | None:
    """The first step (in priority order) whose source site holds a usable container; None when nothing to do.
    load and retrieve alternate: right after a retrieve, load comes before another retrieve and the other way."""
    steps = [s for s in role["steps"] if counts.get(s["from"], 0) > 0]
    if not steps:
        return None
    if last in ("load", "retrieve") and len(steps) > 1 and steps[0]["name"] == last and steps[0]["name"] != "rescue":
        steps = steps[1:] + steps[:1]
    return steps[0]


def count_sites(cell, config: dict, calibration: dict, catalog: list) -> dict:
    """Usable containers seen per site (catalogue match, not tangled), from one top frame."""
    import cell_objects
    import cell_params as prm
    import cell_pivot

    img = cell.frame("top")
    out = {}
    for name, site in config["sites"].items():
        roi, record = site.get("auto_roi"), cell_pivot.map_record(calibration, name)
        if not roi or record is None or "surface_z" not in site:
            continue
        objs = cell_objects.detect(img, roi, record, config["cameras"]["top"], catalog, site["surface_z"],
                                   config.get("params"), site.get("surface_px"), site.get("surface_lab"))
        out[name] = sum(1 for o in objs if o.get("matched") and not o.get("tangled"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true", help="observe and decide only")
    args = ap.parse_args(argv)
    import cell_decisions as cd
    import cell_objects
    import cell_params as prm
    import cell_pipeline as cp
    import cell_task_runner as tr

    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["params"] = prm.load(config.get("params_path"))["values"]
    role = config.get("role") or ROLE
    calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text())
    catalog = cell_objects.load_catalog(args.catalog)
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    work = Path(config["work_dir"]).expanduser()
    (work / "role").mkdir(parents=True, exist_ok=True)
    cd.start(work / "decisions.jsonl", knowledge=config.get("knowledge"))
    last, failures, log = None, 0, []
    for round_no in range(args.rounds):
        counts = count_sites(cell, config, calibration, catalog)
        step = next_step(counts, role, last)
        cd.emit("role", {"counts": counts, "last": last, "failures_in_a_row": failures},
                [s["name"] for s in role["steps"]], step and step["name"], "rule",
                "priority order with load/retrieve alternating" if step else "nothing to carry")
        row = {"round": round_no, "counts": counts, "step": step and step["name"]}
        if step is None or args.dry_run:
            log.append(row)
            break
        carry = tr.run_carry(args.config, args.catalog, config["sites"], step["from"], step["to"], work / "role")
        row["result"] = carry["result"]
        log.append(row)
        print(json.dumps(row), flush=True)
        last = step["name"]
        failures = 0 if carry["result"] == "placed" else failures + 1
        if failures >= role.get("max_failures_in_a_row", 2):
            row["stopped"] = f"{failures} failed carries in a row: a person looks"
            break
        time.sleep(1)
    print(json.dumps({"rounds": log}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
