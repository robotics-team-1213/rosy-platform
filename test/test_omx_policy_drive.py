"""A policy chunk reaches the arm only as a runner chunk inside the reviewed envelope, never faster than taught (2026-11-18)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_policy_drive as drive  # noqa: E402

NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def cal(wrist_roll_homing=0):
    return {n: {"id": i, "drive_mode": 0, "homing_offset": wrist_roll_homing if n == "wrist_roll" else 0,
                "range_min": 0, "range_max": 4095} for i, n in enumerate(NAMES)}


def test_homing_difference_becomes_a_unit_offset():
    off = drive.calibration_offset(cal(957), cal(0))
    assert off[4] == pytest.approx(957 * 200 / 4095) and off[:4] == [0.0] * 4 and off[5] == 0.0
    other = cal(0)
    other["elbow_flex"]["range_max"] = 4000
    with pytest.raises(ValueError, match="not a pure homing shift"):
        drive.calibration_offset(cal(0), other)


LIB = {"fps": 30, "gripper_closed": 46.6,
       "chunks": {"home": [[0, -58, 51, 50, -5, 49]] * 2,
                  "reach": [[0, -58, 51, 50, -5, 49], [10, -40, 40, 45, -5, 49], [20, -20, 30, 40, -5, 60]]}}


def test_envelope_is_the_reviewed_range_and_fastest_step():
    low, high, fastest = drive.envelope(LIB)
    assert low == [0, -58, 30, 40, -5, 49] and high == [20, -20, 51, 50, -5, 60]
    assert fastest == pytest.approx(20.0)


def test_shape_refuses_outside_and_stretches_fast_steps():
    low, high, _ = drive.envelope(LIB)
    with pytest.raises(ValueError, match="wrist_roll"):
        drive.shape_chunk([[0, -58, 51, 50, 40, 49]], [0, -58, 51, 50, -5, 49], low, high, 2.0)
    out = drive.shape_chunk([[10, -58, 51, 50, -5, 49]], [0, -58, 51, 50, -5, 49], low, high, 2.0)
    assert len(out) == 5 and out[-1] == [10, -58, 51, 50, -5, 49]
    assert max(abs(b[0] - a[0]) for a, b in zip([[0] * 6] + out, out)) <= 2.0 + 1e-9
    with pytest.raises(ValueError, match="finite"):
        drive.shape_chunk([[np.nan] * 6], [0] * 6, low, high, 2.0)


class Policy:
    image_views = {"top": (4, 4), "wrist": (4, 4)}

    def __init__(self, chunks):
        self.chunks, self.seen = list(chunks), []

    def inputs(self, state, frames):
        self.seen.append(state)
        return {"state": state}, {"model_frame_sha256": {}}

    def infer(self, obs):
        from types import SimpleNamespace
        return SimpleNamespace(chunk=self.chunks.pop(0))


class Cell:
    def __init__(self, replies=None):
        self.commands, self.replies = [], dict(replies or {})
        self.state = [0, -58, 51, 50, -5, 49]

    def frame(self, view):
        return np.zeros((4, 4, 3), np.uint8)

    def act(self, command):
        self.commands.append(command)
        if command.startswith("load "):
            lib = json.loads(Path(command[5:]).read_text())
            assert set(lib["chunks"]) == {"home", "reach", "policy"}  # IK chunks stay beside the policy chunk
        reply = self.replies.get(command.split()[0] if command.startswith("load ") else command, {"ok": True})
        return {"state": self.state, **reply}


def write_lib(tmp_path, library=LIB):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(library))
    return path


GRASP_THEN_RELEASE = [[[5, -50, 45, 48, -5 + 46.7, 46.0]], [[5, -50, 45, 48, -5 + 46.7, 58.0]]]


def test_episode_runs_policy_chunks_then_parks_after_release(tmp_path):
    cell, rows = Cell({"run policy": {"ok": True, "holding": True}}), []
    off = [0, 0, 0, 0, 46.7, 0]
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path, offset=off,
                               max_chunks=3, dry_run=False, log=rows.append)
    assert result["result"] == "released" and result["parked"]
    assert [c.split()[0] for c in cell.commands] == ["state", "load", "run", "state", "load", "run", "park"]
    assert cell.commands[2] == "run policy"


def test_jaws_open_to_the_library_width_before_the_model_closes():
    chunk = [[0, 0, 0, 0, 0, g] for g in (49.0, 51.0, 52.0, 50.0, 46.6, 46.6)]
    out = drive.open_before_close(chunk, 70.0, 48.8)
    assert [f[5] for f in out] == [70.0, 70.0, 70.0, 70.0, 46.6, 46.6]
    assert [f[5] for f in drive.open_before_close([[0] * 5 + [49.0]] * 3, 70.0, 48.8)] == [49.0] * 3  # no close: as given


def test_closed_empty_jaws_are_not_a_release(tmp_path):
    """11-19 real arm: jaws parked at closed then opened read as 'released' with nothing held; only the runner's hold counts."""
    result = drive.run_episode(Cell(), Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path,
                               offset=[0, 0, 0, 0, 46.7, 0], max_chunks=2, dry_run=False, log=lambda row: None)
    assert result["result"] == "chunks_done" and not result["held"]


def test_policy_sees_model_units(tmp_path):
    policy = Policy(GRASP_THEN_RELEASE)
    drive.run_episode(Cell(), policy, write_lib(tmp_path), tmp_path, offset=[0, 0, 0, 0, 46.7, 0], max_chunks=1,
                      dry_run=True, log=lambda r: None)
    assert policy.seen[0][4] == pytest.approx(-5 + 46.7)


def test_dry_run_never_loads_or_moves(tmp_path):
    cell = Cell()
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path, offset=[0, 0, 0, 0, 46.7, 0],
                               max_chunks=2, dry_run=True, log=lambda r: None)
    assert result["result"] == "dry_run" and set(cell.commands) == {"state"}


@pytest.mark.parametrize("outside", [False, True])
def test_sim_goal_cli_converts_and_logs_envelope_without_motion(tmp_path, monkeypatch, outside):
    import hashlib
    from types import SimpleNamespace

    root = tmp_path / "model"
    root.mkdir()
    weights = b"pinned ACT"
    (root / drive.lrs.WEIGHTS).write_bytes(weights)
    (root / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 4,
        "input_features": {"observation.state": {"shape": [6]}, drive.lrs.GOAL: {"shape": [10]},
                                           "observation.images.top": {"shape": [3, 4, 4]}},
        "output_features": {"action": {"shape": [6]}},
    }))
    (root / drive.lrs.UNITS).write_text('{"state":"sim_rad","gripper":"sim_jaw","arm":"arm_b"}')
    (tmp_path / "arm-cal-arm_b.json").write_text('{"arm_id":"arm_b","held_30mm":53.38,"gap_mm_per_unit":5}')
    config_path = tmp_path / "cell.json"
    config_path.write_text('{"arm_id":"arm_b","io":"unused","cameras":{}}')
    cell_cal = tmp_path / "runner-cal.json"
    cell_cal.write_text(json.dumps(cal()))
    cell = Cell()
    monkeypatch.setitem(sys.modules, "cell_pipeline", SimpleNamespace(FifoCell=lambda *_: cell))
    seen = []

    def predict(obs):
        seen.append(obs)
        action = obs["observation.state"].copy()
        if outside:
            action[0] = 1.5  # ~48 LeRobot units, above the reviewed 20 + margin.
        return action[None, :]

    shadow = drive.lrs.LeRobotShadow
    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: shadow(*a, loader=lambda *_: predict, **kw))
    args = ["--config", str(config_path), "--library", str(write_lib(tmp_path)), "--policy-root", str(root),
            "--policy-revision", hashlib.sha256(weights).hexdigest(), "--cell-calibration", str(cell_cal),
            "--operator", "test", "--max-chunks", "1", "--dry-run"]
    with pytest.raises(SystemExit) as error:
        drive.main(args)
    assert error.value.code == 2 and not cell.commands
    def wrong_units(*_):
        pytest.fail("sim action quantiles are not cell-unit envelope limits")

    monkeypatch.setattr(drive, "demonstrated_range", wrong_units)
    with pytest.raises(SystemExit):
        drive.main([*args, "--goal-site", "yard:r3-s1-t1"])
    site_args = [*args, "--goal-site", "yard:r3-s2-t1"]
    assert drive.main(site_args) == int(outside)
    assert drive.main([*site_args, "--goal-slot", "9"]) == int(outside)
    assert cell.commands == ["state", "state"]
    np.testing.assert_array_equal(seen[0][drive.lrs.GOAL], [1] + [0] * 9)
    np.testing.assert_array_equal(seen[1][drive.lrs.GOAL], [0] * 9 + [1])
    start, row, _, override, *_ = map(json.loads, (tmp_path / "policy-drive.jsonl").read_text().splitlines())
    assert start["goal_site"] == "yard:r3-s2-t1" and start["goal_destination"] == "ship-h1r0-l0"
    assert start["goal_site_slot"] == start["goal_slot"] == override["goal_site_slot"] == 0
    assert override["goal_slot"] == 9
    assert row["envelope"]["ok"] is not outside
    assert row["converted_chunk"][0][0] == pytest.approx(47.78 if outside else cell.state[0], abs=0.1)


class SimPolicy(Policy):
    sim_rule = {"held_30mm": 53.38, "gap_mm_per_unit": 5.0}
    n_action_steps = 4
    arm_id = "arm_b"

    def infer(self, obs, *, state):
        return super().infer(obs)


def test_goal_sites_use_the_h1_training_order():
    for column in range(3):
        for tier in range(3):
            assert drive.resolve_goal_site(f"yard:r{3 - column}-s2-t{tier + 1}") == (
                f"ship-h1r{column}-l{tier}", 3 * column + tier,
            )
    for site in ("tray", "vehicle_tray", "not_places:vehicle_tray"):
        assert drive.resolve_goal_site(site) == ("tray", 9)


def test_sim_policy_interpolates_from_fresh_state_and_runs_only_four_steps(tmp_path, monkeypatch):
    start = np.asarray(Cell().state)
    proposed = [start + [k / 10, 0, 0, 0, 0, 0] for k in range(1, 16)] + [start + 100]
    policy = SimPolicy([proposed, proposed])
    policy.arm_id = "arm_a"
    cell, loaded = Cell(), []
    original_act = cell.act

    def act(command):
        if command.startswith("load "):
            loaded.append(json.loads(Path(command[5:]).read_text())["chunks"]["policy"])
        if command == "run policy":
            cell.state = loaded[-1][-1]
        return original_act(command)

    cell.act = act
    monkeypatch.setattr(drive, "_moved", lambda *_: {})
    result = drive.run_episode(cell, policy, write_lib(tmp_path), tmp_path, offset=[0] * 6,
                               max_chunks=2, dry_run=False, log=lambda _: None)
    assert result["result"] == "chunks_done" and len(loaded) == 2
    assert policy.seen[1][0] == pytest.approx(0.4)
    np.testing.assert_allclose(np.asarray(loaded)[:, :, 0], [
        np.arange(1, 9) / 20, [0.25, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4],
    ])


def test_sim_dry_run_uses_only_library_envelope(tmp_path):
    rows = []
    policy = SimPolicy([[[30, -58, 51, 50, -5, 49]]])
    result = drive.run_episode(Cell(), policy, write_lib(tmp_path), tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=True, log=rows.append, demonstrated=([0] * 6, [100] * 6))
    assert result["result"] == "refused" and "shoulder_pan" in rows[0]["envelope"]["reason"]


def test_sim_jaw_close_detection_uses_converted_floor():
    from cell_act_inputs import sim_gripper

    physical_closed = 48.8
    closed = drive.converted_closed(physical_closed, SimPolicy.sim_rule)
    assert closed == pytest.approx(49.78, abs=0.01)
    assert sim_gripper(closed, SimPolicy.sim_rule) == pytest.approx(sim_gripper(physical_closed, SimPolicy.sim_rule), abs=1e-5)
    chunk = [[0] * 5 + [g] for g in (53.0, closed + 1.01, closed + 0.99, closed)]
    assert drive.open_before_close(chunk, 60, closed)[:, 5].tolist() == [60, 60, closed + 0.99, closed]


@pytest.mark.parametrize("roll, warned", [(-5, False), (95, False), (45, True)])
@pytest.mark.parametrize("dry_run", [False, True])
def test_arm_b_roll_warning_and_live_refusal(tmp_path, roll, warned, dry_run):
    cell, rows = Cell(), []
    policy = SimPolicy([[[0, -58, 51, 50, roll, 49]]])
    result = drive.run_episode(cell, policy, write_lib(tmp_path), tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=dry_run, log=rows.append)
    assert ("wrist_roll_warning" in rows[0]) is warned
    if dry_run:
        assert cell.commands == ["state"]
        assert rows[0]["envelope"]["ok"] is (roll == -5)
    elif warned:
        assert cell.commands == ["state", "park"] and result["reason"] == rows[0]["wrist_roll_warning"]


def test_out_of_envelope_parks_without_loading(tmp_path):
    cell = Cell()
    result = drive.run_episode(cell, Policy([[[0, -58, 51, 50, 80, 49]]]), write_lib(tmp_path), tmp_path,
                               offset=[0] * 6, max_chunks=1, dry_run=False, log=lambda r: None)
    assert result["result"] == "refused" and cell.commands == ["state", "park"]


def test_contact_retreats_then_parks(tmp_path):
    cell = Cell({"run policy": {"ok": False, "contact": True, "error": "strain"}})
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path,
                               offset=[0, 0, 0, 0, 46.7, 0], max_chunks=2, dry_run=False, log=lambda r: None)
    assert result["result"] == "contact" and cell.commands[-2:] == ["retreat", "park"]


def test_refused_load_parks(tmp_path):
    cell = Cell({"load": {"ok": False, "error": "plan_check: overload"}})
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path,
                               offset=[0, 0, 0, 0, 46.7, 0], max_chunks=2, dry_run=False, log=lambda r: None)
    assert result["result"] == "refused" and cell.commands[-1] == "park" and "run policy" not in cell.commands


def test_moving_needs_person_at_switch():
    with pytest.raises(SystemExit):
        drive.main(["--config", "c", "--library", "l", "--policy-root", "p", "--policy-revision", "r",
                    "--model-calibration", "m", "--cell-calibration", "c", "--operator", "x"])


def test_demonstrated_range_widens_only_where_a_person_went(tmp_path):
    low, high, _ = drive.envelope(LIB)
    wl, wh = drive.widen(low, high, [0, -58, 30, 40, -2, 46], [20, -20, 51, 50, 48, 60])
    assert wl[4] == -5 and wh[4] == 48 and wl[5] == 46 and wh[:4] == high[:4]
    rows = []
    result = drive.run_episode(Cell(), Policy([[[0, -58, 51, 50, 40, 49]]]), write_lib(tmp_path), tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=True, log=rows.append, demonstrated=([0] * 4 + [-5, 46], [0] * 4 + [48, 60]))
    assert result["result"] == "dry_run" and "refused" not in rows[0]
