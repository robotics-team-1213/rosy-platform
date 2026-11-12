"""Goal vector encoding, dataset collection (`Recorder`, `collect`), and closed-loop policy evaluation (`Driver`) for `omx_two_arm_policy`."""
import json
from pathlib import Path
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_skill as skills  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import omx_two_arm_teacher as teaching  # noqa: E402

SHAPE = (240, 320)
TASKS = ("stack", "outbound")  # the conveyor stack and Harbor's outbound plan in two-arm mode (omx_two_arm_plan.py)
GOAL = "observation.environment_state"
PROMPT = "carry the container of this plan step"
TRAIN_SEED_BASE, EVAL_SEED_BASE = 1000, 200000  # the teacher never saw an evaluation seed
STEP_ERROR_SEED_BASE = 10 ** 6  # collect's per-step error draws, clear of the training and evaluation seeds
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
            for sid, t in result["timing"].items():
                key, frames = f"{task['name']}/{sid}", round((t["end_s"] - t["start_s"]) * teaching.FPS)
                old = self.longest.get(key, dict(frames=0, picked=0))
                self.longest[key] = dict(frames=max(old["frames"], frames), picked=max(old["picked"], round((t.get("picked_s", t["end_s"]) - t["start_s"]) * teaching.FPS)))
        else:
            self.spoiled = True
            self.dataset.clear_episode_buffer()
        return result

    def run_step(self, data, step, here):
        if self.skill and getattr(self, "error_draw", None):
            seed, deg, physics = self.error_draw
            self.error_draw, self.zero_error = (seed + 1, deg, physics), skills.draw_errors(seed, deg, physics)
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


def collect(seeds, names, out, plan_dir=None, choices=None, skill=None, zero_error_deg=0., lag=False, physics=False, *, pick_vision=False, belt_skew=False):
    if skill and plan_dir:
        raise ValueError("a sub-skill is recorded one step at a time, not in concurrent mode")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import omx_two_arm_world as world_mod
    joints = [f"{arm}.{joint}" for arm in sites.ARMS for joint in world_mod.JOINTS]
    vector = dict(dtype="float32", shape=(12,), names=joints)
    image = dict(dtype="video", shape=(*SHAPE, 3), names=["height", "width", "channels"])
    goal = dict(dtype="float32", shape=(GOAL_SIZE,), names=[f"goal{i}" for i in range(GOAL_SIZE)])
    choices = dict(teaching.VISION_SKEW_CHOICES if (pick_vision or belt_skew) else {}, **(choices or {}))
    layout = sites.Layout(**choices)
    world = world_mod.World(layout)
    dataset = LeRobotDataset.create("rosy/omx-two-arm", world_mod.FPS, root=out, robot_type="omx_follower_pair", features={
        "observation.state": vector, "action": vector, GOAL: goal, **{f"observation.images.{view}": image for view in teaching.RECORDED}})
    longest, spoiled = {}, []
    planned = plan_tasks(plan_dir, names) if plan_dir else None
    for seed in seeds:
        for name in names:
            teacher = Recorder(world, dataset, longest, concurrent=planned is not None, skill=skill, seed=seed, pick_vision=pick_vision, belt_skew=belt_skew)
            skills.disturb(teacher, seed, zero_error_deg, lag, physics)
            teacher.error_draw = (STEP_ERROR_SEED_BASE + 100 * seed + 50 * names.index(name), zero_error_deg, physics)
            teacher.run_task(planned[name] if planned else tasks.get_task(layout, name))
            if teacher.spoiled:
                spoiled.append(f"{name}:{seed}")
            print("collected", name, seed, flush=True)
    dataset.finalize()
    (Path(out).parent / f"{Path(out).name}.steps.json").write_text(json.dumps(dict(longest=longest, spoiled=spoiled)), encoding="utf-8")
    return 0


class Driver:
    """Runs plan steps with the model in the teacher's place, under the teacher's judgement."""

    def __init__(self, model, steps_file, choices=None, *, pick_vision=False, belt_skew=False):
        import omx_two_arm_world as world_mod
        import torch
        from lerobot.policies.factory import make_pre_post_processors
        self.torch = torch
        self.kind = "ik" if str(model) == "ik" else json.loads((Path(model) / "config.json").read_text(encoding="utf-8"))["type"]
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.kind == "act":
            from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
            self.policy = ACTPolicy.from_pretrained(model, local_files_only=True).to(device).eval()
            config = self.policy.config
            config.temporal_ensemble_coeff, config.n_action_steps = .01, 1
            self.policy.temporal_ensembler = ACTTemporalEnsembler(.01, config.chunk_size)
        elif self.kind == "smolvla":
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            self.policy = SmolVLAPolicy.from_pretrained(model, local_files_only=True).to(device).eval()
            self.policy.config.n_action_steps = 5
        elif self.kind != "ik":
            raise ValueError(f"unknown policy type {self.kind}")
        if self.kind != "ik":
            self.pre, self.post = make_pre_post_processors(self.policy.config, pretrained_path=str(model))
            self.device = next(self.policy.parameters()).device
        choices = dict(teaching.VISION_SKEW_CHOICES if (pick_vision or belt_skew) else {}, **(choices or {}))
        self.layout = sites.Layout(**choices)
        self.world = world_mod.World(self.layout)
        self.longest = json.loads(Path(steps_file).read_text(encoding="utf-8"))["longest"]
        self.pick_vision = pick_vision
        self.belt_skew = belt_skew

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
        before = {o: world.pose(data, o) for o in here if o != c}
        start_z, peak = world.pose(data, c)[0][2], 0.
        goal = goal_vector(self.layout, plan, {k: v for k, v in here.items() if k != c})
        self.policy.reset()
        for _ in range(self.longest[plan["id"]] + 15):
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
        """A whole two-arm task with the model driving both arms."""
        L, w = self.layout, self.world
        teacher = teaching.Teacher(w, seed=seed, pick_vision=self.pick_vision, belt_skew=self.belt_skew)
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
                        w.put(data, s["container"], "belt", **(teacher.skew_for(s) if teacher.belt_skew else {}))
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
        """Each step from the plan's nominal state with the teacher's belt and start spread."""
        task = tasks.get_task(self.layout, name)
        here, rows = dict(task.get("start", {})), []
        with self.torch.inference_mode():
            for plan in task["steps"]:
                teacher = teaching.Teacher(self.world, seed=seed + len(rows), pick_vision=self.pick_vision, belt_skew=self.belt_skew)
                data = teacher.fresh(here)
                rows.append(dict(self.step(teacher, data, plan, here), task=name, seed=seed))
                print(json.dumps(rows[-1]), flush=True)
                here[plan["container"]] = plan["to"]
                teacher.off_stand(data, plan, here)
        return rows

    def whole(self, name, seed, sink=None):
        """The task through to its first failed step."""
        task = tasks.get_task(self.layout, name)
        teacher, done, here = teaching.Teacher(self.world, seed=seed, pick_vision=self.pick_vision, belt_skew=self.belt_skew), [], dict(task.get("start", {}))
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
