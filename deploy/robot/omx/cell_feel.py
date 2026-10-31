#!/usr/bin/env python3
"""Feel instead of look: when a grasp comes up empty, try again shifted along the closing axis and let the gripper's
own holding verdict decide (2026-10-29). Needs no camera, holds for any box size; the camera-based check is cell_pinch.
"""
from __future__ import annotations

import math
from pathlib import Path

import cell_params as prm


def feel_hook(config: dict, cell, target: dict, write_library):
    """Feel instead of look (feel.enabled): an empty grasp tries again shifted along the closing axis by +s, -s, +2s,
    -2s (feel.step_mm, feel.tries), each a lift, a re-plan, a descent and a grasp; the gripper's own holding verdict
    decides, for any box size. 2026-10-29: the floor 1-cell came up empty with the box 1-2 cm outside one finger while
    the wrist camera, turned away, could not see the fingers. Each descent follows the same reach correction as the
    first: without it the descent started with little lag, the runner's contact limit stayed at 1.5 and the normal
    descent lag of 1.6-1.7 read as a contact six times in a row, where the first descent peaked at 1.9 untouched
    (2026-10-29). Returns run -> last status, or None when off."""
    import cell_reach

    params = config.get("params")
    if not prm.get(params, "feel.enabled"):
        return None
    work = Path(config["work_dir"]).expanduser()
    c = math.radians(target["pick"]["yaw_deg"] + prm.get(params, "auto.closing_theory_deg"))
    step = prm.get(params, "feel.step_mm")
    offsets = [k * step * sgn for k in (1, 2, 3) for sgn in (1, -1)][:int(prm.get(params, "feel.tries"))]

    def search(run):
        status = {"ok": True, "holding": False}
        for k, off in enumerate(offsets):
            pick = dict(target["pick"], x=round(target["pick"]["x"] + off * math.cos(c) / 1000, 4),
                        y=round(target["pick"]["y"] + off * math.sin(c) / 1000, 4))
            library = write_library(config, pick, target["place"], work / f"feel-{k}.json")
            reach = cell_reach.hook(config, cell, dict(target, pick=pick), write_library)
            for command in ("run lift_pick", f"load {library}", "goto above_pick", "reach", "run descend_pick", "run grasp_pick"):
                if command == "reach":
                    if reach is not None and reach()["verdict"] == "refuse":
                        return {"ok": False, "error": "reach correction refused", "feel_mm": off}
                    continue
                status = run(command)
                if status.get("contact") or not status.get("ok"):
                    return {**status, "feel_mm": off}
            if status.get("holding"):
                return {**status, "feel_mm": off}
        return status
    return search
