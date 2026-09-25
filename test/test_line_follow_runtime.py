"""D-143 runtime slice is shipped and reachable in hardware mode."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_io_image_contains_line_follow_runtime_without_polluting_core():
    dockerfile = (ROOT / "deploy/robot/Dockerfile").read_text(encoding="utf-8")
    core, io = dockerfile.split("FROM runtime-common AS io-runtime", 1)
    assert "COPY src/runtime/control" not in core
    assert "python3-opencv" not in core
    assert "COPY src/runtime/control ./src/runtime/control" in io
    assert "python3-opencv" in io
    assert "control" in io


def test_hardware_launch_reaches_sensing_only_line_follow_launch():
    launch = (ROOT / "src/runtime/navigation/launch/hardware.launch.py").read_text(
        encoding="utf-8")
    assert 'get_package_share_directory("control")' in launch
    assert '"line_follow.launch.py"' in launch
    assert '"enable_line_follow"' in launch


def test_hardware_compose_passes_camera_and_i2c_devices():
    compose = yaml.safe_load(
        (ROOT / "deploy/robot/compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["rosy-io"]
    devices = service["devices"]
    assert "${ROSY_CAMERA_DEVICE:-/dev/video0}:/dev/video0" in devices
    assert "${ROSY_I2C_DEVICE:-/dev/i2c-1}:/dev/i2c-1" in devices
    assert "enable_line_follow:=true" in service["command"]
    assert "${ROSY_VIDEO_GID:-44}" in service["group_add"]
    assert "${ROSY_I2C_GID:-998}" in service["group_add"]


def test_installer_records_device_group_ids():
    installer = (ROOT / "deploy/robot/install-pi.sh").read_text(encoding="utf-8")
    assert "ROSY_VIDEO_GID" in installer
    assert "ROSY_I2C_GID" in installer


def test_ir_calibration_is_an_external_runtime_profile_not_an_image_rebuild():
    compose = yaml.safe_load(
        (ROOT / "deploy/robot/compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["rosy-io"]
    assert any("ROSY_LINE_FOLLOW_CONFIG_PATH" in volume
               and volume.endswith(":/etc/rosy/line_follow.yaml:ro")
               for volume in service["volumes"])
    assert "line_follow_config:=/etc/rosy/line_follow.yaml" in service["command"]
    profile = ROOT / "deploy/robot/config/line_follow.yaml"
    assert profile.is_file()
    assert "ir_calibration_enabled: false" in profile.read_text(encoding="utf-8")


def test_bridge_checks_original_sensor_age_not_only_receipt_age():
    bridge = (ROOT / "src/runtime/core/core/bridge/ros_bridge.py").read_text(
        encoding="utf-8")
    gate = (ROOT / "src/runtime/core/core/bridge/traffic_gate.py").read_text(
        encoding="utf-8")
    assert "self._node.get_clock().now().nanoseconds" in bridge
    assert "source_now=source_now" in bridge
    assert "traffic_gate.apply_line_candidate" in bridge
    assert "line_follow.apply_if_current" in gate
    assert "traffic_policy.apply_if_current" in gate


def test_semantic_road_launch_connects_real_gazebo_camera_to_dashboard():
    launch = (
        ROOT / "src/sim/gz_sim/launch/semantic_road_dashboard.launch.py"
    ).read_text(encoding="utf-8")
    package = (ROOT / "src/sim/gz_sim/package.xml").read_text(encoding="utf-8")
    config = yaml.safe_load((
        ROOT / "src/sim/gz_sim/config/semantic_road_core.yaml"
    ).read_text(encoding="utf-8"))

    assert "map_260905_traffic.world" in launch
    assert '"bridge_image": "true"' in launch
    assert 'package="core"' in launch
    assert 'executable="line_observer_node"' in launch
    assert 'executable="road_observer_node"' in launch
    assert '"require_camera_controls_stable": False' in launch
    assert '"dashboard_source": "GAZEBO"' in launch
    assert 'DeclareLaunchArgument("gazebo_gui", default_value="false")' in launch
    assert '"gui": LaunchConfiguration("gazebo_gui")' in launch
    assert "<exec_depend>core</exec_depend>" in package
    for dependency in (
        "ament_index_python", "launch", "launch_ros", "ros_gz_image",
    ):
        assert f"<exec_depend>{dependency}</exec_depend>" in package
    assert config["runtime"]["mode"] == "simulation"
    assert config["traffic_policy"]["simulation_signal_control"] is True
    assert config["vision"]["preview_min_pull_interval_s"] == 0.4
