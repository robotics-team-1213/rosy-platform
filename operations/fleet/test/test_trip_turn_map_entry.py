"""D-759 rev 1: a left/right turn carries the exit lane's map heading (``map_entry``) only to a
robot announcing ``lane_turn_map_entry``, from the located pose that has an ``odom_stamp``."""

from __future__ import annotations

import dataclasses

import pytest

from fleet.server.console_view import trip_caps
from test_trip_caps import _caps
from test_trip_d507 import PIVOT, SW_POSE
from test_trip_runner import _arc, _plan, _setup, _ticks, run

STAMP = 1790000000.25
CAPS = dataclasses.replace(PIVOT, lane_turn_map_entry=True)


def _sw_turn(caps, stamp=STAMP):
    """The 260919 SW spoke turn (test_trip_d507), sent 0.3 m before the place."""
    runner, store, ports = _setup(caps=caps)
    arc = _arc(store, "west:rev")
    _plan(store, ports, "west:rev", arc.length_m - 0.5, "SE")
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.length_m - 0.3)
    ports.pose = dataclasses.replace(ports.pose, **SW_POSE, odom_stamp=stamp)
    _ticks(runner, ports)
    assert ports.sent[0][0] in ("left", "right")
    return runner, ports


def test_caps_read_lane_turn_map_entry():
    assert trip_caps(_caps(junction_turn=True)).lane_turn_map_entry is False
    assert trip_caps(_caps(lane_turn_map_entry=True)).lane_turn_map_entry is True
    assert trip_caps(_caps(lane_turn_map_entry="true")).lane_turn_map_entry is False


def test_a_turn_to_a_lane_turn_map_entry_robot_carries_the_exit_lanes_heading_and_the_yaw_pair():
    runner, ports = _sw_turn(CAPS)
    live = next(iter(runner._live.values()))
    exit_lane = live.arc(live.view["segment_index"] + 1)
    fields = ports.expects[0]
    assert fields["map_entry"] == {"yaw_rad": pytest.approx(exit_lane.start_tangent, abs=1e-4),
                                   "pose_yaw_rad": ports.pose.yaw, "odom_stamp_s": STAMP}
    plain = _sw_turn(PIVOT)[1].expects[0]
    assert "map_entry" not in plain
    assert {k: v for k, v in fields.items() if k != "map_entry"} == plain


def test_without_an_odom_stamp_the_turn_is_todays():
    assert "map_entry" not in _sw_turn(CAPS, stamp=None)[1].expects[0]
