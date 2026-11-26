"""Policy start gate (2026-11-26): folded poses are not gated, the entry end and later states must be trained states."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_policy_drive import Cell, SimPolicy, drive, write_lib  # noqa: E402
import cell_policy_start_gate as sg  # noqa: E402

REAL = json.loads((Path(__file__).parent / "fixtures/omx_policy_state_range_20261126.json").read_text())
HOME, ENTRY_MID = [0.8, -62.2, 53.1, 51.6, 45.2, 48.8], [0.8, -55.0, 46.5, 49.0, 45.2, 48.8]
CANON = [6.0, -55.0, 46.5, 49.0, 40.0, 55.78]


def real_gate(arm, monkeypatch, jaw):
    import cell_act_inputs

    monkeypatch.setattr(cell_act_inputs, "sim_gripper", lambda *_: jaw)
    stats = {k: np.asarray(v) for k, v in REAL["stats"][f"arm_{arm}"].items()}
    return sg.StateGate(stats, arm_id=f"arm_{arm}", sim_rule={"held_30mm": 50.0, "gap_mm_per_unit": 1.0})


def test_real_inputs_folded_not_gated_entry_end_passes_and_roll_minus_47_refused(monkeypatch):
    n = REAL["native"]
    gate = real_gate("b", monkeypatch, REAL["model_gripper"]["entry_end"])
    assert gate.roll_error(n["park"]) is None and gate.roll_error(n["entry_start"]) is None  # folded B is trained on roll
    assert gate.verdict(n["entry_end"], after_entry=True) is None
    assert "wrist_roll" in gate.roll_error(n["b_roll_minus_47"]) and sg.START_CODE in gate.roll_error(n["b_roll_minus_47"])
    assert gate.verdict(n["b_roll_minus_47"], after_entry=False).startswith(sg.RANGE_CODE)
    a_gate = real_gate("a", monkeypatch, REAL["model_gripper"]["entry_end"])  # the folded park is outside arm_a's trained range
    assert a_gate.verdict(n["park"], after_entry=False).startswith(sg.RANGE_CODE)
    assert a_gate.verdict([4.0, *n["entry_end"][1:]], after_entry=True) is None  # arm_a's canonical pan is 4.0, arm_b's 6.0


def test_start_pose_must_match_the_canonical_start(monkeypatch):
    gate = real_gate("b", monkeypatch, REAL["model_gripper"]["entry_end"])
    near = [6.0 + 0.9, *CANON[1:]]  # 0.9 units = 0.028 rad
    assert gate.verdict(near, after_entry=True) is None
    far = [6.0 + 1.5, *CANON[1:]]  # 0.046 rad: past start_jitter_rad
    assert gate.verdict(far, after_entry=True).startswith(sg.START_CODE)
    assert gate.verdict(far, after_entry=False) is None  # later chunks only need the trained range


def test_library_entry_end_must_be_the_canonical_start(tmp_path):
    lib = {"chunks": {"home": [HOME], "entry": [HOME, ENTRY_MID, CANON]}}
    assert sg.library_entry_error(lib, "arm_b") is None
    lib["chunks"]["entry"][-1] = [8.0, *CANON[1:]]
    assert sg.START_CODE in sg.library_entry_error(lib, "arm_b")
    assert sg.library_entry_error(lib, "arm_s") is None  # no canonical start for this arm
    with pytest.raises(ValueError, match=sg.START_CODE):
        sg.build_gate(tmp_path, lib, SimpleShadow(), [0] * 6)


class SimpleShadow:
    arm_id, sim_rule = "arm_b", {"held_30mm": 50.0, "gap_mm_per_unit": 1.0}


def test_margin_configuration_only_tightens(monkeypatch):
    gate = real_gate("b", monkeypatch, 0.5)
    assert sg.StateGate(gate.stats, arm_id="arm_b", sim_rule=gate.sim_rule, margin=1.0).margin == sg.MARGIN_RAD
    assert sg.StateGate(gate.stats, arm_id="arm_b", sim_rule=gate.sim_rule, margin=0.01).margin == 0.01


def test_state_range_is_read_from_the_checkpoint_statistics(tmp_path):
    save_file = pytest.importorskip("safetensors.numpy").save_file
    save_file({f"observation.state.{k}": np.asarray(v, dtype=np.float32) for k, v in REAL["stats"]["arm_b"].items()},
              str(tmp_path / "policy_preprocessor_step_3_normalizer_processor.safetensors"))
    assert sg.read_state_range(tmp_path)["min"][4] == pytest.approx(-1.1145, abs=1e-3)
    with pytest.raises(ValueError, match="no normalizer"):
        sg.read_state_range(tmp_path / "empty")


def test_conversion_is_the_sim_formula():
    import math

    for v in (-100.0, -62.2, 0.0, 40.0, 100.0):
        assert sg.norm_to_rad(v) == pytest.approx((v + 100) / 200 * 4095 * 2 * math.pi / 4096 - math.pi, abs=1e-3)


class GateCell(Cell):
    def __init__(self, start, end=CANON):
        super().__init__()
        self.state, self.frames, self.end, self.home = list(start), 0, list(end), list(start)

    def frame(self, view):
        self.frames += 1
        return super().frame(view)

    def act(self, command):
        base = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        if base == "run entry":
            self.state = list(self.end)
        elif base == "run policy":
            self.state = [8.0, -40.0, 35.0, 45.0, 15.0, 55.8]
        elif base == "park":
            self.state = list(self.home)
        self.commands.append(command)
        extra = {"human_hold_latched": True, "torque_hold_commanded": True} if base == "human-hold" else {}
        return {"state": list(self.state), "command": base, "ok": True, "settled": True, "holding": False,
                "health": {"current_ma": [0] * 6}, **extra}


def run(tmp_path, gate, start=HOME, paced=True, *, entry=True, end=CANON, max_chunks=1, policy=SimPolicy):
    chunks = {"home": [start], "reach": [HOME, [25.0, 18.0, 5.0, 25.0, -35.0, 57.5]]}
    if entry:
        chunks["entry"] = [start, ENTRY_MID, CANON]
    lib = write_lib(tmp_path, {"fps": 30, "gripper_closed": 48.8, "chunks": chunks})
    cell = GateCell(start, end)
    chunk = [[8.0, -40.0, 35.0, 45.0, 15.0, 55.8]] * 16
    res = drive.run_episode(cell, policy([chunk] * 3), lib, tmp_path, offset=[0] * 6, max_chunks=max_chunks, dry_run=False,
                            log=[].append, paced_chunks=paced, n_action=4, state_gate=gate)
    return cell, res


def unit_gate(low, high, arm="arm_b"):
    stats = {"min": np.asarray(low, float), "max": np.asarray(high, float)}
    return sg.StateGate(stats, arm_id=arm)  # cell units, no sim rule: only the range check applies


WIDE = ([-60.0, -70.0, 0.0, 0.0, -20.0, 0.0], [60.0, 10.0, 60.0, 70.0, 60.0, 100.0])


def test_paced_folded_start_is_not_gated_and_trained_states_pass(tmp_path):
    cell, res = run(tmp_path, unit_gate(*WIDE))
    assert res["result"] == "chunks_done" and "run entry" in cell.commands and "run policy" in cell.commands


def test_paced_state_outside_the_range_after_entry_sends_no_policy_and_no_camera(tmp_path):
    low, high = [-60.0] * 6, [60.0] * 6
    high[0] = 3.0  # the canonical pan 6 is past the trained maximum
    cell, res = run(tmp_path, unit_gate(low, high))
    assert res["result"] == "refused" and res["reason"].startswith(sg.RANGE_CODE)
    assert "run entry" in cell.commands  # the folded pose is not gated: the entry chunk ran
    assert cell.frames == 0 and not any(c.endswith("run policy") for c in cell.commands)


def test_timed_path_gates_the_same_way(tmp_path):
    low, high = [-60.0] * 6, [60.0] * 6
    high[0] = 3.0
    cell, res = run(tmp_path, unit_gate(low, high), paced=False)
    assert res["result"] == "refused" and res["reason"].startswith(sg.RANGE_CODE)
    assert cell.frames == 0 and not any(c.endswith("run policy") for c in cell.commands)
    cell, res = run(tmp_path, unit_gate(*WIDE), start=[2.222, -62.295, 53.602, 54.042, -47.204, 48.889], paced=False)
    assert res["result"] == "refused" and cell.frames == 0 and not any(c.endswith(("run entry", "run policy")) for c in cell.commands)


def test_paced_wrist_roll_minus_47_is_refused_before_entry(tmp_path):
    roll = [2.222, -62.295, 53.602, 54.042, -47.204, 48.889]
    cell, res = run(tmp_path, unit_gate(*WIDE), start=roll)
    assert res["result"] in ("refused", "fault") and cell.frames == 0
    assert not any(c.endswith(("run entry", "run policy")) for c in cell.commands)


def policy_calls(cell):
    return [c for c in cell.commands if c.endswith("run policy")]


def test_paced_second_chunk_outside_the_range_is_refused(tmp_path):
    low, high = [-60.0] * 6, [60.0] * 6
    low[4] = 20.0  # entry end (40) and home (45.2) are trained; chunk 0 ends at roll 15
    cell, res = run(tmp_path, unit_gate(low, high), max_chunks=2)
    assert res["result"] == "refused" and res["at"] == 1 and res["reason"].startswith(sg.RANGE_CODE)
    assert len(policy_calls(cell)) == 1  # chunk 0 ran, chunk 1 was never sent


@pytest.mark.parametrize("paced", [True, False])
def test_library_without_entry_gates_the_first_chunk(tmp_path, paced):
    low, high = [-60.0] * 6, [60.0] * 6
    high[0] = 0.5  # home pan is 0.8
    cell, res = run(tmp_path, unit_gate(low, high), paced=paced, entry=False)
    assert res["result"] == "refused" and res["reason"].startswith(sg.RANGE_CODE)
    assert not policy_calls(cell) and (cell.frames == 0 or not paced)  # timed observes before it reads the state


@pytest.mark.parametrize("paced", [True, False])
def test_roll_branch_refusal_is_independent_of_the_home_check(tmp_path, paced):
    """The library's own home sits on the untrained -47 branch, so START_POSE_OFF_HOME passes; only roll_error refuses."""
    other = [2.222, -62.295, 53.602, 54.042, -47.204, 48.889]
    cell, res = run(tmp_path, unit_gate(*WIDE), start=other, paced=paced)
    assert res["result"] in ("refused", "fault") and sg.START_CODE in res["reason"] and "wrist_roll" in res["reason"]
    assert cell.frames == 0 and not any(c.endswith(("run entry", "run policy")) for c in cell.commands)


@pytest.mark.parametrize("paced", [True, False])
def test_sim_unit_path_refuses_an_entry_end_off_the_canonical_start(tmp_path, monkeypatch, paced):
    import cell_act_inputs

    monkeypatch.setattr(cell_act_inputs, "sim_gripper", lambda *_: 0.5)
    gate = sg.StateGate({"min": np.full(6, -10.0), "max": np.full(6, 10.0)}, arm_id="arm_b", sim_rule=SimPolicy.sim_rule)
    off = [CANON[0] + 1.5, *CANON[1:]]  # 0.046 rad: inside the 2.0-unit entry tolerance, past the 0.035 rad start limit
    cell, res = run(tmp_path, gate, paced=paced, end=off)
    assert res["result"] == "refused" and res["reason"].startswith(sg.START_CODE) and "canonical start" in res["reason"]
    assert cell.frames == 0 and not policy_calls(cell)


def test_checkpoint_statistics_named_by_the_preprocessor_are_read(tmp_path):
    save_file = pytest.importorskip("safetensors.numpy").save_file
    (tmp_path / "policy_preprocessor.json").write_text(json.dumps({"steps": [
        {"registry_name": "normalizer_processor", "state_file": "other_name.safetensors"}]}))
    save_file({f"observation.state.{k}": np.asarray(v, dtype=np.float32) for k, v in REAL["stats"]["arm_a"].items()},
              str(tmp_path / "other_name.safetensors"))
    assert sg.read_state_range(tmp_path)["max"][1] == pytest.approx(0.5681, abs=1e-3)


def test_missing_statistics_name_the_folder_and_the_fix(tmp_path):
    with pytest.raises(ValueError) as error:
        sg.read_state_range(tmp_path)
    assert str(error.value).startswith(sg.STATS_CODE) and str(tmp_path) in str(error.value) and "normalizer" in str(error.value)


def cli_args(tmp_path, monkeypatch):
    """The sim-unit CLI of test_omx_policy_drive, here without its fake statistics fixture."""
    import hashlib

    import cell_pipeline

    root = tmp_path / "model"
    root.mkdir()
    (root / drive.lrs.WEIGHTS).write_bytes(b"pinned ACT")
    (root / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 4, "chunk_size": 16,
        "input_features": {"observation.state": {"shape": [6]}, drive.lrs.GOAL: {"shape": [10]},
                           "observation.images.top": {"shape": [3, 4, 4]}},
        "output_features": {"action": {"shape": [6]}}}))
    (root / drive.lrs.UNITS).write_text('{"state":"sim_rad","gripper":"sim_jaw","arm":"arm_b"}')
    (tmp_path / "arm-cal-arm_b.json").write_text('{"arm_id":"arm_b","held_30mm":53.38,"gap_mm_per_unit":5}')
    (tmp_path / "cell.json").write_text('{"arm_id":"arm_b","io":"unused","cameras":{}}')
    (tmp_path / "runner-cal.json").write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                                                          for i, n in enumerate(drive.lrs.JOINT_NAMES)}))
    cell = Cell()
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: cell)
    shadow = drive.lrs.LeRobotShadow
    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: shadow(*a, loader=lambda *_: (lambda obs: np.zeros((16, 6))), **kw))
    args = ["--config", str(tmp_path / "cell.json"), "--library", str(write_lib(tmp_path)), "--policy-root", str(root),
            "--policy-revision", hashlib.sha256(b"pinned ACT").hexdigest(), "--cell-calibration", str(tmp_path / "runner-cal.json"),
            "--operator", "test", "--max-chunks", "1", "--dry-run", "--goal-site", "yard:r1-s2-t1"]
    return args, cell


def test_cli_without_statistics_refuses_in_the_usual_output_with_the_code(tmp_path, monkeypatch, capsys):
    args, cell = cli_args(tmp_path, monkeypatch)
    assert drive.main(args) == 1  # no SystemExit from parser.error
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["result"] == "refused" and out["reason"].startswith(sg.STATS_CODE) and str(tmp_path / "model") in out["reason"]
    assert not cell.commands


def test_cli_wires_the_gate_into_the_episode(tmp_path, monkeypatch, capsys):
    args, cell = cli_args(tmp_path, monkeypatch)
    monkeypatch.setattr(sg, "read_state_range", lambda _root: {"min": np.full(6, 5.0), "max": np.full(6, 6.0)})  # no real state is inside
    assert drive.main(args) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["result"] == "refused" and sg.RANGE_CODE in out["reason"]
