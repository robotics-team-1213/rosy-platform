#!/usr/bin/env python3
"""Commissioning, calibration, coarse-map, reset, and recovery stages for `cell_pipeline.py` (`cell_pipeline_stages.py`).

Split from `cell_pipeline.py` (D-766 2) so both the core transfer/move/run executor (`cell_pipeline.py`)
and the supervised commissioning/calibration stages (`cell_pipeline_stages.py`) stay well below 380 lines.
All functions resolve `cell_pipeline` helpers late via `_cp()` so test monkeypatches on `cell_pipeline.*`
continue to work identically.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402
from cell_observe import fixed_cameras, maps, record_key  # noqa: E402


def _cp():
    import cell_pipeline
    return cell_pipeline


def calibrate(cell, config: dict, site: str, work: Path, log=print, calibration: dict | None = None) -> dict:
    """Carry the box from the start through grid points on `site`; return the fitted records. Points whose
    box would not sit on the flat zone are skipped before the arm goes there."""
    if config.get("_commissioning") != {"person_at_switch": True}:
        return {"result": "held: supervised commissioning required"}
    calibration = calibration or {"sites": {}}
    import cell_perception as cp_perc
    cp = _cp()

    s = config["sites"][site]
    start = (s["start"][0], s["start"][1])
    measured = {camera: [] for camera in fixed_cameras(config)}
    hovers = []

    def measure(point):
        seen = {}
        for camera in measured:
            box = cp.see(cell.frame(camera), config["profiles"][camera], site)
            if box.get("found"):
                measured[camera].append(((box["cx"], box["cy"]), point))
            seen[camera] = {k: box.get(k) for k in ("found", "cx", "cy", "yaw")}
        log({"measure": point, "seen": seen})
        return any(v["found"] for v in seen.values())

    def hover():
        box = cp_perc.wrist_box(cell.frame("wrist"), config["profiles"]["top"])
        if box.get("found"):
            hovers.append((box["cx"], box["cy"], box["area"]))
        return {"aligned": None}

    if not measure(start):
        return {"result": "box not seen at the start point"}
    current, results = start, []
    for i, point in enumerate(cp.grid_points(config, calibration, site)):
        if point == current:
            continue
        if cp.on_flat(config, calibration, site, point) is False:
            results.append({"point": point, "skipped": "the box would not sit on the flat zone"})
            continue
        try:
            library = cp.write_library(
                config,
                cp.target(config, site, current),
                cp.target(config, site, point, place=True),
                work / f"calibrate-{site}-{i}.json",
            )
        except SystemExit as exc:
            results.append({"point": point, "skipped": str(exc)[:160]})
            continue
        moved = cp.transfer(cell, library, hover, config=config, calibration=calibration)
        results.append({"point": point, "transfer": moved["result"], "at": moved.get("at")})
        if moved["result"] != "placed":
            return {"result": "stopped", "transfers": results}
        current = point
        measure(point)
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = {
        record_key(site, camera): cal.site_record(points, when)
        for camera, points in measured.items()
        if len(points) >= cal.MIN_POINTS
    }
    if not records:
        return {"result": "too few measured points", "transfers": results}
    top = records.get(record_key(site, "top"))
    if hovers and top is not None:
        xs, ys, areas = zip(*hovers)
        spread = max(15.0, 3 * max(float(np.std(xs)), float(np.std(ys))))
        top["wrist"] = {
            "cx": round(float(np.mean(xs)), 1),
            "cy": round(float(np.mean(ys)), 1),
            "area": int(np.mean(areas)),
            "spread_px": round(spread, 1),
            "samples": len(hovers),
        }
    return {"result": "calibrated", "records": records, "transfers": results}


def scene(config: dict, source: str, dest: str, tried: dict) -> dict | None:
    """What a simulator needs to replay this attempt (cell_cases.from_row): box, jaw turn, place, outcome."""
    found, transfer_res = tried["locate"], tried.get("transfer") or {}
    if not found.get("found") or "grasp_yaw" not in tried or "transfer" not in tried:
        return None
    place = config["sites"][dest]["place"]
    return {
        "box_m": found["arm_m"],
        "box_turn_deg": found.get("turn_deg", 0.0),
        "grasp_turn_deg": round(tried["grasp_yaw"]["yaw_deg"] - config["sites"][source]["yaw_deg"], 1),
        "place": "belt" if dest == "belt" else place,
        "outcome": transfer_res.get("result"),
        "at": transfer_res.get("at"),
    }


def grip_to(cell, value: float, timeout_s: float = 10.0, sleep=time.sleep, clock=time.monotonic) -> bool:
    """`grip` only sets the target; the guard moves the jaws at 10 deg/s. Wait until they are there, or
    until they stop short and stay."""
    if not cell.act(f"grip {value}").get("ok"):
        return False
    deadline, last, still_since = clock() + timeout_s, None, None
    while clock() < deadline:
        state = cell.act("state").get("state")
        if state:
            now, jaw = clock(), state[5]
            if abs(jaw - value) < 1.5:
                return True
            still_since = (still_since or now) if last is not None and abs(jaw - last) < 0.2 else None
            # longer than the session's state refresh: arm_s read the jaws about once a second (2026-11-13), and 0.6 s
            # took a jaw still opening as stopped, so every jaw mark of a remap compared two frames of unmoved jaws
            if still_since is not None and now - still_since >= 1.5:
                return True
            last = jaw
        sleep(0.2)
    return False


def coarse_map(cell, config: dict, site: str, work: Path, choices, log=print, around=None) -> dict:
    """A first map before any box has been carried: the empty jaws visit known arm points high above the surface."""
    if config.get("_commissioning") != {"person_at_switch": True}:
        return {"result": "held: supervised commissioning required"}
    cp = _cp()
    c, s = config["coarse"], config["sites"][site]
    points = c["points"]
    if around is not None:
        points = cal.grid(around, c.get("local_spacing_m", 0.03), 3)
        points.pop(4)
    closed_name = "gripper.closed@follower"
    choices.offer(closed_name, float(config["plan"]["grip_closed"]), "taught: plan grip_closed (leader units)")
    choices.offer(closed_name, float(c["grip_closed"]), "config: coarse grip_closed")
    grip_closed = choices.best(closed_name)
    marks = []
    for i, (x, y) in enumerate(points):
        view = {"x": x, "y": y, "z": round(c["z_view"] - config["plan"]["approach_m"], 4), "yaw_deg": s["yaw_deg"]}
        try:
            library = cp.write_library(config, view, view, work / f"coarse-{site}-{i}.json")
        except SystemExit as exc:
            log({"coarse": [x, y], "skipped": str(exc)[:120]})
            continue
        for command in (f"load {library}", "goto above_pick"):
            status = cell.act(command)
            if not status.get("ok"):
                return {"result": "stopped", "at": command, "error": status.get("error"), "fault": status.get("fault")}
        if not cp.grip_to(cell, grip_closed):
            return {"result": "stopped", "at": "grip closed"}
        jaw = (cell.act("state").get("state") or [None] * 6)[5]
        if jaw is not None and abs(jaw - grip_closed) >= 1.0:
            choices.offer(closed_name, round(jaw, 1), "measured: where the follower jaws stopped")
            choices.outcome(closed_name, grip_closed, False, f"asked {grip_closed}, jaws stopped at {jaw:.1f}")
            choices.outcome(closed_name, round(jaw, 1), True, "the jaws' own end")
            grip_closed = round(jaw, 1)
        closed = cell.frame("top")
        cp.keep(f"coarse-{i}-closed", closed)
        if not cp.grip_to(cell, c["grip_open"]):
            return {"result": "stopped", "at": "grip open"}
        opened = cell.frame("top")
        cp.keep(f"coarse-{i}-open", opened)
        jaws = cal.jaw_pixel(closed, opened)
        log({"coarse": [x, y], "jaws": jaws})
        if jaws is not None:
            marks.append((jaws, (x, y)))
    cell.act("park")
    if len(marks) < 4:
        return {"result": f"jaws seen at {len(marks)} points, need 4"}
    return {
        "result": "mapped",
        "record": {
            "homography": cal.fit(marks).round(9).tolist(),
            "z_view": c["z_view"],
            "coarse": True,
            "loo_error_mm": cal.loo_error_mm(marks) if len(marks) >= 5 else None,
            "points": [{"pixel": list(p), "arm_m": list(a)} for p, a in marks],
        },
    }


def start_reference(config: dict, site: str, choices) -> list:
    """Where the start looks in the top view for the top-down plan: the candidate with the best record."""
    taught = config["profiles"]["top"]["reference"]["top"]
    name = f"{site}.start_pixel@topdown"
    choices.offer(name, [taught["cx"], taught["cy"]], "taught: profile reference.top")
    return choices.best(name)


def at_start(cell, config: dict, site: str, choices) -> dict:
    cp = _cp()
    box = cp.see(cell.frame("top"), config["profiles"]["top"], site)
    ref, tol = cp.start_reference(config, site, choices), config["profiles"]["top"]["tolerance"]["box_px"]
    ok = bool(box.get("found")) and math.dist((box["cx"], box["cy"]), ref) <= tol
    return {"ok": ok, "box": {k: box.get(k) for k in ("found", "cx", "cy", "yaw")}, "reference": ref}


def reset(cell, config: dict, calibration: dict, site: str, work: Path, choices, seat=None, log=print,
          person_at_switch: bool = False) -> dict:
    """Put the box back where calibration and cycle A start, wherever it is on `site`, without a person."""
    cp = _cp()
    if cp.at_start(cell, config, site, choices)["ok"]:
        return {"result": "placed", "already": True}
    made = {}
    if not maps(calibration, site, "top"):
        coarse = cp.coarse_map(cell, config, site, work, choices, log)
        if coarse["result"] != "mapped":
            choices.save()
            return {"result": "stopped", "coarse": coarse}
        made = {f"{site}~coarse": coarse["record"]}
        calibration = dict(calibration, sites=dict(calibration["sites"], **made))
    moved = cp.move(cell, config, calibration, site, site, work, seat, choices=choices, person_at_switch=person_at_switch)
    if moved["result"] == "placed":
        box = cp.see(cell.frame("top"), config["profiles"]["top"], site)
        if box.get("found"):
            name, seen = f"{site}.start_pixel@topdown", [round(box["cx"], 1), round(box["cy"], 1)]
            tol = config["profiles"]["top"]["tolerance"]["box_px"]
            for candidate in choices.data["values"].get(name, []):
                choices.outcome(
                    name,
                    candidate["value"],
                    math.dist(candidate["value"], seen) <= tol,
                    f"arm placed the box at the start; seen at {seen}",
                )
            choices.offer(name, seen, "measured: the arm placed the box at the start")
            choices.outcome(name, seen, True, "measured right after the arm placed it")
    choices.save()
    check = cp.at_start(cell, config, site, choices)
    return {
        **moved,
        "result": "placed" if moved["result"] == "placed" and check["ok"] else moved["result"] if moved["result"] != "placed" else "placed off the start",
        "start": check,
        "remapped": {**made, **(moved.get("remapped") or {})},
    }


def grasp_yaw(config: dict, calibration: dict, site: str, found: dict, choices):
    """Which yaw the jaws take over the box: the site's own yaw, or that yaw turned by the top camera's reading."""
    name, base = f"{site}.grasp_yaw@topdown", config["sites"][site]["yaw_deg"]
    if choices is None:
        return "site", base
    choices.offer(name, "site", "taught: the site's yaw")
    choices.offer(name, "camera", "measured: the top camera's box edges")
    pick = choices.best(name)
    if pick == "site":
        return pick, base
    learned = (calibration["sites"].get(record_key(site, "top")) or {}).get("wrist") is not None
    cap = config.get("max_turn_deg", 45.0 if learned else 10.0)
    return pick, round(base + max(-cap, min(cap, found.get("turn_deg", 0.0))), 1)


def recover(cell, config: dict, site: str, work: Path, person_at_switch: bool) -> dict:
    """After the guard turned torque off mid-task, lift clear and put a held box at the start or fold home."""
    if not person_at_switch:
        return {"result": "refused", "error": "recover moves an arm the guard stopped: confirm a person at the switch"}
    cp = _cp()
    state = cell.act("state")
    if not state.get("ok"):
        return {"result": "stopped", "error": state.get("error")}
    current = abs(((state.get("health") or {}).get("current_ma") or [0] * 6)[5])
    holding = current >= config["plan"].get("hold_current_ma", 140)
    steps = [{"command": "state", "gripper_current_ma": current, "holding": holding}]
    if not holding:
        import cell_unwedge
        out = cell_unwedge.unwedge(cell, cell_unwedge.HOME, sleep=time.sleep if config.get("recover_settle_s", 3.0) else bool)
        return {"result": out["result"], "holding": False, "steps": steps + out.get("rows", [])}
    plan = [f"grip {config['plan']['grip_closed']}", config.get("recover_lift", "jog elbow_flex.pos -5 wrist_flex.pos 4")]
    if holding:
        here = state["state"]
        library = cp.write_library(
            config,
            cp.target(config, site, config["sites"][site]["start"]),
            cp.target(config, site, config["sites"][site]["start"], place=True),
            work / f"recover-{site}.json",
        )
        plan += [f"load {library}", "goto above_place", "run descend_place", "run release_place", "run lift_place"]
        steps.append({"held_at": here})
    for command in (*plan, "park"):
        status = cell.act(command)
        steps.append({"command": command, "ok": status.get("ok"), "error": status.get("error")})
        if not status.get("ok"):
            return {"result": "stopped", "at": command, "steps": steps}
        if command.startswith(("grip", "jog")):
            time.sleep(config.get("recover_settle_s", 3.0))
    return {"result": "recovered", "holding": holding, "steps": steps}
