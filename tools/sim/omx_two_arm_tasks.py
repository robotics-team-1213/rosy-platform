"""Two-arm task definitions as data and the plan validator (no MuJoCo): a plan that fails is refused with the reason.

The task file (deploy/robot/omx/sim/two_arm_tasks.json) names sites and steps; this module resolves the sites on a `Layout`, tracks which
container sits where, and checks every step before anything moves: the source holds the container and nothing lies on it, the target is
free and supported, a temporary plate never holds more than its lanes, both ends and the carry between them are reachable by the step's arm
inside the plan's joint limits, and the moving arm keeps clear of the other arm parked at home. Geometry only (D-947).
"""
import json
import math
from pathlib import Path

import numpy as np

import omx_two_arm_sites as sites_mod

ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = ROOT / "deploy/robot/omx/sim/two_arm_tasks.json"
HOLD_BELOW_TCP = .00201  # the held container centre sits 2.01 mm under the TCP (Isaac hold check)
CARRY_CLEAR = .035       # container bottom clears the highest seated container by 5 mm: centre 30 mm up plus 5
ARM_RADIUS, ARM_MARGIN = .03, .005  # capsule stand-in for a link; MuJoCo contacts are the real check
CAPACITY = 3             # lanes per temporary plate (3 x 1 each)


class PlanRefused(ValueError):
    """The plan failed validation; .reasons lists every failed check."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def load(path=TASK_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def wrap_pi(angle):
    return (angle + math.pi / 2) % math.pi - math.pi / 2  # a container turned 180 deg sits the same


def carry_z(layout, here, a, b):
    """TCP height for moving between sites a and b: above every seated container and both ends."""
    tops = [layout.sites[s]["z"] for s in here.values() if layout.sites[s]["kind"] == "ship"]
    return max([layout.sites[a]["z"], layout.sites[b]["z"], *tops]) + CARRY_CLEAR + HOLD_BELOW_TCP


def waypoints(layout, step, here, pick=None):
    """Teacher path of one step as (name, xy, z, yaw, grip): approach, grasp, lift, carry, lower, release, retreat. grip is open/hold."""
    a, b = dict(layout.sites[step["from"]]), layout.sites[step["to"]]
    if pick:  # the container's true pose at pick time (teacher with ground truth, no perception)
        a["xy"], a["yaw"] = pick
    z_up = carry_z(layout, here, step["from"], step["to"])
    za, zb = layout.hold_z(step["from"]), layout.hold_z(step["to"]) + (.005 if b["kind"] != "belt" else 0)  # release 5 mm up (stack_release_clearance_m)
    ya, yb = a["yaw"], a["yaw"] + wrap_pi(b["yaw"] - a["yaw"])
    return [("approach", a["xy"], z_up, ya, "open"), ("grasp", a["xy"], za, ya, "open"), ("close", a["xy"], za, ya, "hold"),
            ("lift", a["xy"], z_up, ya, "hold"), ("carry", b["xy"], z_up, yb, "hold"), ("lower", b["xy"], zb, yb, "hold"),
            ("release", b["xy"], zb, yb, "open"), ("retreat", b["xy"], z_up, yb, "open")]


def clearance(moving, idle_pose, q_path, idle):
    """Smallest centreline distance between the moving arm along q_path and the idle arm parked at idle_pose (capsule stand-in)."""
    def points(arm, q):
        seg = arm.segments(q)
        return np.vstack([seg[i] + (seg[i + 1] - seg[i]) * t for i in range(len(seg) - 1) for t in np.linspace(0, 1, 8)])
    fixed = points(idle, idle_pose)
    return min(float(np.linalg.norm(points(moving, q)[:, None] - fixed[None], axis=2).min()) for q in q_path)


def check_reach(layout, step, here, arm):
    """Walk the step's waypoints with the arm's IK, sampling 6 points per leg. Returns (problems, joint path, first-failure note)."""
    q, path, problems, last = arm.home.copy(), [], [], None
    for name, xy, z, yaw, _ in waypoints(layout, step, here):
        target = np.array([*xy, z])
        legs = [last + (target - last) * t for t in np.linspace(0, 1, 7)[1:]] if last is not None else [target]
        for k, point in enumerate(legs):
            yaw_k = yaw if last is None else None
            ok, q_new, err = arm.reach(q, point, yaw)
            if not ok:
                return [f"{step['id']}: {arm.name} cannot reach {name} at x {point[0]:.3f} y {point[1]:.3f} z {point[2]:.3f} "
                        f"({err * 1000:.1f} mm short, tool-down inside the plan's joint limits)"], path, name
            q, yaw_k = q_new, None
            path.append(q.copy())
        last = target
    return problems, path, None


def validate(layout, task, data=None):
    """Check every step of `task` (a task dict) on `layout`. Raises PlanRefused with all reasons, else returns per-step records."""
    data = data or load()
    problems, records = [], []
    here = dict(task.get("start", {}))  # container -> site
    supply = set(task.get("supply", []))
    known = {c for c, _ in layout.containers()}
    home_pose = {n: a.home for n, a in layout.arms.items()}
    for step in task["steps"]:
        sid, c, a, b, arm = step["id"], step["container"], step["from"], step["to"], step["arm"]
        bad = [f"{sid}: unknown {kind} {name!r}" for kind, name, ok in (
            ("container", c, c in known), ("site", a, a in layout.sites), ("site", b, b in layout.sites), ("arm", arm, arm in layout.arms)) if not ok]
        if bad:
            problems += bad
            continue
        occupied = {s: k for k, s in here.items()}
        if a == "belt":
            if c not in supply:
                problems.append(f"{sid}: {c} is not on the belt supply")
        elif here.get(c) != a:
            problems.append(f"{sid}: {c} is not at {a} (it is at {here.get(c)})")
        sa = layout.sites[a]
        if sa["kind"] == "ship" and (above := f"ship-r{sa['row']}-l{sa['layer'] + 1}") in occupied:
            problems.append(f"{sid}: {c} would be taken from under {occupied[above]} at {above}")
        if b != "belt" and b in occupied:
            problems.append(f"{sid}: target {b} already holds {occupied[b]}")
        sb = layout.sites[b]
        if sb["kind"] == "ship" and sb["layer"] > 0 and f"ship-r{sb['row']}-l{sb['layer'] - 1}" not in occupied:
            problems.append(f"{sid}: {b} has nothing under it")
        if b == "belt":
            problems.append(f"{sid}: the belt end is a source, not a target")
        if sb["kind"] == "temp" and sum(1 for s in occupied if layout.sites[s].get("plate") == sb["plate"]) + (a not in occupied) > CAPACITY:
            problems.append(f"{sid}: temporary plate {sb['plate']} would hold more than {CAPACITY}")
        if not bad and not problems:
            here_after = {k: v for k, v in here.items() if k != c}
            solved = layout.arms[arm]
            reach_problems, path, _ = check_reach(layout, step, here_after, solved)
            problems += reach_problems
            other = next(n for n in layout.arms if n != arm)
            gap = clearance(solved, home_pose[other], path, layout.arms[other]) if path else None
            if gap is not None and gap < 2 * ARM_RADIUS + ARM_MARGIN:
                problems.append(f"{sid}: {arm} passes {gap * 1000:.0f} mm from {other} parked at home (needs {1000 * (2 * ARM_RADIUS + ARM_MARGIN):.0f})")
            roll = min((float(q[4]) for q in path), default=0.)
            records.append(dict(step=sid, arm=arm, joints_ok=not reach_problems, min_roll_rad=round(roll, 3), roll_below_floor=roll < layout.roll_floor, min_arm_gap_mm=None if gap is None else round(gap * 1000, 1)))
        here[c] = b
    plates = {}
    for s in here.values():
        if layout.sites[s]["kind"] == "temp":
            plates[layout.sites[s]["plate"]] = plates.get(layout.sites[s]["plate"], 0) + 1
    if any(n > CAPACITY for n in plates.values()):
        problems.append(f"temporary space over capacity at the end: {plates}")
    if problems:
        raise PlanRefused(problems)
    return records


def get_task(layout, name, data=None):
    """Task dict by name with its start state; `stack` and `rehandle` come from the data file."""
    data = data or load()
    return dict(data["tasks"][name], name=name)
