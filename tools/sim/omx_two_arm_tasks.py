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

import omx_two_arm_kin as kin
import omx_two_arm_sites as sites_mod

ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = ROOT / "deploy/robot/omx/sim/two_arm_tasks.json"
HOLD_BELOW_TCP = .00201  # the held container centre sits 2.01 mm under the TCP (Isaac hold check)
CARRY_CLEAR = .035       # container bottom clears the highest seated container by 5 mm: centre 30 mm up plus 5
ARM_RADIUS, ARM_MARGIN = .03, .005  # capsule stand-in for a link; MuJoCo contacts are the real check
RELEASE_DROP = .005     # fixture stack_release_clearance_m; layer 0 rests on studs (floor enforced) and the temp lanes have a funnel
RELEASE_DROP_UPPER = RELEASE_DROP  # onto a container too (a lower drop was only needed while single-contact deck meshes made boxes creep; see omx_two_arm_world)
LINK_MARGIN = .004      # link3 and link4 (the wrist) must clear every standing container by this much; MuJoCo: failures sat at -3 to -6 mm, passes at +8 mm or more
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


def waypoints(layout, step, here, pick=None, drop=RELEASE_DROP, drop_upper=RELEASE_DROP_UPPER):
    """Teacher path of one step as (name, xy, z, yaw, grip): approach, grasp, lift, carry, lower, release, retreat. grip is open/hold."""
    a, b = dict(layout.sites[step["from"]]), layout.sites[step["to"]]
    if pick:  # the container's true pose at pick time (teacher with ground truth, no perception)
        a["xy"], a["yaw"] = pick
    z_up = carry_z(layout, here, step["from"], step["to"])
    za, zb = layout.hold_z(step["from"]), layout.hold_z(step["to"]) + (0 if b["kind"] == "belt" else drop_upper if b.get("layer", 0) > 0 else drop)  # released this far above its seat: 5 mm on studs and temp lanes, less on a lower container (a drop onto a container spins it)
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


def solve_chain(arm, wps, q0, samples=12, roll_floor=None, branch="best"):
    """Walk the waypoints with continuous IK (warm start, as the teacher moves). The jaw closes the same way turned 180 deg, so joint5 has
    two branches: seeds on both are tried and the branch whose joint5 stays highest above roll_floor wins (a path needing joint5 past its
    limit on one branch is solved on the other). branch="other" takes the second-best branch (the jaw turned 180 deg), for the feasibility matrix. Returns (ok, approach q, joint path, note)."""
    note, found = "no branch converged", []
    for j5 in (q0[4], -1.5, -.4, 0., .8, 1.5, 1.9):
        seed = np.array(q0, float)
        seed[4] = j5
        first = np.array([*wps[0][1], wps[0][2]])
        ok, q, err = arm.reach(seed, first, wps[0][3])
        if not ok:
            note = f"approach {err * 1000:.1f} mm short at x {first[0]:.3f} y {first[1]:.3f} z {first[2]:.3f}"
            continue
        approach, path, last, yaw_last, failed = q, [q.copy()], first, wps[0][3], None
        for name, xy, z, yaw, _ in wps[1:]:
            target = np.array([*xy, z])
            for s in np.linspace(0, 1, samples + 1)[1:]:
                q, e_pos, e_rot = arm.ik(q, last + (target - last) * s, yaw_last + (yaw - yaw_last) * s, 40)
                if e_pos > 1e-3 or e_rot > .03:
                    failed = f"{name} {e_pos * 1000:.1f} mm / {e_rot:.2f} rad off at x {xy[0]:.3f} y {xy[1]:.3f} z {z:.3f}"
                    break
                path.append(q.copy())
            if failed:
                break
            last, yaw_last = target, yaw
        if failed:
            note = failed
            continue
        found.append((min(float(p[4]) for p in path), approach, path))
        found = [f for k, f in enumerate(found) if all(abs(f[1][4] - g[1][4]) > .3 for g in found[:k])]  # one entry per distinct branch
        if branch == "best" and roll_floor is not None and found[-1][0] >= roll_floor:
            break
    found.sort(key=lambda f: -f[0])
    pick = 0 if branch == "best" else 1
    return (True, found[pick][1], found[pick][2], None) if len(found) > pick else (False, None, [], note if not found else "no second branch")


def link_clearance(layout, arm, path, here):
    """Smallest distance (m) from the link3 and link4 meshes along the joint path to any container standing on a site in `here`
    (container name -> site): vertex samples of the real URDF meshes against the 90 x 30 x 30 mm boxes. Negative means inside."""
    boxes = [(np.array([*layout.sites[s]["xy"], layout.sites[s]["z"]]), layout.sites[s]["yaw"]) for s in here.values() if s != "belt"]
    points = {n: kin.link_points(n) for n in ("link3", "link4")}
    best = 1e9
    for q in path:
        for i, name in ((2, "link3"), (3, "link4")):
            R, p = arm.link_poses(q)[i]
            world = points[name] @ R.T + p
            for c, yaw in boxes:
                d = world - c
                cs, sn = math.cos(-yaw), math.sin(-yaw)
                local = np.stack([cs * d[:, 0] - sn * d[:, 1], sn * d[:, 0] + cs * d[:, 1], d[:, 2]], 1)
                q_ = np.abs(local) - np.array([.045, .015, .015])
                best = min(best, float((np.linalg.norm(np.maximum(q_, 0), axis=1) + np.minimum(q_.max(1), 0)).min()))
    return best


def check_reach(layout, step, here, arm):
    """Reach of one step with the step's arm inside the plan's joint limits. Returns (problems, joint path, approach q)."""
    ok, approach, path, note = solve_chain(arm, waypoints(layout, step, here), arm.home, roll_floor=layout.roll_floor)
    if not ok:
        return [f"{step['id']}: {arm.name} cannot reach it tool-down inside the plan's joint limits: {note}"], [], None
    return [], path, approach


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
        if not bad:
            here_after = {k: v for k, v in here.items() if k != c}
            solved = layout.arms[arm]
            reach_problems, path, _ = check_reach(layout, step, here_after, solved)
            problems += reach_problems
            wrist = link_clearance(layout, solved, path, here_after) if path else None
            if wrist is not None and wrist < LINK_MARGIN:
                problems.append(f"{sid}: {arm}'s wrist (link3/4) comes within {wrist * 1000:.0f} mm of a standing container (needs {LINK_MARGIN * 1000:.0f} mm): "
                                "it would hit the neighbouring column; take the neighbour away first or use the other arm")
            other = next(n for n in layout.arms if n != arm)
            gap = clearance(solved, home_pose[other], path, layout.arms[other]) if path else None
            if gap is not None and gap < 2 * ARM_RADIUS + ARM_MARGIN:
                problems.append(f"{sid}: {arm} passes {gap * 1000:.0f} mm from {other} parked at home (needs {1000 * (2 * ARM_RADIUS + ARM_MARGIN):.0f})")
            roll = min((float(q[4]) for q in path), default=0.)
            records.append(dict(step=sid, arm=arm, joints_ok=not reach_problems, min_roll_rad=round(roll, 3), roll_below_floor=roll < layout.roll_floor, min_arm_gap_mm=None if gap is None else round(gap * 1000, 1), min_wrist_gap_mm=None if wrist is None or wrist > 1 else round(wrist * 1000, 1)))
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
