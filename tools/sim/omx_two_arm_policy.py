#!/usr/bin/env python3
"""One ACT model for both arms: the cell's four cameras and 12 joints in, 12 joint targets out, one plan step at a time.

The plan gives the step (which arm, from which site, to which site) as a goal vector; the model sees only the cameras and the joints, so where the
container really lies comes from the images. A LeRobot episode is one step of a teacher run. Run on a lab PC, in a LeRobot environment that can import mujoco:

    MUJOCO_GL=egl python tools/sim/omx_two_arm_policy.py round --root R --python P --lerobot-train T --seeds 30 --steps 60000
    MUJOCO_GL=egl python tools/sim/omx_two_arm_policy.py evaluate --model DIR --steps-file F --out F2 --artifacts DIR

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
import omx_two_arm_tasks as tasks  # noqa: E402
import omx_two_arm_teacher as teaching  # noqa: E402

SCHEMA = "rosy.omx-two-arm-round.v1"
SHAPE = (240, 320)
TASKS = ("stack", "rehandle")
GOAL = "observation.environment_state"
PROMPT = "carry the container of this plan step"
TRAIN_SEED_BASE, EVAL_SEED_BASE = 1000, 200000  # the teacher never saw an evaluation seed


def goal_vector(layout, step, here):
    """Arm one-hot, then the five joints that grasp at the source and lower onto the target, from the teacher's own IK on the nominal sites.
    Round 1 gave site metres: sites 36 mm apart differed by 0.36 in an unnormalised input and the model came down 2 cm off."""
    arm = layout.sim_arms[step["arm"]]
    wps = tasks.waypoints(layout, step, here)
    ok, _, path, note = tasks.solve_chain(arm, wps, arm.home, roll_floor=layout.roll_floor)
    if not ok:
        raise ValueError(f"{step['id']}: {note}")
    per = (len(path) - 1) // (len(wps) - 1)
    grasp, lower = path[per], path[5 * per]  # waypoints 1 and 5: grasp and lower
    return np.array([step["arm"] == "arm_a", step["arm"] == "arm_b", *grasp[:5], *lower[:5]], dtype=np.float32)


def observe(world, data):
    state = np.concatenate([data.qpos[world.q[arm]] for arm in sites.ARMS]).astype(np.float32)
    return state, {view: world.render(data, view, SHAPE) for view in teaching.RECORDED}


def sheet(images):
    return np.vstack([np.hstack([images[view] for view in row]) for row in (teaching.RECORDED[:2], teaching.RECORDED[2:])])


class Recorder(teaching.Teacher):
    """A teacher that saves each passed step as an episode; a failed step spoils the rest of its run."""

    def __init__(self, world, dataset, longest, **options):
        super().__init__(world, **options)
        self.dataset, self.longest, self.goal, self.spoiled, self.count = dataset, longest, None, False, 0

    def frame(self, data, targets, label):
        if self.goal is not None:
            state, images = observe(self.world, data)
            self.dataset.add_frame({"observation.state": state, "action": np.concatenate([targets[arm] for arm in sites.ARMS]).astype(np.float32), GOAL: self.goal,
                                    **{f"observation.images.{view}": image for view, image in images.items()}, "task": PROMPT})
            self.count += 1
        super().frame(data, targets, label)

    def run_step(self, data, step, here):
        self.goal, self.count = goal_vector(self.layout, step, here), 0
        row = super().run_step(data, step, here)
        self.goal = None
        if row["result"] == "pass" and not self.spoiled:
            self.dataset.save_episode()
            self.longest[step["id"]] = max(self.longest.get(step["id"], 0), self.count)
        else:
            self.spoiled = True
            self.dataset.clear_episode_buffer()
        return row


def collect(seeds, names, out):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import omx_two_arm_world as world_mod
    joints = [f"{arm}.{joint}" for arm in sites.ARMS for joint in world_mod.JOINTS]
    vector = dict(dtype="float32", shape=(12,), names=joints)  # radians, unlike the real recordings' normalised units
    image = dict(dtype="video", shape=(*SHAPE, 3), names=["height", "width", "channels"])
    goal = dict(dtype="float32", shape=(12,), names=[f"goal{i}" for i in range(12)])
    layout = sites.Layout()
    world = world_mod.World(layout)
    dataset = LeRobotDataset.create("rosy/omx-two-arm", world_mod.FPS, root=out, robot_type="omx_follower_pair", features={
        "observation.state": vector, "action": vector, GOAL: goal, **{f"observation.images.{view}": image for view in teaching.RECORDED}})
    longest, spoiled = {}, []
    for seed in seeds:
        for name in names:
            teacher = Recorder(world, dataset, longest, seed=seed)
            teacher.run_task(tasks.get_task(layout, name))
            if teacher.spoiled:
                spoiled.append(f"{name}:{seed}")
            print("collected", name, seed, flush=True)
    dataset.finalize()
    (Path(out).parent / f"{Path(out).name}.steps.json").write_text(json.dumps(dict(longest=longest, spoiled=spoiled)), encoding="utf-8")
    return 0


class Driver:
    """Runs plan steps with the model in the teacher's place, under the teacher's judgement."""

    def __init__(self, model, steps_file):
        import omx_two_arm_world as world_mod
        import torch
        from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
        from lerobot.policies.factory import make_pre_post_processors
        self.torch = torch
        self.policy = ACTPolicy.from_pretrained(model, local_files_only=True).to("cuda" if torch.cuda.is_available() else "cpu").eval()
        config = self.policy.config  # temporal ensembling: one new chunk each frame, averaged; round 1 without it drove a link into the container
        config.temporal_ensemble_coeff, config.n_action_steps = .01, 1
        self.policy.temporal_ensembler = ACTTemporalEnsembler(.01, config.chunk_size)
        self.pre, self.post = make_pre_post_processors(self.policy.config, pretrained_path=str(model))
        self.device = next(self.policy.parameters()).device
        self.layout = sites.Layout()
        self.world = world_mod.World(self.layout)
        self.longest = json.loads(Path(steps_file).read_text(encoding="utf-8"))["longest"]

    def act(self, state, images, goal):
        torch, device = self.torch, self.device
        batch = {"observation.state": torch.from_numpy(state)[None].to(device), GOAL: torch.from_numpy(goal)[None].to(device), "task": [PROMPT],
                 **{f"observation.images.{view}": (torch.from_numpy(image).permute(2, 0, 1)[None].float() / 255).to(device) for view, image in images.items()}}
        return self.post(self.policy.select_action(self.pre(batch))).cpu().numpy()[0]

    def step(self, teacher, data, plan, here, sink=None):
        world, c, arm = self.world, plan["container"], plan["arm"]
        teacher.tilt = teacher.held_tilt = 0.
        teacher.contacts, teacher.carried, teacher.first = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), c, {}
        if plan["from"] == "belt":
            home = self.layout.sim_arms
            teacher.belt_in(data, plan, {o: home[o].home for o in self.layout.arms if o != arm})
        before = {o: world.pose(data, o) for o, _ in self.layout.containers() if o != c}
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

    def isolated(self, name, seed):
        """Each step from the plan's nominal state with the teacher's belt and start spread, so one failure does not hide the next step."""
        task = tasks.get_task(self.layout, name)
        here, rows = dict(task.get("start", {})), []
        with self.torch.inference_mode():
            for plan in task["steps"]:
                teacher = teaching.Teacher(self.world, seed=seed + len(rows))
                rows.append(dict(self.step(teacher, teacher.fresh(here), plan, here), task=name, seed=seed))
                print(json.dumps(rows[-1]), flush=True)
                here[plan["container"]] = plan["to"]
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
    driver = Driver(args.model, args.steps_file)
    rows, runs = [], []
    Path(args.artifacts).mkdir(parents=True, exist_ok=True)
    for name in args.tasks.split(","):
        for k in range(args.isolated_seeds):
            rows += driver.isolated(name, EVAL_SEED_BASE + 1000 * k)
        for k in range(args.whole_seeds):
            container = av.open(str(Path(args.artifacts) / f"{name}-seed{k}.mp4"), "w") if k == 0 else None
            sink = None
            if container:
                stream = container.add_stream("h264", rate=15)
                stream.width, stream.height, stream.pix_fmt = SHAPE[1] * 2, SHAPE[0] * 2, "yuv420p"
                sink = lambda image, s=stream, c=container: c.mux(s.encode(av.VideoFrame.from_ndarray(image, format="rgb24")))  # noqa: E731
            runs.append(driver.whole(name, EVAL_SEED_BASE + 500 + 1000 * k, sink))
            print(json.dumps(runs[-1]), flush=True)
            if container:
                container.mux(stream.encode(None))
                container.close()
    Path(args.out).write_text(json.dumps(dict(rows=rows, whole=runs), default=str), encoding="utf-8")
    return 0


def outcome(score):
    """A round that ran to the end has not passed: Rosy Learning shows this status, so only finished tasks earn it."""
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
    recipe = dict(ladder.RECIPE, steps=args.steps, optimizer_lr=args.lr, batch_size=args.batch_size)
    record = dict(schema=SCHEMA, round_id=round_id, created_at=now(), source_sha=ladder.source_sha(args), status="running", stage="collect", cameras=list(teaching.RECORDED),
                  tasks=names, seeds=args.seeds, recipe=recipe, claim="기하: 도달·순서·충돌(D-947). 실물 근거가 아닙니다.")
    write_record(run, record)
    me, environment = str(Path(__file__)), dict(os.environ, MUJOCO_GL="egl", PYTHONUNBUFFERED="1")
    log = (run / "round.log").open("w", encoding="utf-8")
    try:
        # One process per part: rendering four cameras is what takes the time, and LeRobot writes one dataset at a time.
        parts = [(run / f"part{k}", list(range(TRAIN_SEED_BASE + k, TRAIN_SEED_BASE + args.seeds, args.workers))) for k in range(min(args.workers, args.seeds))]
        running = [subprocess.Popen([args.python, me, "collect", "--seeds", ",".join(map(str, seeds)), "--tasks", args.tasks, "--out", str(part)],
                                    env=dict(environment, OMP_NUM_THREADS="1"), stdout=log, stderr=subprocess.STDOUT) for part, seeds in parts]
        if any(worker.wait() for worker in running):
            raise RuntimeError("collect")
        longest, spoiled = {}, []
        for part, _ in parts:
            found = json.loads((run / f"{part.name}.steps.json").read_text(encoding="utf-8"))
            spoiled += found["spoiled"]
            for key, value in found["longest"].items():
                longest[key] = max(longest.get(key, 0), value)
        (run / "steps.json").write_text(json.dumps(dict(longest=longest, spoiled=spoiled)), encoding="utf-8")
        subprocess.run([args.python, "-c", "import sys; from pathlib import Path; from lerobot.datasets.aggregate import aggregate_datasets as a; p=[Path(x) for x in sys.argv[2:]]; "
                        "a([f'rosy/part{i}' for i in range(len(p))], 'rosy/omx-two-arm', roots=p, aggr_root=Path(sys.argv[1]))", str(run / "dataset"), *[str(part) for part, _ in parts]],
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        info = json.loads((run / "dataset/meta/info.json").read_text(encoding="utf-8"))
        for part, _ in parts:
            shutil.rmtree(part)
        record.update(stage="train", data=dict(episodes=info["total_episodes"], frames=info["total_frames"], spoiled_runs=spoiled))
        write_record(run, record)
        subprocess.run([args.lerobot_train, f"--dataset.repo_id=rosy/omx-two-arm-{round_id}", f"--dataset.root={run / 'dataset'}", "--dataset.video_backend=pyav", "--policy.type=act", "--policy.device=cuda",
                        "--policy.push_to_hub=false", f"--policy.chunk_size={recipe['chunk_size']}", f"--policy.n_action_steps={recipe['n_action_steps']}", f"--policy.optimizer_lr={recipe['optimizer_lr']}",
                        f"--batch_size={recipe['batch_size']}", f"--steps={recipe['steps']}", f"--save_freq={max(1, recipe['steps'] // 3)}", "--log_freq=500", f"--num_workers={args.train_workers}", "--wandb.enable=false",
                        f"--output_dir={run / 'train'}", "--job_name=omx-two-arm"], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        record.update(stage="evaluate")
        write_record(run, record)
        subprocess.run([args.python, me, "evaluate", "--model", str(run / "train/checkpoints/last/pretrained_model"), "--steps-file", str(run / "steps.json"), "--tasks", args.tasks,
                        "--isolated-seeds", str(args.isolated_seeds), "--whole-seeds", str(args.whole_seeds), "--out", str(run / "eval.json"), "--artifacts", str(run / "artifacts")],
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        record.update(status="failed", reason=f"{record['stage']} 단계 실패({exc}). round.log를 보세요.", finished_at=now())
        write_record(run, record)
        return 1
    result = json.loads((run / "eval.json").read_text(encoding="utf-8"))
    score = summarise(result["rows"], result["whole"])
    record.update(outcome(score), stage="done", eval=score, finished_at=now(), artifacts=sorted(path.name for path in (run / "artifacts").glob("*.mp4")))
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
    for name in ("evaluate", "round"):
        one = commands.add_parser(name)
        one.add_argument("--tasks", default=",".join(TASKS))
        one.add_argument("--isolated-seeds", type=int, default=3)
        one.add_argument("--whole-seeds", type=int, default=3)
        if name == "evaluate":
            one.add_argument("--model", required=True)
            one.add_argument("--steps-file", required=True)
            one.add_argument("--out", required=True)
            one.add_argument("--artifacts", required=True)
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
    args = parser.parse_args(argv)
    if args.command == "collect":
        return collect([int(seed) for seed in args.seeds.split(",")], args.tasks.split(","), args.out)
    return evaluate(args) if args.command == "evaluate" else run_round(args)


if __name__ == "__main__":
    raise SystemExit(main())
