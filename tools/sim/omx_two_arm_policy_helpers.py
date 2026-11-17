"""Goal vector encoding, dataset collection (`Recorder`, `collect`), and closed-loop policy evaluation (`Driver`) for `omx_two_arm_policy`."""
from contextlib import nullcontext
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
# joints: the teacher's IK joints (needs the sim's site geometry); site: which source and target site by name (an admitted job carries
# exactly this on the real cell, 2026-11-17 panel), so ACT can be told which container to take without language or privileged state.
GOAL_MODES = ("joints", "site")


def site_names(layout):
    return sorted(layout.sites)


def goal_size(layout, mode="joints"):
    return GOAL_SIZE if mode == "joints" else 2 * (1 + 2 * len(site_names(layout)))


def goal_block(layout, step, here, mode="joints"):
    """One arm's part of the goal. `site`: 1, then one-hot source and one-hot target over `site_names`. `joints`: 1, then the five joints
    that grasp at the source and lower onto the target, from the teacher's own IK on the nominal sites. Round 1 gave site metres: sites
    36 mm apart differed by 0.36 in an unnormalised input and the model came down 2 cm off."""
    if mode == "site":
        names = site_names(layout)
        out = np.zeros(1 + 2 * len(names), np.float32)
        out[0], out[1 + names.index(step["from"])], out[1 + len(names) + names.index(step["to"])] = 1., 1., 1.
        return out
    if mode != "joints":
        raise ValueError(f"goal mode {mode!r} not in {GOAL_MODES}")
    arm = layout.sim_arms[step["arm"]]
    wps = tasks.waypoints(layout, step, here)
    ok, _, path, note = tasks.solve_chain(arm, wps, arm.home, roll_floor=layout.roll_floor)
    if not ok:
        raise ValueError(f"{step['id']}: {note}")
    per = (len(path) - 1) // (len(wps) - 1)
    grasp, lower = path[per], path[5 * per]  # waypoints 1 and 5: grasp and lower
    return np.array([1., *grasp[:5], *lower[:5]], dtype=np.float32)


def goal_of(blocks, size=GOAL_SIZE):
    """The goal vector from {arm: block}; an arm without a step has zeros (it waits)."""
    out = np.zeros(size, np.float32)
    for arm, block in blocks.items():
        k = sites.ARMS.index(arm) * (size // 2)
        out[k:k + size // 2] = block
    return out


def goal_vector(layout, step, here, mode="joints"):
    return goal_of({step["arm"]: goal_block(layout, step, here, mode)}, goal_size(layout, mode))


def dataset_features(joints, views, size=None):
    """The LeRobot features of a two-arm dataset: `collect` and the real-recording export (learning/curation/omx/two_arm_export.py) both build them here."""
    vector = dict(dtype="float32", shape=(len(joints),), names=list(joints))
    image = dict(dtype="video", shape=(*SHAPE, 3), names=["height", "width", "channels"])
    features = {"observation.state": vector, "action": vector, **{f"observation.images.{view}": image for view in views}}
    if size:
        features[GOAL] = dict(dtype="float32", shape=(size,), names=[f"goal{i}" for i in range(size)])
    return features


def observe(world, data, zero_error=None):
    """The joints as the arm reports them (true minus its calibration error) and the four cameras."""
    state = np.concatenate([data.qpos[world.q[arm]] - (zero_error or {}).get(arm, 0.) for arm in sites.ARMS]).astype(np.float32)
    return state, {view: world.render(data, view, SHAPE) for view in teaching.RECORDED}


def sheet(images):
    return np.vstack([np.hstack([images[view] for view in row]) for row in (teaching.RECORDED[:2], teaching.RECORDED[2:])])


class Recorder(teaching.Teacher):
    """A teacher that saves each passed step as an episode (a failed step spoils the rest of its run), or with `concurrent` one whole
    two-arm task per episode, every frame with both arms' goals, kept only when the whole task passed."""

    def __init__(self, world, dataset, longest, concurrent=False, skill=None, no_goal=False, goal_mode="joints", **options):
        super().__init__(world, **options)
        self.dataset, self.longest, self.goal, self.spoiled, self.count = dataset, longest, None, False, 0
        self.concurrent, self.recording, self.blocks, self.skill, self.prompt, self.no_goal = concurrent, False, {}, skill, PROMPT, no_goal
        self.goal_mode = goal_mode

    def frame(self, data, targets, label, ctxs=None):
        goal = self.goal
        if self.recording:
            if self.no_goal:
                goal = True
            else:
                for c in ctxs or []:
                    if c.step["id"] not in self.blocks:
                        self.blocks[c.step["id"]] = goal_block(self.layout, c.step, c.here, self.goal_mode)
                goal = goal_of({c.arm: self.blocks[c.step["id"]] for c in ctxs or []}, goal_size(self.layout, self.goal_mode))
        if goal is not None and (self.skill is None or self.phase in skills.SKILLS[self.skill]["phases"]):
            state, images = observe(self.world, data, self.zero_error)
            action = np.concatenate([targets[arm] - self.zero_error.get(arm, 0.) for arm in sites.ARMS]).astype(np.float32)
            row = {"observation.state": state, "action": action,
                   **{f"observation.images.{view}": image for view, image in images.items()}, "task": self.prompt}
            if not self.no_goal:
                row[GOAL] = goal
            self.dataset.add_frame(row)
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
        self.goal, self.count = (True if self.no_goal else goal_vector(self.layout, step, here, self.goal_mode)), 0
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


def resolved_choices(choices=None, *, pick_vision=False, belt_skew=False, cam_jitter=False):
    """Merge layout overrides, adding `VISION_SKEW_CHOICES` when vision/skew perturbation is enabled."""
    return dict(teaching.VISION_SKEW_CHOICES if (pick_vision or belt_skew or cam_jitter) else {}, **(choices or {}))


def _resolve_steps_file(dagger_model, steps_file, name="steps.json"):
    if steps_file and str(steps_file).strip().lower() != "auto":
        return Path(steps_file)
    for parent in Path(dagger_model).resolve().parents:
        candidate = parent / name
        if candidate.is_file():
            return candidate
    raise ValueError(f"--dagger-model requires --steps-file (or an ancestor {name})")


def _failed_steps_from_eval(dagger_model, eval_file):
    path = _resolve_steps_file(dagger_model, eval_file, name="eval.json")
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    return {f"{r['task']}/{r['step']}" if "task" in r else r["step"] for r in rows if r.get("result") != "pass"}


def collect(seeds, names, out, plan_dir=None, choices=None, skill=None, zero_error_deg=0., lag=False, physics=False, *,
            pick_vision=False, belt_skew=False, cam_jitter=False, compensate_zero=False, no_goal=False, goal_mode="joints",
            dagger_model=None, steps_file=None, dagger_prefix_frames="auto", dagger_only=False, dagger_device=None,
            dagger_steps=None, dagger_eval_file=None, n_action_steps=None, flow_steps=None, use_amp=None):
    if goal_mode not in GOAL_MODES or (no_goal and goal_mode != "joints"):
        raise ValueError("--goal is one of joints|site and cannot go with --no-goal")
    if skill and plan_dir:
        raise ValueError("a sub-skill is recorded one step at a time, not in concurrent mode")
    if dagger_model and not skill:
        raise ValueError("--dagger-model requires --skill")
    import shutil
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import omx_two_arm_world as world_mod
    joints = [f"{arm}.{joint}" for arm in sites.ARMS for joint in world_mod.JOINTS]
    raw_choices = choices
    choices = resolved_choices(choices, pick_vision=pick_vision, belt_skew=belt_skew, cam_jitter=cam_jitter)
    layout = sites.Layout(**choices)
    dagger_driver, longest, dagger_counts = None, {}, {}
    step_filter = {s.strip() for s in dagger_steps.split(",") if s.strip()} if isinstance(dagger_steps, str) else (set(dagger_steps) if dagger_steps else None)
    if dagger_eval_file:
        eval_failed = _failed_steps_from_eval(dagger_model, dagger_eval_file)
        step_filter = eval_failed if step_filter is None else (step_filter | eval_failed)
    if dagger_model:
        resolved_steps = _resolve_steps_file(dagger_model, steps_file)
        longest = dict(json.loads(resolved_steps.read_text(encoding="utf-8")).get("longest", {}))
        dagger_driver = Driver(dagger_model, resolved_steps, raw_choices, pick_vision=pick_vision,
                               belt_skew=belt_skew, cam_jitter=cam_jitter, n_action_steps=n_action_steps,
                               flow_steps=flow_steps, use_amp=use_amp, device=dagger_device)
    world = dagger_driver.world if dagger_driver else world_mod.World(layout)
    features = dataset_features(joints, teaching.RECORDED, None if no_goal else goal_size(layout, goal_mode))
    dataset = LeRobotDataset.create("rosy/omx-two-arm", world_mod.FPS, root=out, robot_type="omx_follower_pair", features=features)
    spoiled = []
    planned = plan_tasks(plan_dir, names) if plan_dir else None
    for seed in seeds:
        for name in names:
            if not dagger_only:
                teacher = Recorder(world, dataset, longest, concurrent=planned is not None, skill=skill, no_goal=no_goal,
                                   goal_mode=goal_mode, seed=seed, pick_vision=pick_vision, belt_skew=belt_skew, cam_jitter=cam_jitter)
                skills.disturb(teacher, seed, zero_error_deg, lag, physics)
                teacher.compensate_zero = bool(compensate_zero)
                teacher.error_draw = (STEP_ERROR_SEED_BASE + 100 * seed + 50 * names.index(name), zero_error_deg, physics)
                teacher.run_task(planned[name] if planned else tasks.get_task(layout, name), isolated=bool(skill) and planned is None)
                if teacher.spoiled:
                    spoiled.append(f"{name}:{seed}")
                print("collected", name, seed, flush=True)
            if dagger_driver:
                task = tasks.get_task(layout, name)
                here = dict(task.get("start", {}))
                err_seed_base = STEP_ERROR_SEED_BASE + 100 * seed + 50 * names.index(name)
                with dagger_driver.torch.inference_mode():
                    for idx, plan in enumerate(task["steps"]):
                        if step_filter is None or plan["id"] in step_filter or f"{name}/{plan['id']}" in step_filter:
                            rec = Recorder(world, dataset, longest, skill=skill, no_goal=no_goal, goal_mode=goal_mode, seed=seed + idx,
                                           pick_vision=pick_vision, belt_skew=belt_skew, cam_jitter=cam_jitter)
                            skills.disturb(rec, err_seed_base + idx, zero_error_deg, lag, physics)
                            rec.compensate_zero = bool(compensate_zero)
                            row = skills.recover(dagger_driver, rec, plan, here, skill, prefix_frames=dagger_prefix_frames)
                            st = row.get("dagger_status", "unknown")
                            dagger_counts[st] = dagger_counts.get(st, 0) + 1
                            print("dagger", name, seed, plan["id"], st, row.get("result"), flush=True)
                        here[plan["container"]] = plan["to"]
                        if plan.get("outbound"):
                            here.pop(plan["container"], None)
    num_episodes = getattr(dataset, "num_episodes", None)
    if num_episodes == 0:
        shutil.rmtree(out, ignore_errors=True)
    else:
        dataset.finalize()
    meta = dict(longest=longest, spoiled=spoiled, goal_mode=None if no_goal else goal_mode)
    if goal_mode == "site":
        meta["goal_sites"] = site_names(layout)
    if num_episodes is not None:
        meta["episodes"] = int(num_episodes)
    if dagger_counts:
        meta["dagger"] = dagger_counts
    (Path(out).parent / f"{Path(out).name}.steps.json").write_text(json.dumps(meta), encoding="utf-8")
    return 0


class Driver:
    """Runs plan steps with the model in the teacher's place, under the teacher's judgement."""

    def __init__(self, model, steps_file, choices=None, *, pick_vision=False, belt_skew=False, cam_jitter=False,
                 ensemble_coeff=None, n_action_steps=None, flow_steps=None, use_amp=None, device=None):
        import omx_two_arm_world as world_mod
        import torch
        from lerobot.policies.factory import make_pre_post_processors
        self.torch = torch
        if flow_steps is not None and (type(flow_steps) is not int or flow_steps < 1):
            raise ValueError("positive integer flow_steps required")
        self.kind = "ik" if str(model) == "ik" else json.loads((Path(model) / "config.json").read_text(encoding="utf-8"))["type"]
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        if self.kind == "act":
            from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
            self.policy = ACTPolicy.from_pretrained(model, local_files_only=True).to(device).eval()
            config = self.policy.config
            # D-1032: preserve checkpoint temporal_ensemble_coeff (None) unless explicitly requested for comparison.
            if ensemble_coeff is not None:
                config.temporal_ensemble_coeff = ensemble_coeff
                config.n_action_steps = 1 if n_action_steps is None else n_action_steps
                self.policy.temporal_ensembler = ACTTemporalEnsembler(ensemble_coeff, config.chunk_size)
            elif n_action_steps is not None:
                config.n_action_steps = n_action_steps
        elif self.kind == "smolvla":
            from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
            self.policy = SmolVLAPolicy.from_pretrained(model, local_files_only=True).to(device).eval()
            self.policy.config.n_action_steps = 5 if n_action_steps is None else n_action_steps
            if flow_steps is not None and hasattr(self.policy.config, "num_steps"):
                self.policy.config.num_steps = flow_steps
        elif self.kind != "ik":
            raise ValueError(f"unknown policy type {self.kind}")
        if self.kind != "ik":
            # the checkpoint's processor carries the training device (cuda); without this a cpu Driver fails to load
            self.pre, self.post = make_pre_post_processors(self.policy.config, pretrained_path=str(model),
                                                           preprocessor_overrides={"device_processor": {"device": str(device)}},
                                                           postprocessor_overrides={"device_processor": {"device": "cpu"}})
            self.device = next(self.policy.parameters()).device
            self.has_goal = GOAL in (getattr(self.policy.config, "input_features", None) or {})
            dev_type = getattr(self.device, "type", str(self.device))
            self.use_amp = (bool(getattr(self.policy.config, "use_amp", False)) if use_amp is None else bool(use_amp)) and dev_type == "cuda"
        else:
            self.has_goal = True
            self.use_amp = False
        choices = resolved_choices(choices, pick_vision=pick_vision, belt_skew=belt_skew, cam_jitter=cam_jitter)
        self.layout = sites.Layout(**choices)
        self.world = world_mod.World(self.layout)
        meta = json.loads(Path(steps_file).read_text(encoding="utf-8"))
        self.longest = meta["longest"]
        self.goal_mode = "joints"
        shape = getattr(self.policy.config.input_features[GOAL], "shape", None) if self.kind != "ik" and self.has_goal else None
        if shape:  # a checkpoint's PolicyFeature; no shape keeps the old joints meaning
            size = int(shape[0])
            self.goal_mode = "joints" if size == GOAL_SIZE else "site"
            if size != goal_size(self.layout, self.goal_mode) or meta.get("goal_sites", site_names(self.layout)) != site_names(self.layout):
                raise ValueError(f"the model's {size}-wide goal does not match this layout's sites (choices differ from training?)")
        self.pick_vision = pick_vision
        self.belt_skew = belt_skew
        self.cam_jitter = cam_jitter

    def act(self, state, images, goal=None, prompt=PROMPT):
        torch, device = self.torch, self.device
        batch = {"observation.state": torch.from_numpy(state)[None].to(device), "task": [prompt],
                 **{f"observation.images.{view}": torch.from_numpy(image if image.flags.writeable else np.array(image, copy=True)).to(device).permute(2, 0, 1)[None].float() / 255
                    for view, image in images.items()}}
        if self.has_goal:
            if goal is None:
                raise ValueError("loaded policy expects observation.environment_state goal vector")
            batch[GOAL] = torch.from_numpy(goal)[None].to(device)
        mode = torch.inference_mode() if hasattr(torch, "inference_mode") else nullcontext()
        amp = torch.autocast("cuda") if getattr(self, "use_amp", False) and hasattr(torch, "autocast") else nullcontext()
        with mode, amp:
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
        goal = goal_vector(self.layout, plan, {k: v for k, v in here.items() if k != c}, self.goal_mode) if self.has_goal else None
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
        import omx_two_arm_plan as plan_mod
        L, w = self.layout, self.world
        teacher = teaching.Teacher(w, seed=seed, pick_vision=self.pick_vision, belt_skew=self.belt_skew, cam_jitter=self.cam_jitter)
        here = dict(task.get("start", {}))
        data = teacher.fresh(here)
        queue = {a: [s for s in task["steps"] if s["arm"] == a] for a in L.arms}
        status, held, running, rows, prev_active = {}, {}, {}, [], ()
        self.policy.reset()
        with self.torch.inference_mode():
            for _ in range(sum(self.longest[f"{task['name']}/{s['id']}"]["frames"] + 15 for s in task["steps"])):
                for arm in L.arms:
                    s = queue[arm][0] if queue[arm] and arm not in running else None
                    if s is None or not all(status.get(d) == "done" for d in s.get("after", [])) or not all(status.get(d) for d in s.get("after_pick", [])) \
                            or any(z in held for z in set(s["zones"][0]) | set(s["zones"][1])):
                        continue
                    others = {k: v for k, v in here.items() if k != s["container"]}
                    if running and not all(
                        plan_mod.sweeps_clear(
                            plan_mod.step_swept_poses(L, arm, s["from"], s["to"], others),
                            (poses_oa := plan_mod.step_swept_poses(L, oa, r["step"]["from"], r["step"]["to"], r["others"]) or [])[
                                int(len(poses_oa) * min(1.0, r["t"] / max(1, r["budget"]["frames"]))):
                            ],
                        )
                        for oa, r in running.items()
                    ):
                        continue
                    queue[arm].pop(0)
                    held.update({z: s["id"] for z in set(s["zones"][0]) | set(s["zones"][1])})
                    if s["from"] == "belt":
                        w.put(data, s["container"], "belt", **(teacher.skew_for(s) if teacher.belt_skew else {}))
                    ctx = teaching.Ctx(arm)
                    ctx.carried = s["container"]
                    budget = self.longest[f"{task['name']}/{s['id']}"]
                    running[arm] = dict(step=s, ctx=ctx, others=others, t=0, budget=budget,
                                        block=goal_block(L, s, others, self.goal_mode) if self.has_goal else None,
                                        before={o: w.pose(data, o) for o in others}, start_z=w.pose(data, s["container"])[0][2], peak=0.,
                                        pick_only=set(s["zones"][0]) - set(s["zones"][1]))
                if not running and not any(queue.values()):
                    break
                active = tuple((a, running[a]["step"]["id"]) for a in sorted(running))
                if active != prev_active:
                    self.policy.reset()
                    prev_active = active
                state, images = observe(w, data)
                if sink:
                    sink(sheet(images))
                goal = goal_of({arm: r["block"] for arm, r in running.items()}, goal_size(L, self.goal_mode)) if self.has_goal else None
                action = self.act(state, images, goal)
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
                teacher = teaching.Teacher(self.world, seed=seed + len(rows), pick_vision=self.pick_vision, belt_skew=self.belt_skew, cam_jitter=self.cam_jitter)
                data = teacher.fresh(here)
                rows.append(dict(self.step(teacher, data, plan, here), task=name, seed=seed))
                print(json.dumps(rows[-1]), flush=True)
                here[plan["container"]] = plan["to"]
                teacher.off_stand(data, plan, here)
        return rows

    def whole(self, name, seed, sink=None):
        """The task through to its first failed step."""
        task = tasks.get_task(self.layout, name)
        teacher, done, here = teaching.Teacher(self.world, seed=seed, pick_vision=self.pick_vision, belt_skew=self.belt_skew, cam_jitter=self.cam_jitter), [], dict(task.get("start", {}))
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
