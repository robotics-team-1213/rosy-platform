"""D-196: which profile/capabilities files the CORE node loads, decided without ROS.

Absolute overlay paths (`/etc/rosy/*.yaml`) win and must boot even when the robot
package named by `robot.model` is not installed. Only a missing or relative key
looks the robot package up.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
import shutil

import pytest

from core_common import profile as profile_module
from core_common.config import ConfigError

SRC = (Path(__file__).resolve().parents[4] / "src")


@pytest.fixture
def node_module(monkeypatch):
    """Same fake-rclpy load as test_core_node_teardown: core.node reads without ROS."""
    monkeypatch.delenv("ROSY_DEPLOYMENT", raising=False)
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
    robot_dir = SRC.parent / "middleware" / "devices" / "pinky" / "profile" / "config"

    assert node_module._robot_file_paths({"robot": {}}) == (
        robot_dir / "profile.yaml", robot_dir / "capabilities.yaml")


def test_relative_names_resolve_inside_the_robot_package(node_module, no_ament_share):
    robot_dir = SRC.parent / "middleware" / "devices" / "pinky" / "profile" / "config"
    config = {"robot": {"model": "pinky_pro", "profile": "profile.yaml", "capabilities": "caps/capabilities.yaml"}}

    assert node_module._robot_file_paths(config) == (
        robot_dir / "profile.yaml", robot_dir / "capabilities.yaml")


def test_a_missing_robot_package_fails_with_the_config_error(node_module, no_ament_share, tmp_path):
    config = {"robot": {"model": "not_installed", "profile": str(tmp_path / "profile.yaml")}}

    with pytest.raises(ConfigError, match="not_installed"):
        node_module._robot_file_paths(config)


@pytest.fixture
def installed_rasptank(node_module, no_ament_share, monkeypatch, tmp_path):
    """Product lookup uses an installed share, never the source-checkout fallback."""
    source = SRC.parent / "middleware/devices/rasptank/profile/config"
    share = tmp_path / "install/share/rasptank_metal"
    shutil.copytree(source, share / "config")
    packages = sys.modules["ament_index_python.packages"]

    def installed(name):
        if name != "rasptank_metal":
            raise packages.PackageNotFoundError(name)
        return str(share)

    monkeypatch.setattr(packages, "get_package_share_directory", installed)
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    return share / "config"


def test_device_defaults_use_installed_model(node_module, installed_rasptank):
    assert node_module._robot_file_paths({"robot": {"model": "rasptank_metal"}}) == (
        installed_rasptank / "profile.yaml", installed_rasptank / "capabilities.yaml")


def test_device_accepts_matching_absolute_overlay(node_module, installed_rasptank, tmp_path):
    overlay = tmp_path / "operator"
    shutil.copytree(installed_rasptank, overlay)
    config = {"robot": {"model": "rasptank_metal"},
              "profile": str(overlay / "profile.yaml"),
              "capabilities": str(overlay / "capabilities.yaml")}
    assert node_module._robot_file_paths(config) == (
        overlay / "profile.yaml", overlay / "capabilities.yaml")
    profile, capabilities = node_module._load_robot_settings(config)
    assert profile.model == "RaspTank Metal"
    assert capabilities["teleop"] is False


def test_device_rejects_source_only_model(node_module, no_ament_share, monkeypatch):
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    with pytest.raises(ConfigError, match="rasptank_metal"):
        node_module._robot_file_paths({"robot": {"model": "rasptank_metal"}})


def test_device_absolute_overlays_still_require_installed_package(
        node_module, no_ament_share, monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    config = {"robot": {"model": "not_installed"},
              "profile": str(tmp_path / "profile.yaml"),
              "capabilities": str(tmp_path / "capabilities.yaml")}
    with pytest.raises(ConfigError, match="not_installed"):
        node_module._robot_file_paths(config)


@pytest.mark.parametrize("key", ["profile", "capabilities"])
def test_device_rejects_other_robot_overlay(node_module, installed_rasptank, key):
    other = SRC.parent / "middleware/devices/pinky/profile/config" / f"{key}.yaml"
    config = {"robot": {"model": "rasptank_metal"}, key: str(other)}
    with pytest.raises(ConfigError, match=key):
        node_module._load_robot_settings(config)


@pytest.mark.parametrize("contents", ["[]", "null", "profile: [", "profile: {}"])
def test_device_rejects_invalid_profile(node_module, installed_rasptank, tmp_path, contents):
    overlay = tmp_path / "profile.yaml"
    overlay.write_text(contents, encoding="utf-8")
    config = {"robot": {"model": "rasptank_metal", "profile": str(overlay)}}
    with pytest.raises(ConfigError, match="profile"):
        node_module._load_robot_settings(config)


def test_device_consumes_the_validated_snapshot(node_module, installed_rasptank, monkeypatch, tmp_path):
    overlay = tmp_path / "profile.yaml"
    overlay.write_bytes((installed_rasptank / "profile.yaml").read_bytes())
    read_text = Path.read_text
    replacement = "profile:\n  model: Pinky Pro\n  max_linear_velocity: 3.0\n"

    def replace_after_read(path, *args, **kwargs):
        text = read_text(path, *args, **kwargs)
        if path == overlay:
            path.write_text(replacement, encoding="utf-8")
        return text

    monkeypatch.setattr(Path, "read_text", replace_after_read)
    profile, capabilities = node_module._load_robot_settings(
        {"robot": {"model": "rasptank_metal", "profile": str(overlay)}})
    assert profile.model == "RaspTank Metal"
    assert profile.max_linear_velocity == 0.0
    assert capabilities["teleop"] is False
