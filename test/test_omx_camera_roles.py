"""D-1065: recording configs name cameras by role and use the devices omx-cameras.json gives those roles."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import camera_roles as cr  # noqa: E402

CAMERAS = {"cameras": [
    {"role": "top", "device": "/dev/v4l/by-id/rosy-realsense-d435-color"},
    {"role": "side", "device": "/dev/v4l/by-id/rosy-arm_a_jieli"},
    {"role": "arm_a_wrist", "device": "/dev/v4l/by-id/rosy-arm_a_wrist"},
    {"role": "arm_b_wrist", "device": "/dev/v4l/by-id/rosy-arm_b_wrist"},
]}


def cfg(**cams):
    return {"robot": {"type": "omx_follower", "cameras": {k: {"type": "opencv", "index_or_path": v} for k, v in cams.items()}}}


def test_a_three_role_config_passes_for_each_arm():
    for arm, wrist in (("arm_a", "rosy-arm_a_wrist"), ("arm_b", "rosy-arm_b_wrist")):
        cr.check_record_cameras(cfg(top="/dev/v4l/by-id/rosy-realsense-d435-color", side="/dev/v4l/by-id/rosy-arm_a_jieli",
                                    wrist=f"/dev/v4l/by-id/{wrist}"), CAMERAS, arm)


@pytest.mark.parametrize("cams", [
    dict(top="/dev/v4l/by-id/rosy-realsense-d435-color", front="/dev/v4l/by-id/rosy-arm_a_wrist"),   # 11-21 arm A config
    dict(side="/dev/v4l/by-id/rosy-arm_a_jieli", front="/dev/v4l/by-id/rosy-arm_b_wrist"),          # 11-21 arm B config
    dict(rs="/dev/v4l/by-id/rosy-realsense-d435-color", top="/dev/v4l/by-id/rosy-arm_a_jieli", wrist="/dev/v4l/by-id/rosy-arm_a_wrist"),  # Purple-SY names
])
def test_device_or_legacy_names_are_refused(cams):
    with pytest.raises(ValueError, match="D-1065"):
        cr.check_record_cameras(cfg(**cams), CAMERAS, "arm_a")


def test_a_role_on_the_wrong_device_is_refused():
    swapped = cfg(top="/dev/v4l/by-id/rosy-arm_a_jieli", side="/dev/v4l/by-id/rosy-realsense-d435-color", wrist="/dev/v4l/by-id/rosy-arm_a_wrist")
    with pytest.raises(ValueError, match="camera top must be"):
        cr.check_record_cameras(swapped, CAMERAS, "arm_a")
    other_wrist = cfg(top="/dev/v4l/by-id/rosy-realsense-d435-color", side="/dev/v4l/by-id/rosy-arm_a_jieli", wrist="/dev/v4l/by-id/rosy-arm_b_wrist")
    with pytest.raises(ValueError, match="arm_a_wrist"):
        cr.check_record_cameras(other_wrist, CAMERAS, "arm_a")


def test_cell_s_has_no_side_and_a_duplicate_role_is_an_error():
    s = {"cameras": [{"role": "top", "device": "/dev/top"}, {"role": "arm_s_wrist", "device": "/dev/w"}]}
    cr.check_record_cameras(cfg(top="/dev/top", wrist="/dev/w"), s, "arm_s", cell="s")
    with pytest.raises(ValueError, match="twice"):
        cr.role_devices({"cameras": [{"role": "top", "device": "/a"}, {"role": "top", "device": "/b"}]})
