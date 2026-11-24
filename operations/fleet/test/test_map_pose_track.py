"""The confirmed ceiling-camera track as a map pose anchor, and how far the camera is from odometry (2026-11-21)."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from fleet.localization.track_heading import TrackHeading
from fleet.server.auto_locate_service import AutoLocateService
from fleet.server.map_pose_service import MapPoseService
from rosy.world.state.projections.map_pose import (DEGRADED, LOCALIZED, OPERATOR_PIN, TRACK, UNKNOWN,
                                                   MapPoseConfig, MapPoseTracker, OdomSample, Sighting)

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
    assert MapPoseConfig.from_mapping({"track_anchor_robots": ["r1"], "track_modes": ["led", "motion", "marker"]}).track_modes == ("led", "motion", "marker")
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
    assert pose.anchor_source == "sighting"                 # a fresh marker stays the anchor; the track only measures
    assert pose.camera_residual_m == pytest.approx(0.16) and pose.camera_residual_deg is None   # no camera heading
    assert (pose.camera_x, pose.camera_y, pose.camera_yaw) == (pytest.approx(0.84), 0.0, None)  # what the map draws


def test_a_track_takes_over_once_the_marker_anchor_is_old():
    tr = seeded()
    late = CFG.max_anchor_age_s + 1.0
    for k in range(1, int(late)):                            # odometry keeps reporting while it drives
        assert tr.add_odom(OdomSample(k / late, 0.0, 0.0, T0 + k), T0 + k)
    assert track(tr, late, 0.84, 0.0, odom_x=1.0) is None
    pose = tr.pose(T0 + late)
    assert pose.anchor_source == TRACK and (pose.x, pose.y) == (0.84, 0.0) and pose.yaw == pytest.approx(0.0)


def test_a_heading_far_off_after_contact_with_odometry_yaw_still_reads_the_gap():
    """Site 2026-11-21 (b): the robot turned 50-90 degrees by the camera, odometry yaw changed under 5 degrees."""
    tr, travel = seeded(), TrackHeading(CFG.track_heading_min_m)
    travel.update(0.0, 0.0, True)
    heading = travel.update(0.06, 0.16, True)               # the blob really moved 0.17 m, 69 degrees off the lane
    assert travel.fresh and math.degrees(heading) == pytest.approx(69.4, abs=0.5)
    assert track(tr, 0.25, 0.06, 0.16, heading=heading, odom_x=0.06, odom_yaw=math.radians(3)) is None
    pose = tr.pose(T0 + 0.25)
    assert 50 <= abs(pose.camera_residual_deg) <= 90 and pose.bridge_turn_deg < 5
    assert math.degrees(pose.yaw) == pytest.approx(3.0)      # the travel heading is measured, it never turns the pose
    assert math.degrees(pose.camera_yaw) == pytest.approx(69.4, abs=0.5)
    late = tr.pose(T0 + 0.25 + 3.5)
    assert late.camera_residual_deg is None and late.camera_x is None   # no fresh fix, nothing to show


def test_a_turn_in_place_follows_odometry_not_the_last_travel_heading():
    """Review 2026-11-21: a kept travel heading fed every tick held the yaw at 0 through a 90 degree turn."""
    tr, travel = MapPoseTracker("r1", CFG), TrackHeading(CFG.track_heading_min_m)

    def feed(t, x, odom_yaw):
        assert tr.add_odom(OdomSample(x, 0.0, odom_yaw, T0 + t), T0 + t)
        seen = travel.update(x, 0.0, True)
        return tr.add_track((x, 0.0), seen if travel.fresh else None, T0 + t, T0 + t, "m", "m", "led")

    for k in range(4):                                       # drives east: the first travel heading starts the anchor
        assert feed(0.25 * k, 0.2 * k, 0.0) is None
    for k in range(1, 7):                                    # then turns 90 degrees where it stands
        assert feed(0.75 + 0.25 * k, 0.6, math.radians(15 * k)) is None
    pose = tr.pose(T0 + 2.25)
    assert pose.anchor_source == TRACK and math.degrees(pose.yaw) == pytest.approx(90.0)


def test_backing_up_reads_the_body_heading_not_the_travel_direction():
    tr = MapPoseTracker("r1", CFG)
    assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    assert tr.add_track((1.0, 0.0), None, T0, T0, "m", "m", "led") is None
    assert tr.add_odom(OdomSample(-0.2, 0.0, 0.0, T0 + 0.5), T0 + 0.5)      # odometry: 0.2 m backwards, facing east
    assert tr.add_track((0.8, 0.0), math.pi, T0 + 0.5, T0 + 0.5, "m", "m", "led") is None   # the camera saw it go west
    assert tr.pose(T0 + 0.5).yaw == pytest.approx(0.0)


@pytest.mark.parametrize("mode, source", [("led", TRACK), ("motion", "sighting")])
def test_the_feeder_anchors_a_listed_robot_for_the_allowed_modes_only(mode, source):
    wall = [T0]
    poses = MapPoseService(lambda: ["r1", "r2"], config=CFG, map_id=lambda: "m", wall=lambda: wall[0])
    tracker = poses._tracker("r1")
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    tracker.add_sighting(Sighting("r1", 1.0, 1.0, 0.5, T0, map_id="m"), T0, "m")
    for k in range(1, int(CFG.max_anchor_age_s) + 2):       # the marker anchor grows old: a track may take over
        wall[0] = T0 + k
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


def _service(config, track):
    wall = [T0]
    poses = MapPoseService(lambda: ["r1"], config=config, map_id=lambda: "m", wall=lambda: wall[0])
    poses._tracker("r1").add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    identity = SimpleNamespace(confirmed_track_pose=lambda robot_id: track)
    return AutoLocateService(SimpleNamespace(identity=identity, sources=()), map_pose=poses), poses, wall


def test_with_the_default_config_the_feeder_reads_no_track_and_changes_nothing():
    track = {"state": "CONFIRMED", "x": 1.0, "y": 1.0, "age_s": 0.0, "map_id": "m", "mode": "led"}
    service, poses, _wall = _service(MapPoseConfig(), track)
    asyncio.run(service.tick())
    assert service.track_refused == {} and poses.arbitrated_pose("r1").state == UNKNOWN


def test_a_name_that_may_have_moved_to_another_robot_ends_the_track_anchor():
    """Review 2026-11-21: after an overlap the anchor kept bridging for up to max_anchor_age_s on the wrong robot."""
    track = {"state": "CONFIRMED", "x": 0.0, "y": 0.0, "age_s": 0.0, "map_id": "m", "mode": "led"}
    service, poses, wall = _service(CFG, track)
    for k in range(1, 4):                                    # drives east until the track has a travel heading
        wall[0] = T0 + k
        poses._tracker("r1").add_odom(OdomSample(0.2 * k, 0.0, 0.0, wall[0]), wall[0])
        track.update(x=0.2 * k)
        asyncio.run(service.tick())
    assert poses.arbitrated_pose("r1").anchor_source == TRACK
    track.clear()
    track.update(state="UNKNOWN", reason="ttl")              # a name that only ran out keeps the anchor until it ages
    asyncio.run(service.tick())
    assert poses.arbitrated_pose("r1").anchor_source == TRACK
    track.update(reason="overlap")
    asyncio.run(service.tick())
    assert poses.arbitrated_pose("r1").state == UNKNOWN and service.track_refused["r1"] == "overlap"


def test_agreeing_track_hands_off_from_operator_pin_without_degraded_blip():
    tr = MapPoseTracker("r1", CFG)
    assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    assert tr.add_pin((0.0, 0.0, 0.5), T0, "m") is None
    states = []
    # Drive past both max_dead_reckon_m (1.5 m) and max_anchor_age_s (10 s) with agreeing tracks.
    steps = int(max(CFG.max_dead_reckon_m / 0.05, CFG.max_anchor_age_s / 0.5)) + 6
    for k in range(1, steps):
        t = 0.5 * k
        px = 0.05 * k
        wx, wy = px * math.cos(0.5), px * math.sin(0.5)
        assert track(tr, t, wx, wy, odom_x=px) is None
        pose = tr.pose(T0 + t)
        states.append((pose.state, pose.anchor_source))
    assert all(st == LOCALIZED for st, _ in states)
    assert states[0][1] == TRACK and states[-1][1] == TRACK
    assert tr.pose(T0 + 0.5 * (steps - 1)).yaw == pytest.approx(0.5)


def test_disagreeing_track_still_degrades_after_operator_pin():
    tr = MapPoseTracker("r1", CFG)
    assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0), T0)
    assert tr.add_pin((0.0, 0.0, 0.0), T0, "m") is None
    assert track(tr, 0.5, 0.5, 0.0, odom_x=0.0) is None   # jumped while pin is fresh: ignored, pin stays
    fresh = tr.pose(T0 + 0.5)
    assert (fresh.state, fresh.anchor_source) == (LOCALIZED, OPERATOR_PIN)
    late = CFG.max_anchor_age_s + 1.0
    for k in range(1, int(late)):
        assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + k), T0 + k)
    assert track(tr, late, 0.5, 0.0, odom_x=0.0) is None
    assert tr.pose(T0 + late).state == DEGRADED


def test_agreeing_track_hands_off_from_fresh_sighting_without_degraded_blip():
    tr = seeded()
    assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 0.25), T0 + 0.25)
    assert tr.add_sighting(Sighting("r1", 0.0, 0.0, 0.0, T0 + 0.25, map_id="m"), T0 + 0.25, "m") is True
    assert tr.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 0.5), T0 + 0.5)
    assert tr.add_sighting(Sighting("r1", 0.0, 0.0, 0.0, T0 + 0.5, map_id="m"), T0 + 0.5, "m") is True
    assert tr.pose(T0 + 0.5).state == LOCALIZED
    anchors = []
    steps = int(CFG.max_anchor_age_s / 0.5) + 6
    for k in range(1, steps):
        t = 0.5 + 0.5 * k
        x = 0.04 * k
        assert track(tr, t, x, 0.0) is None
        pose = tr.pose(T0 + t)
        assert pose.state == LOCALIZED
        anchors.append(pose.anchor_source)
    assert anchors[0] == "sighting" and anchors[-1] == TRACK
