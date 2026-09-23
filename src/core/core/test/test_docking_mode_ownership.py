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
