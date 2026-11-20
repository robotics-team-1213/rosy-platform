"""The confirmed ceiling-camera track as a map pose anchor, and how far the camera is from odometry (2026-11-21)."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from fleet.server.auto_locate_service import AutoLocateService
from fleet.server.map_pose_service import MapPoseService
from rosy.world.state.projections.map_pose import (DEGRADED, LOCALIZED, TRACK, UNKNOWN, MapPoseConfig, MapPoseTracker,
                                                   OdomSample, Sighting)

T0 = 1_800_000_000.0
CFG = MapPoseConfig(track_anchor_robots=("r1",))


def seeded(config=CFG):
    """Anchored by one marker sighting at the map origin while odom reads (0, 0, 0)."""
    tr = MapPoseTracker("r1", config)
    assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    assert tr.add_sighting(Sighting("r1", 0.0, 0.0, 0.0, T0, map_id="m"), T0, "m")
    return tr


def track(tr, t, x, y, heading=None, odom_x=None, odom_yaw=0.0, mode="led"):
    assert tr.add_odom(OdomSample(x if odom_x is None else odom_x, 0.0, odom_yaw, T0 + t), T0 + t)
    return tr.add_track((x, y), heading, T0 + t, T0 + t, "m", "m", mode)


def test_by_default_no_robot_and_only_led_tracks_may_anchor():
    off = seeded(MapPoseConfig())
    off.add_odom(OdomSample(0.1, 0.0, 0.0, T0 + 0.25), T0 + 0.25)
    assert off.add_track((0.1, 0.0), None, T0 + 0.25, T0 + 0.25, "m", "m", "led") == "DISABLED"
    assert off.pose(T0 + 0.25).anchor_source == "sighting"
    on = seeded()
    on.add_odom(OdomSample(0.1, 0.0, 0.0, T0 + 0.25), T0 + 0.25)
    assert on.add_track((0.1, 0.0), None, T0 + 0.25, T0 + 0.25, "m", "m", "motion") == "DISABLED"
    assert MapPoseConfig.from_mapping({"track_anchor_robots": ["r1"], "track_modes": ["led", "motion"]}).track_modes == ("led", "motion")
    with pytest.raises(ValueError):
        MapPoseConfig.from_mapping({"track_modes": ["blob"]})


def test_a_track_without_a_heading_needs_an_anchor_to_take_its_yaw_from():
    tr = MapPoseTracker("r1", CFG)
    assert track(tr, 0.0, 1.0, 1.0) is None
    assert tr.pose(T0).state == UNKNOWN                      # nothing to bridge a heading from
    assert track(tr, 0.25, 1.1, 1.0, heading=0.3) is None
    pose = tr.pose(T0 + 0.25)
    assert pose.anchor_source == TRACK and pose.yaw == pytest.approx(0.3) and (pose.x, pose.y) == (1.1, 1.0)


def test_odometry_that_reports_arrival_while_the_camera_shows_it_short_reads_the_gap():
    """Site 2026-11-21 (a): odometry says 1.00 m, the camera 0.84 m; a camera that re-anchors every frame must not hide it."""
    tr = seeded()
    assert tr.pose(T0).camera_residual_m is None            # one fix, nothing to compare with
    for k in range(1, 6):
        assert track(tr, 0.25 * k, 0.84 * k / 5, 0.0, odom_x=0.2 * k) is None
    pose = tr.pose(T0 + 1.25)
    assert pose.anchor_source == TRACK and pose.state == LOCALIZED
    assert pose.camera_residual_m == pytest.approx(0.16) and pose.camera_residual_deg is None   # no camera heading


def test_a_heading_far_off_after_contact_with_odometry_yaw_still_reads_the_gap():
    """Site 2026-11-21 (b): the robot turned 50-90 degrees by the camera, odometry yaw changed under 5 degrees."""
    tr = seeded()
    assert track(tr, 0.25, 0.05, 0.14, heading=math.radians(70), odom_x=0.05, odom_yaw=math.radians(3)) is None
    pose = tr.pose(T0 + 0.25)
    assert 50 <= abs(pose.camera_residual_deg) <= 90 and pose.bridge_turn_deg < 5
    assert pose.state == DEGRADED                            # the sighting's jump rule, unchanged
    assert tr.pose(T0 + 0.25 + 3.5).camera_residual_deg is None   # no fresh fix, no residual


@pytest.mark.parametrize("mode, source", [("led", TRACK), ("motion", "sighting")])
def test_the_feeder_anchors_a_listed_robot_for_the_allowed_modes_only(mode, source):
    wall = [T0]
    poses = MapPoseService(lambda: ["r1", "r2"], config=CFG, map_id=lambda: "m", wall=lambda: wall[0])
    tracker = poses._tracker("r1")
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    tracker.add_sighting(Sighting("r1", 1.0, 1.0, 0.5, T0, map_id="m"), T0, "m")
    wall[0] = T0 + 0.5
    tracker.add_odom(OdomSample(0.1, 0.0, 0.0, wall[0]), wall[0])
    track = {"state": "CONFIRMED", "x": 1.1, "y": 1.0, "age_s": 0.0, "map_id": "m", "mode": mode}
    identity = SimpleNamespace(confirmed_track_pose=lambda robot_id: track)
    service = AutoLocateService(SimpleNamespace(identity=identity, sources=()), map_pose=poses)
    asyncio.run(service.tick())
    pose = poses.arbitrated_pose("r1")
    assert pose.anchor_source == source
    assert service.track_refused["r1"] == (None if mode == "led" else "DISABLED")
    assert "r2" not in service.track_refused            # not listed: never fed
    if mode == "led":
        assert (pose.x, pose.y, pose.yaw) == (1.1, 1.0, pytest.approx(0.5))   # camera position, odometry-bridged yaw
