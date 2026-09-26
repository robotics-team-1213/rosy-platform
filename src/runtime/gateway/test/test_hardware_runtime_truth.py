"""Hardware presence and drive readiness come from live evidence (D-32, D-192).

Field evidence (rosy-pinky-e4us, release 2026.09.24-010): the image default is
CORE-only (`runtime.mode: core`). The operator started `rosy-io` in no-motion
mode: battery 8.69 V and 10 Hz lidar arrived, bringup published
`motor/ready: false` and did not subscribe `cmd_vel`. The API still advertised
teleop and five available motion descriptors, and the dashboard said the
hardware runtime was off. Each test below pins one of those.
"""

from __future__ import annotations

import time

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
NAV_COMPONENTS = ("amcl", "map_server", "controller_server", "local_costmap", "global_costmap")


def _no_motion_io(svc):
    """What `rosy-io` with ROSY_IO_DRIVE_ENABLED=false feeds CORE."""
    svc.state.set_battery(100.0, 8.69)
    svc.state.set_velocity(0.0, 0.0)
    svc.state.set_pose(0.0, 0.0, 0.0)
    svc.readiness.observe("motor_adapter", False, lease=True)


def _caps(tc):
    return tc.get("/api/v1/system/capabilities", headers=VIEWER).json()


def _rows(tc):
    body = tc.get("/api/v1/system/inventory", headers=VIEWER).json()
    return {row["id"]: row for row in body["descriptors"]}


# --- 1. presence: the mode string is not evidence ----------------------------

def test_core_mode_without_samples_is_hardware_off(core_client):
    tc, _svc = core_client()
    runtime = _caps(tc)["runtime"]
    assert runtime["mode"] == "core"
    assert runtime["hardware"] == "off"
    assert runtime["evidence"] == []
    assert runtime["drive"] == "unknown"


def test_no_motion_io_is_hardware_on_with_drive_disabled(core_client):
    tc, svc = core_client()
    _no_motion_io(svc)
    runtime = _caps(tc)["runtime"]
    assert runtime["mode"] == "core"
    assert runtime["hardware"] == "on"
    assert set(runtime["evidence"]) == {"odometry", "battery"}
    assert runtime["drive"] == "disabled"
    assert runtime["navigation"] == "absent"


def test_battery_alone_proves_the_runtime_but_not_a_drive(core_client):
    tc, svc = core_client()
    svc.state.set_battery(100.0, 8.69)
    caps = _caps(tc)
    assert caps["runtime"]["hardware"] == "on"
    assert caps["runtime"]["evidence"] == ["battery"]
    assert caps["teleop"] is False
    assert caps["withheld"]["reasons"]["teleop"] == "drive_absent"


def test_a_runtime_that_went_quiet_is_silent_not_on(core_client):
    tc, svc = core_client()
    _no_motion_io(svc)
    later = time.time() + 60.0
    svc.state._clock = lambda: later
    caps = _caps(tc)
    assert caps["runtime"]["hardware"] == "silent"
    assert caps["withheld"]["reasons"]["teleop"] == "hardware_silent"


# --- 2. capabilities: motion needs motor/ready, navigation needs Nav2 --------

def test_no_motion_withholds_motion_with_the_precise_reason(core_client):
    tc, svc = core_client()
    _no_motion_io(svc)
    caps = _caps(tc)
    assert caps["teleop"] is False
    assert caps["navigation"]["goal_navigation"] is False
    assert caps["swarm"] == {"follow": False, "lead": False}
    assert caps["slam"] is False
    reasons = caps["withheld"]["reasons"]
    for flag in ("teleop", "navigation.goal_navigation", "navigation.return_home",
                 "swarm.follow", "swarm.lead"):
        assert reasons[flag] == "drive_disabled:no_motion", flag
    # Localizing does not move the base; it is missing Nav2/SLAM instead.
    assert reasons["slam"] == "navigation_absent"
    assert caps["withheld"]["reason"] == "drive_disabled:no_motion"

    rows = _rows(tc)
    assert rows["mobility.move"]["available"] is False
    assert rows["mobility.move"]["reason"] == "drive_disabled:no_motion"
    assert rows["mobility.navigate"]["reason"] == "drive_disabled:no_motion"
    assert rows["perception.localize"]["reason"] == "navigation_absent"
    assert all(row["state"] == "blocked" for row in rows.values())


def test_ready_drive_without_nav2_keeps_teleop_only(core_client):
    tc, svc = core_client()
    _no_motion_io(svc)
    svc.readiness.observe("motor_adapter", True, lease=True)
    caps = _caps(tc)
    assert caps["runtime"]["drive"] == "ready"
    assert caps["teleop"] is True
    assert caps["swarm"] == {"follow": True, "lead": True}
    assert caps["navigation"]["goal_navigation"] is False
    assert caps["withheld"]["reasons"] == {
        "navigation.goal_navigation": "navigation_absent",
        "navigation.return_home": "navigation_absent",
        "slam": "navigation_absent",
    }


def test_ready_drive_and_nav2_keep_every_flag(core_client):
    tc, svc = core_client()
    _no_motion_io(svc)
    svc.readiness.observe("motor_adapter", True, lease=True)
    for component in NAV_COMPONENTS:
        svc.readiness.observe(component, True)
    caps = _caps(tc)
    assert caps["runtime"]["navigation"] == "ready"
    assert caps["teleop"] is True
    assert caps["navigation"]["goal_navigation"] is True
    assert "withheld" not in caps


def test_expired_motor_lease_withholds_motion(core_client):
    tc, svc = core_client()
    _no_motion_io(svc)
    svc.readiness.observe("motor_adapter", True, lease=True,
                          now=time.monotonic() - 30.0)
    caps = _caps(tc)
    assert caps["runtime"]["drive"] == "stale"
    assert caps["withheld"]["reasons"]["teleop"] == "drive_lease_expired"


def test_simulator_bench_without_motor_ready_keeps_its_capabilities(core_client):
    """gz_multi: CORE-only with simulated odometry and no motor/ready topic."""
    tc, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)
    caps = _caps(tc)
    assert caps["runtime"]["drive"] == "unknown"
    assert caps["runtime"]["navigation"] == "unknown"
    assert caps["teleop"] is True
    assert "withheld" not in caps


# --- 3. precedence: a missing runtime outlives an e-stop ---------------------

def test_runtime_reason_precedes_safe_stop_and_both_are_listed(core_client):
    from core_common.protocol.schemas import HealthState

    tc, svc = core_client()
    svc.state.set_diagnostic("drive", HealthState.OK)
    assert tc.post("/api/v1/safety/stop",
                   headers={"Authorization": "Bearer rosy-dev-operator"}).status_code == 200
    rows = _rows(tc)
    for row in rows.values():
        assert row["reason"] == "runtime_mode:core"
        assert row["reasons"] == ["runtime_mode:core", "device_state:SAFE_STOP"]


def test_drive_reason_precedes_safe_stop(core_client):
    from core_common.protocol.schemas import HealthState

    tc, svc = core_client()
    _no_motion_io(svc)
    svc.state.set_diagnostic("drive", HealthState.OK)
    svc.safety.trigger_estop("api:operator")
    row = _rows(tc)["mobility.move"]
    assert row["reasons"] == ["drive_disabled:no_motion", "device_state:SAFE_STOP"]


def test_safe_stop_alone_is_still_the_reason(core_client):
    from core_common.protocol.schemas import HealthState

    tc, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)
    svc.state.set_diagnostic("drive", HealthState.OK)
    svc.safety.trigger_estop("api:operator")
    row = _rows(tc)["mobility.move"]
    assert row["reason"] == "device_state:SAFE_STOP"
    assert row["reasons"] == ["device_state:SAFE_STOP"]


# --- 5. maps: say which snapshots exist before a client asks -----------------

def test_runtime_names_which_map_snapshots_exist(core_client):
    tc, svc = core_client()
    assert _caps(tc)["runtime"]["maps"] == {"occupancy": False, "global_costmap": False}
    grid = {"width": 2, "height": 1, "resolution": 0.05,
            "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "data": [0, 100]}
    svc.maps.set_map(grid)
    assert _caps(tc)["runtime"]["maps"] == {"occupancy": True, "global_costmap": False}
    assert tc.get("/api/v1/map", headers=VIEWER).status_code == 200


# --- readiness gate: one component's report, gate required or not ------------

@pytest.mark.parametrize("active, age, expected", [
    (True, 0.0, "ready"),
    (False, 0.0, "inactive"),
    (True, 5.0, "stale"),
])
def test_component_state(active, age, expected):
    from core_features.navigation.readiness import NavigationReadinessGate

    gate = NavigationReadinessGate(required=False, stale_after_s=2.0, monotonic=lambda: 100.0)
    assert gate.component_state("motor_adapter") == "unobserved"
    gate.observe("motor_adapter", active, now=100.0 - age, lease=True)
    assert gate.component_state("motor_adapter") == expected


def test_component_state_without_lease_never_goes_stale():
    from core_features.navigation.readiness import NavigationReadinessGate

    gate = NavigationReadinessGate(required=False, monotonic=lambda: 1000.0)
    gate.observe("amcl", True, now=0.0)
    assert gate.component_state("amcl") == "ready"
