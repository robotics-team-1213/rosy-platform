#!/usr/bin/env python3
"""Look, then correct: at the hover the top camera finds the jaws and the box in the same image (2026-10-29).

Picks near the board missed by about 1 cm because the map bias changes with position (16.9 / 6.1 / 4.2 mm at regions
3.5-5.7 cm apart): any bias carried from elsewhere is a guess. A relative measurement does not need it. At the hover
the jaw mark is found by opening and closing the jaws (cell_pivot.mark_jaws, any background); the pivot circle of the
nearest region gives the mark's radius and phase around the TCP, so the TCP in the map's raw frame is the mark minus
that radius along yaw + phase. The box's raw position comes from the same map in the same patch of image, so the map's
local error is in both and cancels: box - TCP is the move. The new command is the runner's own command (FK of its
target joints) plus that move, so the arm's droop is corrected too: a first field run that set FK + move left y 4.4 mm
short three times (2026-10-29). Run last among the position hooks; up to look.max_iter looks, every one kept.
"""
from __future__ import annotations

import math
import time

import cell_params as prm
import cell_pivot


def tcp_from_mark(mark_raw, yaw_deg: float, region: dict):
    """The TCP in the map's raw frame from one jaw mark: the pivot circle put the mark at radius along yaw + phase."""
    a = math.radians(yaw_deg + region["phase_deg"])
    r = region["radius_mm"] / 1000
    return mark_raw[0] - r * math.cos(a), mark_raw[1] - r * math.sin(a)


def look(cell, config: dict, record: dict, site: str, target: dict, write_library, work, sleep=time.sleep,
         goto: str = "goto above_pick", name: str = "look-replan.json") -> dict:
    """Measure point - TCP at the hover and move the target there; verdict pass / refuse with every look kept.
    `target[\"object\"][\"raw_m\"]` is the raw point the TCP must stand over: a box to pick, or a push's start."""
    params, region = config.get("params"), target.get("bias_region") or {}
    box = target["object"]["raw_m"]
    rows, total = [], 0.0
    for i in range(int(prm.get(params, "look.max_iter")) + 1):
        status = cell.act("state")
        state, commanded = status.get("state"), status.get("target")
        pixel = cell_pivot.mark_jaws(cell, config, sleep)
        if state is None or commanded is None or pixel is None:
            rows.append({"look": i, "seen": False})
            return {"verdict": "pass", "why": "jaw mark not seen: the plan stands", "looks": rows, "total_mm": round(total, 1)}
        x, y, z, yaw = cell_pivot.joints_tcp(state)
        tcp = tcp_from_mark(cell_pivot.mark_to_arm(record, config, site, pixel, z), yaw, region)
        d = (box[0] - tcp[0], box[1] - tcp[1])
        off = 1000 * math.hypot(*d)
        rows.append({"look": i, "mark_px": [round(v, 1) for v in pixel], "fk_m": [round(x, 4), round(y, 4)],
                     "box_minus_tcp_mm": [round(1000 * d[0], 1), round(1000 * d[1], 1)]})
        if off <= prm.get(params, "look.tol_mm"):
            return {"verdict": "pass", "looks": rows, "total_mm": round(total, 1)}
        if i == int(prm.get(params, "look.max_iter")) or total + off > prm.get(params, "look.max_total_mm"):
            return {"verdict": "refuse", "why": f"box still {off:.0f} mm from the jaws", "looks": rows, "total_mm": round(total, 1)}
        total += off
        cx, cy, _, _ = cell_pivot.joints_tcp(commanded)  # what the runner was told; the arm stands short of it
        target["pick"] = dict(target["pick"], x=round(cx + d[0], 4), y=round(cy + d[1], 4))
        library = write_library(config, target["pick"], target["place"], work / name)
        if not all(cell.act(c).get("ok") for c in (f"load {library}", goto)):
            return {"verdict": "refuse", "why": "re-plan refused", "looks": rows, "total_mm": round(total, 1)}
    return {"verdict": "refuse", "why": "no look left", "looks": rows, "total_mm": round(total, 1)}


def hook(config: dict, cell, target: dict, write_library, calibration: dict, site: str):
    """The look as the first hover hook (look.enabled), or None: off, no map, or no pivot circle for the box's region."""
    from pathlib import Path

    region = target.get("bias_region") or {}
    record = cell_pivot.map_record(calibration or {}, site)
    if not prm.get(config.get("params"), "look.enabled") or record is None or "radius_mm" not in region:
        return None
    work = Path(config["work_dir"]).expanduser()
    return lambda: look(cell, config, record, site, target, write_library, work)

