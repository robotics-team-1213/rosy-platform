"""store_cli accept checks and the robot <-> PC merge (D-47 addendum, review H1/H2/M2)."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import store_cli  # noqa: E402
from core_common.calibration_store import CalibrationStore  # noqa: E402

ROBOT = "rosy-test"


@pytest.mark.parametrize("kind,values,ok", [
    ("lidar_mount", {"lidar_yaw_offset": math.radians(181.9)}, True),
    ("lidar_mount", {"lidar_yaw_offset": math.radians(40.0)}, False),
    ("wheel_odometry", {"wheel_radius": 0.0271, "wheel_separation": 0.0968}, True),
    ("wheel_odometry", {"wheel_radius": 0.0400, "wheel_separation": 0.0968}, False),
    ("wheel_odometry", {"wheel_radius": True, "wheel_separation": 0.0968}, False),
])
def test_accept_refuses_implausible_values(tmp_path, kind, values, ok):
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, kind, values, method="t/1")
    code = store_cli.main(["accept", ROBOT, kind, rid, "--actor", "op", "--root", str(tmp_path)])
    assert (code == 0) is ok
    assert (store.current(ROBOT, kind) is not None) is ok


def test_sync_merges_missing_records_and_events_both_ways(tmp_path):
    pc, robot = CalibrationStore(tmp_path / "pc"), CalibrationStore(tmp_path / "robot")
    on_robot = robot.add(ROBOT, "camera_profile", {"pitch_rad": 0.19, "height_m": 0.058}, method="step/1",
                         created_at="2026-10-01T09:00:00.000000Z")
    on_pc = pc.add(ROBOT, "wheel_odometry", {"wheel_radius": 0.0271, "wheel_separation": 0.0968},
                   method="tool/1")
    pc.set_status(ROBOT, "wheel_odometry", on_pc, "accepted", actor="op")
    assert store_cli.main(["sync", ROBOT, "--from", str(tmp_path / "pc"), "--root", str(tmp_path / "robot")]) == 0
    assert robot.current(ROBOT, "wheel_odometry")["id"] == on_pc
    assert [r["id"] for r in robot.records(ROBOT, "camera_profile")] == [on_robot]   # kept
    # Syncing again adds nothing; the other direction brings the robot's candidate home.
    assert robot.merge_from(tmp_path / "pc", ROBOT) == {"records": 0, "events": 0}
    assert pc.merge_from(tmp_path / "robot", ROBOT) == {"records": 1, "events": 0}


def test_hand_deg_is_optional_and_only_widens_the_window(tmp_path):
    # F6: without --hand-deg only 150-210 deg; with it, +-15 deg around it too.
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, "lidar_mount", {"lidar_yaw_offset": math.radians(20.0)}, method="t/1")
    assert store_cli.main(["accept", ROBOT, "lidar_mount", rid, "--actor", "op", "--root", str(tmp_path)]) == 2
    assert store_cli.main(["accept", ROBOT, "lidar_mount", rid, "--actor", "op", "--root", str(tmp_path),
                           "--hand-deg", "10"]) == 0


def test_errors_print_refused_instead_of_a_traceback(tmp_path, capsys):
    # F8: a missing record or a sync conflict is a one-line refusal, exit 2.
    assert store_cli.main(["accept", ROBOT, "lidar_mount", "20261001T000000_000000000000", "--actor", "op",
                           "--root", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("refused: ")
    pc, robot = CalibrationStore(tmp_path / "pc"), CalibrationStore(tmp_path / "robot")
    rid = pc.add(ROBOT, "lidar_mount", {"lidar_yaw_offset": 3.17}, method="t/1")
    robot.merge_from(tmp_path / "pc", ROBOT)
    pc.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="op")
    robot.set_status(ROBOT, "lidar_mount", rid, "rejected", actor="x")
    assert store_cli.main(["sync", ROBOT, "--from", str(tmp_path / "pc"), "--root", str(tmp_path / "robot")]) == 2
    assert "refused: " in capsys.readouterr().err


def test_sync_never_overwrites_a_conflicting_record(tmp_path):
    a, b = CalibrationStore(tmp_path / "a"), CalibrationStore(tmp_path / "b")
    rid = a.add(ROBOT, "lidar_mount", {"lidar_yaw_offset": 3.17}, method="t/1")
    path_b = tmp_path / "b" / ROBOT / "lidar_mount" / "records" / f"{rid}.json"
    path_b.parent.mkdir(parents=True)
    path_b.write_text("{}")
    with pytest.raises(ValueError):
        b.merge_from(tmp_path / "a", ROBOT)
    assert path_b.read_text() == "{}"
