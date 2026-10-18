"""OMX SIM reach imitation loop on the sim host: teacher -> batch export -> ACT -> closed loop -> eval.

Run on the reserved Linux sim host next to a running Pilot container (compose.pilot-sim.yaml), never
on the laptop. Every stage is an existing script invoked by path; this driver only chains them and
stops at the first failing stage. ``--dry-run`` prints the commands.

  1 teacher     deploy/robot/omx/sim_reach_teacher.py --task T --episodes N --out RUN/teacher-results.json
  2 copy        docker cp CONTAINER:/recordings RUN/recordings   (skipped with --recordings DIR)
  3 export      learning/curation/omx/sim_batch_export.py ... --out RUN/batch   (LeRobot interpreter)
  4 train       learning/training/omx/act_job.py <batch act_job_args> --out RUN/act --steps S (CPU)
  - restart     docker restart CONTAINER: a new one-time pairing code for the closed loop
  5 closed_loop learning/evaluation/omx/sim_closed_loop.py   (other owner; skipped when missing)
  6 eval        learning/evaluation/omx/sim_reach_eval.py    (other owner; skipped when missing)

The closed loop uses held-out episode indices from N on (seed = task seed + index). Rounded
start poses can repeat across seeds; this does not prove pose generalization. RUN must be new.

python3 tools/sim/run_sim_reach_pipeline.py --task deploy/robot/omx/sim/reach_task.example.json \\
    --episodes 12 --run /srv/rosy-sim-il/run-01 --lerobot-python /opt/lerobot/bin/python [--steps 400]
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEACHER = ROOT / "deploy/robot/omx/sim_reach_teacher.py"
BATCH = ROOT / "learning/curation/omx/sim_batch_export.py"
ACT_JOB = ROOT / "learning/training/omx/act_job.py"
CLOSED_LOOP = ROOT / "learning/evaluation/omx/sim_closed_loop.py"
EVALUATOR = ROOT / "learning/evaluation/omx/sim_reach_eval.py"
STAGES = ("teacher", "copy", "export", "train", "restart", "closed_loop", "eval")
OPTIONAL = {"closed_loop": CLOSED_LOOP, "eval": EVALUATOR}


def commands(args, act_job_args: list[str] | None = None) -> list[tuple[str, list[str]]]:
    run, py, lerobot = Path(args.run), args.python, args.lerobot_python
    target = ["--inside"] if args.inside else [args.container]
    recordings = Path(args.recordings) if args.recordings else (
        Path("/recordings") if args.inside else run / "recordings")
    results = run / "teacher-results.json"
    planned = [
        ("teacher", [py, str(TEACHER), *target, "--task", str(args.task), "--episodes", str(args.episodes),
                     "--out", str(results)]),
        ("copy", [] if args.recordings or args.inside else
                 ["docker", "cp", f"{args.container}:/recordings", str(recordings)]),
        ("export", [lerobot, str(BATCH), "--results", str(results), "--recordings", str(recordings),
                    "--out", str(run / "batch"), "--eval-count", "1", "--python", lerobot]),
        ("train", [lerobot, str(ACT_JOB), *(act_job_args or ["<act_job_args from RUN/batch/batch-manifest.json>"]),
                   "--out", str(run / "act"), "--steps", str(args.steps)]),
        # The pairing code is one-time per server start: the closed loop pairs with a restarted server.
        ("restart", [] if args.inside else ["docker", "restart", args.container]),
        # shortcut: seeds can share rounded poses; verify pose separation before claiming generalization.
        ("closed_loop", [lerobot, str(CLOSED_LOOP), *target, "--task", str(args.task), "--policy", str(run / "act"),
                         "--first-index", str(args.episodes), "--episodes", str(args.eval_episodes),
                         "--out", str(run / "closed-loop.json")]),
        ("eval", [py, str(EVALUATOR), "--task", str(args.task), "--teacher-results", str(results),
                  "--closed-loop", str(run / "closed-loop.json"), "--out", str(run / "eval.json")]),
    ]
    first = STAGES.index(args.from_stage)
    return [(stage, argv) for stage, argv in planned if STAGES.index(stage) >= first]


def act_job_args(run: Path) -> list[str]:
    manifest = json.loads((run / "batch" / "batch-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "ready" or not manifest.get("act_job_args"):
        raise SystemExit(f"batch export not ready: {len(manifest.get('train', []))} train, "
                         f"{len(manifest.get('eval', []))} eval; see {run / 'batch' / 'batch-manifest.json'}")
    return manifest["act_job_args"]


def main(argv: list[str] | None = None, *, runner=subprocess.run, log=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--episodes", type=int, required=True, help="teacher episodes (indices 0..N-1)")
    parser.add_argument("--run", type=Path, required=True, help="new run directory")
    parser.add_argument("--container", default="rosy-omx-pilot-sim")
    parser.add_argument("--inside", action="store_true", help="already inside the Pilot container")
    parser.add_argument("--recordings", type=Path, help="recordings already copied out (skips docker cp)")
    parser.add_argument("--python", default=sys.executable, help="interpreter for teacher/evaluator (stdlib)")
    parser.add_argument("--lerobot-python", default=sys.executable, help="interpreter with lerobot==0.4.4")
    parser.add_argument("--steps", type=int, default=40, help="act_job.py --steps (device stays cpu)")
    parser.add_argument("--eval-episodes", type=int, default=10, help="closed-loop held-out episodes")
    parser.add_argument("--from-stage", choices=STAGES, default="teacher", help="resume an existing RUN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.from_stage == "teacher" and args.run.exists() and not args.dry_run:
        parser.error("--run must be a new directory (use --from-stage to resume)")
    if not args.dry_run:
        args.run.mkdir(parents=True, exist_ok=True)
    planned = commands(args)
    for index, (stage, _) in enumerate(planned):
        if stage == "train" and not args.dry_run:
            planned[index] = next(item for item in commands(args, act_job_args(args.run)) if item[0] == "train")
        stage, command = planned[index]
        if not command:
            log(f"[{stage}] skipped (recordings given or running inside the container)")
            continue
        if stage == "restart" and not CLOSED_LOOP.is_file():
            log(f"[{stage}] skipped: no closed-loop runner to pair with")
            continue
        if stage in OPTIONAL and not OPTIONAL[stage].is_file():
            log(f"[{stage}] skipped: {OPTIONAL[stage].relative_to(ROOT).as_posix()} is not in this checkout "
                f"(closed-loop runner/evaluator not landed yet)")
            continue
        log(f"[{stage}] {shlex.join(command)}")
        if args.dry_run:
            continue
        done = runner(command, cwd=ROOT)
        if done.returncode != 0:
            log(f"[{stage}] failed with exit {done.returncode}; later stages not run")
            return done.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
