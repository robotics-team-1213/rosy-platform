"""Stage-3 dock tag evidence: frames to `dock/observation` wire payloads.

control observes (frames and OpenCV live here, D-66); CORE decides motion
and remains the only final cmd_vel publisher. The node is a thin rclpy
shell over DockTagObserver, checked here by source and packaging.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest

import dock_scene

from control.sensing.dock_observer import (
    SOURCE,
    DockTagObserver,
    camera_matrix_from_hfov,
    dock_observation_payload,
)
from control.sensing.dock_tag import CameraMount

ROOT = Path(__file__).resolve().parents[1]
MOUNT = CameraMount(height_m=dock_scene.HEIGHT_M, pitch_rad=dock_scene.PITCH_RAD,
                    x_offset_m=dock_scene.CAM_X)


def _observer():
    return DockTagObserver(tag_id=7, tag_size_m=0.05, mount=MOUNT, hfov_rad=dock_scene.HFOV)


def test_the_camera_matrix_is_the_gazebo_pinhole():
    matrix = camera_matrix_from_hfov(320, 180, 1.1519)
    assert matrix[0, 0] == pytest.approx(246.4, abs=0.1)
    assert matrix[1, 1] == matrix[0, 0]
    # Gazebo's pixel centres: (W - 1) / 2, not the W / 2 of its camera_info.
    assert (matrix[0, 2], matrix[1, 2]) == (159.5, 89.5)
    assert np.allclose(matrix, dock_scene.CAMERA_MATRIX)
    for bad in [(320, 180, 0.0), (320, 180, math.pi), (0, 180, 1.0),
                (320, 180, float("nan")), (320, 180, "x")]:
        assert camera_matrix_from_hfov(*bad) is None


def test_a_rendered_tag_becomes_a_visible_base_link_observation():
    payload = _observer().observe(dock_scene.render(dock_scene.SPOT), 12.5)
    x, y, yaw = dock_scene.truth(dock_scene.SPOT)
    assert payload["source"] == SOURCE == "CAMERA_TAG"
    assert payload["visible"] is True and payload["tag_id"] == 7
    assert payload["stamp"] == 12.5
    assert payload["x"] == pytest.approx(x, abs=0.004)
    assert payload["y"] == pytest.approx(y, abs=0.002)
    assert payload["yaw"] == pytest.approx(yaw, abs=math.radians(1.0))
    assert payload["range_m"] == pytest.approx(math.hypot(payload["x"], payload["y"]))
    assert 0.0 < payload["confidence"] <= 1.0
    assert json.loads(json.dumps(payload)) == payload


def test_no_tag_is_a_not_visible_observation_never_a_guess():
    payload = _observer().observe(dock_scene.render(dock_scene.SPOT, marker=False), 3.0)
    assert payload == {"source": "CAMERA_TAG", "stamp": 3.0, "visible": False,
                       "tag_id": None, "x": None, "y": None, "yaw": None,
                       "range_m": None, "confidence": 0.0, "revision": None}


def test_a_foreign_tag_id_is_not_ours():
    observer = DockTagObserver(tag_id=8, tag_size_m=0.05, mount=MOUNT, hfov_rad=dock_scene.HFOV)
    assert observer.observe(dock_scene.render(dock_scene.SPOT), 1.0)["visible"] is False


def test_the_stamp_must_be_finite():
    for bad in [float("nan"), float("inf"), True, "1.0"]:
        with pytest.raises(ValueError):
            dock_observation_payload(bad, None)


def test_the_observer_refuses_a_bad_contract():
    with pytest.raises(ValueError):
        DockTagObserver(tag_id=7, tag_size_m=0.0, mount=MOUNT, hfov_rad=1.1519)
    with pytest.raises(ValueError):
        DockTagObserver(tag_id=7, tag_size_m=0.05, mount=None, hfov_rad=1.1519)
    with pytest.raises(ValueError):
        DockTagObserver(tag_id=7, tag_size_m=0.05, mount=MOUNT, hfov_rad=0.0)
    with pytest.raises(ValueError):
        _observer().observe(np.zeros((0, 0), np.uint8), 1.0)


def test_the_node_publishes_evidence_only_and_fails_closed_off_gazebo():
    source = (ROOT / "control" / "dock_observer_node.py").read_text(encoding="utf-8")
    assert "create_publisher(String, 'dock/observation', 10)" in source
    assert "cmd_vel" not in source.replace("``cmd_vel``", "")
    assert "Twist" not in source
    assert "source != 'GAZEBO' or not use_sim_time" in source
    # A frame always publishes: not visible unless an observer was built.
    assert "payload = dock_observation_payload(stamp, None)" in source


def test_the_node_is_an_installed_entry_point():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "'dock_observer_node = control.dock_observer_node:main'" in setup



_NODE_SMOKE = """
import json
import cv2, rclpy
from sensor_msgs.msg import Image
import dock_scene
from control.dock_observer_node import DockObserverNode

bgr = cv2.cvtColor(dock_scene.render(dock_scene.SPOT), cv2.COLOR_GRAY2BGR)

params = {"use_sim_time": "true", "camera_geometry_source": "GAZEBO",
          "camera_height_m": dock_scene.HEIGHT_M, "camera_pitch_rad": dock_scene.PITCH_RAD,
          "camera_hfov_rad": dock_scene.HFOV, "camera_x_offset_m": dock_scene.CAM_X}
args = ["--ros-args"]
for name, value in params.items():
    args += ["-p", f"{name}:={value}"]
rclpy.init(args=args)
node = DockObserverNode()
published = []
node.observation_pub.publish = lambda msg: published.append(json.loads(msg.data))
msg = Image(height=bgr.shape[0], width=bgr.shape[1], encoding="bgr8",
            step=bgr.shape[1] * 3, data=bgr.tobytes())
msg.header.stamp.sec = 12
node._on_camera(msg)
print(json.dumps(published[-1]))
node.destroy_node()
rclpy.shutdown()
"""


def test_the_node_observes_a_rendered_tag_in_a_fresh_interpreter():
    """The rclpy shell end to end, in a child interpreter so a native crash
    (exit -11 from the OpenCV 4.6 aruco API in all three Gazebo missions)
    fails the test instead of killing pytest. Skipped without rclpy (the
    Windows host)."""
    pytest.importorskip("rclpy")
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(Path(__file__).resolve().parent)]
        + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _NODE_SMOKE],
                            env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, (result.returncode, result.stderr[-2000:])
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    x, y, yaw = dock_scene.truth(dock_scene.SPOT)
    assert payload["visible"] is True and payload["tag_id"] == 7
    assert payload["stamp"] == 12.0
    assert payload["x"] == pytest.approx(x, abs=0.004)
    assert payload["y"] == pytest.approx(y, abs=0.002)
    assert payload["yaw"] == pytest.approx(yaw, abs=math.radians(1.0))
