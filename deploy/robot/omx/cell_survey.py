"""`cell_pipeline --stage survey`: where the jaws end up over a box the cameras located (2026-10-28).

Locate the box, go above it without descending, mark the jaws in the top view by closing and opening them
(the coarse map's method), park. The jaws' offset from the box is the whole reach error at that box
position, map plus arm; the attempt row keeps the measured joints, and cell_attempts.arm_error_mm turns
them into the arm's own share. Offset minus arm error is what the map got wrong there. Never descends, so
it can map a whole tray of positions without touching the box or the Pinky frame.
"""
from __future__ import annotations

import time
from pathlib import Path

import cell_attempts
import cell_calibration as cal
import cell_pipeline as cp
from cell_observe import keep, locate, record_key


def survey(cell, config: dict, calibration: dict, site: str, work: Path, choices=None) -> dict:
    t_start, plan = time.time(), config["plan"]
    found = locate(cell, config, calibration, site)
    tried = {"locate": found}

    def done(result: str) -> dict:
        cell_attempts.record(config, calibration, site, site, 0, tried, t_start, choices)
        return {"result": result, **tried}

    if not found["found"]:
        return done("box not seen")
    yaw_pick, yaw = cp.grasp_yaw(config, calibration, site, found, choices)
    tried["grasp_yaw"] = {"choice": yaw_pick, "yaw_deg": yaw}
    pick = cp.target(config, site, found["arm_m"], yaw)
    tried["plan"] = {"pick": pick, "place": pick}
    try:
        library = cp.write_library(config, pick, pick, work / f"survey-{site}.json")
    except SystemExit as exc:
        tried["plan_error"] = str(exc)[:200]
        return done("plan refused")
    steps = []
    tried["transfer"] = {"result": "surveyed", "steps": steps}
    for command in (f"load {library}", "goto above_pick"):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if not status.get("ok"):
            if not status.get("fault"):
                cell.act("park")  # a refused step leaves the arm holding: fold it
            tried["transfer"] = {"result": "fault" if status.get("fault") else "refused", "at": command, "steps": steps}
            return done(tried["transfer"]["result"])
    closed = choices.best("gripper.closed@follower", plan["grip_closed"]) if choices else plan["grip_closed"]
    frames = []
    for value in (closed, plan["grip_open"]):
        cp.grip_to(cell, value)
        frames.append(cell.frame("top"))
    keep(f"survey-{site}-closed", frames[0])
    keep(f"survey-{site}-open", frames[1])
    cell.act("park")
    jaws = cal.jaw_pixel(*frames)
    tried["survey"] = {"jaws_px": None if jaws is None else [round(v, 1) for v in jaws]}
    top = next((e for e in found["estimates"] if e["camera"] == "top"), None)
    if jaws is not None and top is not None:  # both pixels to the map's fitting height, then into millimetres
        record = calibration["sites"][record_key(site, "top")]
        camera, fit_z = config["cameras"]["top"], record.get("z_view", config["sites"][site]["z"])
        jaw = cal.to_arm(record["homography"], cal.parallax(jaws, pick["z"] + plan["approach_m"], fit_z, camera))
        box = cal.to_arm(record["homography"], cal.parallax(top["pixel"], config["sites"][site]["z"], fit_z, camera))
        tried["survey"]["offset_mm"] = [round(1000 * (j - b), 1) for j, b in zip(jaw, box)]
    return done("surveyed")


def stage(cell, config: dict, calibration_path: Path, site: str, work: Path) -> dict:
    """Survey with the map the pipeline would use now: the fine map, else the coarse one."""
    import cell_choices

    calibration = cal.load(calibration_path)
    if record_key(site, "top") not in calibration["sites"] and f"{site}~coarse" in calibration["sites"]:
        calibration["sites"][site] = calibration["sites"][f"{site}~coarse"]
    return survey(cell, config, calibration, site, work, cell_choices.Choices(work / "choices.json"))
