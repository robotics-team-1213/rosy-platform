#!/usr/bin/env python3
"""A servo ramp test at the folded home: each body joint in turn ramps out by `units`, holds, ramps back and holds, the
others still, through the running chunk_runner (guard on). Recorded episodes move every joint at once; one joint alone
separates its kp and kv from the others' (omx_sysid.py servo reads the runner trace). The library loader caps frames at
the guard's 5 units/s, so this is a ramp at 0.85 of that, not a step: armature stays out of reach.

  cell_step.py --config cell-auto.json [--units 2] [--hold-s 2] (--dry-run | --commissioning --person-at-switch)

Each ramp leaves the folded arm one joint `units` (1.8 deg each) off home; it moves only as a supervised trial (D-911).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_pipeline as cp  # noqa: E402

MAX_UNITS = 4.0     # 7.2 deg off home at most: the folded arm stays inside its own footprint
SPEED = 0.85 * 5.0  # units/s, the share of GUARD_UNITS_PER_S chunk_library admits for streamed frames


def step_library(plan: dict, units: float, hold_s: float) -> dict:
    from grasp_planner import NAMES
    if not 0 < units <= MAX_UNITS:
        raise SystemExit(f"--units must be in (0, {MAX_UNITS}]")
    fps, grip = plan["fps"], plan["grip_closed"]
    home = [round(x, 3) for x in plan["home"]] + [grip]
    ramp = max(2, round(units / SPEED * fps) + 1)
    hold = max(1, round(hold_s * fps))
    chunks = {"home": [home]}
    for j in range(5):
        def at(f):
            return [round(h + (units * f if i == j else 0.0), 3) for i, h in enumerate(home)]
        out = [at(k / (ramp - 1)) for k in range(ramp)]
        chunks[f"step_j{j + 1}"] = out + [out[-1]] * hold + out[::-1] + [home] * hold
    return {"schema": "rosy.omx-chunk-library.v1", "names": NAMES, "fps": fps, "gripper_closed": grip, "chunks": chunks,
            "transit": plan.get("transit", {}), "transit_speed": plan.get("transit_speed", 0.85)}


def run_steps(cell, library_path: Path) -> dict:
    steps = []
    for command in [f"load {library_path}", "goto home"] + [f"run step_j{j}" for j in range(1, 6)]:
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if not status.get("ok"):
            if not command.startswith("load"):
                steps.append({"command": "park", "ok": cell.act("park").get("ok")})
            return {"result": "stopped", "at": command, "steps": steps}
    steps.append({"command": "park", "ok": cell.act("park").get("ok")})
    return {"result": "stepped", "steps": steps}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--units", type=float, default=2.0)
    ap.add_argument("--hold-s", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial of these ramps (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    if args.commissioning != args.person_at_switch:
        raise SystemExit("--commissioning needs --person-at-switch (and the other way round)")
    if not (args.dry_run or args.commissioning):
        raise SystemExit("a ramp test moves the arm outside the D-911 gate: --dry-run, or --commissioning --person-at-switch")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    plan = json.loads(Path(config["plan_path"]).expanduser().read_text())
    work = Path(config["work_dir"]).expanduser() / "step"
    work.mkdir(parents=True, exist_ok=True)
    lib = work / f"{time.strftime('%Y%m%d-%H%M%S')}-step.json"
    lib.write_text(json.dumps(step_library(plan, args.units, args.hold_s)))
    out = {"library": str(lib), "units": args.units, "hold_s": args.hold_s}
    if args.dry_run:
        out["result"] = "planned"
    else:
        out.update(run_steps(cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"]), lib))
    (lib.with_suffix(".result.json")).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "steps"}))
    return 0 if out["result"] in ("stepped", "planned") else 1


if __name__ == "__main__":
    sys.exit(main())
