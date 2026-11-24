"""The cycle and return-held callers preserve a blocked Gate's attempt intent."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def held_gate(tmp_path, monkeypatch):
    root = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(root / "middleware/devices/omx/adapter"))
    monkeypatch.syspath_prepend(str(root / "deploy/robot/omx"))
    import cell_attempts
    import cell_transfer
    import cell_unwedge

    monkeypatch.setattr(cell_attempts, "RUN", {**cell_attempts.RUN, "path": None, "pending": None, "episode": None})
    pending = tmp_path / "attempts.pending.json"
    assessment = {"allowed": True, "reason": None, "mode": "commissioning"}
    before_rehome = []

    def rehome(*args, **kwargs):
        before_rehome.append(pending.read_bytes() if pending.exists() else None)
        return {"result": "session_changed"}

    monkeypatch.setattr(cell_transfer.Gate, "_assess", Mock(return_value=assessment))
    monkeypatch.setattr(cell_unwedge, "can_rehome", Mock(return_value=True))
    monkeypatch.setattr(cell_unwedge, "rehome_before_work", rehome)
    library = tmp_path / "carry.json"
    library.write_text("{}", encoding="utf-8")
    return library, before_rehome


@pytest.fixture
def state_only_cell():
    def act(command):
        assert command == "state"
        return {"ok": True}

    return Mock(act=Mock(side_effect=act))


@pytest.fixture
def cycle_carry(tmp_path, monkeypatch, state_only_cell, held_gate):
    import cell_auto_setup
    import cell_calibration
    import cell_cycle
    import cell_pipeline
    import cell_robot_profile

    config = {"work_dir": str(tmp_path), "calibration_path": str(tmp_path / "calibration.json"),
              "operating_profile_path": "profile.json", "io": str(tmp_path / "io"), "cameras": {}, "sites": {}}
    monkeypatch.setattr(cell_auto_setup, "load_config", Mock(return_value=config))
    monkeypatch.setattr(cell_calibration, "load", Mock(return_value={"sites": {}}))
    monkeypatch.setattr(cell_robot_profile, "bind_pipeline", Mock(return_value={"_operating_profile_binding": {}}))
    monkeypatch.setattr(cell_pipeline, "FifoCell", Mock(return_value=state_only_cell))

    def carry(**cycle_plan):
        plan = {"cells": dict.fromkeys(cell_cycle.ARMS, "cell.json"), **cycle_plan}
        return cell_cycle._tools(plan, commissioning=True)["carry"]("arm_s", held_gate[0])

    return carry


def assert_hold_ledger(tmp_path, before_rehome, active_ledger, endpoints):
    import cell_attempts

    attempts = tmp_path / "attempts.jsonl"
    pending = attempts.with_suffix(".pending.json")
    if not active_ledger:
        assert before_rehome == [None]
        assert not attempts.exists() and not pending.exists()
        assert cell_attempts.RUN["pending"] is None
        return

    line, = attempts.read_text(encoding="utf-8").splitlines()
    row = json.loads(line)
    intent = json.loads(pending.read_bytes())
    assert before_rehome == [pending.read_bytes()]
    assert row["attempt_id"] == intent["attempt_id"] == cell_attempts.RUN["pending"]
    assert row["envelope"] == intent["envelope"]
    assert (row["outcome"], row["transfer"]["at"], row["fail_class"]) == ("held", "rehome", "session_changed")
    assert (row["from"], row["to"]) == endpoints


@pytest.mark.parametrize(("cycle_plan", "endpoints"), [
    ({}, ("unknown", "unknown")),
    ({"source_site": "tray", "target_site": "belt"}, ("tray", "belt")),
    ({"target_site": "belt"}, ("unknown", "belt")),
    (None, None),
])
def test_cycle_records_held_open_only_with_ledger(tmp_path, cycle_carry, held_gate, cycle_plan, endpoints):
    import cell_attempts

    if cycle_plan is not None:
        cell_attempts.start(tmp_path / "attempts.jsonl", "cycle")
    assert cycle_carry(**(cycle_plan or {})) == {"ok": False, "error": "held: session_changed"}
    assert_hold_ledger(tmp_path, held_gate[1], cycle_plan is not None, endpoints)


@pytest.mark.parametrize(("arm", "work_dir"), [("arm_a", "."), ("arm_s", "other")])
def test_cycle_refuses_a_foreign_active_ledger_before_open(tmp_path, cycle_carry, state_only_cell, arm, work_dir):
    import cell_attempts

    attempts = tmp_path / work_dir / "attempts.jsonl"
    cell_attempts.start(attempts, "foreign", arm_id=arm)
    assert cycle_carry() == {"ok": False, "error": "held: audit_unavailable"}
    state_only_cell.act.assert_not_called()
    assert not attempts.exists() and not attempts.with_suffix(".pending.json").exists()


@pytest.mark.parametrize("active_ledger", [True, False])
def test_return_held_records_held_open_only_with_ledger(tmp_path, monkeypatch, state_only_cell, held_gate, active_ledger):
    import cell_attempts
    import cell_auto_pick
    import cell_return_held

    library, before_rehome = held_gate
    config = {"work_dir": str(tmp_path), "sites": {"belt": {"place": [0.06, 0.07]}}}
    evidence = cell_auto_pick.cell_auto_evidence
    monkeypatch.setattr(evidence, "map_pose_preflight", Mock(return_value=None))
    monkeypatch.setattr(evidence, "track_sites", Mock(return_value=(config, None, None)))
    monkeypatch.setattr(evidence, "source_frame", Mock(return_value=(None, None, None)))
    monkeypatch.setattr(cell_auto_pick, "open_episode", Mock(return_value=None))
    monkeypatch.setattr(cell_auto_pick, "close_episode", Mock())
    monkeypatch.setattr(cell_return_held, "_plan_return_held", Mock(return_value=(library, {}, 0.04, 0, None)))
    if active_ledger:
        cell_attempts.start(tmp_path / "attempts.jsonl", "return-held")

    out = cell_return_held.run_return_held(
        state_only_cell, config, {"sites": {}}, tmp_path / "calibration.json", [{"id": "box"}], None, "belt", tmp_path,
    )
    assert out["result"] == "held: session_changed"
    assert_hold_ledger(tmp_path, before_rehome, active_ledger, ("held", "belt"))
