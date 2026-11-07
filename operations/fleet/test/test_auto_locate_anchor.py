"""D-989 7: a robot opted in anchors trips on the auto-locate transform; every other robot is untouched."""

import asyncio
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from fleet.localization.auto_locate import (ALIGNED, DRIVE_MAX_EXTRAPOLATION_M, DRIVE_MAX_RESIDUAL_M, DRIVE_MIN_SPAN_M,
                                            Fit)
from fleet.localization.auto_locate import DEGRADED as DEGRADED_FIT
from fleet.localization.pose_request import overhead_decision
from fleet.localization.stuck_heading import reassess
from fleet.server.auto_locate_service import AutoLocateService
from fleet.server.map_pose_service import MapPoseService
from fleet.server.trip_runner import TripRunner
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
    return tracker.add_auto_locate((x, y, yaw), T0 + t, T0 + t, map_id, "m", 0.0)


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
    assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0, T0, "m", "m", 0.0) == "DISABLED"


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
    assert tracker.pose(T0 + 1, "m", auto_locate=True).state == DEGRADED
    feed(tracker, 2)
    feed(tracker, 3)
    pose = tracker.pose(T0 + 3, "m", auto_locate=True)
    assert (pose.state, pose.anchor_source, pose.x) == (LOCALIZED, AUTO_LOCATE, 1.0)


def test_dropping_ends_the_anchor_at_once():
    tracker = localized()
    tracker.drop_auto_locate()
    assert tracker.pose(T0 + 3, "m", auto_locate=True).state == UNKNOWN


def test_dropping_leaves_a_sighting_anchor_alone():
    tracker = fed()
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 1), T0 + 1)
    tracker.add_sighting(sighting(1), T0 + 1, "m")
    tracker.drop_auto_locate()
    assert tracker.pose(T0 + 1, "m").anchor_source == "sighting"


def test_an_unfed_anchor_ages_out():
    tracker = localized()
    for t in range(4, 7):
        tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + t), T0 + t)
    assert tracker.pose(T0 + 6, "m", auto_locate=True).state == LOCALIZED  # 3 s: the limit itself
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 7), T0 + 7)
    assert tracker.pose(T0 + 7, "m", auto_locate=True).state == DEGRADED


def test_another_map_or_a_stale_sample_is_refused():
    tracker = fed()
    assert feed(tracker, 1, map_id="other") == "MAP_NOT_ACTIVE"
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 5), T0 + 5)
    assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0 + 1, T0 + 5, "m", "m", 0.0) == "STALE_SAMPLE"


def test_a_sighting_that_disagrees_blocks_auto_locate_until_a_new_session():
    tracker = localized()
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 4), T0 + 4)
    tracker.add_sighting(sighting(4, x=1.3), T0 + 4, "m")
    assert tracker.pose(T0 + 4, "m").state == DEGRADED
    assert feed(tracker, 5) == "INDEPENDENT_ANCHOR_DISAGREES"
    assert tracker.auto_blocked is True
    tracker.allow_auto_locate()
    assert tracker.auto_blocked is False


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
    pose = localized().pose(T0 + 3, "m", auto_locate=True)
    assert overhead_decision({"request_id": "req-1", "reason": "x"}, pose) is None
    assert reassess(pose, {}, now=T0 + 3, map_id="m", map_version=1) == {"status": "pose_untrusted"}


def test_every_consumer_but_the_allowlist_sees_no_auto_anchor():
    tracker = localized()
    assert tracker.pose(T0 + 3, "m").state == UNKNOWN
    assert tracker.odom_to_map() is None
    assert tracker.pose(T0 + 3, "m", auto_locate=True).state == LOCALIZED


def test_the_allowlist_is_exactly_the_trip_runner_and_the_readback():
    root = Path(__file__).resolve().parents[1] / "fleet"
    callers = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py")
                     if "driving_pose" in p.read_text(encoding="utf-8"))
    assert callers == ["server/pose/map_pose_service.py", "server/trips/trip_runner.py"]


def test_anchor_age_counts_from_the_camera_not_the_sample():
    tracker = fed()
    for t in (1, 2, 3):
        tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + t), T0 + t)
        assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0 + t, T0 + t, "m", "m", float(t + 20)) is None
    pose = tracker.pose(T0 + 3, "m", auto_locate=True)
    assert pose.anchor_age_s == pytest.approx(21.0, abs=1.1)  # a trip start's 2 s check refuses this


def test_a_block_outlives_a_session_and_lifts_on_a_fresh_agreeing_sample():
    tracker = fed()
    for t in (1, 2):
        tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + t), T0 + t)
        tracker.add_sighting(sighting(t), T0 + t, "m")
    assert feed(tracker, 3, x=1.3) is None
    assert tracker.auto_blocked is True
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, T0 + 4), T0 + 4)
    assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0 + 4, T0 + 4, "m", "m", 30.0) == "INDEPENDENT_ANCHOR_DISAGREES"
    assert tracker.add_auto_locate((1.0, 2.0, 0.0), T0 + 4, T0 + 4, "m", "m", 0.5) is None
    assert tracker.auto_blocked is False


# --- the service, across a session and after it --------------------------------------------


def state(x=1.0, y=0.3, *, loc="LOCALIZED", map_id="slam", odom=None, stamp=T0):
    ox, oy = (x, y) if odom is None else odom
    return {"pose": {"x": x, "y": y, "yaw": 0.1}, "map_id": map_id,
            "odom_pose": {"x": ox, "y": oy, "yaw": 0.1, "stamp": stamp}, "safety": {"estop": False},
            "localization": {"state": loc, "pose_frame": "map", "unmapped_objects": [], "objects_stamp": None}}


PATH_M = [(0.0, 0.0), (0.3, 0.0), (0.6, 0.1), (1.0, 0.3)]


class Rig:
    def __init__(self, config=ON, path=PATH_M):
        self.mono, self.wall = 0.0, T0
        self.state = state(*path[-1])
        self.revision = "r1"
        self.track = {"state": "UNKNOWN"}
        self.map_pose = MapPoseService(lambda: ["r1"], config=config, wall=lambda: self.wall, map_id=lambda: "world")
        self.tracking = SimpleNamespace(
            identity=SimpleNamespace(confirmed_track_pose=lambda _: self.track),
            sources=[SimpleNamespace(source_id="north", robot_ids=("r1",))],
            robot_state=lambda _: self.state, approved_revision=lambda _: self.revision)
        self.locate = AutoLocateService(self.tracking, map_pose=self.map_pose, clock=lambda: self.mono)
        self.locate.start(["r1"])
        self.fit = self.locate._trackers["r1"]
        for i, (x, y) in enumerate(path):
            self.fit.observe(float(i), self.camera(x, y), state(x, y), {})
        assert self.fit.view(float(len(path) - 1))["state"] == ALIGNED

    @staticmethod
    def camera(x, y):
        return {"state": "CONFIRMED", "x": x + 1.0, "y": y, "age_s": 0.1, "map_id": "world",
                "calibration_revision": "r1", "source_id": "north"}

    def tick(self, seconds=1.0):
        self.mono += seconds
        self.wall += seconds
        self.state = {**self.state, "odom_pose": {**self.state["odom_pose"], "stamp": self.wall}}
        odom = self.state["odom_pose"]
        self.map_pose._tracker("r1").add_odom(OdomSample(odom["x"], odom["y"], 0.1, self.wall), self.wall)
        asyncio.run(self.locate.tick())
        return self.map_pose.driving_pose("r1")

    @property
    def row(self):
        return self.locate.snapshot()["robots"][0]


def localized_rig(config=ON):
    rig = Rig(config)
    rig.mono = 3.0
    for _ in range(3):
        pose = rig.tick()
    return rig, pose


def test_on_the_transform_anchors_at_the_site_position():
    rig, pose = localized_rig()
    assert (pose.state, pose.anchor_source) == (LOCALIZED, AUTO_LOCATE)
    assert (pose.x, pose.y) == pytest.approx((2.0, 0.3), abs=1e-3)
    assert rig.map_pose.arbitrated_pose("r1").state == UNKNOWN


def test_off_the_same_rig_never_anchors():
    rig = Rig(MapPoseConfig())
    rig.mono = 3.0
    for _ in range(3):
        pose = rig.tick()
    assert pose.state == UNKNOWN
    assert (rig.row["anchor_enabled"], rig.row["state"]) == (False, ALIGNED)


def test_without_a_new_camera_sample_it_expires_inside_two_minutes():
    rig, _ = localized_rig()
    for _ in range(84):
        pose = rig.tick()
    assert pose.state == LOCALIZED and pose.anchor_age_s > 80.0
    for _ in range(6):
        pose = rig.tick()
    assert pose.state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "EXPIRED"


def test_the_camera_stays_on_while_it_anchors_and_a_new_sample_renews_it():
    rig, _ = localized_rig()
    for _ in range(80):
        rig.tick()
    assert rig.locate.stream_wanted() is True
    rig.track = rig.camera(1.0, 0.3)
    pose = rig.tick()
    assert pose.anchor_age_s < 2.0


def test_the_camera_session_still_ends_for_a_robot_that_is_off():
    rig = Rig(MapPoseConfig())
    rig.mono = 3.0
    rig.tick(120.0)
    assert rig.locate.stream_wanted() is False


def test_peer_heading_alone_stays_observation_only():
    rig = Rig()
    rig.fit._fit = Fit(0.0, 1.0, 0.0, 0.0, 0.0, "peer_heading")
    rig.mono = 3.0
    assert rig.tick().state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "OBSERVATION_ONLY_EVIDENCE"


def test_a_short_baseline_cannot_drive():
    rig = Rig(path=[(0.0, 0.0), (0.3, 0.0), (0.6, 0.0)])
    rig.mono = 3.0
    assert rig.tick().state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "BASELINE_TOO_SHORT"


def test_a_loose_fit_cannot_drive():
    rig = Rig()
    fit = rig.fit._fit
    rig.fit._fit = Fit(fit.yaw, fit.tx, fit.ty, 0.06, fit.span_m, "span")
    rig.mono = 3.0
    assert rig.tick().state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "RESIDUAL_TOO_LARGE"


def test_the_stated_bound_holds():
    assert 2 * DRIVE_MAX_RESIDUAL_M / DRIVE_MIN_SPAN_M <= 0.1 + 1e-9
    assert DRIVE_MAX_RESIDUAL_M + DRIVE_MAX_EXTRAPOLATION_M * 2 * DRIVE_MAX_RESIDUAL_M / DRIVE_MIN_SPAN_M <= 0.15 + 1e-9


def test_leaving_the_sampled_region_ends_the_anchor():
    rig, _ = localized_rig()
    rig.state = state(2.2, 0.3)
    assert rig.tick().state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "OUTSIDE_SAMPLED_REGION"


def test_a_slam_restart_under_the_same_map_id_invalidates_the_fit():
    rig, _ = localized_rig()
    rig.state = state(1.0, 0.3, odom=(1.5, 0.3))  # same id, the map frame moved 0.5 m against odom
    assert rig.tick().state == UNKNOWN
    assert rig.row["state"] == DEGRADED_FIT and rig.row["reason"] == "ROBOT_MAP_JUMP"
    rig.state = state(1.0, 0.3)
    assert rig.tick().state == UNKNOWN


def test_missing_odom_fails_closed():
    rig, _ = localized_rig()
    rig.state = {**state(), "odom_pose": None}
    rig.mono += 1.0
    rig.wall += 1.0
    asyncio.run(rig.locate.tick())
    assert rig.map_pose.driving_pose("r1").state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "ODOM_UNKNOWN"


@pytest.mark.parametrize("change,reason", [
    ({"loc": "SUSPECT"}, "ROBOT_NOT_LOCALIZED"),
    ({"map_id": "other"}, "ROBOT_MAP_CHANGED"),
])
def test_losing_the_robots_own_pose_ends_the_anchor_in_one_tick(change, reason):
    rig, _ = localized_rig()
    rig.state = state(**change)
    assert rig.tick().state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == reason


def test_a_new_calibration_ends_the_anchor():
    rig, _ = localized_rig()
    rig.revision = "r2"
    assert rig.tick().state == UNKNOWN


def test_a_degraded_fit_ends_the_anchor():
    rig, _ = localized_rig()
    rig.fit.fail("CAMERA_DISAGREES")
    assert rig.tick().state == UNKNOWN


def test_no_identity_service_still_clears_the_anchor():
    rig, _ = localized_rig()
    rig.tracking.identity = None
    rig.fit.fail("CAMERA_DISAGREES")
    assert rig.tick().state == UNKNOWN


def test_one_robots_failure_clears_only_its_own_anchor():
    rig, _ = localized_rig()
    def boom(*_):
        raise RuntimeError("bad input")
    rig.fit.observe = boom
    rig.track = rig.camera(1.0, 0.3)
    assert rig.tick().state == UNKNOWN
    assert rig.row["state"] == DEGRADED_FIT


def test_a_feed_exception_clears_the_anchor():
    rig, _ = localized_rig()
    def boom(*_):
        raise RuntimeError("bad input")
    rig.fit.anchor_sample = boom
    assert rig.tick().state == UNKNOWN
    assert rig.row["anchor_refused_reason"] == "FEED_FAILED"


def test_a_dead_tick_reads_degraded_within_three_seconds():
    rig, _ = localized_rig()
    for _ in range(4):
        rig.mono += 1.0
        rig.wall += 1.0
        rig.map_pose._tracker("r1").add_odom(OdomSample(1.0, 0.3, 0.1, rig.wall), rig.wall)
    assert rig.map_pose.driving_pose("r1").state == DEGRADED


def test_switching_off_means_a_restart_and_the_pose_is_unknown():
    # No runtime toggle: the list is read at start-up. A restarted Fleet has no anchor, and the trip
    # loop closes on any pose that is not LOCALIZED (trip_steps: _stop "pose").
    rig, pose = localized_rig()
    assert pose.state == LOCALIZED
    restarted = Rig(MapPoseConfig())
    restarted.wall = rig.wall
    restarted.mono = 3.0
    assert restarted.tick().state == UNKNOWN


def test_a_new_session_does_not_lift_the_block_but_a_named_clear_does(caplog):
    rig, _ = localized_rig()
    tracker = rig.map_pose._tracker("r1")
    tracker._auto_blocked = True
    rig.mono = 10_000.0
    rig.locate.start(["r1"])
    assert tracker.auto_blocked is True and rig.row["anchor_blocked"] is True
    with caplog.at_level("WARNING", logger="fleet.auto_locate"):
        assert rig.locate.lift_block("r1", "operator-1") is True
    assert tracker.auto_blocked is False
    assert any("operator-1" in record.getMessage() for record in caplog.records)


def test_lifting_is_refused_for_a_robot_that_is_off():
    rig = Rig(MapPoseConfig())
    assert rig.locate.lift_block("r1", "operator-1") is False


def test_a_bad_robot_pose_clears_the_anchor():
    rig, _ = localized_rig()
    rig.state = {**state(), "pose": {"x": math.nan, "y": 0.0, "yaw": 0.0}}
    assert rig.tick().state == UNKNOWN


class _Poses:
    def __init__(self, on):
        self.on = on

    def auto_locate_enabled(self, _):
        return self.on


def test_a_robot_that_is_on_gets_a_stop_on_loss_even_on_a_free_arc():
    runner = TripRunner.__new__(TripRunner)
    runner._poses = _Poses(True)
    assert runner._auto_locate_on("r1") is True
    runner._poses = _Poses(False)
    assert runner._auto_locate_on("r1") is False
    runner._poses = object()
    assert runner._auto_locate_on("r1") is False
