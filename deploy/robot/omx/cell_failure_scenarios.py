#!/usr/bin/env python3
"""Failure scenarios run in parallel through cell_recovery.carry, on a scripted cell: no arm, no camera, no session.

Each scenario is data: what each attempt ends in, what the top camera shows, whether a push moves anything, and what the cell
must then do. `teach` runs rounds first on the same ledger, and the action that failed must lose its place.
--decisions turns the real failures of a cell's decisions.jsonl into scenarios too: each must get the table's answer today, and
one that only a person can answer goes on the `unsolved` list, the list of rules still to write. A scenario that passes here
proves the decision, not the motion: motion is proven only on the arm.

  cell_failure_scenarios.py [--workers 8] [--decisions work/decisions.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import cell_choices
import cell_diagnose
import cell_recovery

STALL, ROOM = "stopped: released after a stop at run lift_pick", "stopped: no usable object"
PICK_PX = (100, 100)  # a change within NEAR_PX of it is the box itself; `pile` paints one far from it

# rounds: (run_auto's result, the pile moved away from the box in that attempt, the push moved something[, cell_why's reading])
SCENARIOS = [
    {"name": "clean carry", "rounds": [("placed", False, True)], "result": "placed", "actions": ["done"]},
    {"name": "lift too fast, slower works", "rounds": [(STALL, False, True, "too_fast"), ("placed", False, True)], "result": "placed",
     "actions": ["slow_down", "done"]},
    {"name": "lift blocked, push frees it", "rounds": [(STALL, False, True, "blocked"), ("placed", False, True)], "result": "placed",
     "actions": ["push_clear", "done"]},
    {"name": "lift stall nobody could read: slower first", "rounds": [(STALL, False, True), ("placed", False, True)], "result": "placed",
     "actions": ["slow_down", "done"]},
    {"name": "lift blocked, push does nothing", "rounds": [(STALL, False, False, "blocked")], "result": "ask a person: lift_stall", "actions": ["ask_person"]},
    {"name": "lift stall every time", "rounds": [(STALL, False, True, "blocked")] * 4, "result": "ask a person: lift_stall",
     "actions": ["push_clear", "slow_down", "observe_again", "ask_person"]},
    {"name": "lift at its slowest already", "floor": True, "rounds": [(STALL, False, True, "too_fast")], "result": "ask a person: lift_stall", "actions": ["ask_person"]},
    {"name": "a model's guess chooses nothing", "rounds": [("stopped: misaligned", False, True, "model says blocked"), ("placed", False, True)],
     "result": "placed", "actions": ["observe_again", "done"]},
    {"name": "unknown again: a person, not another try", "rounds": [("stopped: misaligned", False, True, "repeat")], "result": "ask a person: misaligned", "actions": ["ask_person"]},
    {"name": "a reading never turns a hard stop into a retry", "rounds": [("stopped: fault", False, True, "too_fast")], "result": "ask a person: other", "actions": ["ask_person"]},
    {"name": "held box, jaws stuck", "rounds": [("stopped: holding after a stop at run lift_pick", False, True)],
     "result": "ask a person: held_stop", "actions": ["ask_person"]},
    {"name": "box comes along on the fold", "rounds": [("stopped: still holding", False, True)], "result": "ask a person: stuck_in_jaws", "actions": ["ask_person"]},
    {"name": "no finger room, push clears", "rounds": [(ROOM, False, True), ("placed", False, True)], "result": "placed", "actions": ["push_clear", "done"]},
    {"name": "pile moved during the pick", "rounds": [("stopped: misaligned", True, True), ("placed", False, True)], "result": "placed",
     "actions": ["observe_again", "done"]},
    {"name": "no room, but the pile moved: look before pushing", "rounds": [(ROOM, True, True), ("placed", False, True)], "result": "placed",
     "actions": ["observe_again", "done"]},
    {"name": "hover refused, seen again", "rounds": [("stopped: misaligned", False, True), ("placed", False, True)], "result": "placed", "actions": ["observe_again", "done"]},
    {"name": "placed but not seen", "rounds": [("stopped: placed", False, True), ("placed", False, True)], "result": "placed", "actions": ["observe_again", "done"]},
    {"name": "reinserted: the grasp was unstable, look again", "rounds": [("stopped: reinserted", False, True), ("placed", False, True)],
     "result": "placed", "actions": ["observe_again", "done"]},
    {"name": "attempts ran out", "rounds": [("stopped: 2 attempts", False, True), ("placed", False, True)], "result": "placed", "actions": ["push_clear", "done"]},
    {"name": "pivot stopped", "rounds": [("stopped: pivot: stopped", False, True)], "result": "ask a person: calibrate", "actions": ["ask_person"]},
    {"name": "no clear point to pivot", "rounds": [("stopped: no clear pivot point", False, True)], "result": "ask a person: calibrate", "actions": ["ask_person"]},
    {"name": "contact, then the pile moved: the plan is stale", "rounds": [("stopped: beside -> ask_person", True, True), ("placed", False, True)], "result": "placed",
     "actions": ["observe_again", "done"]},
    {"name": "contact table reached a person", "rounds": [("stopped: beside -> ask_person", False, True)], "result": "ask a person: contact", "actions": ["ask_person"]},
    {"name": "fault with the pile moved", "rounds": [("stopped: fault", True, True)], "result": "ask a person: other", "actions": ["ask_person"]},
    {"name": "guard abort", "rounds": [("aborted: 55 C", False, True)], "result": "ask a person: other", "actions": ["ask_person"]},
    {"name": "D-911 hold", "rounds": [("held: not reviewed", False, True)], "result": "ask a person: other", "actions": ["ask_person"]},
    {"name": "learns: a look that never helped loses its place", "teach": [("stopped: misaligned", False, True), ("stopped: fault", False, True)],
     "rounds": [("stopped: misaligned", False, True), ("placed", False, True)], "result": "placed", "actions": ["push_clear", "done"]},
    {"name": "S6 unseated cone: seat nudge clears and places", "rounds": [("stopped: unseated_cone: +2.0 mm", False, True), ("placed", False, True)],
     "result": "placed", "actions": ["push_clear", "done"]},
    {"name": "S2 toppled stack: hard stop in carry (S-Temp or person)", "rounds": [("stopped: toppled: r_k=-11 mm", False, True)],
     "result": "ask a person: s2_toppled_or_slumped", "actions": ["ask_person"]},
    {"name": "S4 shallow pinch: observe again and re-pick", "rounds": [("stopped: shallow_pinch: I=62 mA", False, True), ("placed", False, True)],
     "result": "placed", "actions": ["observe_again", "done"]},
    {"name": "S3 packed column: push clears finger clearance", "rounds": [("stopped: packed_column: clear_x=3.5 mm", False, True), ("placed", False, True)],
     "result": "placed", "actions": ["push_clear", "done"]},
]


class World:
    """A top view that changes only where a scenario says."""

    def __init__(self, rounds):
        self.rounds, self.painted, self.now = iter(rounds), 0, None

    def frame(self):
        img = np.full((480, 640, 3), 90, np.uint8)
        for i in range(self.painted):
            img[300:340, 300 + 50 * i:340 + 50 * i] = 240
        return img

    def pick(self):
        self.now = next(self.rounds)
        self.painted += bool(self.now[1])
        return {"result": self.now[0], "attempts": [{}]}

    def push(self, cause, attempt):
        self.painted += bool(self.now[2])
        return True

    def explain(self, cause, out):
        reading = self.now[3] if len(self.now) > 3 else None
        if reading == "repeat":
            return {"hypothesis": "unknown", "by": "nobody", "repeat_unknown": True}
        if reading == "model says blocked":
            return {"hypothesis": "blocked", "by": "model"}
        return {"hypothesis": reading, "by": "measurement"} if reading else {"hypothesis": "unknown", "by": "nobody"}


def replay(rounds, choices, floor=False):
    world = World(rounds)
    return cell_recovery.carry(world.frame, world.pick, world.push, expected_px=lambda attempt: [PICK_PX], emit=lambda *a: None, choices=choices,
                               explain=world.explain, slow=lambda: not floor)


def run_one(scenario: dict) -> dict:
    """A scenario on its own ledger, so that parallel runs cannot teach each other."""
    with tempfile.TemporaryDirectory() as tmp:
        choices = cell_choices.Choices(Path(tmp) / "choices.json")
        try:
            if "teach" in scenario:
                replay(scenario["teach"], choices)
            out = replay(scenario["rounds"], choices, scenario.get("floor", False))
        except StopIteration:  # asked for an attempt the scenario does not have: it went on where it should have stopped
            return {"name": scenario["name"], "ok": False, "result": "tried again past the scenario's end", "actions": [], "unsolved": {}}
    actions =[r["action"] for r in out["rounds"]]
    return {"name": scenario["name"], "ok": out["result"] == scenario["result"] and actions == scenario["actions"],
            "result": out["result"], "actions": actions, "unsolved": cell_recovery.unsolved(choices)}


def from_decisions(path: Path) -> list:
    """Real failures as scenarios, one per distinct result: what today's table does with the first attempt ending that way."""
    seen, out = set(), []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        facts = row.get("facts") or {}
        if row.get("stage") != "recovery" or facts.get("result") in seen or facts.get("result") == "placed":
            continue
        seen.add(facts["result"])
        pile = bool(facts.get("pile_moved"))
        cause = cell_diagnose.attempt_cause(facts["result"], pile)
        first = cell_recovery.options(cause, {"observe_again", "push_clear", "slow_down"})[0]
        out.append({"name": f"real: {facts['result'][:70]}", "rounds": [(facts["result"], pile, True), ("placed", False, True)],
                    "result": "placed" if first != "ask_person" else f"ask a person: {cause}",
                    "actions": [first, "done"] if first != "ask_person" else ["ask_person"]})
    return out


def run_all(scenarios: list, workers: int = 8) -> dict:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(run_one, scenarios))
    unsolved = {}
    for row in rows:
        if row["name"].startswith("real: "):
            unsolved.update(row["unsolved"])
    return {"passed": sum(r["ok"] for r in rows), "total": len(rows), "failed": [r for r in rows if not r["ok"]], "unsolved": unsolved}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--decisions", type=Path, help="a cell's decisions.jsonl: its real failures become scenarios")
    args = ap.parse_args(argv)
    out = run_all(SCENARIOS + (from_decisions(args.decisions) if args.decisions else []), args.workers)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if not out["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
