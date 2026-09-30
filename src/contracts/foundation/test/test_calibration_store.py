"""Versioned calibration store (core_common/calibration_store.py, D-47 addendum 2026-10-01)."""
import json

import pytest

from core_common.calibration_store import CalibrationStore, resolve

ROBOT = "rosy-pinky-8kcn"


def add(store, value, when, kind="lidar_mount"):
    return store.add(ROBOT, kind, {"lidar_yaw_offset": value}, sessions=["s1"], method="test/1",
                     intervals={"lidar_yaw_offset": [value - 0.01, value + 0.01]}, created_at=when)


def test_every_run_is_a_new_record_and_none_is_overwritten(tmp_path):
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    b = add(store, 3.18, "2026-10-01T11:00:00.000000Z")
    assert a != b
    ids = [r["id"] for r in store.records(ROBOT, "lidar_mount")]
    assert ids == [a, b]
    assert all(r["status"] == "candidate" for r in store.records(ROBOT, "lidar_mount"))
    with pytest.raises(FileExistsError):  # the same content at the same time is the same id
        add(store, 3.17, "2026-10-01T10:00:00.000000Z")


def test_a_candidate_is_never_current_until_an_operator_accepts_it(tmp_path):
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    assert store.current(ROBOT, "lidar_mount") is None
    store.set_status(ROBOT, "lidar_mount", a, "accepted", actor="operator")
    assert store.current(ROBOT, "lidar_mount")["id"] == a
    with pytest.raises(ValueError):
        store.set_status(ROBOT, "lidar_mount", a, "accepted", actor=" ")


def test_latest_accepted_wins_and_older_reads_superseded(tmp_path):
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    b = add(store, 3.18, "2026-10-01T11:00:00.000000Z")
    c = add(store, 3.19, "2026-10-01T12:00:00.000000Z")
    for rid in (b, a):  # acceptance order does not matter; creation time does
        store.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    store.set_status(ROBOT, "lidar_mount", c, "rejected", actor="op")
    assert store.current(ROBOT, "lidar_mount")["id"] == b
    status = {r["id"]: r["status"] for r in store.records(ROBOT, "lidar_mount")}
    assert status == {a: "superseded", b: "accepted", c: "rejected"}


def test_pin_rolls_back_and_unpin_follows_the_newest_again(tmp_path):
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    b = add(store, 3.18, "2026-10-01T11:00:00.000000Z")
    for rid in (a, b):
        store.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    store.pin(ROBOT, "lidar_mount", a, actor="op", note="rollback")
    cur = store.current(ROBOT, "lidar_mount")
    assert cur["id"] == a and cur["pinned"]
    store.pin(ROBOT, "lidar_mount", None, actor="op")
    assert store.current(ROBOT, "lidar_mount")["id"] == b
    with pytest.raises(ValueError):
        store.pin(ROBOT, "lidar_mount", add(store, 3.2, "2026-10-01T13:00:00.000000Z"), actor="op")


def test_rejecting_the_newest_accepted_rolls_back(tmp_path):
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    b = add(store, 3.18, "2026-10-01T11:00:00.000000Z")
    for rid in (a, b):
        store.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    store.set_status(ROBOT, "lidar_mount", b, "rejected", actor="op", note="bad run")
    assert store.current(ROBOT, "lidar_mount")["id"] == a
    events = (tmp_path / ROBOT / "lidar_mount" / "events.jsonl").read_text().splitlines()
    assert len(events) == 3  # history kept, append-only


def test_a_tampered_record_is_never_current(tmp_path):
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    store.set_status(ROBOT, "lidar_mount", a, "accepted", actor="op")
    path = tmp_path / ROBOT / "lidar_mount" / "records" / f"{a}.json"
    rec = json.loads(path.read_text())
    rec["values"]["lidar_yaw_offset"] = 1.0
    path.write_text(json.dumps(rec))
    assert store.current(ROBOT, "lidar_mount") is None
    assert store.records(ROBOT, "lidar_mount")[0]["status"] == "invalid"


def test_resolve_falls_back_to_static_config_and_names_the_source(tmp_path):
    store = CalibrationStore(tmp_path)
    values, source = resolve("lidar_mount", {"lidar_yaw_offset": 3.316}, fallback_source="robot.yaml",
                             robot=ROBOT, store=store)
    assert values == {"lidar_yaw_offset": 3.316}
    assert source.startswith("robot.yaml")
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    store.set_status(ROBOT, "lidar_mount", a, "accepted", actor="op")
    values, source = resolve("lidar_mount", {"lidar_yaw_offset": 3.316}, fallback_source="robot.yaml",
                             robot=ROBOT, store=store)
    assert values == {"lidar_yaw_offset": 3.17}
    assert a in source and "sha256" in source


def test_missing_store_root_is_a_fallback_not_an_error(tmp_path):
    values, source = resolve("wheel_odometry", {"wheel_radius": 0.027}, fallback_source="rosy_params.yaml",
                             robot=ROBOT, root=tmp_path / "absent")
    assert values == {"wheel_radius": 0.027} and "no accepted" in source


def test_names_are_checked():
    store = CalibrationStore("/nonexistent")
    with pytest.raises(ValueError):
        store.current("../etc", "lidar_mount")
    with pytest.raises(ValueError):
        store.current(ROBOT, "anything")
