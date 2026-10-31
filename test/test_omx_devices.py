"""omx_devices: plugged-in boards and cameras against each role's configured device (2026-10-31: boards moved between
arms, and roles kept pointing at boards and cameras that were gone, or at a board that now answered as a leader)."""
from pathlib import Path
import sys
from types import SimpleNamespace

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import omx_devices as od
finally:
    sys.path.remove(str(OMX))

F, L1, L2, GONE = "/dev/serial/by-id/F", "/dev/serial/by-id/L1", "/dev/serial/by-id/L2", "/dev/serial/by-id/GONE"
CAM = "/dev/v4l/by-id/usb-Innomaker-video-index0"


def test_a_board_is_a_follower_or_a_leader_by_the_ids_it_answers():
    assert [od.kind(range(11, 17)), od.kind(range(1, 7)), od.kind([]), od.kind([11, 12])] == [
        "follower", "leader", "absent", "unknown"]


def test_roles_come_from_the_per_role_env_files(tmp_path):
    (tmp_path / "omx-observer-arm_b.env").write_text(f"ROSY_OBSERVER_SOURCE=/x.py\nROSY_OBSERVER_DEVICE={F}\n")
    (tmp_path / "omx-camera-top.env").write_text("ROSY_CAMERA_DEVICE=/dev/v4l/by-id/jieli-index0\n")
    (tmp_path / "omx-arm-status.env").write_text("ROSY_ARM_STATUS_ARM_ID=arm_s\n")  # no device: not a role
    assert od.roles(tmp_path) == {"camera-top": "/dev/v4l/by-id/jieli-index0", "observer-arm_b": F}


def test_missing_wrong_kind_and_unassigned_devices_are_all_reported():
    boards = {F: "follower", L1: "leader", L2: "leader"}
    configured = {"observer-arm_a": GONE, "observer-arm_b": L1, "camera-arm_a_wrist": CAM}
    out = od.scan(boards, [CAM], configured)
    assert out["problems"] == [f"observer-arm_a: {GONE} is not plugged in",
                               f"observer-arm_b: {L1} answers as a leader, not a follower"]
    assert out["unassigned"] == sorted([F, L2])
    cell = SimpleNamespace(workcell_id="omx_02", enabled=True, follower=F, leader=GONE)
    out = od.scan(boards, [CAM], {"camera-arm_a_wrist": CAM}, SimpleNamespace(workcells=[cell]))
    assert out["problems"] == ["omx_02 leader: /dev/serial/by-id/GONE is not plugged in"] and out["unassigned"] == [L1, L2]
    assert od.scan(boards, [CAM], {"observer-arm_b": F, "camera-x": CAM})["problems"] == []
