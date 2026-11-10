#!/usr/bin/env python3
"""OMX learning ladder: one round of teacher data, ACT training and held-out evaluation, recorded for Rosy Learning.

A round is `<root>/rounds/<round_id>/round.json` (rosy.omx-ladder-round.v1). MuJoCo answers geometry only, Gazebo the
ROS execution contract, Isaac contact and vision (D-947). A person replaces the best round in Rosy Learning; this tool
never does, and a replacement is a recorded comparison, not an approval or a promotion (D-793, D-857).

    python3 tools/sim/omx_ladder.py round --root R --cell cell.json --python P --lerobot-train T [--parent ID]
    python3 tools/sim/omx_ladder.py two-arm --root R --python P --task stack|rehandle [--seed N]
    python3 tools/sim/omx_ladder.py two-arm-compare --root R --python P [--seed N]
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "rosy.omx-ladder-round.v1"
TWO_ARM_SCHEMA = "rosy.omx-two-arm-run.v1"
TWO_ARM_COMPARE_SCHEMA = "rosy.omx-two-arm-compare.v1"
COMPARE_RUNS = (("one-arm-A", "one-arm A", False), ("one-arm-B", "one-arm B", False), ("two-arm", "two-arm", True))  # tag, planner mode, both arms at once
ROUND_ID = re.compile(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{8}")
STATUSES = {"pending", "running", "passed", "failed", "blocked", "not_run"}
# A fifth of the 36 mm stud pitch and a yaw that still seats between studs; 20 mm passed boxes lying across a stud row.
STRICT_XY_MM, STRICT_YAW_DEG, STRICT_Z_MM, STRICT_TILT_DEG = 8.0, 8.0, 5.0, 5.0
LOOSE_XY_MM = 20.0
RECIPE = dict(policy="act", steps=20000, batch_size=8, chunk_size=30, n_action_steps=8, optimizer_lr=1e-5)
TRAIN_SEED_BASE = 1000
EVAL_SEED_STRIDE = 1000  # every round evaluates seeds no earlier round used


def judge(xy_err_mm: float, yaw_err_deg: float, z_err_mm: float, tilt_deg: float, peak_lift_m: float) -> dict:
    """Whether one episode placed the box. Strict is what a round is compared by; loose is the first report's rule."""
    return dict(lifted=bool(peak_lift_m > .03), loose=bool(xy_err_mm <= LOOSE_XY_MM and abs(z_err_mm) <= 25.0),
                strict=bool(xy_err_mm <= STRICT_XY_MM and yaw_err_deg <= STRICT_YAW_DEG and abs(z_err_mm) <= STRICT_Z_MM
                            and tilt_deg <= STRICT_TILT_DEG),
                xy_err_mm=round(float(xy_err_mm), 1), yaw_err_deg=round(float(yaw_err_deg), 1),
                z_err_mm=round(float(z_err_mm), 1), tilt_deg=round(float(tilt_deg), 1))


def wilson_low(successes: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the 95 % Wilson interval: 19 of 20 and 190 of 200 are not the same evidence."""
    if n == 0:
        return 0.0
    p = successes / n
    return round((p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n), 3)


def wilson_high(successes: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 1.0
    p = successes / n
    return round((p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n), 3)


def summarise(rows: list[dict], seed_base: int) -> dict:
    n = len(rows)
    strict = sum(row["strict"] for row in rows)
    placed = [row for row in rows if row["loose"]]
    return dict(n=n, seed_base=seed_base, lifted=sum(row["lifted"] for row in rows),
                loose=dict(placed=len(placed)), strict=dict(placed=strict, wilson_low=wilson_low(strict, n), wilson_high=wilson_high(strict, n)),
                xy_err_mm_median=round(statistics.median(row["xy_err_mm"] for row in placed), 1) if placed else None,
                yaw_err_deg_median=round(statistics.median(row["yaw_err_deg"] for row in placed), 1) if placed else None,
                failed_seeds=[row["seed"] for row in rows if not row["strict"]])


def compare(candidate: dict, best: dict | None) -> str:
    """'better', 'worse' or 'unclear': only intervals that do not overlap decide."""
    if best is None:
        return "better"
    a, b = candidate["strict"], best["strict"]
    if a["wilson_low"] > b["wilson_high"]:
        return "better"
    if b["wilson_low"] > a["wilson_high"]:
        return "worse"
    return "unclear"


def new_round_id(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def write_round(root: Path, row: dict) -> Path:
    if row.get("schema") != SCHEMA or not ROUND_ID.fullmatch(row["round_id"]):
        raise ValueError("rosy.omx-ladder-round.v1 with a valid round_id required")
    for name, stage in row["stages"].items():
        if stage["status"] not in STATUSES:
            raise ValueError(f"{name}: unknown status")
        if stage["status"] in {"blocked", "not_run"} and not stage.get("reason"):
            raise ValueError(f"{name}: {stage['status']} needs a reason")
    path = root / "rounds" / row["round_id"] / "round.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)
    return path


def read_round(root: Path, round_id: str) -> dict:
    if not ROUND_ID.fullmatch(round_id):
        raise ValueError("round id")
    return json.loads((root / "rounds" / round_id / "round.json").read_text(encoding="utf-8"))


def best_round(root: Path) -> str | None:
    """The newest 'replace' decision. decisions.jsonl is the record; best.json is only a copy of this."""
    path = root / "decisions.jsonl"
    if not path.exists():
        return None
    chosen = None
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["verdict"] == "replace":
            chosen = row["round_id"]
    return chosen


def eval_seed_base(root: Path) -> int:
    """Past every seed any recorded round evaluated, so selection cannot overfit a fixed set."""
    used = [100000]
    for path in (root / "rounds").glob("*/round.json"):
        run = json.loads(path.read_text(encoding="utf-8"))["stages"]["mujoco"].get("eval") or {}
        if run:
            used.append(run["seed_base"] + EVAL_SEED_STRIDE)
    return max(used)


def new_round(root: Path, parent: str | None, cell: dict, source_sha: str, recipe: dict, from_failures: int, episodes: int) -> dict:
    return dict(schema=SCHEMA, round_id=new_round_id(), created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                parent_round_id=parent, source_sha=source_sha, scene=cell["scene"], recipe=recipe,
                data=dict(episodes=episodes, from_failures=from_failures),
                stages=dict(mujoco=dict(stage_order=1, track="learning_and_physics", status="pending", claim="기하: 도달·순서·충돌", eval=None, artifacts=[], reason=None),
                            isaac=dict(stage_order=2, track="learning_and_physics", status="not_run", claim="접촉·영상", scenario="arm-s-cell-case", run_id=None, result=None, artifacts=[],
                                       reason="Stage 1(MuJoCo) 뒤 Stage 2(Isaac 접촉·안착 스위트, cell_case_suite.py)를 아직 실행하지 않았습니다."),
                            gazebo=dict(stage_order=None, track="ros2_execution_contract", status="not_run", claim="ROS 실행 계약", contract=None, artifacts=[],
                                        reason="별도 ROS 2 실행 계약 점검(omx_backend_conformance.py)을 이 라운드에서 실행하지 않았습니다.")))


def judge_gazebo_contract(samples_or_report: dict | Path, *, shape: tuple[int, int] = (240, 320), camera_hz: float = 5.0) -> dict:
    """Judge Gazebo's D-866 §2 ROS 2 execution contract from raw conformance samples or a saved conformance report."""
    data = json.loads(Path(samples_or_report).read_text(encoding="utf-8")) if isinstance(samples_or_report, (str, Path)) else dict(samples_or_report)
    if "failures" in data:
        failures = list(data["failures"])
        shape = tuple(data.get("shape") or shape)
        camera_hz = float(data.get("camera_hz") or camera_hz)
    else:
        import omx_backend_conformance as conformance
        failures = conformance.check(data, shape=shape, camera_hz=camera_hz)
    return dict(status="passed" if not failures else "failed", claim="ROS 실행 계약",
                contract=dict(shape=list(shape), camera_hz=camera_hz, failures=failures,
                              stop=data.get("stop"), object_drift_mm=data.get("object_drift_mm")),
                artifacts=[], reason=None if not failures else "; ".join(failures))


def judge_isaac_stage(suite_or_report: dict | Path, *, scenario: str = "arm-s-cell-case") -> dict:
    """Judge or stage Isaac Sim's D-872 / D-947 contact & vision confirmation from a suite report, single report, 3-tier container stack report, or MuJoCo handoff."""
    data = json.loads(Path(suite_or_report).read_text(encoding="utf-8")) if isinstance(suite_or_report, (str, Path)) else dict(suite_or_report)
    ok_results = {"placed", "success", "completed"}
    if "suite" in data and "container_stack" in data:
        s_judge = judge_isaac_stage(data["suite"], scenario="arm-s-cell-case")
        c_judge = judge_isaac_stage(data["container_stack"], scenario="omx-map-container-stack")
        passed = s_judge["status"] == "passed" and c_judge["status"] == "passed"
        reasons = [r for r in (s_judge.get("reason"), c_judge.get("reason")) if r]
        return dict(status="passed" if passed else "failed", claim="접촉·영상", scenario="arm-s-cell-case+omx-map-container-stack",
                    run_id=c_judge.get("run_id") or s_judge.get("run_id"),
                    result=dict(suite=s_judge["result"], container_stack=c_judge["result"]),
                    artifacts=list(dict.fromkeys([*s_judge.get("artifacts", []), *c_judge.get("artifacts", [])])),
                    reason=None if passed else "; ".join(reasons))
    if data.get("schema") == "rosy.omx-container-stack/1" or ("trials" in data and "task_success" in data):
        trials = data.get("trials") or [{}]
        layers = trials[0].get("layers") or []
        fixture = data.get("fixture") or {}
        placed = sum("opened_sample" in l for l in layers)
        planned = len(fixture.get("row_order", [0, 1, 2])) * int(fixture.get("layers", 3))
        passed = bool(data.get("task_success"))
        err = trials[0].get("error") or ("; ".join(trials[0].get("failures") or []) if trials[0].get("failures") else None)
        return dict(status="passed" if passed else "failed", claim="접촉·영상", scenario="omx-map-container-stack",
                    run_id=data.get("run_id"),
                    result=dict(task_success=passed, placed=placed, planned=planned, layers=fixture.get("layers", 3),
                                case=fixture.get("case"), error=err),
                    artifacts=[], reason=None if passed else f"Isaac 3단 적재 실패({placed}/{planned}): {err or 'task_success=False'}")
    if "rows" in data:
        rows = data["rows"]
        bad = [r["id"] for r in rows if r.get("matches") is False or r.get("judgement") is None
               or (r.get("expect") is None and (r.get("judgement") or {}).get("result") not in ok_results)]
        passed = bool(rows) and not bad
        return dict(status="passed" if passed else "failed", claim="접촉·영상", scenario=scenario,
                    run_id=rows[-1].get("run_id") if rows else None,
                    result=dict(total=len(rows), matched=sum(r.get("matches") is True for r in rows),
                                measured=sum(r.get("expect") is None and r.get("judgement") is not None for r in rows),
                                failed_cases=bad),
                    artifacts=[], reason=None if passed else (f"Isaac 불일치/미판정: {', '.join(bad)}" if bad else "Isaac 실행 결과가 비어 있습니다."))
    if "judgement" in data:
        judgement = data["judgement"] or {}
        passed = judgement.get("result") in ok_results
        return dict(status="passed" if passed else "failed", claim="접촉·영상", scenario=scenario,
                    run_id=data.get("run_id"), result=judgement, artifacts=[],
                    reason=None if passed else f"Isaac 판정 실패: {judgement.get('result')}")
    s2 = data.get("stage_2_isaac") or {}
    cases = data.get("cases") or s2.get("single_arm_cases") or []
    return dict(status="pending" if cases else "not_run", claim="접촉·영상", scenario=scenario,
                run_id=None, result=dict(prepared_cases=[c.get("id") for c in cases],
                                         two_arm_scenario=s2.get("two_arm_scenario"),
                                         two_arm_config=s2.get("two_arm_config")), artifacts=[],
                reason=None if cases else "전달할 Isaac 케이스가 없습니다.")


def run_isaac_stage(run: Path, sha: str, python: str, mode: str, only: list[str] | None = None) -> dict | Path | None:
    """Execute Stage 2 Isaac Sim (cell_case_suite and/or 3-tier omx-map-container-stack) from Stage 1's handoff."""
    suite_report = stack_report = None
    suite_file = run / "isaac-suite.json"
    handoff_file = run / "isaac-handoff.json"
    if mode in ("suite", "both") and suite_file.is_file():
        out_dir = run / "isaac-runs"
        only_args = [arg for cid in (only or []) for arg in ("--only", cid)]
        subprocess.run([python, str(ROOT / "deploy/robot/omx/cell_case_suite.py"), "--suite", str(suite_file),
                        "--sha", sha, "--out", str(out_dir), *only_args], check=False)
        if (out_dir / "suite-report.json").is_file():
            suite_report = json.loads((out_dir / "suite-report.json").read_text(encoding="utf-8"))
    if mode in ("container-stack", "both") and handoff_file.is_file():
        s2 = (json.loads(handoff_file.read_text(encoding="utf-8")).get("stage_2_isaac") or {})
        cfg = s2.get("two_arm_config") or dict(seed=0, layers=3, case="nominal-palletizing-v21-ship-surveyed-skew-20261110")
        out_dir = run / "isaac-container-stack"
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = out_dir / "config.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        subprocess.run([python, str(ROOT / "tools/remote/remote_isaac.py"), "run", "--scenario",
                        s2.get("two_arm_scenario", "omx-map-container-stack"), "--config", str(cfg_file),
                        "--sha", sha, "--out", str(out_dir / "run")], check=False)
        found = next((out_dir / "run").rglob("mapped-stack-report.json"), None)
        if found and found.is_file():
            stack_report = json.loads(found.read_text(encoding="utf-8"))
    if mode == "both" and suite_report is not None and stack_report is not None:
        return dict(suite=suite_report, container_stack=stack_report)
    return stack_report if mode == "container-stack" else suite_report


def parent_on_same_seeds(python: str, sim: str, cell: str, model: Path, episodes: int, base: int, run: Path, environment: dict) -> dict | None:
    """The parent re-evaluated on this round's seeds; None when it cannot run (its checkpoint may be on another PC), which must not undo the round's own result."""
    done = subprocess.run([python, sim, "--cell", cell, "evaluate", "--model", str(model), "--episodes", str(episodes),
                           "--seed-base", str(base), "--out", str(run / "eval-parent.json"), "--artifacts", str(run / "artifacts-parent")],
                          env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None if done.returncode else summarise(json.loads((run / "eval-parent.json").read_text(encoding="utf-8"))["rows"], base)


def source_sha(args) -> str:
    return args.source_sha or subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def require_gpu(python: str) -> None:
    """lerobot-train silently falls back to CPU when the GPU is lost (40k steps became 13 h), so refuse first."""
    if subprocess.run([python, "-c", "import sys, torch; sys.exit(not torch.cuda.is_available())"]).returncode:
        raise SystemExit("no usable GPU for training; nothing started. Check nvidia-smi on this host.")


def run_round(args) -> int:
    require_gpu(args.python)
    root = Path(args.root)
    cell = json.loads(Path(args.cell).read_text(encoding="utf-8"))
    parent = args.parent or best_round(root)
    seeds_from_parent = read_round(root, parent)["stages"]["mujoco"]["eval"]["failed_seeds"] if parent else []
    recipe = dict(RECIPE, steps=args.steps, optimizer_lr=args.lr)
    row = new_round(root, parent, cell, source_sha(args), recipe, len(seeds_from_parent), args.episodes + len(seeds_from_parent))
    path = write_round(root, row)
    run, sim = path.parent, str(Path(__file__).with_name("omx_cell_sim.py"))
    environment = dict(os.environ, MUJOCO_GL="egl", PYTHONUNBUFFERED="1")
    row["stages"]["mujoco"].update(status="running", started_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    write_round(root, row)
    base = eval_seed_base(root)
    steps = [
        [args.python, sim, "--cell", args.cell, "collect", "--episodes", str(args.episodes), "--extra-seeds", ",".join(map(str, seeds_from_parent)), "--out", str(run / "dataset")],
        [args.lerobot_train, f"--dataset.repo_id=rosy/omx-ladder-{row['round_id']}", f"--dataset.root={run / 'dataset'}", "--dataset.video_backend=pyav",
         "--policy.type=act", "--policy.device=cuda", "--policy.push_to_hub=false", f"--policy.chunk_size={recipe['chunk_size']}",
         f"--policy.n_action_steps={recipe['n_action_steps']}", f"--policy.optimizer_lr={recipe['optimizer_lr']}", f"--batch_size={recipe['batch_size']}",
         f"--steps={recipe['steps']}", f"--save_freq={recipe['steps']}", "--log_freq=500", "--num_workers=4", "--wandb.enable=false", f"--output_dir={run / 'train'}", "--job_name=omx-ladder"],
        [args.python, sim, "--cell", args.cell, "evaluate", "--model", str(run / "train/checkpoints/last/pretrained_model"), "--episodes", str(args.eval_episodes),
         "--seed-base", str(base), "--out", str(run / "eval.json"), "--artifacts", str(run / "artifacts")],
    ]
    try:
        with (run / "round.log").open("w", encoding="utf-8") as log:
            for argv in steps:
                subprocess.run(argv, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    except subprocess.CalledProcessError as exc:
        row["stages"]["mujoco"].update(status="failed", reason=f"{Path(str(exc.cmd[0])).name} {exc.cmd[2] if len(exc.cmd) > 2 else ''} 종료 코드 {exc.returncode}. round.log를 보세요.",
                                       finished_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        write_round(root, row)
        return 1
    result = json.loads((run / "eval.json").read_text(encoding="utf-8"))
    evaluation = summarise(result["rows"], base)
    stage = row["stages"]["mujoco"]
    stage.update(status="passed", eval=evaluation, finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                 artifacts=[dict(name=name, path=f"artifacts/{name}", kind="image") for name in result["artifacts"]])
    # The same seeds for both: an old score came from easier or harder seeds and would not compare.
    best = parent and parent_on_same_seeds(args.python, sim, args.cell, root / "rounds" / parent / "train/checkpoints/last/pretrained_model",
                                           args.eval_episodes, base, run, environment)
    row["comparison"] = dict(against=parent, same_seeds=bool(best), parent_eval=best, result="unclear" if parent and not best else compare(evaluation, best))
    if getattr(args, "gazebo_report", None):
        row["stages"]["gazebo"] = judge_gazebo_contract(args.gazebo_report)
    if getattr(args, "isaac_report", None):
        row["stages"]["isaac"] = judge_isaac_stage(args.isaac_report)
    write_round(root, row)
    print(json.dumps(dict(round_id=row["round_id"], eval=evaluation, comparison=row["comparison"]), ensure_ascii=False))
    return 0


def run_two_arm(args) -> int:
    """One scripted two-arm task as a record the screen can read: geometry of the plan (D-947), not a learned policy."""
    run_id = new_round_id()
    run = Path(args.root) / "two_arm" / run_id
    run.mkdir(parents=True)
    record = dict(schema=TWO_ARM_SCHEMA, run_id=run_id, task=args.task, seed=args.seed, source_sha=source_sha(args), status="running",
                  created_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    file = run / "run.json"
    file.write_text(json.dumps(record), encoding="utf-8")
    teacher = str(Path(__file__).with_name("omx_two_arm_teacher.py"))
    extra = [*(["--pick-vision"] if getattr(args, "pick_vision", False) else []),
             *(["--belt-skew"] if getattr(args, "belt_skew", False) else []),
             *[arg for item in (getattr(args, "choice", None) or []) for arg in ("--choice", item)]]
    handoff_file = run / "isaac-handoff.json"
    if extra or getattr(args, "isaac_handoff", False) or getattr(args, "run_isaac", None):
        extra += ["--isaac-handoff", str(handoff_file)]
    with (run / "run.log").open("w", encoding="utf-8") as log:
        code = subprocess.run([args.python, teacher, "run", args.task, "--seed", str(args.seed), "--out", str(run), "--video", "--frames", str(run / "artifacts"), *extra],
                              env=dict(os.environ, MUJOCO_GL="egl", PYTHONUNBUFFERED="1"), stdout=log, stderr=subprocess.STDOUT).returncode
    out = run / f"{args.task}-elliptic-seed{args.seed}.json"
    if out.exists():
        result = json.loads(out.read_text(encoding="utf-8"))
        record.update({key: result[key] for key in ("steps", "steps_pass", "final_ok", "final_total", "roll_below_floor_steps", "note")})
        record.update(status="passed" if result["completed"] else "failed",
                      failed_steps=[dict(step=row["step"], arm=row["arm"], result=row["result"], reason=row.get("reason")) for row in result["rows"] if row["result"] != "pass"])
    else:
        record.update(status="failed", reason=f"종료 코드 {code}. run.log를 보세요.")
    if handoff_file.exists():
        record["isaac_handoff"] = handoff_file.name
        suite_file = run / "isaac-suite.json"
        cell_cases = ROOT / "deploy/robot/omx/cell_cases.py"
        if cell_cases.is_file():
            subprocess.run([args.python, str(cell_cases), "--mujoco-handoff", str(handoff_file), "--out", str(suite_file)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if suite_file.exists():
                record["isaac_suite"] = suite_file.name
    isaac_report = getattr(args, "isaac_report", None)
    if not isaac_report and getattr(args, "run_isaac", None) and record["status"] == "passed":
        isaac_report = run_isaac_stage(run, record["source_sha"], args.python, args.run_isaac, getattr(args, "isaac_only", None))
    if getattr(args, "gazebo_report", None) or isaac_report or handoff_file.exists():
        record["stages"] = dict(
            mujoco=dict(stage_order=1, track="learning_and_physics", status=record["status"], claim="기하: 도달·순서·충돌", steps_pass=record.get("steps_pass"), steps=record.get("steps")),
            isaac=dict(stage_order=2, track="learning_and_physics", **(judge_isaac_stage(isaac_report if isaac_report else handoff_file)
            if (isaac_report or handoff_file.exists()) else dict(
                status="not_run", claim="접촉·영상", scenario="arm-s-cell-case", run_id=None, result=None, artifacts=[], reason="이 실행에서 Isaac 핸드오프를 생성하지 않았습니다."))),
            gazebo=dict(stage_order=None, track="ros2_execution_contract", **(judge_gazebo_contract(args.gazebo_report) if getattr(args, "gazebo_report", None) else dict(
                status="not_run", claim="ROS 실행 계약", contract=None, artifacts=[], reason="별도 ROS 2 실행 계약 점검을 이 실행에서 수행하지 않았습니다."))),
        )
    record["views"] = sorted(path.name for path in (run / "artifacts").glob("*.png"))
    record["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: record.get(k) for k in ("run_id", "status", "steps_pass", "steps", "isaac_handoff", "isaac_suite", "stages")}, ensure_ascii=False))
    return 0 if record["status"] == "passed" else 1


def run_two_arm_compare(args) -> int:
    """The same Harbor-ordered input (stack from the conveyor, two outbound requests) in one-arm A, one-arm B and two-arm mode:
    omx_two_arm_plan.py assigns and schedules, the teacher runs each plan (two-arm with both arms at once). Geometry only (D-947)."""
    run_id = new_round_id()
    run = Path(args.root) / "two_arm_compare" / run_id
    (run / "artifacts").mkdir(parents=True)
    record = dict(schema=TWO_ARM_COMPARE_SCHEMA, run_id=run_id, seed=args.seed, source_sha=source_sha(args), status="running",
                  created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                  claim="같은 입력의 한 팔·두 팔 기하 비교(D-947). 실제 팔의 성공이 아니고, 시간은 정답 동작의 구간값입니다.")
    file = run / "compare.json"
    file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    sim, env = Path(__file__).parent, dict(os.environ, MUJOCO_GL="egl", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    runs = []
    with (run / "run.log").open("w", encoding="utf-8") as log:
        code = subprocess.run([args.python, str(sim / "omx_two_arm_plan.py"), "compare", "--out", str(run / "plan.json"), "--replay-dir", str(run / "replay")],
                              env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        plan = json.loads((run / "plan.json").read_text(encoding="utf-8")) if code == 0 else {}
        for scenario in ("stack", "outbound"):
            for tag, mode, both in COMPARE_RUNS if plan else ():
                planned, out = plan[mode][scenario], run / "runs" / f"{scenario}-{tag}"
                row = dict(scenario=scenario, mode=tag, concurrent=both, planned_makespan_s=planned["makespan_s"], holds=planned.get("holds", []),
                           extra_transports=planned["extra_transports"], moves_per_arm=planned["moves_per_arm"])
                subprocess.run([args.python, str(sim / "omx_two_arm_teacher.py"), "run", "plan", "--plan", str(run / "replay" / f"{scenario}-{tag}.json"),
                                "--seed", str(args.seed), "--out", str(out), "--video", "--video-skip", "3", *(["--concurrent"] if both else [])],
                               env=env, stdout=log, stderr=subprocess.STDOUT)
                result = out / f"plan-elliptic-seed{args.seed}.json"
                if result.exists():
                    r = json.loads(result.read_text(encoding="utf-8"))
                    row.update({k: r.get(k) for k in ("steps", "steps_pass", "completed", "makespan_s", "overlap_s")},
                               failed_steps=[dict(step=x["step"], arm=x["arm"], result=x["result"], reason=x.get("reason")) for x in r["rows"] if x["result"] != "pass"])
                else:
                    row.update(completed=False, reason="정답 동작이 결과를 남기지 못했습니다. run.log를 보세요.")
                video = out / "plan-short.mp4"
                if video.exists():
                    row["video"] = f"{scenario}-{tag}.mp4"
                    video.replace(run / "artifacts" / row["video"])
                runs.append(row)
    two = [r for r in runs if r["mode"] == "two-arm"]
    record.update(runs=runs, videos=sorted(r["video"] for r in runs if r.get("video")),
                  status="passed" if two and all(r["completed"] for r in two) else "failed",
                  finished_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    if not runs:
        record["reason"] = f"계획 단계가 끝나지 못했습니다(종료 코드 {code}). run.log를 보세요."
    elif record["status"] == "failed":
        record["reason"] = "두 팔 모드가 과제를 끝까지 마치지 못했습니다."
    file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return 0 if record["status"] == "passed" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("round")
    one.add_argument("--root", required=True)
    one.add_argument("--cell", required=True)
    one.add_argument("--python", default=sys.executable)
    one.add_argument("--lerobot-train", required=True)
    one.add_argument("--parent")
    one.add_argument("--source-sha", help="the commit this copy came from, when the folder has no Git")
    one.add_argument("--episodes", type=int, default=60)
    one.add_argument("--eval-episodes", type=int, default=50)
    one.add_argument("--steps", type=int, default=RECIPE["steps"])
    one.add_argument("--lr", type=float, default=RECIPE["optimizer_lr"])
    one.add_argument("--gazebo-report", help="Gazebo ROS 2 conformance report or samples JSON (D-866 §2)")
    one.add_argument("--isaac-report", help="Isaac Sim cell_case_suite report, single report, or handoff JSON (D-872)")
    two = commands.add_parser("two-arm")
    two.add_argument("--root", required=True)
    two.add_argument("--python", default=sys.executable)
    two.add_argument("--task", required=True, choices=["stack", "rehandle"])
    two.add_argument("--seed", type=int, default=0)
    two.add_argument("--source-sha", help="the commit this copy came from, when the folder has no Git")
    two.add_argument("--pick-vision", action="store_true", help="infer belt pick pose from top camera")
    two.add_argument("--belt-skew", action="store_true", help="spawn skewed/offset containers on belt")
    two.add_argument("--choice", action="append", help="key=value override of omx_two_arm_sites.CHOICES")
    two.add_argument("--isaac-handoff", action="store_true", help="emit Stage-2 Isaac Sim case suite from MuJoCo picks")
    two.add_argument("--run-isaac", nargs="?", const="suite", choices=["suite", "container-stack", "both"],
                     help="automatically run Stage-2 Isaac Sim (cell_case_suite and/or 3-tier omx-map-container-stack)")
    two.add_argument("--isaac-only", action="append", help="case id filter passed to cell_case_suite.py with --run-isaac")
    two.add_argument("--gazebo-report", help="Gazebo ROS 2 conformance report or samples JSON (D-866 §2)")
    two.add_argument("--isaac-report", help="Isaac Sim cell_case_suite report or single report JSON (D-872)")
    both = commands.add_parser("two-arm-compare")
    both.add_argument("--root", required=True)
    both.add_argument("--python", default=sys.executable)
    both.add_argument("--seed", type=int, default=0)
    both.add_argument("--source-sha", help="the commit this copy came from, when the folder has no Git")
    args = parser.parse_args(argv)
    return dict(round=run_round, two_arm=run_two_arm, two_arm_compare=run_two_arm_compare)[args.command.replace("-", "_")](args)


if __name__ == "__main__":
    raise SystemExit(main())
