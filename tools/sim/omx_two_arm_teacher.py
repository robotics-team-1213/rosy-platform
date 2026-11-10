#!/usr/bin/env python3
"""Scripted two-arm teacher for the `stack` and `rehandle` tasks, with strict per-step and whole-task judging and an mp4 of each run.

    MUJOCO_GL=egl python tools/sim/omx_two_arm_teacher.py run stack --out DIR [--video] [--choice key=value ...]
    python tools/sim/omx_two_arm_teacher.py validate rehandle [--choice key=value ...]      # no MuJoCo needed

One arm moves at a time while the other parks at home, or with --concurrent both arms move at once by the plan's order and zones. The teacher reads the true container pose (no perception) and corrects the placement for
where the container sits in the jaw. MuJoCo answers GEOMETRY only (reach, order, arm collisions, temporary space; D-947): contact and friction
numbers here are not results. A step the geometry cannot do is reported, never moved to a reachable place.
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import palletizing_gripper as jaw  # noqa: E402

FPS = 15
CARRY_SPEED = .05  # m/s; .08 let a 16 g container swing 10 deg in the jaws on the short reach to the near row
OPEN_GAP = dict(belt=.042, ship=.033, temp=.033, outbound=.033)  # 33 mm lets a pad stay inside the 6 mm gaps between rows (release_gap_m of the ship case); the stern bay mouth is 37 mm
HOLD_GAP = .030 - jaw.SQUEEZE_M


RECORDED = ("top", "side", "a_wrist", "b_wrist")  # the cell's four cameras (D-960); the world's overview is not one of them
PREFIX = {"arm_a": "a_", "arm_b": "b_"}


def judge_pose(world, data, cid, site, limits):
    """Container against its target site: position, yaw (180 deg symmetric), height, tilt."""
    s = world.layout.sites[site]
    pos, yaw, tilt = world.pose(data, cid)
    xy = float(np.linalg.norm(pos[:2] - s["xy"])) * 1000
    dyaw = abs(math.degrees(tasks.wrap_pi(yaw - s["yaw"])))
    dz = float(pos[2] - s["z"]) * 1000
    ok = xy <= limits["xy_mm"] and dyaw <= limits["yaw_deg"] and abs(dz) <= limits["z_mm"] and tilt <= limits["tilt_deg"]
    return dict(ok=bool(ok), xy_mm=round(xy, 1), yaw_deg=round(dyaw, 1), z_mm=round(dz, 1), tilt_deg=round(tilt, 1))


class Ctx:
    """What one running step tracks: its arm's contacts, the carried container, the phase, tilts and every container another arm moved
    meanwhile (not a disturbance by this step). The Teacher itself is the context of a sequential step (the policy reads its fields)."""

    def __init__(self, arm):
        self.arm, self.carried, self.phase, self.first, self.tilt, self.held_tilt, self.others = arm, None, "", {}, 0., 0., set()
        self.contacts = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set())


class Teacher:
    SKEW_CASES = (
        (.006, .006, 18.), (.005, -.006, -16.), (.004, .005, -12.),
        (.005, .006, 15.), (.004, -.005, 14.), (.004, .006, -10.),
        (.004, .007, 16.), (.004, -.006, -14.), (.004, .006, 12.),
    )

    def __init__(self, world, data_file=None, frame_hook=None, drop=tasks.RELEASE_DROP, drop_upper=tasks.RELEASE_DROP_UPPER, seed=0,
                 pick_vision=False, belt_skew=False):
        self.rng, self.seed, self.branch, self.carried = np.random.default_rng(seed), seed, "best", None
        self.world, self.layout, self.drop, self.drop_upper = world, world.layout, drop, drop_upper
        self.pick_vision, self.belt_skew, self.skew_i = pick_vision, belt_skew, 0
        self.limits = (data_file or tasks.load())["judge"]
        self.hook = frame_hook or (lambda data, label: None)
        self.contacts, self.phase, self.first, self.tilt, self.n, self.held_tilt = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), "", {}, 0., 0, 0.
        self.others = set()

    def perceive_pick(self, data, sa, true_xy, true_yaw):
        """Detect a skewed/offset container at `sa` from the rendered top camera frame (omx_real2sim pinhole back-projection)."""
        import cv2
        import omx_real2sim as r2s

        cam = r2s.Camera(self.layout.fixture["real_cameras"]["top"], (480, 640))
        bgr = cv2.cvtColor(self.world.render(data, "top"), cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        top_z, box_l, box_w = sa["z"] + self.layout.box[2] / 2, self.layout.box[0], self.layout.box[1]
        cands = []
        for kind, px in r2s.blobs(bgr):
            if kind != "container":
                continue
            xy, yaw, sz = r2s.rect(cam.to_plane(px, top_z))
            for idx, ref, vec in ((0, box_l, (math.cos(yaw), math.sin(yaw))), (1, box_w, (-math.sin(yaw), math.cos(yaw)))):
                if sz[idx] > ref:  # oblique end/side wall widens the contour toward the camera eye
                    sh = (.5 if (cam.eye[0] - xy[0]) * vec[0] + (cam.eye[1] - xy[1]) * vec[1] >= 0 else -.5) * (sz[idx] - ref)
                    xy = (xy[0] - sh * vec[0], xy[1] - sh * vec[1])
                    sz = (ref, sz[1]) if idx == 0 else (sz[0], ref)
            if math.dist(xy, sa["xy"]) <= .045 and .040 <= sz[0] <= .125:
                cx, cy = int(round(px[:, 0].mean())), int(round(px[:, 1].mean()))
                h = float(np.median(hsv[max(0, cy - 2):cy + 3, max(0, cx - 2):cx + 3, 0]))
                col = "red" if h < 6 or h >= 160 else "orange" if h < 22 else "green" if h < 90 else "purple"
                cands.append((math.dist(xy, true_xy), xy, yaw, sz, col))
        if not cands:
            return None
        _, xy, yaw, sz, col = min(cands, key=lambda x: x[0])
        return xy, yaw, dict(colour=col, xy_err_mm=round(math.dist(xy, true_xy) * 1000, 2),
                             yaw_err_deg=round(abs(math.degrees(r2s.fold(yaw - true_yaw))), 2),
                             seen_xy=[round(xy[0], 4), round(xy[1], 4)], seen_yaw_deg=round(math.degrees(yaw), 1),
                             size_mm=[round(sz[0] * 1000, 1), round(sz[1] * 1000, 1)])

    def frame(self, data, targets, label, ctxs=None):
        """One video frame of physics. Sequential: the Teacher is the one context. Two arms at once: each context gets its own arm's
        link and pad contacts; arm-arm contacts go to both."""
        self.n += 1
        self.world.advance(data, targets)
        both = ctxs is not None
        ctxs = ctxs if both else [self]
        rep = self.world.contact_report(data, {c.carried for c in ctxs if c.carried}, by_arm=both)
        for c in ctxs:
            p = PREFIX[c.arm] if both else None
            mine = dict(arm_arm=rep["arm_arm"], arm_other={x for x in rep["arm_other"] if p is None or x[0].startswith(p)},
                        pad_neighbour={x[1] for x in rep["pad_neighbour"] if x[0] == p} if both else rep["pad_neighbour"])
            for k, v in mine.items():
                if v - c.contacts[k] and k != "pad_neighbour":
                    c.first.setdefault(k, f"{c.phase}@frame{self.n}")
                c.contacts[k] |= v
            if c.carried and c.phase in ("lift", "carry", "lower"):
                c.held_tilt = max(c.held_tilt, self.world.pose(data, c.carried)[2])
        self.hook(data, label)

    def q_now(self, data, arm):
        return data.qpos[self.world.q[arm]].copy()

    @staticmethod
    def move_g(q_from, q_to, seconds):
        """Joint-space move of one arm, one target per frame."""
        n = max(1, round(seconds * FPS))
        for i in range(1, n + 1):
            s = i / n
            yield q_from + s * s * (3 - 2 * s) * (q_to - q_from)

    def tcp_move_g(self, ctx, ik_arm, q, p_from, p_to, yaw_from, yaw_to, grip, seconds, shift=None):
        """TCP straight line with IK warm start, one target per frame. Returns the final q and the worst IK error (m) met on the way."""
        n, worst = max(1, round(seconds * FPS)), 0.
        for i in range(1, n + 1):
            s = i / n
            s = s * s * (3 - 2 * s)
            pos, yaw = p_from + s * (p_to - p_from), yaw_from + s * (yaw_to - yaw_from)
            if shift is not None:
                pos = pos + shift(pos, yaw, q)
            q, err, rot = ik_arm.ik(q, pos, yaw, 30)
            worst = max(worst, err)
            ctx.tilt = max(ctx.tilt, rot)
            yield np.append(q[:5], grip)
        return q, worst

    def run_step(self, data, step, here):
        """One step with the other arm holding home (sequential)."""
        L = self.layout
        idle = {o: L.sim_arms[o].wait.copy() for o in L.arms if o != step["arm"]}
        gen = self.step_gen(data, step, here, self)
        try:
            while True:
                self.frame(data, {step["arm"]: next(gen), **idle}, step["id"])
        except StopIteration as stop:
            return stop.value

    def step_gen(self, data, step, here, ctx):
        """One step as a generator of this arm's joint targets, one per frame; returns the judged row."""
        w, L = self.world, self.layout
        arm, c, ik_arm = step["arm"], step["container"], L.sim_arms[step["arm"]]
        sa, sb = L.sites[step["from"]], L.sites[step["to"]]
        ctx.tilt = ctx.held_tilt = 0.
        ctx.contacts, ctx.carried, ctx.first, ctx.phase = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), c, {}, "approach"
        if step["from"] == "belt":
            yield from self.belt_in_g(data, step)
        pos0, yaw0, _ = w.pose(data, c)
        row = dict(step=step["id"], container=c, arm=arm, source=step["from"], target=step["to"])
        if np.linalg.norm(pos0[:2] - sa["xy"]) > .035:
            return dict(row, result="blocked", reason=f"{c} is {np.linalg.norm(pos0[:2] - sa['xy']) * 1000:.0f} mm from {step['from']}")
        pick_xy, pick_yaw = pos0[:2], yaw0
        if self.pick_vision:
            seen = self.perceive_pick(data, sa, pos0[:2], yaw0)
            if seen is None:
                return dict(row, result="blocked", reason=f"top camera did not see {c} at {step['from']}")
            pick_xy, pick_yaw, row["vision_pick"] = seen[0], seen[1], seen[2]
        before = {o: w.pose(data, o) for o in here}  # the containers on the cell; one that left with Pinky is not a neighbour
        wps = tasks.waypoints(L, step, here, pick=(pick_xy, pick_yaw), drop=self.drop, drop_upper=self.drop_upper)
        g_open, g_to = jaw.angle_for_gap(OPEN_GAP[sa["kind"]]), jaw.angle_for_gap(OPEN_GAP[sb["kind"]])
        g_hold = jaw.angle_for_gap(HOLD_GAP)
        q = self.q_now(data, arm)
        # solve from home as the validator does: seeded from the side wait pose the IK fell on other branches or missed the approach
        ok, q_app, _, note = tasks.solve_chain(ik_arm, wps, ik_arm.home, roll_floor=L.roll_floor, branch=self.branch)
        if not ok:
            return dict(row, result="unreachable", reason=f"{arm} cannot do the step tool-down inside the limits: {note}")
        yield from self.move_g(np.append(q[:5], g_open), np.append(q_app[:5], g_open), 2.5)
        q, off, worst, prev, held = q_app, None, 0., wps[0], {}
        for name, xy, z, yaw, grip in wps[1:]:
            ctx.phase = name
            p_from, p_to = np.array([*prev[1], prev[2]]), np.array([*xy, z])
            yaw_from = prev[3]
            # once the container is held its offset in the jaw is known: aim the container centre, not the TCP
            shift = None if off is None or name in ("grasp", "close", "lift") else (lambda pos, yw, qq: self._hold_shift(ik_arm, off, qq, yw, pos))
            seconds = 1.5 if name in ("grasp", "lower", "lift", "retreat") else max(1.5, float(np.linalg.norm(p_to - p_from)) / CARRY_SPEED)
            if name in ("close", "release"):
                if name == "release":
                    held["yaw_before_release_deg"] = round(math.degrees(tasks.wrap_pi(w.pose(data, c)[1] - sb["yaw"])), 1)
                if name == "close":
                    held["yaw_before_close_deg"] = round(math.degrees(tasks.wrap_pi(w.pose(data, c)[1] - sb["yaw"])), 1)
                a0, a1 = (g_open, g_hold) if name == "close" else (g_hold, g_to)
                n = round(1.5 * FPS)
                for i in range(1, n + 1):
                    yield np.append(q[:5], a0 + (a1 - a0) * i / n)
                if name == "close":
                    tcp, R = w.tcp(data, arm)
                    off = R.T @ (w.pose(data, c)[0] - tcp)
                    held["offset_in_jaw_mm"] = [round(float(v) * 1000, 1) for v in off]
                if name == "release":
                    ctx.carried = None
            else:
                g = g_hold if grip == "hold" else (g_open if name in ("approach", "grasp") else g_to)
                q, e = yield from self.tcp_move_g(ctx, ik_arm, q, p_from, p_to, yaw_from, yaw, g, seconds, shift)
                worst = max(worst, e)
            prev = (name, xy, z, yaw, grip)
        ctx.phase = "park"
        yield from self.move_g(np.append(q[:5], g_to), np.append(ik_arm.wait[:5], g_to), 2.5)
        for _ in range(round(.7 * FPS)):
            yield np.append(ik_arm.wait[:5], g_to)
        return dict(self.verdict(data, step, row, before, ctx), held=held, worst_ik_error_mm=round(worst * 1000, 2))

    def belt_in_g(self, data, step):
        """The next container arrives; the belt pick pose varies inside the fixture's infeed tolerance, seed 0 is the nominal pose."""
        f, arm = self.layout.fixture, step["arm"]
        if self.belt_skew:
            dx, dy, y_deg = self.SKEW_CASES[self.skew_i % len(self.SKEW_CASES)]
            self.skew_i += 1
            j = (dx, dy, math.radians(y_deg))
        else:
            j = (0., 0., 0.) if self.seed == 0 else (*self.rng.uniform(-1, 1, 2) * f["infeed_jitter_xy_m"], float(self.rng.uniform(-1, 1)) * f["infeed_yaw_jitter_rad"])
        self.world.put(data, step["container"], "belt", jitter=j)
        for _ in range(8):
            yield self.q_now(data, arm)

    def run_concurrent(self, data, task, here, max_s=900):
        """Both arms at once (D-778 L1). Each arm runs its own steps in the given order; a step starts when its `after` steps are done,
        its `after_pick` steps have lifted their container (the conveyor holds one) and its zones are free. It holds its pick zones until
        the carry ends (a carry from the conveyor to one side sweeps the middle: two arms met there, 2026-11-08) and its place zones
        until it is done; one arm parks at a time, the other holds its pose; an arm without a step holds its last pose (the wait pose after a park).
        Returns (rows, per-step start and end seconds, None or why it stopped)."""
        L = self.layout
        queue = {a: [s for s in task["steps"] if s["arm"] == a] for a in L.arms}
        status, held, running, rows, timing = {}, {}, {}, [], {}
        last = {a: L.sim_arms[a].wait.copy() for a in L.arms}
        frames = 0
        while any(queue.values()) or running:
            for arm in L.arms:
                if arm in running or not queue[arm]:
                    continue
                s = queue[arm][0]
                pick, place = set(s["zones"][0]), set(s["zones"][1])
                ready = all(status.get(d) == "done" for d in s.get("after", [])) and all(status.get(d) for d in s.get("after_pick", []))
                if ready and not any(z in held for z in pick | place):
                    queue[arm].pop(0)
                    held.update({z: s["id"] for z in pick | place})
                    ctx = Ctx(arm)
                    ctx.step, ctx.here = s, {k: v for k, v in here.items() if k != s["container"]}  # what a recorder needs for this step's goal
                    running[arm] = (s, self.step_gen(data, s, ctx.here, ctx), ctx, pick - place)
                    timing[s["id"]] = dict(arm=arm, start_s=round(frames / FPS, 2))
            if not running:
                return rows, timing, f"deadlock: {[q[0]['id'] for q in queue.values() if q]} cannot start"
            targets = {}
            parking = [a for a, r in running.items() if r[2].phase == "park"]
            for arm, (s, gen, ctx, pick_only) in list(running.items()):
                if ctx.phase == "park" and parking[0] != arm:  # one arm parks at a time: two parks met link5 to link5 (MuJoCo 2026-11-08)
                    continue
                try:
                    targets[arm] = last[arm] = next(gen)
                except StopIteration as stop:
                    rows.append(stop.value)
                    print(json.dumps(stop.value), flush=True)
                    status[s["id"]] = "done"
                    timing[s["id"]]["end_s"] = round(frames / FPS, 2)
                    held = {z: i for z, i in held.items() if i != s["id"]}
                    here[s["container"]] = s["to"]
                    self.off_stand(data, s, here)
                    del running[arm]
                    continue
                if ctx.phase in ("carry", "lower", "release", "retreat", "park") and not status.get(s["id"]):
                    status[s["id"]] = "picked"  # lifted: the conveyor may bring the next one
                    timing[s["id"]]["picked_s"] = round(frames / FPS, 2)
                    here.pop(s["container"], None)
                if ctx.phase in ("lower", "release", "retreat", "park"):  # the carry has left the source side (it crossed the middle)
                    held = {z: i for z, i in held.items() if not (i == s["id"] and z in pick_only)}
            ctxs = [r[2] for r in running.values()]
            for c in ctxs:
                c.others |= {o.carried for o in ctxs if o is not c and o.carried}
            self.frame(data, {a: targets.get(a, last[a]) for a in L.arms}, " | ".join(r[0]["id"] for r in running.values()) or "wait", ctxs)
            frames += 1
            if frames > max_s * FPS:
                return rows, timing, f"timeout after {max_s} s"
        return rows, timing, None

    def belt_in(self, data, step, idle):
        """belt_in_g for a caller that drives frames itself with the other arm holding `idle` (the policy evaluation)."""
        for target in self.belt_in_g(data, step):
            self.frame(data, {step["arm"]: target, **idle}, step["id"])

    def verdict(self, data, step, row, before, ctx=None):
        """The same judgement for the teacher and a learned policy: the container, its neighbours, and what the arms touched. Containers
        another arm moved meanwhile (ctx.others) are that arm's, not disturbed neighbours."""
        w, ctx = self.world, ctx or self
        pose = judge_pose(w, data, step["container"], step["to"], self.limits)
        moved = []
        for o, (p, yw, tl) in before.items():
            if o in ctx.others:
                continue
            p2, yw2, tl2 = w.pose(data, o)
            d = float(np.linalg.norm(p2 - p)) * 1000
            dyaw = abs(math.degrees(tasks.wrap_pi(yw2 - yw)))
            if d > self.limits["neighbour_mm"] or abs(tl2 - tl) > self.limits["neighbour_tilt_deg"] or dyaw > self.limits["neighbour_yaw_deg"]:
                moved.append(f"{o} {d:.1f} mm {dyaw:.1f} deg")
        arm_hits = sorted(f"{a}~{b}" for a, b in ctx.contacts["arm_other"])
        crash = sorted("~".join(p) for p in ctx.contacts["arm_arm"])
        ok = pose["ok"] and not moved and not crash and not arm_hits
        return dict(row, result="pass" if ok else "fail", pose=pose, neighbours_disturbed=moved, arm_arm_contacts=crash, arm_link_contacts=arm_hits,
                    pad_touched_neighbours=sorted(ctx.contacts["pad_neighbour"]), held_tilt_max_deg=round(ctx.held_tilt, 1), first_contact_phase=ctx.first)

    def _hold_shift(self, arm, off, q, yaw, pos):
        """TCP shift that puts the container centre (not the TCP) where the waypoint says: R @ held offset, nominal layout.hold_below under the TCP removed."""
        qs, _, _ = arm.ik(q, pos, yaw, 20)
        R = arm.frames(qs)[2]
        return -(R @ off) - np.array([0, 0, self.layout.hold_below])

    def fresh(self, here):
        """A world at rest with the containers of `here` on their sites and every other container parked."""
        w, L = self.world, self.layout
        data = w.reset()
        for cid, site in here.items():
            # seeds above 0 vary the start placement inside the stud-lane clearance (0.4 mm per side): +-0.3 mm, +-0.5 deg
            j = (0., 0., 0.) if self.seed == 0 or site == "belt" else (*self.rng.uniform(-1, 1, 2) * .0003, float(self.rng.uniform(-1, 1)) * math.radians(.5))
            w.put(data, cid, site, jitter=j)
        for _ in range(FPS):
            self.frame(data, {a: L.sim_arms[a].wait for a in L.arms}, "settle")
        return data

    def off_stand(self, data, step, here):
        """A container judged on its outbound lane leaves with Pinky: it is parked off the cell and the lane is free again."""
        if step.get("outbound"):
            self.world.put(data, step["container"], None, [c for c, _ in self.layout.containers()].index(step["container"]))
            here.pop(step["container"], None)

    def run_single(self, here, step, branch="best"):
        """One step from a given nominal state (feasibility matrix); branch "other" grips with the jaw turned 180 deg."""
        self.branch = branch
        self.contacts, self.carried = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), None
        return self.run_step(self.fresh(here), step, {k: v for k, v in here.items() if k != step["container"]})

    def run_task(self, task, isolated=False, concurrent=False):
        w, L = self.world, self.layout
        here = dict(task.get("start", {}))
        self.contacts, self.carried = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), None
        data = self.fresh(here)
        rows, timing, stopped = [], None, None
        start = self.n
        if concurrent:
            rows, timing, stopped = self.run_concurrent(data, task, here)
        for step in [] if concurrent else task["steps"]:
            if isolated and rows:  # every step starts from the nominal plan state, so one failure does not spoil the next
                data = self.fresh(here)
            row = self.run_step(data, step, {k: v for k, v in here.items() if k != step["container"]})
            rows.append(row)
            print(json.dumps(row), flush=True)
            here[step["container"]] = step["to"]
            self.off_stand(data, step, here)
        last = {step["container"]: step for step in task["steps"]}
        final = {c: s["to"] for c, s in last.items() if not s.get("outbound")}  # judged when placed, then gone with Pinky
        self.data = data  # the last state, for the record's pictures
        finals = {c: judge_pose(w, data, c, s, self.limits) for c, s in final.items()}
        passed = sum(r["result"] == "pass" for r in rows)
        out = dict(task=task["name"], steps=len(task["steps"]), steps_pass=passed, final_ok=sum(f["ok"] for f in finals.values()), final_total=len(finals),
                   completed=bool(passed == len(task["steps"]) and all(f["ok"] for f in finals.values()) and not stopped), rows=rows, final=finals,
                   makespan_s=round((self.n - start) / FPS, 1))
        if concurrent:
            spans = {a: [(t["start_s"], t["end_s"]) for t in timing.values() if t["arm"] == a and "end_s" in t] for a in L.arms}
            a, b = spans.values()
            out.update(concurrent=True, stopped=stopped, timing=timing,
                       overlap_s=round(sum(max(0., min(e1, e2) - max(s1, s2)) for s1, e1 in a for s2, e2 in b), 1))
        return out


parse_choices = sites.parse_choices


def isaac_handoff(result, layout, seed=0):
    """Build a Stage-1 (MuJoCo geometry/vision/IK) -> Stage-2 (Isaac PhysX contact/slip/seating) handoff spec."""
    rows = result.get("rows", [])
    vis = [r["vision_pick"] for r in rows if "vision_pick" in r]
    poses = [r["pose"] for r in rows if "pose" in r]
    contacts_clear = all(not r.get("arm_arm_contacts") and not r.get("arm_link_contacts")
                         and not r.get("neighbours_disturbed") for r in rows)
    belt_xy = layout.sites["belt"]["xy"]
    single_cases = []
    for r in rows:
        vp = r.get("vision_pick")
        if vp:
            dx = max(-.025, min(.025, round(vp["seen_xy"][0] - belt_xy[0], 4)))
            dy = max(-.025, min(.025, round(vp["seen_xy"][1] - belt_xy[1], 4)))
            turn = max(-45., min(45., round(vp["seen_yaw_deg"], 1)))
            aim_m = round(min(.025, vp["xy_err_mm"] / 1000), 4)
            single_cases.append(dict(
                id=f"mujoco-{result['task']}-{r['step']}-{r['container']}",
                source=f"mujoco:{result['task']}:{r['step']}",
                sim=dict(box=[dx, dy, turn], place="belt", grasp_turn=turn, expect=None, aim=[aim_m, 0.0]),
            ))
    layers = 3 if result.get("steps", 0) > 3 else 1
    return dict(
        schema="rosy.omx-mujoco-isaac-handoff.v1",
        task=result["task"],
        stage_1_mujoco=dict(
            role="geometry_vision_ik_and_collision_screening",
            completed=bool(result.get("completed")),
            steps_pass=result.get("steps_pass", 0),
            steps_total=result.get("steps", 0),
            contacts_clear=contacts_clear,
            worst_vision_xy_mm=max((v["xy_err_mm"] for v in vis), default=0.0),
            worst_vision_yaw_deg=max((v["yaw_err_deg"] for v in vis), default=0.0),
            worst_pose_xy_mm=max((p["xy_mm"] for p in poses), default=0.0),
            worst_pose_yaw_deg=max((p["yaw_deg"] for p in poses), default=0.0),
            worst_ik_error_mm=max((r.get("worst_ik_error_mm", 0.0) for r in rows), default=0.0),
            colours_seen=[v.get("colour") for v in vis if v.get("colour")],
        ),
        stage_2_isaac=dict(
            role="physx_contact_pad_slip_and_seating_confirmation",
            ready=bool(result.get("completed") and contacts_clear),
            two_arm_scenario="omx-map-container-stack",
            two_arm_config=dict(seed=seed, layers=layers, case="nominal-palletizing-v21-ship-surveyed-skew-20261110"),
            single_arm_scenario="arm-s-cell-case",
            single_arm_cases=single_cases,
        ),
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=["run", "validate"])
    p.add_argument("task", choices=["stack", "cell-stack", "rehandle", "outbound", "plan",
                                    "stack-t1", "stack-t2", "stack-t3", "cell-stack-t1", "cell-stack-t2", "cell-stack-t3"])
    p.add_argument("--tier", type=int, choices=list(tasks.TIERS), help="run or validate only tier 1 (1단/l0), 2 (2단/l1), or 3 (3단/l2)")
    p.add_argument("--plan", help="with task 'plan': a JSON task (name, supply, start, steps), e.g. omx_two_arm_plan.py replay output")
    p.add_argument("--out", default=".")
    p.add_argument("--video", action="store_true")
    p.add_argument("--frames", help="folder for one last picture per real camera")
    p.add_argument("--video-skip", type=int, default=1, help="write every Nth frame (a short version); the file is named TASK-short.mp4")
    p.add_argument("--seed", type=int, default=0, help="0 = nominal belt pose, else a seeded pose inside the infeed tolerance")
    p.add_argument("--cone", default="elliptic", choices=["elliptic", "pyramidal"], help="MuJoCo friction cone (sensitivity: resting boxes creep in yaw with elliptic)")
    p.add_argument("--drop-upper", type=float, default=tasks.RELEASE_DROP_UPPER, help="release height over a lower container, m")
    p.add_argument("--isolated", action="store_true", help="reset to the nominal plan state before every step (per-step truth without cascades)")
    p.add_argument("--concurrent", action="store_true", help="both arms at once by the steps' after/after_pick/zones (omx_two_arm_plan.py --concurrent output)")
    p.add_argument("--pick-vision", action="store_true", help="perceive each pick container's (xy, yaw) from the rendered top camera instead of true pose")
    p.add_argument("--belt-skew", action="store_true", help="arrive belt containers with +-8..12 mm xy offset and +-15..22 deg yaw skew")
    p.add_argument("--isaac-handoff", help="write Stage-1 MuJoCo -> Stage-2 Isaac Sim handoff spec JSON to this path")
    p.add_argument("--choice", action="append", help="key=value override of omx_two_arm_sites.CHOICES (named parameters)")
    a = p.parse_args(argv)
    choices = parse_choices(a.choice)
    layout = sites.Layout(**choices)
    task = json.loads(Path(a.plan).read_text(encoding="utf-8")) if a.task == "plan" else tasks.get_task(layout, a.task, tier=a.tier)
    if a.task == "plan" and a.tier is not None:
        task = tasks.tier_task(layout, task, a.tier)
    try:
        records = tasks.validate(layout, task)
    except tasks.PlanRefused as e:
        print("REFUSED:", *e.reasons, sep="\n  ")
        return 2
    print("validated", len(records), "steps; roll below floor:", [r["step"] for r in records if r["roll_below_floor"]])
    if a.command == "validate":
        print(json.dumps(records))
        return 0
    import omx_two_arm_world as world_mod
    world = world_mod.World(layout, cone=a.cone)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    writer = close_video = None
    if a.video:
        video_path = str(out / f"{a.task}{'-short' if a.video_skip > 1 else ''}.mp4")
        from PIL import Image, ImageDraw
        try:
            import av
            container = av.open(video_path, "w")
            stream = container.add_stream("h264", rate=FPS)
            stream.width, stream.height, stream.pix_fmt = 1280, 960, "yuv420p"
            encode_rgb = lambda arr: container.mux(stream.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")))
            close_video = lambda: (container.mux(stream.encode(None)), container.close())
        except ImportError:
            import subprocess
            ff = subprocess.Popen(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x960",
                 "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", video_path],
                stdin=subprocess.PIPE,
            )
            encode_rgb = lambda arr: ff.stdin.write(arr.tobytes())
            close_video = lambda: (ff.stdin.close(), ff.wait())

        count = [0]

        def writer(data, label):
            count[0] += 1
            if count[0] % a.video_skip:
                return
            frame = Image.fromarray(np.vstack([np.hstack([world.render(data, view) for view in row]) for row in (RECORDED[:2], RECORDED[2:])]))
            ImageDraw.Draw(frame).text((8, 8), f"{a.task} {label}", fill=(255, 255, 0))
            encode_rgb(np.asarray(frame))
    teacher = Teacher(world, frame_hook=writer, seed=a.seed, drop_upper=a.drop_upper, pick_vision=a.pick_vision, belt_skew=a.belt_skew)
    result = teacher.run_task(task, a.isolated, a.concurrent)
    if a.frames:
        from PIL import Image
        Path(a.frames).mkdir(parents=True, exist_ok=True)
        for view in RECORDED:
            Image.fromarray(world.render(teacher.data, view)).save(Path(a.frames) / f"{view}.png")
    if close_video:
        close_video()
    roll = {r["step"]: r["roll_below_floor"] for r in records}
    result.update(choices=layout.choices, cone=a.cone, seed=a.seed, drop_m=[teacher.drop, teacher.drop_upper], roll_below_floor_steps=[s for s, v in roll.items() if v],
                  note="geometry only (D-947): contact numbers are not results; " + ("both arms at once by zones" if a.concurrent else "one arm moves at a time") + "; true container pose, no perception")
    (out / f"{a.task}{'-isolated' if a.isolated else ''}-{a.cone}-seed{a.seed}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    if a.isaac_handoff:
        hp = Path(a.isaac_handoff)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(json.dumps(isaac_handoff(result, layout, a.seed), indent=1), encoding="utf-8")
    print(f"{a.task}: steps pass {result['steps_pass']}/{result['steps']}, final poses ok {result['final_ok']}/{result['final_total']}, completed {result['completed']}"
          + f", makespan {result['makespan_s']} s" + (f", overlap {result['overlap_s']} s, stopped {result['stopped']}" if a.concurrent else ""))
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
