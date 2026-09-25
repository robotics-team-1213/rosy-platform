"""Fail-closed contracts for the physical hardware mapping backend (D-144)."""

from pathlib import Path

import yaml

from robot_contracts import DEPLOY, NAV_LAUNCH, ROOT, compose


def test_mapping_capability_overlay_advertises_only_an_available_slam_graph():
    path = DEPLOY / "config" / "capabilities.hardware-mapping.yaml"
    caps = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert caps["slam"] is True
    assert caps["teleop"] is True
    assert caps["navigation"]["goal_navigation"] is True
    assert caps["sensors"] == ["lidar", "encoder"]


def test_runtime_wrapper_validates_backend_and_limits_slam_to_hardware():
    script = (DEPLOY / "runtime-mode.sh").read_text(encoding="utf-8")

    assert 'ROSY_NAVIGATION_BACKEND' in script
    assert 'localization|slam' in script
    assert 'slam backend requires hardware runtime mode' in script
    assert 'capabilities.hardware-mapping.yaml' in script
    assert 'ROSY_MAPS_MOUNT_MODE=rw' in script
    assert 'ROSY_MAPS_MOUNT_MODE=ro' in script


def test_compose_passes_backend_and_keeps_write_scope_bounded():
    services = compose()["services"]
    core = services["rosy-core"]
    io = services["rosy-io"]

    assert core["environment"]["ROSY_NAVIGATION_BACKEND"] == (
        "${ROSY_NAVIGATION_BACKEND:-localization}"
    )
    assert core["environment"]["ROSY_MAP_OUTPUT_DIR"] == "/var/lib/rosy/maps"
    assert (
        "./config/${ROSY_CAPABILITIES_FILE:-capabilities.core.yaml}:"
        "/etc/rosy/capabilities.yaml:ro"
    ) in core["volumes"]
    assert "navigation_backend:=${ROSY_NAVIGATION_BACKEND:-localization}" in io["command"]
    assert "${ROSY_DATA_PATH:-/var/lib/rosy}/maps:/var/lib/rosy/maps:${ROSY_MAPS_MOUNT_MODE:-ro}" in io["volumes"]
    assert "${ROSY_DATA_PATH:-/var/lib/rosy}/commissioning:/var/lib/rosy/commissioning:rw" in io["volumes"]
    assert "/var/lib/rosy:/var/lib/rosy:rw" not in io["volumes"]
    health = " ".join(io["healthcheck"]["test"])
    assert "${ROSY_NAVIGATION_BACKEND:-localization}" in health
    assert "slam_toolbox" in health
    assert "amcl" in health
    assert "map_server" in health


def test_io_image_contains_slam_and_bounded_mcap_recording_tools():
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")

    assert "ros-jazzy-slam-toolbox" in dockerfile
    assert "ros-jazzy-ros2bag" in dockerfile
    assert "ros-jazzy-rosbag2-storage-mcap" in dockerfile


def test_hardware_launch_has_mutually_exclusive_localization_and_mapping_graphs():
    launch = (NAV_LAUNCH / "hardware.launch.py").read_text(encoding="utf-8")
    mapping = (NAV_LAUNCH / "mapping_bringup_launch.xml").read_text(encoding="utf-8")

    assert '"navigation_backend"' in launch
    assert "navigation backend must be localization or slam" in launch
    assert "bringup_launch.xml" in launch
    assert "mapping_bringup_launch.xml" in launch
    assert "resolve_occupancy_map" in launch
    assert "map_building.launch.xml" in mapping
    assert "navigation_launch.xml" in mapping
    assert "localization_launch.xml" not in mapping


def test_mapper_params_are_rewritten_for_the_robot_namespace(tmp_path):
    import sys

    package = ROOT / "src" / "runtime" / "navigation"
    if str(package) not in sys.path:
        sys.path.append(str(package))
    from navigation.params_rewrite import write_prefixed_nav2_params

    source = package / "params" / "mapper_params.yaml"
    output = Path(write_prefixed_nav2_params(source, "rosy_01", directory=tmp_path))
    params = yaml.safe_load(output.read_text(encoding="utf-8"))["slam_toolbox"][
        "ros__parameters"
    ]

    assert params["odom_frame"] == "rosy_01/odom"
    assert params["base_frame"] == "rosy_01/base_footprint"
    assert params["map_frame"] == "map"
    assert params["scan_topic"] == "/rosy_01/scan"


def test_navigation_package_declares_slam_runtime_dependency():
    package_xml = (
        ROOT / "src" / "runtime" / "navigation" / "package.xml"
    ).read_text(encoding="utf-8")
    assert "<exec_depend>slam_toolbox</exec_depend>" in package_xml
