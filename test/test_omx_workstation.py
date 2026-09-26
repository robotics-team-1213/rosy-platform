from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy" / "omx"
SPEC = importlib.util.spec_from_file_location("omx_preflight", OMX / "preflight.py")
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def device_probe(devices: dict[str, str], denied: set[str] | None = None):
    denied = denied or set()

    def realpath(path: str) -> str:
        return devices.get(path, path)

    def stat_fn(path: str):
        if path not in devices.values():
            raise FileNotFoundError(path)
        return type("Stat", (), {"st_mode": stat.S_IFCHR | 0o600})()

    def access_fn(path: str, mode: int) -> bool:
        return path not in denied

    return realpath, stat_fn, access_fn


def test_preflight_requires_distinct_writable_by_id_devices():
    follower = "/dev/serial/by-id/usb-robotis-follower"
    leader = "/dev/serial/by-id/usb-robotis-leader"
    probe = device_probe({follower: "/dev/ttyUSB0", leader: "/dev/ttyUSB1"})

    resolved = preflight.resolve_devices(follower, leader, probe=probe)

    assert resolved == {"OMX_FOLLOWER_DEVICE": "/dev/ttyUSB0", "OMX_LEADER_DEVICE": "/dev/ttyUSB1"}
    assert preflight.render_env(resolved) == (
        "OMX_FOLLOWER_DEVICE=/dev/ttyUSB0\nOMX_LEADER_DEVICE=/dev/ttyUSB1\n"
    )


@pytest.mark.parametrize(
    ("follower", "leader", "devices", "denied", "message"),
    [
        ("/dev/ttyUSB0", "/dev/serial/by-id/usb-leader", {}, set(), "by-id"),
        (
            "/dev/serial/by-id/usb-same",
            "/dev/serial/by-id/usb-same",
            {"/dev/serial/by-id/usb-same": "/dev/ttyUSB0"},
            set(),
            "different",
        ),
        (
            "/dev/serial/by-id/usb-follower",
            "/dev/serial/by-id/usb-leader",
            {
                "/dev/serial/by-id/usb-follower": "/dev/ttyUSB0",
                "/dev/serial/by-id/usb-leader": "/dev/ttyUSB1",
            },
            {"/dev/ttyUSB1"},
            "read/write",
        ),
    ],
)
def test_preflight_fails_closed(follower, leader, devices, denied, message):
    probe = device_probe(devices, denied)
    with pytest.raises(ValueError, match=message):
        preflight.resolve_devices(follower, leader, probe=probe)


def test_preflight_rejects_non_character_device_targets():
    follower = "/dev/serial/by-id/usb-follower"
    leader = "/dev/serial/by-id/usb-leader"
    resolved = {follower: "/dev/ttyUSB0", leader: "/dev/ttyUSB1"}

    def stat_fn(path: str):
        mode = stat.S_IFREG | 0o600 if path.endswith("0") else stat.S_IFCHR | 0o600
        return type("Stat", (), {"st_mode": mode})()

    probe = (lambda path: resolved[path], stat_fn, lambda _path, _mode: True)
    with pytest.raises(ValueError, match="character device"):
        preflight.resolve_devices(follower, leader, probe=probe)


def test_compose_keeps_hardware_and_simulation_without_shared_device_grants():
    compose = (OMX / "compose.yaml").read_text(encoding="utf-8")
    assert 'profiles: ["hardware"]' in compose
    assert 'profiles: ["simulation"]' in compose
    assert '"${OMX_FOLLOWER_DEVICE:?run the host preflight}:${OMX_FOLLOWER_DEVICE:?run the host preflight}"' in compose
    assert '"${OMX_LEADER_DEVICE:?run the host preflight}:${OMX_LEADER_DEVICE:?run the host preflight}"' in compose
    assert '"/dev:/dev"' not in compose
    assert "privileged:" not in compose
    assert compose.count("devices:") == 1


def test_dockerfile_builds_only_from_locked_sources_and_remains_inert():
    dockerfile = (OMX / "Dockerfile").read_text(encoding="utf-8")
    assert "fetch_sources.py" in dockerfile
    assert "rosdep install" in dockerfile
    assert "colcon build" in dockerfile
    assert "CMD" in dockerfile
    assert "open_manipulator" in dockerfile


def test_simulation_profile_runs_pinned_robotis_gazebo_launch_without_hardware_access():
    import yaml

    compose = yaml.safe_load((OMX / "compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["omx-simulation"]

    assert service["profiles"] == ["simulation"]
    assert service["command"] == [
        "ros2",
        "launch",
        "open_manipulator_bringup",
        "omx_f_gazebo.launch.py",
    ]
    assert "devices" not in service
    assert "privileged" not in service
    assert service["environment"] == {
        "ROS_DOMAIN_ID": "${OMX_SIM_DOMAIN_ID:-31}",
        "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
        "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST",
    }


def test_dockerfile_installs_gazebo_runtime_dependencies_for_vendor_simulation():
    dockerfile = (OMX / "Dockerfile").read_text(encoding="utf-8")
    skip_line = next(line for line in dockerfile.splitlines() if "--skip-keys" in line)

    assert not any(
        package in skip_line
        for package in ("ros_gz_bridge", "ros_gz_sim", "ros_gz_image", "gz_ros2_control")
    )


def test_simulation_build_patches_vendor_launch_to_use_gazebo_server_only():
    dockerfile = (OMX / "Dockerfile").read_text(encoding="utf-8")
    patch = (OMX / "patches" / "omx-f-gazebo-headless.patch").read_text(encoding="utf-8")

    assert "omx-f-gazebo-headless.patch" in dockerfile
    assert " apply --check " in dockerfile
    assert "-v 1 -s" in patch
    assert "omx_f_gazebo.launch.py" in patch


def test_omx_runtime_domain_is_configurable_but_simulation_discovery_stays_local():
    import yaml

    compose = yaml.safe_load((OMX / "compose.yaml").read_text(encoding="utf-8"))
    hardware = compose["services"]["omx-hardware-shell"]["environment"]
    simulation = compose["services"]["omx-simulation"]["environment"]

    assert hardware == {
        "ROS_DOMAIN_ID": "${OMX_ROS_DOMAIN_ID:-30}",
        "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
        "ROS_AUTOMATIC_DISCOVERY_RANGE": "${OMX_ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}",
    }
    assert simulation["ROS_DOMAIN_ID"] == "${OMX_SIM_DOMAIN_ID:-31}"
    assert simulation["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
    assert simulation["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"
    dockerfile = (OMX / "Dockerfile").read_text(encoding="utf-8")
    assert "ros-jazzy-rmw-cyclonedds-cpp" in dockerfile
    assert "ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" in dockerfile


def test_omx_entrypoint_uses_discovery_range_without_legacy_localhost_override():
    entrypoint = (OMX / "entrypoint.sh").read_text(encoding="utf-8")

    assert "unset ROS_LOCALHOST_ONLY" in entrypoint
