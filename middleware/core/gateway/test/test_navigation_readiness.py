"""Hardware motion stays in HOLD until the ROS graph is ready."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.navigation.readiness import COMPONENTS, NavigationReadinessGate
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


def test_disabled_gate_is_inert_for_core_and_simulation():
    gate = NavigationReadinessGate(required=False)

    assert gate.is_ready()
    assert gate.snapshot().reason == "disabled"


def test_required_gate_needs_every_component_and_a_fresh_motor_lease():
    now = [10.0]
    gate = NavigationReadinessGate(required=True, stale_after_s=2.0,
                                   monotonic=lambda: now[0])

    for component in COMPONENTS:
        gate.observe(component, True, now=now[0], lease=component == "motor_adapter")
    assert gate.snapshot().ready

    now[0] = 12.1
    snapshot = gate.snapshot()
    assert not snapshot.ready
    assert snapshot.missing == ("motor_adapter",)

    gate.observe("motor_adapter", True, now=now[0], lease=True)
    assert gate.snapshot().ready
    now[0] = 14.2
    snapshot = gate.snapshot()
    assert not snapshot.ready
    assert snapshot.missing == ("motor_adapter",)
    assert snapshot.reason == "missing_or_stale:motor_adapter"

    # Lifecycle state is persistent; an old ACTIVE transition does not age
    # out merely because no second transition occurred.
    now[0] = 100.0
    gate.observe("motor_adapter", True, now=now[0], lease=True)
    assert gate.snapshot().ready


def test_inactive_lifecycle_component_keeps_the_gate_in_hold():
    gate = NavigationReadinessGate(required=True)
    for component in COMPONENTS:
        gate.observe(component, component != "controller_server")

    snapshot = gate.snapshot()
    assert not snapshot.ready
    assert snapshot.missing == ("controller_server",)


def test_command_manager_returns_zero_and_rejects_teleop_while_held():
    gate = NavigationReadinessGate(required=True)
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety, readiness=gate)

    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0))
    assert command.select_output() == Twist(0.0, 0.0)

    modes.transition(Mode.MANUAL)
    accepted, reason = command.teleop(0.1, 0.0)
    assert not accepted
    assert reason == "HARDWARE_NOT_READY"


@pytest.mark.parametrize("required", [False, True])
def test_gate_rejects_non_positive_lease(required):
    with pytest.raises(ValueError):
        NavigationReadinessGate(required=required, stale_after_s=0)


def test_gate_rejects_string_component_configuration():
    with pytest.raises(ValueError):
        NavigationReadinessGate(required=True, required_components="amcl")


def test_core_services_turns_the_gate_on_for_hardware_even_without_an_overlay(tmp_path):
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    config_dir = (Path(__file__).resolve().parents[4] / "contracts") / "foundation" / "config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["runtime"] = {"mode": "hardware"}
    config["navigation"].pop("readiness", None)
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    capabilities = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))

    services = CoreServices.build(config, profile, capabilities, tmp_path / "waypoints.json")

    assert services.readiness.required is True


def test_mapping_backend_uses_slam_readiness_instead_of_amcl(tmp_path):
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    config_dir = (Path(__file__).resolve().parents[4] / "contracts") / "foundation" / "config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["runtime"] = {"mode": "hardware", "navigation_backend": "slam"}
    config["navigation"]["readiness"] = {
        "required": True,
        "profiles": {
            "localization": ["amcl", "map_server", "controller_server", "local_costmap", "global_costmap", "motor_adapter"],
            "slam": ["slam_toolbox", "controller_server", "local_costmap", "global_costmap", "motor_adapter"],
        },
    }
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    capabilities = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))

    services = CoreServices.build(config, profile, capabilities, tmp_path / "waypoints.json")

    assert services.readiness.required_components == (
        "slam_toolbox", "controller_server", "local_costmap",
        "global_costmap", "motor_adapter",
    )


def test_navigation_state_exposes_readiness_reason_to_the_device_ui(core_client):
    client, services = core_client()

    response = client.get(
        "/api/v1/navigation/state",
        headers={"Authorization": "Bearer rosy-dev-viewer"},
    )

    assert response.status_code == 200
    assert response.json()["readiness"] == {
        "required": False,
        "ready": True,
        "missing": [],
        "reason": "disabled",
    }
    assert response.json()["mapping_active"] is False
    services.nav.mapping_active = True
    assert client.get(
        "/api/v1/navigation/state",
        headers={"Authorization": "Bearer rosy-dev-viewer"},
    ).json()["mapping_active"] is True


def test_navigation_request_is_rejected_before_mode_change_when_hardware_is_held(core_client):
    client, services = core_client()
    services.readiness.required = True

    response = client.post(
        "/api/v1/navigation/goal",
        json={"x": 1.0, "y": 0.0},
        headers={"Authorization": "Bearer rosy-dev-operator"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAPABILITY_WITHHELD"
    assert response.json()["error"]["detail"]["capability"] == "navigation.goal_navigation"
    assert services.modes.mode is Mode.IDLE


def _runtime_config(mode, backend="localization"):
    defaults = Path(__file__).resolve().parents[4] / "contracts/foundation/config/rosy_default.yaml"
    config = yaml.safe_load(defaults.read_text(encoding="utf-8"))
    config["runtime"] = {"mode": mode, "navigation_backend": backend}
    config["navigation"]["readiness"]["required"] = True
    return {"runtime": config["runtime"], "navigation": config["navigation"]}


def test_motor_profile_accepts_manual_api_without_navigation_components(core_client):
    client, services = core_client(config_overrides=_runtime_config("motor"))
    services.state.set_velocity(0.0, 0.0)
    # A slow runner spent the real lease window on the requests below (merge group 2026-11-06).
    services.readiness._monotonic = lambda: 10.0
    services.readiness.observe("motor_adapter", True, lease=True)
    assert services.readiness.required_components == ("motor_adapter",)
    assert services.readiness.required and services.readiness.is_ready()
    capabilities = client.get("/api/v1/system/capabilities", headers={"Authorization": "Bearer rosy-dev-viewer"}).json()
    assert capabilities["navigation"]["goal_navigation"] is False
    assert capabilities["slam"] is False
    headers = {"Authorization": "Bearer rosy-dev-operator"}
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=headers).status_code == 200
    response = client.post("/api/v1/teleop", json={"linear": 0.02, "angular": 0.0}, headers=headers)
    assert response.status_code == 200, response.text
    assert services.command.select_output() == Twist(0.02, 0.0)


@pytest.mark.parametrize("lease", ["missing", "expired"])
def test_required_motor_profile_rejects_missing_or_expired_lease_and_outputs_zero(core_client, lease):
    client, services = core_client(config_overrides=_runtime_config("motor"))
    services.state.set_velocity(0.0, 0.0)
    now = [10.0]
    services.readiness._monotonic = lambda: now[0]
    headers = {"Authorization": "Bearer rosy-dev-operator"}
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=headers).status_code == 200
    if lease == "expired":
        services.readiness.observe("motor_adapter", True, lease=True)
        response = client.post("/api/v1/teleop", json={"linear": 0.02}, headers=headers)
        assert response.status_code == 200, response.text
        assert services.command.select_output().linear == 0.02
        now[0] += services.readiness.stale_after_s + 0.01
    response = client.post("/api/v1/teleop", json={"linear": 0.02}, headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CAPABILITY_WITHHELD"
    assert services.readiness.snapshot().missing == ("motor_adapter",)
    assert services.command.select_output() == Twist(0.0, 0.0)


@pytest.mark.parametrize("profile", ["missing_mapping", "missing_motor", "missing_adapter"])
def test_required_motor_profile_cannot_fall_back_or_omit_the_adapter(core_client, profile):
    config = _runtime_config("motor")
    readiness = config["navigation"]["readiness"]
    if profile == "missing_mapping":
        readiness.pop("profiles")
        readiness["required_components"] = ["motor_adapter"]
    elif profile == "missing_motor":
        readiness["profiles"].pop("motor", None)
        readiness["profiles"]["localization"] = ["motor_adapter"]
    else:
        readiness["profiles"]["motor"] = ["controller_server"]
    with pytest.raises(ValueError, match="motor"):
        core_client(config_overrides=config)


@pytest.mark.parametrize("mode", ["core", "motor"])
def test_disabled_legacy_gate_without_motor_profile_keeps_backend_configuration(core_client, mode):
    config = _runtime_config(mode)
    readiness = config["navigation"]["readiness"]
    readiness["required"] = False
    readiness["profiles"].pop("motor", None)
    _, services = core_client(config_overrides=config)
    assert not services.readiness.required
    assert services.readiness.is_ready()
    assert services.readiness.required_components == tuple(readiness["profiles"]["localization"])


@pytest.mark.parametrize("backend,components", [
    ("localization", ("amcl", "map_server", "controller_server", "local_costmap", "global_costmap", "motor_adapter")),
    ("slam", ("slam_toolbox", "controller_server", "local_costmap", "global_costmap", "motor_adapter")),
])
def test_hardware_profiles_still_require_every_existing_component(core_client, backend, components):
    _, services = core_client(config_overrides=_runtime_config("hardware", backend))
    assert services.readiness.required and services.readiness.required_components == components
    services.modes.transition(Mode.MANUAL)
    for missing in components:
        for component in components:
            services.readiness.observe(component, component != missing, lease=component == "motor_adapter")
        assert services.readiness.snapshot().missing == (missing,)
        assert services.command.teleop(0.02, 0.0) == (False, "HARDWARE_NOT_READY")
        assert services.command.select_output() == Twist(0.0, 0.0)
