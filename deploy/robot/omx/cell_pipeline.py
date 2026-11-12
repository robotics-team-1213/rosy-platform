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
from cell_pipeline_io import FifoCell, case, fold, write_library, write_receipt  # noqa: E402
from cell_envelope import SEQUENCE  # noqa: E402
import cell_choices  # noqa: E402
from cell_observe import (  # noqa: E402
    KEEP, detection, fixed_cameras, grid_points, hover_check, keep, load_maps, locate, map_check, maps, on_flat,
    record_key, save_maps, see,
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
        if status.get("contact"):  # the runner held with torque on: back up the same path (unless shedding), fold home
            for after in (() if "overload-hold" in (status.get("error") or "") else ("retreat",)) + ("park",):
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


from cell_pipeline_stages import (  # noqa: E402, F401
    at_start,
    calibrate,
    coarse_map,
    grasp_yaw,
    grip_to,
    recover,
    reset,
    scene,
    start_reference,
)


def move(cell, config: dict, calibration: dict, source: str, dest: str, work: Path, seat=None,
         attempts: int = 2, choices=None, person_at_switch: bool = False) -> dict:
    """locate -> transfer -> verify, with the judge seat at each check (D-872 §2.2): measured facts decide
    first, the decision model picks among what is left, and every decision is kept as training data.
    Each attempt picks where the cameras see the box now; a re-map goes into `calibration` and out["remapped"]."""
    import cell_attempts
    import judge_seat

    seat = seat or judge_seat.Seat(judge_seat.rules)
    out = {"from": source, "to": dest, "attempts": [], "decisions": []}
    for attempt in range(attempts):
        t_start, found = time.time(), locate(cell, config, calibration, source)
        tried = {"locate": found}
        out["attempts"].append(tried)
        off_map = map_check(config, found, calibration) if found["found"] else None
        if found["found"] and off_map is None:
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
        elif found["found"] and off_map is None:
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
                                    "attempt_id": attempt_id, "detection": detection(found)})
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
        elif found["found"]:
            facts = {"box_found": True, "next": "grasp", "aligned": False, "remap": True, "check": off_map}
        else:
            facts = {"box_found": False, "next": "grasp", "check": found.get("error"),
                     "remap": not maps(calibration, source, "top")}
        attempt_id = cell_attempts.record(config, calibration, source, dest, attempt, tried, t_start, choices)
        decision = seat.decide(dict(facts, site=source, attempt=attempt))
        out["decisions"].append(decision)
        case(work, {"from": source, "to": dest, "attempt": attempt, "facts": facts, "decision": decision["decision"],
                    "by": decision["by"], "reason": decision.get("reason"), "detection": detection(found),
                    "scene": scene(config, source, dest, tried), "attempt_id": attempt_id})
        if decision["decision"] == "remap":  # the seat only proposes (D-328/D-785); moving needs a person at the switch
            if not person_at_switch:
                return {**out, "result": f"stopped: remap proposed, confirm a person at the switch ({facts['check']})"}
            choices = choices or cell_choices.Choices(Path(work) / "choices.json")
            key = f"{source}~local" if found["found"] else f"{source}~coarse"
            mapped = coarse_map(cell, config, source, work, choices, around=found.get("arm_m"))
            tried["remap"] = {"result": mapped["result"], "key": key}
            if mapped["result"] != "mapped":
                return {**out, "result": f"stopped: remap {mapped['result']}"}
            calibration["sites"][key] = out.setdefault("remapped", {})[key] = mapped["record"]
            continue
        if decision["decision"] not in ("retry", "reinsert") or (facts.get("fault")):
            return {**out, "result": f"stopped: {decision['decision']} ({facts['check']})"}
    return {**out, "result": f"stopped: {attempts} attempts"}


def run(cell, config: dict, calibration_path: Path, work: Path, cycles: int, log=print, seat=None,
        choices=None, person_at_switch: bool = False) -> dict:
    """Calibrate what has no map, then cycles of A (pinky -> belt) and B (belt -> pinky); stop at the first miss."""
    steps = []
    choices = choices or cell_choices.Choices(Path(work) / "choices.json")
    calibration = load_maps(calibration_path, config)
    if not config.get("_commissioning") and not {"pinky", "belt"} <= set(calibration["sites"]):
        return {"result": "held: commissioning required for calibration", "steps": []}
    gate = {"choices": choices, "person_at_switch": person_at_switch}

    def saved(result):  # every map a stage made is in the file, and in use, before the next stage
        nonlocal calibration
        if save_maps(calibration_path, result):
            calibration = load_maps(calibration_path, config)
        return result

    if "pinky" not in calibration["sites"]:  # the box may be anywhere on the tray
        homed = saved(reset(cell, config, calibration, "pinky", work, choices, seat, log, person_at_switch))
        steps.append({"reset": "pinky", **homed})
        if homed["result"] != "placed":
            return {"result": "stopped", "steps": steps}
        result = saved(calibrate(cell, config, "pinky", work, log, calibration))
        steps.append({"calibrate": "pinky", "result": result["result"], "transfers": result.get("transfers")})
        if result["result"] != "calibrated":
            return {"result": "stopped", "steps": steps}
    if "belt" not in calibration["sites"]:
        moved = saved(move(cell, config, calibration, "pinky", "belt", work, seat, attempts=1, **gate))
        steps.append(moved)
        if moved["result"] != "placed":
            return {"result": "stopped", "steps": steps}
        config = dict(config, sites=dict(config["sites"], belt=dict(config["sites"]["belt"],
                                                                     start=config["sites"]["belt"]["place"])))
        result = saved(calibrate(cell, config, "belt", work, log, calibration))
        steps.append({"calibrate": "belt", "result": result["result"], "transfers": result.get("transfers")})
        if result["result"] != "calibrated":
            return {"result": "stopped", "steps": steps}
        moved = saved(move(cell, config, calibration, "belt", "pinky", work, seat, **gate))  # back where cycle A starts
        steps.append(moved)
        if moved["result"] != "placed":
            return {"result": "stopped", "steps": steps}
    for cycle in range(cycles):
        for source, dest in (("pinky", "belt"), ("belt", "pinky")):
            moved = saved(move(cell, config, calibration, source, dest, work, seat, **gate))
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
    parser.add_argument("--person-at-switch", action="store_true", help="recover or re-map: a person is at the switch")
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
    if config.get("debate_models") or config.get("decision_model"):
        import judge_seat

        seat = judge_seat.Seat(config.get("debate_models") or config["decision_model"], knowledge=config.get("knowledge"), params=config.get("params_path"), context=config.get("decision_context"))
    KEEP["dir"] = work / "frames"
    import cell_attempts

    cell_attempts.start(work / "attempts.jsonl", knowledge=config.get("knowledge"), params=config.get("params_path"))
    calibration, gate = load_maps(calibration_path, config), args.person_at_switch
    if args.stage == "record":
        import cell_record

        result = cell_record.record_cycle(cell, config, calibration, work, args.source, args.to)
    elif args.stage == "recover":
        result = recover(cell, config, args.source, work, gate)
    elif args.stage == "run":
        result = run(cell, config, calibration_path, work, args.cycles, seat=seat, person_at_switch=gate)
    elif args.stage == "reset":
        result = reset(cell, config, calibration, args.source, work, cell_choices.Choices(work / "choices.json"), seat,
                       person_at_switch=gate)
    elif args.stage == "calibrate":
        result = calibrate(cell, config, args.source, work, calibration=calibration)
    elif args.stage == "locate":
        result = locate(cell, config, calibration, args.source)
    elif args.stage == "survey":
        import cell_survey

        result = cell_survey.stage(cell, config, calibration_path, args.source, work)
    elif args.stage == "transfer":
        result = move(cell, config, calibration, args.source, args.to, work, seat, attempts=1, person_at_switch=gate)
    else:
        result = verify(cell, config, args.to)
    save_maps(calibration_path, result)
    path = write_receipt(work / "receipts", args.stage, result)
    print(json.dumps({"receipt": str(path), "result": result.get("result") or result.get("transfer", {}).get("result")
                      or result.get("found") or result.get("inside")}))


if __name__ == "__main__":
    main()
