"""A robot is named by its motion without the lamp, and D-989 can then pair it (2026-11-21)."""
from test_led_identity import _detections, _setup

from fleet.server.identity import IdentityConfig

BAY, LANE = (-0.37, 0.48), (0.85, -0.48)


def _poses(tracking, clock, **xy):
    tracking.observe_states([{"robot_id": rid, "online": True,
                              "state": {"pose": {"x": x, "y": y, "yaw": 0.0}, "velocity": {"linear": 0.0, "angular": 0.0}}}
                             for rid, (x, y) in xy.items()], now=clock.now)


def test_the_robot_that_moved_like_one_detection_gets_a_confirmed_track_without_any_lamp_request():
    clock, tracking, identity, robots = _setup()
    _poses(tracking, clock, rosy_60=(0.17, -0.09), rosy_26=(2.0, 2.0))
    _detections(tracking, clock, BAY, LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.31, 0.047), rosy_26=(2.0, 2.0))   # 0.196 m by its own map
    _detections(tracking, clock, (-0.37, 0.285), LANE)                   # 0.195 m in the camera, the other one still
    track = identity.confirmed_track_pose("rosy_60")
    assert track["state"] == "CONFIRMED" and (track["x"], track["y"]) == (-0.37, 0.285)
    assert identity.confirmed_track_pose("rosy_26")["state"] == "UNKNOWN"
    assert robots["rosy_60"].calls == [] and robots["rosy_26"].calls == []   # nobody was asked to blink


def test_motion_match_can_be_switched_off_and_never_names_on_a_mismatch():
    clock, tracking, identity, _robots = _setup(IdentityConfig(motion_match=False))
    _poses(tracking, clock, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.2, 0.0))
    _detections(tracking, clock, (-0.37, 0.28), LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"

    clock, tracking, identity, _robots = _setup()
    _poses(tracking, clock, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.2, 0.0))
    _detections(tracking, clock, (-0.37, 0.28), (0.85, -0.28))           # both detections moved: no name
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"


def test_the_site_sets_the_motion_thresholds():
    clock, tracking, identity, _robots = _setup(IdentityConfig(motion_min_move_m=0.30))
    _poses(tracking, clock, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.2, 0.0))                           # 0.20 m: under this site's 0.30 m
    _detections(tracking, clock, (-0.37, 0.28), LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"
