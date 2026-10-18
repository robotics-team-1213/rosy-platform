"""The SIM reach pipeline driver chains existing scripts by path and stops at the first failure."""

from __future__ import annotations

import importlib.util
import json
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_sim_reach_pipeline", ROOT / "tools/sim/run_sim_reach_pipeline.py")
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)
TASK = "deploy/robot/omx/sim/reach_task.example.json"


def test_every_chained_script_exists_except_the_optional_evaluation_stages():
    for path in (pipeline.TEACHER, pipeline.BATCH, pipeline.ACT_JOB):
        assert path.is_file(), path
    assert set(pipeline.OPTIONAL) == {"closed_loop", "eval"}


def test_dry_run_prints_each_stage_in_order(tmp_path):
    lines = []
    code = pipeline.main(["--task", TASK, "--episodes", "6", "--run", str(tmp_path / "run"), "--steps", "300",
                          "--lerobot-python", "/opt/lerobot/bin/python", "--dry-run"], log=lines.append)
    assert code == 0 and not (tmp_path / "run").exists()
    stages = [line.split("]")[0][1:] for line in lines]
    assert stages[:4] == ["teacher", "copy", "export", "train"]
    assert "--episodes 6" in lines[0] and "docker cp rosy-omx-pilot-sim:/recordings" in lines[1]
    train = next(line for line in lines if line.startswith("[train]"))
    assert "--steps 300" in train and "--device" not in train
    for optional in ("closed_loop", "eval"):
        line = next(line for line in lines if line.startswith(f"[{optional}]"))
        if not pipeline.OPTIONAL[optional].is_file():
            assert "skipped" in line and "not in this checkout" in line
        else:
            assert "--first-index 6" in line or optional == "eval"


@pytest.mark.parametrize("recordings, expected", [(None, "/recordings"), ("/captures", "/captures")])
def test_inside_export_reads_container_recordings_unless_overridden(tmp_path, recordings, expected):
    lines = []
    args = ["--task", TASK, "--episodes", "4", "--run", str(tmp_path / "run"), "--inside", "--dry-run"]
    if recordings is not None:
        args.extend(["--recordings", recordings])

    assert pipeline.main(args, log=lines.append) == 0

    export = shlex.split(next(line for line in lines if line.startswith("[export]")))[1:]
    assert export[export.index("--recordings") + 1] == expected
    assert any(line.startswith("[copy] skipped") for line in lines)
    assert not (tmp_path / "run").exists()


def test_run_reads_act_job_args_from_the_batch_manifest_and_stops_on_failure(tmp_path, monkeypatch):
    run = tmp_path / "run"
    recordings = tmp_path / "rec"
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[1] == str(pipeline.BATCH):
            (run / "batch").mkdir(parents=True)
            (run / "batch" / "batch-manifest.json").write_text(json.dumps({
                "status": "ready", "act_job_args": ["--train-export", "a", "b", "--eval-export", "c"]}))
        return SimpleNamespace(returncode=3 if command[1] == str(pipeline.ACT_JOB) else 0)

    lines = []
    code = pipeline.main(["--task", TASK, "--episodes", "4", "--run", str(run), "--recordings", str(recordings)],
                         runner=runner, log=lines.append)
    assert code == 3
    assert [Path(c[1]).name for c in calls] == ["sim_reach_teacher.py", "sim_batch_export.py", "act_job.py"]
    assert calls[2][2:7] == ["--train-export", "a", "b", "--eval-export", "c"]
    assert any("[copy] skipped" in line for line in lines) and "later stages not run" in lines[-1]


def test_an_insufficient_batch_stops_before_training(tmp_path):
    run = tmp_path / "run"
    (run / "batch").mkdir(parents=True)
    (run / "batch" / "batch-manifest.json").write_text(json.dumps({"status": "insufficient", "train": [{}],
                                                                   "eval": [{}], "act_job_args": []}))
    try:
        pipeline.main(["--task", TASK, "--episodes", "4", "--run", str(run), "--from-stage", "train"],
                      runner=lambda *a, **k: SimpleNamespace(returncode=0), log=lambda _l: None)
    except SystemExit as exc:
        assert "batch export not ready: 1 train, 1 eval" in str(exc)
    else:
        raise AssertionError("training ran on an insufficient batch")
