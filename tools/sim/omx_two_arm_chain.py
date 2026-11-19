"""Whole two-arm scenarios by the teacher's IK under the cell's errors, judged row by row without stopping at the first failure.

Three modes over one seed's single draw of zero error and servo lag: `iso` resets to the plan's nominal state before every step (today's
step-alone table, but whole steps and one draw per seed), `seq` runs the steps one arm at a time on top of the world the previous step
left, `conc` runs both arms at once through `run_concurrent_steps` (after/zones/belt ledger). A step's grasp half (grasp, close, lift)
is commanded in reported angles, so the seed's joint-zero error shows there as in the sub-skill evaluation (omx_two_arm_skill.step); the
rest of the step is in true angles, as the real cell's zero estimate would leave it. Each row also carries `grasp`: the sub-skill
judgement (held, no neighbour moved, no contact) taken the frame the carry begins, so step pass counts compare with that table.
Geometry only (D-947): no learned policy, no real arm.
"""
import argparse
import inspect
import json
from pathlib import Path
import sys

import numpy as np

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_two_arm_plan as plan_mod  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_skill as skills  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import omx_two_arm_teacher as teaching  # noqa: E402

GRASP_HALF = ("grasp", "close", "lift")
EVAL_SEEDS = (200000, 201000, 202000)  # omx_two_arm_policy.EVAL_SEED_BASE + 1000 k, the 93-row evaluation's seeds
MODES = ("iso", "seq", "conc")


class ChainTeacher(teaching.Teacher):
    """A Teacher whose arm is in reported angles (zero error shows) only during its grasp half, and which judges that half as it passes."""

    def __init__(self, *args, max_s=900, **kw):
        super().__init__(*args, **kw)
        self.max_s, self.arm_ctx, self.start, self.grasp, self.step = max_s, {}, {}, {}, None

    def priv(self, arm):
        ctx = self.arm_ctx.get(arm)
        return ctx is None or ctx.phase not in GRASP_HALF  # an arm with no step holds its true wait pose

    def run_step(self, data, step, here):
        self.step, self.arm_ctx = step, {step["arm"]: self}
        return super().run_step(data, step, here)

    def run_concurrent(self, data, task, here, max_s=None, faults=None):
        return super().run_concurrent(data, task, here, max_s=max_s or self.max_s, faults=faults)

    def frame(self, data, targets, label, ctxs=None):
        for c in ctxs or ():
            self.arm_ctx[c.arm] = c
        super().frame(data, targets, label, ctxs)
        for c in ctxs or (self,):
            self._judge_grasp(data, c)

    def _judge_grasp(self, data, c):
        if getattr(c, "step", None) is None or not c.carried:  # the settle before a step, or a step that has let go
            return
        sid, w = c.step["id"], self.world
        if c.phase == "grasp" and sid not in self.start:  # the container is on its site, nothing has touched it yet
            self.start[sid] = (float(w.pose(data, c.carried)[0][2]), {o: w.pose(data, o) for o, _ in self.layout.containers() if o != c.carried})
        elif c.phase == "carry" and sid in self.start and sid not in self.grasp:
            z0, before = self.start[sid]
            pos = w.pose(data, c.carried)[0]
            rise, in_jaw = float(pos[2] - z0), float(np.linalg.norm(pos - w.tcp(data, c.step["arm"])[0]))
            moved, hits, crash = self.disturbed(data, before, c), sorted(f"{a}~{b}" for a, b in c.contacts["arm_other"]), sorted("~".join(p) for p in c.contacts["arm_arm"])
            held = rise > .015 and in_jaw < .06
            self.grasp[sid] = dict(ok=bool(held and not moved and not hits and not crash), held=bool(held), rise_mm=round(rise * 1000, 1),
                                   container_to_tcp_mm=round(in_jaw * 1000, 1), neighbours_disturbed=moved, arm_link_contacts=hits, arm_arm_contacts=crash)


def get_task(layout, name):
    """A data-file task by name, or `plan:<scenario>`: the planner's two-arm replay (omx_two_arm_plan.compare + replay_tasks), whose arms
    and order the scheduler chose to overlap in time (the file's tasks keep the one-arm-at-a-time arms)."""
    if name.startswith("plan:"):
        scenario = name[5:]
        return plan_mod.replay_tasks(layout, plan_mod.compare(layout, scenario))[f"{scenario}-two-arm"]
    return tasks.get_task(layout, name)


def concurrent_task(layout, task):
    """The data file's task with what `run_concurrent_steps` needs, derived as omx_two_arm_plan.replay_tasks does for a planned move: `after`
    (earlier steps on the same stack, lane or container), `after_pick` (the previous conveyor pick) and `zones`. Arms and order stay the file's."""
    if "zones" in task["steps"][0]:
        return task
    steps, moves = [], []
    for s in task["steps"]:
        move = dict(source=s["from"], destination=s["to"], cargo_id=s["container"])
        belt = [p["id"] for p in steps if p["from"] == "belt"]
        steps.append(dict(s, after=[p["id"] for p, m in zip(steps, moves) if plan_mod.done_keys(layout, move) & plan_mod.done_keys(layout, m)],
                          after_pick=belt[-1:] if s["from"] == "belt" else [], zones=[sorted(z) for z in plan_mod.holds(layout, s["arm"], s["from"], s["to"])]))
        moves.append(move)
    return dict(task, steps=steps)


def run_scenario(world, layout, name, seed, mode, *, zero_error_deg=1., lag=True, max_s=900, **teacher_kw):
    """One scenario in one mode; the seed draws the arm's errors once, as one cell has them for the whole run."""
    task = get_task(layout, name)
    task = concurrent_task(layout, task) if mode == "conc" else task
    teacher = ChainTeacher(world, seed=seed, max_s=max_s, **teacher_kw)
    skills.disturb(teacher, seed, zero_error_deg, lag)
    result = teacher.run_task(task, isolated=mode == "iso", concurrent=mode == "conc")
    for row in result["rows"]:
        row["grasp"] = teacher.grasp.get(row["step"])
    return dict(result, mode=mode, seed=seed, summary=summarise(result))


def summarise(result):
    """What the comparison tables need from one run (a row is one plan step; `grasp` is the sub-skill judgement of its grasp half)."""
    rows, concurrent = result["rows"], result.get("concurrent", False)
    order = sorted(rows, key=lambda r: result["timing"].get(r["step"], {}).get("end_s", 0.)) if concurrent else rows
    stage = lambda r: bool((r.get("grasp") or {}).get("ok"))  # noqa: E731
    vision = [r["vision_pick"]["xy_err_mm"] for r in rows if "vision_pick" in r]
    unseen = [r["step"] for r in rows if r["result"] == "blocked" and "did not see" in r.get("reason", "")]
    out = dict(
        steps=result["steps"], done=len(rows), step_pass=result["steps_pass"],
        grasp_pass=sum(map(stage, rows)), completed=result["completed"], grasp_complete=len(rows) == result["steps"] and all(map(stage, rows)),
        first_fail=next((r["step"] for r in order if r["result"] != "pass"), None), first_grasp_fail=next((r["step"] for r in order if not stage(r)), None),
        makespan_s=result["makespan_s"], stopped=result.get("stopped"),
        arm_arm=sum(bool(r.get("arm_arm_contacts")) for r in rows), neighbour=sum(bool(r.get("neighbours_disturbed")) for r in rows),
        arm_link=sum(bool(r.get("arm_link_contacts")) for r in rows), pad_neighbour=sum(bool(r.get("pad_touched_neighbours")) for r in rows),
        vision_n=len(vision), vision_unseen=unseen, vision_xy_mm=[round(float(np.median(vision)), 2), round(float(np.max(vision)), 2)] if vision else None,
        **{k: result.get("invariants", {}).get(k) for k in ("picks_before_arrival", "max_cargo_on_belt", "steps_started_after_stop")})
    if concurrent:
        out.update(overlap_s=result["overlap_s"], deadlock=str(result["stopped"]).startswith("deadlock"))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tasks", default="stack,outbound,rehandle")
    p.add_argument("--seeds", default=",".join(map(str, EVAL_SEEDS)))
    p.add_argument("--modes", default=",".join(MODES))
    p.add_argument("--out", required=True, help="folder: one JSON per task, seed and mode; an existing one is kept")
    p.add_argument("--zero-error-deg", type=float, default=1.)
    p.add_argument("--servo-lag", action="store_true")
    p.add_argument("--max-s", type=float, default=900., help="conc: sim seconds before the run is cut off as a stall")
    p.add_argument("--choice", action="append")
    for flag in ("pick-vision", "belt-skew", "cam-jitter", "pose-random"):
        p.add_argument(f"--{flag}", action="store_true")
    a = p.parse_args(argv)
    if a.pose_random and "pose_random" not in inspect.signature(teaching.Teacher).parameters:
        p.error("this checkout's Teacher has no --pose-random")
    kw = dict(pick_vision=a.pick_vision, belt_skew=a.belt_skew, cam_jitter=a.cam_jitter, **(dict(pose_random=True) if a.pose_random else {}))
    choices = dict(teaching.VISION_SKEW_CHOICES if any(kw.values()) else {}, **sites.parse_choices(a.choice))
    layout = sites.Layout(**choices)
    import omx_two_arm_world as world_mod
    world, out = world_mod.World(layout), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in a.tasks.split(","):
        for seed in map(int, a.seeds.split(",")):
            for mode in a.modes.split(","):
                path = out / f"{name.replace(':', '-')}-{seed}-{mode}.json"
                if path.exists():
                    continue
                result = run_scenario(world, layout, name, seed, mode, zero_error_deg=a.zero_error_deg, lag=a.servo_lag, max_s=a.max_s, **kw)
                path.write_text(json.dumps(dict(result, task=name, choices=layout.choices), default=str), encoding="utf-8")
                print(name, seed, mode, json.dumps(result["summary"], default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
