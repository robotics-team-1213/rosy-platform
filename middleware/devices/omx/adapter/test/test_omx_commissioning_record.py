"""D-858 S3 commissioning record: atomic store, history, revision, MotionEvidence loader, gate."""

import json
from datetime import datetime, timezone

import pytest

from omx_adapter.command_owner import ArmCommandConfig
from omx_adapter.real.commissioning_record import (
    CommissioningStore, gate_status, load_motion_evidence, revision_of,
)
from omx_adapter.real.dynamixel_gates import MotionEvidence

JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
STOP = {"joint": "joint1", "measured_stop_ms": 180, "joint1_deviation_rad": 0.02,
        "joint1_velocity_rad_s": 0.01, "pre_stop_velocity_rad_s": 0.19, "passed": True, "driver": "dynamixel",
        "config_revision": "cal-measured-1"}
MEASURED = {"joint_limits": {name: [-1.6, 1.6] for name in JOINTS},
            "gripper": {"open_rad": 0.5, "close_rad": -0.2},
            "workspace": [[-1.0, 1.0], [-1.0, 1.0], [-0.5, 1.0]]}


def _config(revision="cal-measured-1", limit=1.5):
    return ArmCommandConfig(
        enabled=True, workcell_id="omx-1", instance_id="omx-1-control", joint_names=JOINTS,
        position_limits={name: (-limit, limit) for name in JOINTS},
        velocity_limits={name: 2.0 for name in JOINTS},
        allowed_owners=("rule_based",), calibration_revision=revision)


def _store(tmp_path):
    return CommissioningStore(tmp_path, workcell_id="omx-1", instance_id="omx-1-control")


def _save(store, changes, *, by="kim", revision="cal-measured-1"):
    return store.save(changes, by=by, config_revision=revision, joint_names=JOINTS,
                      expected_revision=store.revision(), now=NOW)


def _full(tmp_path):
    store = _store(tmp_path)
    _save(store, MEASURED)
    _save(store, {"stop_test": STOP}, by="lee")
    return store


def test_full_record_opens_the_gate_bound_to_its_revisions(tmp_path):
    store = _full(tmp_path)
    evidence = load_motion_evidence(store, _config())
    assert evidence.blockers(config_revision="cal-measured-1") == []
    assert evidence.revision == store.revision() == revision_of(store.read())
    assert evidence.config_revision == "cal-measured-1"
    item = store.read()["items"]["stop_test"]
    assert item["measured_by"] == "lee" and item["measured_at"] == NOW.isoformat()


def test_save_is_atomic_keeps_history_and_refuses_a_stale_revision(tmp_path):
    store = _store(tmp_path)
    first = _save(store, {"gripper": MEASURED["gripper"]})
    second = _save(store, {"workspace": MEASURED["workspace"]})
    assert first != second
    history = store.history()
    assert [h["revision"] for h in history] == [first, second]
    assert history[1]["previous_revision"] == first and history[1]["changed"] == ["workspace"]
    assert revision_of(history[0]["record"]) == first  # every earlier version stays readable
    with pytest.raises(ValueError, match="changed since"):
        store.save({"gripper": {"open_rad": 0.4, "close_rad": 0.0}}, by="kim",
                   config_revision="cal-measured-1", joint_names=JOINTS, expected_revision=first)
    assert store.revision() == second
    assert [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.parametrize("changes,by", [
    ({"gripper": {"open_rad": 0.5, "close_rad": 0.5}}, "kim"),
    ({"gripper": {"open_rad": float("nan"), "close_rad": 0.1}}, "kim"),
    ({"joint_limits": {"joint1": [-1, 1]}}, "kim"),
    ({"joint_limits": {name: [1, -1] for name in JOINTS}}, "kim"),
    ({"workspace": [[0, 1], [0, 1]]}, "kim"),
    ({"stop_test": {**STOP, "passed": "yes"}}, "kim"),
    ({"stop_test": {k: v for k, v in STOP.items() if k != "config_revision"}}, "kim"),
    ({"tuning": {}}, "kim"),
    (MEASURED, ""),
])
def test_invalid_values_or_missing_name_never_reach_the_file(tmp_path, changes, by):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        _save(store, changes, by=by)
    assert store.read() is None and store.history() == []


def test_instance_names_cannot_escape_the_root(tmp_path):
    with pytest.raises(ValueError):
        CommissioningStore(tmp_path, workcell_id="..", instance_id="x")
    with pytest.raises(ValueError):
        CommissioningStore(tmp_path, workcell_id="omx-1", instance_id="a/b")


def test_no_record_or_missing_items_close_the_gate_with_reasons(tmp_path):
    store = _store(tmp_path)
    assert "no commissioning record" in "; ".join(load_motion_evidence(store, _config()).blockers())
    _save(store, {"gripper": MEASURED["gripper"]})
    blockers = "; ".join(load_motion_evidence(store, _config()).blockers())
    assert "missing: joint_limits, workspace" in blockers
    assert "no stop test record" in blockers


def test_damaged_record_closes_the_gate(tmp_path):
    store = _full(tmp_path)
    store.path.write_text("{not json", encoding="utf-8")
    assert "unreadable" in load_motion_evidence(store, _config()).blockers()[0]
    with pytest.raises(ValueError):
        store.revision()


@pytest.mark.parametrize("change,reason", [
    ({"measured_stop_ms": 501}, "did not pass"),
    ({"joint1_deviation_rad": -0.11}, "did not pass"),
    ({"joint1_velocity_rad_s": 0.2}, "did not pass"),
    ({"pre_stop_velocity_rad_s": 0.1}, "did not pass"),  # the arm was not really moving
    ({"passed": False}, "did not pass"),
    ({"driver": "fake"}, "did not pass"),
    ({"config_revision": "cal-old"}, "not run under the record's config revision"),
])
def test_stop_test_gate_rechecks_v016_and_its_config_revision(tmp_path, change, reason):
    store = _store(tmp_path)
    _save(store, {**MEASURED, "stop_test": {**STOP, **change}})
    evidence = load_motion_evidence(store, _config())
    assert any(reason in b for b in evidence.blockers(config_revision="cal-measured-1"))
    # Measurement mode (the stop test itself) runs without the stop-test item.
    assert evidence.blockers(config_revision="cal-measured-1", include_stop_test=False) == []


def test_record_of_another_config_revision_or_wider_limits_is_refused(tmp_path):
    store = _full(tmp_path)
    assert any("port config is 'cal-measured-2'" in b for b in
               load_motion_evidence(store, _config("cal-measured-2")).blockers(config_revision="cal-measured-2"))
    wide = load_motion_evidence(store, _config(limit=1.7))
    assert any("owner limit joint1" in b for b in wide.blockers(config_revision="cal-measured-1"))
    disabled = load_motion_evidence(store, ArmCommandConfig())
    assert "owner config is not enabled" in disabled.blockers()


def test_items_measured_under_different_config_revisions_are_refused(tmp_path):
    """S3 review M1: a later save under another revision never relabels earlier items."""
    store = _store(tmp_path)
    _save(store, {"joint_limits": MEASURED["joint_limits"]}, revision="cal-measured-1")
    _save(store, {"gripper": MEASURED["gripper"], "workspace": MEASURED["workspace"],
                  "stop_test": {**STOP, "config_revision": "cal-measured-2"}}, revision="cal-measured-2")
    items = store.read()["items"]
    assert items["joint_limits"]["config_revision"] == "cal-measured-1"
    assert items["gripper"]["config_revision"] == "cal-measured-2"
    for config in (_config("cal-measured-1"), _config("cal-measured-2")):
        evidence = load_motion_evidence(store, config)
        blockers = "; ".join(evidence.blockers(config_revision=config.calibration_revision))
        assert "different config revisions" in blockers and "items not measured under" in blockers
        assert evidence.config_revision is None


def test_evidence_without_a_record_revision_is_refused():
    assert "evidence not loaded from a commissioning record" in MotionEvidence().blockers()


def test_gate_status_lists_items_and_blockers_read_only(tmp_path):
    store = _store(tmp_path)
    _save(store, {"gripper": MEASURED["gripper"]}, by="park")
    before = store.path.read_bytes()
    status = gate_status(store)
    assert status["items"]["gripper"] == {"measured_at": NOW.isoformat(), "measured_by": "park",
                                          "config_revision": "cal-measured-1"}
    assert status["items"]["stop_test"] is None and status["revision"] == store.revision()
    assert any("no stop test record" in b for b in status["blockers"])
    json.dumps(status, allow_nan=False)
    assert store.path.read_bytes() == before
    assert gate_status(_store(tmp_path / "none"))["revision"] is None
