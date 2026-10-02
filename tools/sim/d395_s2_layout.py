"""D-395 S2 bench layouts and pure helpers (no ROS): layout q and its checks, the truth
parser and the collision metric. Used by `d395_s2_bench.py` and `d395_s2_summary.py`."""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d395_truth import mirror  # noqa: E402

HALF_PI = math.pi / 2
#: map_v2_fleet inner wall faces (walls at +-1.4025 / +-0.6275, 5 mm thick).
ARENA_X, ARENA_Y = 1.400, 0.625
#: Brief: collision when two robot centres are closer than 2 x 0.11 m.
ROBOT_R = 0.11
COLLISION_M = 2 * ROBOT_R
#: Spawn and drop points keep this from a wall face. Square B sits 0.105 m from the bottom
#: wall and square A 0.135 m from the top: the squares set the floor (URDF sweep r 0.088).
WALL_CLEAR_M = 0.10
#: Off-slot points, goals and drops keep more room: Nav2's padded radius is 0.115 m.
OPEN_WALL_CLEAR_M = 0.20
#: Spawn and drop points stay this far apart (keep-out 0.45 m, contract §3).
SEP_M = 0.45
#: fleet.localization.cues: PEER_VIEW_M 2.0; matching is 0.15 m, doubled here for margin.
PEER_VIEW_M = 2.0
TWIN_MATCH_M = 0.30
SQUARES = {"A": (-1.26, 0.49), "B": (0.86, -0.52)}

#: Layout q (x, y, yaw). r3/r4 are placed so that no robot's 180-degree twin lands within
#: TWIN_MATCH_M of another robot: a twin hypothesis gets no `peers` support (layout_problems).
SCENARIOS = {
    "q": {
        "spawn": [(-1.26, 0.49, -HALF_PI), (0.86, -0.52, math.pi), (-0.70, -0.20, math.pi), (0.20, 0.25, 0.0)],
        "slots": [0, 1],
        # s2b: lift r1 and r4 together. r4 lands on the twin of wherever it stands ("twin"),
        # r1 where its twin would see r4 at r4's old (stale) pose.
        "pickup": {"robots": [0, 3], "drops": [(0.45, -0.10, HALF_PI), "twin"]},
        # s2c: the off-slot r4; its twin is 0.50 m from r3.
        "mirror": 3,
        # s2d: r4 homes while r1 and r2 run these legs, each passing about 0.5 m from r4.
        "traffic": {"homer": 3, "drivers": {0: [(-0.30, 0.42, 0.0), (-1.00, 0.40, math.pi)],
                                            1: [(0.20, -0.25, math.pi), (0.95, -0.25, 0.0)]}},
    },
}


# --- pure helpers -------------------------------------------------------------------------
def wall_clearance(p):
    """Distance from (x, y) to the nearest inner wall face (negative outside)."""
    return min(ARENA_X - abs(p[0]), ARENA_Y - abs(p[1]))


def on_square(p, tol=0.05):
    return any(math.dist(p[:2], c) <= tol for c in SQUARES.values())


def peer_support(observer, observed, anchors):
    """(truth, twin) `peers` cue for a robot at `observer` (x, y[, yaw]).

    `observed` are the true positions of the robots it sees; `anchors` the positions Fleet
    believes. At the truth an object lands on its observed position; at the twin (the
    point reflection) on that position's mirror. Each score is the share of anchors in view
    of that pose that some placed object lands within TWIN_MATCH_M of (cues.peers_cue)."""
    def score(pose, placed):
        in_view = [a for a in anchors if math.dist(pose[:2], a[:2]) <= PEER_VIEW_M]
        if not in_view:
            return 0.0
        return sum(1 for a in in_view if any(math.dist(a[:2], q) <= TWIN_MATCH_M for q in placed)) / len(in_view)
    truth = score(observer, [o[:2] for o in observed])
    twin = score(mirror((observer[0], observer[1], 0.0)), [mirror((o[0], o[1], 0.0))[:2] for o in observed])
    return truth, twin


def layout_problems(poses, anchors=()):
    """Reasons a layout is unfit for the bench; empty when valid.

    Every pose keeps WALL_CLEAR_M (on a square) or OPEN_WALL_CLEAR_M (elsewhere) from the walls
    and SEP_M from every other pose. Every robot that is not an anchor (index in `anchors`)
    has an anchor in view, and its twin gets no `peers` support from any layout robot."""
    out = []
    for i, p in enumerate(poses):
        need = WALL_CLEAR_M if on_square(p) else OPEN_WALL_CLEAR_M
        if wall_clearance(p) < need:
            out.append(f"r{i + 1} {wall_clearance(p):.3f} m from a wall (< {need})")
        for j in range(i + 1, len(poses)):
            d = math.dist(p[:2], poses[j][:2])
            if d < SEP_M:
                out.append(f"r{i + 1}-r{j + 1} {d:.3f} m apart (< {SEP_M})")
    for i, p in enumerate(poses):
        if i in anchors:
            continue
        others = [q for j, q in enumerate(poses) if j != i]
        truth, _ = peer_support(p, others, [q for j, q in enumerate(poses) if j in anchors])
        if truth <= 0.0:
            out.append(f"r{i + 1} has no anchor in view")
        _, twin = peer_support(p, others, others)
        if twin > 0.0:
            out.append(f"r{i + 1}'s twin gets peers support {twin:.2f}")
    return out


def point_problems(points, fixed, label="goal"):
    """Goals: OPEN_WALL_CLEAR_M from the walls and 2 x COLLISION_M from robots that stay put."""
    out = []
    for g in points:
        if wall_clearance(g) < OPEN_WALL_CLEAR_M:
            out.append(f"{label} {g[:2]} {wall_clearance(g):.3f} m from a wall")
        for q in fixed:
            if math.dist(g[:2], q[:2]) < 2 * COLLISION_M:
                out.append(f"{label} {g[:2]} {math.dist(g[:2], q[:2]):.3f} m from a robot at {q[:2]}")
    return out


def scenario_problems(sc):
    """All layout checks of one scenario: spawn, the s2b drop layout and its stale trap, s2d goals."""
    spawn, slots = sc["spawn"], sc.get("slots", ())
    out = [f"spawn: {m}" for m in layout_problems(spawn, slots)]
    pk = sc.get("pickup")
    if pk:
        out += [f"drop: {m}" for m in drop_problems(spawn, pk)]
    tr = sc.get("traffic")
    if tr:
        homer = spawn[tr["homer"]]
        fixed = [p for i, p in enumerate(spawn) if i not in tr["drivers"]]
        for idx, legs in tr["drivers"].items():
            out += [f"traffic r{idx + 1}: {m}" for m in point_problems(legs, fixed)]
            near = min(math.dist(g[:2], homer[:2]) for g in legs)
            if near > 0.8:
                out.append(f"traffic r{idx + 1}: no leg within 0.8 m of the homer ({near:.2f})")
    return out


def drop_layout(before, pk):
    """Poses after the s2b teleport: each lifted robot at its drop; "twin" is the 180-degree
    twin of where that robot stood."""
    after = list(before)
    for idx, drop in zip(pk["robots"], pk["drops"]):
        after[idx] = mirror(before[idx]) if drop == "twin" else drop
    return after


def drop_problems(before, pk):
    """layout_problems of the drop layout (the robots left standing are the anchors), plus
    "trap disarmed" when no stale anchor would support a lifted robot's twin."""
    stay = [i for i in range(len(before)) if i not in pk["robots"]]
    out = layout_problems(drop_layout(before, pk), stay)
    if not any(twin > 0.0 for _, twin in stale_trap(before, pk).values()):
        out.append("stale-anchor trap disarmed")
    return out


def stale_trap(before, pk):
    """s2b: (truth, twin) `peers` score of each lifted robot if Fleet kept the other lifted
    robot's pre-pickup pose as an anchor. twin > 0 means a stale anchor would drag it."""
    after = drop_layout(before, pk)
    out = {}
    for idx in pk["robots"]:
        other = [i for i in pk["robots"] if i != idx]
        anchors = [after[i] for i in range(len(after)) if i != idx and i not in other] + [before[i] for i in other]
        observed = [after[i] for i in range(len(after)) if i != idx]
        out[f"rosy_{idx + 1:02d}"] = peer_support(after[idx], observed, anchors)
    return out


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def _fields(block):
    return {k: float(v) for k, v in re.findall(rf"\b([xyzw])\s*:\s*({_NUM})", block or "")}


def parse_pose_v(text, names):
    """{name: (x, y, yaw)} for the wanted model names in `gz topic -e` text of a gz.msgs.Pose_V.

    Protobuf text omits zero fields, so a missing x/y/z/w reads 0 (a missing orientation is
    the identity)."""
    out = {}
    marks = list(re.finditer(r'\bname:\s*"([^"]*)"', text or ""))
    for k, m in enumerate(marks):
        if m.group(1) not in names or m.group(1) in out:
            continue
        end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
        body = text[m.end():end]
        pos = re.search(r"position\s*\{([^}]*)\}", body)
        if pos is None:
            continue
        p = _fields(pos.group(1))
        ori = re.search(r"orientation\s*\{([^}]*)\}", body)
        q = _fields(ori.group(1)) if ori else {"w": 1.0}
        qx, qy, qz, qw = (q.get(c, 0.0) for c in "xyzw")
        yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
        out[m.group(1)] = (p.get("x", 0.0), p.get("y", 0.0), yaw)
    return out


def min_pairwise(trail, since=None, until=None):
    """Closest approach of any two robots in a truth trail of (t, robot, x, y, yaw) rows.

    Rows of one sampling round share t. Returns {"min_m", "t", "pair", "rounds", "below"} where
    `below` counts rounds with a pair under COLLISION_M; min_m None without a 2-robot round."""
    rounds = {}
    for t, rid, x, y, *_ in trail:
        if (since is None or t >= since) and (until is None or t <= until):
            rounds.setdefault(t, {})[rid] = (x, y)
    best, below = {"min_m": None, "t": None, "pair": None}, 0
    for t in sorted(rounds):
        poses = sorted(rounds[t].items())
        low = None
        for i, (a, pa) in enumerate(poses):
            for b, pb in poses[i + 1:]:
                d = math.dist(pa, pb)
                if low is None or d < low[0]:
                    low = (d, a, b)
        if low is None:
            continue
        below += low[0] < COLLISION_M
        if best["min_m"] is None or low[0] < best["min_m"]:
            best = {"min_m": round(low[0], 4), "t": t, "pair": [low[1], low[2]]}
    return {**best, "rounds": len(rounds), "below": below}
