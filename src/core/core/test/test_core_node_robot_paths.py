"""D-196: which profile/capabilities files the CORE node loads, decided without ROS.

Absolute overlay paths (`/etc/rosy/*.yaml`) win and must boot even when the robot
package named by `robot.model` is not installed. Only a missing or relative key
looks the robot package up.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from core_common import profile as profile_module
from core_common.config import ConfigError

SRC = Path(__file__).resolve().parents[3]


@pytest.fixture
def node_module(monkeypatch):
    """Same fake-rclpy load as test_core_node_teardown: core.node reads without ROS."""
    rclpy = types.ModuleType("rclpy")
    executors = types.ModuleType("rclpy.executors")
    node = types.ModuleType("rclpy.node")
    executors.MultiThreadedExecutor = object
    node.Node = object
    rclpy.executors = executors
    rclpy.node = node
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.executors", executors)
    monkeypatch.setitem(sys.modules, "rclpy.node", node)
    import core
    monkeypatch.delitem(sys.modules, "core.node", raising=False)
    missing = object()
    saved_attr = getattr(core, "node", missing)
    import core.node as module
    yield module
    sys.modules.pop("core.node", None)
    if saved_attr is missing:
        delattr(core, "node")
    else:
        core.node = saved_attr


@pytest.fixture
def no_ament_share(monkeypatch):
    """ament importable but knowing no robot package, so the source fallback is the answer
    on a host and on a sourced ROS box alike."""
    package = types.ModuleType("ament_index_python")
    packages = types.ModuleType("ament_index_python.packages")

    class PackageNotFoundError(KeyError):
        pass

    def missing(name):
        raise PackageNotFoundError(name)

    packages.PackageNotFoundError = PackageNotFoundError
    packages.get_package_share_directory = missing
    package.packages = packages
    monkeypatch.setitem(sys.modules, "ament_index_python", package)
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", packages)


def test_absolute_overlays_boot_without_the_robot_package(node_module, monkeypatch, tmp_path):
    def no_lookup(robot):
        raise AssertionError(f"robot package looked up for {robot!r}")

    monkeypatch.setattr(profile_module, "robot_config_dir", no_lookup)
    profile = tmp_path / "profile.yaml"
    capabilities = tmp_path / "capabilities.yaml"
    config = {"robot": {"model": "not_installed"}, "profile": str(profile), "capabilities": str(capabilities)}

    assert node_module._robot_file_paths(config) == (profile, capabilities)


def test_missing_keys_read_the_default_robot_package(node_module, no_ament_share):
    robot_dir = SRC / "robots" / "pinky_pro" / "config"

    assert node_module._robot_file_paths({"robot": {}}) == (
        robot_dir / "profile.yaml", robot_dir / "capabilities.yaml")


def test_relative_names_resolve_inside_the_robot_package(node_module, no_ament_share):
    robot_dir = SRC / "robots" / "pinky_pro" / "config"
    config = {"robot": {"model": "pinky_pro", "profile": "profile.yaml", "capabilities": "caps/capabilities.yaml"}}

    assert node_module._robot_file_paths(config) == (
        robot_dir / "profile.yaml", robot_dir / "capabilities.yaml")


def test_a_missing_robot_package_fails_with_the_config_error(node_module, no_ament_share, tmp_path):
    config = {"robot": {"model": "not_installed", "profile": str(tmp_path / "profile.yaml")}}

    with pytest.raises(ConfigError, match="not_installed"):
        node_module._robot_file_paths(config)
