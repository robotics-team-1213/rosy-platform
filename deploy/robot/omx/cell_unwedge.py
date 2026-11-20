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
from chunk_runner import JOG_MAX, SETTLE_TOL  # noqa: E402
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
ACTIONS = {"lift": "shoulder_lift", "pull": "elbow_flex"}
STEP, LAG_STOP, CLEAR, MAX_STEPS, SETTLE_S = 1.0, 1.2, 12.0, 60, 1.5
# 2026-11-14 arm_s at a far pick: shoulder_lift lagged 1.3-1.6 just holding (P 640), so LAG_STOP read every step as blocked.
# A joint that already droops gets DROOP_ROOM over its own starting lag, never past LAG_CEIL (the guard trips near 2.2), and
# SMALL_STEP jogs (hand 0.3 steps raised the lift there until it stalled at 2.04).
LAG_CEIL, DROOP_ROOM, SMALL_STEP = 2.0, 0.4, 0.3
HOME = [0.8, -62.2, 53.1, 51.6, 45.2]  # the chunk libraries' home (topdown-guard), body joints
RELEASE_OPEN, JAW_STEP, JAW_TOL = 2.7, 5.0, 1.5  # gripper units; 2.7 was the way from a 30 mm box back to its approach opening
HOME_STEP, HOME_SETTLE_S, HOME_TOL, SETTLE_LAG, HOME_MAX_STEPS = min(4.0, JOG_MAX), 2.0, 1.0, 1.5, 80
REST_TOL = 8.0  # D-1048 cell_auto_fold.REST_TOL on local main
FOLDED_TOL = 10.0
# 11-20 13:15: A's long wrist camera contacted the body at roll 18–20 twice; elbow -10 cleared the turn.
LIFT_JOINT, LIFT_UNITS = "elbow_flex", -10.0
PLATEAU_TOL = 0.05


def lags(status: dict) -> list | None:
    values = (status.get("target"), status.get("state"))
    if any(not isinstance(v, list) or len(v) < len(BODY) or any(
            type(n) not in (int, float) or not math.isfinite(n) for n in v[:len(BODY)]) for v in values):
        return None
    return [round(abs(t - s), 2) for t, s in zip(values[0][:5], values[1][:5])]


def _home_pose(values):
    return (isinstance(values, list) and len(values) == 6
            and all(type(value) in (int, float) and math.isfinite(value) for value in values))


def _home_state(status, context):
    return (status.get("ok") is True and not status.get("fault") and not status.get("contact")
            and not status.get("human_hold_latched")
            and _home_pose(status.get("state")) and _home_pose(status.get("target"))
            and status.get("operating_context") == context)


def _home_plan(home, bounds, start, lift):
    measured, held = start["state"], list(start["target"])
    roll = BODY.index("wrist_roll")
    if lift is None and abs(home[roll] - measured[roll]) > FOLDED_TOL:
        lift = (LIFT_JOINT, LIFT_UNITS)
    lift_axis = BODY.index(lift[0]) if lift else None
    plan = []

    def add(axis, goal, *, outside=False):
        low, high = bounds[axis]
        if not low <= goal <= high:
            raise ValueError(f"{BODY[axis]}: planned target outside joint limits")
        plan.append({"joint": BODY[axis], "delta": goal - held[axis], "goal": goal, "outside_limits": outside})
        held[axis] = goal

    for axis, (low, high) in enumerate(bounds[:len(BODY)]):
        if not low <= measured[axis] <= high:
            goal = home[axis]
            if lift and axis == roll:
                # Re-enter the limits with room for lag, then finish the turn after lifting.
                goal = min(goal, low + SETTLE_TOL) if measured[axis] < low else max(goal, high - SETTLE_TOL)
            add(axis, goal, outside=True)
    if lift:
        add(lift_axis, held[lift_axis] + lift[1])
    for axis in reversed(range(len(BODY))):
        if (axis != lift_axis and home[axis] != held[axis]
                and max(abs(home[axis] - held[axis]), abs(home[axis] - measured[axis])) > HOME_TOL):
            add(axis, home[axis])
    if lift:
        add(lift_axis, home[lift_axis])
    return plan


def _home_stop_result(status):
    if status.get("contact") is True or str(status.get("fault") or "").startswith("contact"):
        return "bind_suspected"
    return "stopped"


def _home_jogs(cell, home, bounds, start, receipt, sleep, log, grip=True):
    baseline = lags(start)
    context = start.get("operating_context")
    for step in receipt["plan"]:
        joint, goal = step["joint"], step["goal"]
        axis = BODY.index(joint)
        low, high = bounds[axis]
        while True:
            status = cell.act("state")
            if not _home_state(status, context):
                return _home_stop_result(status), f"{joint}: live state refused"
            measured, target = status["state"][axis], status["target"][axis]
            remaining = goal - target
            delta = round(max(-HOME_STEP, min(HOME_STEP, remaining)), 2)
            next_target = round(target + delta, 2)
            if low <= measured <= high and (not delta or (abs(remaining) < 0.01 and not low <= next_target <= high)):
                break
            if (not delta or (measured < low and (delta < 0 or next_target <= measured))
                    or (measured > high and (delta > 0 or next_target >= measured))
                    or not min(low, measured) <= next_target <= max(high, measured)):
                return "stopped", f"{joint}: no inward jog"
            if len(receipt["jogs"]) >= HOME_MAX_STEPS:
                return "stopped", "too many jogs"
            command = f"jog {joint}.pos {delta}"
            row = {"command": command, "joint": joint, "delta": delta, "before": status}
            receipt["jogs"].append(row)
            row["ack"] = cell.act(command)
            if row["ack"].get("ok") is not True:
                return _home_stop_result(row["ack"]), f"{joint}: jog refused"
            sleep(HOME_SETTLE_S)
            history, positions = [], [measured]
            for attempt in range(10):
                status = row["after"] = cell.act("state")
                if not _home_state(status, context):
                    return _home_stop_result(status), f"{joint}: live state refused after jog"
                lag = row["lags"] = lags(status)
                if any(value > max(LAG_CEIL, base + DROOP_ROOM) for value, base in zip(lag, baseline)):
                    return "bind_suspected", f"{joint}: strain"
                # A's P-only roll settled 0.5–1.0 units behind, once at 1.75 (11-20).
                if lag[axis] <= max(SETTLE_LAG, baseline[axis] + DROOP_ROOM):
                    break
                history.append(lag[axis])
                positions.append(status["state"][axis])
                if len(history) >= 3 and round(max(history[-3:]) - min(history[-3:]), 2) <= PLATEAU_TOL:
                    break
                if attempt < 9:
                    sleep(1.0)
            else:
                if max(positions) - min(positions) > PLATEAU_TOL:
                    return "bind_suspected", f"{joint}: did not settle; inspect cable or obstruction"
                return "stopped", f"{joint}: did not settle and showed no movement"
            if log:
                log(row)

    status = cell.act("state")
    if not _home_state(status, context):
        return _home_stop_result(status), "live state refused before grip"
    if grip:  # an automatic rehome never opens or closes the jaws (an undetected box would drop)
        ack = receipt["grip"] = cell.act(f"grip {home[5]}")
        sleep(HOME_SETTLE_S)
        if ack.get("ok") is not True:
            return _home_stop_result(ack), "grip refused"
    status = receipt["end"] = cell.act("state")
    if not _home_state(status, context):
        return _home_stop_result(status), "live state refused after grip"
    if any(abs(value - want) > SETTLE_TOL for value, want in zip(status["state"][:6 if grip else 5], home)):
        return "stopped", "measured body or gripper did not reach home"
    return "home", None


def return_home(cell, home, limits, *, lift=None, sleep=time.sleep, log=None, grip=True) -> dict:
    """Return a folded arm to library home through the runner's guarded jogs."""
    minimum, maximum = limits.get("joint_min") or {}, limits.get("joint_max") or {}
    names = tuple(f"{joint}.pos" for joint in (*BODY, "gripper"))
    if not isinstance(minimum, dict) or not isinstance(maximum, dict):
        raise ValueError("configured joint limits must be objects")
    bounds = [(minimum.get(name, -100.0), maximum.get(name, 100.0)) for name in names]
    # an arm with no joint window (arm_s, 11-20) homes over the full range only when its config says so
    if (not _home_pose(home) or not (minimum or maximum or limits.get("joint_window_full_range") is True)
            or (minimum.keys() | maximum.keys()) - set(names)
            or any(not all(type(bound) in (int, float) and math.isfinite(bound) for bound in (low, high))
                   or not max(-100.0, low) <= value <= min(100.0, high)
                   for value, (low, high) in zip(home, bounds))):
        raise ValueError("home or configured joint limits are invalid")
    bounds = [(max(-100.0, low), min(100.0, high)) for low, high in bounds]
    if lift is not None and lift is not False and (
            not isinstance(lift, tuple) or len(lift) != 2 or lift[0] not in BODY
            or type(lift[1]) not in (int, float) or not math.isfinite(lift[1]) or not round(lift[1], 2)):
        raise ValueError("lift needs a body joint and a finite delta that rounds to a nonzero jog")

    receipt = {"home": home, "plan": [], "jogs": [], "start": None, "end": None}
    started = False
    try:
        status = receipt["start"] = receipt["end"] = cell.act("state")
        context = status.get("operating_context")
        profile = getattr(cell, "operating_profile", None)
        if (not _home_state(status, context) or
                (profile is not None and (context or {}).get("operating_profile") != profile)):
            return {**receipt, "result": "stopped", "error": "initial live state refused"}
        measured = status["state"]
        current = (status.get("health") or {}).get("current_ma") or [0] * 6
        if (status.get("holding") or abs(current[5]) >= 140
                or any(abs(value - want) > FOLDED_TOL for value, want in zip(measured[:4], home))):
            return {**receipt, "result": "refused", "error": "home requires an empty, folded arm"}
        try:
            receipt["plan"] = _home_plan(home, bounds, status, lift)
        except ValueError as exc:
            return {**receipt, "result": "refused", "error": str(exc)}
        started = True
        result, error = _home_jogs(cell, home, bounds, status, receipt, sleep, log, grip)
    except (Exception, KeyboardInterrupt) as exc:
        result, error = "stopped", repr(exc)

    receipt.update(result=result, error=error)
    if started and result != "home":
        try:
            receipt["end"] = status = cell.act("state")
            if status.get("operating_context") != context:
                receipt["stop_error"] = "runner session changed or could not be confirmed"
            elif not status.get("human_hold_latched"):
                at_rest = (status.get("ok") is True and _home_pose(status.get("state"))
                           and all(abs(value - want) <= REST_TOL for value, want in zip(status["state"][:5], home)))
                command = "stop now" if at_rest else "human-hold"
                receipt["stop"] = {"command": command, "ack": cell.act(command)}
        except (Exception, KeyboardInterrupt) as exc:
            receipt["stop_error"] = repr(exc)
    return receipt


def rehome_before_work(cell, library: dict, limits: dict, *, sleep=time.sleep) -> dict | None:
    """User 2026-11-20 "홈자세 다시 잡도록 변경해": on 11-19 all three folded wrists were turned by hand (torque OFF) and
    work could not start. An arm off its library home takes the lift-then-turn home first. None: already home.
    A result without jogs (not empty and folded, state refused): nothing moved, the caller goes on as before."""
    try:
        home = library["chunks"]["home"][-1]
        state = cell.act("state").get("state")
        if _home_pose(state) and all(abs(a - b) <= SETTLE_TOL for a, b in zip(state[:5], home[:5])):
            return None
        return return_home(cell, home, limits, sleep=sleep, grip=False)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, OSError) as exc:
        return {"result": "refused", "error": str(exc)}


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
    limits = [min(LAG_CEIL, max(LAG_STOP, b + DROOP_ROOM)) for b in lags(status)]
    size = SMALL_STEP if max(lags(status)) > LAG_STOP else STEP
    lift_direction = 1 if home[1] > initial_lift else -1
    rows, last, blocked, misses, lifted = [], None, None, 0, 0.0
    for step in range(round(MAX_STEPS * STEP / size)):
        lifted = lift_direction * (status["state"][1] - initial_lift)
        action = decide(last, blocked, lifted)
        joint = ACTIONS[action]
        index = BODY.index(joint)
        remaining = home[index] - status["target"][index]  # jog changes the held target, not the measured pose
        if remaining * (home[index] - status["state"][index]) <= 0:
            return {"result": "stopped", "error": f"{joint} reached home before clearance", "rows": rows}
        delta = max(-size, min(size, remaining))
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
        strained = any(v > limit for v, limit in zip(lag, limits))
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
    return {"result": "stopped", "error": f"not clear after {len(rows)} steps", "rows": rows}


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
