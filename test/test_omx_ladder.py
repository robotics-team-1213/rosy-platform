"""The learning ladder's judge and record: strict placing, honest comparison, new seeds, and no automatic replacement."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("omx_ladder", ROOT / "tools/sim/omx_ladder.py")
ladder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ladder)
CELL = dict(scene=dict(robot="arm_b", jaw="palletizing-v2.1", wrist_camera="omx-ai-stock", revision="r"))


def fresh(root, parent=None):
    return ladder.new_round(root, parent, CELL, "0" * 40, dict(ladder.RECIPE), 0, 60)


@pytest.mark.parametrize("xy,yaw,z,tilt,strict,loose", [
    (2, 1, 0, 0, True, True), (10, 1, 0, 0, False, True), (2, 45, 0, 0, False, True), (2, 1, 9, 0, False, True),
    (2, 1, 0, 40, False, True), (30, 1, 0, 0, False, False)])
def test_strict_needs_position_yaw_height_and_flat(xy, yaw, z, tilt, strict, loose):
    row = ladder.judge(xy, yaw, z, tilt, .07)
    assert row["strict"] is strict and row["loose"] is loose and row["lifted"] is True


def test_the_interval_grows_with_the_evidence():
    assert ladder.wilson_low(19, 20) < ladder.wilson_low(190, 200) < .95
    assert ladder.wilson_low(0, 0) == 0.0 and ladder.wilson_high(0, 0) == 1.0


def summary(successes, n=50):
    rows = [dict(seed=i, **ladder.judge(2 if i < successes else 30, 1, 0, 0, .07)) for i in range(n)]
    return ladder.summarise(rows, 100000)


def test_only_intervals_that_do_not_overlap_decide():
    assert ladder.compare(summary(48), summary(10)) == "better"
    assert ladder.compare(summary(10), summary(48)) == "worse"
    assert ladder.compare(summary(26), summary(24)) == "unclear"
    assert ladder.compare(summary(1), None) == "better"


def test_a_summary_names_the_failed_seeds_for_the_next_round():
    result = summary(48)
    assert result["failed_seeds"] == [48, 49] and result["strict"]["placed"] == 48 and result["lifted"] == 50


def test_a_round_refuses_to_start_without_a_gpu(tmp_path):
    stub = tmp_path / "python"
    for code, refused in ((1, True), (0, False)):
        stub.write_text(f"#!/bin/sh\nexit {code}\n", encoding="utf-8")
        stub.chmod(0o755)
        if refused:
            with pytest.raises(SystemExit, match="no usable GPU"):
                ladder.require_gpu(str(stub))
        else:
            ladder.require_gpu(str(stub))
    args = type("Args", (), dict(root=str(tmp_path / "root"), python=str(tmp_path / "python")))
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no usable GPU"):
        ladder.run_round(args)  # before it reads the cell or writes a round
    assert not (tmp_path / "root").exists()


def stub_python(tmp_path, body):
    stub = tmp_path / "python"
    stub.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    stub.chmod(0o755)
    return str(stub)


def test_a_parent_that_cannot_run_leaves_no_comparison_instead_of_a_stuck_round(tmp_path):
    python = stub_python(tmp_path, "exit 1")
    assert ladder.parent_on_same_seeds(python, "sim", "cell", tmp_path / "missing", 5, 100, tmp_path, {}) is None


@pytest.mark.parametrize("task,completed,status,code", [("stack", True, "passed", 0), ("rehandle", False, "failed", 1)])
def test_a_two_arm_run_records_what_the_screen_needs(tmp_path, task, completed, status, code):
    result = dict(steps=2, steps_pass=1, final_ok=1, final_total=2, completed=completed, roll_below_floor_steps=["s1"], note="geometry only",
                  rows=[dict(step="s1", arm="arm_b", result="pass"), dict(step="s2", arm="arm_a", result="blocked", reason="too far")])
    (tmp_path / "result.json").write_text(json.dumps(result), encoding="utf-8")
    python = stub_python(tmp_path, f'cp {tmp_path}/result.json "$7/{task}-elliptic-seed3.json"; [ "$8" = --video ] && [ "$9" = --frames ] && mkdir -p "$7/artifacts" && touch "$7/artifacts/top.png"')
    args = type("Args", (), dict(root=str(tmp_path / "root"), python=python, task=task, seed=3, source_sha="a" * 40))
    assert ladder.run_two_arm(args) == code
    record = json.loads(next((tmp_path / "root/two_arm").glob("*/run.json")).read_text(encoding="utf-8"))
    assert record["schema"] == ladder.TWO_ARM_SCHEMA and record["status"] == status and record["steps_pass"] == 1
    assert record["failed_steps"] == [dict(step="s2", arm="arm_a", result="blocked", reason="too far")]
    assert record["roll_below_floor_steps"] == ["s1"] and record["views"] == ["top.png"]


def test_a_two_arm_run_that_writes_nothing_says_why(tmp_path):
    args = type("Args", (), dict(root=str(tmp_path / "root"), python=stub_python(tmp_path, "exit 2"), task="stack", seed=0, source_sha="a" * 40))
    assert ladder.run_two_arm(args) == 1
    record = json.loads(next((tmp_path / "root/two_arm").glob("*/run.json")).read_text(encoding="utf-8"))
    assert record["status"] == "failed" and "종료 코드 2" in record["reason"]


def test_every_round_evaluates_new_seeds(tmp_path):
    assert ladder.eval_seed_base(tmp_path) == 100000
    row = fresh(tmp_path)
    row["stages"]["mujoco"]["eval"] = summary(1)
    ladder.write_round(tmp_path, row)
    assert ladder.eval_seed_base(tmp_path) == 100000 + ladder.EVAL_SEED_STRIDE


def test_a_round_refuses_a_bad_status_or_a_block_without_a_reason(tmp_path):
    row = fresh(tmp_path)
    row["stages"]["gazebo"]["reason"] = None
    with pytest.raises(ValueError, match="gazebo"):
        ladder.write_round(tmp_path, row)
    row = fresh(tmp_path)
    row["stages"]["isaac"]["status"] = "done"
    with pytest.raises(ValueError, match="isaac"):
        ladder.write_round(tmp_path, row)
    row = fresh(tmp_path)
    row["round_id"] = "../evil"
    with pytest.raises(ValueError):
        ladder.write_round(tmp_path, row)


def test_the_best_round_comes_only_from_a_person_s_replace_decision(tmp_path):
    assert ladder.best_round(tmp_path) is None
    row = fresh(tmp_path)
    row["stages"]["mujoco"]["eval"] = summary(50)
    ladder.write_round(tmp_path, row)
    assert ladder.best_round(tmp_path) is None, "a good result alone changes nothing"
    with (tmp_path / "decisions.jsonl").open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(verdict="replace", round_id=row["round_id"])) + "\n")
        stream.write(json.dumps(dict(verdict="keep", round_id="20261107T000000-00000000")) + "\n")
    assert ladder.best_round(tmp_path) == row["round_id"]
