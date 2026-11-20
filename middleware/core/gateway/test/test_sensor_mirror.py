"""bridge/sensor_mirror.py: values served by GET /sensors/{imu,odometry,wheels,motor,dock_observation}."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

import pytest

from core.bridge.sensor_mirror import SensorMirror


def _xyz(x=0.0, y=0.0, z=0.0):
    return NS(x=x, y=y, z=z)


def _hdr(sec=3, nanosec=7, frame="f"):
    return NS(stamp=NS(sec=sec, nanosec=nanosec), frame_id=frame)


def _mirror(period=0.1):
    clock = [0.0]
    m = SensorMirror(min_period_s=period, monotonic=lambda: clock[0], wall=lambda: 99.0)
    return m, clock


def _imu(pitch=0.0, ax=0.0):
    q = NS(x=0.0, y=math.sin(pitch / 2), z=0.0, w=math.cos(pitch / 2))
    return NS(header=_hdr(), orientation=q, angular_velocity=_xyz(0, 0, .3),
              linear_acceleration=_xyz(ax, 0, 9.8))


def test_nothing_is_converted_in_the_callback():
    m, _ = _mirror()
    m.imu(object())  # would raise on any attribute access
    m.odometry(object())
    m.wheels(NS(name=["l_wheel_joint"]))  # only the name list is read
    assert m._raw.keys() == {"imu", "wheels", "odometry"}


def test_imu_carries_orientation_rates_acceleration_and_pitch():
    m, _ = _mirror()
    m.imu(_imu(pitch=0.2, ax=-1.9))
    s = m.sample("imu")
    assert s["received_at"] == 99.0 and s["source_stamp_ns"] == 3_000_000_007
    assert s["pitch_rad"] == pytest.approx(0.2) and s["roll_rad"] == pytest.approx(0.0)
    assert s["pitch_accel_rad"] == pytest.approx(math.atan2(1.9, 9.8))
    assert s["angular_velocity"]["z"] == 0.3 and s["linear_acceleration"]["x"] == -1.9
    assert s["orientation"]["w"] == pytest.approx(math.cos(0.1))
    assert s["angular_velocity_z"] == 0.3  # legacy field kept


def test_wheels_and_odometry_fields():
    m, _ = _mirror()
    m.wheels(NS(header=_hdr(), name=["caster_wheel_joint", "l_wheel_joint", "r_wheel_joint"],
                position=[9.0, 1.0, 2.0], velocity=[9.0, 0.1, 0.2], effort=[]))
    m.wheels(NS(header=_hdr(), name=["arm_joint"], position=[5.0], velocity=[], effort=[]))  # other publisher
    m.odometry(NS(header=_hdr(frame="odom"), child_frame_id="base",
                  pose=NS(pose=NS(position=_xyz(1, 2), orientation=NS(x=0, y=0, z=math.sin(.25), w=math.cos(.25)))),
                  twist=NS(twist=NS(linear=_xyz(.1), angular=_xyz(0, 0, .2)))))
    w, o = m.sample("wheels"), m.sample("odometry")
    assert w["names"] == ["l_wheel_joint", "r_wheel_joint"] and w["position"] == [1.0, 2.0]
    assert w["velocity"] == [0.1, 0.2] and w["effort"] == []
    assert o["pose"]["yaw"] == pytest.approx(0.5) and o["pose"]["x"] == 1.0
    assert o["twist"]["angular"]["z"] == 0.2 and o["child_frame_id"] == "base"


def test_callback_keeps_one_message_per_period():
    m, clock = _mirror(period=0.1)
    for t_, ax in ((0.0, 1.0), (0.05, 2.0), (0.12, 3.0)):
        clock[0] = t_
        m.imu(_imu(ax=ax))
    assert m.sample("imu")["linear_acceleration"]["x"] == 3.0
    clock[0] = 0.13
    m.imu(_imu(ax=4.0))  # inside the period: dropped
    assert m.sample("imu")["linear_acceleration"]["x"] == 3.0


def test_motor_merges_health_and_ready_and_ignores_garbage():
    m, _ = _mirror()
    m.motor_ready(True)
    assert m.sample("motor") == {"health": None, "ready": True, "received_at": 99.0}
    m.motor_health("not json")
    assert m.sample("motor")["health"] is None
    m._last.clear()
    m.motor_health('{"temp_c": 40}')
    assert m.sample("motor")["health"] == {"temp_c": 40} and m.sample("motor")["ready"] is True


def test_dock_observation_keeps_payload_and_drops_non_objects():
    m, _ = _mirror()
    m.dock_observation([1])
    assert m.sample("dock_observation") is None
    m._last.clear()
    m.dock_observation({"visible": True, "x": 0.3, "lateral_measured": 0.01})
    assert m.sample("dock_observation") == {"visible": True, "x": 0.3, "lateral_measured": 0.01,
                                            "received_at": 99.0}


def test_install_serves_through_state_and_missing_topic_is_absent():
    from core_features.state.manager import StateManager
    state = StateManager("rosy_t")
    m, _ = _mirror()
    m.install(state)
    assert state.get_sensor("imu") is None and "imu" not in state.get_sensors()
    m.imu(_imu())
    assert state.get_sensor("imu")["pitch_rad"] == 0.0 and "imu" in state.get_sensors()


def test_silent_topic_answers_missing_not_404_and_fresh_after_a_sample():
    from types import SimpleNamespace
    from core_api_web.api.v1.robot import sensor_detail
    from core_features.state.manager import StateManager
    state = StateManager("rosy_t")
    m, _ = _mirror()
    m.install(state)
    svc = SimpleNamespace(state=state)
    silent = sensor_detail("imu", None, svc)
    assert silent["evidence"] == "missing" and silent["received_at"] is None
    m._raw["imu"] = (_imu(), __import__("time").time())
    assert sensor_detail("imu", None, svc)["evidence"] == "fresh"
