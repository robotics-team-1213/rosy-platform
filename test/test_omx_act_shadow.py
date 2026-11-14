"""ACT proposals are logged beside real IK attempts without acquiring motion authority."""
import json
from types import SimpleNamespace

from test_omx_cell_auto_pick import (  # reuse the simulated cell and its operating profile
    CATALOG, CONFIG, CONT2, ROI, Cell, auto, biased_map, cal, cell_attempts,
    cell_choices, no_sleep, np, simulated_operating_profile,
)


class RecordingPolicy:
    policy_revision, policy_environment = "rev-shadow-test", "sim"
    joint_names = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper")

    def __init__(self, error=None):
        self.error, self.seen = error, []

    def infer(self, observation):
        if self.error is not None:
            raise self.error
        self.seen.append(observation)
        return SimpleNamespace(chunk=[tuple(observation["positions"])] * 2)


def run_carry(tmp_path):
    path, cell = biased_map(tmp_path), Cell([CONT2])
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep, log=lambda row: None)
    return result


def shadowed_run(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "r1")
    shadow_mod = auto.cell_act_shadow
    monkeypatch.setattr(shadow_mod, "load", lambda config, work: shadow_mod.Shadow(policy, work, lambda **fields: fields))
    result = run_carry(tmp_path)
    attempts = [json.loads(line) for line in (tmp_path / "attempts.jsonl").read_text().splitlines()]
    rows = [json.loads(line) for line in (tmp_path / "act-shadow.jsonl").read_text().splitlines()]
    return result, attempts, rows


def test_shadow_rows_pair_policy_proposal_with_real_ik_outcome(tmp_path, monkeypatch):
    policy = RecordingPolicy()
    result, attempts, rows = shadowed_run(tmp_path, monkeypatch, policy)
    assert result["result"] == "placed"
    assert [r["attempt_id"] for r in rows] == [a["attempt_id"] for a in attempts]
    assert [r["ik"]["outcome"] for r in rows] == ["empty", "placed"]
    assert all(r["schema"] == "rosy.omx-act-shadow.v1" and r["policy_id"] == "rev-shadow-test" for r in rows)
    assert all(r["policy_environment"] == "sim" for r in rows)
    assert all(len(r["proposed"]) == 2 and len(r["proposed"][0]) == 6 for r in rows)
    assert all(r["observation"]["t_ns"] > 0 and len(r["observation"]["top_frame_sha256"]) == 64 for r in rows)
    assert len({r["observation"]["id"] for r in rows}) == len(rows)
    assert policy.seen and len(policy.seen[0]["positions"]) == 6


def test_shadow_inference_error_is_logged_without_changing_ik(tmp_path, monkeypatch):
    result, attempts, rows = shadowed_run(tmp_path, monkeypatch, RecordingPolicy(ValueError("shadow_inference_fault")))
    assert result["result"] == "placed"
    assert len(rows) == len(attempts) == 2
    assert all("proposed" not in row and "shadow_inference_fault" in row["error"] for row in rows)


def test_shadow_setup_error_is_logged_without_stopping_ik(tmp_path, monkeypatch):
    shadow_mod = auto.cell_act_shadow
    monkeypatch.setattr(shadow_mod, "load", lambda config, work: shadow_mod.Shadow(
        None, work, None, error="policy artifact unavailable", policy_id="missing-revision"))
    assert run_carry(tmp_path)["result"] == "placed"
    rows = [json.loads(line) for line in (tmp_path / "act-shadow.jsonl").read_text().splitlines()]
    assert rows and all("policy artifact unavailable" in row["error"] for row in rows)


def test_shadow_load_failure_stays_in_shadow(tmp_path):
    shadow = auto.cell_act_shadow.load(
        {"act_shadow": {"policy_root": str(tmp_path / "missing"), "policy_revision": "missing-revision"}}, tmp_path)
    row = shadow.capture(Cell([CONT2]), CONFIG, 0, np.zeros((8, 8, 3), dtype=np.uint8))
    assert row["policy_id"] == "missing-revision"
    assert "error" in row and "proposed" not in row


def test_shadow_log_error_does_not_change_ik(tmp_path, monkeypatch):
    shadow_mod = auto.cell_act_shadow
    def broken_record(*_args):
        raise OSError("shadow disk full")
    monkeypatch.setattr(shadow_mod.Shadow, "record", broken_record)
    policy = RecordingPolicy()
    monkeypatch.setattr(shadow_mod, "load", lambda config, work: shadow_mod.Shadow(policy, work, lambda **fields: fields))
    assert run_carry(tmp_path)["result"] == "placed"


def test_shadow_is_off_without_config(tmp_path):
    assert run_carry(tmp_path)["result"] == "placed"
    assert not (tmp_path / "act-shadow.jsonl").exists()
