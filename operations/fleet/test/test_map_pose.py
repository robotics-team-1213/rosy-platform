"""D-491 3: Fleet map pose — sighting anchors, odom bridge, LOCALIZED / DEGRADED / UNKNOWN."""

import ast
import math
from pathlib import Path

import pytest

from fleet.localization.map_pose import (BRIDGED, DEGRADED, LOCALIZED, SIGHTING, UNKNOWN,
                                         MapPoseConfig, MapPoseTracker, OdomSample, Sighting,
                                         odom_from_snapshot, sighting_from_row)

T0 = 1_800_000_000.0
ANCHOR = (1.0, 2.0, math.pi / 2)     # map pose seen by Rosy Cam while odom reads (0, 0, 0)


def odom(t, x=0.0, y=0.0, yaw=0.0):
    return OdomSample(x, y, yaw, T0 + t)


def seen(t, x=ANCHOR[0], y=ANCHOR[1], yaw=ANCHOR[2], robot="r1", quality=None):
    return Sighting(robot, x, y, yaw, T0 + t, quality)


def localized(config=MapPoseConfig()):
    """Standing still: three agreeing sightings (one anchor + two consistent) -> LOCALIZED."""
    tr = MapPoseTracker("r1", config)
    for i in range(3):
        t = 0.1 * i
        assert tr.add_odom(odom(t), T0 + t)
        assert tr.add_sighting(seen(t), T0 + t)
    assert tr.pose(T0 + 0.2).state == LOCALIZED
    return tr


def close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_never_anchored_is_unknown():
    tr = MapPoseTracker("r1")
    assert tr.pose(T0).state == UNKNOWN
    tr.add_odom(odom(0), T0)
    assert tr.pose(T0).state == UNKNOWN and tr.pose(T0).x is None


def test_first_anchor_needs_two_consistent_sightings():
    tr = MapPoseTracker("r1")
    tr.add_odom(odom(0), T0)
    tr.add_sighting(seen(0), T0)
    first = tr.pose(T0)
    assert (first.state, first.source, first.dead_reckon_m) == (DEGRADED, SIGHTING, 0.0)
    assert close((first.x, first.y, first.yaw), ANCHOR)
    tr.add_odom(odom(0.1), T0 + 0.1)
    tr.add_sighting(seen(0.1), T0 + 0.1)
    assert tr.pose(T0 + 0.1).state == DEGRADED
    tr.add_odom(odom(0.2), T0 + 0.2)
    tr.add_sighting(seen(0.2), T0 + 0.2)
    assert tr.pose(T0 + 0.2).state == LOCALIZED


def test_bridge_composes_the_rigid_odom_delta_with_rotation():
    tr = localized()
    # odom: 1 m forward along odom x and a quarter turn left; the anchor faces map +y.
    tr.add_odom(odom(1.5, x=1.0, yaw=math.pi / 2), T0 + 1.5)
    pose = tr.pose(T0 + 1.6)
    assert (pose.state, pose.source) == (LOCALIZED, BRIDGED)
    assert close((pose.x, pose.y, pose.yaw), (1.0, 3.0, -math.pi), 1e-9) or \
        close((pose.x, pose.y, pose.yaw), (1.0, 3.0, math.pi), 1e-9)
    assert pose.dead_reckon_m == pytest.approx(1.0)
    assert pose.age_s == pytest.approx(0.1)


def test_bridge_uses_the_anchor_odom_not_the_odom_origin():
    tr = MapPoseTracker("r1")
    # Robot odom already at (5, 5, pi) when first seen at the anchor.
    for i in range(3):
        t = 0.1 * i
        tr.add_odom(odom(t, 5.0, 5.0, math.pi), T0 + t)
        tr.add_sighting(seen(t), T0 + t)
    tr.add_odom(odom(0.8, 4.5, 5.0, math.pi), T0 + 0.8)    # 0.5 m forward in its own heading
    pose = tr.pose(T0 + 0.8)
    assert close((pose.x, pose.y), (1.0, 2.5), 1e-6)
    assert pose.yaw == pytest.approx(math.pi / 2)


def test_sighting_between_two_odom_samples_is_interpolated():
    tr = localized()
    tr.add_odom(odom(1.0, x=0.0), T0 + 1.0)
    # Sighting at t=1.5 arrives before the sample that brackets it: it waits.
    assert tr.add_sighting(seen(1.5, x=1.0, y=2.5), T0 + 1.6)
    tr.add_odom(odom(2.0, x=1.0), T0 + 2.0)
    # Interpolated odom at 1.5 is x=0.5, so the prediction is (1, 2.5): consistent, re-anchored.
    pose = tr.pose(T0 + 2.0)
    assert pose.state == LOCALIZED
    assert close((pose.x, pose.y), (1.0, 3.0))
    assert pose.dead_reckon_m == pytest.approx(0.5)


def test_sighting_without_odom_within_the_pair_window_is_dropped():
    tr = localized()
    tr.add_odom(odom(2.0), T0 + 2.0)
    tr.add_odom(odom(4.0), T0 + 4.0)             # a 2 s gap is too wide to interpolate
    assert tr.add_sighting(seen(3.0, x=9.0), T0 + 3.5)
    pose = tr.pose(T0 + 4.0)
    assert close((pose.x, pose.y), ANCHOR[:2])  # not re-anchored to the unpaired sighting


def test_nearest_odom_pairs_only_once_the_next_sample_cannot_bracket():
    tr = localized()
    tr.add_odom(odom(1.0, x=0.2), T0 + 1.0)
    tr.add_sighting(seen(1.2, y=2.2), T0 + 1.2)      # 0.2 s after the newest odom
    assert tr.pose(T0 + 2.4).anchor_age_s == pytest.approx(2.2)   # still waiting for odom
    tr.add_odom(odom(2.5, x=0.2), T0 + 2.5)          # 1.5 s gap: too wide to interpolate
    pose = tr.pose(T0 + 2.5)
    assert pose.state == LOCALIZED and pose.anchor_age_s == pytest.approx(1.3)
    assert close((pose.x, pose.y), (1.0, 2.2))


def test_sighting_near_an_earlier_sample_interpolates_once_the_bracket_arrives():
    tr = localized()
    tr.add_odom(odom(1.0, x=0.0), T0 + 1.0)
    tr.add_sighting(seen(1.1, y=2.1), T0 + 1.1)      # 0.1 s after: nearest would say y=2.0 + 0
    tr.add_odom(odom(1.5, x=0.5), T0 + 1.5)
    # Interpolated odom at 1.1 is x=0.1 -> predicted (1, 2.1): consistent, anchored there.
    pose = tr.pose(T0 + 1.5)
    assert pose.state == LOCALIZED
    assert close((pose.x, pose.y), (1.0, 2.5), 1e-6)
    assert pose.dead_reckon_m == pytest.approx(0.4)


def test_jump_degrades_reanchors_and_recovers_after_two_consistent():
    tr = localized()
    tr.add_odom(odom(1.0), T0 + 1.0)
    tr.add_sighting(seen(1.0, x=1.3), T0 + 1.0)      # 0.30 m off the prediction
    pose = tr.pose(T0 + 1.0)
    assert pose.state == DEGRADED and pose.x == pytest.approx(1.3)   # re-anchored
    tr.add_odom(odom(1.1), T0 + 1.1)
    tr.add_sighting(seen(1.1, x=1.3), T0 + 1.1)
    assert tr.pose(T0 + 1.1).state == DEGRADED
    tr.add_odom(odom(1.2), T0 + 1.2)
    tr.add_sighting(seen(1.2, x=1.3), T0 + 1.2)
    assert tr.pose(T0 + 1.2).state == LOCALIZED


def test_heading_jump_degrades():
    tr = localized()
    tr.add_odom(odom(1.0), T0 + 1.0)
    tr.add_sighting(seen(1.0, yaw=ANCHOR[2] + math.radians(25)), T0 + 1.0)
    assert tr.pose(T0 + 1.0).state == DEGRADED


def test_a_jump_interrupts_recovery():
    tr = localized()
    tr.add_odom(odom(1.0), T0 + 1.0)
    tr.add_sighting(seen(1.0, x=1.3), T0 + 1.0)
    tr.add_odom(odom(1.1), T0 + 1.1)
    tr.add_sighting(seen(1.1, x=1.3), T0 + 1.1)
    tr.add_odom(odom(1.2), T0 + 1.2)
    tr.add_sighting(seen(1.2, x=1.0), T0 + 1.2)      # jumps back: count restarts
    tr.add_odom(odom(1.3), T0 + 1.3)
    tr.add_sighting(seen(1.3, x=1.0), T0 + 1.3)
    assert tr.pose(T0 + 1.3).state == DEGRADED


def test_dead_reckon_limit_degrades_until_new_sightings_agree():
    tr = localized()
    for i in range(1, 17):                            # 1.6 m along odom x, no sightings
        tr.add_odom(odom(0.2 + 0.1 * i, x=0.1 * i), T0 + 0.2 + 0.1 * i)
    pose = tr.pose(T0 + 1.8)
    assert pose.dead_reckon_m == pytest.approx(1.6)
    assert pose.state == DEGRADED
    # The prediction (1, 3.6) still agrees: one sighting is not enough after the limit.
    tr.add_odom(odom(1.9, x=1.6), T0 + 1.9)
    tr.add_sighting(seen(1.9, y=3.6), T0 + 1.9)
    assert tr.pose(T0 + 1.9).state == DEGRADED
    tr.add_odom(odom(2.0, x=1.6), T0 + 2.0)
    tr.add_sighting(seen(2.0, y=3.6), T0 + 2.0)
    assert tr.pose(T0 + 2.0).state == LOCALIZED


def test_stale_odom_is_unknown():
    tr = localized()
    assert tr.pose(T0 + 3.1).state == LOCALIZED
    assert tr.pose(T0 + 3.3).state == UNKNOWN


def test_out_of_order_and_repeated_odom_is_ignored():
    tr = localized()
    assert not tr.add_odom(odom(0.2, x=5.0), T0 + 0.3)        # same stamp again
    assert not tr.add_odom(odom(0.1, x=5.0), T0 + 0.3)        # older
    assert tr.pose(T0 + 0.3).x == pytest.approx(ANCHOR[0])


def test_out_of_order_and_repeated_sightings_are_ignored():
    tr = localized()
    assert not tr.add_sighting(seen(0.2, x=9.0), T0 + 0.3)
    assert not tr.add_sighting(seen(0.15, x=9.0), T0 + 0.3)
    assert tr.pose(T0 + 0.3).x == pytest.approx(ANCHOR[0])


def test_future_timestamps_are_refused():
    tr = localized()
    assert not tr.add_odom(odom(1.0, x=0.1), T0 + 0.4)            # 0.6 s ahead > 0.5 s
    assert not tr.add_sighting(seen(1.0, x=3.0), T0 + 0.9)          # 0.1 s ahead > 0.05 s
    pose = tr.pose(T0 + 0.4)
    assert pose.x == pytest.approx(ANCHOR[0])
    assert (pose.odom_refused, pose.odom_refused_reason) == (1, "future")


def test_odom_inside_the_skew_allowance_is_accepted():
    tr = localized()
    assert tr.add_odom(odom(0.7, x=0.1), T0 + 0.3)                 # robot clock 0.4 s ahead


def test_stale_wrong_robot_and_low_quality_sightings_are_ignored():
    tr = localized()
    tr.add_odom(odom(2.0), T0 + 2.0)
    assert not tr.add_sighting(seen(0.9, x=9.0), T0 + 2.0)                # outside the 1 s lease
    assert not tr.add_sighting(seen(2.0, x=9.0, robot="r2"), T0 + 2.0)
    assert not tr.add_sighting(seen(2.0, x=9.0, quality=0.2), T0 + 2.0)
    assert tr.add_sighting(seen(2.0, quality=0.9), T0 + 2.0)
    assert tr.pose(T0 + 2.0).x == pytest.approx(ANCHOR[0])


def test_snapshot_adapter_reads_odom_pose_or_none():
    assert odom_from_snapshot({"pose": {"x": 1}}) is None
    assert odom_from_snapshot(None) is None
    expected = OdomSample(1.0, 2.0, 0.5, 1791331200.0)
    assert odom_from_snapshot({"odom_pose": {"x": 1, "y": 2, "yaw": 0.5, "stamp": 1791331200.0}}) == expected
    assert odom_from_snapshot({"odom_pose": {"x": 1, "y": 2, "yaw": 0.5,          # ISO also read
                                              "stamp": "2026-10-07T00:00:00Z"}}) == expected
    for bad in ({"x": 1, "y": 2, "yaw": 0, "stamp": "2026-10-07T00:00:00"},       # no zone
                {"x": 1, "y": 2, "yaw": 0, "stamp": float("inf")},
                {"x": 1, "y": 2, "yaw": 0, "stamp": True},
                {"x": 1, "y": 2, "yaw": 0, "stamp": None},
                {"x": True, "y": 2, "yaw": 0, "stamp": "2026-10-07T00:00:00Z"},
                {"x": float("nan"), "y": 2, "yaw": 0, "stamp": "2026-10-07T00:00:00Z"},
                {"x": 1, "y": 2, "stamp": "2026-10-07T00:00:00Z"}):
        assert odom_from_snapshot({"odom_pose": bad}) is None


def test_sighting_row_adapter():
    row = {"robot_id": "r1", "x": 1, "y": 2, "yaw": 0.1, "captured_at": T0, "quality": None,
           "source_id": "cam", "age_ms": 3}
    assert sighting_from_row(row) == Sighting("r1", 1.0, 2.0, 0.1, T0, None)
    assert sighting_from_row({**row, "x": "1"}) is None
    assert sighting_from_row({**row, "robot_id": None}) is None


@pytest.mark.parametrize("raw", [{"max_dead_reckon_m": 0}, {"max_jump_m": -1}, {"max_jump_deg": 181},
                                 {"max_odom_age_s": float("inf")}, {"min_quality": 1.5},
                                 {"max_pair_s": 0.5, "max_interp_gap_s": 0.3}, {"max_jump_m": True},
                                 {"unknown_key": 1}])
def test_config_refuses_out_of_range(raw):
    with pytest.raises(ValueError):
        MapPoseConfig.from_mapping(raw)


def test_config_defaults_are_the_adr_values():
    cfg = MapPoseConfig.from_mapping(None)
    assert (cfg.max_dead_reckon_m, cfg.max_jump_m, cfg.max_jump_deg, cfg.max_odom_age_s,
            cfg.max_pair_s, cfg.sighting_lease_s) == (1.5, 0.15, 20.0, 3.0, 0.25, 1.0)


def test_map_pose_is_stdlib_only_and_never_reads_tracking():
    path = Path(__file__).resolve().parents[1] / "fleet" / "localization" / "map_pose.py"
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    assert names <= {"__future__", "math", "collections", "dataclasses", "datetime", "typing"}
    assert not any("tracking" in name for name in names)


def _localized_at(odom_yaw, map_yaw):
    tr = MapPoseTracker("r1")
    for i in range(3):
        t = 0.1 * i
        tr.add_odom(odom(t, yaw=odom_yaw), T0 + t)
        tr.add_sighting(seen(t, yaw=map_yaw), T0 + t)
    return tr


def test_yaw_interpolation_across_plus_minus_pi():
    tr = _localized_at(math.pi - 0.1, 0.0)
    tr.add_odom(odom(1.0, yaw=math.pi - 0.05), T0 + 1.0)
    tr.add_sighting(seen(1.25, yaw=0.1), T0 + 1.3)
    tr.add_odom(odom(1.5, yaw=-math.pi + 0.05), T0 + 1.5)      # crossed +-pi
    pose = tr.pose(T0 + 1.5)
    assert pose.state == LOCALIZED and pose.source == BRIDGED
    assert pose.yaw == pytest.approx(0.15)


def test_jump_check_wraps_heading():
    tr = _localized_at(0.0, math.pi - 0.05)
    tr.add_odom(odom(1.0), T0 + 1.0)
    tr.add_sighting(seen(1.0, yaw=-math.pi + 0.05), T0 + 1.0)   # 0.1 rad off, not 2*pi - 0.1
    assert tr.pose(T0 + 1.0).state == LOCALIZED


def test_odom_reset_after_reboot_drops_the_anchor():
    tr = localized()
    tr.add_odom(odom(1.0, x=0.5), T0 + 1.0)
    assert tr.pose(T0 + 1.0).state == LOCALIZED
    tr.add_odom(odom(1.1, x=0.0), T0 + 1.1)                     # CORE restart: odom back at 0
    pose = tr.pose(T0 + 1.1)
    assert (pose.state, pose.x) == (UNKNOWN, None)
    tr.add_odom(odom(1.2), T0 + 1.2)
    assert tr.pose(T0 + 1.2).state == UNKNOWN                   # until a sighting re-anchors
    tr.add_sighting(seen(1.2), T0 + 1.2)
    assert tr.pose(T0 + 1.2).state == DEGRADED


def test_odom_gap_and_resume_after_unknown_drop_the_anchor():
    tr = localized()
    assert tr.pose(T0 + 60).state == UNKNOWN
    tr.add_odom(odom(60.0), T0 + 60)                            # same place, after a 60 s gap
    assert tr.pose(T0 + 60).state == UNKNOWN
    # Resumed late: the previous sample is still recent by stamp but went stale meanwhile.
    tr = localized()
    tr.add_odom(odom(2.0), T0 + 5.5)
    assert tr.pose(T0 + 5.5).state == UNKNOWN


def test_pending_sighting_is_dropped_when_it_goes_stale():
    tr = MapPoseTracker("r1")
    assert tr.add_sighting(seen(0.0), T0)                       # no odom at all yet
    tr.pose(T0 + 3.5)                                           # older than max_odom_age_s
    tr.add_odom(odom(0.0), T0 + 3.6)                            # would bracket it exactly
    assert tr.pose(T0 + 3.6).state == UNKNOWN


def test_odom_refusals_are_counted_with_the_last_reason():
    tr = localized()
    assert not tr.add_odom(odom(0.1, x=0.1), T0 + 0.3)
    assert not tr.add_odom(odom(0.2), T0 + 0.3)                 # the same sample twice: not counted
    pose = tr.pose(T0 + 0.3)
    assert (pose.odom_refused, pose.odom_refused_reason) == (1, "out_of_order")


def test_rotation_budget_degrades_a_spin_in_place():
    tr = localized()
    for i in range(1, 17):                                      # 16 x 20 deg = 320 deg
        tr.add_odom(odom(0.2 + 0.1 * i, yaw=math.radians(20 * i)), T0 + 0.2 + 0.1 * i)
        if i == 9:                                              # one U-turn is still fine
            assert tr.pose(T0 + 1.1).state == LOCALIZED
    pose = tr.pose(T0 + 1.8)
    assert pose.dead_reckon_m == 0.0 and pose.state == DEGRADED


def test_impossible_turn_rate_is_an_odom_reset():
    tr = localized()
    tr.add_odom(odom(0.3, yaw=math.radians(90)), T0 + 0.3)      # 90 deg in 0.1 s
    assert tr.pose(T0 + 0.3).state == UNKNOWN


def test_anchor_age_degrades_without_new_sightings():
    tr = localized()
    for i in range(1, 25):
        tr.add_odom(odom(0.2 + 0.5 * i), T0 + 0.2 + 0.5 * i)
    pose = tr.pose(T0 + 9.9)
    assert pose.state == LOCALIZED and pose.anchor_age_s == pytest.approx(9.7)
    pose = tr.pose(T0 + 12.2)
    assert pose.state == DEGRADED and pose.anchor_age_s == pytest.approx(12.0)


def test_another_map_id_starts_a_new_anchor():
    tr = MapPoseTracker("r1")
    for i in range(3):
        t = 0.1 * i
        tr.add_odom(odom(t), T0 + t)
        tr.add_sighting(Sighting("r1", 1.0, 2.0, 0.0, T0 + t, map_id="a"), T0 + t)
    assert tr.pose(T0 + 0.2).map_id == "a"
    tr.add_odom(odom(0.3), T0 + 0.3)
    tr.add_sighting(Sighting("r1", 1.0, 2.0, 0.0, T0 + 0.3, map_id="b"), T0 + 0.3)
    pose = tr.pose(T0 + 0.3)
    assert (pose.map_id, pose.state) == ("b", DEGRADED)


def test_jump_while_degraded_by_dead_reckoning_restarts_the_count():
    tr = localized()
    for i in range(1, 17):
        tr.add_odom(odom(0.2 + 0.1 * i, x=0.1 * i), T0 + 0.2 + 0.1 * i)
    tr.add_odom(odom(1.9, x=1.6), T0 + 1.9)
    tr.add_sighting(seen(1.9, x=1.4, y=3.6), T0 + 1.9)          # 0.4 m off: jump
    tr.add_odom(odom(2.0, x=1.6), T0 + 2.0)
    tr.add_sighting(seen(2.0, x=1.4, y=3.6), T0 + 2.0)
    assert tr.pose(T0 + 2.0).state == DEGRADED                  # one consistent after the jump
    tr.add_odom(odom(2.1, x=1.6), T0 + 2.1)
    tr.add_sighting(seen(2.1, x=1.4, y=3.6), T0 + 2.1)
    assert tr.pose(T0 + 2.1).state == LOCALIZED


def test_huge_numbers_are_malformed_not_a_crash():
    assert odom_from_snapshot({"odom_pose": {"x": 10 ** 400, "y": 0, "yaw": 0,
                                              "stamp": "2026-10-07T00:00:00Z"}}) is None
    assert odom_from_snapshot({"odom_pose": {"x": 0, "y": 0, "yaw": 0, "stamp": "9999-99-99"}}) is None
    assert odom_from_snapshot("not a mapping") is None


def _late_odom_run(odom_period, odom_lat, cam_period, cam_lat, dur=20.0, v=0.2):
    """Robot drives at v along map x; odom and sightings are delivered late, in arrival order."""
    tr = MapPoseTracker("r1")
    events = [(k * odom_period + odom_lat, "o", k * odom_period) for k in range(int(dur / odom_period))]
    events += [(j * cam_period + cam_lat, "s", j * cam_period) for j in range(int(dur / cam_period))]
    states = []
    for at, kind, t in sorted(events):
        if kind == "o":
            tr.add_odom(odom(t, x=v * t), T0 + at)
        else:
            tr.add_sighting(seen(t, x=1.0 + v * t, yaw=0.0), T0 + at)
        states.append(tr.pose(T0 + at).state)
    return states[len(states) // 2:]


@pytest.mark.parametrize("odom_lat, cam_lat", [(0.3, 0.02), (0.5, 0.15), (0.05, 0.15)])
def test_odom_arriving_later_than_sightings_still_localizes(odom_lat, cam_lat):
    assert set(_late_odom_run(1.0, odom_lat, 0.1, cam_lat)) == {LOCALIZED}


def test_heartbeat_read_by_a_half_second_poll_still_localizes():
    tr = MapPoseTracker("r1")
    events = []
    for k in range(20):                    # 1 Hz heartbeat, seen at the next 0.5 s poll (phase 0.4)
        deliver = math.ceil((k - 0.4) / 0.5) * 0.5 + 0.4
        events.append((deliver if deliver >= k else deliver + 0.5, "o", float(k)))
    events += [(j * 0.1 + 0.15, "s", j * 0.1) for j in range(200)]
    states = []
    for at, kind, t in sorted(events):
        if kind == "o":
            tr.add_odom(odom(t, x=0.2 * t), T0 + at)
        else:
            tr.add_sighting(seen(t, x=1.0 + 0.2 * t, yaw=0.0), T0 + at)
        states.append(tr.pose(T0 + at).state)
    assert set(states[len(states) // 2:]) == {LOCALIZED}


def test_waiting_sightings_are_not_displaced_by_newer_ones():
    tr = localized()
    for j in range(1, 8):                                       # 0.3 .. 0.9, odom not yet here
        assert tr.add_sighting(seen(0.2 + 0.1 * j), T0 + 0.2 + 0.1 * j)
    tr.add_odom(odom(1.0), T0 + 1.0)
    pose = tr.pose(T0 + 1.0)
    assert pose.state == LOCALIZED and pose.anchor_age_s == pytest.approx(0.1)


def test_active_map_frame_filters_and_degrades():
    tr = MapPoseTracker("r1")
    for i in range(3):
        t = 0.1 * i
        tr.add_odom(odom(t), T0 + t)
        tr.add_sighting(Sighting("r1", 1.0, 2.0, 0.0, T0 + t, map_id="a"), T0 + t, active_map_id="a")
    assert tr.pose(T0 + 0.2, active_map_id="a").state == LOCALIZED
    assert not tr.add_sighting(Sighting("r1", 1.0, 2.0, 0.0, T0 + 0.25, map_id="b"), T0 + 0.25,
                               active_map_id="a")
    assert tr.pose(T0 + 0.25, active_map_id="a").sightings_filtered_map_id == 1
    assert tr.pose(T0 + 0.25, active_map_id="b").state == DEGRADED   # the site map changed
