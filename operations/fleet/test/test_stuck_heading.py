"""D-607: heading reassessment is evidence, never a motion authorization."""

import asyncio
import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fleet.localization.map_pose import MapPose
from fleet.stuck.heading import reassess
from fleet.server.lane_compliance_service import LaneComplianceMonitor
from test_stuck_resolver_loop import _setup


def _inputs():
    pose = MapPose(0.0, 0.0, math.radians(170), "LOCALIZED", "bridged", 0.0, 0.1,
                   anchor_age_s=0.2, map_id="site", odom_stamp=99.9)
    view = {"map_version": 5, "pose_state": "LOCALIZED", "pose_source": "map_pose",
            "heading_source": "pose", "at": 100.0,
            "return": {"pose_stamp": 99.9, "lane_heading_deg": -170.0,
                       "edge_id": "lower", "turn_spot": False}}
    return pose, view


def test_reassessment_wraps_to_lane_direction_without_authorizing_a_turn():
    pose, view = _inputs()
    result = reassess(pose, view, now=100.1, map_id="site", map_version=5)
    assert result == {"status": "heading_compared", "turn_deg": 20.0,
                      "pose_stamp": 99.9, "edge_id": "lower", "map_version": 5,
                      "turn_spot": False}


def test_monitor_reassesses_against_current_active_map():
    pose, view = _inputs()
    maps = SimpleNamespace(active=lambda: (5, SimpleNamespace(map_id="site"), None, None))
    monitor = LaneComplianceMonitor(lambda: ["robot"],
                                    poses=SimpleNamespace(arbitrated_pose=lambda _rid: pose),
                                    site_maps=maps, wall=lambda: 100.1)
    monitor._latest["robot"] = view
    assert monitor.stuck_heading("robot")["turn_deg"] == 20.0
    maps.active = lambda: (6, SimpleNamespace(map_id="site"), None, None)
    assert monitor.stuck_heading("robot") == {"status": "lane_sample_untrusted"}
    maps.active = lambda: None
    assert monitor.stuck_heading("robot") == {"status": "pose_untrusted"}


@pytest.mark.parametrize("change", [
    {"state": "DEGRADED"}, {"age_s": 2.1}, {"age_s": -0.1},
    {"anchor_age_s": 1.6}, {"anchor_age_s": None}, {"map_id": "other"},
    {"yaw": float("nan")}, {"odom_stamp": None}, {"odom_stamp": float("inf")},
])
def test_untrusted_pose_cannot_produce_a_heading(change):
    pose, view = _inputs()
    result = reassess(replace(pose, **change), view, now=100.1, map_id="site", map_version=5)
    assert result["status"] == "pose_untrusted"
    assert "turn_deg" not in result


@pytest.mark.parametrize("change", [
    {"map_version": 4}, {"at": 97.0}, {"at": 101.0},
    {"pose_source": "led_track"}, {"heading_source": "none"},
    {"return": {"pose_stamp": 99.8, "lane_heading_deg": 0}},
    {"return": {"pose_stamp": 99.9, "lane_heading_deg": float("nan")}},
    {"return": None},
])
def test_other_or_stale_lane_sample_cannot_produce_a_heading(change):
    pose, view = _inputs()
    result = reassess(pose, {**view, **change}, now=100.1, map_id="site", map_version=5)
    assert result["status"] == "lane_sample_untrusted"
    assert "turn_deg" not in result


def test_loop_logs_each_stuck_heading_change_without_sending_realign(caplog):
    loop, _board, robot = _setup()
    loop.heading_review = lambda _rid: {"status": "heading_compared", "turn_deg": 20.0,
                                      "pose_stamp": 99.9, "edge_id": "lower",
                                      "map_version": 5, "turn_spot": False}
    with caplog.at_level("INFO", logger="fleet.stuck.loop"):
        asyncio.run(loop.run_once())
        asyncio.run(loop.run_once())
    assert len([r for r in caplog.records if "stuck heading" in r.message]) == 1
    assert not any(call[0] == "line_stuck_decision" and call[2] == "REALIGN" for call in robot.calls)
    loop.heading_review = lambda _rid: {"status": "pose_untrusted"}
    with caplog.at_level("INFO", logger="fleet.stuck.loop"):
        asyncio.run(loop.run_once())
    assert len([r for r in caplog.records if "stuck heading" in r.message]) == 2
