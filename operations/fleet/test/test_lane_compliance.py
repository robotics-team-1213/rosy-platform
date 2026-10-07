"""D-511 2: lane compliance — signed offset, body margin, persistence, UNKNOWN."""

import math

import pytest

from core_common.robot_body import PINKY_PRO
from fleet.localization.lane_compliance import (ACT, OK, UNKNOWN, WARN, LaneComplianceConfig,
                                                LaneComplianceTracker, sample)
from fleet.localization.map_pose import MapPose
from fleet.routing.graph import build_graph
from fleet.site_map import SiteMap

HALF = PINKY_PRO.half_width_m
WIDTH = 0.3


def _graph(edges, places):
    return build_graph(SiteMap.model_validate({
        "places": [{"id": p, "name": p, "x": x, "y": y, "kind": "junction"} for p, x, y in places],
        "edges": [{"id": e, "from": a, "to": b, "polyline": line, "width_m": WIDTH, "speed_cap_mps": 0.2,
                   "direction": way} for e, a, b, line, way in edges]}))


STRAIGHT = _graph([("ab", "A", "B", [[0, 0], [2, 0]], "one_way")], [("A", 0, 0), ("B", 2, 0)])
TWO_WAY = _graph([("ab", "A", "B", [[0, 0], [2, 0]], "two_way")], [("A", 0, 0), ("B", 2, 0)])
#: Quarter circle of radius 1 around (0, 1), from (0, 0) heading +x to (1, 1) heading +y.
ARC_POINTS = [[math.sin(a), 1 - math.cos(a)] for a in (i * math.pi / 40 for i in range(21))]
CURVED = _graph([("cv", "A", "B", ARC_POINTS, "one_way")], [("A", 0, 0), ("B", 1, 1)])


def pose(x, y, yaw=0.0, state="LOCALIZED"):
    return MapPose(x, y, yaw, state, "sighting", 0.0, 0.1)


def test_straight_left_is_positive_and_margin_counts_the_body():
    lane = sample(pose(1.0, 0.05), STRAIGHT)
    assert lane.edge_id == "ab" and lane.arc_id == "ab:fwd"
    assert lane.offset_m == pytest.approx(0.05)
    assert lane.margin_m == pytest.approx(WIDTH / 2 - 0.05 - HALF)
    assert sample(pose(1.0, -0.05), STRAIGHT).offset_m == pytest.approx(-0.05)


def test_body_half_width_comes_from_the_urdf_body():
    assert sample(pose(1.0, 0.0), STRAIGHT).margin_m == pytest.approx(WIDTH / 2 - HALF)
    assert sample(pose(1.0, 0.0), STRAIGHT, body_half_width_m=0.1).margin_m == pytest.approx(0.05)


def test_two_way_edge_uses_the_arc_along_the_heading():
    ahead = sample(pose(1.0, 0.05, yaw=0.0), TWO_WAY)
    back = sample(pose(1.0, 0.05, yaw=math.pi), TWO_WAY)
    assert (ahead.arc_id, back.arc_id) == ("ab:fwd", "ab:rev")
    assert ahead.offset_m == pytest.approx(0.05) and back.offset_m == pytest.approx(-0.05)
    assert ahead.margin_m == pytest.approx(back.margin_m)


def test_curved_arc_inside_is_left_outside_is_right():
    a = math.pi / 4                                # half way round, tangent heading 45 deg
    inside = sample(pose(0.9 * math.sin(a), 1 - 0.9 * math.cos(a), yaw=a), CURVED)
    outside = sample(pose(1.1 * math.sin(a), 1 - 1.1 * math.cos(a), yaw=a), CURVED)
    assert inside.offset_m == pytest.approx(0.1, abs=0.005)    # chord sag is < 3 mm
    assert outside.offset_m == pytest.approx(-0.1, abs=0.005)


def test_not_localized_or_no_lane_is_unknown_and_restarts_the_count():
    tracker = LaneComplianceTracker(LaneComplianceConfig(persist_n=2))
    out = pose(1.0, 0.2)
    assert tracker.judge(out, STRAIGHT).act_count == 1
    for unknown in (tracker.judge(pose(1.0, 0.2, state="DEGRADED"), STRAIGHT),
                    tracker.judge(out, None), tracker.judge(None, STRAIGHT)):
        assert unknown.level == UNKNOWN and unknown.margin_m is None
        assert (unknown.warn_count, unknown.act_count) == (0, 0)
    assert tracker.judge(out, STRAIGHT).level == OK            # one sample again, not two


def test_warn_and_act_need_persist_n_consecutive_samples():
    cfg = LaneComplianceConfig(warn_margin_m=0.02, persist_n=3)
    tracker = LaneComplianceTracker(cfg)
    near = pose(1.0, WIDTH / 2 - HALF - 0.01)      # margin 0.01 < warn 0.02
    over = pose(1.0, WIDTH / 2 - HALF + 0.01)      # margin -0.01: body over the edge
    assert [tracker.judge(near, STRAIGHT).level for _ in range(3)] == [OK, OK, WARN]
    assert tracker.judge(pose(1.0, 0.0), STRAIGHT).level == OK  # a good sample resets
    levels = [tracker.judge(over, STRAIGHT).level for _ in range(3)]
    assert levels == [OK, OK, ACT]
    assert tracker.judge(near, STRAIGHT).level == WARN          # warn count kept running


CROSS = _graph([("ab", "A", "B", [[0, 0], [2, 0]], "one_way"), ("cd", "C", "D", [[1, -1], [1, 1]], "one_way")],
               [("A", 0, 0), ("B", 2, 0), ("C", 1, -1), ("D", 1, 1)])


def test_a_robot_parked_off_the_graph_is_unknown_not_act():
    tracker = LaneComplianceTracker(LaneComplianceConfig(persist_n=1))
    bay = tracker.judge(pose(1.0, 0.5), STRAIGHT)          # 0.5 m off a 0.3 m lane: a bay
    assert bay.level == UNKNOWN and bay.edge_id is None
    assert sample(pose(1.0, 0.25), STRAIGHT).edge_id == "ab"          # within width_m: judged
    assert sample(pose(1.0, 0.25), STRAIGHT, config=LaneComplianceConfig(max_lateral_m=0.2)).edge_id is None


def test_past_a_dead_end_is_unknown():
    assert sample(pose(2.05, 0.0), STRAIGHT).edge_id is None          # foot clamped to the end
    assert sample(pose(-0.05, 0.02), STRAIGHT).edge_id is None
    assert sample(pose(1.99, 0.02), STRAIGHT).edge_id == "ab"


def test_junction_picks_the_lane_along_the_heading():
    near_cross = pose(0.98, 0.06, yaw=0.0)                  # 2 cm from cd, 6 cm from ab, heading east
    lane = sample(near_cross, CROSS)
    assert lane.edge_id == "ab" and lane.offset_m == pytest.approx(0.06)
    north = sample(pose(0.98, 0.06, yaw=math.pi / 2), CROSS)
    assert north.edge_id == "cd" and north.offset_m == pytest.approx(0.02)   # left of a northbound lane
    assert sample(pose(1.5, 0.0, yaw=math.pi / 2), CROSS).edge_id is None   # across a lane
    assert sample(pose(1.0, 0.0, yaw=math.pi), STRAIGHT).edge_id is None    # backing on a one-way lane


def test_config_from_mapping_refuses_bad_values():
    assert LaneComplianceConfig.from_mapping(None) == LaneComplianceConfig()
    assert LaneComplianceConfig.from_mapping({"persist_n": 5}).persist_n == 5
    for bad in ({"persist_n": 0}, {"persist_n": 1.5}, {"warn_margin_m": -0.1},
                {"act_timeout_s": 0}, {"warn_margin_m": float("nan")}, {"typo": 1},
                {"max_lateral_m": 0}, {"heading_gate_deg": 90}, {"moving_min_m": -1}):
        with pytest.raises(ValueError):
            LaneComplianceConfig.from_mapping(bad)
