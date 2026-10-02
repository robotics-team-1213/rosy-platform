#!/usr/bin/env python3
"""D-395 S2 Gazebo bench driver: 4 robots, CORE + loc_assist + Fleet, zero human input.

Builds on the S1 driver (`d395_s1_bench.Bench`: launch, CORE polling, scores, teardown) and adds
what four robots need. One call is one power-on of layout `q`:

  r1 on square A, r2 on square B, r3 and r4 off-slot   (s2a: all reach LOCALIZED)

optionally with, in this order,

  --traffic  (s2d) homing in traffic, during the power-on: once r1 and r2 are LOCALIZED and r4
             (lone-ish, never trusted) is in CANDIDATES with its ladder rotation, r1 and r2 get
             Fleet goals that pass about 0.5 m from r4, through the console (`POST
             /api/fleet/robots/<id>/goal`), so the traffic keep-out and hold decide;
  phase c    (s2c) forced mirror on r4 with 4 robots: detected in time, nobody else accused;
  phase b    (s2b) simultaneous re-arbitration: `safety/pickup` on r1 and r4 at once, both
             teleported, set down; r4 lands on the 180-degree twin of its old pose, so a stale
             anchor at r4's old pose would hand r1's twin a `peers` cue (the "dragged" trap).

Timeouts are **sim seconds** (the host runs Gazebo far below real time), each capped in wall
time by `--max-wall`. Gazebo truth for all robots comes from one `pose/info` read (falls back
to `gz model`); the summary computes the minimum pairwise distance from that trail.
The bench polls `/api/fleet/state` every second, as the console UI does: Fleet's traffic,
trust and queue release run on that read.

  python tools/sim/d395_s2_bench.py --out /rosy_d395e_runs/q1 --traffic --phases c,b
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d395_s1_bench as s1  # noqa: E402
from d395_truth import mirror  # noqa: E402

HALF_PI = math.pi / 2
WORLD = s1.WORLD

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
#: CORE navigation states of a live goal (NAV_STATES); ARRIVED/IDLE/CANCELED/FAILED are not.
ACTIVE_NAV = ("PLANNING", "NAVIGATING", "BLOCKED")

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


class Bench(s1.Bench):
    SCENARIOS = SCENARIOS

    def __init__(self, args):
        # Set before the S1 constructor: it starts the sampling thread.
        self.fleet_rows, self.fleet_last, self.fleet_at = {}, {}, -math.inf
        self.latest_poses = (-math.inf, {})
        self.traffic = None
        super().__init__(args)
        self.sc = SCENARIOS[args.scenario]
        self.record["layout_problems"] = scenario_problems(self.sc)
        self.record["t0_epoch"] = time.time() - (time.monotonic() - self.t0)

    def rid(self, index):
        return self.robots[index]

    # --- truth and clock ------------------------------------------------------------------
    def read_poses(self):
        text = self.run_quiet(["gz", "topic", "-e", "-n", "1", "-t", f"/world/{WORLD}/pose/info"], 15.0)
        poses = parse_pose_v(text, set(self.robots))
        for rid in self.robots:
            if rid not in poses:
                pose = s1.parse_gz_model_pose(self.run_quiet(["gz", "model", "-m", rid, "-p"], 20.0))
                if pose is not None:
                    poses[rid] = pose
        self.latest_poses = (time.monotonic(), poses)
        return poses

    def truth(self, rid):
        at, poses = self.latest_poses
        if time.monotonic() - at > 1.5 or rid not in poses:
            poses = self.read_poses()
        return poses.get(rid)

    def sample_clock(self):
        while not self.stopping.is_set():
            t = self.t()
            text = self.run_quiet(["gz", "topic", "-e", "-n", "1", "-t", f"/world/{WORLD}/stats"], 8.0)
            sim = re.search(r"sim_time\s*\{\s*sec:\s*(\d+)(?:\s*nsec:\s*(\d+))?", text)
            rtf = re.search(r"real_time_factor:\s*([0-9.eE+-]+)", text)
            if sim:
                self.clock_samples.append((t, int(sim.group(1)) + int(sim.group(2) or 0) * 1e-9,
                                           float(rtf.group(1)) if rtf else None))
            for rid, pose in self.read_poses().items():
                self.trail.append((t, rid, *pose))
            self.stopping.wait(1.0)

    def sim_now(self):
        return self.clock_samples[-1][1] if self.clock_samples else None

    def wait(self, until, timeout_s, period=0.5):
        """As S1, but `timeout_s` is sim seconds, capped at timeout_s / --min-rtf and --max-wall."""
        start_wall, start_t, start_sim = time.monotonic(), self.t(), None
        cap = min(timeout_s / self.args.min_rtf, self.args.max_wall)
        snaps = {}
        while True:
            dead = [p.pid for p in self.procs if p.poll() is not None]
            if dead:
                raise RuntimeError(f"launched process exited: {dead}")
            snaps = self.poll()
            if until(snaps):
                return snaps, True
            sim = self.sim_now()
            if start_sim is None:   # the first sample taken after the wait began, not an older one
                start_sim = next((s for t, s, _ in self.clock_samples if t >= start_t), None)
            if start_sim is not None and sim is not None and sim - start_sim >= timeout_s:
                return snaps, False
            if time.monotonic() - start_wall >= cap:
                return snaps, False
            time.sleep(period)

    # --- Fleet ----------------------------------------------------------------------------
    def fleet(self, method, path, body=None, timeout=5.0):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.args.fleet_port}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"null")
            except ValueError:
                return exc.code, None
        except (OSError, ValueError):
            return None, None

    def fleet_state(self):
        """The console UI's read: it runs Fleet traffic, trust and queue release."""
        if time.monotonic() - self.fleet_at < 1.0:
            return None
        self.fleet_at = time.monotonic()
        code, body = self.fleet("GET", "/api/fleet/state", timeout=8.0)
        if code != 200 or not body:
            return None
        rows = self.fleet_rows = {row["robot_id"]: row for row in body.get("robots", ())}
        for rid, row in rows.items():
            key = json.dumps([row.get("goal"), row.get("queued"), row.get("held"), row.get("yielding")],
                             sort_keys=True, default=str)
            if key != self.fleet_last.get(rid):
                self.fleet_last[rid] = key
                self.note("fleet", robot=rid, goal=row.get("goal"), queued=row.get("queued"),
                          held=row.get("held"), yielding=row.get("yielding"),
                          badge=row.get("localization"))
        return rows

    def poll(self):
        snaps = super().poll()
        self.fleet_state()
        if self.traffic is not None:
            self.traffic_tick(snaps, self.fleet_rows)
        return snaps

    # --- s2d: homing in traffic -----------------------------------------------------------
    def arm_traffic(self):
        tr = self.sc["traffic"]
        self.traffic = {"homer": self.rid(tr["homer"]), "started": None, "done": False,
                        "drivers": {self.rid(i): {"legs": legs, "leg": 0, "posted": None, "posted_sim": None, "attempts": 0,
                                                  "navigating": False, "done": []}
                                    for i, legs in tr["drivers"].items()},
                        "posts": [], "homer_at_start": None}

    def traffic_tick(self, snaps, rows):
        tr = self.traffic
        if tr["done"]:
            return
        homer = tr["homer"]
        if tr["started"] is None:
            drivers_ok = all(self.loc_state(snaps, d) == "LOCALIZED" for d in tr["drivers"])
            mission = self.missions.get(homer) or {}
            # Start while the homer's ladder mission runs. If the homer localizes without one,
            # start anyway and record it, so the phase is never silently skipped.
            if not drivers_ok or not (mission.get("state") == "running"
                                      or self.loc_state(snaps, homer) == "LOCALIZED"):
                return
            tr["started"] = self.t()
            tr["homer_at_start"] = {"state": self.loc_state(snaps, homer), "mission": mission,
                                    "truth": self.truth(homer)}
            self.note("traffic_start", **tr["homer_at_start"])
        now = time.monotonic()
        for rid, d in tr["drivers"].items():
            if d["leg"] >= len(d["legs"]):
                continue
            nav = ((snaps.get(rid) or {}).get("navigation"))
            queued = (rows.get(rid) or {}).get("queued")
            goal = d["legs"][d["leg"]]
            if d["posted"] is not None:
                if queued:
                    # Held, queued or yielding: an ARRIVED now (a bay) is not this leg; the
                    # released goal must be seen driving again.
                    d["navigating"] = False
                elif nav in ACTIVE_NAV:
                    d["navigating"] = True
                elif d["navigating"] and nav == "ARRIVED":
                    truth = self.truth(rid)
                    off = None if truth is None else round(math.dist(truth[:2], goal[:2]), 3)
                    d["done"].append({"leg": d["leg"], "t": self.t(), "truth": truth, "off_goal_m": off})
                    self.note("traffic_leg", robot=rid, leg=d["leg"], truth=truth, off_goal_m=off)
                    d["leg"], d["posted"], d["navigating"], d["attempts"] = d["leg"] + 1, None, False, 0
                    continue
                # Re-post only when Fleet holds nothing for it and it is not driving: a goal
                # Nav2 aborted (S1: compute_path_to_pose timeouts under load) or never started.
                sim, sim_posted = self.sim_now(), d["posted_sim"]
                slow = sim is None or sim_posted is None or sim - sim_posted >= 5.0
                if queued or nav in ACTIVE_NAV or now - d["posted"] < 30.0 or not slow or d["attempts"] >= 4:
                    continue
            x, y, yaw = goal
            code, body = self.fleet("POST", f"/api/fleet/robots/{rid}/goal", {"x": x, "y": y, "yaw": yaw},
                                    timeout=45.0)     # S2 q0: 15 s timed out at load 150
            d["posted"], d["posted_sim"], d["navigating"] = now, self.sim_now(), False
            d["attempts"] += 1
            tr["posts"].append({"t": self.t(), "robot": rid, "leg": d["leg"], "code": code, "body": body})
            self.note("traffic_goal", robot=rid, leg=d["leg"], code=code, body=body)
        if all(d["leg"] >= len(d["legs"]) for d in tr["drivers"].values()):
            tr["done"] = True
            self.note("traffic_done")

    def traffic_finish(self):
        """After the power-on: let the drivers finish their legs (sim timeout), then record."""
        tr = self.traffic
        if tr is None:
            return True
        _, done = self.wait(lambda s: tr["done"], self.args.traffic_timeout)
        cancels = {}
        if not done:
            # A goal left in Fleet would be released or keep driving during phases c and b.
            for rid in tr["drivers"]:
                cancels[rid] = self.fleet("POST", f"/api/fleet/robots/{rid}/cancel", timeout=15.0)
            self.fleet_at = -math.inf
            self.fleet_state()
            cancels["left_in_fleet"] = {rid: [row.get("goal"), row.get("queued")]
                                        for rid, row in self.fleet_rows.items()
                                        if rid in tr["drivers"] and (row.get("goal") or row.get("queued"))}
            self.note("traffic_cancel", **cancels)
        tr["finished_at"] = self.t()
        self.record["phases"]["traffic"] = {
            "done": done, "homer": tr["homer"], "started": tr["started"], "finished": tr["finished_at"],
            "homer_at_start": tr["homer_at_start"], "posts": tr["posts"], "cancels": cancels,
            "legs": {rid: d["done"] for rid, d in tr["drivers"].items()},
            "planned": {rid: len(d["legs"]) for rid, d in tr["drivers"].items()},
            "homer_localized": self.first_time(tr["homer"], "LOCALIZED"),
            "rtf": self.rtf(), "load": self.load()}
        self.traffic = None
        self.note("traffic_phase_done", done=done)
        return True

    # --- s2c: forced mirror ---------------------------------------------------------------
    def forced_mirror(self):
        target = self.rid(self.sc["mirror"])
        start = self.t()
        truth = self.truth(target) or s1.last_trail_pose(self.trail, target)
        if truth is None:
            self.record["phases"]["mirror"] = {"error": f"no truth for {target}"}
            return False
        x, y, yaw = mirror(truth)
        cov = [0.0] * 36
        cov[0] = cov[7] = 0.05 ** 2
        cov[35] = math.radians(5) ** 2
        payload = ("{header: {frame_id: map}, pose: {pose: {position: {x: %f, y: %f}, orientation: "
                   "{z: %f, w: %f}}, covariance: %s}}" % (x, y, math.sin(yaw / 2), math.cos(yaw / 2), cov))
        sim_start = self.sim_now()
        self.ros_pub(f"/{target}/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped", payload)
        injected, sim_injected = self.t(), self.sim_now()
        # Any exit from LOCALIZED counts (SUSPECT can turn CANDIDATES between two polls).
        snaps, detected = self.wait(lambda s: self.loc_state(s, target) not in ("LOCALIZED", None),
                                    self.args.detect_window)
        locked = self.verdict(target, snaps)
        self.note("mirror_injected", target=target, detected=detected, locked=locked)
        snaps, done = self.wait(lambda s: self.all_localized(s) and bool(self.left_localized(start, only=target)),
                                self.args.localize_timeout)
        if done:
            snaps, _ = self.wait(lambda s: not self.all_localized(s), 5.0)
        left = self.left_localized(start, only=target)
        phase = {"target": target, "t_pub_start": start, "sim_pub_start": sim_start, "t_injected": injected,
                 "sim_injected": sim_injected, "detected": detected, "target_after_injection": locked,
                 "target_left": left[0] if left else None,
                 "accused": self.left_localized(start, exclude=target),
                 "t_target_localized": self.first_time(target, "LOCALIZED", start), "done": done,
                 "rtf": self.rtf(), "load": self.load(), **{rid: self.verdict(rid, snaps) for rid in self.robots}}
        self.record["phases"]["mirror"] = phase
        self.note("mirror_done", **{k: v for k, v in phase.items() if k != "load"})
        return done

    def all_localized(self, snaps):
        return self.both_localized(snaps)

    def left_localized(self, after, exclude=(), only=None):
        """(t, robot, state, reason) of every non-LOCALIZED state row since `after`, for the
        robots not in `exclude` (or only robot `only`). CORE's `state_stale` rows are skipped."""
        rows = []
        for row in self.timeline:
            loc = row.get("loc") or {}
            rid = row.get("robot")
            if (row["what"] == "state" and row["t"] >= after and rid not in exclude
                    and (only is None or rid == only) and loc.get("state") not in (None, "LOCALIZED")
                    and loc.get("reason") != "state_stale"):     # CORE's wall-time blip, not an accusation
                rows.append((row["t"], row["robot"], loc.get("state"), loc.get("reason")))
        return rows

    # --- s2b: simultaneous re-arbitration -------------------------------------------------
    def simultaneous_pickup(self):
        pk = self.sc["pickup"]
        lifted = [self.rid(i) for i in pk["robots"]]
        start = self.t()
        before = [self.truth(rid) or s1.last_trail_pose(self.trail, rid) or self.sc["spawn"][i]
                  for i, rid in enumerate(self.robots)]
        # Drops and the stale trap from where the robots stand now (traffic may have moved them).
        drops = [drop_layout(before, pk)[i] for i in pk["robots"]]
        problems, trap = drop_problems(before, pk), stale_trap(before, pk)
        self.note("pickup2_layout", drops=drops, problems=problems, stale_trap=trap)

        def all_at_once(active):
            threads = [threading.Thread(target=self.pickup, args=(rid, active)) for rid in lifted]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        all_at_once(True)
        t_lifted = self.t()
        for rid, drop in zip(lifted, drops):
            self.teleport(rid, drop)
        snaps, _ = self.wait(lambda s: False, 3.0)
        held = {rid: self.loc_state(snaps, rid) for rid in lifted}
        all_at_once(False)
        t_down = self.t()
        snaps, done = self.wait(lambda s: all(self.loc_state(s, r) == "LOCALIZED" for r in lifted),
                                self.args.localize_timeout)
        if done:
            snaps, _ = self.wait(lambda s: not self.all_localized(s), 5.0)
        phase = {"lifted": lifted, "drops": drops, "layout_problems": problems, "stale_trap": trap,
                 "before": before,
                 "t_start": start, "t_lifted": t_lifted, "t_set_down": t_down, "state_while_held": held,
                 "t_localized": {rid: self.first_time(rid, "LOCALIZED", t_down) for rid in lifted},
                 "others_left_localized": self.left_localized(start, exclude=lifted), "done": done,
                 "rtf": self.rtf(), "load": self.load(), **{rid: self.verdict(rid, snaps) for rid in self.robots}}
        self.record["phases"]["pickup2"] = phase
        self.note("pickup2_done", **{k: v for k, v in phase.items() if k not in ("load", "before")})
        return done


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="q")
    p.add_argument("--out", required=True)
    p.add_argument("--traffic", action="store_true", help="s2d: homing in traffic during the power-on")
    p.add_argument("--phases", default="", help="comma list after power-on: c (mirror), b (simultaneous pickup)")
    p.add_argument("--check", action="store_true", help="print the layout checks and exit (no ROS)")
    p.add_argument("--ws", default=str(Path(__file__).resolve().parents[2]))
    p.add_argument("--partition", default="rosy_d395e")
    p.add_argument("--domain", type=int, default=99)
    p.add_argument("--api-port", type=int, default=18940)
    p.add_argument("--fleet-port", type=int, default=18995)
    p.add_argument("--localize-timeout", type=float, default=150.0, help="sim s")
    p.add_argument("--traffic-timeout", type=float, default=120.0, help="sim s after the power-on")
    p.add_argument("--detect-window", type=float, default=30.0, help="(c) sim s to wait for SUSPECT")
    p.add_argument("--min-rtf", type=float, default=0.04, help="wall cap = sim timeout / this")
    p.add_argument("--max-wall", type=float, default=1500.0, help="wall cap of any one wait")
    p.add_argument("--loc-param", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--launch-arg", action="append", default=[], metavar="NAME:=VALUE",
                   help="extra gz_multi argument, e.g. nav_composition:=true")
    args = p.parse_args(argv)
    if args.check:
        sc = SCENARIOS[args.scenario]
        print(json.dumps({"problems": scenario_problems(sc), "stale_trap": stale_trap(sc["spawn"], sc["pickup"])},
                         indent=1))
        return
    bench = Bench(args)
    try:
        if args.traffic:
            bench.arm_traffic()
        ok = bench.power_on()
        bench.traffic_finish()       # recorded (and left goals cancelled) even after a failed power-on
        for phase in filter(None, args.phases.split(",")):
            if not ok:
                break
            ok = bench.forced_mirror() if phase == "c" else bench.simultaneous_pickup()
    except KeyboardInterrupt:
        bench.note("interrupted")
    finally:
        bench.stop()
        bench.save()


if __name__ == "__main__":
    main()
