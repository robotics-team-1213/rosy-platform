"""D-767 A Fleet side: a ``lane_instruction_stamp`` robot gets ``pose_stamp`` (the odom stamp of the
pose the distances were measured from) and no latency guesses; other robots are unchanged."""

from __future__ import annotations

import dataclasses

import pytest

import fleet.server.trip_ports as trip_ports
from fleet.server.console_view import trip_caps
from test_trip_bend import BEND_CAPS, ENTRY_CAPS, SW_BEND, _bend_map, _stamped, _trip
from test_trip_caps import _caps
from fleet.swarm.transport import RobotApiError
from test_trip_d507 import PIVOT, _sent_at, _straight_map
from test_trip_runner import _free_map, _ticks

STAMP = 1790000000.25
LOW = {"expect_tol_min_m": 0.01}


def _late_send(monkeypatch):
    """The send starts 0.5 s after the pose read."""
    clock = iter([100.0, 100.5])
    monkeypatch.setattr(trip_ports, "_monotonic", lambda: next(clock, 100.5))


def test_caps_read_lane_instruction_stamp():
    assert trip_caps(_caps()).lane_instruction_stamp is False
    assert trip_caps(_caps(lane_instruction_stamp=True)).lane_instruction_stamp is True
    assert trip_caps(_caps(lane_instruction_stamp="true")).lane_instruction_stamp is False


def test_a_stamp_robot_gets_pose_stamp_and_a_window_without_send_latency(monkeypatch):
    _late_send(monkeypatch)
    caps = dataclasses.replace(PIVOT, lane_instruction_stamp=True)
    sent = _sent_at(_free_map("lane"), caps, 0.5, pose={"odom_stamp": STAMP}, **LOW).expects[0]
    assert sent["pose_stamp"] == STAMP and sent["expect_in_m"] == 0.5
    # 0.05 x 0.5 to drive + 0.2 m/s x pose age 0.1 + 0.05: no read-to-send, no SEND_ALLOWANCE_S
    assert sent["expect_tol_m"] == pytest.approx(0.095, abs=1e-6)


@pytest.mark.parametrize("stamp_cap, odom_stamp", [(False, STAMP), (True, None)])
def test_without_the_capability_or_an_odom_stamp_the_window_is_todays(monkeypatch, stamp_cap, odom_stamp):
    _late_send(monkeypatch)
    caps = dataclasses.replace(PIVOT, lane_instruction_stamp=stamp_cap)
    sent = _sent_at(_free_map("lane"), caps, 0.5, pose={"odom_stamp": odom_stamp}, **LOW).expects[0]
    assert "pose_stamp" not in sent
    assert sent["expect_tol_m"] == pytest.approx(0.235, abs=1e-6)  # 0.2 x (0.1 + 0.5 + 0.2) as before


def test_a_stamp_robot_gets_its_bend_unled_with_the_pose_stamp():
    caps = dataclasses.replace(ENTRY_CAPS, lane_instruction_stamp=True)
    fields = _trip(_bend_map(SW_BEND), caps, before=_stamped(STAMP))[2].expects[0]
    assert fields["bend_in_m"] == pytest.approx(0.4, abs=1e-3)       # no lead: CORE counts from the stamp
    assert fields["pose_stamp"] == fields["map_entry"]["odom_stamp_s"] == STAMP


@pytest.mark.parametrize("stamp_cap, stamp", [(False, STAMP), (True, None)])
def test_without_the_capability_or_an_odom_stamp_the_bend_keeps_its_lead(stamp_cap, stamp):
    caps = dataclasses.replace(BEND_CAPS, lane_instruction_stamp=stamp_cap)
    fields = _trip(_bend_map(SW_BEND), caps, before=_stamped(stamp))[2].expects[0]
    assert "pose_stamp" not in fields
    assert fields["bend_in_m"] == pytest.approx(0.38, abs=0.005)      # led 0.2 m/s x 0.1 s as before


def test_a_junction_without_a_window_carries_no_pose_stamp():
    caps = dataclasses.replace(PIVOT, lane_instruction_stamp=True)
    assert _sent_at(_straight_map(), caps, 0.6, pose={"odom_stamp": STAMP}).expects == [
        {"map_id": "site", "pivot_past_line_m": 0.1}]


def _unusable(reason):
    return RobotApiError("rosy_60", 409, "INSTRUCTION_STAMP_UNUSABLE", f"pose_stamp cannot be used: {reason}",
                         {"reason": reason})


def test_an_unusable_stamp_is_sent_again_with_the_next_pose():
    """Review: CORE refuses a stamp it cannot use; the next period sends a fresh one."""
    caps = dataclasses.replace(ENTRY_CAPS, lane_instruction_stamp=True)
    before = lambda runner: (_stamped(STAMP)(runner), setattr(runner._junction, "junction_error", _unusable("no_sample")))
    runner, _, ports, _, _ = _trip(_bend_map(SW_BEND), caps, before=before)
    view = runner.view("p1")
    assert view["state"] == "running" and ports.sent == [] and view["detail"]["junction_retry"] == "INSTRUCTION_STAMP_UNUSABLE"
    ports.junction_error = None
    ports.pose = dataclasses.replace(ports.pose, odom_stamp=STAMP + 0.5)
    _ticks(runner, ports)
    assert ports.sent[-1][0] == "bend" and ports.expects[-1]["pose_stamp"] == STAMP + 0.5
    assert ports.expects[-1]["bend_in_m"] == pytest.approx(0.4, abs=1e-3)


def test_a_disabled_stamp_stops_stamping_and_the_bend_is_led_again():
    """Review MEDIUM-2: CORE's flag is off (capability drift): this trip sends unstamped with the lead."""
    caps = dataclasses.replace(ENTRY_CAPS, lane_instruction_stamp=True)
    before = lambda runner: (_stamped(STAMP)(runner), setattr(runner._junction, "junction_error", _unusable("disabled")))
    runner, _, ports, _, _ = _trip(_bend_map(SW_BEND), caps, before=before)
    assert ports.sent == [] and runner.view("p1")["caps"]["lane_instruction_stamp"] is False
    ports.junction_error = None
    _ticks(runner, ports)
    assert ports.sent[-1][0] == "bend" and "pose_stamp" not in ports.expects[-1]
    assert ports.expects[-1]["bend_in_m"] == pytest.approx(0.38, abs=0.005)
