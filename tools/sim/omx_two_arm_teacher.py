#!/usr/bin/env python3
"""Scripted two-arm teacher for the `stack` and `rehandle` tasks, with strict per-step and whole-task judging and an mp4 of each run.

    MUJOCO_GL=egl python tools/sim/omx_two_arm_teacher.py run stack --out DIR [--video] [--choice key=value ...]
    python tools/sim/omx_two_arm_teacher.py validate rehandle [--choice key=value ...]      # no MuJoCo needed

One arm moves at a time, the other parks at home. The teacher reads the true container pose (no perception) and corrects the placement for
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
OPEN_GAP = dict(belt=.042, ship=.033, temp=.033)  # 33 mm lets a pad stay inside the 6 mm gaps between rows (release_gap_m of the ship case)
HOLD_GAP = .030 - jaw.SQUEEZE_M


def judge_pose(world, data, cid, site, limits):
    """Container against its target site: position, yaw (180 deg symmetric), height, tilt."""
    s = world.layout.sites[site]
    pos, yaw, tilt = world.pose(data, cid)
    xy = float(np.linalg.norm(pos[:2] - s["xy"])) * 1000
    dyaw = abs(math.degrees(tasks.wrap_pi(yaw - s["yaw"])))
    dz = float(pos[2] - s["z"]) * 1000
    ok = xy <= limits["xy_mm"] and dyaw <= limits["yaw_deg"] and abs(dz) <= limits["z_mm"] and tilt <= limits["tilt_deg"]
    return dict(ok=bool(ok), xy_mm=round(xy, 1), yaw_deg=round(dyaw, 1), z_mm=round(dz, 1), tilt_deg=round(tilt, 1))


class Teacher:
    def __init__(self, world, data_file=None, frame_hook=None, drop=tasks.RELEASE_DROP, drop_upper=tasks.RELEASE_DROP_UPPER, seed=0):
        self.rng, self.seed, self.branch, self.carried = np.random.default_rng(seed), seed, "best", None
        self.world, self.layout, self.drop, self.drop_upper = world, world.layout, drop, drop_upper
        self.limits = (data_file or tasks.load())["judge"]
        self.hook = frame_hook or (lambda data, label: None)
        self.contacts, self.phase, self.first, self.tilt, self.n, self.held_tilt = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), "", {}, 0., 0, 0.

    def frame(self, data, targets, label):
        self.n += 1
        self.world.advance(data, targets)
        rep = self.world.contact_report(data, self.carried)
        for k, v in rep.items():
            if v - self.contacts[k] and k != "pad_neighbour":
                self.first.setdefault(k, f"{self.phase}@frame{self.n}")
            self.contacts[k] |= v
        if self.carried and self.phase in ("lift", "carry", "lower"):
            self.held_tilt = max(self.held_tilt, self.world.pose(data, self.carried)[2])
        self.hook(data, label)

    def q_now(self, data, arm):
        return data.qpos[self.world.q[arm]].copy()

    def move(self, data, arm, q_from, q_to, seconds, label, idle):
        """Joint-space move of one arm (idle arm holds)."""
        for i in range(1, max(1, round(seconds * FPS)) + 1):
            s = i / max(1, round(seconds * FPS))
            s = s * s * (3 - 2 * s)
            self.frame(data, {arm: q_from + s * (q_to - q_from), **idle}, label)

    def tcp_move(self, data, ik_arm, arm, q, p_from, p_to, yaw_from, yaw_to, grip, seconds, label, idle, shift=None):
        """TCP straight line with IK warm start. Returns the final q and the worst IK error (m) met on the way."""
        n, worst = max(1, round(seconds * FPS)), 0.
        for i in range(1, n + 1):
            s = i / n
            s = s * s * (3 - 2 * s)
            pos, yaw = p_from + s * (p_to - p_from), yaw_from + s * (yaw_to - yaw_from)
            if shift is not None:
                pos = pos + shift(pos, yaw, q)
            q, err, rot = ik_arm.ik(q, pos, yaw, 30)
            worst = max(worst, err)
            self.tilt = max(self.tilt, rot)
            target = np.append(q[:5], grip)
            self.frame(data, {arm: target, **idle}, label)
        return q, worst

    def run_step(self, data, step, here):
        w, L = self.world, self.layout
        arm, c, ik_arm = step["arm"], step["container"], L.sim_arms[step["arm"]]
        sa, sb = L.sites[step["from"]], L.sites[step["to"]]
        self.tilt = self.held_tilt = 0.
        self.contacts, self.carried, self.first = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), c, {}
        idle = {o: np.append(L.sim_arms[o].home[:5], L.sim_arms[o].home[5]) for o in L.arms if o != arm}
        if step["from"] == "belt":
            f = L.fixture  # the belt pick pose varies inside the fixture's infeed tolerance; seed 0 is the nominal pose
            j = (0., 0., 0.) if self.seed == 0 else (*self.rng.uniform(-1, 1, 2) * f["infeed_jitter_xy_m"], float(self.rng.uniform(-1, 1)) * f["infeed_yaw_jitter_rad"])
            w.put(data, c, "belt", jitter=j)
            for _ in range(8):
                self.frame(data, {arm: self.q_now(data, arm), **idle}, step["id"])
        pos0, yaw0, _ = w.pose(data, c)
        row = dict(step=step["id"], container=c, arm=arm, source=step["from"], target=step["to"])
        if np.linalg.norm(pos0[:2] - sa["xy"]) > .03:
            return dict(row, result="blocked", reason=f"{c} is {np.linalg.norm(pos0[:2] - sa['xy']) * 1000:.0f} mm from {step['from']}")
        before = {o: w.pose(data, o) for o, _ in L.containers() if o != c}
        wps = tasks.waypoints(L, step, here, pick=(pos0[:2], yaw0), drop=self.drop, drop_upper=self.drop_upper)
        g_open, g_to = jaw.angle_for_gap(OPEN_GAP[sa["kind"]]), jaw.angle_for_gap(OPEN_GAP[sb["kind"]])
        g_hold = jaw.angle_for_gap(HOLD_GAP)
        q = self.q_now(data, arm)
        ok, q_app, _, note = tasks.solve_chain(ik_arm, wps, q, roll_floor=L.roll_floor, branch=self.branch)
        if not ok:
            return dict(row, result="unreachable", reason=f"{arm} cannot do the step tool-down inside the limits: {note}")
        self.move(data, arm, np.append(q[:5], g_open), np.append(q_app[:5], g_open), 2.5, step["id"], idle)
        q, off, worst, prev, held = q_app, None, 0., wps[0], {}
        for name, xy, z, yaw, grip in wps[1:]:
            self.phase = name
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
                    self.frame(data, {arm: np.append(q[:5], a0 + (a1 - a0) * i / n), **idle}, step["id"])
                if name == "close":
                    tcp, R = w.tcp(data, arm)
                    off = R.T @ (w.pose(data, c)[0] - tcp)
                    held["offset_in_jaw_mm"] = [round(float(v) * 1000, 1) for v in off]
                if name == "release":
                    self.carried = None
            else:
                g = g_hold if grip == "hold" else (g_open if name in ("approach", "grasp") else g_to)
                q, e = self.tcp_move(data, ik_arm, arm, q, p_from, p_to, yaw_from, yaw, g, seconds, step["id"], idle, shift)
                worst = max(worst, e)
            prev = (name, xy, z, yaw, grip)
        self.move(data, arm, np.append(q[:5], g_to), np.append(ik_arm.home[:5], g_to), 2.5, step["id"], idle)  # park
        for _ in range(round(.7 * FPS)):
            self.frame(data, {arm: np.append(ik_arm.home[:5], g_to), **idle}, step["id"])
        pose = judge_pose(w, data, c, step["to"], self.limits)
        moved = []
        for o, (p, yw, tl) in before.items():
            p2, yw2, tl2 = w.pose(data, o)
            d = float(np.linalg.norm(p2 - p)) * 1000
            dyaw = abs(math.degrees(tasks.wrap_pi(yw2 - yw)))
            if d > self.limits["neighbour_mm"] or abs(tl2 - tl) > self.limits["neighbour_tilt_deg"] or dyaw > self.limits["neighbour_yaw_deg"]:
                moved.append(f"{o} {d:.1f} mm {dyaw:.1f} deg")
        arm_hits = sorted(f"{a}~{b}" for a, b in self.contacts["arm_other"])
        crash = sorted("~".join(p) for p in self.contacts["arm_arm"])
        ok = pose["ok"] and not moved and not crash and not arm_hits
        return dict(row, result="pass" if ok else "fail", pose=pose, held=held, neighbours_disturbed=moved, arm_arm_contacts=crash,
                    arm_link_contacts=arm_hits, pad_touched_neighbours=sorted(self.contacts["pad_neighbour"]), worst_ik_error_mm=round(worst * 1000, 2),
                    held_tilt_max_deg=round(self.held_tilt, 1), first_contact_phase=self.first)

    def _hold_shift(self, arm, off, q, yaw, pos):
        """TCP shift that puts the container centre (not the TCP) where the waypoint says: R @ held offset, nominal 2.01 mm under the TCP removed."""
        qs, _, _ = arm.ik(q, pos, yaw, 20)
        R = arm.frames(qs)[2]
        return -(R @ off) - np.array([0, 0, tasks.HOLD_BELOW_TCP])

    def fresh(self, here):
        """A world at rest with the containers of `here` on their sites and every other container parked."""
        w, L = self.world, self.layout
        data = w.reset()
        for cid, site in here.items():
            # seeds above 0 vary the start placement inside the stud-lane clearance (0.4 mm per side): +-0.3 mm, +-0.5 deg
            j = (0., 0., 0.) if self.seed == 0 or site == "belt" else (*self.rng.uniform(-1, 1, 2) * .0003, float(self.rng.uniform(-1, 1)) * math.radians(.5))
            w.put(data, cid, site, jitter=j)
        for _ in range(FPS):
            self.frame(data, {a: L.sim_arms[a].home for a in L.arms}, "settle")
        return data

    def run_single(self, here, step, branch="best"):
        """One step from a given nominal state (feasibility matrix); branch "other" grips with the jaw turned 180 deg."""
        self.branch = branch
        self.contacts, self.carried = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), None
        return self.run_step(self.fresh(here), step, {k: v for k, v in here.items() if k != step["container"]})

    def run_task(self, task, isolated=False):
        w, L = self.world, self.layout
        here = dict(task.get("start", {}))
        self.contacts, self.carried = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), None
        data = self.fresh(here)
        rows = []
        for step in task["steps"]:
            if isolated and rows:  # every step starts from the nominal plan state, so one failure does not spoil the next
                data = self.fresh(here)
            row = self.run_step(data, step, {k: v for k, v in here.items() if k != step["container"]})
            rows.append(row)
            print(json.dumps(row), flush=True)
            here[step["container"]] = step["to"]
        final = {}
        for step in task["steps"]:
            final[step["container"]] = step["to"]
        finals = {c: judge_pose(w, data, c, s, self.limits) for c, s in final.items()}
        passed = sum(r["result"] == "pass" for r in rows)
        return dict(task=task["name"], steps=len(rows), steps_pass=passed, final_ok=sum(f["ok"] for f in finals.values()), final_total=len(finals),
                    completed=bool(passed == len(rows) and all(f["ok"] for f in finals.values())), rows=rows, final=finals)


def parse_choices(items):
    out = {}
    for item in items or []:
        key, value = item.split("=", 1)
        out[key] = json.loads(value) if value[:1] in "0123456789-." else value
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=["run", "validate"])
    p.add_argument("task", choices=["stack", "rehandle"])
    p.add_argument("--out", default=".")
    p.add_argument("--video", action="store_true")
    p.add_argument("--video-skip", type=int, default=1, help="write every Nth frame (a short version); the file is named TASK-short.mp4")
    p.add_argument("--seed", type=int, default=0, help="0 = nominal belt pose, else a seeded pose inside the infeed tolerance")
    p.add_argument("--cone", default="elliptic", choices=["elliptic", "pyramidal"], help="MuJoCo friction cone (sensitivity: resting boxes creep in yaw with elliptic)")
    p.add_argument("--drop-upper", type=float, default=tasks.RELEASE_DROP_UPPER, help="release height over a lower container, m")
    p.add_argument("--isolated", action="store_true", help="reset to the nominal plan state before every step (per-step truth without cascades)")
    p.add_argument("--choice", action="append", help="key=value override of omx_two_arm_sites.CHOICES (named parameters)")
    a = p.parse_args(argv)
    choices = parse_choices(a.choice)
    layout = sites.Layout(**choices)
    task = tasks.get_task(layout, a.task)
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
    writer = None
    if a.video:
        import av
        container = av.open(str(out / f"{a.task}{'-short' if a.video_skip > 1 else ''}.mp4"), "w")
        stream = container.add_stream("h264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = 1280, 480, "yuv420p"
        from PIL import Image, ImageDraw

        count = [0]

        def writer(data, label):
            count[0] += 1
            if count[0] % a.video_skip:
                return
            image = np.hstack([world.render(data, "top"), world.render(data, "overview")])
            frame = Image.fromarray(image)
            ImageDraw.Draw(frame).text((8, 8), f"{a.task} {label}", fill=(255, 255, 0))
            container.mux(stream.encode(av.VideoFrame.from_ndarray(np.asarray(frame), format="rgb24")))
    teacher = Teacher(world, frame_hook=writer, seed=a.seed, drop_upper=a.drop_upper)
    result = teacher.run_task(task, a.isolated)
    if writer:
        container.mux(stream.encode(None))
        container.close()
    roll = {r["step"]: r["roll_below_floor"] for r in records}
    result.update(choices=layout.choices, cone=a.cone, seed=a.seed, drop_m=[teacher.drop, teacher.drop_upper], roll_below_floor_steps=[s for s, v in roll.items() if v],
                  note="geometry only (D-947): contact numbers are not results; one arm moves at a time; true container pose, no perception")
    (out / f"{a.task}{'-isolated' if a.isolated else ''}-{a.cone}-seed{a.seed}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(f"{a.task}: steps pass {result['steps_pass']}/{result['steps']}, final poses ok {result['final_ok']}/{result['final_total']}, completed {result['completed']}")
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
