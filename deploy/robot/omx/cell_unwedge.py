#!/usr/bin/env python3
"""Free an arm the guard dropped onto the cell, in small steps the strong joints make, watching every step.

2026-11-03: arm_b's wrist_flex fell behind by 5 degrees on a goto, the guard turned torque off, and the extended arm
came down onto the stacked containers. cell_pipeline.recover then asked the wrist (an XL330) to lift by 4 units, and
it fell behind again at 62 % PWM. Here the wrist gets no command: only shoulder_lift ("lift") and elbow_flex ("pull")
step toward home, STEP units at a time. After each step the decision rule reads every body joint's lag:
  - all under LAG_STOP (well inside the guard's ~2.8 units): keep going with the same action;
  - over: half a step back on that action, and the other action is tried next;
  - both actions blocked in a row: stop where it is and ask for a person.
Once the shoulder has risen CLEAR units the arm is off the cell, and the runner's park folds it home. Every step keeps
a top and side frame and one decision row (state, lags, action, outcome) for training a decision model later.
It runs on the arm's host with a chunk session already holding the dropped pose:

  cell_unwedge.py --config C --catalog K --person-at-switch
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chunk_runner import SETTLE_TOL  # noqa: E402
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
ACTIONS = {"lift": "shoulder_lift", "pull": "elbow_flex"}
STEP, LAG_STOP, CLEAR, MAX_STEPS, SETTLE_S = 1.0, 1.2, 12.0, 60, 1.5
HOME = [0.8, -62.2, 53.1, 51.6, 45.2]  # the chunk libraries' home (topdown-guard), body joints
RELEASE_OPEN, JAW_STEP, JAW_TOL = 2.7, 5.0, 1.5  # gripper units; 2.7 was the way from a 30 mm box back to its approach opening


def lags(status: dict) -> list | None:
    values = (status.get("target"), status.get("state"))
    if any(not isinstance(v, list) or len(v) < len(BODY) or any(
            type(n) not in (int, float) or not math.isfinite(n) for n in v[:len(BODY)]) for v in values):
        return None
    return [round(abs(t - s), 2) for t, s in zip(values[0][:5], values[1][:5])]


def decide(last: str | None, blocked: str | None, lifted: float) -> str:
    """The next action: lift until the arm is a few units up (it lies on something), then alternate; never the one
    that was just blocked."""
    choice = "lift" if lifted < 3 * STEP else ("pull" if last == "lift" else "lift")
    if choice == blocked:
        choice = "pull" if choice == "lift" else "lift"
    return choice


def unwedge(cell, home: list, *, sleep=time.sleep, frames=None, log=None) -> dict:
    status = cell.act("state")
    if status.get("ok") is not True or lags(status) is None:
        return {"result": "stopped", "error": status.get("error") or "body measurements unavailable"}
    initial_lift = status["state"][1]
    lift_direction = 1 if home[1] > initial_lift else -1
    rows, last, blocked, misses, lifted = [], None, None, 0, 0.0
    for step in range(MAX_STEPS):
        lifted = lift_direction * (status["state"][1] - initial_lift)
        action = decide(last, blocked, lifted)
        joint = ACTIONS[action]
        index = BODY.index(joint)
        remaining = home[index] - status["target"][index]  # jog changes the held target, not the measured pose
        if remaining * (home[index] - status["state"][index]) <= 0:
            return {"result": "stopped", "error": f"{joint} reached home before clearance", "rows": rows}
        delta = max(-STEP, min(STEP, remaining))
        status = cell.act(f"jog {joint}.pos {delta}")
        if not status.get("ok"):
            return {"result": "stopped", "at": step, "error": status.get("error"), "rows": rows}
        sleep(SETTLE_S)
        status = cell.act("state")
        if not status.get("ok"):
            return {"result": "stopped", "at": step, "error": status.get("error"), "rows": rows}
        lag = lags(status)
        if lag is None:
            return {"result": "stopped", "at": step, "error": "body measurements unavailable", "rows": rows}
        strained = max(lag) > LAG_STOP
        row = {"step": step, "action": action, "delta": delta, "state": status["state"], "lags": lag,
               "outcome": "blocked" if strained else "moved"}
        if frames:
            row["frames"] = frames(f"unwedge-{step:02d}-{action}")
        rows.append(row)
        if log:
            log(row)
        if strained:  # back off half a step so the joint stops pushing, then try the other action
            backed = cell.act(f"jog {joint}.pos {-delta / 2}")
            if backed.get("ok") is not True:
                return {"result": "stopped", "at": step, "error": backed.get("error"), "rows": rows}
            sleep(SETTLE_S)
            misses, blocked = misses + 1, action
            if misses >= 2:
                return {"result": "stuck", "at": step, "rows": rows}
            status = cell.act("state")
            if status.get("ok") is not True or lags(status) is None:
                return {"result": "stopped", "at": step, "error": "body measurements unavailable", "rows": rows}
            continue
        misses, blocked, last = 0, None, action
        lifted = lift_direction * (status["state"][1] - initial_lift)
        if lifted >= CLEAR:
            parked = cell.act("park")
            recovered = (parked.get("ok") is True and parked.get("settled") is True and lags(parked) is not None
                         and max(abs(a - b) for a, b in zip(parked["state"][:5], home)) <= SETTLE_TOL)
            return {"result": "recovered" if recovered else "stopped",
                    "park": parked.get("error") if recovered else parked.get("error") or "park did not confirm settled home",
                    "rows": rows}
    return {"result": "stopped", "error": f"not clear after {MAX_STEPS} steps", "rows": rows}


def release_and_rise(cell, *, sleep=time.sleep) -> dict:
    """An arm stopped low with a box in its jaws: open back to about the opening it came down with, then rise straight up with
    the jaws round the box. A pull here would drag the box, so a blocked rise stops and asks. The caller folds home; a park
    closes the jaws first and refuses while the box is in them (2026-11-07, arm_b: this order, by hand, peak lag 0.77)."""
    status = cell.act("state")
    if not status.get("ok"):
        return {"result": "stopped", "error": status.get("error")}
    target, want = status["target"][5], status["state"][5] + RELEASE_OPEN
    while want - target > 0.05:
        step = round(min(JAW_STEP, want - target), 2)
        status = cell.act(f"jog gripper.pos {step}")
        if not status.get("ok"):
            return {"result": "stopped", "at": "open", "error": status.get("error")}
        target += step
        sleep(SETTLE_S)
    status = cell.act("state")
    if not status.get("ok") or status["state"][5] < want - JAW_TOL:
        return {"result": "stuck", "at": "open", "jaws": status.get("state", [None] * 6)[5]}
    for step in range(int(CLEAR / STEP)):
        status = cell.act(f"jog shoulder_lift.pos {-STEP}")
        if not status.get("ok"):
            return {"result": "stopped", "at": step, "error": status.get("error")}
        sleep(SETTLE_S)
        status = cell.act("state")
        if not status.get("ok"):
            return {"result": "stopped", "at": step, "error": status.get("error")}
        if max(lags(status)) > LAG_STOP:
            cell.act(f"jog shoulder_lift.pos {STEP / 2}")  # stop pushing, then hold with torque on
            return {"result": "stuck", "at": step, "lags": lags(status)}
    return {"result": "risen", "state": status["state"]}


def main(argv=None) -> int:
    import cv2
    from cell_field import Field

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    if not args.person_at_switch:
        ap.error("unwedge moves an arm the guard dropped: confirm a person at the switch")
    field = Field(args.config, args.catalog)
    def frames(name):
        out = {}
        for camera in ("top", "side"):
            try:
                path = field.dir / f"{field.stamp}-{name}-{camera}.jpg"
                cv2.imwrite(str(path), field.cell.frame(camera))
                out[camera] = str(path)
            except Exception as exc:  # a missing camera must not stop the recovery
                out[camera] = f"no frame: {exc}"[:80]
        return out

    decisions = field.dir / f"{field.stamp}-unwedge-decisions.jsonl"
    with decisions.open("a") as fh:
        out = unwedge(field.cell, HOME, frames=frames, log=lambda row: fh.write(json.dumps(row) + "\n") or fh.flush())
    print(json.dumps(field.report("unwedge", {k: v for k, v in out.items() if k != "rows"} | {"steps": len(out.get("rows", [])),
                                                                                         "decisions": str(decisions)}), indent=1))
    return 0 if out["result"] == "recovered" else 1


if __name__ == "__main__":
    sys.exit(main())
