#!/usr/bin/env python3
"""Close the arm's own position error at the hover before a descent, from FK alone (no camera).

2026-10-29: over a floor container 0.17 m out, the arm hovered 8 mm short of the commanded xy, repeatably (P-only
joints under gravity), and the open jaws came down on the box top (contact at z 0.037, the box top). The map bias is
measured against the arm's actual FK pose, so it never includes this error. Here: read the hovering pose, FK it, and
if it is off, re-plan the pick by that offset and hover again (feedforward), up to reach.max_iter times.
"""
from __future__ import annotations

import math

import cell_params as prm


def fk_xy(state: list) -> tuple:
    from grasp_planner import load_kinematics, norm_to_rad

    kin, _, _ = load_kinematics(None)
    k = kin.fk([norm_to_rad(v) for v in state[:5]])
    return k.x, k.y


def correct(cell, aim_xy, replan, params=None, fk=fk_xy) -> dict:
    """{verdict: pass|refuse, dx_mm, dy_mm, total_mm, iterations}; dx/dy is the offset added to the pick."""
    tol, top = prm.get(params, "reach.tol_mm"), prm.get(params, "reach.max_mm")
    dx = dy = 0.0
    rows = []
    for i in range(int(prm.get(params, "reach.max_iter")) + 1):
        status = cell.act("state")
        x, y = fk(status["state"])
        ex, ey = 1000 * (aim_xy[0] - x), 1000 * (aim_xy[1] - y)
        rows.append({"iteration": i, "error_mm": [round(ex, 1), round(ey, 1)]})
        if math.hypot(ex, ey) <= tol:
            return {"verdict": "pass", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(math.hypot(dx, dy), 1), "iterations": rows}
        if i == int(prm.get(params, "reach.max_iter")) or math.hypot(dx + ex, dy + ey) > top:
            break
        dx, dy = dx + ex, dy + ey
        for command in (f"load {replan(dx, dy)}", "goto above_pick"):
            if not cell.act(command).get("ok"):
                rows[-1]["why"] = f"{command.split()[0]} refused"
                return {"verdict": "refuse", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(math.hypot(dx, dy), 1), "iterations": rows}
    return {"verdict": "refuse", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(math.hypot(dx, dy), 1), "iterations": rows}


def hook(config: dict, cell, target: dict, write_library):
    """The callable transfer_folded runs after `goto above_pick`, or None when reach.enabled is 0."""
    params = config.get("params")
    if not prm.get(params, "reach.enabled"):
        return None
    from pathlib import Path

    work = Path(config["work_dir"]).expanduser()

    def replan(dx_mm, dy_mm):
        pick = dict(target["pick"], x=round(target["pick"]["x"] + dx_mm / 1000, 4), y=round(target["pick"]["y"] + dy_mm / 1000, 4))
        return write_library(config, pick, target["place"], work / "reach-replan.json")

    return lambda: correct(cell, (target["pick"]["x"], target["pick"]["y"]), replan, params)


def chain(*hooks):
    """Run the hover hooks in order (reach, then wrist); the first refusal stops; the last answer otherwise."""
    live = [h for h in hooks if h is not None]
    if not live:
        return None

    def run():
        out = None
        for h in live:
            out = h()
            if out["verdict"] == "refuse":
                return out
        return out
    return run
