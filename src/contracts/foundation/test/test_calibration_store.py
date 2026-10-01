"""Versioned calibration store (core_common/calibration_store.py, D-47 addendum 2026-10-01)."""
import json
import math
import os

import pytest

from core_common.calibration_store import CalibrationStore, check_values, resolve

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
    for rid in (a, b):  # the latest accept event wins (L3), not creation time
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


def test_torn_and_malformed_event_lines_are_skipped_not_fatal(tmp_path):
    # M1/H3: a power cut mid-append leaves a torn line; hand edits leave junk.
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    store.set_status(ROBOT, "lidar_mount", a, "accepted", actor="op")
    events = tmp_path / ROBOT / "lidar_mount" / "events.jsonl"
    with open(events, "a", encoding="utf-8") as f:
        f.write('[1, 2]\n{"record": 5, "status": "accepted"}\n{"record": "x", "status": "maybe"}\n'
                '{"pin": 7}\n\xff\xfe garbage\n{"record": "' + a + '", "sta')
    assert store.current(ROBOT, "lidar_mount")["id"] == a
    assert [r["status"] for r in store.records(ROBOT, "lidar_mount")] == ["accepted"]


def test_record_without_values_or_created_at_never_loads(tmp_path):
    store = CalibrationStore(tmp_path)
    folder = tmp_path / ROBOT / "lidar_mount" / "records"
    folder.mkdir(parents=True)
    from core_common.calibration_store import SCHEMA, content_sha
    body = {"schema": SCHEMA, "kind": "lidar_mount", "robot": ROBOT, "created_at": 5, "values": [1]}
    (folder / "bad_000000000000.json").write_text(json.dumps({**body, "sha256": content_sha(body)}))
    with pytest.raises(ValueError):
        store.load(ROBOT, "lidar_mount", "bad_000000000000")
    store._event(ROBOT, "lidar_mount", {"record": "bad_000000000000", "status": "accepted"})
    assert store.current(ROBOT, "lidar_mount") is None


def test_reaccepting_an_older_record_makes_it_current(tmp_path):
    # L3: newest accept event wins, not the newest created_at.
    store = CalibrationStore(tmp_path)
    old = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    new = add(store, 3.18, "2026-10-01T11:00:00.000000Z")
    store.set_status(ROBOT, "lidar_mount", new, "accepted", actor="op")
    store.set_status(ROBOT, "lidar_mount", old, "accepted", actor="op")
    assert store.current(ROBOT, "lidar_mount")["id"] == old


def test_resolve_falls_back_on_any_store_error_and_on_implausible_values(tmp_path):
    class Broken:
        def current(self, robot, kind):
            raise RuntimeError("disk on fire")
    values, source = resolve("lidar_mount", {"lidar_yaw_offset": 3.14}, fallback_source="hand",
                             robot=ROBOT, store=Broken())
    assert values == {"lidar_yaw_offset": 3.14} and "unreadable" in source
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, "lidar_mount", {"lidar_yaw_offset": 0.5}, method="t/1")  # 28.6 deg
    store.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    values, source = resolve("lidar_mount", {"lidar_yaw_offset": 3.14}, fallback_source="hand",
                             robot=ROBOT, store=store, nominal={"lidar_forward_deg": 180.0})
    assert values == {"lidar_yaw_offset": 3.14} and "rejected" in source


@pytest.mark.parametrize("kind,values,nominal,ok", [
    ("lidar_mount", {"lidar_yaw_offset": math.radians(181.9)}, {}, True),
    ("lidar_mount", {"lidar_yaw_offset": math.radians(30.0)}, {"lidar_forward_deg": 20.0}, True),
    ("lidar_mount", {"lidar_yaw_offset": math.radians(30.0)}, {"lidar_forward_deg": 180.0}, False),
    ("lidar_mount", {"lidar_yaw_offset": True}, {}, False),
    ("lidar_mount", {"lidar_yaw_offset": float("nan")}, {}, False),
    ("lidar_mount", {}, {}, False),
    ("wheel_odometry", {"wheel_radius": 0.0271, "wheel_separation": 0.0968}, {}, True),
    ("wheel_odometry", {"wheel_radius": 0.031, "wheel_separation": 0.0968}, {}, False),
    ("wheel_odometry", {"wheel_radius": "0.027", "wheel_separation": 0.0968}, {}, False),
    ("wheel_odometry", {"wheel_radius": 0.027, "wheel_separation": True}, {}, False),
    ("camera_profile", {"pitch_rad": 0.195, "height_m": 0.058}, {}, True),
    ("camera_profile", {"pitch_rad": 0.195, "height_m": 1.0}, {}, False),
])
def test_check_values(kind, values, nominal, ok):
    assert (check_values(kind, values, nominal=nominal) is None) is ok


def test_an_append_after_a_torn_tail_is_not_lost(tmp_path):
    # F1: power cut mid-append leaves no trailing newline; the next accept must survive.
    store = CalibrationStore(tmp_path)
    a = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    events = tmp_path / ROBOT / "lidar_mount" / "events.jsonl"
    events.write_text('{"record": "' + a + '", "sta')          # torn, no newline
    store.set_status(ROBOT, "lidar_mount", a, "accepted", actor="op")
    assert store.current(ROBOT, "lidar_mount")["id"] == a


def _two_stores(tmp_path):
    pc, robot = CalibrationStore(tmp_path / "pc"), CalibrationStore(tmp_path / "robot")
    rid = pc.add(ROBOT, "lidar_mount", {"lidar_yaw_offset": 3.17}, method="t/1",
                 created_at="2026-10-01T10:00:00.000000Z")
    robot.merge_from(tmp_path / "pc", ROBOT)
    return pc, robot, rid


def test_sync_refuses_when_both_sides_decided_independently(tmp_path):
    # F2: decisions on both sides could make `current` differ; refuse, write nothing.
    pc, robot, rid = _two_stores(tmp_path)
    pc.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    robot.set_status(ROBOT, "lidar_mount", rid, "rejected", actor="someone-on-the-robot")
    before = (tmp_path / "robot" / ROBOT / "lidar_mount" / "events.jsonl").read_bytes()
    with pytest.raises(ValueError, match="decide on the PC"):
        robot.merge_from(tmp_path / "pc", ROBOT)
    assert (tmp_path / "robot" / ROBOT / "lidar_mount" / "events.jsonl").read_bytes() == before


def test_a_conflict_in_one_kind_writes_nothing_in_any_kind(tmp_path):
    # F8: the whole merge is checked before the first write.
    pc, robot, rid = _two_stores(tmp_path)
    wheel = pc.add(ROBOT, "wheel_odometry", {"wheel_radius": 0.0271, "wheel_separation": 0.0968}, method="t/1")
    pc.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    robot.set_status(ROBOT, "lidar_mount", rid, "rejected", actor="x")
    with pytest.raises(ValueError):
        robot.merge_from(tmp_path / "pc", ROBOT)
    assert not (tmp_path / "robot" / ROBOT / "wheel_odometry" / "records" / f"{wheel}.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_directories_and_files_are_group_writable(tmp_path):
    # F4: a second member of rosy-calib must be able to write.
    store = CalibrationStore(tmp_path)
    rid = add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    store.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    base = tmp_path / ROBOT / "lidar_mount"
    for folder in (tmp_path / ROBOT, base, base / "records"):
        assert folder.stat().st_mode & 0o7777 == 0o2775
    for file in (base / "events.jsonl", base / "records" / f"{rid}.json"):
        assert file.stat().st_mode & 0o777 == 0o664


def test_records_are_written_whole_and_never_leave_a_temporary(tmp_path):
    store = CalibrationStore(tmp_path)
    add(store, 3.17, "2026-10-01T10:00:00.000000Z")
    assert [p.name for p in (tmp_path / ROBOT / "lidar_mount" / "records").iterdir()
            if p.name.startswith(".")] == []


@pytest.mark.parametrize("extra,ok", [
    ({}, True),
    ({"width": 320, "height": 240, "fx": 281.6, "cx": 160.0, "cy": 120.0, "max_range_m": 0.6}, True),
    ({"fx": 0.0}, False),
    ({"width": -320}, False),
    ({"cy": True}, False),
    ({"max_range_m": "0.6"}, False),
])
def test_camera_profile_intrinsics_must_be_finite_positive(extra, ok):
    # F7
    values = {"pitch_rad": 0.195, "height_m": 0.058, **extra}
    assert (check_values("camera_profile", values) is None) is ok


def test_names_are_checked():
    store = CalibrationStore("/nonexistent")
    with pytest.raises(ValueError):
        store.current("../etc", "lidar_mount")
    with pytest.raises(ValueError):
        store.current(ROBOT, "anything")


# D-396: URDF nominal (the static fallback) < accepted record < operator override, per kind.
URDF_NOMINAL = {
    "lidar_mount": ({"lidar_yaw_offset": math.pi},
                    {"lidar_yaw_offset": math.radians(181.9)},
                    {"lidar_yaw_offset": math.radians(183.0)}),
    "wheel_odometry": ({"wheel_radius": 0.028, "wheel_separation": 0.0971},
                       {"wheel_radius": 0.0272, "wheel_separation": 0.0975},
                       {"wheel_radius": 0.0269}),
    "camera_profile": ({"pitch_rad": math.radians(8.0), "height_m": 0.06343, "x_offset_m": 0.03317, "fx": 281.6},
                       {"pitch_rad": math.radians(11.8), "height_m": 0.060},
                       {"height_m": 0.0615}),
}


@pytest.mark.parametrize("kind", sorted(URDF_NOMINAL))
def test_order_urdf_nominal_then_accepted_record_then_operator_override(tmp_path, kind):
    nominal, measured, operator = URDF_NOMINAL[kind]
    store = CalibrationStore(tmp_path)
    values, source = resolve(kind, nominal, fallback_source="geometry.yaml", robot=ROBOT, store=store)
    assert values == nominal and source.startswith("geometry.yaml")
    rid = store.add(ROBOT, kind, measured, method="t/1")
    store.set_status(ROBOT, kind, rid, "accepted", actor="op")
    values, source = resolve(kind, nominal, fallback_source="geometry.yaml", robot=ROBOT, store=store)
    assert values == {**nominal, **measured} and rid in source
    values, source = resolve(kind, nominal, fallback_source="geometry.yaml", robot=ROBOT, store=store,
                             override=operator)
    assert values == {**nominal, **measured, **operator}
    assert rid in source and "operator override" in source
    # An override alone, with no record, also wins over the nominal.
    values, _ = resolve(kind, nominal, fallback_source="geometry.yaml", robot=ROBOT,
                        store=CalibrationStore(tmp_path / "empty"), override=operator)
    assert values == {**nominal, **operator}


def test_none_valued_override_keys_are_ignored(tmp_path):
    values, source = resolve("wheel_odometry", {"wheel_radius": 0.028}, fallback_source="geometry.yaml",
                             robot=ROBOT, store=CalibrationStore(tmp_path), override={"wheel_radius": None})
    assert values == {"wheel_radius": 0.028} and "operator override" not in source


def test_measured_robots_pass_the_urdf_centred_checks():
    """8kcn 0.0272/0.0975 and 9dfk 0.0266/0.0953 sit inside the URDF nominal +-10 %; 181-182 deg in the window."""
    for r, b in ((0.0272, 0.0975), (0.0266, 0.0953)):
        assert check_values("wheel_odometry", {"wheel_radius": r, "wheel_separation": b}) is None
    for deg in (181.0, 182.0):
        assert check_values("lidar_mount", {"lidar_yaw_offset": math.radians(deg)}) is None
