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


def test_resolve_record_cameras_heals_stale_path_and_fails_closed():
    live_reg = {"cameras": [
        {"role": "top", "device": "/dev/v4l/by-id/rosy-realsense-d435-color"},
        {"role": "side", "device": "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4:1.0-video-index0"},
        {"role": "arm_a_wrist", "device": "/dev/v4l/by-id/rosy-arm_a_wrist"},
        {"role": "arm_b_wrist", "device": "/dev/v4l/by-id/rosy-arm_b_wrist"},
        {"role": "arm_s_top", "device": "/dev/v4l/by-id/rosy-arm_s_jieli", "enabled": False},
        {"role": "arm_s_wrist", "device": "/dev/v4l/by-id/rosy-arm_s_wrist"},
    ]}
    present = {
        "/dev/v4l/by-id/rosy-realsense-d435-color": "/dev/video4",
        "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4:1.0-video-index0": "/dev/video6",
        "/dev/v4l/by-id/rosy-arm_a_wrist": "/dev/video8",
        "/dev/v4l/by-id/rosy-arm_s_wrist": "/dev/video10",
    }
    raw_a = cfg(top="/dev/v4l/by-id/rosy-realsense-d435-color", side="/dev/v4l/by-id/rosy-arm_a_jieli",
                wrist="/dev/v4l/by-id/rosy-arm_a_wrist")
    resolved, rebinds, issues = cr.resolve_record_cameras(
        raw_a, "arm_a", live_reg, exists=lambda p: p in present, realpath=lambda p: present.get(p, p))
    assert issues == [] and len(rebinds) == 1
    assert resolved["robot"]["cameras"]["side"]["index_or_path"] == "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4:1.0-video-index0"

    # arm_b fails closed because registered arm_b_wrist device is unplugged
    _, _, b_issues = cr.resolve_record_cameras(
        cfg(top="/dev/v4l/by-id/rosy-realsense-d435-color", side="/dev/v4l/by-id/rosy-arm_a_jieli",
            wrist="/dev/v4l/by-id/rosy-arm_b_wrist"),
        "arm_b", live_reg, exists=lambda p: p in present, realpath=lambda p: present.get(p, p))
    assert any("arm_b_wrist" in s and "등록 장치 없음" in s for s in b_issues)

    # arm_s top never falls back to Cell A/B top and rejects disabled arm_s_top
    assert cr.source_role("top", "arm_s") == "arm_s_top"
    _, _, s_issues = cr.resolve_record_cameras(
        cfg(top="/dev/v4l/by-id/rosy-arm_s_jieli", wrist="/dev/v4l/by-id/rosy-arm_s_wrist"),
        "arm_s", live_reg, exists=lambda p: p in present, realpath=lambda p: present.get(p, p))
    assert any("비활성" in s and "arm_s_top" in s for s in s_issues)
    _, _, s_ok = cr.resolve_record_cameras(
        cfg(wrist="/dev/v4l/by-id/rosy-arm_s_wrist"),
        "arm_s", live_reg, exists=lambda p: p in present, realpath=lambda p: present.get(p, p))
    assert s_ok == []

    # Duplicate realpath and bimanual parent cameras
    bi = {"robot": {"type": "bi_omx_follower", "cameras": {
        "top": {"type": "opencv", "index_or_path": "/dev/v4l/by-id/rosy-realsense-d435-color"},
        "side": {"type": "opencv", "index_or_path": "/dev/v4l/by-id/rosy-arm_a_jieli"},
        "arm_a_wrist": {"type": "opencv", "index_or_path": "/dev/v4l/by-id/rosy-arm_a_wrist"},
    }, "arm_a": {"cameras": {}}, "arm_b": {"cameras": {}}}}
    r_bi, bi_reb, bi_iss = cr.resolve_record_cameras(bi, "arm_ab", live_reg, exists=lambda p: p in present, realpath=lambda p: present.get(p, p))
    assert bi_iss == [] and len(bi_reb) == 1 and r_bi["robot"]["cameras"]["side"]["index_or_path"].startswith("/dev/v4l/by-path/")
    dup = cfg(top="/dev/v4l/by-id/rosy-realsense-d435-color", wrist="/dev/v4l/by-id/rosy-arm_a_wrist")
    _, _, dup_iss = cr.resolve_record_cameras(dup, "arm_a", live_reg, exists=lambda p: p in present, realpath=lambda _: "/dev/video4")
    assert any("중복" in s for s in dup_iss)
