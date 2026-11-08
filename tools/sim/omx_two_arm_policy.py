#!/usr/bin/env python3
"""One ACT model for both arms: the cell's four cameras and 12 joints in, 12 joint targets out.

The plan gives each arm's current step (from which site to which site) as a goal vector; the model sees only the cameras and the joints, so
where the container really lies comes from the images. Two modes: `steps` (one arm at a time, a LeRobot episode is one step) and `concurrent`
(both arms at once by omx_two_arm_plan.py's order and zones, an episode is one whole task, both arms' goals in every frame). Run on a lab PC,
in a LeRobot environment that can import mujoco:

    MUJOCO_GL=egl python tools/sim/omx_two_arm_policy.py round --root R --python P --lerobot-train T --seeds 30 --steps 60000 [--mode concurrent]
    MUJOCO_GL=egl python tools/sim/omx_two_arm_policy.py evaluate --model DIR --steps-file F --out F2 --artifacts DIR

`--skill grasp|release` learns only that part of each step (omx_two_arm_skill.py: the teacher's IK does the rest) under `--zero-error-deg`
joint-zero calibration error and `--servo-lag`, and the round also judges that IK alone on the same seeds (`eval-ik.json`).
`--policy smolvla --base-model B --vlm-assets V` fine-tunes SmolVLA offline instead of training ACT, with the step's arm and site as its
language input.

A round is `<root>/two_arm_rounds/<id>/round.json` (rosy.omx-two-arm-round.v1). MuJoCo answers geometry only (D-947); no learned policy reaches the real arm (D-793).
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import omx_ladder as ladder  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_skill as skills  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import omx_two_arm_teacher as teaching  # noqa: E402

SCHEMA = "rosy.omx-two-arm-round.v1"
SHAPE = (240, 320)
TASKS = ("stack", "outbound")  # the conveyor stack and Harbor's outbound plan in two-arm mode (omx_two_arm_plan.py)
GOAL = "observation.environment_state"
PROMPT = "carry the container of this plan step"
TRAIN_SEED_BASE, EVAL_SEED_BASE = 1000, 200000  # the teacher never saw an evaluation seed


GOAL_SIZE = 22  # per arm (arm_a, arm_b): active, then the five grasp joints and the five lower joints


def goal_block(layout, step, here):
    """One arm's part of the goal: 1, then the five joints that grasp at the source and lower onto the target, from the teacher's own IK on
    the nominal sites. Round 1 gave site metres: sites 36 mm apart differed by 0.36 in an unnormalised input and the model came down 2 cm off."""
    arm = layout.sim_arms[step["arm"]]
    wps = tasks.waypoints(layout, step, here)
    ok, _, path, note = tasks.solve_chain(arm, wps, arm.home, roll_floor=layout.roll_floor)
    if not ok:
        raise ValueError(f"{step['id']}: {note}")
    per = (len(path) - 1) // (len(wps) - 1)
    grasp, lower = path[per], path[5 * per]  # waypoints 1 and 5: grasp and lower
    return np.array([1., *grasp[:5], *lower[:5]], dtype=np.float32)


def goal_of(blocks):
    """The goal vector from {arm: block}; an arm without a step has zeros (it waits)."""
    out = np.zeros(GOAL_SIZE, np.float32)
    for arm, block in blocks.items():
        k = sites.ARMS.index(arm) * (GOAL_SIZE // 2)
        out[k:k + GOAL_SIZE // 2] = block
    return out


def goal_vector(layout, step, here):
    return goal_of({step["arm"]: goal_block(layout, step, here)})


def observe(world, data, zero_error=None):
    """The joints as the arm reports them (true minus its calibration error) and the four cameras."""
    state = np.concatenate([data.qpos[world.q[arm]] - (zero_error or {}).get(arm, 0.) for arm in sites.ARMS]).astype(np.float32)
    return state, {view: world.render(data, view, SHAPE) for view in teaching.RECORDED}


def sheet(images):
    return np.vstack([np.hstack([images[view] for view in row]) for row in (teaching.RECORDED[:2], teaching.RECORDED[2:])])


class Recorder(teaching.Teacher):
    """A teacher that saves each passed step as an episode (a failed step spoils the rest of its run), or with `concurrent` one whole
    two-arm task per episode, every frame with both arms' goals, kept only when the whole task passed."""

    def __init__(self, world, dataset, longest, concurrent=False, skill=None, **options):
        super().__init__(world, **options)
        self.dataset, self.longest, self.goal, self.spoiled, self.count = dataset, longest, None, False, 0
        self.concurrent, self.recording, self.blocks, self.skill, self.prompt = concurrent, False, {}, skill, PROMPT

    def frame(self, data, targets, label, ctxs=None):
        goal = self.goal
        if self.recording:
            for c in ctxs or []:
                if c.step["id"] not in self.blocks:
                    self.blocks[c.step["id"]] = goal_block(self.layout, c.step, c.here)
            goal = goal_of({c.arm: self.blocks[c.step["id"]] for c in ctxs or []})
        if goal is not None and (self.skill is None or self.phase in skills.SKILLS[self.skill]["phases"]):
            state, images = observe(self.world, data, self.zero_error)
            # the privileged teacher moves in true angles; the arm is commanded in reported ones
            action = np.concatenate([targets[arm] - self.zero_error.get(arm, 0.) for arm in sites.ARMS]).astype(np.float32)
            self.dataset.add_frame({"observation.state": state, "action": action, GOAL: goal,
                                    **{f"observation.images.{view}": image for view, image in images.items()}, "task": self.prompt})
            self.count += 1
        super().frame(data, targets, label, ctxs)

    def run_task(self, task, isolated=False, concurrent=False):
        if not self.concurrent:
            return super().run_task(task, isolated)
        self.recording, self.blocks = True, {}
        result = super().run_task(task, concurrent=True)
        self.recording = False
        if result["completed"]:
            self.dataset.save_episode()
            for sid, t in result["timing"].items():  # each step's teacher time and when it lifted, for the concurrent evaluation
                key, frames = f"{task['name']}/{sid}", round((t["end_s"] - t["start_s"]) * teaching.FPS)
                old = self.longest.get(key, dict(frames=0, picked=0))
                self.longest[key] = dict(frames=max(old["frames"], frames), picked=max(old["picked"], round((t.get("picked_s", t["end_s"]) - t["start_s"]) * teaching.FPS)))
        else:
            self.spoiled = True
            self.dataset.clear_episode_buffer()
        return result

    def run_step(self, data, step, here):
        self.goal, self.count = goal_vector(self.layout, step, here), 0
        self.prompt = skills.prompt(step, self.skill) if self.skill else PROMPT
        row = super().run_step(data, step, here)
        self.goal = None
        if row["result"] == "pass" and not self.spoiled:
            self.dataset.save_episode()
            self.longest[step["id"]] = max(self.longest.get(step["id"], 0), self.count)
        else:
            self.spoiled = True
            self.dataset.clear_episode_buffer()
        return row


def plan_tasks(plan_dir, names):
    """The two-arm plans of omx_two_arm_plan.py (compare --replay-dir) by task name, for concurrent collection and evaluation."""
    return {name: dict(json.loads((Path(plan_dir) / f"{name}-two-arm.json").read_text(encoding="utf-8")), name=name) for name in names}


def collect(seeds, names, out, plan_dir=None, choices=None, skill=None, zero_error_deg=0., lag=False):
    if skill and plan_dir:
        raise ValueError("a sub-skill is recorded one step at a time, not in concurrent mode")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import omx_two_arm_world as world_mod
    joints = [f"{arm}.{joint}" for arm in sites.ARMS for joint in world_mod.JOINTS]
    vector = dict(dtype="float32", shape=(12,), names=joints)  # radians, unlike the real recordings' normalised units
    image = dict(dtype="video", shape=(*SHAPE, 3), names=["height", "width", "channels"])
    goal = dict(dtype="float32", shape=(GOAL_SIZE,), names=[f"goal{i}" for i in range(GOAL_SIZE)])
    layout = sites.Layout(**(choices or {}))
    world = world_mod.World(layout)
    dataset = LeRobotDataset.create("rosy/omx-two-arm", world_mod.FPS, root=out, robot_type="omx_follower_pair", features={
        "observation.state": vector, "action": vector, GOAL: goal, **{f"observation.images.{view}": image for view in teaching.RECORDED}})
    longest, spoiled = {}, []
    planned = plan_tasks(plan_dir, names) if plan_dir else None
    for seed in seeds:
        for name in names:
            teacher = Recorder(world, dataset, longest, concurrent=planned is not None, skill=skill, seed=seed)
            skills.disturb(teacher, seed, zero_error_deg, lag)
            teacher.run_task(planned[name] if planned else tasks.get_task(layout, name))
            if teacher.spoiled:
                spoiled.append(f"{name}:{seed}")
            print("collected", name, seed, flush=True)
    dataset.finalize()
    (Path(out).parent / f"{Path(out).name}.steps.json").write_text(json.dumps(dict(longest=longest, spoiled=spoiled)), encoding="utf-8")
    return 0


class Driver:
    """Runs plan steps with the model in the teacher's place, under the teacher's judgement."""

    def __init__(self, model, steps_file, choices=None):
        import omx_two_arm_world as world_mod
        import torch
        from lerobot.policies.factory import make_pre_post_processors
        self.torch = torch
        # "ik": no model, the teacher's own IK in reported angles (the sub-skill baseline)
        self.kind = "ik" if str(model) == "ik" else json.loads((Path(model) / "config.json").read_text(encoding="utf-8"))["type"]
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.kind == "act":
            from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
            self.policy = ACTPolicy.from_pretrained(model, local_files_only=True).to(device).eval()
            config = self.policy.config  # temporal ensembling: one new chunk each frame, averaged; round 1 without it drove a link into the container
            config.temporal_ensemble_coeff, config.n_action_steps = .01, 1
            self.policy.temporal_ensembler = ACTTemporalEnsembler(.01, config.chunk_size)
        elif self.kind == "smolvla":
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            self.policy = SmolVLAPolicy.from_pretrained(model, local_files_only=True).to(device).eval()
            # 5 of the 50-step chunk per inference (0.33 s at 15 fps): one inference per frame is ~0.1 s (policy latency 2026-10-25)
            self.policy.config.n_action_steps = 5
        elif self.kind != "ik":
            raise ValueError(f"unknown policy type {self.kind}")
        if self.kind != "ik":
            self.pre, self.post = make_pre_post_processors(self.policy.config, pretrained_path=str(model))
            self.device = next(self.policy.parameters()).device
        self.layout = sites.Layout(**(choices or {}))
        self.world = world_mod.World(self.layout)
        self.longest = json.loads(Path(steps_file).read_text(encoding="utf-8"))["longest"]

    def act(self, state, images, goal, prompt=PROMPT):
        torch, device = self.torch, self.device
        batch = {"observation.state": torch.from_numpy(state)[None].to(device), GOAL: torch.from_numpy(goal)[None].to(device), "task": [prompt],
                 **{f"observation.images.{view}": (torch.from_numpy(image).permute(2, 0, 1)[None].float() / 255).to(device) for view, image in images.items()}}
        return self.post(self.policy.select_action(self.pre(batch))).cpu().numpy()[0]

    def step(self, teacher, data, plan, here, sink=None):
        world, c, arm = self.world, plan["container"], plan["arm"]
        teacher.tilt = teacher.held_tilt = 0.
        teacher.contacts, teacher.carried, teacher.first = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), c, {}
        if plan["from"] == "belt":
            home = self.layout.sim_arms
            teacher.belt_in(data, plan, {o: home[o].wait for o in self.layout.arms if o != arm})
        before = {o: world.pose(data, o) for o in here if o != c}  # on the cell; one that left with Pinky is not a neighbour
        start_z, peak = world.pose(data, c)[0][2], 0.
        goal = goal_vector(self.layout, plan, {k: v for k, v in here.items() if k != c})
        self.policy.reset()
        for _ in range(self.longest[plan["id"]] + 15):  # the teacher's time for this step and a second of grace, then the verdict
            state, images = observe(world, data)
            if sink:
                sink(sheet(images))
            action = self.act(state, images, goal)
            teacher.frame(data, {name: action[i * 6:i * 6 + 6] for i, name in enumerate(sites.ARMS)}, plan["id"])
            peak = max(peak, world.pose(data, c)[0][2] - start_z)
        teacher.carried = None
        row = dict(step=plan["id"], container=c, arm=arm, source=plan["from"], target=plan["to"], lifted=bool(peak > .015))
        return teacher.verdict(data, plan, row, before)

    def concurrent(self, task, seed, sink=None):
        """A whole two-arm task with the model driving both arms: each arm's step turns on by the plan's order and zones as in the teacher,
        runs for the teacher's time on it plus a second, and is judged; its pick zones open at the teacher's lift time. Stops at a failure."""
        L, w = self.layout, self.world
        teacher = teaching.Teacher(w, seed=seed)
        here = dict(task.get("start", {}))
        data = teacher.fresh(here)
        queue = {a: [s for s in task["steps"] if s["arm"] == a] for a in L.arms}
        status, held, running, rows = {}, {}, {}, []
        self.policy.reset()
        with self.torch.inference_mode():
            for _ in range(sum(self.longest[f"{task['name']}/{s['id']}"]["frames"] + 15 for s in task["steps"])):
                for arm in L.arms:
                    s = queue[arm][0] if queue[arm] and arm not in running else None
                    if s is None or not all(status.get(d) == "done" for d in s.get("after", [])) or not all(status.get(d) for d in s.get("after_pick", [])) \
                            or any(z in held for z in set(s["zones"][0]) | set(s["zones"][1])):
                        continue
                    queue[arm].pop(0)
                    held.update({z: s["id"] for z in set(s["zones"][0]) | set(s["zones"][1])})
                    if s["from"] == "belt":
                        w.put(data, s["container"], "belt")
                    ctx, others = teaching.Ctx(arm), {k: v for k, v in here.items() if k != s["container"]}
                    ctx.carried = s["container"]
                    budget = self.longest[f"{task['name']}/{s['id']}"]
                    running[arm] = dict(step=s, ctx=ctx, t=0, budget=budget, block=goal_block(L, s, others), before={o: w.pose(data, o) for o in others},
                                        start_z=w.pose(data, s["container"])[0][2], peak=0., pick_only=set(s["zones"][0]) - set(s["zones"][1]))
                if not running and not any(queue.values()):
                    break
                state, images = observe(w, data)
                if sink:
                    sink(sheet(images))
                action = self.act(state, images, goal_of({arm: r["block"] for arm, r in running.items()}))
                ctxs = [r["ctx"] for r in running.values()]
                for c in ctxs:
                    c.others |= {o.carried for o in ctxs if o is not c}
                teacher.frame(data, {name: action[i * 6:i * 6 + 6] for i, name in enumerate(sites.ARMS)}, "policy", ctxs)
                for arm, r in list(running.items()):
                    s, c = r["step"], r["step"]["container"]
                    r["t"] += 1
                    r["peak"] = max(r["peak"], w.pose(data, c)[0][2] - r["start_z"])
                    if r["t"] == r["budget"]["picked"]:
                        status[s["id"]] = "picked"
                        held = {z: i for z, i in held.items() if not (i == s["id"] and z in r["pick_only"])}
                        here.pop(c, None)
                    if r["t"] < r["budget"]["frames"] + 15:
                        continue
                    row = dict(step=s["id"], container=c, arm=arm, source=s["from"], target=s["to"], lifted=bool(r["peak"] > .015), task=task["name"], seed=seed)
                    rows.append(teacher.verdict(data, s, row, r["before"], r["ctx"]))
                    print(json.dumps(rows[-1]), flush=True)
                    status[s["id"]], here[c] = "done", s["to"]
                    held = {z: i for z, i in held.items() if i != s["id"]}
                    teacher.off_stand(data, s, here)
                    del running[arm]
                if rows and rows[-1]["result"] != "pass":
                    break
        passed = sum(row["result"] == "pass" for row in rows)
        return rows, dict(task=task["name"], seed=seed, total=len(task["steps"]), passed=passed, completed=passed == len(task["steps"]), last=rows[-1] if rows else {})

    def isolated(self, name, seed):
        """Each step from the plan's nominal state with the teacher's belt and start spread, so one failure does not hide the next step."""
        task = tasks.get_task(self.layout, name)
        here, rows = dict(task.get("start", {})), []
        with self.torch.inference_mode():
            for plan in task["steps"]:
                teacher = teaching.Teacher(self.world, seed=seed + len(rows))
                data = teacher.fresh(here)
                rows.append(dict(self.step(teacher, data, plan, here), task=name, seed=seed))
                print(json.dumps(rows[-1]), flush=True)
                here[plan["container"]] = plan["to"]
                teacher.off_stand(data, plan, here)
        return rows

    def whole(self, name, seed, sink=None):
        """The task through to its first failed step."""
        task = tasks.get_task(self.layout, name)
        teacher, done, here = teaching.Teacher(self.world, seed=seed), [], dict(task.get("start", {}))
        data = teacher.fresh(here)
        with self.torch.inference_mode():
            for plan in task["steps"]:
                done.append(self.step(teacher, data, plan, here, sink))
                if done[-1]["result"] != "pass":
                    break
                here[plan["container"]] = plan["to"]
                teacher.off_stand(data, plan, here)
        passed = sum(row["result"] == "pass" for row in done)
        return dict(task=name, seed=seed, total=len(task["steps"]), passed=passed, completed=passed == len(task["steps"]), last=done[-1])


def summarise(rows, whole):
    passed, lifted = sum(row["result"] == "pass" for row in rows), sum(row["lifted"] for row in rows)
    per_step = {}
    for row in rows:
        key = f'{row["task"]}/{row["step"]}'
        per_step[key] = per_step.get(key, 0) + (row["result"] == "pass")
    return dict(n=len(rows), passed=passed, lifted=lifted, wilson_low=ladder.wilson_low(passed, len(rows)), wilson_high=ladder.wilson_high(passed, len(rows)), per_step=per_step,
                whole=[{key: run[key] for key in ("task", "seed", "total", "passed", "completed")} for run in whole])


def evaluate(args):
    import av
    driver = Driver(args.model, args.steps_file, sites.parse_choices(args.choice))
    rows, runs = [], []
    Path(args.artifacts).mkdir(parents=True, exist_ok=True)
    planned = plan_tasks(args.plan_dir, args.tasks.split(",")) if args.plan_dir else None
    if args.skill:
        for name in args.tasks.split(","):
            for k in range(args.isolated_seeds):
                rows += skills.isolated(driver, name, EVAL_SEED_BASE + 1000 * k, args.skill, args.zero_error_deg, args.servo_lag)
        Path(args.out).write_text(json.dumps(dict(rows=rows, whole=[], policy=driver.kind), default=str), encoding="utf-8")
        return 0
    for name in args.tasks.split(","):
        for k in range(0 if planned else args.isolated_seeds):
            rows += driver.isolated(name, EVAL_SEED_BASE + 1000 * k)
        for k in range(args.whole_seeds):
            container = av.open(str(Path(args.artifacts) / f"{name}-seed{k}.mp4"), "w") if k == 0 else None
            sink = None
            if container:
                stream = container.add_stream("h264", rate=15)
                stream.width, stream.height, stream.pix_fmt = SHAPE[1] * 2, SHAPE[0] * 2, "yuv420p"
                sink = lambda image, s=stream, c=container: c.mux(s.encode(av.VideoFrame.from_ndarray(image, format="rgb24")))  # noqa: E731
            if planned:
                found, run = driver.concurrent(planned[name], EVAL_SEED_BASE + 500 + 1000 * k, sink)
                rows += found
                runs.append(run)
            else:
                runs.append(driver.whole(name, EVAL_SEED_BASE + 500 + 1000 * k, sink))
            print(json.dumps(runs[-1]), flush=True)
            if container:
                container.mux(stream.encode(None))
                container.close()
    Path(args.out).write_text(json.dumps(dict(rows=rows, whole=runs), default=str), encoding="utf-8")
    return 0


def outcome(score, skill=None):
    """A round that ran to the end has not passed: Rosy Learning shows this status, so only finished tasks earn it."""
    if skill:
        return skills.outcome(score, skill)
    if score["whole"] and all(run["completed"] for run in score["whole"]):
        return dict(status="passed")
    return dict(status="failed", reason="평가에서 작업을 끝까지 마치지 못했습니다.")


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_record(run, record):
    temporary = run / "round.tmp"
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, run / "round.json")


def run_round(args):
    ladder.require_gpu(args.python)
    round_id = ladder.new_round_id()
    run = Path(args.root) / "two_arm_rounds" / round_id
    run.mkdir(parents=True)
    names = args.tasks.split(",")
    if args.skill and args.mode != "steps" or args.policy == "smolvla" and not (args.base_model and args.vlm_assets):
        raise SystemExit("a sub-skill needs --mode steps; SmolVLA needs --base-model and --vlm-assets (local, offline)")
    recipe = dict(ladder.RECIPE, steps=args.steps, optimizer_lr=args.lr, batch_size=args.batch_size, mode=args.mode, policy=args.policy,
                  skill=args.skill, zero_error_deg=args.zero_error_deg, servo_lag=args.servo_lag)
    record = dict(schema=SCHEMA, round_id=round_id, created_at=now(), source_sha=ladder.source_sha(args), status="running", stage="collect", cameras=list(teaching.RECORDED),
                  tasks=names, seeds=args.seeds, recipe=recipe, choices=sites.parse_choices(args.choice), claim="기하: 도달·순서·충돌(D-947). 실물 근거가 아닙니다.")
    write_record(run, record)
    me, environment = str(Path(__file__)), dict(os.environ, MUJOCO_GL="egl", PYTHONUNBUFFERED="1")
    log = (run / "round.log").open("w", encoding="utf-8")
    chosen = [arg for item in args.choice or [] for arg in ("--choice", item)]  # the same layout for plan, collection and judgement
    skilled = skills.argv(args)
    try:
        plan = []
        if args.mode == "concurrent":  # one plan for all workers and the evaluation: omx_two_arm_plan.py's two-arm order and zones
            subprocess.run([args.python, str(Path(__file__).with_name("omx_two_arm_plan.py")), "compare", "--out", str(run / "plan.json"), "--replay-dir", str(run / "plan"), *chosen],
                           env=dict(environment, PYTHONIOENCODING="utf-8"), stdout=log, stderr=subprocess.STDOUT, check=True)
            plan = ["--plan-dir", str(run / "plan")]
        # One process per part: rendering four cameras is what takes the time, and LeRobot writes one dataset at a time.
        parts = [(run / f"part{k}", list(range(TRAIN_SEED_BASE + k, TRAIN_SEED_BASE + args.seeds, args.workers))) for k in range(min(args.workers, args.seeds))]
        running = [subprocess.Popen([args.python, me, "collect", "--seeds", ",".join(map(str, seeds)), "--tasks", args.tasks, "--out", str(part), *plan, *chosen, *skilled],
                                    env=dict(environment, OMP_NUM_THREADS="1"), stdout=log, stderr=subprocess.STDOUT) for part, seeds in parts]
        if any(worker.wait() for worker in running):
            raise RuntimeError("collect")
        longest, spoiled = {}, []
        for part, _ in parts:
            found = json.loads((run / f"{part.name}.steps.json").read_text(encoding="utf-8"))
            spoiled += found["spoiled"]
            for key, value in found["longest"].items():
                longest[key] = {k: max(v, longest.get(key, {}).get(k, 0)) for k, v in value.items()} if isinstance(value, dict) else max(longest.get(key, 0), value)
        (run / "steps.json").write_text(json.dumps(dict(longest=longest, spoiled=spoiled)), encoding="utf-8")
        subprocess.run([args.python, "-c", "import sys; from pathlib import Path; from lerobot.datasets.aggregate import aggregate_datasets as a; p=[Path(x) for x in sys.argv[2:]]; "
                        "a([f'rosy/part{i}' for i in range(len(p))], 'rosy/omx-two-arm', roots=p, aggr_root=Path(sys.argv[1]))", str(run / "dataset"), *[str(part) for part, _ in parts]],
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        info = json.loads((run / "dataset/meta/info.json").read_text(encoding="utf-8"))
        for part, _ in parts:
            shutil.rmtree(part)
        record.update(stage="train", data=dict(episodes=info["total_episodes"], frames=info["total_frames"], spoiled_runs=spoiled))
        write_record(run, record)
        common = [f"--batch_size={recipe['batch_size']}", f"--steps={recipe['steps']}", f"--save_freq={max(1, recipe['steps'] // 3)}", "--log_freq=500",
                  f"--num_workers={args.train_workers}", "--wandb.enable=false", f"--output_dir={run / 'train'}",
                  # whole-task episodes put frames 1400 s into a video file: float rounding exceeded the 0.1 ms default (round 4)
                  "--tolerance_s=0.001"]
        dataset = [f"--dataset.repo_id=rosy/omx-two-arm-{round_id}", f"--dataset.root={run / 'dataset'}", "--dataset.video_backend=pyav"]
        if args.policy == "smolvla":
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "learning/training/omx"))
            import smolvla_training  # the same offline snapshot of smolvla_base and SmolVLM2 as the native cycle
            prepared = smolvla_training.prepare(args.base_model, args.vlm_assets, run / "inputs", device="cuda")
            (run / "train-config.json").write_text(json.dumps(dict(policy=dict(prepared["policy"], optimizer_lr=args.lr), job_name="omx-two-arm-smolvla")), encoding="utf-8")
            command = [args.lerobot_train, f"--config_path={run / 'train-config.json'}", *dataset, *common]
            environment.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1")
        else:
            command = [args.lerobot_train, *dataset, "--policy.type=act", "--policy.device=cuda", "--policy.push_to_hub=false", f"--policy.chunk_size={recipe['chunk_size']}",
                       f"--policy.n_action_steps={recipe['n_action_steps']}", f"--policy.optimizer_lr={recipe['optimizer_lr']}", "--job_name=omx-two-arm", *common]
        subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        record.update(stage="evaluate")
        write_record(run, record)
        judged = [("eval.json", str(run / "train/checkpoints/last/pretrained_model"))] + ([("eval-ik.json", "ik")] if args.skill else [])
        for out, model in judged:  # a sub-skill round also judges the IK it would replace on the same seeds
            subprocess.run([args.python, me, "evaluate", "--model", model, "--steps-file", str(run / "steps.json"), "--tasks", args.tasks,
                            "--isolated-seeds", str(args.isolated_seeds), "--whole-seeds", str(args.whole_seeds), "--out", str(run / out), "--artifacts", str(run / "artifacts"),
                            *plan, *chosen, *skilled], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        record.update(status="failed", reason=f"{record['stage']} 단계 실패({exc}). round.log를 보세요.", finished_at=now())
        write_record(run, record)
        return 1
    result = json.loads((run / "eval.json").read_text(encoding="utf-8"))
    score = summarise(result["rows"], result["whole"])
    if args.skill:
        baseline = json.loads((run / "eval-ik.json").read_text(encoding="utf-8"))
        record.update(eval_ik=summarise(baseline["rows"], []))
    record.update(outcome(score, args.skill), stage="done", eval=score, finished_at=now(), artifacts=sorted(path.name for path in (run / "artifacts").glob("*.mp4")))
    write_record(run, record)
    print(json.dumps(dict(round_id=round_id, eval=record["eval"]), ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("collect")
    one.add_argument("--seeds", required=True)
    one.add_argument("--tasks", default=",".join(TASKS))
    one.add_argument("--out", required=True)
    one.add_argument("--plan-dir", help="two-arm plans (omx_two_arm_plan.py --replay-dir): record whole tasks with both arms at once")
    one.add_argument("--choice", action="append", help="key=value override of omx_two_arm_sites.CHOICES")
    skills.options(one)
    for name in ("evaluate", "round"):
        one = commands.add_parser(name)
        one.add_argument("--tasks", default=",".join(TASKS))
        one.add_argument("--isolated-seeds", type=int, default=3)
        one.add_argument("--whole-seeds", type=int, default=3)
        one.add_argument("--choice", action="append", help="key=value override of omx_two_arm_sites.CHOICES")
        skills.options(one)
        if name == "evaluate":
            one.add_argument("--model", required=True, help="a trained ACT or SmolVLA model folder, or ik for the teacher's IK in reported angles")
            one.add_argument("--steps-file", required=True)
            one.add_argument("--out", required=True)
            one.add_argument("--artifacts", required=True)
            one.add_argument("--plan-dir", help="judge whole tasks with both arms at once by these plans")
    one.add_argument("--root", required=True)
    one.add_argument("--python", default=sys.executable)
    one.add_argument("--lerobot-train", required=True)
    one.add_argument("--source-sha", help="the commit this copy came from, when the folder has no Git")
    one.add_argument("--seeds", type=int, default=30)
    one.add_argument("--workers", type=int, default=6)
    one.add_argument("--train-workers", type=int, default=8)
    one.add_argument("--steps", type=int, default=60000)
    one.add_argument("--lr", type=float, default=1e-4)
    one.add_argument("--batch-size", type=int, default=8)
    one.add_argument("--mode", default="steps", choices=["steps", "concurrent"], help="one arm at a time per step, or whole tasks with both arms at once")
    one.add_argument("--policy", default="act", choices=["act", "smolvla"])
    one.add_argument("--base-model", help="SmolVLA: local smolvla_base folder")
    one.add_argument("--vlm-assets", help="SmolVLA: local SmolVLM2-500M-Video-Instruct folder")
    args = parser.parse_args(argv)
    if args.command == "collect":
        return collect([int(seed) for seed in args.seeds.split(",")], args.tasks.split(","), args.out, args.plan_dir, sites.parse_choices(args.choice),
                       args.skill, args.zero_error_deg, args.servo_lag)
    return evaluate(args) if args.command == "evaluate" else run_round(args)


if __name__ == "__main__":
    raise SystemExit(main())
