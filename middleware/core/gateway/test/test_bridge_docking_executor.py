"""`BridgeDockingExecutor` — the bridge's DockingExecutor, without rclpy.

It lived inline in `ros_bridge.py`, which host pytest cannot import, so the
docking slot writes, the undock distance and the latched exemption were checked
by source greps at best. The ROS actions arrive as callables; these tests pass
recorders in their place.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core.bridge.docking_executor import BridgeDockingExecutor
from core_features.navigation.manager import NavGoalSpec


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []


def build(pose=None):
    rec = Recorder()
    odom = {"pose": pose}
    services = SimpleNamespace(
        nav=SimpleNamespace(
            external_goal_sent=lambda: rec.events.append(("external_goal_sent",))),
        command=SimpleNamespace(
            set_docking_twist=lambda twist: rec.events.append(("docking_twist", twist))),
    )
    executor = BridgeDockingExecutor(
        services,
        send_goal=lambda spec: rec.events.append(("send_goal", spec)),
        cancel_goal=lambda: rec.events.append(("cancel_goal",)),
        publish_exemption=lambda on: rec.events.append(("exemption", on)),
        odom_pose=lambda: odom["pose"],
        info=lambda msg: rec.events.append(("info", msg)),
    )
    return executor, rec, odom


def test_drive_writes_the_docking_slot():
    executor, rec, _ = build()
    executor.drive(0.06, -0.2)
    [(kind, twist)] = rec.events
    assert kind == "docking_twist"
    assert (twist.linear, twist.angular) == (0.06, -0.2)


def test_stop_writes_a_zero_twist_to_the_docking_slot():
    executor, rec, _ = build()
    executor.drive(0.06, 0.1)
    executor.stop()
    kind, twist = rec.events[-1]
    assert kind == "docking_twist"
    assert (twist.linear, twist.angular) == (0.0, 0.0)


def test_navigate_to_marks_the_external_goal_before_sending_it():
    executor, rec, _ = build()
    executor.navigate_to(SimpleNamespace(x=1.0, y=2.0, yaw=0.5))
    assert [e[0] for e in rec.events] == ["external_goal_sent", "send_goal"]
    spec = rec.events[1][1]
    assert isinstance(spec, NavGoalSpec)
    assert (spec.x, spec.y, spec.yaw) == (1.0, 2.0, 0.5)


def test_cancel_navigation_cancels_the_goal():
    executor, rec, _ = build()
    executor.cancel_navigation()
    assert rec.events == [("cancel_goal",)]


def test_exemption_publish_is_idempotent():
    executor, rec, _ = build()
    executor.set_collision_exemption(False)   # already off at start: no publish
    assert rec.events == []
    executor.set_collision_exemption(True)
    executor.set_collision_exemption(True)
    executor.set_collision_exemption(False)
    executor.set_collision_exemption(False)
    published = [e[1] for e in rec.events if e[0] == "exemption"]
    assert published == [True, False]
    assert all(type(on) is bool for on in published)
    assert ("info", "docking collision exemption on") in rec.events
    assert ("info", "docking collision exemption off") in rec.events


def test_exemption_publishes_a_truthy_value_as_bool():
    executor, rec, _ = build()
    executor.set_collision_exemption(1)
    assert [e for e in rec.events if e[0] == "exemption"] == [("exemption", True)]


def test_travelled_distance_is_measured_from_the_mark():
    executor, _, odom = build(pose=(1.0, 1.0, 0.3))
    executor.reset_odometry_mark()
    assert executor.travelled_m() == 0.0
    odom["pose"] = (1.0 - 0.15, 1.0 - 0.2, 0.3)
    assert executor.travelled_m() == pytest.approx(0.25)


def test_without_odometry_nothing_is_travelled_and_nothing_is_available():
    executor, _, odom = build(pose=None)
    assert executor.odometry_available() is False
    assert executor.odometry_pose() is None
    executor.reset_odometry_mark()          # mark is None: no baseline
    odom["pose"] = (3.0, 4.0, 0.0)
    assert executor.odometry_available() is True
    assert executor.travelled_m() == 0.0    # safe answer: "not far enough yet"


def test_travelled_is_zero_before_any_mark():
    executor, _, _ = build(pose=(2.0, 0.0, math.pi))
    assert executor.travelled_m() == 0.0


def test_odometry_pose_is_the_last_odom_pose():
    executor, _, odom = build(pose=(0.5, -0.5, 1.0))
    assert executor.odometry_pose() == (0.5, -0.5, 1.0)
    odom["pose"] = (0.6, -0.5, 1.1)
    assert executor.odometry_pose() == (0.6, -0.5, 1.1)
