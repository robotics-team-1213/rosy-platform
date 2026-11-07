#!/usr/bin/env python3
"""One box to its destination, going on after a failed attempt: the attempt's result and the top camera name the cause, the
table in cell_diagnose (data, not code) names the next action, and each action is tried once per cause, so a retry always
changes something. Then a person decides.

2026-11-07 (arm_b, ship): the first lift of a held box stopped, the retreat pressed it down and the park refused to close on it.
Now run_auto lets go and rises (cell_unwedge.release_and_rise); here a lift stall or a packed box gets a push (cell_align) and
another pick. Folded before and after each attempt, the two top views show what moved: the pile changing away from the box
and its destination means the plan is stale. A push that changed nothing in the view did nothing, and stops.

  cell_recovery.py --config C --catalog K --roi X0 Y0 X1 Y1 --from S --dest D --commissioning --person-at-switch
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import cell_align
import cell_auto_pick as auto
import cell_decisions as cd
import cell_diagnose
import cell_objects
import cell_pivot
import cell_why
from cell_calibration import load as load_calibration
from cell_scene_guard import scene_moved

NEAR_PX, ROUNDS = 60, 5  # about 1 mm per px in the 650 mm top view; a long box is 90 mm
# what the trace measured -> what it asks for; a model's text never chooses (D-971)
# shortcut: cell_why reads no too_fast until a free-motion baseline separates it from contact, so that entry waits for it
PREFER = {"too_fast": "slow_down", "blocked": "push_clear"}
SLOWER, SLOWEST = 0.7, 0.25  # lift_guard_frac: each slow_down, and its floor


def away_from(blobs: list, points: list, near_px: int = NEAR_PX) -> list:
    """The changed regions ([area, x0, y0, x1, y1]) farther than near_px from all of the points where a change is expected."""
    def near(b, p):
        return math.hypot(max(b[1] - p[0], 0, p[0] - b[3]), max(b[2] - p[1], 0, p[1] - b[4])) <= near_px
    return [b for b in blobs if not any(near(b, p) for p in points)]


def options(cause: str, can: set, choices=None, prefer: str | None = None) -> list:
    """The table's actions possible now, best record first; what cell_why read as the cause goes before the record; a person
    stays last and a cause's list is never added to."""
    actions = [a for a in cell_diagnose.next_actions(cause, can, cell_diagnose.RECOVERY) if a != "ask_person"]
    actions = choices.ranked(f"recovery.{cause}", actions) if choices else actions
    return sorted(actions, key=lambda a: a != prefer) + ["ask_person"]


def learned(choices, cause: str, action: str, ok: bool, note: str) -> None:
    if choices:
        choices.offer(f"recovery.{cause}", action, "table")
        choices.outcome(f"recovery.{cause}", action, ok, note[:200])


def unsolved(choices) -> dict:
    """What the cell could not solve itself: cause -> times a person was asked, and the last raw result. The list to add rules for."""
    return {name.removeprefix("recovery."): {"asked": c["tries"], "last": (c["last"] or {}).get("note")}
            for name, values in choices.data["values"].items() if name.startswith("recovery.")
            for c in values if c["value"] == "ask_person" and c["tries"]}


def at_home(state, home: list, tolerance: float = 2.0) -> bool:
    """The body joints are folded; the jaws do not count. No reading is not home."""
    return bool(state) and max(abs(a - b) for a, b in zip(state[:5], home[:5])) <= tolerance


def carry(frame, pick, push, *, expected_px, emit=cd.emit, rounds: int = ROUNDS, choices=None, explain=None, slow=None, folded=None) -> dict:
    """pick() -> run_auto's result; push(cause, attempt) -> whether it moved the arm; expected_px(attempt) -> pixels of the
    pick and the place; frame() -> the top view with the arm folded. An action earns its record from the next attempt: only a
    placed box counts as working, and `choices` then ranks the actions next time. explain(cause, out) -> cell_why's row: what it
    measured orders the actions, and a cause unknown again goes to a person. slow() -> lowered the lift speed, or at the floor.
    folded() -> the arm came home: a fold can fail after a stop, and no retry starts from there."""
    tried, rows, pending = {}, [], None
    try:
        for _ in range(rounds):
            before = frame()
            out = pick()
            attempt = (out.get("attempts") or [{}])[-1]
            moved = away_from(scene_moved(before, frame()), expected_px(attempt))
            cause = cell_diagnose.attempt_cause(out["result"], bool(moved))
            if pending:
                learned(choices, *pending, cause == "placed", out["result"])
                pending = None
            why = explain(cause, out) if explain and cause != "placed" else {}
            can = ({"observe_again", "push_clear"} | ({"slow_down"} if slow else set())) - set(tried.setdefault(cause, []))
            action = "done" if cause == "placed" else options(cause, can, choices, PREFER.get(why.get("hypothesis")) if why.get("by") == "measurement" else None)[0]
            if why.get("repeat_unknown") or (folded and action != "done" and not folded()):
                action = "ask_person"
            if action == "slow_down" and not slow():
                learned(choices, cause, action, False, "the lift is at its slowest")
                action = "ask_person"
            if action == "push_clear":
                before = frame()
                if not push(cause, attempt) or not scene_moved(before, frame()):
                    learned(choices, cause, action, False, "the push changed nothing in the top view")
                    action = "ask_person"
            if action == "ask_person":
                learned(choices, cause, action, False, out["result"])
            rows.append({"result": out["result"], "cause": cause, "pile_moved": moved, "action": action,
                         "why": why.get("hypothesis"), "missing": why.get("missing", [])})
            emit("recovery", rows[-1], cell_diagnose.RECOVERY.get(cause, []), action, "rule", f"cause {cause}")
            if action in ("done", "ask_person"):
                return {"result": "placed" if action == "done" else f"ask a person: {cause}", "rounds": rows}
            tried[cause].append(action)
            pending = (cause, action)
        return {"result": f"ask a person: {rounds} rounds", "rounds": rows}
    finally:
        if choices:
            choices.save()


def main(argv=None) -> int:
    import cell_choices
    from cell_auto_setup import open_cell, parser

    ap = parser(__doc__)
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    if args.dry_run:
        ap.error("recovery has no dry run: use cell_auto_pick --dry-run for the plan, cell_failure_scenarios for the decisions")
    if not (args.commissioning and args.person_at_switch):
        ap.error("recovery moves the arm outside the D-911 gate: --commissioning --person-at-switch")
    args.push_site = args.source
    config, cell, calibration_path, work = open_cell(args, True)
    catalog = cell_objects.load_catalog(args.catalog)
    calibration = cell_pivot.with_site_maps(config, load_calibration(calibration_path))
    site_of = {"pick": args.source, "place": auto.parse_dest(config, args.source, args.dest)[0]}

    def expected_px(attempt):
        plan = attempt.get("plan") or {}
        points = [auto.predicted_pixel(config, calibration, site_of[k], (plan[k]["x"], plan[k]["y"])) for k in plan if k in site_of]
        return [p for p in points if p is not None]

    choices = cell_choices.Choices(work / "choices.json")  # one copy: run_auto's closing-axis records and these share the file

    def pick():
        return auto.run_auto(cell, config, calibration, calibration_path, catalog, args.roi, args.source, args.dest, work, choices)

    def push(cause, attempt):
        packed = None
        if cause == "lift_stall":  # it looks free: the box under the stalled lift is the one to move
            _, _, objects, error = auto.observe(cell, config, calibration, args.source, args.roi, catalog)
            pick_at = (attempt.get("plan") or {}).get("pick")
            if error or not objects or not pick_at:
                return False
            packed = [min(objects, key=lambda o: math.dist(o["raw_m"], (pick_at["x"], pick_at["y"])))["centre_mm"]]
        step = cell_align.next_step(cell, config, calibration, calibration_path, catalog, args.roi, args.source, args.push_site,
                                    args.dest, work, packed)
        print(json.dumps({"next": step}, default=str), flush=True)
        return step["step"] in ("push", "pivot") and cell_align.run_step(step, args) == 0

    why_path, started = work / "why.jsonl", time.time()

    def explain(cause, out):  # measurement only: the control PC does not call a model; Fleet hands the incident to the AI PC (D-971)
        # shortcut: the newest trace in the working folder, as the session script writes it; upgrade if a run ever starts elsewhere
        traces = sorted(Path(".").glob(f"trace-{config.get('arm_id', 'arm_s')}-*.jsonl"), key=lambda p: p.stat().st_mtime)
        return cell_why.explain(cause, out["result"], cell_why.read_trace(traces[-1]) if traces else [], [], None, why_path, since=started)

    def slow():
        slower = round(config["plan"].get("lift_guard_frac", 0.85) * SLOWER, 3)
        if slower < SLOWEST:
            return False
        config["plan"]["lift_guard_frac"] = slower
        return True

    out = carry(lambda: cell.frame("top"), pick, push, expected_px=expected_px, choices=choices, explain=explain, slow=slow,
                folded=lambda: at_home(cell.act("state").get("state"), config["plan"]["home"]))
    print(json.dumps({**out, "unsolved": unsolved(choices), "open_questions": cell_why.open_questions(why_path)}, indent=1, default=str))
    return 0 if out["result"] == "placed" else 1


if __name__ == "__main__":
    sys.exit(main())
