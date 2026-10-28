"""Batch LeRobot export of scripted-teacher SIM reach episodes, split ready for ``act_job.py``.

sim_batch_export.py --results TEACHER.json --recordings DIR --out NEW_DIR [--eval-count 1]
                    [--python PY] [--repo-id ID]

``TEACHER.json`` is ``rosy.omx-sim-reach-teacher-results.v1`` (deploy/robot/omx/sim_reach_teacher.py);
``DIR`` holds the recorder's ``<episode_id>/manifest.json`` folders copied out of the SIM volume.
Only an episode that the teacher judged a success AND whose recording is complete, issue-free,
``task_outcome=success``, in the task's joint order, with every row at the task's single
``jog_duration_s`` and the same world/calibration/camera/fps/limits as the others is exported -- one
``lerobot_export.py`` subprocess per episode (its CLI, in the lerobot==0.4.4 interpreter given by
``--python``), each into ``NEW_DIR/exports/<episode_id>``. Every other episode is listed under
``refused`` with its reasons; nothing is repaired, interpolated or relabelled.

The eval split is the ``--eval-count`` exported episodes with the highest seeds, the rest train.
``NEW_DIR/batch-manifest.json`` (``rosy.omx-sim-batch-export.v1``) lists both and the exact
``act_job.py`` arguments. Exit 0 when at least two train and one eval export exist, else 2.
No robot, ROS or network command.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPORTER = Path(__file__).resolve().parent / "lerobot_export.py"
SCHEMA = "rosy.omx-sim-batch-export.v1"
RESULTS_SCHEMA = "rosy.omx-sim-reach-teacher-results.v1"
DEMONSTRATION_SCHEMA = "rosy.omx-demonstration.v1"
# act_job.compatible_sources keys: every export of one study must agree on them.
COMPATIBLE_KEYS = ("joint_names", "position_limits_rad", "camera", "fps", "calibration_revision", "world_sha256")


def _task_module():
    spec = importlib.util.spec_from_file_location("sim_reach_task", ROOT / "deploy/robot/omx/sim_reach_task.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_exporter(episode: Path, output: Path, repo_id: str, *, python: str = sys.executable) -> dict:
    """``lerobot_export.py`` as its CLI is meant to be called; its ``rosy_export.json`` is the receipt."""
    # Same PYTHONPATH as the documented single-episode command (deploy/robot/omx/README.md).
    paths = [str(ROOT / "middleware/devices/omx/adapter"), str(ROOT / "contracts/foundation")]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths + [os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
    done = subprocess.run([python, str(EXPORTER), str(episode), str(output), "--repo-id", repo_id],
                          capture_output=True, text=True, env=env)
    receipt = output / "rosy_export.json"
    report = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    if done.returncode != 0 or report.get("status") != "verified":
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no output"]
        raise ValueError(f"exit {done.returncode}, status {report.get('status')}: {tail[0][:300]}")
    return report


def recording_reasons(episode: dict, recordings: Path, task: dict) -> tuple[list[str], dict | None]:
    """Why one teacher episode cannot be exported (empty list = exportable) and its provenance."""
    reasons = []
    if not episode.get("success"):
        reasons.append(f"teacher_failure:{episode.get('reason') or 'not_reached'}")
    recording = episode.get("recording") or {}
    if recording.get("status") != "complete":
        reasons.append(f"recording_{recording.get('status') or 'missing'}")
    if recording.get("issues"):
        reasons.append("recording_issues:" + ",".join(recording["issues"]))
    episode_id = recording.get("episode_id")
    folder = recordings / str(episode_id)
    if not episode_id or not (folder / "manifest.json").is_file():
        return reasons + ["source_missing"], None
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    source = manifest.get("provenance") or {}
    if manifest.get("schema") != DEMONSTRATION_SCHEMA:
        reasons.append("source_schema")
    if manifest.get("episode_id") != episode_id:
        reasons.append("source_episode_id_mismatch")
    if manifest.get("status") != "complete" or manifest.get("issues"):
        reasons.append(f"source_{manifest.get('status')}:" + ",".join(manifest.get("issues") or []))
    if manifest.get("task_outcome") != "success":
        reasons.append(f"source_outcome_{manifest.get('task_outcome')}")
    if source.get("joint_names") != task["joint_names"]:
        reasons.append("joint_order_differs_from_task")
    try:
        rows = [json.loads(line) for line in (folder / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError):
        return reasons + ["samples_unreadable"], source
    durations = sorted({row.get("duration_s") for row in rows}, key=str)
    if durations != [task["jog_duration_s"]]:
        reasons.append(f"duration_mismatch:{durations}")
    if len(rows) < 2 or len(rows) != manifest.get("frame_count"):
        reasons.append("frame_count")
    return reasons, source


def plan(results: dict, recordings: Path) -> tuple[list[dict], list[dict]]:
    """(exportable candidates in seed order, refused) before any export runs."""
    task = _task_module().validate_task(results["task"])
    accepted, refused, reference, seen = [], [], None, set()
    for episode in sorted(results["episodes"], key=lambda item: item["seed"]):
        reasons, source = recording_reasons(episode, recordings, task)
        episode_id = (episode.get("recording") or {}).get("episode_id")
        if episode_id in seen:
            reasons.append("duplicate_episode_id")
        seen.add(episode_id)
        if not reasons:
            if reference is None:
                reference = source
            differs = [key for key in COMPATIBLE_KEYS if source.get(key) != reference.get(key)]
            if differs:
                reasons.append("provenance_mismatch:" + ",".join(differs))
        entry = {"index": episode.get("index"), "seed": episode["seed"], "episode_id": episode_id}
        (refused if reasons else accepted).append({**entry, **({"reasons": reasons} if reasons else {})})
    return accepted, refused


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def batch_export(results_path: Path, recordings: Path, out: Path, *, eval_count: int = 1,
                 repo_id: str = "rosy-local/omx-sim", exporter=run_exporter) -> dict:
    results_path, recordings, out = Path(results_path).resolve(), Path(recordings).resolve(), Path(out).resolve()
    if eval_count < 1:
        raise ValueError("at least one eval episode is required")
    if out.exists() or out.drive.upper() == "F:" or out.is_relative_to(recordings):
        raise ValueError("a new output directory outside F: and outside the recordings is required")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if results.get("schema") != RESULTS_SCHEMA:
        raise ValueError(f"teacher results must be {RESULTS_SCHEMA}")
    accepted, refused = plan(results, recordings)
    out.mkdir(parents=True)
    exported = []
    for entry in accepted:
        target = out / "exports" / entry["episode_id"]
        target.parent.mkdir(exist_ok=True)
        try:
            exporter(recordings / entry["episode_id"], target, repo_id)
        except Exception as exc:   # the exporter's own refusal is the reason
            refused.append({**entry, "reasons": [f"export_failed:{exc}"]})
            continue
        exported.append({**entry, "export": target.as_posix()})
    split = len(exported) - eval_count
    train, evaluation = exported[:max(split, 0)], exported[max(split, 0):]
    ready = len(train) >= 2 and len(evaluation) == eval_count
    manifest = {"schema": SCHEMA, "status": "ready" if ready else "insufficient",
                "task_id": results["task_id"], "task_sha256": results["task_sha256"],
                "teacher_results": results_path.as_posix(), "teacher_results_sha256": sha256(results_path),
                "recordings_root": recordings.as_posix(), "jog_duration_s": results["task"]["jog_duration_s"],
                "eval_rule": f"highest {eval_count} seed(s) among exported episodes",
                "train": train, "eval": evaluation,
                "refused": sorted(refused, key=lambda item: item["seed"]),
                "act_job_args": (["--train-export", *[e["export"] for e in train],
                                  "--eval-export", evaluation[0]["export"]] if ready else [])}
    (out / "batch-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--recordings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--eval-count", type=int, default=1)
    parser.add_argument("--repo-id", default="rosy-local/omx-sim")
    parser.add_argument("--python", default=sys.executable, help="interpreter with lerobot==0.4.4")
    args = parser.parse_args(argv)
    manifest = batch_export(args.results, args.recordings, args.out, eval_count=args.eval_count,
                            repo_id=args.repo_id,
                            exporter=lambda e, o, r: run_exporter(e, o, r, python=args.python))
    print(json.dumps({key: manifest[key] for key in ("status", "train", "eval", "refused")}, indent=2))
    return 0 if manifest["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
