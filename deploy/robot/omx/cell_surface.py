#!/usr/bin/env python3
"""Measure a site's surface height by touch: closed jaws go straight down over the site until the runner's soft
contact holds them, the held pose's FK z is the surface, then back out and fold home. No contact before `z_to` is
a refusal (nothing there, or the site is lower than thought). Placing needs `surface_z`; the belt and Pinky sites
only had grasp heights taught for another box (2026-10-28).

  cell_surface.py --config cell-auto.json --site belt [--z-from 0.10 --z-to 0.010] [--write]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_pipeline as cp  # noqa: E402


def probe_library(plan: dict, x: float, y: float, yaw: float, z_from: float, z_to: float) -> dict:
    from grasp_planner import NAMES, Planner, norm_to_rad

    p = dict(plan, approach_m=z_from - z_to, descend_m_s=0.010)
    planner = Planner(p)
    chunks, _ = planner.site("probe", {"x": x, "y": y, "z": z_to, "yaw_deg": yaw}, p["grip_closed"],
                             p["grip_closed"], norm_to_rad(p["home"][4]))
    home = [round(v, 3) for v in p["home"]] + [p["grip_closed"]]
    return {"schema": "rosy.omx-chunk-library.v1", "names": NAMES, "fps": p["fps"],
            "chunks": {"above_probe": chunks["above_probe"], "descend_probe": chunks["descend_probe"], "home": [home]},
            "gripper_closed": p["grip_closed"], "transit": p.get("transit", {}),
            "transit_speed": p.get("transit_speed", 0.85)}


def fk_z(state: list) -> float:
    from grasp_planner import load_kinematics, norm_to_rad

    kin, _, _ = load_kinematics(None)
    return kin.fk([norm_to_rad(v) for v in state[:5]]).z


def touch(cell, library_path: Path, fk=fk_z) -> dict:
    """goto above, descend; a contact hold is the surface. Always ends folded home (or reports why not)."""
    steps = []
    for command in (f"load {library_path}", "goto above_probe", "run descend_probe"):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if status.get("contact"):
            z = fk(status["state"])
            for after in ("retreat", "park"):
                steps.append({"command": after, "ok": cell.act(after).get("ok")})
            return {"result": "touched", "surface_z": round(z, 4), "error": status.get("error"), "steps": steps}
        if not status.get("ok"):
            if not status.get("fault") and not command.startswith("load"):
                steps.append({"command": "park", "ok": cell.act("park").get("ok")})
            return {"result": "fault" if status.get("fault") else "refused", "at": command, "steps": steps}
    steps.append({"command": "park", "ok": cell.act("park").get("ok")})
    return {"result": "no contact", "steps": steps}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--site", required=True)
    ap.add_argument("--z-from", type=float, default=0.10)
    ap.add_argument("--z-to", type=float, default=0.010)
    ap.add_argument("--write", action="store_true", help="store the measured surface_z in the config's site")
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    plan = json.loads(Path(config["plan_path"]).expanduser().read_text())
    site = config["sites"][args.site]
    x, y = site["place"]
    work = Path(config["work_dir"]).expanduser()
    path = work / f"surface-{args.site}.library.json"
    path.write_text(json.dumps(probe_library(plan, x, y, site["yaw_deg"], args.z_from, args.z_to)))
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    out = dict(touch(cell, path), site=args.site, xy=[x, y], measured=time.strftime("%Y-%m-%d %H:%M"))
    (work / f"surface-{args.site}.json").write_text(json.dumps(out, indent=1))
    if args.write and out["result"] == "touched":
        site["surface_z"] = out["surface_z"]
        args.config.write_text(json.dumps(config, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "steps"}))
    return 0 if out["result"] == "touched" else 1


if __name__ == "__main__":
    sys.exit(main())
