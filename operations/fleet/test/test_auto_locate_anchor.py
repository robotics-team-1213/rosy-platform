"""D-989 7: a robot opted in anchors trips on the auto-locate transform; every other robot is untouched."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from fleet.localization.auto_locate import ALIGNED, AlignmentTracker
from fleet.localization.pose_request import overhead_decision
from fleet.localization.stuck_heading import reassess
from fleet.server.auto_locate_service import AutoLocateService
from fleet.server.map_pose_service import MapPoseService
from rosy.world.state.projections.map_pose import (AUTO_LOCATE, DEGRADED, LOCALIZED, UNKNOWN, MapPoseConfig,
                                                   MapPoseTracker, OdomSample, Sighting)

T0 = 1_700_000_000.0
ON = MapPoseConfig(auto_locate_robots=("r1",))


def fed(config=ON, *, start=T0):
    tracker = MapPoseTracker("r1", config)
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, start), start)
    return tracker


def feed(tracker, t, x=1.0, y=2.0, yaw=0.0, odom_x=0.0, map_id="m"):
    tracker.add_odom(OdomSample(odom_x, 0.0, 0.0, T0 + t), T0 + t)
    return tracker.add_auto_locate((x, y, yaw), T0 + t, T0 + t, map_id, "m")


def localized(config=ON):
    tracker = fed(config)
    for t in (1, 2, 3):
        assert feed(tracker, t) is None
    return tracker


def sighting(t, x=1.0, y=2.0):
    return Sighting("r1", x, y, 0.0, T0 + t, None, "m")


def test_off_is_the_default_and_refuses():
    assert MapPoseConfig().auto_locate_robots == ()
    tracker = fed(MapPoseConfig())
    assert feed(tracker, 1) == "DISABLED"
    assert tracker.pose(T0 + 1, "m").state == UNKNOWN


def test_a_robot_not_in_the_list_is_off():
    tracker = MapPoseTracker("r2", ON)
    assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0, T0, "m", "m") == "DISABLED"


def _run(tracker, config_calls):
    out = []
    for t, x in config_calls:
        tracker.add_odom(OdomSample(0.1 * t, 0.0, 0.0, T0 + t), T0 + t)
        tracker.add_sighting(Sighting(tracker.robot_id, x, 2.0, 0.0, T0 + t, None, "m"), T0 + t, "m")
        out.append(tracker.pose(T0 + t, "m"))
    return out


def test_off_gives_the_same_poses_as_before_the_flag():
    calls = [(1, 1.1), (2, 1.2), (3, 2.5), (4, 1.4)]
    assert _run(MapPoseTracker("r1", MapPoseConfig()), calls) == _run(MapPoseTracker("r1", ON), calls)


@pytest.mark.parametrize("raw", [{"auto_locate_robots": "r1"}, {"auto_locate_robots": [""]}, {"auto_locate_robots": [1]}])
def test_bad_config_is_refused_at_start_up(raw):
    with pytest.raises(ValueError, match="auto_locate_robots"):
        MapPoseConfig.from_mapping(raw)


def test_config_reads_a_yaml_list():
    assert MapPoseConfig.from_mapping({"auto_locate_robots": ["r1"]}).auto_locate_robots == ("r1",)


def test_on_needs_two_consistent_samples_like_a_first_sighting():
    tracker = fed()
    assert feed(tracker, 1) is None
    assert tracker.pose(T0 + 1, "m").state == DEGRADED
    feed(tracker, 2)
    feed(tracker, 3)
    pose = tracker.pose(T0 + 3, "m")
    assert (pose.state, pose.anchor_source, pose.x) == (LOCALIZED, AUTO_LOCATE, 1.0)


def test_dropping_ends_the_anchor_at_once():
    tracker = localized()
    tracker.drop_auto_locate()
    assert tracker.pose(T0 + 3, "m").state == UNKNOWN


def test_dropping_leaves_a_sighting_anchor_alone():
    tracker = fed()
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 1), T0 + 1)
    tracker.add_sighting(sighting(1), T0 + 1, "m")
    tracker.drop_auto_locate()
    assert tracker.pose(T0 + 1, "m").anchor_source == "sighting"


def test_an_unfed_anchor_ages_out():
    tracker = localized()
    for t in range(4, 15):
        tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + t), T0 + t)
    assert tracker.pose(T0 + 14, "m").state == DEGRADED


def test_another_map_or_a_stale_sample_is_refused():
    tracker = fed()
    assert feed(tracker, 1, map_id="other") == "MAP_NOT_ACTIVE"
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 5), T0 + 5)
    assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0 + 1, T0 + 5, "m", "m") == "STALE_SAMPLE"


def test_a_sighting_that_disagrees_blocks_auto_locate_until_a_new_session():
    tracker = localized()
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 4), T0 + 4)
    tracker.add_sighting(sighting(4, x=1.3), T0 + 4, "m")
    assert tracker.pose(T0 + 4, "m").state == DEGRADED
    assert feed(tracker, 5) == "INDEPENDENT_ANCHOR_DISAGREES"
    tracker.allow_auto_locate()
    assert feed(tracker, 6) is None


def test_a_later_sighting_is_not_refused_as_old_by_a_newer_sample():
    tracker = localized()
    assert tracker.add_sighting(sighting(2.5), T0 + 3.2, "m") is True
    assert tracker.pose(T0 + 3.2, "m").anchor_source == "sighting"


def test_a_fresh_sighting_stays_the_anchor():
    tracker = fed()
    for t in (1, 2, 3):
        tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + t), T0 + t)
        tracker.add_sighting(sighting(t), T0 + t, "m")
    assert feed(tracker, 4) is None
    pose = tracker.pose(T0 + 4, "m")
    assert (pose.state, pose.anchor_source) == (LOCALIZED, "sighting")


def test_a_sample_that_disagrees_with_a_sighting_is_not_taken_and_blocks():
    tracker = fed()
    for t in (1, 2):
        tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + t), T0 + t)
        tracker.add_sighting(sighting(t), T0 + t, "m")
    assert feed(tracker, 3, x=1.3) is None
    pose = tracker.pose(T0 + 3, "m")
    assert (pose.state, pose.anchor_source, pose.x) == (DEGRADED, "sighting", 1.0)
    assert feed(tracker, 4) == "INDEPENDENT_ANCHOR_DISAGREES"


def test_a_sample_that_disagrees_with_a_pin_blocks():
    tracker = fed()
    assert tracker.add_pin((1.0, 2.0, 0.0), T0, "m") is None
    assert feed(tracker, 1, x=1.3) is None
    pose = tracker.pose(T0 + 1, "m")
    assert (pose.state, pose.anchor_source) == (DEGRADED, "operator_pin")
    assert feed(tracker, 2) == "INDEPENDENT_ANCHOR_DISAGREES"


def test_consumers_that_need_independent_evidence_refuse_it():
    pose = localized().pose(T0 + 3, "m")
    assert overhead_decision({"request_id": "req-1", "reason": "x"}, pose) is None
    assert reassess(pose, {}, now=T0 + 3, map_id="m", map_version=1) == {"status": "pose_untrusted"}


# --- the service, across a session and after it --------------------------------------------


def state(x=0.6, y=0.3, *, loc="LOCALIZED", map_id="slam", stamp=T0):
    return {"pose": {"x": x, "y": y, "yaw": 0.1}, "map_id": map_id, "odom_pose": {"x": x, "y": y, "yaw": 0.1, "stamp": stamp},
            "safety": {"estop": False},
            "localization": {"state": loc, "pose_frame": "map", "unmapped_objects": [], "objects_stamp": None}}


class Rig:
    def __init__(self, config=ON):
        self.mono, self.wall = 0.0, T0
        self.state = state()
        self.revision = "r1"
        self.map_pose = MapPoseService(lambda: ["r1"], config=config, wall=lambda: self.wall, map_id=lambda: "world")
        tracking = SimpleNamespace(identity=SimpleNamespace(confirmed_track_pose=lambda _: {"state": "UNKNOWN"}),
                                   sources=[SimpleNamespace(source_id="north", robot_ids=("r1",))],
                                   robot_state=lambda _: self.state, approved_revision=lambda _: self.revision)
        self.locate = AutoLocateService(tracking, map_pose=self.map_pose, clock=lambda: self.mono)
        self.locate.start(["r1"])
        tracker = self.locate._trackers["r1"]
        for i, (x, y) in enumerate([(0.0, 0.0), (0.2, 0.0), (0.4, 0.1), (0.6, 0.3)]):
            tracker.observe(float(i), {"state": "CONFIRMED", "x": x + 1.0, "y": y, "age_s": 0.1, "map_id": "world",
                                       "calibration_revision": "r1", "source_id": "north"}, state(x, y), {})
        assert tracker.view(3.0)["state"] == ALIGNED

    def tick(self, seconds=1.0):
        self.mono += seconds
        self.wall += seconds
        self.state = {**self.state, "odom_pose": {**self.state["odom_pose"], "stamp": self.wall}}
        self.map_pose._tracker("r1").add_odom(OdomSample(0.6, 0.3, 0.1, self.wall), self.wall)
        asyncio.run(self.locate.tick())
        return self.map_pose.arbitrated_pose("r1")


def localized_rig(config=ON):
    rig = Rig(config)
    rig.mono = 3.0
    for _ in range(3):
        pose = rig.tick()
    return rig, pose


def test_on_the_transform_anchors_at_the_site_position():
    _, pose = localized_rig()
    assert (pose.state, pose.anchor_source) == (LOCALIZED, AUTO_LOCATE)
    assert (pose.x, pose.y) == pytest.approx((1.6, 0.3), abs=1e-3)


def test_off_the_same_rig_never_anchors():
    rig = Rig(MapPoseConfig())
    rig.mono = 3.0
    for _ in range(3):
        pose = rig.tick()
    assert pose.state == UNKNOWN
    row = rig.locate.snapshot()["robots"][0]
    assert (row["anchor_enabled"], row["state"]) == (False, ALIGNED)


def test_it_keeps_anchoring_after_the_session_and_expires():
    rig, _ = localized_rig()
    assert rig.tick(200.0).state != UNKNOWN  # the 120 s session is over
    assert rig.locate.stream_wanted() is False
    rig.tick(1.0)
    assert rig.tick(1.0).state == LOCALIZED
    pose = rig.tick(700.0)
    assert pose.state == UNKNOWN
    assert rig.locate.snapshot()["robots"][0]["anchor_refused_reason"] == "EXPIRED"


@pytest.mark.parametrize("change,reason", [
    ({"loc": "SUSPECT"}, "ROBOT_NOT_LOCALIZED"),
    ({"map_id": "other"}, "ROBOT_MAP_CHANGED"),
])
def test_losing_the_robots_own_pose_ends_the_anchor_in_one_tick(change, reason):
    rig, _ = localized_rig()
    rig.state = state(**change)
    assert rig.tick().state == UNKNOWN
    assert rig.locate.snapshot()["robots"][0]["anchor_refused_reason"] == reason


def test_a_new_calibration_ends_the_anchor():
    rig, _ = localized_rig()
    rig.revision = "r2"
    assert rig.tick().state == UNKNOWN


def test_a_degraded_fit_ends_the_anchor():
    rig, _ = localized_rig()
    rig.locate._trackers["r1"]._degraded = "CAMERA_DISAGREES"
    assert rig.tick().state == UNKNOWN


def test_switching_off_means_a_restart_and_the_pose_is_unknown():
    # No runtime toggle: the list is read at start-up. A restarted Fleet has no anchor, and the trip
    # loop stops on any pose that is not LOCALIZED (trip_steps: _stop "pose").
    rig, pose = localized_rig()
    assert pose.state == LOCALIZED
    restarted = Rig(MapPoseConfig())
    restarted.wall = rig.wall
    restarted.mono = 3.0
    assert restarted.tick().state == UNKNOWN


def test_a_new_session_lifts_the_block():
    rig, _ = localized_rig()
    tracker = rig.map_pose._tracker("r1")
    tracker._auto_blocked = True
    rig.mono = 200.0
    rig.locate.start(["r1"])
    assert tracker._auto_blocked is False


def test_math_is_not_nan_for_a_bad_robot_pose():
    rig, _ = localized_rig()
    rig.state = {**state(), "pose": {"x": math.nan, "y": 0.0, "yaw": 0.0}}
    assert rig.tick().state == UNKNOWN
