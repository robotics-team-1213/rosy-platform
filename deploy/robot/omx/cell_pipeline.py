#!/usr/bin/env python3
"""One-arm native cell: locate -> plan -> reviewed transfer -> verify (D-872, D-911).

Automatic `run` requires existing calibration and reviewed evidence for every exact task;
it holds before motion on missing or changed evidence. `transfer` performs one attempt.
Supervised `--commissioning --person-at-switch` is for individual stages, never `run`:
  calibrate  fit camera -> arm maps from placements at known points
  reset      return the box to the start, with a coarse jaw map if needed
  survey     mark the jaws above the box without descending
  record     record one A/B replay; no chunk session may hold the arm
`locate` and `verify` observe without moving. `recover` requires a person at the switch.
Receipts and attempts retain checks, interrupted work and phase-specific failures.

The existing guarded chunk_runner session owns the actuator bus. This pipeline only sends
commands; it never opens a serial port. Configuration and review procedure: README.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402
from cell_pipeline_io import FifoCell, write_library, write_receipt  # noqa: E402
from cell_envelope import SEQUENCE  # noqa: E402
from cell_observe import (  # noqa: E402
    KEEP, fixed_cameras, grid_points, hover_check, keep, locate, on_flat, predicted_pixel, record_key, see, wrap90,
)
import numpy as np  # noqa: E402

STAGES = ("run", "reset", "calibrate", "locate", "transfer", "verify", "recover", "record", "survey")


def target(config: dict, site: str, xy, yaw_deg=None, place=False) -> dict:
    s = config["sites"][site]
    return {"x": xy[0], "y": xy[1], "z": round(s["z"] + (s.get("place_dz", 0.0) if place else 0.0), 4),
            "yaw_deg": s["yaw_deg"] if yaw_deg is None else yaw_deg}


STEP_KEYS = ("ok", "error", "holding", "gripper_current_ma", "settled", "fault", "contact", "state", "target", "t",
             "paced_ticks")


def transfer(cell, library: Path, hover=None, *, config=None, calibration=None, before_motion=None) -> dict:
    """`hover()` runs right above the box; a hover that is not aligned stops before the descent."""
    from cell_envelope import assess, same_session

    assessment = assess(config or {}, calibration or {}, json.loads(library.read_text()), cell.act("state"))
    if not assessment["allowed"]:
        return {"result": "held", "at": "preflight", "steps": [], "envelope": assessment}
    try:
        if before_motion is not None:
            before_motion(assessment)
        elif assessment["mode"] == "automatic":
            raise OSError("automatic transfer requires a durable attempt intent")
    except OSError:
        return {"result": "held", "at": "preflight", "steps": [],
                "envelope": {**assessment, "allowed": False, "reason": "audit_unavailable"}}
    steps, seen = [], None
    def act(command):
        return cell.checked(command, assessment)

    for command in (f"load {library}", *SEQUENCE):
        state = cell.act("state")
        if (not same_session(state, assessment)
                or (steps and state.get("library_sha256") != assessment["library_sha256"])):
            return {"result": "held", "at": command, "steps": steps,
                    "envelope": {**assessment, "allowed": False, "reason": "session_changed"}}
        status = act(command)
        steps.append({"command": command, **{k: status.get(k) for k in STEP_KEYS}})
        if command == f"load {library}" and status.get("library_sha256") != assessment["library_sha256"]:
            return {"result": "held", "at": command, "steps": steps,
                    "envelope": {**assessment, "allowed": False, "reason": "library_changed"}}
        if status.get("contact"):  # the runner held with torque on: back up the same path, fold home
            for after in ("retreat", "park"):
                steps.append({"command": after, "ok": act(after).get("ok")})
            return {"result": "contact", "at": command, "steps": steps, "error": status.get("error"),
                    "envelope": assessment}
        if not status.get("ok"):
            if not status.get("fault") and command not in ("park", f"load {library}"):
                act("park")  # preserve the checked library even on the existing recovery path
            return {"result": "fault" if status.get("fault") else "refused", "at": command, "steps": steps,
                    "envelope": assessment}
        if command == "goto above_pick" and hover is not None:
            seen = hover()
            if seen.get("aligned") is False:
                act("park")
                return {"result": "misaligned", "at": command, "hover": seen, "steps": steps,
                        "envelope": assessment}
        if command == "run grasp_pick" and not status.get("holding"):
            for after in ("run lift_pick", "park"):
                steps.append({"command": after, "ok": act(after).get("ok")})
            return {"result": "empty", "at": command, "hover": seen, "steps": steps, "envelope": assessment}
    return {"result": "placed", "hover": seen, "steps": steps, "envelope": assessment}


def verify(cell, config: dict, site: str, calibration: dict | None = None, intended=None) -> dict:
    """Did the box land where it was put? With a fine map for `site`: the located box against the intended
    arm point (verify_tol_mm). With only a coarse map or none, the arm's own placement is trusted once the
    grasp held: a pixel zone drawn for another plan would refuse a correct placement (2026-10-25)."""
    from cell_envelope import verification_tolerance

    tolerance = verification_tolerance(config)
    record = (calibration or {}).get("sites", {}).get(record_key(site, "top"))
    if record is not None and "z_view" not in record and intended is not None:
        found = locate(cell, config, calibration, site)
        if not found["found"]:
            return {"found": False, "inside": False}
        off = 1000 * math.dist(found["arm_m"], intended)
        return {"found": True, "inside": off <= tolerance, "off_mm": round(off, 1),
                "arm_m": found["arm_m"], "basis": "fine map"}
    box = see(cell.frame("top"), config["profiles"]["top"], site)
    return {**{k: box.get(k) for k in ("found", "cx", "cy")}, "inside": bool(box.get("found")),
            "basis": "arm placement"}


def calibrate(cell, config: dict, site: str, work: Path, log=print, calibration: dict | None = None) -> dict:
    """Carry the box from the start through grid points on `site`; return the fitted records. Points whose
    box would not sit on the flat zone are skipped before the arm goes there."""
    if config.get("_commissioning") != {"person_at_switch": True}:
        return {"result": "held: supervised commissioning required"}
    calibration = calibration or {"sites": {}}
    import cell_perception as cp

    s = config["sites"][site]
    start = (s["start"][0], s["start"][1])
    measured = {camera: [] for camera in fixed_cameras(config)}
    hovers = []

    def measure(point):
        seen = {}
        for camera in measured:
            box = see(cell.frame(camera), config["profiles"][camera], site)
            if box.get("found"):
                measured[camera].append(((box["cx"], box["cy"]), point))
            seen[camera] = {k: box.get(k) for k in ("found", "cx", "cy", "yaw")}
        log({"measure": point, "seen": seen})
        return any(v["found"] for v in seen.values())

    def hover():  # above a box placed at a known point: what aligned looks like in the wrist view
        box = cp.wrist_box(cell.frame("wrist"), config["profiles"]["top"])
        if box.get("found"):
            hovers.append((box["cx"], box["cy"], box["area"]))
        return {"aligned": None}

    if not measure(start):
        return {"result": "box not seen at the start point"}
    current, results = start, []
    for i, point in enumerate(grid_points(config, calibration, site)):
        if point == current:
            continue
        if on_flat(config, calibration, site, point) is False:
            results.append({"point": point, "skipped": "the box would not sit on the flat zone"})
            continue
        try:
            library = write_library(config, target(config, site, current), target(config, site, point, place=True),
                                    work / f"calibrate-{site}-{i}.json")
        except SystemExit as exc:  # IK refused this grid point: skip it, keep the box where it is
            results.append({"point": point, "skipped": str(exc)[:160]})
            continue
        moved = transfer(cell, library, hover, config=config, calibration=calibration)
        results.append({"point": point, "transfer": moved["result"], "at": moved.get("at")})
        if moved["result"] != "placed":
            return {"result": "stopped", "transfers": results}
        current = point
        measure(point)
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = {record_key(site, camera): cal.site_record(points, when)
               for camera, points in measured.items() if len(points) >= cal.MIN_POINTS}
    if not records:
        return {"result": "too few measured points", "transfers": results}
    top = records.get(record_key(site, "top"))
    if hovers and top is not None:
        xs, ys, areas = zip(*hovers)
        spread = max(15.0, 3 * max(float(np.std(xs)), float(np.std(ys))))
        top["wrist"] = {"cx": round(float(np.mean(xs)), 1), "cy": round(float(np.mean(ys)), 1),
                        "area": int(np.mean(areas)), "spread_px": round(spread, 1), "samples": len(hovers)}
    return {"result": "calibrated", "records": records, "transfers": results}


def rule_backend(prompt, images, schema):
    """No decision model configured: retry while retry is allowed, else stop. Measurement already vetoed."""
    allowed = schema["properties"]["decision"]["enum"]
    return {"decision": "retry" if "retry" in allowed else "abort", "reason": "rule: no decision model"}


def scene(config: dict, source: str, dest: str, tried: dict) -> dict | None:
    """What a simulator needs to replay this attempt (cell_cases.from_row): box, jaw turn, place, outcome."""
    found, transfer = tried["locate"], tried.get("transfer") or {}
    if not found.get("found") or "grasp_yaw" not in tried or "transfer" not in tried:  # nothing moved: nothing to replay
        return None
    place = config["sites"][dest]["place"]
    return {"box_m": found["arm_m"], "box_turn_deg": found.get("turn_deg", 0.0),
            "grasp_turn_deg": round(tried["grasp_yaw"]["yaw_deg"] - config["sites"][source]["yaw_deg"], 1),
            "place": "belt" if dest == "belt" else place, "outcome": transfer.get("result"), "at": transfer.get("at")}


def case(work: Path, row: dict) -> None:
    """One line per check that did not simply pass, and the outcome that followed: new failure cases to fix
    and turn into tests, and the decision model's training data (it learns before any VLA, D-872)."""
    work.mkdir(parents=True, exist_ok=True)
    with (work / "cases.jsonl").open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **row}, default=str) + "\n")


def grip_to(cell, value: float, timeout_s: float = 10.0, sleep=time.sleep, clock=time.monotonic) -> bool:
    """`grip` only sets the target; the guard moves the jaws at 10 deg/s. Wait until they are there, or
    until they stop short and stay (their mechanical end: on arm S the follower jaws stop at 48.5 while
    the taught closed value is 46.6, 2026-10-25)."""
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
            if still_since is not None and now - still_since >= 1.0:
                return True
            last = jaw
        sleep(0.3)
    return False


def coarse_map(cell, config: dict, site: str, work: Path, choices, log=print) -> dict:
    """A first map before any box has been carried: the empty jaws visit known arm points high above the
    surface; at each, the top camera sees only the fingers change when they open, which marks the jaws.
    The fit is for the viewing height; locate() shifts a box pixel to that height by parallax."""
    if config.get("_commissioning") != {"person_at_switch": True}:
        return {"result": "held: supervised commissioning required"}
    c, s = config["coarse"], config["sites"][site]  # the top camera marks the jaws
    closed_name = "gripper.closed@follower"
    choices.offer(closed_name, float(config["plan"]["grip_closed"]), "taught: plan grip_closed (leader units)")
    choices.offer(closed_name, float(c["grip_closed"]), "config: coarse grip_closed")
    grip_closed = choices.best(closed_name)
    points = []
    for i, (x, y) in enumerate(c["points"]):
        view = {"x": x, "y": y, "z": round(c["z_view"] - config["plan"]["approach_m"], 4), "yaw_deg": s["yaw_deg"]}
        try:
            library = write_library(config, view, view, work / f"coarse-{site}-{i}.json")
        except SystemExit as exc:
            log({"coarse": [x, y], "skipped": str(exc)[:120]})
            continue
        for command in (f"load {library}", "goto above_pick"):
            status = cell.act(command)
            if not status.get("ok"):
                return {"result": "stopped", "at": command, "error": status.get("error"), "fault": status.get("fault")}
        if not grip_to(cell, grip_closed):
            return {"result": "stopped", "at": "grip closed"}
        jaw = (cell.act("state").get("state") or [None] * 6)[5]
        if jaw is not None and abs(jaw - grip_closed) >= 1.0:  # the jaws end short of the asked value
            choices.offer(closed_name, round(jaw, 1), "measured: where the follower jaws stopped")
            choices.outcome(closed_name, grip_closed, False, f"asked {grip_closed}, jaws stopped at {jaw:.1f}")
            choices.outcome(closed_name, round(jaw, 1), True, "the jaws' own end")
            grip_closed = round(jaw, 1)
        closed = cell.frame("top")
        keep(f"coarse-{i}-closed", closed)
        if not grip_to(cell, c["grip_open"]):
            return {"result": "stopped", "at": "grip open"}
        opened = cell.frame("top")
        keep(f"coarse-{i}-open", opened)
        jaws = cal.jaw_pixel(closed, opened)
        log({"coarse": [x, y], "jaws": jaws})
        if jaws is not None:
            points.append((jaws, (x, y)))
    cell.act("park")
    if len(points) < 4:
        return {"result": f"jaws seen at {len(points)} points, need 4"}
    return {"result": "mapped", "record": {"homography": cal.fit(points).round(9).tolist(), "z_view": c["z_view"],
            "coarse": True, "loo_error_mm": cal.loo_error_mm(points) if len(points) >= 5 else None,
            "points": [{"pixel": list(p), "arm_m": list(a)} for p, a in points]}}


def start_reference(config: dict, site: str, choices) -> list:
    """Where the start looks in the top view for the top-down plan: the candidate with the best record.
    The taught reference is one candidate (it belongs to the taught replay); a pixel measured right after
    the arm itself put the box at the start is another."""
    taught = config["profiles"]["top"]["reference"]["top"]
    name = f"{site}.start_pixel@topdown"
    choices.offer(name, [taught["cx"], taught["cy"]], "taught: profile reference.top")
    return choices.best(name)


def at_start(cell, config: dict, site: str, choices) -> dict:
    box = see(cell.frame("top"), config["profiles"]["top"], site)
    ref, tol = start_reference(config, site, choices), config["profiles"]["top"]["tolerance"]["box_px"]
    ok = bool(box.get("found")) and math.dist((box["cx"], box["cy"]), ref) <= tol
    return {"ok": ok, "box": {k: box.get(k) for k in ("found", "cx", "cy", "yaw")}, "reference": ref}


def reset(cell, config: dict, calibration: dict, site: str, work: Path, choices, seat=None, log=print) -> dict:
    """Put the box back where calibration and cycle A start, wherever it is on `site`, without a person:
    with a map, a normal move; without one, a coarse jaw map first. After the arm itself put the box at the
    start, the pixel it shows is a measured start candidate, and every candidate gets that outcome."""
    if at_start(cell, config, site, choices)["ok"]:
        return {"result": "placed", "already": True}
    if record_key(site, "top") not in calibration["sites"]:
        coarse = coarse_map(cell, config, site, work, choices, log)
        if coarse["result"] != "mapped":
            choices.save()
            return {"result": "stopped", "coarse": coarse}
        calibration = dict(calibration, sites=dict(calibration["sites"], **{record_key(site, "top"): coarse["record"]}))
        coarse_record = coarse["record"]
    else:
        coarse_record = None
    moved = move(cell, config, calibration, site, site, work, seat, choices=choices)
    if moved["result"] == "placed":
        box = see(cell.frame("top"), config["profiles"]["top"], site)
        if box.get("found"):
            name, seen = f"{site}.start_pixel@topdown", [round(box["cx"], 1), round(box["cy"], 1)]
            tol = config["profiles"]["top"]["tolerance"]["box_px"]
            for candidate in choices.data["values"].get(name, []):
                choices.outcome(name, candidate["value"], math.dist(candidate["value"], seen) <= tol,
                                f"arm placed the box at the start; seen at {seen}")
            choices.offer(name, seen, "measured: the arm placed the box at the start")
            choices.outcome(name, seen, True, "measured right after the arm placed it")
    choices.save()
    check = at_start(cell, config, site, choices)
    return {**moved, "result": "placed" if moved["result"] == "placed" and check["ok"] else
            moved["result"] if moved["result"] != "placed" else "placed off the start", "start": check,
            "coarse_record": coarse_record}


def grasp_yaw(config: dict, calibration: dict, site: str, found: dict, choices):
    """Which yaw the jaws take over the box: the site's own yaw, or that yaw turned by the top camera's
    reading of the box edges. They compete on real grasps. Until the wrist view is learned the turn is
    capped: a 30 px box gives a rough angle, and a box the arm placed is already square to the jaws
    (2026-10-25: a 25 degree camera turn put the jaws on the box's corners and the guard stopped)."""
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
    """After the guard turned torque off mid-task (2026-10-25: four times by hand), with a new session
    already holding the present pose: lift clear the way the top-down descent came (jaws kept closed if a
    box is held, opened if not), then put a held box at the start or fold home. Never without a person
    at the power switch: a joint that faults again drops the arm."""
    if not person_at_switch:
        return {"result": "refused", "error": "recover moves an arm the guard stopped: confirm a person at the switch"}
    state = cell.act("state")
    if not state.get("ok"):
        return {"result": "stopped", "error": state.get("error")}
    current = abs(((state.get("health") or {}).get("current_ma") or [0] * 6)[5])
    holding = current >= config["plan"].get("hold_current_ma", 140)
    steps = [{"command": "state", "gripper_current_ma": current, "holding": holding}]
    plan = [f"grip {config['plan']['grip_closed']}" if holding else f"grip {config['plan']['grip_open']}",
            config.get("recover_lift", "jog elbow_flex.pos -5 wrist_flex.pos 4")]
    if holding:
        here = state["state"]
        library = write_library(config, target(config, site, config["sites"][site]["start"]),
                                target(config, site, config["sites"][site]["start"], place=True),
                                work / f"recover-{site}.json")
        plan += [f"load {library}", "goto above_place", "run descend_place", "run release_place", "run lift_place"]
        steps.append({"held_at": here})
    for command in (*plan, "park"):
        status = cell.act(command)
        steps.append({"command": command, "ok": status.get("ok"), "error": status.get("error")})
        if not status.get("ok"):
            return {"result": "stopped", "at": command, "steps": steps}
        if command.startswith(("grip", "jog")):
            time.sleep(config.get("recover_settle_s", 3.0))  # these set targets; the guard moves at 10 deg/s
    return {"result": "recovered", "holding": holding, "steps": steps}


def move(cell, config: dict, calibration: dict, source: str, dest: str, work: Path, seat=None,
         attempts: int = 2, choices=None) -> dict:
    """locate -> transfer -> verify, with the judge seat at each check (D-872 §2.2): measured facts decide
    first, the decision model picks among what is left, and every decision is kept as training data."""
    import cell_attempts
    import judge_seat

    seat = seat or judge_seat.Seat(rule_backend)
    out = {"from": source, "to": dest, "attempts": [], "decisions": []}
    for attempt in range(attempts):
        t_start, found = time.time(), locate(cell, config, calibration, source)
        tried = {"locate": found}
        out["attempts"].append(tried)
        if found["found"]:
            yaw_pick, yaw = grasp_yaw(config, calibration, source, found, choices)
            tried["grasp_yaw"] = {"choice": yaw_pick, "yaw_deg": yaw}
            tried["plan"] = {"pick": target(config, source, found["arm_m"], yaw),
                             "place": target(config, dest, config["sites"][dest]["place"], place=True)}
            try:
                library = write_library(config, *tried["plan"].values(), work / f"move-{source}-{dest}.json")
            except SystemExit as exc:  # no IK for where the box was seen: an attempt to keep, not a crash
                tried["plan_error"] = str(exc)[:200]
        if "plan_error" in tried:
            facts = {"box_found": True, "next": "grasp", "aligned": False, "check": f"plan refused: {tried['plan_error']}"}
        elif found["found"]:
            def before_motion(assessment):
                tried["envelope"] = assessment
                cell_attempts.begin(config, assessment)

            tried["transfer"] = transfer(cell, library, lambda: hover_check(cell, config, calibration, source),
                                         config=config, calibration=calibration, before_motion=before_motion)
            tried["envelope"] = tried["transfer"]["envelope"]
            moved = tried["transfer"]["result"]
            if moved == "held":
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t_start, choices)
                return {**out, "result": f"held: {tried['envelope']['reason']}"}
            if choices is not None and moved in ("placed", "empty", "fault", "refused", "contact"):
                held = moved == "placed" or any(s.get("holding") for s in tried["transfer"]["steps"])
                choices.outcome(f"{source}.grasp_yaw@topdown", yaw_pick, held, f"{moved} at yaw {yaw}")
                choices.save()
            if moved == "placed":
                tried["verify"] = verify(cell, config, dest, calibration, config["sites"][dest]["place"])
                if tried["verify"].get("inside"):
                    attempt_id = cell_attempts.record(config, calibration, source, dest, attempt, tried, t_start, choices)
                    if out["decisions"]:  # the outcome of the last decision: this retry worked
                        case(work, {"from": source, "to": dest, "attempt": attempt, "outcome": "placed",
                                    "attempt_id": attempt_id})
                    return {**out, "result": "placed"}
                facts = {"box_found": tried["verify"].get("found", False), "next": "grasp", "aligned": False,
                         "check": "placed out of the next grasp's reach"}
            elif moved == "contact":
                facts = {"box_found": True, "next": "grasp", "aligned": False,
                         "check": f"soft contact at {tried['transfer']['at']}: {tried['transfer'].get('error')}"}
            elif moved == "misaligned":
                hover = tried["transfer"]["hover"]
                facts = {"box_found": hover["box_found"], "next": "grasp", "aligned": False,
                         "check": f"wrist view off the learned hover by {hover.get('off_px')} px",
                         "wrist": hover["wrist"]}
            else:
                facts = {"box_found": True, "next": "lift", "holding": False, "check": f"transfer {moved}",
                         "fault": tried["transfer"]["at"] if moved == "fault" else None,
                         "wrist": (tried["transfer"].get("hover") or {}).get("wrist")}
        else:
            facts = {"box_found": False, "next": "grasp", "check": found.get("error")}
        attempt_id = cell_attempts.record(config, calibration, source, dest, attempt, tried, t_start, choices)
        decision = seat.decide(dict(facts, site=source, attempt=attempt))
        out["decisions"].append(decision)
        case(work, {"from": source, "to": dest, "attempt": attempt, "facts": facts, "decision": decision["decision"],
                    "by": decision["by"], "reason": decision.get("reason"),
                    "scene": scene(config, source, dest, tried), "attempt_id": attempt_id})
        if decision["decision"] != "retry" or (facts.get("fault")):
            return {**out, "result": f"stopped: {decision['decision']} ({facts['check']})"}
    return {**out, "result": f"stopped: {attempts} attempts"}


def run(cell, config: dict, calibration_path: Path, work: Path, cycles: int, log=print, seat=None,
        choices=None) -> dict:
    """Calibrate what has no map, then cycles of A (pinky -> belt) and B (belt -> pinky); stop at the first miss."""
    import cell_choices

    steps = []
    choices = choices or cell_choices.Choices(Path(work) / "choices.json")
    calibration = cal.load(calibration_path) if Path(calibration_path).exists() else {"schema": cal.SCHEMA, "sites": {}}
    if not config.get("_commissioning") and not {"pinky", "belt"} <= set(calibration["sites"]):
        return {"result": "held: commissioning required for calibration", "steps": []}
    if "pinky" not in calibration["sites"]:
        homed = reset(cell, config, calibration, "pinky", work, choices, seat, log)  # the box may be anywhere on the tray
        if homed.get("coarse_record"):
            cal.save(calibration_path, "pinky~coarse", homed.pop("coarse_record"))
            calibration = cal.load(calibration_path)
        steps.append({"reset": "pinky", **homed})
        if homed["result"] != "placed":
            return {"result": "stopped", "steps": steps}
        result = calibrate(cell, config, "pinky", work, log, calibration)
        steps.append({"calibrate": "pinky", "result": result["result"], "transfers": result.get("transfers")})
        if result["result"] != "calibrated":
            return {"result": "stopped", "steps": steps}
        for key, record in result["records"].items():
            cal.save(calibration_path, key, record)
        calibration = cal.load(calibration_path)
    if "belt" not in calibration["sites"]:
        moved = move(cell, config, calibration, "pinky", "belt", work, seat, choices=choices, attempts=1)
        steps.append(moved)
        if moved["result"] != "placed":
            return {"result": "stopped", "steps": steps}
        config = dict(config, sites=dict(config["sites"], belt=dict(config["sites"]["belt"],
                                                                     start=config["sites"]["belt"]["place"])))
        result = calibrate(cell, config, "belt", work, log, calibration)
        steps.append({"calibrate": "belt", "result": result["result"], "transfers": result.get("transfers")})
        if result["result"] != "calibrated":
            return {"result": "stopped", "steps": steps}
        for key, record in result["records"].items():
            cal.save(calibration_path, key, record)
        calibration = cal.load(calibration_path)
        moved = move(cell, config, calibration, "belt", "pinky", work, seat, choices=choices)  # back where cycle A starts
        steps.append(moved)
        if moved["result"] != "placed":
            return {"result": "stopped", "steps": steps}
    for cycle in range(cycles):
        for source, dest in (("pinky", "belt"), ("belt", "pinky")):
            moved = move(cell, config, calibration, source, dest, work, seat, choices=choices)
            steps.append({"cycle": cycle, "episode": "A" if source == "pinky" else "B", **moved})
            log({"cycle": cycle, "from": source, "result": moved["result"]})
            if moved["result"] != "placed":
                return {"result": "stopped", "steps": steps}
    return {"result": "done", "cycles": cycles, "steps": steps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--stage", default="run", choices=STAGES)
    parser.add_argument("--cycles", type=int, default=1, help="run: A/B cycles after calibration")
    parser.add_argument("--person-at-switch", action="store_true", help="recover: a person is at the power switch")
    parser.add_argument("--commissioning", action="store_true", help="supervised evidence collection; never enables run")
    parser.add_argument("--operating-profile", type=Path, help="select this device's pinned operating profile")
    parser.add_argument("--from", dest="source", default="pinky")
    parser.add_argument("--to", default="belt")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text())
    config.pop("_operating_profile_binding", None)
    config.pop("_commissioning", None)  # a stored config cannot attest a person's presence
    if args.commissioning:
        if not args.person_at_switch or args.stage == "run":
            parser.error("--commissioning requires --person-at-switch and an individual stage, not run")
        config["_commissioning"] = {"person_at_switch": True}
    if args.stage in ("calibrate", "reset", "survey", "record") and not args.commissioning:
        parser.error(f"{args.stage} requires supervised --commissioning --person-at-switch")
    if args.operating_profile or config.get("operating_profile_path"):
        from cell_robot_profile import bind_pipeline

        config = bind_pipeline(config, args.operating_profile)
    elif args.stage not in ("locate", "verify", "recover"):
        parser.error("select a per-device --operating-profile before a motion stage")
    import cell_perception as cp

    config["profiles"] = {camera: cp.load_profile(Path(spec.get("profile_path", config["profile_path"])).expanduser())
                          for camera, spec in config["cameras"].items()}
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())  # grasp-plan.example.json form
    work = Path(config["work_dir"]).expanduser()
    calibration_path = Path(config["calibration_path"]).expanduser()
    cell = FifoCell(Path(config["io"]).expanduser(), config["cameras"],
                    operating_profile=config.get("_operating_profile_binding"))
    if args.stage == "record":  # record_session takes the arm itself: no chunk session may hold it
        if cell.act("state").get("ok"):
            raise SystemExit("stop the chunk session first (park, stop): record_session needs the arm")
    elif not cell.act("state").get("ok"):
        raise SystemExit("start record_session.py --chunks first: no chunk_runner answers")
    seat = None
    if config.get("decision_model"):  # e.g. {"url": "http://127.0.0.1:11434", "model": "qwen3-vl:8b-instruct"}
        import judge_seat

        seat = judge_seat.Seat(judge_seat.ollama(**config["decision_model"]), knowledge=config.get("knowledge"), params=config.get("params_path"), context=config.get("decision_context"))
    KEEP["dir"] = work / "frames"
    import cell_attempts

    cell_attempts.start(work / "attempts.jsonl", knowledge=config.get("knowledge"), params=config.get("params_path"))
    if args.stage == "record":
        import cell_record

        result = cell_record.record_cycle(cell, config, cal.load(calibration_path), work, args.source, args.to)
    elif args.stage == "recover":
        result = recover(cell, config, args.source, work, args.person_at_switch)
    elif args.stage == "run":
        result = run(cell, config, calibration_path, work, args.cycles, seat=seat)
    elif args.stage == "reset":
        calibration = cal.load(calibration_path) if calibration_path.exists() else {"schema": cal.SCHEMA, "sites": {}}
        import cell_choices

        result = reset(cell, config, calibration, args.source, work, cell_choices.Choices(work / "choices.json"), seat)
        if result.get("coarse_record"):
            cal.save(calibration_path, f"{args.source}~coarse", result.pop("coarse_record"))
    elif args.stage == "calibrate":
        calibration = cal.load(calibration_path) if calibration_path.exists() else {"schema": cal.SCHEMA, "sites": {}}
        result = calibrate(cell, config, args.source, work, calibration=calibration)
        for key, record in result.get("records", {}).items():
            cal.save(calibration_path, key, record)
    elif args.stage == "locate":
        result = locate(cell, config, cal.load(calibration_path), args.source)
    elif args.stage == "survey":
        import cell_survey

        result = cell_survey.stage(cell, config, calibration_path, args.source, work)
    elif args.stage == "transfer":
        result = move(cell, config, cal.load(calibration_path), args.source, args.to, work, seat, attempts=1)
    else:
        result = verify(cell, config, args.to)
    path = write_receipt(work / "receipts", args.stage, result)
    print(json.dumps({"receipt": str(path), "result": result.get("result") or result.get("transfer", {}).get("result")
                      or result.get("found") or result.get("inside")}))


if __name__ == "__main__":
    main()
