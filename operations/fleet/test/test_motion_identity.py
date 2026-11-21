"""A robot is named by its motion without the lamp, and D-989 can then pair it (2026-11-21)."""
import asyncio

from test_led_identity import _confirm, _detections, _setup

from fleet.server.identity import IdentityConfig

BAY, LANE = (-0.37, 0.48), (0.85, -0.48)
ON = IdentityConfig(motion_match=True)   # off by default: the site opts in


def _poses(tracking, clock, epoch=0, age_s=0.0, **xy):
    """What a real Pinky reports: wheel odometry and no localization status."""
    tracking.observe_states([{"robot_id": rid, "online": True,
                              "state": {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "pose_frame": None, "localization": None,
                                        "velocity": {"linear": 0.0, "angular": 0.0},
                                        "odom_pose": {"x": x, "y": y, "yaw": 0.0, "stamp": clock.now - age_s,
                                                      "epoch": epoch}}}
                             for rid, (x, y) in xy.items()], now=clock.now)


def test_the_robot_that_moved_like_one_detection_gets_a_confirmed_track_without_any_lamp_request():
    clock, tracking, identity, robots = _setup(ON)
    _poses(tracking, clock, rosy_60=(0.17, -0.09), rosy_26=(2.0, 2.0))
    _detections(tracking, clock, BAY, LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.31, 0.047), rosy_26=(2.0, 2.0))   # 0.196 m by its own map
    _detections(tracking, clock, (-0.37, 0.285), LANE)                   # 0.195 m in the camera, the other one still
    track = identity.confirmed_track_pose("rosy_60")
    assert track["state"] == "CONFIRMED" and (track["x"], track["y"]) == (-0.37, 0.285)
    assert track["mode"] == "motion" and next(r for r in identity.snapshot()["robots"] if r["robot_id"] == "rosy_60")["mode"] == "motion"
    assert identity.confirmed_track_pose("rosy_26")["state"] == "UNKNOWN"
    assert robots["rosy_60"].calls == [] and robots["rosy_26"].calls == []   # nobody was asked to blink


def test_motion_match_can_be_switched_off_and_never_names_on_a_mismatch():
    clock, tracking, identity, _robots = _setup()   # the default
    _poses(tracking, clock, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.2, 0.0))
    _detections(tracking, clock, (-0.37, 0.28), LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"

    clock, tracking, identity, _robots = _setup(ON)
    _poses(tracking, clock, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.2, 0.0))
    _detections(tracking, clock, (-0.37, 0.28), (0.85, -0.28))           # both detections moved: no name
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"


def test_the_site_sets_the_motion_thresholds():
    clock, tracking, identity, _robots = _setup(IdentityConfig(motion_match=True, motion_min_move_m=0.30))
    _poses(tracking, clock, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, rosy_60=(0.2, 0.0))                           # 0.20 m: under this site's 0.30 m
    _detections(tracking, clock, (-0.37, 0.28), LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"


def test_an_odometry_restart_never_counts_as_a_move():
    """A CORE restart puts odometry back at (0, 0) under a new epoch: a jump of 0.2 m that nobody drove."""
    clock, tracking, identity, _robots = _setup(ON)
    _poses(tracking, clock, epoch=3, rosy_60=(0.2, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, epoch=4, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, (-0.37, 0.28), LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"


def test_stale_odometry_is_no_pose():
    clock, tracking, identity, _robots = _setup(ON)
    _poses(tracking, clock, age_s=60.0, rosy_60=(0.0, 0.0))
    _detections(tracking, clock, BAY, LANE)
    clock.now += 1.0
    _poses(tracking, clock, age_s=60.0, rosy_60=(0.2, 0.0))
    _detections(tracking, clock, (-0.37, 0.28), LANE)
    assert identity.confirmed_track_pose("rosy_60")["state"] == "UNKNOWN"


def test_a_lamp_binding_reads_mode_led_and_an_unknown_robot_reads_none():
    clock, tracking, identity, _robots = _setup(ON)
    _confirm(clock, tracking, identity)
    assert identity.confirmed_track_pose("rosy_60")["mode"] == "led"
    assert identity.confirmed_track_pose("rosy_26")["mode"] is None
