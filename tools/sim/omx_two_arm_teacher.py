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
import omx_real2sim_comp as r2s_comp  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
from omx_two_arm_teacher_stages import (  # noqa: E402, F401
    CARRY_SPEED,
    FPS,
    HOLD_GAP,
    OPEN_GAP,
    PREFIX,
    RECORDED,
    SERVO_GAIN,
    VISION_SKEW_CHOICES,
    Ctx,
    isaac_handoff,
    judge_pose,
    open_video_writer,
    parse_choices,
    run_concurrent_steps,
    servo_values,
)
import palletizing_gripper as jaw  # noqa: E402


class Teacher:
    SKEW_CASES = (
        (.006, .006, 18.), (.005, -.006, -16.), (.004, .005, -12.),
        (.005, .006, 15.), (.004, -.005, 14.), (.004, .006, -10.),
        (.004, .007, 16.), (.004, -.006, -14.), (.004, .006, 12.),
    )

    def __init__(self, world, data_file=None, frame_hook=None, drop=tasks.RELEASE_DROP, drop_upper=tasks.RELEASE_DROP_UPPER, seed=0,
                 pick_vision=False, belt_skew=False, cam_jitter=False):
        self.rng, self.seed, self.branch, self.carried = np.random.default_rng(seed), seed, "best", None
        self.world, self.layout, self.drop, self.drop_upper = world, world.layout, drop, drop_upper
        self.pick_vision, self.belt_skew, self.cam_jitter, self.skew_i, self.settle_frames = pick_vision, belt_skew, cam_jitter, 0, 0
        self.limits = (data_file or tasks.load())["judge"]
        self.hook = frame_hook or (lambda data, label: None)
        self.contacts, self.phase, self.first, self.tilt, self.n, self.held_tilt = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), "", {}, 0., 0, 0.
        self.others = set()
        self.zero_error, self.privileged, self.compensate_zero = {}, True, False
        self.servo = {}
        self.servo_comp = r2s_comp.ServoCompensator(world, FPS) if hasattr(world, "q") else None
        if cam_jitter and hasattr(world, "model"):
            r2s_comp.apply_world_camera(world, "top", r2s_comp.perturbed_camera_dict(self.layout.fixture["real_cameras"]["top"], **r2s_comp.DEFAULT_CAM_JITTER))

    def perceive_pick(self, data, sa, true_xy, true_yaw, here=None):
        """Detect a skewed/offset container at `sa` from the rendered top camera frame (online 6-DoF anchor-calibrated pinhole back-projection)."""
        import cv2

        qid = self.world.model.geom("ship_quay").id if "ship_quay" in self.world.geom_name else -1
        if qid >= 0:
            self.world.model.geom_rgba[qid, 3] = 0.
        bgr = cv2.cvtColor(self.world.render(data, "top"), cv2.COLOR_RGB2BGR)
        if qid >= 0:
            self.world.model.geom_rgba[qid, 3] = 1.
        return r2s_comp.perceive_container(bgr, sa, true_xy, true_yaw, self.layout, here=here)

    def frame(self, data, targets, label, ctxs=None):
        """One video frame of physics. Sequential: the Teacher is the one context. Two arms at once: each context gets its own arm's
        link and pad contacts; arm-arm contacts go to both."""
        self.n += 1
        if not self.privileged:
            targets = {arm: t + self.zero_error[arm] if arm in self.zero_error else t for arm, t in targets.items()}
        if self.servo_comp is not None:
            targets = self.servo_comp.apply(data, targets)
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

    def settle_g(self, data, arm, q_target, grip, pos_target=None, max_s=6.0):
        """Closed-loop settle at a waypoint until joint error, velocity, TCP position, and jitter gate converge."""
        cmd = np.append(q_target[:5], grip)
        z_off = (self.zero_error[arm][:5] - (self.servo_comp.zero_est[arm] if self.servo_comp is not None else 0.)) if (not self.privileged and arm in self.zero_error) else 0.
        check_tcp = self.privileged or self.compensate_zero
        arm_q_idx = self.world.q[arm][:5]
        arm_dof_idx = self.world.arm_dof[arm][:5]
        target5 = q_target[:5] + z_off
        for _ in range(round(max_s * FPS)):
            q_err = float(np.max(np.abs(target5 - data.qpos[arm_q_idx])))
            q_vel = float(np.max(np.abs(data.qvel[arm_dof_idx])))
            tcp_ok = not check_tcp or pos_target is None or float(np.linalg.norm(self.world.tcp(data, arm)[0] - pos_target)) <= .0012
            if self.servo_comp.is_settled(arm, q_err, q_vel, tcp_ok) if self.servo_comp is not None else (q_err <= .0045 and q_vel <= .02 and tcp_ok):
                break
            self.settle_frames += 1
            yield cmd

    def tcp_move_g(self, ctx, ik_arm, q, p_from, p_to, yaw_from, yaw_to, grip, seconds, shift=None):
        """TCP straight line with IK warm start, one target per frame. Returns the final q and the worst IK error (m) met on the way."""
        if self.servo_comp is not None:
            q_end = ik_arm.ik(q, p_to + shift(p_to, yaw_to, q) if shift is not None else p_to, yaw_to, 20)[0]
            seconds = self.servo_comp.pace_seconds(ik_arm.name, q, q_end, seconds)
        n, worst = max(1, round(seconds * FPS)), 0.
        dp = p_to - p_from
        dyaw = yaw_to - yaw_from
        for i in range(1, n + 1):
            s = i / n
            s = s * s * (3 - 2 * s)
            pos, yaw = p_from + s * dp, yaw_from + s * dyaw
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
        self.settle_frames = 0
        if self.servo_comp is not None:
            self.servo_comp.reset_arm(arm)
        ctx.contacts, ctx.carried, ctx.first, ctx.phase = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), c, {}, "approach"
        if step["from"] == "belt":
            yield from self.belt_in_g(data, step)
        pos0, yaw0, _ = w.pose(data, c)
        row = dict(step=step["id"], container=c, arm=arm, source=step["from"], target=step["to"])
        if np.linalg.norm(pos0[:2] - sa["xy"]) > .035:
            return dict(row, result="blocked", reason=f"{c} is {np.linalg.norm(pos0[:2] - sa['xy']) * 1000:.0f} mm from {step['from']}")
        pick_xy, pick_yaw = pos0[:2], yaw0
        if self.pick_vision:
            seen = self.perceive_pick(data, sa, pos0[:2], yaw0, here=here)
            if seen is None:
                return dict(row, result="blocked", reason=f"top camera did not see {c} at {step['from']}")
            pick_xy, pick_yaw, row["vision_pick"] = seen[0], seen[1], seen[2]
        before = {o: w.pose(data, o) for o in here}
        wps = tasks.waypoints(L, step, here, pick=(pick_xy, pick_yaw), drop=self.drop, drop_upper=self.drop_upper)
        g_open, g_to = jaw.angle_for_gap(OPEN_GAP[sa["kind"]]), jaw.angle_for_gap(OPEN_GAP[sb["kind"]])
        g_hold = jaw.angle_for_gap(HOLD_GAP)
        q = self.q_now(data, arm)
        ok, q_app, _, note = tasks.solve_chain(ik_arm, wps, ik_arm.home, roll_floor=L.roll_floor, branch=self.branch)
        if not ok:
            return dict(row, result="unreachable", reason=f"{arm} cannot do the step tool-down inside the limits: {note}")
        app_s = self.servo_comp.pace_seconds(arm, q, q_app, 2.5) if self.servo_comp is not None else 2.5
        yield from self.move_g(np.append(q[:5], g_open), np.append(q_app[:5], g_open), app_s)
        yield from self.settle_g(data, arm, q_app, g_open, np.array([*wps[0][1], wps[0][2]]))
        q, off, worst, prev, held = q_app, None, 0., wps[0], {}
        for name, xy, z, yaw, grip in wps[1:]:
            ctx.phase = name
            p_from, p_to = np.array([*prev[1], prev[2]]), np.array([*xy, z])
            yaw_from = prev[3]
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
                p_end = p_to + shift(p_to, yaw, q) if shift is not None else p_to
                yield from self.settle_g(data, arm, q, g, p_end)
            prev = (name, xy, z, yaw, grip)
        ctx.phase = "park"
        park_s = self.servo_comp.pace_seconds(arm, q, ik_arm.wait, 2.5) if self.servo_comp is not None else 2.5
        yield from self.move_g(np.append(q[:5], g_to), np.append(ik_arm.wait[:5], g_to), park_s)
        yield from self.settle_g(data, arm, ik_arm.wait, g_to)
        for _ in range(round(.7 * FPS)):
            yield np.append(ik_arm.wait[:5], g_to)
        scomp = dict(physics=L.choices["physics"], settle_frames=self.settle_frames,
                     max_trim_deg=round(math.degrees(self.servo_comp.max_trim_rad[arm]), 2) if self.servo_comp else 0.0,
                     damped_frames=self.servo_comp.damped_frames[arm] if self.servo_comp else 0,
                     max_jitter_std_deg=round(math.degrees(self.servo_comp.max_jitter_std_rad[arm]), 3) if self.servo_comp else 0.0)
        return dict(self.verdict(data, step, row, before, ctx), held=held, servo_comp=scomp, worst_ik_error_mm=round(worst * 1000, 2))

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
        return run_concurrent_steps(self, data, task, here, max_s=max_s)

    def belt_in(self, data, step, idle):
        """belt_in_g for a caller that drives frames itself with the other arm holding `idle` (the policy evaluation)."""
        for target in self.belt_in_g(data, step):
            self.frame(data, {step["arm"]: target, **idle}, step["id"])

    def verdict(self, data, step, row, before, ctx=None):
        """The same judgement for the teacher and a learned policy: the container, its neighbours, and what the arms touched."""
        w, ctx = self.world, ctx or self
        pose = judge_pose(w, data, step["container"], step["to"], self.limits)
        moved = self.disturbed(data, before, ctx)
        arm_hits = sorted(f"{a}~{b}" for a, b in ctx.contacts["arm_other"])
        crash = sorted("~".join(p) for p in ctx.contacts["arm_arm"])
        ok = pose["ok"] and not moved and not crash and not arm_hits
        return dict(row, result="pass" if ok else "fail", pose=pose, neighbours_disturbed=moved, arm_arm_contacts=crash, arm_link_contacts=arm_hits,
                    pad_touched_neighbours=sorted(ctx.contacts["pad_neighbour"]), held_tilt_max_deg=round(ctx.held_tilt, 1), first_contact_phase=ctx.first)

    def disturbed(self, data, before, ctx):
        """Neighbours that moved past the judge's limits since `before`."""
        moved = []
        for o, (p, yw, tl) in before.items():
            if o in ctx.others:
                continue
            p2, yw2, tl2 = self.world.pose(data, o)
            d = float(np.linalg.norm(p2 - p)) * 1000
            dyaw = abs(math.degrees(tasks.wrap_pi(yw2 - yw)))
            if d > self.limits["neighbour_mm"] or abs(tl2 - tl) > self.limits["neighbour_tilt_deg"] or dyaw > self.limits["neighbour_yaw_deg"]:
                moved.append(f"{o} {d:.1f} mm {dyaw:.1f} deg")
        return moved

    def _hold_shift(self, arm, off, q, yaw, pos):
        """TCP shift that puts the container centre (not the TCP) where the waypoint says."""
        qs, _, _ = arm.ik(q, pos, yaw, 20)
        R = arm.frames(qs)[2]
        return -(R @ off) - np.array([0, 0, self.layout.hold_below])

    def fresh(self, here):
        """A world at rest with the containers of `here` on their sites and every other container parked."""
        w, L = self.world, self.layout
        m = w.model
        if not hasattr(w, "servo0"):
            w.servo0 = {arm: servo_values(m, ids) for arm, ids in w.act.items()}
        for arm, ids in w.act.items():
            mine = self.servo.get(arm, {})
            v = {k: np.where(np.isnan(mine[k]), base, mine[k]) if k in mine else base for k, base in w.servo0[arm].items()}
            dofs = m.jnt_dofadr[m.actuator_trnid[ids[:5], 0]]
            m.actuator_gainprm[ids[:5], 0], m.actuator_biasprm[ids[:5], 1], m.actuator_biasprm[ids[:5], 2] = v["kp"], -v["kp"], -v["kv"]
            m.actuator_forcerange[ids[:5]] = np.stack([-v["force"], v["force"]], 1)
            m.dof_damping[dofs], m.dof_frictionloss[dofs] = v["damping"], v["frictionloss"]
        data = w.reset()
        if self.servo_comp is not None:
            self.servo_comp = r2s_comp.ServoCompensator(w, FPS)
            if self.compensate_zero:
                for a in L.arms:
                    q_true = self.q_now(data, a)
                    q_rep = q_true - self.zero_error.get(a, np.zeros(6))
                    self.servo_comp.calibrate_zero_offset(a, q_true, q_rep)
        for cid, site in here.items():
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
            if isolated and rows:
                data = self.fresh(here)
            row = self.run_step(data, step, {k: v for k, v in here.items() if k != step["container"]})
            rows.append(row)
            print(json.dumps(row), flush=True)
            if row["result"] in ("blocked", "unreachable") and step["from"] == "belt":
                self.world.put(data, step["container"], None, [c for c, _ in self.layout.containers()].index(step["container"]))
            else:
                here[step["container"]] = step["to"]
            self.off_stand(data, step, here)
        last = {step["container"]: step for step in task["steps"]}
        final = {c: s["to"] for c, s in last.items() if not s.get("outbound")}
        self.data = data
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
    p.add_argument("--cone", default="elliptic", choices=["elliptic", "pyramidal"], help="MuJoCo friction cone")
    p.add_argument("--drop-upper", type=float, default=tasks.RELEASE_DROP_UPPER, help="release height over a lower container, m")
    p.add_argument("--isolated", action="store_true", help="reset to the nominal plan state before every step")
    p.add_argument("--concurrent", action="store_true", help="both arms at once by the steps' after/after_pick/zones")
    p.add_argument("--pick-vision", action="store_true", help="perceive each pick container's (xy, yaw) from the rendered top camera")
    p.add_argument("--belt-skew", action="store_true", help="arrive belt containers with +-8..12 mm xy offset and +-15..22 deg yaw skew")
    p.add_argument("--cam-jitter", action="store_true", help="perturb physical top camera pose to verify online 6-DoF anchor self-calibration")
    p.add_argument("--zero-error-deg", type=float, default=0.0, help="inject +-deg joint-zero calibration error per arm and compensate online (G-20)")
    p.add_argument("--isaac-handoff", help="write Stage-1 MuJoCo -> Stage-2 Isaac Sim handoff spec JSON to this path")
    p.add_argument("--choice", action="append", help="key=value override of omx_two_arm_sites.CHOICES (named parameters)")
    a = p.parse_args(argv)
    choices = parse_choices(a.choice)
    if a.pick_vision or a.belt_skew or a.cam_jitter:
        for k, v in VISION_SKEW_CHOICES.items():
            choices.setdefault(k, v)
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
    writer, close_video = open_video_writer(world, out, a.task, a.video_skip) if a.video else (None, None)
    teacher = Teacher(world, frame_hook=writer, seed=a.seed, drop_upper=a.drop_upper, pick_vision=a.pick_vision, belt_skew=a.belt_skew, cam_jitter=a.cam_jitter)
    if a.zero_error_deg > 0:
        import omx_two_arm_skill as skill_mod
        teacher.zero_error = skill_mod.draw_zero_error(a.seed or 1003, a.zero_error_deg)
        teacher.privileged, teacher.compensate_zero = False, True
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
