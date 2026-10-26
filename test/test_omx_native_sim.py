"""Exercise the shared Gazebo launcher without ROS, devices, or a simulator."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/robot/omx/run_cell_sim.sh"
pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="requires bash")


def launch(tmp_path, *, overlay_exists=True, site=False, launch_exit=0):
    home = tmp_path / "home"
    home.mkdir()
    if site:
        (home / "rosy-jobs").mkdir()
        (home / "rosy-jobs/site").touch()
    setup = tmp_path / "ros setup.bash"
    setup.write_text("export NATIVE_ROS_LOADED=yes\n")
    overlay = tmp_path / "selected overlay"
    overlay.mkdir()
    if overlay_exists:
        (overlay / "setup.bash").write_text("export NATIVE_OVERLAY_LOADED=yes\n")
    world = tmp_path / "selected world"
    world.with_suffix(".sdf").write_text("<sdf/>\n")
    tools = tmp_path / "bin"
    tools.mkdir()
    ros2 = tools / "ros2"
    ros2.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$@\" > \"$CAPTURE\"\n"
        "env -0 > \"$CAPTURE.env\"\n"
        "echo native-sim-launch\n"
        f"exit {launch_exit}\n"
    )
    ros2.chmod(0o755)
    capture = tmp_path / "capture"
    env = dict(os.environ, HOME=str(home), PATH=str(tools) + os.pathsep + os.environ["PATH"],
               OMX_CELL_ROS_SETUP=str(setup), OMX_CELL_OVERLAY=str(overlay),
               OMX_CELL_WORLD=str(world), OMX_CELL_LOG_DIR=str(tmp_path / "logs"),
               ROS_DOMAIN_ID="17", ROS_AUTOMATIC_DISCOVERY_RANGE="SUBNET", CAPTURE=str(capture))
    env.pop("OMX_CELL_DOMAIN_ID", None)
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    return result, capture


def test_native_overlay_world_and_allocated_domain_reach_simulation_launch(tmp_path, monkeypatch):
    multiline = "first\r\nnot-a-key-value\nlast=part"
    monkeypatch.setenv("ROSY_TEST_MULTILINE", multiline)
    result, capture = launch(tmp_path)
    assert result.returncode == 0, result.stderr
    args = capture.read_text().splitlines()
    assert args[:3] == ["launch", "open_manipulator_bringup", "omx_f_follower_ai_gazebo.launch.py"]
    assert args[3] == "world:=" + str(tmp_path / "selected world")
    env = dict(os.fsdecode(record).split("=", 1)
               for record in capture.with_suffix(".env").read_bytes().split(b"\0") if record)
    assert env["ROSY_TEST_MULTILINE"] == multiline
    assert env["NATIVE_ROS_LOADED"] == env["NATIVE_OVERLAY_LOADED"] == "yes"
    assert env["ROS_DOMAIN_ID"] == "17"
    assert env["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
    assert (tmp_path / "logs/rosy-cell-gazebo.log").read_text().strip() == "native-sim-launch"


def test_missing_selected_overlay_never_launches_simulator(tmp_path):
    result, capture = launch(tmp_path, overlay_exists=False)
    assert result.returncode != 0
    assert not capture.exists()


def test_site_host_marker_refuses_simulation_before_launch(tmp_path):
    result, capture = launch(tmp_path, site=True)
    assert result.returncode != 0
    assert "site host" in result.stderr
    assert not capture.exists()


def test_simulator_failure_is_not_reported_as_success(tmp_path):
    result, _ = launch(tmp_path, launch_exit=23)
    assert result.returncode == 23
