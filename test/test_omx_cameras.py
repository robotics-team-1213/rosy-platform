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
    rows = oc.inventory({"cameras": [TOP]}, facts, {"/dev/video12": [TOP["device"]]}, ask=lambda node: ["YUYV"],
                        realpath=lambda device: "/dev/video12")
    assert rows[0]["roles"] == ["top"]
    assert rows[0]["formats"] == ["YUYV"] and rows[0]["names"] == [TOP["device"]]


MANIFEST = """cameras:
  - source_id: omx_wrist_b
    image_topic: /arm_b_wrist_camera/image_raw
    device_path: /dev/v4l/by-path/pci-usb-0:3.3:1.0-video-index0  # swapped by hand
    token_env: ROSY_CAMERA_WRIST_B_TOKEN
  - source_id: omx_overhead
    image_topic: /top_camera/image_raw
    device_path: /dev/v4l/by-id/rosy-realsense-d435-color
  - source_id: omx_side
    image_topic: /side_camera/image_raw
    device_path: /dev/v4l/by-id/usb-Jieli-video-index0
"""


def test_manifest_takes_each_camera_device_from_the_role_with_its_topic_and_lists_unknown_topics(tmp_path):
    reg = registry(tmp_path, [TOP, WRIST])
    text, changed, unregistered = oc.sync_manifest(reg, MANIFEST)
    assert changed == [{"topic": WRIST["topic"], "from": "/dev/v4l/by-path/pci-usb-0:3.3:1.0-video-index0",
                        "to": WRIST["device"]}]
    assert f"    device_path: {WRIST['device']}\n    token_env" in text and unregistered == ["/side_camera/image_raw"]
    assert oc.sync_manifest(reg, text)[1] == []


def test_manifest_check_exits_1_until_applied(tmp_path, capsys):
    reg_path = tmp_path / "omx-cameras.json"
    reg_path.write_text(json.dumps({"schema": oc.SCHEMA, "defaults": DEFAULTS, "cameras": [TOP, WRIST]}))
    manifest = tmp_path / "observations.yaml"
    manifest.write_text(MANIFEST)
    args = ["manifest", "--registry", str(reg_path), "--manifest", str(manifest)]
    assert oc.main(args) == 1 and manifest.read_text() == MANIFEST
    assert oc.main(args + ["--apply"]) == 0 and oc.main(args) == 0


A_WRIST = {"role": "arm_a_wrist", "device": "/dev/v4l/by-path/pci-usb-0:3.3:1.0-video-index0",
           "topic": "/arm_a_wrist_camera/image_raw", "frame": "arm_a_wrist_camera_link"}
U20 = {"id": "0c45:6366", "serial": "SN0001", "usb": "1-2", "interface": "1-2:1.0", "speed_mbps": 480}


def _bench(nodes: dict):
    """facts, names and present/realpath for {node: (fact, [names])}."""
    facts = {n: f for n, (f, _) in nodes.items()}
    names = {n: ns for n, (_, ns) in nodes.items()}
    owner = {name: n for n, (_, ns) in nodes.items() for name in ns}
    return facts, names, owner.__contains__, lambda d: owner.get(d, d)


def test_a_wrist_camera_moved_to_another_port_follows_its_role_and_a_new_model_is_only_proposed(tmp_path):
    reg = registry(tmp_path, [dict(WRIST, usb_id=U20["id"]), dict(TOP, usb_id="8086:0b07")])
    moved = "/dev/v4l/by-path/pci-usb-0:2.4:1.0-video-index0"
    facts, names, present, realpath = _bench({
        "/dev/video2": (U20, ["/dev/v4l/by-id/usb-U20CAM_SN0001-video-index0", moved]),
        "/dev/video4": ({**U20, "id": "04f2:b678", "serial": "0001"}, ["/dev/v4l/by-id/usb-LG_Camera_0001-video-index0",
                                                                      "/dev/v4l/by-path/pci-usb-0:2:1.0-video-index0"]),
        "/dev/video12": ({**U20, "id": "8086:0b07"}, [TOP["device"]])})
    rows = oc.propose(reg, facts, names, present, realpath)
    assert [(r["node"], r["follow"], r["roles"]) for r in rows] == [("/dev/video2", "arm_b_wrist", ["arm_b_wrist"]),
                                                                    ("/dev/video4", None, [])]
    assert [r["device"] for r in rows] == [moved, "/dev/v4l/by-path/pci-usb-0:2:1.0-video-index0"]  # never by-id
    changes = oc.learn(reg, facts, rows, present, realpath)
    assert changes == [{"role": "arm_b_wrist", "from": WRIST["device"], "to": rows[0]["device"]}]


def test_two_identical_cameras_gone_at_once_are_proposed_by_port_not_followed(tmp_path):
    reg = registry(tmp_path, [dict(WRIST, usb_id=U20["id"]), dict(A_WRIST, usb_id=U20["id"])])
    facts, names, present, realpath = _bench({
        "/dev/video2": (U20, ["/dev/v4l/by-id/usb-U20CAM_SN0001-video-index0", "/dev/v4l/by-path/pci-usb-0:1.1:1.0-video-index0"]),
        "/dev/video6": ({**U20, "usb": "1-3"}, ["/dev/v4l/by-id/usb-U20CAM_SN0001-video-index0",
                                                "/dev/v4l/by-path/pci-usb-0:1.2:1.0-video-index0"])})
    rows = oc.propose(reg, facts, names, present, realpath)
    assert [r["follow"] for r in rows] == [None, None] and rows[0]["roles"] == ["arm_b_wrist", "arm_a_wrist"]
    assert oc.learn(reg, facts, rows, present, realpath) == []


def test_learn_records_the_model_of_each_present_camera_so_a_later_move_can_follow(tmp_path):
    reg = registry(tmp_path, [WRIST])
    facts, _, present, realpath = _bench({"/dev/video2": (U20, [WRIST["device"]])})
    assert oc.learn(reg, facts, [], present, realpath) == [{"role": "arm_b_wrist", "usb_id": U20["id"]}]
    assert reg["cameras"][0]["usb_id"] == U20["id"] and oc.learn(reg, facts, [], present, realpath) == []


def test_approve_gives_a_new_role_the_naming_convention_and_save_refuses_a_device_used_twice(tmp_path):
    path = tmp_path / "omx-cameras.json"
    reg = registry(tmp_path, [TOP])
    row = {"device": "/dev/v4l/by-id/usb-LG_Camera_0001-video-index0", "usb_id": "04f2:b678"}
    oc.save(oc.approve(reg, "front", row), path)
    front = oc.load(path)["cameras"][1]
    assert front == {"role": "front", "topic": "/front_camera/image_raw", "frame": "front_camera_link",
                     "stream": "color", "device": row["device"], "usb_id": "04f2:b678"}
    with pytest.raises(SystemExit):
        oc.save(oc.approve(oc.load(path), "back", {**row}), path)
    assert len(oc.load(path)["cameras"]) == 2 and not path.with_suffix(".tmp").exists()


def test_twin_wrist_cameras_are_suggested_for_the_arm_whose_board_shares_their_hub(tmp_path):
    reg = registry(tmp_path, [dict(WRIST, usb_id=U20["id"]), dict(A_WRIST, usb_id=U20["id"])])
    facts, names, present, realpath = _bench({
        "/dev/video2": ({**U20, "usb": "3-1.4"}, ["/dev/v4l/by-path/pci-usb-0:1.4:1.0-video-index0"]),
        "/dev/video6": ({**U20, "usb": "3-2"}, ["/dev/v4l/by-path/pci-usb-0:2:1.0-video-index0"])})
    rows = oc.propose(reg, facts, names, present, realpath, hubs={"arm_b": "3-1", "arm_a": "3-4"})
    assert [(r["hub_arm"], r["suggest"], r["follow"]) for r in rows] == [("arm_b", "arm_b_wrist", None),
                                                                         (None, None, None)]  # root port: no hub
    assert oc.learn(reg, facts, rows, present, realpath) == []  # a hint only: nothing is bound
    assert oc.hub("3-1.3.2") == "3-1.3" and oc.hub("3-2") is None


def test_the_devices_updater_ships_the_bind_units():
    # 2026-11-03: the site never had the bind timer, so moved cameras and Fleet approvals were never applied.
    units = json.loads((OMX / "omx-devices-autoupdate.json.example").read_text(encoding="utf-8"))["unit_files"]
    for name in ("rosy-omx-cameras-bind.service", "rosy-omx-cameras-bind.timer"):
        assert f"deploy/robot/omx/{name}" in units and (OMX / name).is_file()
