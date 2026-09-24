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

    config_dir = Path(__file__).parent.parent / "config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["runtime"] = {"mode": "hardware"}
    config["navigation"].pop("readiness", None)
    profile = RobotProfile.load(robot_config_dir("pinky_pro") / "profile.yaml")
    capabilities = yaml.safe_load((robot_config_dir("pinky_pro") / "capabilities.yaml").read_text(encoding="utf-8"))

    services = CoreServices.build(config, profile, capabilities, tmp_path / "waypoints.json")

    assert services.readiness.required is True


def test_mapping_backend_uses_slam_readiness_instead_of_amcl(tmp_path):
    from core_common.profile import RobotProfile, robot_config_dir
    from core.services import CoreServices

    config_dir = Path(__file__).parent.parent / "config"
    config = yaml.safe_load((config_dir / "rosy_default.yaml").read_text(encoding="utf-8"))
    config["runtime"] = {"mode": "hardware", "navigation_backend": "slam"}
    config["navigation"]["readiness"] = {
        "required": True,
        "profiles": {
            "localization": ["amcl", "map_server", "controller_server", "local_costmap", "global_costmap", "motor_adapter"],
            "slam": ["slam_toolbox", "controller_server", "local_costmap", "global_costmap", "motor_adapter"],
        },
    }
    profile = RobotProfile.load(robot_config_dir("pinky_pro") / "profile.yaml")
    capabilities = yaml.safe_load((robot_config_dir("pinky_pro") / "capabilities.yaml").read_text(encoding="utf-8"))

    services = CoreServices.build(config, profile, capabilities, tmp_path / "waypoints.json")

    assert services.readiness.required_components == (
        "slam_toolbox", "controller_server", "local_costmap",
        "global_costmap", "motor_adapter",
    )


def test_navigation_state_exposes_readiness_reason_to_the_device_ui(core_client):
    client, _services = core_client()

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


def test_navigation_request_is_rejected_before_mode_change_when_hardware_is_held(core_client):
    client, services = core_client()
    services.readiness.required = True

    response = client.post(
        "/api/v1/navigation/goal",
        json={"x": 1.0, "y": 0.0},
        headers={"Authorization": "Bearer rosy-dev-operator"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "HARDWARE_NOT_READY"
    assert services.modes.mode is Mode.IDLE
