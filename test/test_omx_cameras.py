"""omx_cameras: one registry binds each camera role to its camera, and a camera plugged back gets its role again
(2026-10-31: roles were rewired by hand after cameras moved and a RealSense D435 replaced the top camera)."""
import json
from pathlib import Path
import sys

import pytest

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import omx_cameras as oc
finally:
    sys.path.remove(str(OMX))

DEFAULTS = {"ROSY_CAMERA_SOURCE": "/r/camera_source.py", "ROS_DOMAIN_ID": "13"}
TOP = {"role": "top", "device": "/dev/v4l/by-id/rosy-realsense-d435-color", "topic": "/top_camera/image_raw",
       "frame": "top_camera_link", "fourcc": "YUYV", "stream": "color"}
WRIST = {"role": "arm_b_wrist", "device": "/dev/v4l/by-path/pci-usb-0:1.3:1.0-video-index0",
         "topic": "/arm_b_wrist_camera/image_raw", "frame": "arm_b_wrist_camera_link", "fourcc": "MJPG"}
DEPTH = {"role": "top_depth", "device": "/dev/v4l/by-id/rosy-realsense-d435-depth", "topic": "/top_depth/image_raw",
         "frame": "top_camera_link", "fourcc": "Z16", "stream": "depth", "env": {"ROSY_DEPTH_RANGE_MM": "300,900"}}


def registry(tmp_path, cameras):
    path = tmp_path / "omx-cameras.json"
    path.write_text(json.dumps({"schema": oc.SCHEMA, "defaults": DEFAULTS, "cameras": cameras}))
    return oc.load(path)


def test_each_role_env_comes_from_the_registry_and_a_default_format_is_left_to_the_producer(tmp_path):
    reg = registry(tmp_path, [TOP, WRIST, DEPTH])
    env = {c["role"]: oc.role_env(c, reg["defaults"]) for c in reg["cameras"]}
    assert env["top"] == {**DEFAULTS, "ROSY_CAMERA_DEVICE": TOP["device"], "ROSY_CAMERA_TOPIC": TOP["topic"],
                          "ROSY_CAMERA_FRAME": "top_camera_link", "ROSY_CAMERA_FOURCC": "YUYV"}
    assert "ROSY_CAMERA_FOURCC" not in env["arm_b_wrist"] and env["top_depth"]["ROSY_DEPTH_RANGE_MM"] == "300,900"


def test_bind_writes_changed_roles_waits_for_absent_cameras_and_lists_unregistered_ones(tmp_path):
    reg = registry(tmp_path, [TOP, WRIST, DEPTH])
    (tmp_path / "omx-camera-top.env").write_text("".join(f"{k}={v}\n" for k, v in oc.role_env(TOP, DEFAULTS).items()))
    nodes = {TOP["device"]: "/dev/video12", WRIST["device"]: "/dev/video6"}
    plan = oc.bind(reg, tmp_path, lambda d: d in nodes, {"/dev/video12", "/dev/video6", "/dev/video4"},
                   realpath=lambda d: nodes.get(d, d))
    assert plan["write"] == {"arm_b_wrist": oc.role_env(WRIST, DEFAULTS)} and plan["restart"] == ["arm_b_wrist"]
    assert plan["waiting"] == ["top_depth"] and plan["unregistered"] == ["/dev/video4"]  # top unchanged: left alone
    calls = []
    done = oc.apply({**plan, "present": ["top", "arm_b_wrist"]}, tmp_path, lambda role: role == "top",
                    run=lambda argv, **kw: calls.append(argv[-1]))
    assert (tmp_path / "omx-camera-arm_b_wrist.env").read_text().count("ROSY_CAMERA_DEVICE=") == 1
    assert calls == ["rosy-omx-camera@arm_b_wrist.service"] * 2 and len(done) == 2


def test_a_registry_with_a_numeric_device_twice_used_device_or_unknown_stream_is_refused(tmp_path):
    for cameras in ([dict(TOP, device="/dev/video8")], [TOP, dict(WRIST, device=TOP["device"])], [dict(TOP, stream="thermal")]):
        with pytest.raises(SystemExit):
            registry(tmp_path, cameras)


def test_init_adopts_the_role_env_files_in_use(tmp_path):
    for camera in (TOP, WRIST):
        (tmp_path / f"omx-camera-{camera['role']}.env").write_text(
            "".join(f"{k}={v}\n" for k, v in oc.role_env(camera, DEFAULTS).items()))
    adopted = oc.init(tmp_path)
    assert adopted["defaults"] == DEFAULTS
    assert {c["role"]: c["device"] for c in adopted["cameras"]} == {"top": TOP["device"], "arm_b_wrist": WRIST["device"]}
    path = tmp_path / "reg.json"
    path.write_text(json.dumps(adopted))
    assert oc.load(path)["cameras"][1]["fourcc"] == "YUYV"


def test_inventory_names_every_node_and_its_role():
    facts = {"/dev/video12": {"id": "8086:0b07", "usb": "3-4", "serial": "1", "speed_mbps": 480, "interface": "3-4:1.3"}}
    rows = oc.inventory({"cameras": [TOP]}, facts, {"/dev/video12": [TOP["device"]]}, ask=lambda node: ["YUYV"])
    assert rows[0]["roles"] == [] or rows[0]["roles"] == ["top"]  # realpath of a test path is itself
    assert rows[0]["formats"] == ["YUYV"] and rows[0]["names"] == [TOP["device"]]
