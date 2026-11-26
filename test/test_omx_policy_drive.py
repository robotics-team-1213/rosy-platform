"""A policy chunk reaches the arm only as a runner chunk inside the reviewed envelope, never faster than taught (2026-11-18)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
    def __init__(self, replies=None, expected_chunks=None):
        self.commands, self.replies = [], dict(replies or {})
        self.expected_chunks = set(expected_chunks or {"home", "reach", "policy"})
        self.state = [0, -58, 51, 50, -5, 49]

    def frame(self, view):
        return np.zeros((4, 4, 3), np.uint8)

    def act(self, command):
        self.commands.append(command)
        if command.startswith("load "):
            lib = json.loads(Path(command[5:]).read_text())
            assert set(lib["chunks"]) == self.expected_chunks  # IK chunks stay beside the policy chunk
        base_cmd = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        reply = self.replies.get(command.split()[0] if command.startswith("load ") else command, {"ok": True})
        extra = {"human_hold_latched": True, "torque_hold_commanded": True} if base_cmd == "human-hold" else {}
        return {"state": self.state, "command": base_cmd, "settled": True, "holding": False, **extra, **reply}


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


def test_hybrid_pre_lift_masks_only_model_input_and_keeps_handoff(tmp_path, monkeypatch):
    class GoalPolicy(Policy):
        goal_size = 10

        def inputs(self, state, frames, *, goal, mask_goal=False):
            self.seen.append((goal, mask_goal))
            return {"state": state}, {}

    shadow = GoalPolicy(GRASP_THEN_RELEASE)
    cell, handoff = Cell(), object()

    def timed(cell, model, library, work, **kwargs):
        assert kwargs["handoff"] is handoff
        assert kwargs["dry_run"] is True
        kwargs["infer"](cell.state, {})
        return {"result": "dry_run"}

    monkeypatch.setattr(drive, "run_timed", timed)
    path = write_lib(tmp_path)
    kwargs = dict(offset=[0] * 6, max_chunks=1, dry_run=True, log=lambda row: None, goal_slot=1)
    with pytest.raises(ValueError, match="hybrid handoff"):
        drive.run_episode(cell, shadow, path, tmp_path, mask_pick_goal=True, **kwargs)
    result = drive.run_episode(cell, shadow, path, tmp_path, handoff=handoff, mask_pick_goal=True, **kwargs)
    assert result["result"] == "dry_run"
    assert shadow.seen == [(1, True)]
    assert cell.commands == []


@pytest.mark.parametrize("outside", [False, True])
def test_sim_goal_cli_converts_and_logs_envelope_without_motion(tmp_path, monkeypatch, outside):
    import hashlib

    import cell_pipeline
    import cv2  # noqa: F401 - load the camera dependency before the inference deadline starts

    root = tmp_path / "model"
    root.mkdir()
    weights = b"pinned ACT"
    (root / drive.lrs.WEIGHTS).write_bytes(weights)
    (root / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 4, "chunk_size": 16,
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
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: cell)
    seen = []

    def predict(obs):
        seen.append(obs)
        action = obs["observation.state"].copy()
        if outside:
            action[0] = 1.5  # ~48 LeRobot units, above the reviewed 20 + margin.
        return np.repeat(action[None, :], 16, axis=0)

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
        drive.main([*args, "--goal-site", "yard:r1-s1-t1"])
    site_args = [*args, "--goal-site", "yard:r1-s2-t1"]
    assert drive.main(site_args) == int(outside)
    assert drive.main([*site_args, "--goal-slot", "9"]) == int(outside)
    assert cell.commands == ["state", "state"]
    np.testing.assert_array_equal(seen[0][drive.lrs.GOAL], [1] + [0] * 9)
    np.testing.assert_array_equal(seen[1][drive.lrs.GOAL], [0] * 9 + [1])
    start, row, _, override, *_ = map(json.loads, (tmp_path / "policy-drive.jsonl").read_text().splitlines())
    assert start["goal_site"] == "yard:r1-s2-t1" and start["goal_destination"] == "ship-h1r0-l0"
    assert start["goal_site_slot"] == start["goal_slot"] == override["goal_site_slot"] == 0
    assert override["goal_slot"] == 9
    assert row["envelope"]["ok"] is not outside
    assert row["converted_chunk"][0][0] == pytest.approx(47.78 if outside else cell.state[0], abs=0.1)


class SimPolicy(Policy):
    sim_rule = {"held_30mm": 53.38, "gap_mm_per_unit": 5.0}
    n_action_steps = 4
    chunk_size = 16
    arm_id = "arm_b"

    def infer(self, obs, *, state):
        return super().infer(obs)


def test_goal_sites_use_the_h1_training_order():
    for column in range(3):
        for tier in range(3):
            assert drive.resolve_goal_site(f"yard:r{column + 1}-s2-t{tier + 1}") == (
                f"ship-h1r{column}-l{tier}", 3 * column + tier,
            )
    for site in ("tray", "vehicle_tray", "not_places:vehicle_tray"):
        assert drive.resolve_goal_site(site) == ("tray", 9)


def test_sim_policy_interpolates_from_fresh_state_and_runs_eight_steps(tmp_path):
    start = np.asarray(Cell().state)
    proposed = [start + [k / 10, 0, 0, 0, 0, 0] for k in range(1, 16)] + [start + 100]
    policy = SimPolicy([proposed])
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
    rows = []
    result = drive.run_episode(cell, policy, write_lib(tmp_path), tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=False, log=rows.append)
    assert result["result"] == "chunks_done" and len(loaded) == 1
    assert rows[0]["action_steps"] == 8 and len(loaded[0]) == 16
    dropped = rows[0]["dropped_actions"]
    assert loaded[0][0][0] == pytest.approx((dropped + 1) / 20)
    assert loaded[0][-1][0] == pytest.approx((dropped + 8) / 10)


def test_sim_dry_run_uses_only_library_envelope(tmp_path):
    rows = []
    policy = SimPolicy([[[30, -58, 51, 50, -5, 49]] * 16])
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
    policy = SimPolicy([[[0, -58, 51, 50, roll, 49]] * 16])
    result = drive.run_episode(cell, policy, write_lib(tmp_path), tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=dry_run, log=rows.append)
    assert ("wrist_roll_warning" in rows[0]) is warned
    if dry_run:
        assert cell.commands == ["state"]
        assert rows[0]["envelope"]["ok"] is (roll == -5)
    elif warned:
        assert cell.commands == ["state", "state", "human-hold"] and result["reason"] == rows[0]["wrist_roll_warning"]


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


def test_demonstrated_range_refuses_sim_units_checkpoint(tmp_path):
    (tmp_path / "UNITS.json").write_text(json.dumps({"state": "sim_rad", "gripper": "sim_jaw", "arm": "arm_b"}))
    with pytest.raises(ValueError, match="sim-unit checkpoint"):
        drive.demonstrated_range(tmp_path, [0.0] * 6)


LIB_GRASP = {
    **LIB,
    "chunks": {
        **LIB["chunks"],
        "grasp_pick": [[38.8, -10.0, 2.0, 55.0, -14.0, 49.0]] * 2,
    },
}


class FakeKin:
    def fk(self, joints):
        from types import SimpleNamespace
        from grasp_planner import norm_to_rad

        pan = joints[0]
        yaw = pan - joints[4]
        near_pick = abs(pan - norm_to_rad(38.8)) < 0.35
        low_z = joints[1] > norm_to_rad(-30.0)
        tilt = 0.8 if joints[3] > norm_to_rad(80.0) else 0.05
        return SimpleNamespace(
            x=0.18 if near_pick else 0.02,
            y=0.14 if near_pick else 0.0,
            z=0.04 if low_z else 0.16,
            yaw=yaw,
            tool_down_error_rad=tilt,
        )


def _grasp_policy(roll, *, lift=-10.0, wrist_flex=55.0, timed=True):
    frame = [39.0, lift, 2.0, wrist_flex, roll, 49.0]
    if not timed:
        return Policy([[frame]])

    class TimedPolicy(Policy):
        n_action_steps = 4
        chunk_size = 16

    return TimedPolicy([[frame] * 16])


def _grasp_cell(state, *, replies=None):
    cell = Cell(replies=replies, expected_chunks={"home", "reach", "grasp_pick", "policy"})
    cell.state = list(state)
    return cell


@pytest.mark.parametrize("roll, lift, refused", [
    (43.93, -10.0, True),   # ~76 deg off inside grasp cylinder -> refused
    (86.0, -10.0, False),   # 180-deg twin inside grasp cylinder -> admitted
    (43.93, -55.0, False),  # high transit z -> admitted
])
def test_jaw_gate_refuses_quarter_turn_admits_twin_and_transit(tmp_path, roll, lift, refused):
    cell, rows = _grasp_cell([38.9, lift, 2.0, 55.0, roll, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    result = drive.run_episode(
        cell, _grasp_policy(roll, lift=lift), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    if refused:
        assert result["result"] == "refused" and "jaw_warning" in rows[0]
        assert "load" not in " ".join(cell.commands) and "run policy" not in cell.commands
    else:
        assert result["result"] == "chunks_done" and "jaw_warning" not in rows[0] and "run policy" in cell.commands


def test_jaw_gate_refuses_excessive_tilt_in_grasp_zone(tmp_path):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 84.9, -14.0, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 90, 90, 60]]}}
    result = drive.run_episode(
        cell, _grasp_policy(-14.0, wrist_flex=85.0), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    assert result["result"] == "refused" and "jaw tilt" in rows[0]["jaw_warning"]
    assert "run policy" not in cell.commands


@pytest.mark.parametrize("demo_range, refused", [
    (([0] * 4 + [2.59, 46.0], [0] * 4 + [48.68, 60.0]), True),   # pinky_v1 q01..q99 - 46.74 misses -14 & +86
    (([0] * 4 + [80.0, 46.0], [0] * 4 + [92.0, 60.0]), False),  # 180-deg twin interval admits -14 (+100 = 86)
])
def test_startup_preflight_refuses_pinky_v1_trained_grasp_and_admits_twin(tmp_path, demo_range, refused):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 86.0, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    result = drive.run_episode(
        cell, _grasp_policy(86.0), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, demonstrated=demo_range, kin=FakeKin(),
    )
    if refused:
        assert result["result"] == "refused" and result["at"] == 0 and cell.commands == []
        assert rows[0]["preflight"] == "jaw_roll"
    else:
        assert result["result"] == "chunks_done" and "run policy" in cell.commands


def test_legacy_loop_enforces_jaw_gate(tmp_path):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 43.93, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    result = drive.run_episode(
        cell, _grasp_policy(43.93, timed=False), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    assert result["result"] == "refused" and cell.commands == ["state", "human-hold"]
    assert "jaw yaw" in rows[0]["jaw_warning"]


def test_dry_run_logs_jaw_warning_without_motion(tmp_path):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 43.93, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    result = drive.run_episode(
        cell, _grasp_policy(43.93), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=True, log=rows.append, kin=FakeKin(),
    )
    assert result["result"] == "dry_run" and "jaw_warning" in rows[0] and cell.commands == ["state"]


@pytest.mark.parametrize("square, refused", [(False, True), (True, False)])
def test_square_object_metadata_admits_quarter_turn(tmp_path, square, refused):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 36.0, 49.0]), []
    lib = {
        **LIB_GRASP,
        "source": {"pick": {"square": square}},
        "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]},
    }
    result = drive.run_episode(
        cell, _grasp_policy(36.0), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    if refused:
        assert result["result"] == "refused" and "jaw yaw" in rows[0]["jaw_warning"]
    else:
        assert result["result"] == "chunks_done" and "run policy" in cell.commands


@pytest.mark.parametrize("bad_square", ["false", "true", 1, 0])
def test_malformed_square_metadata_refuses(tmp_path, bad_square):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 36.0, 49.0]), []
    lib = {
        **LIB_GRASP,
        "source": {"pick": {"square": bad_square}},
        "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]},
    }
    with pytest.raises(ValueError, match="square"):
        drive.run_episode(
            cell, _grasp_policy(36.0), write_lib(tmp_path, lib), tmp_path,
            offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
        )
    assert cell.commands == []


def test_library_tcp_resolved_conflicts_refused_and_boundary_enforced(tmp_path, monkeypatch):
    monkeypatch.delenv("ROSY_OMX_TCP_X_M", raising=False)
    cand = [25.0, -16.0, 14.0, 58.0, 36.0, 49.0]
    start = [24.9, -16.0, 14.0, 58.0, 36.0, 49.0]
    base_lib = {
        **LIB_GRASP,
        "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 60, 90, 60]]},
    }

    class TimedPolicy(Policy):
        n_action_steps = 4
        chunk_size = 16

    cell_stock, rows_stock = _grasp_cell(start), []
    res_stock = drive.run_episode(
        cell_stock, TimedPolicy([[cand] * 16]), write_lib(tmp_path, base_lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows_stock.append,
    )
    assert res_stock["result"] == "chunks_done" and "run policy" in cell_stock.commands

    jaw_lib = {**base_lib, "tcp_x_m": 0.0741}
    cell_jaw, rows_jaw = _grasp_cell(start), []
    res_jaw = drive.run_episode(
        cell_jaw, TimedPolicy([[cand] * 16]), write_lib(tmp_path, jaw_lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows_jaw.append,
    )
    assert res_jaw["result"] == "refused" and "jaw yaw" in rows_jaw[0]["jaw_warning"]
    assert "load" not in " ".join(cell_jaw.commands) and "run policy" not in cell_jaw.commands

    cell_conflict = _grasp_cell(start)
    with pytest.raises(ValueError, match="conflicts"):
        drive.run_episode(
            cell_conflict, TimedPolicy([[cand] * 16]), write_lib(tmp_path, jaw_lib), tmp_path,
            offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, tcp_x_m=0.091,
        )
    assert cell_conflict.commands == []

    for bad_tcp in ("bad", True, 0.01):
        cell_bad = _grasp_cell(start)
        with pytest.raises(ValueError):
            drive.run_episode(
                cell_bad, TimedPolicy([[cand] * 16]), write_lib(tmp_path, {**base_lib, "tcp_x_m": bad_tcp}), tmp_path,
                offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append,
            )
        assert cell_bad.commands == []


def test_timed_gate_refuses_unsafe_measured_state_even_when_target_outside(tmp_path, monkeypatch):
    monkeypatch.delenv("ROSY_OMX_TCP_X_M", raising=False)
    measured = [25.0, -16.0, 14.0, 58.0, 36.0, 49.0]
    target = [24.72, -16.0, 14.0, 58.0, 36.0, 49.0]
    base_lib = {
        **LIB_GRASP,
        "tcp_x_m": 0.0741,
        "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 60, 90, 60]]},
    }

    class TimedPolicy(Policy):
        n_action_steps = 4
        chunk_size = 16

    class MeasuredCell(Cell):
        def act(self, cmd):
            reply = super().act(cmd)
            if cmd == "state":
                return {**reply, "target": list(target)}
            return reply

    cell = MeasuredCell(expected_chunks={"home", "reach", "grasp_pick", "policy"})
    cell.state = list(measured)
    rows = []
    result = drive.run_episode(
        cell, TimedPolicy([[target] * 16]), write_lib(tmp_path, base_lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append,
    )
    assert result["result"] == "refused" and "jaw yaw" in rows[0]["jaw_warning"]
    assert "human-hold" in cell.commands
    assert "load" not in " ".join(cell.commands) and "run policy" not in cell.commands

    for bad_lib in (
        {**base_lib, "chunks": {**base_lib["chunks"], "grasp_pick": []}},
        {**base_lib, "chunks": {**base_lib["chunks"], "grasp_pick": None}},
        {**base_lib, "source": {"pick": {"yaw_deg": "bad"}}},
    ):
        cell_bad = _grasp_cell(measured)
        with pytest.raises(ValueError):
            drive.run_episode(
                cell_bad, TimedPolicy([[target] * 16]), write_lib(tmp_path, bad_lib), tmp_path,
                offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append,
            )
        assert cell_bad.commands == []
    with pytest.raises(ValueError):
        drive.jaw_gate_spec({**base_lib, "chunks": {**base_lib["chunks"], "grasp_pick": None}}, FakeKin())


def test_legacy_out_of_envelope_from_unsafe_posture_holds_without_park(tmp_path):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 43.93, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    policy = Policy([[[99.0, -10.0, 2.0, 55.0, 43.93, 49.0]]])
    result = drive.run_episode(
        cell, policy, write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    assert result["result"] == "refused" and cell.commands == ["state", "human-hold"]
    assert "park" not in cell.commands and "jaw yaw" in rows[0]["jaw_warning"]


def test_jaw_gate_stays_active_after_prior_hold_in_zone_and_admits_lift_above_zone(tmp_path):
    lib = {
        **LIB_GRASP,
        "gripper_closed": 49.0,
        "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]},
    }
    lib_path = write_lib(tmp_path, lib)
    c0 = [38.9, -10.0, 2.0, 55.0, -14.0, 49.0]
    c1_open = [38.9, -10.0, 2.0, 55.0, 43.93, 49.15]
    c1_closed = [38.9, -10.0, 2.0, 55.0, 43.93, 49.0]
    c1_transit = [38.9, -55.0, 2.0, 55.0, 43.93, 49.0]

    class TwoChunkCell(Cell):
        def __init__(self, c1_holding: bool, c1_measured_grip: float, *, lift: float = -10.0):
            super().__init__(expected_chunks={"home", "reach", "grasp_pick", "policy"})
            self.state = list(c0)
            self.target = list(c0)
            self.c1_holding = c1_holding
            self.c1_measured_grip = c1_measured_grip
            self.lift = lift
            self.runs = 0
            self.live_holding = False

        def act(self, cmd):
            reply = super().act(cmd)
            if cmd == "state":
                return {**reply, "target": list(self.target), "holding": self.live_holding}
            if cmd.endswith("run policy"):
                self.runs += 1
                self.live_holding = self.c1_holding
                self.state = [38.9, self.lift, 2.0, 55.0, 43.93, self.c1_measured_grip]
                self.target = [38.9, self.lift, 2.0, 55.0, 43.93, 49.0]
                return {**reply, "holding": True}
            return reply

    class TwoChunkTimedPolicy(Policy):
        n_action_steps = 4
        chunk_size = 16

        def __init__(self, second):
            super().__init__([[c0] * 16])
            self.second = second
            self.calls = 0

        def infer(self, obs):
            self.calls += 1
            return SimpleNamespace(chunk=[c0] * 16 if self.calls == 1 else [self.second] * 16)

    pos_cell, pos_rows = TwoChunkCell(True, 53.0, lift=-55.0), []
    pos_res = drive.run_episode(
        pos_cell, TwoChunkTimedPolicy(c1_transit), lib_path, tmp_path,
        offset=[0] * 6, max_chunks=2, dry_run=False, log=pos_rows.append, kin=FakeKin(),
    )
    assert pos_res["result"] == "chunks_done" and pos_cell.runs == 2

    for c1_holding, meas_grip, c1_frame in (
        (True, 53.0, c1_open),
        (True, 53.0, c1_closed),
        (True, 49.0, c1_closed),
        (False, 53.0, c1_closed),
    ):
        cell, rows = TwoChunkCell(c1_holding, meas_grip), []
        res = drive.run_episode(
            cell, TwoChunkTimedPolicy(c1_frame), lib_path, tmp_path,
            offset=[0] * 6, max_chunks=2, dry_run=False, log=rows.append, kin=FakeKin(),
        )
        assert res["result"] == "refused" and res["at"] == 1 and cell.runs == 1
        assert cell.commands[-1] == "human-hold" and "jaw yaw" in rows[-2]["jaw_warning"]
        assert sum(" load " in f" {cmd}" for cmd in cell.commands) == 1

    class TwoChunkLegacyPolicy(Policy):
        def __init__(self, second):
            super().__init__([[c0]])
            self.second = second
            self.calls = 0

        def infer(self, obs):
            self.calls += 1
            return SimpleNamespace(chunk=[c0] if self.calls == 1 else [self.second])

    for c1_holding, meas_grip, c1_frame in (
        (True, 53.0, c1_open),
        (True, 53.0, c1_closed),
        (True, 49.0, c1_closed),
    ):
        legacy_cell, legacy_rows = TwoChunkCell(c1_holding, meas_grip), []
        legacy_res = drive.run_episode(
            legacy_cell, TwoChunkLegacyPolicy(c1_frame), lib_path, tmp_path,
            offset=[0] * 6, max_chunks=2, dry_run=False, log=legacy_rows.append, kin=FakeKin(),
        )
        assert legacy_res["result"] == "refused" and legacy_res["at"] == 1 and legacy_cell.runs == 1
        assert legacy_cell.commands[-1] == "human-hold" and "jaw yaw" in legacy_rows[-2]["jaw_warning"]
        assert sum(" load " in f" {cmd}" for cmd in legacy_cell.commands) == 1


def test_null_jaw_empty_stop_falls_back_to_gripper_closed(tmp_path):
    from cell_policy_handoff import CellHandoff
    from cell_policy_shape import closed_gripper

    lib = {
        **LIB_GRASP,
        "gripper_closed": 46.6,
        "jaw_empty_stop": None,
        "source": {"pick": {"x": 0.18, "y": 0.14, "z": 0.04, "yaw_deg": 95.0}},
        "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 46], [40, -10, 51, 55, 90, 60]]},
    }
    assert closed_gripper(lib) == 46.6
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, 86.0, 49.0]), []
    res = drive.run_episode(
        cell, _grasp_policy(86.0), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    assert res["result"] == "chunks_done" and "run policy" in cell.commands
    cfg = {"sites": {"belt": {"surface_z": 0.0}}}
    handoff = CellHandoff(cfg, "belt", write_lib(tmp_path, lib), lib, 47.6, tmp_path)
    assert handoff.spec["empty_stop"] == 46.6


def test_configured_rim_z_raises_gate_ceiling(tmp_path):
    from cell_policy_shape import source_rim_z

    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    lib_path = write_lib(tmp_path, lib)
    assert source_rim_z({"sites": {"belt": {"surface_z": 0.0, "rim_z": 0.15}}}, "belt", lib) == 0.15
    with pytest.raises(ValueError, match="rim_z"):
        source_rim_z({"sites": {"belt": {"surface_z": 0.1, "rim_z": 0.05}}}, "belt", lib)

    cell_low, rows_low = _grasp_cell([38.9, -55.0, 2.0, 55.0, 43.93, 49.0]), []
    res_low = drive.run_episode(
        cell_low, _grasp_policy(43.93, lift=-55.0), lib_path, tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows_low.append, kin=FakeKin(),
    )
    assert res_low["result"] == "chunks_done" and "run policy" in cell_low.commands

    cell_rim, rows_rim = _grasp_cell([38.9, -55.0, 2.0, 55.0, 43.93, 49.0]), []
    res_rim = drive.run_episode(
        cell_rim, _grasp_policy(43.93, lift=-55.0), lib_path, tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows_rim.append, kin=FakeKin(), rim_z_m=0.15,
    )
    assert res_rim["result"] == "refused" and "jaw yaw" in rows_rim[0]["jaw_warning"]
    assert "load" not in " ".join(cell_rim.commands) and "run policy" not in cell_rim.commands


def test_legacy_single_chunk_lift_then_rotate_refused_without_measured_clearance(tmp_path):
    cell, rows = _grasp_cell([38.9, -10.0, 2.0, 55.0, -14.0, 49.0]), []
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}
    chunk = [[38.9, -55.0, 2.0, 55.0, -14.0, 49.0], [38.9, -55.0, 2.0, 55.0, 43.93, 49.0]]
    res = drive.run_episode(
        cell, Policy([chunk]), write_lib(tmp_path, lib), tmp_path,
        offset=[0] * 6, max_chunks=1, dry_run=False, log=rows.append, kin=FakeKin(),
    )
    assert res["result"] == "refused" and cell.commands == ["state", "human-hold"]
    assert "jaw yaw" in rows[0]["jaw_warning"]


def test_legacy_jaw_refusal_sends_human_hold_before_log_failure(tmp_path):
    cell = _grasp_cell([38.9, -10.0, 2.0, 55.0, 43.93, 49.0])
    lib = {**LIB_GRASP, "chunks": {**LIB_GRASP["chunks"], "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]}}

    def fail_log(_row):
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        drive.run_episode(
            cell, _grasp_policy(43.93, timed=False), write_lib(tmp_path, lib), tmp_path,
            offset=[0] * 6, max_chunks=1, dry_run=False, log=fail_log, kin=FakeKin(),
        )
    assert cell.commands == ["state", "human-hold"]


def test_paced_chunks_flag_uses_guarded_loop_and_rejects_incompatible_modes(tmp_path, monkeypatch):
    import cell_pipeline

    root = tmp_path / "model"
    root.mkdir()
    (root / drive.lrs.WEIGHTS).write_bytes(b"pinned")
    (root / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 100, "chunk_size": 100,
        "input_features": {"observation.state": {"shape": [6]}, "observation.images.top": {"shape": [3, 4, 4]}},
        "output_features": {"action": {"shape": [6]}},
    }))
    import hashlib
    rev = hashlib.sha256(b"pinned").hexdigest()
    cell_cal = tmp_path / "cell_cal.json"
    cell_cal.write_text(json.dumps(cal()))
    config_path = tmp_path / "cell.json"
    config_path.write_text(json.dumps({"arm_id": "arm_s", "io": "unused", "cameras": {}, "work_dir": str(tmp_path)}))
    lib_path = write_lib(tmp_path)
    cell = Cell()
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: cell)

    class PacedPolicy:
        image_views = {"top": (4, 4)}
        goal_size = None
        sim_rule = None
        chunk_size = 100
        n_action_steps = 100
        files = {}

        def inputs(self, state, frames, **_):
            return {"observation.state": state}, {"model_frame_sha256": {}}

        def infer(self, obs, **_):
            return SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]] * 100)

    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: PacedPolicy())
    monkeypatch.setattr(drive, "demonstrated_range", lambda *a, **kw: ([0, -58, 30, 40, -5, 49], [20, -20, 51, 50, -5, 60]))
    seen = []
    orig_run_episode = drive.run_episode
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: (seen.append(kw.get("paced_chunks")) or {"result": "dry_run", "chunks": 1}))

    base = ["--config", str(config_path), "--library", str(lib_path), "--policy-root", str(root),
            "--policy-revision", rev, "--model-calibration", str(cell_cal), "--cell-calibration", str(cell_cal),
            "--operator", "livsbittt", "--max-chunks", "1", "--dry-run"]
    assert drive.main([*base, "--paced-chunks"]) == 0
    assert seen == [True]
    assert drive.main([*base, "--paced-chunks", "--n-action", "8"]) == 0
    with pytest.raises(SystemExit):
        drive.main([*base, "--paced-chunks", "--mode", "hybrid", "--goal-site", "tray"])
    with pytest.raises(SystemExit):
        drive.main([*base, "--paced-chunks", "--mode", "taught", "--goal-site", "tray"])
    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: SimPolicy([[[0] * 6] * 16]))
    assert drive.main([*base, "--paced-chunks", "--n-action", "4"]) == 0

    # Direct run_episode with paced_chunks=True bypasses run_timed and admits n_action; handoff still rejected.
    monkeypatch.setattr(drive, "run_episode", orig_run_episode)
    rows = []
    ep = drive.run_episode(cell, PacedPolicy(), lib_path, tmp_path, offset=[0] * 6,
                           max_chunks=1, dry_run=True, log=rows.append, paced_chunks=True, n_action=8)
    assert ep == {"result": "dry_run", "chunks": 1} and rows[0]["envelope"] == {"ok": True}

    with pytest.raises(ValueError, match="paced_chunks"):
        drive.run_episode(cell, PacedPolicy(), lib_path, tmp_path, offset=[0] * 6,
                          max_chunks=1, dry_run=True, log=rows.append, paced_chunks=True, handoff=object())

    # Checked failure recovery: chunk-0 authorize/load failures never send bare park; chunk-1 authorize failure parks with chunk-0 prefix.
    cell_auth = Cell()
    res_auth = drive.run_episode(
        cell_auth, Policy([[[5, -50, 45, 48, -5, 49.0]]]), write_lib(tmp_path), tmp_path, offset=[0] * 6,
        max_chunks=1, dry_run=False, log=[].append, paced_chunks=True,
        authorize=lambda *_a: (_ for _ in ()).throw(ValueError("operating envelope refused: start_not_home")),
    )
    assert res_auth["result"] == "refused" and res_auth["at"] == 0
    assert res_auth["reason"] == "operating envelope refused: start_not_home" and res_auth["parked"] is False
    assert cell_auth.commands == ["state", "state", "state"]

    class CheckedLoadFailCell(Cell):
        def act(self, command):
            self.commands.append(command)
            if " load " in command:
                return {"state": self.state, "ok": False, "error": "load_failed"}
            return {"command": command, "state": self.state, "ok": True, "settled": True, "holding": False}

    cell_load = CheckedLoadFailCell()
    res_load = drive.run_episode(
        cell_load, Policy([[[5, -50, 45, 48, -5, 49.0]]]), write_lib(tmp_path), tmp_path, offset=[0] * 6,
        max_chunks=1, dry_run=False, log=[].append, paced_chunks=True,
        authorize=lambda *_a: {"session_id": "s1", "library_sha256": "deadbeef"},
    )
    assert res_load["result"] == "refused" and res_load["at"] == 0
    assert res_load["reason"] == "load_failed" and res_load["parked"] is False
    assert cell_load.commands[:3] == ["state", "state", "state"] and " load " in cell_load.commands[3] and len(cell_load.commands) == 4

    auth_calls_2 = []

    def auth_chunk1_fail(*_a):
        auth_calls_2.append(len(auth_calls_2) + 1)
        if len(auth_calls_2) == 1:
            return {"session_id": "s1", "library_sha256": "sha1"}
        raise ValueError("operating envelope refused: drifted")

    cell_auth2 = Cell()
    res_auth2 = drive.run_episode(
        cell_auth2, Policy([[[5, -50, 45, 48, -5, 49.0]], [[5, -50, 45, 48, -5, 49.0]]]), write_lib(tmp_path), tmp_path, offset=[0] * 6,
        max_chunks=2, dry_run=False, log=[].append, paced_chunks=True, authorize=auth_chunk1_fail,
    )
    assert res_auth2["result"] == "refused" and res_auth2["at"] == 1
    assert res_auth2["reason"] == "operating envelope refused: drifted" and res_auth2["parked"] is True
    assert cell_auth2.commands[-1] == "checked s1 sha1 park" and "park" not in cell_auth2.commands

    # Pre-authorize state refresh passes post-inference timestamp, refuses faulted state, and latches human-hold on jaw drift.
    class RefreshAuthCell(Cell):
        def __init__(self, states, *, expected_chunks=None):
            super().__init__(expected_chunks=expected_chunks)
            self._states = list(states)

        def act(self, command):
            if command == "state":
                self.commands.append(command)
                reply = {"holding": False, "state": self.state, **self._states.pop(0)}
                self.state = list(reply["state"])
                return reply
            return super().act(command)

    import time as _t

    now = _t.time()
    t0, t1 = now - 0.01, now
    auth_seen_states = []
    cell_fresh = RefreshAuthCell([{"ok": True, "t": t0}, {"ok": True, "t": t0}, {"ok": True, "t": t1}])
    res_fresh = drive.run_episode(
        cell_fresh, Policy([[[5, -50, 45, 48, -5, 49.0]]]), write_lib(tmp_path), tmp_path, offset=[0] * 6,
        max_chunks=1, dry_run=False, log=[].append, paced_chunks=True,
        authorize=lambda _lib, st, _seq: (auth_seen_states.append(st) or {"session_id": "s1", "library_sha256": "deadbeef"}),
    )
    assert res_fresh["result"] == "chunks_done" and len(auth_seen_states) == 1 and auth_seen_states[0]["t"] == t1

    cell_refetch_fault = RefreshAuthCell([{"ok": True, "t": t0}, {"ok": True, "t": t0}, {"ok": False, "fault": "servo_err", "error": "servo_err"}])
    res_refetch_fault = drive.run_episode(
        cell_refetch_fault, Policy([[[5, -50, 45, 48, -5, 49.0]]]), write_lib(tmp_path), tmp_path, offset=[0] * 6,
        max_chunks=1, dry_run=False, log=[].append, paced_chunks=True,
        authorize=lambda *_a: pytest.fail("authorize must not run when refreshed state is faulted"),
    )
    assert res_refetch_fault["result"] == "fault" and res_refetch_fault["parked"] is False
    assert cell_refetch_fault.commands == ["state", "state", "state", "human-hold"]

    transit_pose = [38.9, -55.0, 2.0, 55.0, 43.93, 49.0]
    jaw_lib = write_lib(tmp_path, {
        **LIB_GRASP,
        "chunks": {**LIB_GRASP["chunks"], "home": [transit_pose] * 2,
                   "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]},
    })
    for drifted_pose in ([38.9, -10.0, 2.0, 55.0, 43.93, 49.0], [38.9, -10.0, 2.0, 55.0, 86.0, 49.0]):
        cell_drift = RefreshAuthCell(
            [{"ok": True, "state": list(transit_pose)}, {"ok": True, "state": list(transit_pose)}, {"ok": True, "state": list(drifted_pose)}],
            expected_chunks={"home", "reach", "grasp_pick", "policy"},
        )
        drift_rows = []
        res_drift = drive.run_episode(
            cell_drift, Policy([[[39.0, -55.0, 2.0, 55.0, 43.93, 49.0]]]), jaw_lib, tmp_path,
            offset=[0] * 6, max_chunks=1, dry_run=False, log=drift_rows.append, kin=FakeKin(), paced_chunks=True,
            authorize=lambda *_a: pytest.fail("authorize must not run when refreshed pose violates jaw gate"),
        )
        assert res_drift["result"] == "refused" and res_drift["parked"] is False
        assert "jaw yaw" in drift_rows[-2]["jaw_warning"]
        assert cell_drift.commands == ["state", "state", "state", "human-hold"]

    # Mid-loop exception during inference catches; chunk-0 refuses without park, chunk-1 tries park then human-hold.
    class CrashPolicy(PacedPolicy):
        def __init__(self, fail_at: int = 1):
            self.calls, self.fail_at = 0, fail_at

        def infer(self, obs, **_):
            self.calls += 1
            if self.calls >= self.fail_at:
                raise RuntimeError("cuda oom")
            return super().infer(obs)

    class ParkFailCell(Cell):
        def act(self, command):
            self.commands.append(command)
            if command.endswith("park"):
                return {"state": self.state, "ok": False, "settled": False, "error": "park_blocked"}
            extra = {"human_hold_latched": True, "torque_hold_commanded": True} if command == "human-hold" else {}
            return {"command": command, "state": self.state, "ok": True, "settled": True, "holding": False, **extra}

    cell_crash0 = ParkFailCell()
    res_crash0 = drive.run_episode(cell_crash0, CrashPolicy(fail_at=1), write_lib(tmp_path), tmp_path, offset=[0] * 6,
                                 max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert res_crash0["result"] == "refused" and "cuda oom" in res_crash0["reason"] and res_crash0["parked"] is False
    assert cell_crash0.commands == ["state", "state"]

    cell_crash = ParkFailCell()
    res_crash = drive.run_episode(cell_crash, CrashPolicy(fail_at=2), write_lib(tmp_path), tmp_path, offset=[0] * 6,
                                max_chunks=2, dry_run=False, log=[].append, paced_chunks=True)
    assert res_crash["result"] == "refused" and res_crash["at"] == 1 and "cuda oom" in res_crash["reason"] and res_crash["parked"] is False
    assert cell_crash.commands.count("run policy") == 1 and cell_crash.commands[-3:] == ["state", "park", "human-hold"]

    # Runner fault skips park and latches human-hold directly.
    cell_fault = Cell({"run policy": {"ok": False, "fault": "servo_err", "error": "servo_err"}})
    res_fault = drive.run_episode(cell_fault, Policy([[[5, -50, 45, 48, -5, 49.0]]]), write_lib(tmp_path), tmp_path,
                                offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert res_fault["result"] == "fault" and res_fault["parked"] is False
    assert cell_fault.commands[-1] == "human-hold" and "park" not in cell_fault.commands

    # Stale frame_receipt timestamp older than max_obs_age_s refuses before run policy without bare park on chunk 0.
    class StaleReceiptCell(Cell):
        def frame_receipt(self, view, **_kw):
            return {"image": np.zeros((4, 4, 3), np.uint8), "source_stamp": 0.0}

    cell_stale = StaleReceiptCell()
    res_stale = drive.run_episode(cell_stale, PacedPolicy(), write_lib(tmp_path), tmp_path, offset=[0] * 6,
                                max_chunks=1, dry_run=False, log=[].append, paced_chunks=True, max_obs_age_s=0.5)
    assert res_stale["result"] == "refused" and res_stale["reason"] == "stale policy observation"
    assert res_stale["parked"] is False and "park" not in cell_stale.commands and not any("run policy" in c for c in cell_stale.commands)


def test_chunk_runner_settle_updates_holding_for_policy_chunks():
    from chunk_runner_run import Runner
    from chunk_runner_settle import arm_queue_release, check_chunk_settled
    from omx_adapter.chunk_library import NAMES, SCHEMA

    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6]}}
    robot = SimpleNamespace(get_observation=lambda: dict(zip(NAMES, [0, 0, 0, 0, 0, 52.0])), send_action=lambda a: a)

    # Closed target + jaw held open by object waits for gripper_still then sets holding True.
    reports_hold = []
    r_hold = Runner(robot, lib, fps=30, status=reports_hold.append, clock=lambda: 0.5)
    r_hold.chunk, r_hold.queue, r_hold.target = "policy", [], [0, 0, 0, 0, 0, 46.6]
    r_hold.settle_since, r_hold.last_body = 0.0, [0, 0, 0, 0, 0]
    check_chunk_settled(r_hold, [0, 0, 0, 0, 0, 52.0], 0.0, 0.5, lambda _n, d: d)
    assert r_hold.chunk == "policy"  # last_grip was None: waits for still jaw feedback before settling
    check_chunk_settled(r_hold, [0, 0, 0, 0, 0, 52.0], 0.0, 0.55, lambda _n, d: d)
    assert r_hold.chunk is None and r_hold.holding is True and reports_hold[-1]["holding"] is True

    # Closed target + empty closed jaw -> holding False.
    reports_empty = []
    r_empty = Runner(robot, lib, fps=30, status=reports_empty.append, clock=lambda: 0.5)
    r_empty.chunk, r_empty.queue, r_empty.target = "policy", [], [0, 0, 0, 0, 0, 46.6]
    r_empty.settle_since, r_empty.last_body, r_empty.last_grip = 0.0, [0, 0, 0, 0, 0], 46.8
    check_chunk_settled(r_empty, [0, 0, 0, 0, 0, 46.8], 0.0, 0.5, lambda _n, d: d)
    assert r_empty.holding is False and reports_empty[-1]["holding"] is False

    # Open release trajectory via arm_queue_release -> clears holding cleanly without disturbing closed-hold jaw_gate chunks.
    reports_open = []
    r_open = Runner(robot, lib, fps=30, status=reports_open.append, clock=lambda: 0.5)
    r_open.holding, r_open.target = True, [0, 0, 0, 0, 0, 46.6]
    assert arm_queue_release(r_open, [[0, 0, 0, 0, 0, 75.0]]) is True
    assert r_open.holding is False
    r_open.chunk, r_open.queue, r_open.target = "policy", [], [0, 0, 0, 0, 0, 75.0]
    r_open.settle_since, r_open.last_body = 0.0, [0, 0, 0, 0, 0]
    check_chunk_settled(r_open, [0, 0, 0, 0, 0, 75.0], 0.0, 0.5, lambda _n, d: d)
    assert r_open.holding is False


def test_empty_jaw_overclose_floor_prevents_false_hold_without_weakening_real_hold():
    from chunk_runner_run import Runner
    from chunk_runner_settle import check_chunk_settled, confirm_grip_release
    from omx_adapter.chunk_library import NAMES, SCHEMA

    def _sent(grip: float) -> dict[str, float]:
        return {**dict.fromkeys(NAMES, 0.0), "gripper.pos": grip}

    # 1: Empty over-closed jaw (sent 46.52, physical stop 48.864, gripper_closed 48.5) must not latch _held_jaw or false hold.
    lib_arm_s = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 48.5, "chunks": {"home": [[0] * 6]}}
    reports_empty = []
    r_empty = Runner(SimpleNamespace(get_observation=lambda: dict(zip(NAMES, [0, 0, 0, 0, 0, 48.864])), send_action=lambda a: a),
                     lib_arm_s, fps=30, status=reports_empty.append, clock=lambda: 0.5)
    r_empty.chunk, r_empty.queue, r_empty.target = "policy", [[0, 0, 0, 0, 0, 48.62]], [0, 0, 0, 0, 0, 46.71]
    r_empty._fresh_present = True
    confirm_grip_release(r_empty, _sent(46.52), [0, 0, 0, 0, 0, 48.864], committed=True, empty_margin=2.0)
    assert r_empty._held_jaw is None
    confirm_grip_release(r_empty, _sent(46.545), [0, 0, 0, 0, 0, 48.864], committed=True, empty_margin=2.0)
    assert r_empty._release_until is None and r_empty._release_floor is None
    r_empty.queue, r_empty.settle_since, r_empty.last_body, r_empty.last_grip = [], 0.0, [0, 0, 0, 0, 0], 48.864
    check_chunk_settled(r_empty, [0, 0, 0, 0, 0, 48.864], 0.0, 0.5, lambda _n, d: d)
    assert r_empty.holding is False and reports_empty[-1]["ok"] is True and reports_empty[-1]["holding"] is False

    # 2: Same over-closed command while genuinely holding an object (55.0 > 48.5 + 2.0) must still arm release floor & hold.
    reports_held = []
    r_held = Runner(SimpleNamespace(get_observation=lambda: dict(zip(NAMES, [0, 0, 0, 0, 0, 55.0])), send_action=lambda a: a),
                    lib_arm_s, fps=30, status=reports_held.append, clock=lambda: 0.5)
    r_held.chunk, r_held.queue, r_held.target = "policy", [[0, 0, 0, 0, 0, 48.62]], [0, 0, 0, 0, 0, 46.71]
    r_held._fresh_present = True
    confirm_grip_release(r_held, _sent(46.52), [0, 0, 0, 0, 0, 55.0], committed=True, empty_margin=2.0)
    assert r_held._held_jaw == pytest.approx(55.0)
    confirm_grip_release(r_held, _sent(46.545), [0, 0, 0, 0, 0, 55.0], committed=True, empty_margin=2.0)
    assert r_held._release_until == pytest.approx(48.62) and r_held._release_floor >= 57.0
    r_held.queue, r_held.settle_since, r_held.last_body, r_held.last_grip = [], 0.0, [0, 0, 0, 0, 0], 55.0
    check_chunk_settled(r_held, [0, 0, 0, 0, 0, 55.0], 0.0, 0.5, lambda _n, d: d)
    assert reports_held[-1]["ok"] is False and reports_held[-1]["holding"] is True

    # 3: Explicit jaw_empty_stop > gripper_closed (48.5 > 46.5) blocks false hold at 48.9 and preserves genuine hold at 51.0.
    lib_stop = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.5, "jaw_empty_stop": 48.5, "chunks": {"home": [[0] * 6]}}
    for present_g, want_held in ((48.9, False), (51.0, True)):
        reports_s = []
        rs = Runner(SimpleNamespace(get_observation=lambda g=present_g: dict(zip(NAMES, [0, 0, 0, 0, 0, g])), send_action=lambda a: a),
                    lib_stop, fps=30, status=reports_s.append, clock=lambda: 0.5)
        rs.chunk, rs.queue, rs.target = "policy", [], [0, 0, 0, 0, 0, 46.5]
        rs._fresh_present = True
        confirm_grip_release(rs, _sent(46.5), [0, 0, 0, 0, 0, present_g], committed=True, empty_margin=2.0)
        assert (rs._held_jaw is not None) is want_held
        rs.settle_since, rs.last_body, rs.last_grip = 0.0, [0, 0, 0, 0, 0], present_g
        check_chunk_settled(rs, [0, 0, 0, 0, 0, present_g], 0.0, 0.5, lambda _n, d: d)
        assert rs.holding is want_held and reports_s[-1]["holding"] is want_held

    # 4: Partial/None library on non-policy chunks and huge int jaw_empty_stop never crash; policy chunks still fail closed.
    for mock_lib in (None, {"chunks": {"home": [[0] * 6]}}):
        r_mock = SimpleNamespace(
            library=mock_lib, human_hold_latched=False, _fresh_present=True, chunk="park", queue=[],
            target=[0, 0, 0, 0, 0, 48.0], settle_since=0.0, last_grip=48.0, last_body=[0, 0, 0, 0, 0],
            jitter={"shaking": False}, paced_ticks=0, pace_floor=0.0, peak_lag=0.0, over_ticks=0,
            damped_ticks=0, holding=False, fault=None, read_health=lambda: None, status=lambda _r: None,
            report=lambda **_kw: None,
        )
        confirm_grip_release(r_mock, _sent(48.0), [0, 0, 0, 0, 0, 48.0], committed=True, empty_margin=2.0)
        assert r_mock._held_jaw is None
        if isinstance(mock_lib, dict):
            check_chunk_settled(r_mock, [0, 0, 0, 0, 0, 48.0], 0.0, 0.5, lambda _n, d: d)
            assert r_mock.chunk is None and r_mock.holding is False

    lib_huge = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 48.5, "jaw_empty_stop": 10**400, "chunks": {"home": [[0] * 6]}}
    r_huge = Runner(SimpleNamespace(get_observation=lambda: dict(zip(NAMES, [0, 0, 0, 0, 0, 48.864])), send_action=lambda a: a),
                    lib_huge, fps=30, status=[].append, clock=lambda: 0.5)
    r_huge.chunk, r_huge.queue, r_huge.target, r_huge._fresh_present = "policy", [], [0, 0, 0, 0, 0, 46.5], True
    confirm_grip_release(r_huge, _sent(46.5), [0, 0, 0, 0, 0, 48.864], committed=True, empty_margin=2.0)
    assert r_huge._held_jaw is None

    r_bad_policy = Runner(SimpleNamespace(get_observation=lambda: dict(zip(NAMES, [0, 0, 0, 0, 0, 49.0])), send_action=lambda a: a),
                          {"chunks": {"home": [[0] * 6]}}, fps=30, status=[].append, clock=lambda: 0.5)
    r_bad_policy.chunk, r_bad_policy.queue, r_bad_policy.target = "policy", [], [0, 0, 0, 0, 0, 48.0]
    with pytest.raises(ValueError, match="invalid gripper_closed"):
        check_chunk_settled(r_bad_policy, [0, 0, 0, 0, 0, 49.0], 0.0, 0.5, lambda _n, d: d)


def test_paced_pre_home_settles_sagged_start_or_fails_closed(tmp_path, monkeypatch):
    import cell_policy_handoff as handoff
    import cell_policy_paced as paced

    clock_t = [100.0]
    monkeypatch.setattr(paced.time, "time", lambda: clock_t[0])
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    lib_path = write_lib(tmp_path)
    good_pose = [0, -58, 51, 50, -5, 49]
    sagged_pose = [0, -58, 54.97, 50, -5, 49]
    chunk = [[5, -50, 45, 48, -5, 49]] * 100

    class PreHomeCell:
        def __init__(self, pose, *, holding=False, current_ma=0, second_state=None, post_fault=None, cam_wait_s=0.0):
            self.state, self.holding, self.current_ma = list(pose), holding, current_ma
            self.second_state, self.post_fault, self.cam_wait_s = second_state, post_fault, cam_wait_s
            self.events = []

        def frame_receipt(self, view, **_kw):
            clock_t[0] += self.cam_wait_s
            self.events.append(f"frame:{view}")
            return {"image": np.zeros((4, 4, 3), np.uint8), "source_stamp": clock_t[0]}

        def act(self, cmd):
            self.events.append(cmd)
            if cmd == "state":
                pose_now = list(self.second_state if self.second_state is not None and self.events.count("state") >= 2 else self.state)
                res = {"command": "state", "ok": True, "state": pose_now, "t": clock_t[0],
                       "health": {"current_ma": [0] * 5 + [self.current_ma]}}
                if self.holding is not None:
                    res["holding"] = self.holding
                if self.post_fault and len(self.events) > 1:
                    res["fault"] = self.post_fault
                return res
            if cmd == "human-hold":
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
            base = cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd
            return {"command": base, "ok": True, "settled": True, "holding": False, "state": list(self.state)}

    pres_chunk = [list(sagged_pose), [0, -58, 53.0, 50, -5, 49], list(LIB["chunks"]["home"][-1])]
    (tmp_path / "ev_lib").mkdir()
    ev_lib_path = write_lib(tmp_path / "ev_lib", {**LIB, "chunks": {**LIB["chunks"], "presettle": pres_chunk}})

    # Already on home: stationary verified with two state reads + pre-dispatch state check, 0 pre-settle motion.
    c_home = PreHomeCell(good_pose, cam_wait_s=0.1)
    r_home = drive.run_episode(c_home, Policy([chunk]), lib_path, tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert r_home["result"] == "chunks_done" and not any("presettle" in e for e in c_home.events) and c_home.events.count("park") == 1

    # Sagged and extended off-home starts — even with `presettle` chunk and verified authorize — fail closed with confirmed HOLD (run home stage first).
    seen_auth = []
    for lp, pose in ((lib_path, sagged_pose), (ev_lib_path, sagged_pose), (ev_lib_path, [0, -58, 65.0, 50, -5, 49])):
        c_off = PreHomeCell(pose)
        r_off = drive.run_episode(
            c_off, Policy([chunk]), lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append,
            authorize=lambda *_a, **_kw: seen_auth.append(_a), paced_chunks=True,
        )
        assert r_off["result"] == "refused" and r_off["parked"] is False and "run home stage first" in r_off["reason"]
        assert c_off.events == ["state", "human-hold"] and not seen_auth

    # Real Authorization passes check_home=False through to cell_envelope.assess.
    import cell_envelope
    import cell_pipeline_io
    cal_path = tmp_path / "cal.json"
    cal_path.write_text("{}")
    assess_calls = []
    with monkeypatch.context() as mp:
        mp.setattr(cell_pipeline_io, "limit_error", lambda *_a, **_kw: None)
        mp.setattr(cell_envelope, "assess", lambda *a, **kw: (assess_calls.append(kw), {"allowed": True, "session_id": "s", "library_sha256": "x"})[1])
        handoff.Authorization({"calibration_path": str(cal_path)})(LIB, {"state": sagged_pose}, ("park",), check_home=False)
    assert assess_calls[-1]["check_home"] is False

    # Missing home, non-stationary drift, holding True/None, high gripper current, and post-check fault ALL send confirmed human-hold before capture.
    no_home_lib = tmp_path / "no-home.json"
    no_home_lib.write_text(json.dumps({**LIB, "chunks": {"reach": LIB["chunks"]["reach"]}}))
    r_no_home = drive.run_episode(c_nh := PreHomeCell(good_pose), Policy([chunk]), no_home_lib, tmp_path,
                                  offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert r_no_home["result"] == "refused" and "missing home" in r_no_home["reason"] and c_nh.events == ["state", "human-hold"]

    for kw in (
        {"second_state": [0, -58, 51.35, 50, -5, 49]},
        {"holding": True}, {"holding": None}, {"current_ma": 150}, {"post_fault": "motor_err"},
    ):
        c_hh = PreHomeCell(good_pose, **kw)
        r_hh = drive.run_episode(c_hh, Policy([chunk]), lib_path, tmp_path, offset=[0] * 6,
                                 max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert r_hh["result"] in ("refused", "fault") and c_hh.events[-1] == "human-hold"
        assert not any("load " in e or "run policy" in e or e.startswith("frame:") for e in c_hh.events)

    # Dry run skips start-home verification and HOLD.
    c_dry = PreHomeCell(sagged_pose)
    assert drive.run_episode(c_dry, Policy([chunk]), ev_lib_path, tmp_path, offset=[0] * 6,
                             max_chunks=1, dry_run=True, log=[].append, paced_chunks=True) == {"result": "dry_run", "chunks": 1}
    assert c_dry.events[0] == "state" and "human-hold" not in c_dry.events

    # Start-home jaw_zone_error refuses + sends confirmed human-hold BEFORE capture or load.
    bad_jaw_home = [38.9, -26.0, 2.0, 55.0, 43.93, 49.0]
    jaw_lib = write_lib(tmp_path, {
        **LIB_GRASP,
        "chunks": {**LIB_GRASP["chunks"], "home": [bad_jaw_home] * 2,
                   "reach": [[0, -58, 2, 40, -20, 49], [40, -10, 51, 55, 90, 60]]},
    })
    c_jaw = PreHomeCell(bad_jaw_home)
    r_jaw = drive.run_episode(c_jaw, Policy([chunk]), jaw_lib, tmp_path, offset=[0] * 6,
                              max_chunks=1, dry_run=False, log=[].append, kin=FakeKin(), paced_chunks=True)
    assert r_jaw["result"] == "refused" and "jaw" in r_jaw["reason"] and c_jaw.events == ["state", "human-hold"]


def test_paced_stops_on_unsettled_chunk_and_invalid_stamps(tmp_path):
    import time as _t

    lib_path = write_lib(tmp_path)
    chunk = [[5, -50, 45, 48, -5, 49]] * 100
    c_unsettled = Cell({"run policy": {"ok": True, "settled": False}})
    r_unsettled = drive.run_episode(c_unsettled, Policy([chunk, chunk]), lib_path, tmp_path, offset=[0] * 6,
                                    max_chunks=2, dry_run=False, log=[].append, paced_chunks=True)
    assert r_unsettled["result"] == "unsettled" and r_unsettled["at"] == 0
    assert c_unsettled.commands.count("run policy") == 1 and c_unsettled.commands[-1] == "human-hold" and "park" not in c_unsettled.commands

    class BadReceiptCell(Cell):
        def __init__(self, *, cam_stamp=None, state_t=_t.time()):
            super().__init__()
            self.cam_stamp, self.state_t = cam_stamp, state_t

        def frame_receipt(self, _view, **_kw):
            return {"image": np.zeros((4, 4, 3), np.uint8), **({"source_stamp": self.cam_stamp} if self.cam_stamp is not None else {})}

        def act(self, command):
            res = super().act(command)
            if command == "state":
                res["t"] = self.state_t
            return res

    now = _t.time()
    for bad in (None, float("nan"), float("inf"), True, now + 5.0):
        c_cam = BadReceiptCell(cam_stamp=bad, state_t=now)
        r_cam = drive.run_episode(c_cam, Policy([chunk]), lib_path, tmp_path, offset=[0] * 6,
                                  max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert r_cam["result"] == "refused" and "camera stamp" in r_cam["reason"] and "run policy" not in c_cam.commands

    for bad_state_t in (float("nan"), float("inf"), True, now + 5.0):
        c_st = BadReceiptCell(cam_stamp=now, state_t=bad_state_t)
        r_st = drive.run_episode(c_st, Policy([chunk]), lib_path, tmp_path, offset=[0] * 6,
                                 max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert r_st["result"] == "refused" and "state stamp" in r_st["reason"] and "run policy" not in c_st.commands

    # dry_run tolerates invalid stamps without failing or loading.
    assert drive.run_episode(BadReceiptCell(cam_stamp=None, state_t=float("nan")), Policy([chunk]), lib_path, tmp_path,
                             offset=[0] * 6, max_chunks=1, dry_run=True, log=[].append, paced_chunks=True) == {"result": "dry_run", "chunks": 1}


def test_r22_paced_contact_during_unconfirmed_release_holds_and_owner_refuses_retreat(tmp_path):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES as OMX_NAMES, SCHEMA

    home, rep = list(LIB["chunks"]["home"][0]), []
    lib_r = {"schema": SCHEMA, "names": OMX_NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {**LIB["chunks"], "policy": [home]}}
    r = Runner(SimpleNamespace(send_action=lambda _a: None, get_observation=lambda: dict(zip(OMX_NAMES, home))),
               lib_r, fps=30, status=rep.append, clock=lambda: 1.0)
    r.holding, r._release_until, r.chunk, r.target = True, 75.0, "policy", list(home)
    r.played = [list(home), [1.0, -58.0, 51.0, 50.0, -5.0, 49.0]]
    r.hold(list(home), "contact in policy: lag", human=False)
    owner_contact = rep[-1]
    assert owner_contact["contact"] is True and owner_contact["ok"] is False and owner_contact["holding"] is True and r._release_until == 75.0
    assert r.command("retreat") is True and rep[-1]["ok"] is False and "unconfirmed" in rep[-1]["error"] and not r.queue

    cell = Cell({"run policy": owner_contact})
    res = drive.run_episode(cell, Policy([[home] * 8]), write_lib(tmp_path), tmp_path,
                            offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert res["result"] == "contact" and res["parked"] is False
    assert cell.commands[cell.commands.index("run policy") + 1:] == ["human-hold"]


def test_arm_b_wrist_roll_warning_allows_unfolded_transit_in_range():
    from cell_policy_shape import wrist_roll_warning

    assert wrist_roll_warning([[0.0, -20.0, 20.0, 45.0, 17.0, 55.0]], 45.2, roll_range=(-35.0, 45.2)) is None
    assert "wrist_roll" in (wrist_roll_warning([[0.0, -55.0, 46.5, 49.0, -5.0, 55.0]], 45.2, roll_range=(-35.0, 45.2)) or "")
    assert "wrist_roll" in (wrist_roll_warning([[0.0, -45.0, 48.0, 49.0, -5.0, 55.0]], 45.2, roll_range=(-35.0, 45.2)) or "")
    assert "wrist_roll" in (wrist_roll_warning([[0.0, -20.0, 20.0, 45.0, 17.0, 55.0]], 45.2, roll_range=(25.0, 45.2)) or "")


def test_paced_sim_entry_bridge_dry_and_live_execution(tmp_path):
    home = [0.8, -62.2, 53.1, 51.6, 45.2, 48.8]
    canon = [6.0, -55.0, 46.5, 49.0, 40.0, 55.78]
    lib_entry = {
        "fps": 30, "gripper_closed": 48.8,
        "chunks": {
            "home": [home],
            "entry": [home, [0.8, -55.0, 46.5, 49.0, 45.2, 48.8], canon],
            "reach": [[0.8, -62.2, 53.1, 51.6, 45.2, 48.8], [1.0, -62.17, 53.07, 51.57, 45.17, 48.8],
                      [25.0, 18.0, 5.0, 25.0, -35.0, 57.5]],
        },
    }
    lib_path = write_lib(tmp_path, lib_entry)

    class EntryCell(Cell):
        def __init__(self):
            super().__init__(expected_chunks={"home", "entry", "reach"} | {"policy"})
            self.state = list(home)
            self.target = list(home)
            self._checked_reads = 0

        def act(self, command):
            self.commands.append(command)
            if command.startswith("load "):
                return {"state": list(self.state), "command": "load", "ok": True, "settled": True, "holding": False}
            base = command.split(" ", 3)[-1] if command.startswith("checked ") else command
            if base == "state":
                return {"state": list(self.state), "target": list(self.target), "command": "state", "ok": True, "settled": True, "holding": False, "health": {"current_ma": [0] * 6}}
            if base == "run entry":
                self.state, self.target = list(canon), list(canon)
            elif base == "run policy":
                self.state = [8.0, -40.0, 35.0, 45.0, 15.0, 55.8]
                self.target = list(self.state)
            elif base == "park":
                self.state, self.target = list(home), list(home)
            extra = {"human_hold_latched": True, "torque_hold_commanded": True} if base == "human-hold" else {}
            return {"state": list(self.state), "target": list(self.target), "command": base, "ok": True, "settled": True, "holding": False, **extra}

    c0_chunk = [[8.0, -40.0, 35.0, 45.0, 15.0, 55.8]] * 16
    c1_chunk = [[12.0, -25.0, 20.0, 40.0, -10.0, 55.8]] * 16
    dry_pol, dry_rows = SimPolicy([c0_chunk, c1_chunk]), []
    dry_res = drive.run_episode(EntryCell(), dry_pol, lib_path, tmp_path, offset=[0] * 6,
                                max_chunks=2, dry_run=True, log=dry_rows.append, paced_chunks=True, n_action=4)
    assert dry_res == {"result": "dry_run", "chunks": 2} and dry_rows[0]["entry_pose"] == canon
    assert dry_pol.seen[0] == canon and dry_pol.seen[1][0] == pytest.approx(8.0) and all(r["envelope"]["ok"] for r in dry_rows)

    no_runner = Cell({"state": {"ok": False, "fault": "no runner", "error": "chunk_runner is not running"}})
    nr_dry = drive.run_episode(no_runner, SimPolicy([c0_chunk]), lib_path, tmp_path, offset=[0] * 6,
                               max_chunks=1, dry_run=True, log=[].append, paced_chunks=True, n_action=4)
    assert nr_dry == {"result": "dry_run", "chunks": 1}
    nr_live = drive.run_episode(no_runner, SimPolicy([c0_chunk]), lib_path, tmp_path, offset=[0] * 6,
                                max_chunks=1, dry_run=False, log=[].append, paced_chunks=True, n_action=4)
    assert nr_live["result"] == "fault" and "not running" in nr_live["reason"]

    auth_checks = []

    class Auth:
        supports_check_home = True

        def __call__(self, _lib, _st, seq, *, check_home=True):
            auth_checks.append((seq, check_home))
            return {"session_id": f"s{len(auth_checks)}", "library_sha256": f"h{len(auth_checks)}"}

    live_cell = EntryCell()
    live_res = drive.run_episode(live_cell, SimPolicy([c0_chunk]), lib_path, tmp_path, offset=[0] * 6,
                                 max_chunks=1, dry_run=False, log=[].append, authorize=Auth(), paced_chunks=True, n_action=4)
    assert live_res["result"] == "chunks_done" and live_res["parked"] is True
    assert auth_checks == [(("run entry", "park"), True), (("run policy", "park"), False)]
    assert live_cell.commands[-1] == "checked s2 h2 park" and "checked s1 h1 run entry" in live_cell.commands

    fail_cell = EntryCell()

    def auth_fail_policy(_lib, _st, seq, *, check_home=True):
        if seq == ("run entry", "park"):
            return {"session_id": "se", "library_sha256": "he"}
        raise ValueError("operating envelope refused: test")

    auth_fail_policy.supports_check_home = True
    fail_res = drive.run_episode(fail_cell, SimPolicy([c0_chunk]), lib_path, tmp_path, offset=[0] * 6,
                                 max_chunks=1, dry_run=False, log=[].append, authorize=auth_fail_policy, paced_chunks=True, n_action=4)
    assert fail_res["result"] == "refused" and fail_res["parked"] is True
    assert fail_cell.commands[-1] == "checked se he park"


def test_remote_endpoint_cli_wiring_and_validation(tmp_path, monkeypatch):
    import cell_pipeline
    import cell_remote_policy as crp

    tok = tmp_path / "remote.tok"
    tok.write_text("x" * 32, encoding="utf-8")
    tok.chmod(0o600)
    cal_path = tmp_path / "cal.json"
    cal_path.write_text(json.dumps(cal()))
    cfg = tmp_path / "cell.json"
    cfg.write_text(json.dumps({"arm_id": "arm_b", "io": "unused", "cameras": {}, "work_dir": str(tmp_path)}))
    lib_path = write_lib(tmp_path)
    pdir = tmp_path / "m"
    pdir.mkdir()
    created, closed = [], []

    class FakeRemote:
        image_views = {"top": (4, 4), "wrist": (4, 4)}
        goal_size = 10
        sim_rule = {"held_30mm": 53.4, "gap_mm_per_unit": 5.0}
        chunk_size = 16
        n_action_steps = 4
        arm_id = "arm_b"
        files = {}

        def __init__(self, url, arm_id, rev, **kw):
            created.append((url, arm_id, rev, kw))

        def close(self):
            closed.append(True)

    monkeypatch.setattr(crp, "RemotePolicyShadow", FakeRemote)
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: Cell())
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: {"result": "dry_run", "chunks": 1})
    rc = drive.main([
        "--config", str(cfg), "--library", str(lib_path), "--policy-root", str(pdir),
        "--policy-revision", "a" * 64, "--cell-calibration", str(cal_path), "--endpoint-url", "http://10.0.0.2:8790",
        "--token-file", str(tok), "--goal-slot", "4", "--operator", "op_b", "--paced-chunks", "--max-chunks", "1", "--dry-run",
    ])
    assert rc == 0 and created[0][:3] == ("http://10.0.0.2:8790", "arm_b", "a" * 64) and created[0][3]["token"] == "x" * 32 and closed == [True]
    with pytest.raises(SystemExit):
        drive.main(["--config", str(cfg), "--library", str(lib_path), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op_b", "--endpoint-url", "http://127.0.0.1:8790", "--dry-run"])
    with pytest.raises(SystemExit):
        drive.main(["--config", str(cfg), "--library", str(lib_path), "--policy-root", str(pdir),
                    "--policy-revision", "a" * 64, "--cell-calibration", str(cal_path), "--model-calibration", str(cal_path),
                    "--token-file", str(tok), "--operator", "op_b", "--dry-run"])
    with pytest.raises(SystemExit):
        drive.main(["--config", str(cfg), "--library", str(lib_path), "--policy-root", str(pdir),
                    "--policy-revision", "a" * 64, "--cell-calibration", str(cal_path), "--endpoint-url", "http://10.0.0.2:8790",
                    "--token-file", str(tok), "--arm-id", "arm_a", "--goal-slot", "4", "--operator", "op_b",
                    "--paced-chunks", "--max-chunks", "1", "--dry-run"])
    prof_b = tmp_path / "arm-b-robot-profile.json"
    prof_b.write_text(json.dumps({
        "schema": "rosy.omx-cell-robot-profile.v1", "device_id": "arm_b", "instance_id": "arm_b_follower",
        "robot_config_sha256": "a" * 64, "operating_envelope_path": str(tmp_path / "env.json"), "work_dir": str(tmp_path),
    }))
    cfg_prof = tmp_path / "cell-prof.json"
    cfg_prof.write_text(json.dumps({"arm_id": "arm_b", "operating_profile_path": str(prof_b), "io": "unused", "cameras": {}}))
    created.clear()
    rc_prof = drive.main([
        "--config", str(cfg_prof), "--library", str(lib_path), "--policy-root", str(pdir),
        "--policy-revision", "a" * 64, "--cell-calibration", str(cal_path), "--endpoint-url", "http://10.0.0.2:8790",
        "--token-file", str(tok), "--goal-slot", "4", "--operator", "op_b", "--paced-chunks", "--max-chunks", "1", "--dry-run",
    ])
    assert rc_prof == 0 and created[0][1] == "arm_b"
    prof_a = tmp_path / "arm-a-robot-profile.json"
    prof_a.write_text(json.dumps({
        "schema": "rosy.omx-cell-robot-profile.v1", "device_id": "arm_a", "instance_id": "omx_follower_arm",
        "robot_config_sha256": "a" * 64, "operating_envelope_path": str(tmp_path / "env.json"), "work_dir": str(tmp_path),
    }))
    cfg_prof.write_text(json.dumps({"arm_id": "arm_b", "operating_profile_path": str(prof_a), "io": "unused", "cameras": {}}))
    with pytest.raises(SystemExit):
        drive.main([
            "--config", str(cfg_prof), "--library", str(lib_path), "--policy-root", str(pdir),
            "--policy-revision", "a" * 64, "--cell-calibration", str(cal_path), "--endpoint-url", "http://10.0.0.2:8790",
            "--token-file", str(tok), "--goal-slot", "4", "--operator", "op_b", "--paced-chunks", "--max-chunks", "1", "--dry-run",
        ])


def test_live_local_cpu_act_sets_nice_and_thread_env(tmp_path, monkeypatch):
    import cell_pipeline
    import cell_policy_handoff
    import os

    cal_path = tmp_path / "cal.json"
    cal_path.write_text(json.dumps(cal()))
    cfg = tmp_path / "cell.json"
    cfg.write_text(json.dumps({"arm_id": "arm_b", "io": "unused", "cameras": {}, "work_dir": str(tmp_path)}))
    lib_path = write_lib(tmp_path)
    pdir = tmp_path / "m"
    pdir.mkdir()

    class FakeShadow:
        image_views = {"top": (4, 4)}
        goal_size = 10
        sim_rule = {"held_30mm": 53.4, "gap_mm_per_unit": 5.0}
        chunk_size = 16
        n_action_steps = 4
        arm_id = "arm_b"
        files = {}

    nice_calls = []
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(drive.os, "nice", lambda inc: nice_calls.append(inc), raising=False)
    monkeypatch.setattr(drive, "open_policy_shadow", lambda *a, **kw: FakeShadow())
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: Cell())
    monkeypatch.setattr(cell_policy_handoff, "Authorization", lambda _cfg: None)
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: {"result": "chunks_done", "parked": True, "chunks": 1})
    import cell_policy_preflight
    monkeypatch.setattr(cell_policy_preflight, "preflight", lambda *a, **kw: None)  # this test is about nice/threads

    common = ["--config", str(cfg), "--library", str(lib_path), "--policy-root", str(pdir),
              "--policy-revision", "a" * 64, "--cell-calibration", str(cal_path), "--goal-slot", "4",
              "--operator", "op_b", "--paced-chunks", "--max-chunks", "1"]
    assert drive.main([*common, "--dry-run"]) == 0 and nice_calls == []
    assert drive.main([*common, "--person-at-switch"]) == 0 and nice_calls == [10]
    assert all(os.environ[v] == "2" for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"))
