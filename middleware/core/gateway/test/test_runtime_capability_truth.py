"""Runtime capability truth for the physical Pinky modes (D-295)."""

from __future__ import annotations

import yaml

from core.services import CoreServices
from core_common.config import load_config
from core_common.profile import RobotProfile, robot_config_dir


def _services(tmp_path, *, mode: str, backend: str = "localization",
              deployment: str = ""):
    robot_dir = robot_config_dir("pinky_pro")
    config = {
        "robot": {"id": "rosy_19", "model": "pinky_pro"},
        "runtime": {"mode": mode, "navigation_backend": backend,
                    "deployment": deployment},
    }
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    declared = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    return CoreServices.build(config, profile, declared, tmp_path / "waypoints.json"), declared


def test_motor_mode_keeps_teleop_but_refuses_navigation_and_mapping(tmp_path):
    services, declared = _services(tmp_path, mode="motor")

    assert services.capability.supports("teleop")
    for feature in ("navigation.goal_navigation", "navigation.return_home", "slam",
                    "swarm.follow", "swarm.lead"):
        assert not services.capability.supports(feature)
    assert declared["slam"] is True  # masking must not mutate the product profile


def test_native_core_remains_inert_even_after_io_reports_odometry(tmp_path):
    services, _ = _services(tmp_path, mode="core", deployment="device")
    services.state.set_velocity(0.0, 0.0)

    for feature in ("teleop", "navigation.goal_navigation", "slam",
                    "swarm.follow"):
        assert not services.capability.supports(feature)


def test_device_environment_marks_native_core_for_runtime_gating(monkeypatch):
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    monkeypatch.setenv("ROSY_RUNTIME_MODE", "core")

    assert load_config()["runtime"]["deployment"] == "device"


def test_hardware_localization_refuses_slam_but_keeps_navigation(tmp_path):
    services, _ = _services(tmp_path, mode="hardware")

    assert services.capability.supports("navigation.goal_navigation")
    assert not services.capability.supports("slam")


def test_hardware_slam_advertises_mapping(tmp_path):
    services, _ = _services(tmp_path, mode="hardware", backend="slam")

    assert services.capability.supports("navigation.goal_navigation")
    assert services.capability.supports("slam")


def test_motor_api_advertisement_and_command_gate_agree(core_client):
    client, services = core_client(config_overrides={
        "runtime": {"mode": "motor", "navigation_backend": "localization"}})
    operator = {"Authorization": "Bearer rosy-dev-operator"}
    caps = client.get("/api/v1/system/capabilities", headers=operator).json()

    assert caps["teleop"] is True
    assert caps["slam"] is False
    assert caps["navigation"]["goal_navigation"] is False
    assert client.post("/api/v1/slam/start", headers=operator).status_code == 501
    assert client.post("/api/v1/navigation/goal", json={"x": 0.25, "y": 0},
                       headers=operator).status_code == 501
    assert services.nav.mapping_active is False


def test_native_core_api_rejects_motion_even_with_fresh_odometry(core_client):
    client, services = core_client(config_overrides={
        "runtime": {"mode": "core", "navigation_backend": "localization",
                    "deployment": "device"}})
    services.state.set_velocity(0.0, 0.0)
    operator = {"Authorization": "Bearer rosy-dev-operator"}

    caps = client.get("/api/v1/system/capabilities", headers=operator).json()
    assert caps["teleop"] is False
    assert caps["slam"] is False
    assert client.post("/api/v1/teleop", json={"linear": 0.05},
                       headers=operator).status_code == 501
    assert client.post("/api/v1/slam/start", headers=operator).status_code == 501
