"""Docking owns its own command slot and cannot outlive the DOCKING mode.

Independent review of stage 3 (parking), H1-H3: docking used to write the nav
slot, so leaving DOCKING (to IDLE, then NAVIGATION by any path) put the docking
twist on the wheels as `source='navigation'`, and Nav2 or swarm output reached
the wheels while docking. Here docking has its own slot that passes only in
DOCKING, every exit from DOCKING cancels the run, and Nav2 reaches the wheels
in DOCKING only while a staging dock is driving through Nav2.
"""

from __future__ import annotations

import math

import pytest

from core_common.protocol.schemas import DockState
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.docking.manager import DockPhase
from core.bridge import docking_mode

from test_docking_parking_wiring import OPERATOR, StillExecutor, sim_overrides


class DrivingExecutor(StillExecutor):
    """The bridge's DockingExecutor: drive/stop write the docking slot."""

    def __init__(self, services):
        self._svc = services

    def drive(self, linear, angular):
        self._svc.command.set_docking_twist(Twist(linear, angular))

    def stop(self):
        self._svc.command.set_docking_twist(Twist(0.0, 0.0))


def docking_robot(core_client):
    client, services = core_client(config_overrides=sim_overrides())
    services.docking.executor = DrivingExecutor(services)
    services.state.set_pose(-1.2696, 0.0, math.pi / 2)
    response = client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert services.modes.mode is Mode.DOCKING
    assert services.docking.state is DockState.DOCKING
    return client, services


def wheels(services):
    out = services.command.select_output()
    return out.linear, out.angular


# --- the slot split ---------------------------------------------------------


def test_the_docking_slot_reaches_the_wheels_only_in_docking(core_client):
    _, services = docking_robot(core_client)
    services.command.set_docking_twist(Twist(0.03, 0.1))
    assert wheels(services) == pytest.approx((0.03, 0.1))
    services.modes.transition(Mode.IDLE)
    services.modes.transition(Mode.NAVIGATION)
    services.command.set_docking_twist(Twist(0.03, 0.1))
    assert wheels(services) == (0.0, 0.0)


def test_the_nav_slot_does_not_reach_the_wheels_in_docking(core_client):
    _, services = docking_robot(core_client)
    services.command.set_nav_twist(Twist(0.2, 0.0))
    assert wheels(services) == (0.0, 0.0)


# --- every exit from DOCKING cancels docking ---------------------------------


def test_mode_idle_mid_dock_cancels_docking_and_navigation_never_carries_it(core_client):
    client, services = docking_robot(core_client)
    assert client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=OPERATOR).status_code == 200
    assert services.docking.state is DockState.UNDOCKED
    services.modes.transition(Mode.NAVIGATION)
    services.docking.tick()
    assert wheels(services) == (0.0, 0.0)


def test_manual_outranks_docking_and_taking_it_cancels_docking(core_client):
    client, services = docking_robot(core_client)
    response = client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert services.modes.mode is Mode.MANUAL
    assert services.docking.state is DockState.UNDOCKED
    services.docking.tick()
    assert wheels(services) == (0.0, 0.0)


def test_leaving_docking_directly_on_the_mode_machine_cancels_docking(core_client):
    _, services = docking_robot(core_client)
    ok, _ = services.modes.transition(Mode.IDLE)
    assert ok
    assert services.docking.state is DockState.UNDOCKED


def test_an_emergency_fails_docking(core_client):
    client, services = docking_robot(core_client)
    client.post("/api/v1/safety/stop", headers=OPERATOR)
    assert services.docking.state is DockState.DOCK_FAILED


def test_the_bridge_release_after_a_finished_run_changes_nothing(core_client):
    _, services = docking_robot(core_client)
    services.docking.cancel()
    assert docking_mode.release_docking_mode(services)
    assert services.docking.state is DockState.UNDOCKED
    assert services.modes.mode is Mode.IDLE


def test_line_follow_is_refused_while_docking(core_client):
    client, services = docking_robot(core_client)
    response = client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"},
                          headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCKING_ACTIVE"
    assert services.docking.state is DockState.DOCKING
    assert services.modes.mode is Mode.DOCKING
    assert not services.line_follow.active


# --- nav_cmd_vel routing (ros_bridge._on_nav_cmd_vel) --------------------------


def test_nav_cmd_vel_is_dropped_in_docking_outside_staging(core_client):
    _, services = docking_robot(core_client)
    assert services.docking.phase is not DockPhase.STAGING
    assert not docking_mode.route_nav_cmd_vel(services, Twist(0.2, 0.0))
    assert wheels(services) == (0.0, 0.0)


def test_nav_cmd_vel_drives_a_staging_dock(core_client):
    _, services = docking_robot(core_client)
    services.docking._phase = DockPhase.STAGING
    assert docking_mode.route_nav_cmd_vel(services, Twist(0.1, 0.0))
    assert wheels(services) == pytest.approx((0.1, 0.0))


def test_nav_cmd_vel_drives_navigation(core_client):
    _, services = core_client(config_overrides=sim_overrides())
    services.modes.transition(Mode.NAVIGATION)
    assert docking_mode.route_nav_cmd_vel(services, Twist(0.1, 0.0))
    assert wheels(services) == pytest.approx((0.1, 0.0))


def test_nav_cmd_vel_is_dropped_while_line_following(core_client):
    _, services = core_client(config_overrides=sim_overrides())
    services.modes.transition(Mode.NAVIGATION)
    services.line_follow.set_mode("CAMERA_LINE")
    assert not docking_mode.route_nav_cmd_vel(services, Twist(0.1, 0.0))


# --- H2: the mode is checked before the manager is touched --------------------


class RecordingExecutor(DrivingExecutor):
    def __init__(self, services):
        super().__init__(services)
        self.calls = []

    def navigate_to(self, pose):
        self.calls.append(("navigate_to", pose))

    def drive(self, linear, angular):
        self.calls.append(("drive", linear, angular))
        super().drive(linear, angular)


def manual_robot(core_client):
    client, services = core_client(config_overrides=sim_overrides())
    executor = RecordingExecutor(services)
    services.docking.executor = executor
    services.state.set_pose(-1.2696, 0.0, math.pi / 2)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"},
                       headers=OPERATOR).status_code == 200
    return client, services, executor


def test_undock_from_manual_leaves_a_docked_robot_docked(core_client):
    client, services, executor = manual_robot(core_client)
    services.docking._state = DockState.DOCKED
    services.docking._dock = services.docking.database.get("parking")
    response = client.post("/api/v1/docking/undock", headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert services.docking.state is DockState.DOCKED
    assert services.docking.status().dock_id == "parking"
    assert services.modes.mode is Mode.MANUAL
    assert executor.calls == []


def test_dock_from_manual_changes_nothing(core_client):
    client, services, executor = manual_robot(core_client)
    response = client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert services.docking.state is DockState.UNDOCKED
    assert services.docking.status().dock_id is None
    assert services.modes.mode is Mode.MANUAL
    assert executor.calls == []


def test_a_staging_dock_from_manual_sends_no_staging_goal(core_client):
    from core_features.docking.database import DockInstance, DockType
    client, services, executor = manual_robot(core_client)
    services.docking.database.add_type(DockType(name="std", detector="simulated"))
    services.docking.database.add(DockInstance(id="std1", type="std", x=1.0, y=0.0, yaw=0.0))
    response = client.post("/api/v1/docking/dock", json={"dock": "std1"}, headers=OPERATOR)
    assert response.status_code == 409
    assert executor.calls == []
    assert services.docking.state is DockState.UNDOCKED


# --- H3: taking DOCKING cancels Nav2 and swarm; navigation refuses meanwhile ---


class NavExecutor:
    def __init__(self):
        self.sent, self.cancelled = [], 0

    def send_goal(self, spec):
        self.sent.append(spec)

    def cancel_goal(self):
        self.cancelled += 1


def navigating_robot(core_client):
    from core_features.navigation.manager import NavGoalSpec
    client, services = core_client(config_overrides=sim_overrides())
    services.docking.executor = DrivingExecutor(services)
    services.state.set_pose(-1.2696, 0.0, math.pi / 2)
    nav_exec = NavExecutor()
    services.nav.executor = nav_exec
    services.modes.transition(Mode.NAVIGATION)
    services.nav.goal(NavGoalSpec(x=1.0, y=0.0, yaw=0.0))
    return client, services, nav_exec


def test_taking_docking_cancels_the_nav2_goal(core_client):
    from core_common.protocol.schemas import NavigationState
    client, services, nav_exec = navigating_robot(core_client)
    response = client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert nav_exec.cancelled >= 1
    assert services.nav.nav_state is NavigationState.CANCELED
    assert services.modes.mode is Mode.DOCKING


def test_taking_docking_closes_a_swarm_moving_goal_session(core_client):
    client, services, nav_exec = navigating_robot(core_client)
    services.nav.cancel()
    services.nav.open_moving_session()
    closed = []
    services.nav.session_closed_listener = closed.append
    client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert services.nav._moving_session is None
    assert closed == ["docking"]


def test_navigation_refuses_goals_while_docking(core_client):
    from core_features.navigation.manager import NavGoalSpec, NavigationError
    _, services, nav_exec = navigating_robot(core_client)
    services.nav.cancel()
    services.docking.dock("parking")
    sent = len(nav_exec.sent)
    for call in (lambda: services.nav.goal(NavGoalSpec(x=1.0, y=0.0, yaw=0.0)),
                 lambda: services.nav.moving_goal(NavGoalSpec(x=1.0, y=0.0, yaw=0.0))):
        with pytest.raises(NavigationError) as excinfo:
            call()
        assert excinfo.value.code == "DOCKING_ACTIVE"
    assert len(nav_exec.sent) == sent


def test_nav2_and_swarm_output_during_docking_never_reach_the_wheels(core_client):
    _, services, _ = navigating_robot(core_client)
    services.docking.dock("parking")
    assert services.docking.phase is not DockPhase.STAGING
    docking_mode.route_nav_cmd_vel(services, Twist(0.2, 0.3))
    assert wheels(services) == (0.0, 0.0)


# --- M2: the battery auto-return takes DOCKING through the same seam ----------


def test_the_battery_return_takes_docking_and_cancels_navigation(core_client):
    from core_common.protocol.schemas import BatteryLevel, NavigationState
    _, services, nav_exec = navigating_robot(core_client)
    services.docking.on_battery_level(BatteryLevel.WARNING)
    assert services.docking.state is DockState.DOCKING
    assert services.modes.mode is Mode.DOCKING
    assert services.nav.nav_state is NavigationState.CANCELED


def test_the_battery_return_waits_while_manual(core_client):
    from core_common.protocol.schemas import BatteryLevel
    client, services, executor = manual_robot(core_client)
    services.docking.on_battery_level(BatteryLevel.WARNING)
    assert services.docking.state is DockState.UNDOCKED
    assert services.docking.return_pending
    assert services.modes.mode is Mode.MANUAL
    assert executor.calls == []
    client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=OPERATOR)
    services.docking.tick()
    assert services.docking.state is DockState.DOCKING
    assert services.modes.mode is Mode.DOCKING


# --- M1: every dock type takes DOCKING; a default dock stages through Nav2 ----


def default_dock_robot(core_client):
    from core_features.docking.database import DockInstance, DockType
    client, services = core_client(config_overrides=sim_overrides())
    executor = RecordingExecutor(services)
    services.docking.executor = executor
    services.docking.database.add_type(DockType(name="std", detector="simulated"))
    services.docking.database.add(DockInstance(id="std1", type="std", x=1.0, y=0.0, yaw=0.0))
    return client, services, executor


def test_a_default_dock_takes_docking_and_stages_through_nav2(core_client):
    from core_common.protocol.schemas import NavigationState
    client, services, executor = default_dock_robot(core_client)
    response = client.post("/api/v1/docking/dock", json={"dock": "std1"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert services.modes.mode is Mode.DOCKING
    assert services.docking.phase is DockPhase.STAGING
    assert [c[0] for c in executor.calls] == ["navigate_to"]
    # Nav2's staging output reaches the wheels as docking ...
    assert docking_mode.route_nav_cmd_vel(services, Twist(0.1, 0.05))
    assert wheels(services) == pytest.approx((0.1, 0.05))
    # ... and stops doing so once staging ends.
    services.docking.on_navigation_state(NavigationState.ARRIVED)
    services.docking.tick()
    assert services.docking.phase is DockPhase.ACQUIRING
    assert not docking_mode.route_nav_cmd_vel(services, Twist(0.1, 0.05))


def test_a_default_dock_approach_drives_the_docking_slot(core_client):
    client, services, executor = default_dock_robot(core_client)
    client.post("/api/v1/docking/dock", json={"dock": "std1"}, headers=OPERATOR)
    services.docking._phase = DockPhase.APPROACHING
    executor.drive(0.06, 0.2)
    assert wheels(services) == pytest.approx((0.06, 0.2))


def test_a_default_undock_takes_docking_and_releases_it_when_done(core_client):
    client, services, executor = default_dock_robot(core_client)
    services.docking._state = DockState.DOCKED
    services.docking._dock = services.docking.database.get("std1")
    response = client.post("/api/v1/docking/undock", headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert services.modes.mode is Mode.DOCKING
    services.docking.tick()
    assert executor.calls[-1][0] == "drive"
    assert wheels(services)[0] < 0.0
    services.docking.cancel()
    assert docking_mode.release_docking_mode(services)
    assert services.modes.mode is Mode.IDLE


# --- M3: an exception in the docking tick fails docking and releases the mode --


def test_a_docking_tick_exception_fails_docking_and_releases_the_mode(core_client):
    _, services = docking_robot(core_client)

    def boom(now):
        raise RuntimeError("dock type deleted")

    services.docking._tick_docking = boom
    warnings = []
    docking_mode.tick(services, warnings.append)
    assert services.docking.state is DockState.DOCK_FAILED
    assert services.modes.mode is Mode.IDLE
    assert warnings and "dock type deleted" in warnings[0]
    assert wheels(services) == (0.0, 0.0)


def test_the_api_refuses_to_delete_the_active_dock(core_client):
    client, services = docking_robot(core_client)
    admin = {"Authorization": "Bearer rosy-dev-admin"}
    response = client.delete("/api/v1/docking/docks/parking", headers=admin)
    assert response.status_code == 409, response.text
    assert [d.id for d in services.docking.database.list()] == ["parking"]
