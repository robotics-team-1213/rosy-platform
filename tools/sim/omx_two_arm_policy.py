#!/usr/bin/env python3
"""One ACT model for both arms: the cell's four cameras and 12 joints in, 12 joint targets out.

The plan gives each arm's current step (from which site to which site) as a goal vector; the model sees only the cameras and the joints, so
where the container really lies comes from the images. Two modes: `steps` (one arm at a time, a LeRobot episode is one step) and `concurrent`
(both arms at once by omx_two_arm_plan.py's order and zones, an episode is one whole task, both arms' goals in every frame). Run on a lab PC,
in a LeRobot environment that can import mujoco:

    MUJOCO_GL=egl python tools/sim/omx_two_arm_policy.py round --root R --python P --lerobot-train T --seeds 30 --steps 60000 [--mode concurrent]
    MUJOCO_GL=egl python tools/sim/omx_two_arm_policy.py evaluate --model DIR --steps-file F --out F2 --artifacts DIR

`--skill grasp|release` learns only that part of each step (omx_two_arm_skill.py: the teacher's IK does the rest) under `--zero-error-deg`
joint-zero calibration error, `--servo-lag` and `--physics-ranges` (omx_physics, measured constants only), and the round also judges that IK alone on the same seeds (`eval-ik.json`).
`--policy smolvla --base-model B --vlm-assets V` fine-tunes SmolVLA offline instead of training ACT, with the step's arm and site as its
language input.

A round is `<root>/two_arm_rounds/<id>/round.json` (rosy.omx-two-arm-round.v1). MuJoCo answers geometry only (D-947); no learned policy reaches the real arm (D-793).
"""
import argparse
import functools
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402, F401
import omx_ladder as ladder  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "remote"))
import gpu_yield  # noqa: E402
from omx_two_arm_policy_helpers import (  # noqa: E402, F401
    EVAL_SEED_BASE,
    GOAL,
    GOAL_MODES,
    GOAL_SIZE,
    PROMPT,
    SHAPE,
    STEP_ERROR_SEED_BASE,
    TASKS,
    TRAIN_SEED_BASE,
    Driver,
    Recorder,
    collect,
    goal_block,
    goal_of,
    goal_vector,
    observe,
    plan_tasks,
    resolved_choices,
    sheet,
)
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_skill as skills  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402, F401
import omx_two_arm_teacher as teaching  # noqa: E402

SCHEMA = "rosy.omx-two-arm-round.v1"
TRAIN_POLL_S = 10  # how often train() looks for a new checkpoint
VRAM_MB = dict(act=4000, smolvla=9000)  # what training needs free on the GPU: SmolVLA at batch 8 took about 7.5 GB
pipeline_stages = skills.pipeline_stages


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
    driver = Driver(args.model, args.steps_file, sites.parse_choices(args.choice),
                    pick_vision=getattr(args, "pick_vision", False), belt_skew=getattr(args, "belt_skew", False),
                    cam_jitter=getattr(args, "cam_jitter", False),
                    ensemble_coeff=getattr(args, "ensemble_coeff", None), n_action_steps=getattr(args, "n_action_steps", None),
                    flow_steps=getattr(args, "flow_steps", None), use_amp=True if getattr(args, "amp", False) else None)
    rows, runs = [], []
    Path(args.artifacts).mkdir(parents=True, exist_ok=True)
    planned = plan_tasks(args.plan_dir, args.tasks.split(",")) if args.plan_dir else None
    if args.skill:
        comp_kw = dict(compensate_zero=True) if getattr(args, "compensate_zero", False) else {}
        for name in args.tasks.split(","):
            for k in range(args.isolated_seeds):
                rows += skills.isolated(driver, name, EVAL_SEED_BASE + 1000 * k, args.skill, args.zero_error_deg, args.servo_lag,
                                        args.physics_ranges, **comp_kw)
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


def checkpoint_step(out):
    last = out / "checkpoints" / "last"
    return int(last.resolve().name) if last.is_symlink() else None


def train(command, out, lerobot_train, log, env, vram_mb=0, early_stop_fn=None):
    """lerobot-train that steps aside at a checkpoint while an alone test waits, then resumes from it. The total stays the
    round's steps, so the learning-rate schedule is the one an uninterrupted run has. Older checkpoints go: eval reads last."""
    while True:
        gpu_yield.wait_vram(vram_mb, say=functools.partial(print, file=log))
        trainer, seen, stopped, solved = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True), checkpoint_step(out), False, None
        try:
            while trainer.poll() is None:
                time.sleep(TRAIN_POLL_S)
                step = checkpoint_step(out)
                if step is None or step == seen:  # LeRobot unlinks last before it links the new step
                    continue
                seen = step
                for old in (out / "checkpoints").iterdir():
                    if old.name.isdigit() and int(old.name) < step:  # never one still being written
                        shutil.rmtree(old)
                if early_stop_fn is not None and early_stop_fn(step, out / "checkpoints/last/pretrained_model"):
                    stop(trainer)
                    solved = step
                elif gpu_yield.alone_waiting():
                    stop(trainer)
                    stopped = True
        finally:  # the trainer has its own session: a round that dies must not leave it on the GPU without a lock
            if trainer.poll() is None:
                stop(trainer)
        if solved is not None:
            return solved
        if not stopped:
            if trainer.returncode:
                raise subprocess.CalledProcessError(trainer.returncode, command)
            return None
        last = checkpoint_step(out) or 0
        for partial in (out / "checkpoints").iterdir():  # a save cut short past last would be written over by the resumed run
            if partial.name.isdigit() and int(partial.name) > last:
                shutil.rmtree(partial)
        gpu_yield.yield_turn(say=functools.partial(print, file=log))
        command = [lerobot_train, f"--config_path={out / 'checkpoints/last/pretrained_model/train_config.json'}", "--resume=true"]


def stop(trainer):
    """SIGTERM the trainer's session (it and its data workers), SIGKILL after 2 min; it may have ended on its own meanwhile."""
    try:
        os.killpg(trainer.pid, signal.SIGTERM)
        trainer.wait(timeout=120)
    except subprocess.TimeoutExpired:
        os.killpg(trainer.pid, signal.SIGKILL)
        trainer.wait()
    except ProcessLookupError:
        trainer.wait()


def run_round(args):
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # so train() takes its trainer down with the round
    ladder.require_gpu(args.python)
    round_id = ladder.new_round_id()
    run = Path(args.root) / "two_arm_rounds" / round_id
    run.mkdir(parents=True)
    names = args.tasks.split(",")
    if args.skill and args.mode != "steps" or args.policy == "smolvla" and not (args.base_model and args.vlm_assets):
        raise SystemExit("a sub-skill needs --mode steps; SmolVLA needs --base-model and --vlm-assets (local, offline)")
    parsed_choices = resolved_choices(sites.parse_choices(args.choice), pick_vision=getattr(args, "pick_vision", False),
                                      belt_skew=getattr(args, "belt_skew", False), cam_jitter=getattr(args, "cam_jitter", False))
    recipe = dict(ladder.RECIPE, steps=args.steps, optimizer_lr=args.lr, batch_size=args.batch_size, mode=args.mode, policy=args.policy,
                  skill=args.skill, zero_error_deg=args.zero_error_deg, servo_lag=args.servo_lag, physics_ranges=args.physics_ranges,
                  pick_vision=bool(getattr(args, "pick_vision", False)), belt_skew=bool(getattr(args, "belt_skew", False)),
                  cam_jitter=bool(getattr(args, "cam_jitter", False)), compensate_zero=bool(getattr(args, "compensate_zero", False)),
                  no_goal=bool(getattr(args, "no_goal", False)), goal=getattr(args, "goal", "joints"),
                  dagger_model=getattr(args, "dagger_model", None), dagger_only=bool(getattr(args, "dagger_only", False)),
                  extra_datasets=list(getattr(args, "extra_dataset", None) or []))
    record = dict(schema=SCHEMA, round_id=round_id, created_at=now(), source_sha=ladder.source_sha(args), status="running", stage="collect", cameras=list(teaching.RECORDED),
                  tasks=names, seeds=args.seeds, recipe=recipe, choices=parsed_choices, claim="기하: 도달·순서·충돌(D-947). 실물 근거가 아닙니다.")
    write_record(run, record)
    me, environment = str(Path(__file__)), dict(os.environ, MUJOCO_GL="egl", PYTHONUNBUFFERED="1")
    log = (run / "round.log").open("w", encoding="utf-8")
    chosen = [arg for item in args.choice or [] for arg in ("--choice", item)]
    skilled = [*skills.argv(args), *(["--pick-vision"] if getattr(args, "pick_vision", False) else []),
               *(["--belt-skew"] if getattr(args, "belt_skew", False) else [])]
    no_goal = ["--no-goal"] if getattr(args, "no_goal", False) else ["--goal", getattr(args, "goal", "joints")]
    eval_accel = [*(["--n-action-steps", str(args.n_action_steps)] if getattr(args, "n_action_steps", None) is not None else []),
                  *(["--flow-steps", str(args.flow_steps)] if getattr(args, "flow_steps", None) is not None else []),
                  *(["--amp"] if getattr(args, "amp", False) else [])]
    dagger = [*(["--dagger-model", args.dagger_model, "--dagger-prefix-frames", str(args.dagger_prefix_frames)] if getattr(args, "dagger_model", None) else []),
              *(["--steps-file", args.steps_file] if getattr(args, "steps_file", None) else []),
              *(["--dagger-only"] if getattr(args, "dagger_only", False) else []),
              *(["--dagger-device", args.dagger_device] if getattr(args, "dagger_device", None) else []),
              *(["--dagger-steps", args.dagger_steps] if getattr(args, "dagger_steps", None) else []),
              *(["--dagger-eval-file", args.dagger_eval_file] if getattr(args, "dagger_eval_file", None) else []),
              *(eval_accel if getattr(args, "dagger_model", None) else [])]
    try:
        plan = []
        if args.mode == "concurrent":
            scenario = "all" if "rearrange" in args.tasks.split(",") else "both"
            subprocess.run([args.python, str(Path(__file__).with_name("omx_two_arm_plan.py")), "compare", "--scenario", scenario, "--out", str(run / "plan.json"), "--replay-dir", str(run / "plan"), *chosen],
                           env=dict(environment, PYTHONIOENCODING="utf-8"), stdout=log, stderr=subprocess.STDOUT, check=True)
            plan = ["--plan-dir", str(run / "plan")]
        parts = [(run / f"part{k}", list(range(TRAIN_SEED_BASE + k, TRAIN_SEED_BASE + args.seeds, args.workers))) for k in range(min(args.workers, args.seeds))]
        running = [subprocess.Popen([args.python, me, "collect", "--seeds", ",".join(map(str, seeds)), "--tasks", args.tasks, "--out", str(part), *plan, *chosen, *skilled, *no_goal, *dagger],
                                    env=dict(environment, OMP_NUM_THREADS="1"), stdout=log, stderr=subprocess.STDOUT) for part, seeds in parts]
        if any(worker.wait() for worker in running):
            raise RuntimeError("collect")
        longest, spoiled, dagger_totals, part_roots, goal_meta = {}, [], {}, [], {}
        for part, _ in parts:
            found = json.loads((run / f"{part.name}.steps.json").read_text(encoding="utf-8"))
            spoiled += found["spoiled"]
            goal_meta.update({k: found[k] for k in ("goal_mode", "goal_sites") if k in found})
            for k, v in (found.get("dagger") or {}).items():
                dagger_totals[k] = dagger_totals.get(k, 0) + v
            if found.get("episodes", 1) != 0:
                part_roots.append(part)
            for key, value in found["longest"].items():
                longest[key] = {k: max(v, longest.get(key, {}).get(k, 0)) for k, v in value.items()} if isinstance(value, dict) else max(longest.get(key, 0), value)
        (run / "steps.json").write_text(json.dumps(dict(longest=longest, spoiled=spoiled, **goal_meta, **({"dagger": dagger_totals} if dagger_totals else {}))), encoding="utf-8")
        roots = part_roots + [Path(p) for p in (getattr(args, "extra_dataset", None) or [])]
        if getattr(args, "early_stop", True) and getattr(args, "dagger_only", False) and getattr(args, "dagger_model", None) and not roots and dagger_totals.get("recovered", 0) == 0 and dagger_totals.get("recovery_failed", 0) == 0 and dagger_totals.get("passed_skip", 0) > 0:
            for part, _ in parts:
                shutil.rmtree(part, ignore_errors=True)
            ckpt0 = run / "train/checkpoints/000000/pretrained_model"
            ckpt0.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(args.dagger_model, ckpt0)
            (run / "train/checkpoints/last").symlink_to("000000")
            record.update(stage="evaluate", data=dict(episodes=0, frames=0, spoiled_runs=spoiled, dagger=dagger_totals, early_stopped_at_step=0))
            write_record(run, record)
        else:
            if not roots:
                raise RuntimeError("collect produced 0 episodes")
            subprocess.run([args.python, "-c", "import sys; from pathlib import Path; from lerobot.datasets.aggregate import aggregate_datasets as a; p=[Path(x) for x in sys.argv[2:]]; "
                            "a([f'rosy/part{i}' for i in range(len(p))], 'rosy/omx-two-arm', roots=p, aggr_root=Path(sys.argv[1]))", str(run / "dataset"), *map(str, roots)],
                           env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
            info = json.loads((run / "dataset/meta/info.json").read_text(encoding="utf-8"))
            for part, _ in parts:
                shutil.rmtree(part, ignore_errors=True)
            gpu_yield.yield_turn(say=functools.partial(print, file=log))
            record.update(stage="train", data=dict(episodes=info["total_episodes"], frames=info["total_frames"], spoiled_runs=spoiled, **({"dagger": dagger_totals} if dagger_totals else {})))
            write_record(run, record)
            common = [f"--batch_size={recipe['batch_size']}", f"--steps={recipe['steps']}", f"--save_freq={max(500, recipe['steps'] // 20)}", "--log_freq=500",
                      f"--num_workers={args.train_workers}", "--wandb.enable=false", f"--output_dir={run / 'train'}",
                      "--tolerance_s=0.001"]
            dataset = [f"--dataset.repo_id=rosy/omx-two-arm-{round_id}", f"--dataset.root={run / 'dataset'}", "--dataset.video_backend=pyav"]
            if args.policy == "smolvla":
                sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "learning/training/omx"))
                import smolvla_training
                prepared = smolvla_training.prepare(args.base_model, args.vlm_assets, run / "inputs", device="cuda")
                (run / "train-config.json").write_text(json.dumps(dict(policy=dict(prepared["policy"], optimizer_lr=args.lr), job_name="omx-two-arm-smolvla")), encoding="utf-8")
                command = [args.lerobot_train, f"--config_path={run / 'train-config.json'}", *dataset, *common]
                environment.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1")
            else:
                pretrained = [f"--policy.pretrained_path={args.base_model}"] if args.base_model else []
                command = [args.lerobot_train, *dataset, "--policy.type=act", "--policy.device=cuda", "--policy.push_to_hub=false", f"--policy.chunk_size={recipe['chunk_size']}",
                           f"--policy.n_action_steps={recipe['n_action_steps']}", f"--policy.optimizer_lr={recipe['optimizer_lr']}", "--job_name=omx-two-arm", *pretrained, *common]

            def _probe_early_stop(step, ckpt_dir):
                if step < getattr(args, "early_stop_min_steps", 0) or not ckpt_dir.is_dir():
                    return False
                probe_ckpt = run / "train/early_stop_ckpt"
                shutil.rmtree(probe_ckpt, ignore_errors=True)
                shutil.copytree(ckpt_dir, probe_ckpt)
                probe_out = run / f"eval-step-{step:06d}.json"
                n_seeds = max(1, int(getattr(args, "early_stop_seeds", 1)))
                extra_probe = ["--compensate-zero"] if (args.zero_error_deg > 0 and not getattr(args, "compensate_zero", False)) else []
                probe_env = dict(environment, **({"CUDA_VISIBLE_DEVICES": ""} if args.policy == "act" else {}))
                rc = subprocess.run([args.python, me, "evaluate", "--model", str(probe_ckpt), "--steps-file", str(run / "steps.json"),
                                     "--tasks", args.tasks, "--isolated-seeds", str(n_seeds), "--whole-seeds", str(n_seeds),
                                     "--out", str(probe_out), "--artifacts", str(run / "artifacts"),
                                     *plan, *chosen, *skilled, *eval_accel, *extra_probe],
                                    env=probe_env, stdout=log, stderr=subprocess.STDOUT).returncode
                if rc != 0 or not probe_out.is_file():
                    return False
                probe_res = json.loads(probe_out.read_text(encoding="utf-8"))
                probe_score = summarise(probe_res["rows"], probe_res["whole"])
                solved = outcome(probe_score, args.skill)["status"] == "passed"
                print(f"[early-stop] step={step} passed={probe_score['passed']}/{probe_score['n']} solved={solved}", file=log, flush=True)
                return solved

            log.flush()
            early_step = train(command, run / "train", args.lerobot_train, log, environment, vram_mb=VRAM_MB[args.policy],
                               early_stop_fn=_probe_early_stop if getattr(args, "early_stop", True) else None)
            if early_step is not None:
                record["data"]["early_stopped_at_step"] = early_step
            record.update(stage="evaluate")
            write_record(run, record)
        ckpt_last = str(run / "train/checkpoints/last/pretrained_model")
        judged = [("eval.json", ckpt_last, [])]
        if args.zero_error_deg > 0 and not getattr(args, "compensate_zero", False):
            judged.append(("eval-comp.json", ckpt_last, ["--compensate-zero"]))
        if args.skill:
            judged.append(("eval-ik.json", "ik", []))
        for out, model, extra_eval in judged:
            gpu_yield.yield_turn(say=functools.partial(print, file=log))
            subprocess.run([args.python, me, "evaluate", "--model", model, "--steps-file", str(run / "steps.json"), "--tasks", args.tasks,
                            "--isolated-seeds", str(args.isolated_seeds), "--whole-seeds", str(args.whole_seeds), "--out", str(run / out), "--artifacts", str(run / "artifacts"),
                            *plan, *chosen, *skilled, *eval_accel, *extra_eval], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        record.update(status="failed", reason=f"{record['stage']} 단계 실패({exc}). round.log를 보세요.", finished_at=now())
        write_record(run, record)
        return 1
    result = json.loads((run / "eval.json").read_text(encoding="utf-8"))
    score = summarise(result["rows"], result["whole"])
    if (run / "eval-comp.json").is_file():
        comp = json.loads((run / "eval-comp.json").read_text(encoding="utf-8"))
        record.update(eval_comp=summarise(comp["rows"], comp["whole"]))
    if args.skill:
        baseline = json.loads((run / "eval-ik.json").read_text(encoding="utf-8"))
        record.update(eval_ik=summarise(baseline["rows"], []))
    stages = pipeline_stages(score, sites.Layout(**(parsed_choices or {})), result["rows"],
                             pick_vision=getattr(args, "pick_vision", False), belt_skew=getattr(args, "belt_skew", False),
                             gazebo_report=getattr(args, "gazebo_report", None), isaac_report=getattr(args, "isaac_report", None), skill=args.skill)
    handoff_file, suite_file = run / "isaac-handoff.json", run / "isaac-suite.json"
    handoff_file.write_text(json.dumps(stages["isaac"]["handoff"], ensure_ascii=False, indent=2), encoding="utf-8")
    cell_cases = Path(__file__).resolve().parents[2] / "deploy/robot/omx/cell_cases.py"
    if cell_cases.is_file():
        subprocess.run([args.python, str(cell_cases), "--mujoco-handoff", str(handoff_file), "--out", str(suite_file)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record.update(outcome(score, args.skill), stage="done", eval=score, stages=stages, isaac_handoff=handoff_file.name,
                  isaac_suite=suite_file.name if suite_file.exists() else None,
                  finished_at=now(), artifacts=sorted(path.name for path in (run / "artifacts").glob("*.mp4")))
    write_record(run, record)
    print(json.dumps(dict(round_id=round_id, eval=record["eval"]), ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    accel_opts = (("--n-action-steps", dict(type=int)), ("--flow-steps", dict(type=int)), ("--amp", dict(action="store_true")))
    dagger_opts = (("--dagger-model", dict(help="checkpoint to roll out and harvest Teacher recoveries from failures")),
                   ("--steps-file", dict(help="steps.json matching --dagger-model (auto-found in ancestors if omitted)")),
                   ("--dagger-prefix-frames", dict(default="auto")), ("--dagger-only", dict(action="store_true")),
                   ("--dagger-device", dict(choices=("cpu", "cuda"))), ("--dagger-steps", dict(help="comma-separated step IDs to target")),
                   ("--dagger-eval-file", dict(help="eval.json (or 'auto') to restrict DAgger to failed steps")))
    one = commands.add_parser("collect")
    for flag, kw in (("--seeds", dict(required=True)), ("--tasks", dict(default=",".join(TASKS))), ("--out", dict(required=True)),
                     ("--plan-dir", dict(help="two-arm plans")), ("--choice", dict(action="append")), ("--no-goal", dict(action="store_true")),
                     ("--goal", dict(default="joints", choices=GOAL_MODES)),
                     *accel_opts, *dagger_opts):
        one.add_argument(flag, **kw)
    skills.options(one)
    for name in ("evaluate", "round"):
        one = commands.add_parser(name)
        for flag, kw in (("--tasks", dict(default=",".join(TASKS))), ("--isolated-seeds", dict(type=int, default=3)),
                         ("--whole-seeds", dict(type=int, default=3)), ("--choice", dict(action="append")), *accel_opts):
            one.add_argument(flag, **kw)
        skills.options(one)
        if name == "evaluate":
            for flag, kw in (("--model", dict(required=True)), ("--steps-file", dict(required=True)), ("--out", dict(required=True)),
                             ("--artifacts", dict(required=True)), ("--plan-dir", dict(help="judge whole tasks")),
                             ("--ensemble-coeff", dict(type=float))):
                one.add_argument(flag, **kw)
        else:
            one.add_argument("--no-goal", action="store_true")
            one.add_argument("--goal", default="joints", choices=GOAL_MODES,
                             help="site: one-hot source and target site (what an admitted job names), not the IK joints")
            one.add_argument("--extra-dataset", action="append")
            one.add_argument("--early-stop", action=argparse.BooleanOptionalAction, default=True)
            one.add_argument("--early-stop-min-steps", type=int, default=0)
            one.add_argument("--early-stop-seeds", type=int, default=1)
            for flag, kw in dagger_opts:
                one.add_argument(flag, **kw)
    for flag, kw in (("--root", dict(required=True)), ("--python", dict(default=sys.executable)), ("--lerobot-train", dict(required=True)),
                     ("--source-sha", dict()), ("--seeds", dict(type=int, default=30)), ("--workers", dict(type=int, default=6)),
                     ("--train-workers", dict(type=int, default=8)), ("--steps", dict(type=int, default=60000)),
                     ("--lr", dict(type=float, default=1e-4)), ("--batch-size", dict(type=int, default=8)),
                     ("--mode", dict(default="steps", choices=["steps", "concurrent"])), ("--policy", dict(default="act", choices=["act", "smolvla"])),
                     ("--base-model", dict()), ("--vlm-assets", dict()), ("--gazebo-report", dict()), ("--isaac-report", dict())):
        one.add_argument(flag, **kw)
    args = parser.parse_args(argv)
    if args.command == "collect":
        return collect([int(seed) for seed in args.seeds.split(",")], args.tasks.split(","), args.out, args.plan_dir, sites.parse_choices(args.choice),
                       args.skill, args.zero_error_deg, args.servo_lag, args.physics_ranges,
                       pick_vision=args.pick_vision, belt_skew=args.belt_skew, cam_jitter=args.cam_jitter,
                       compensate_zero=args.compensate_zero, no_goal=args.no_goal, goal_mode=args.goal,
                       dagger_model=args.dagger_model, steps_file=args.steps_file, dagger_prefix_frames=args.dagger_prefix_frames,
                       dagger_only=args.dagger_only, dagger_device=args.dagger_device, dagger_steps=args.dagger_steps,
                       dagger_eval_file=args.dagger_eval_file,
                       n_action_steps=args.n_action_steps, flow_steps=args.flow_steps, use_amp=True if args.amp else None)
    return evaluate(args) if args.command == "evaluate" else run_round(args)


if __name__ == "__main__":
    raise SystemExit(main())
