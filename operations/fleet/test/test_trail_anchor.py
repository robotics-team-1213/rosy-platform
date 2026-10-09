"""D-581: the ceiling camera anchors a TRAIL formation whose robots have no map pose."""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from core_common.protocol.schemas import PoseSample
from fleet.localization.map_pose import (DEGRADED, LOCALIZED, UNKNOWN, MapPose, MapPoseTracker,
                                         OdomSample, Sighting, compose, relative)
from fleet.server.map_pose_service import MapPoseService
from fleet.swarm import anchor as anchor_mod
from fleet.swarm.anchor import TrailAnchor
from fleet.swarm.relay import Relay

LEADER, FOLLOWER = "rosy_40", "rosy_41"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Poses:
    """The two MapPoseService reads the anchor uses, set directly."""

    def __init__(self):
        # map <- odom: the leader's odom starts at (1, 2) facing +y, the follower's at (0, 0).
        self.T = {LEADER: (1.0, 2.0, math.pi / 2), FOLLOWER: (0.0, 0.0, 0.0)}
        self.odom = {LEADER: (0.0, 0.0, 0.0), FOLLOWER: (0.0, 0.0, 0.0)}
        self.state = {LEADER: LOCALIZED, FOLLOWER: LOCALIZED}
        self.age = {LEADER: 0.2, FOLLOWER: 0.2}
        self.anchor_at = {LEADER: 1.0, FOLLOWER: 1.0}
        self.epoch = {LEADER: 0, FOLLOWER: 0}

    def arbitrated_pose(self, robot_id):
        x, y, yaw = compose(self.T[robot_id], self.odom[robot_id])
        return MapPose(x, y, yaw, self.state[robot_id], "bridged", 0.0, 0.0,
                       anchor_age_s=self.age[robot_id], map_id="site")

    def odom_to_map(self, robot_id):
        return (self.T[robot_id], self.odom[robot_id], self.anchor_at.get(robot_id, 1.0),
                self.epoch.get(robot_id, 0))


def frame(x, y, yaw, frame_name="odom", seq=7):
    return json.dumps({"protocol_version": "1.0", "msg_id": "m", "type": "pose", "ts": "t",
                       "payload": {"robot_id": LEADER, "pose": {"x": x, "y": y, "yaw": yaw},
                                   "seq": seq, "map_id": None, "frame": frame_name}})


def rig():
    clock, poses = Clock(), Poses()
    return TrailAnchor(poses, LEADER, [FOLLOWER], clock=clock), poses, clock


def payload(routed):
    return json.loads(routed[FOLLOWER])["payload"]


def test_the_leader_is_re_expressed_in_the_follower_odom_frame():
    anchor, poses, _ = rig()
    poses.T[FOLLOWER] = (0.5, -0.5, 0.3)
    body = payload(anchor.route(frame(0.4, 0.1, 0.2)))
    expected = relative(poses.T[FOLLOWER], compose(poses.T[LEADER], (0.4, 0.1, 0.2)))
    assert (body["pose"]["x"], body["pose"]["y"], body["pose"]["yaw"]) == pytest.approx(expected)
    assert body["frame"] == "odom" and body["anchor"] == "fleet" and body["for_robot_id"] == FOLLOWER
    assert body["map_id"] == "site" and body["anchor_age_s"] == 0.2 and body["seq"] == 7
    PoseSample.model_validate(body)                       # the shared contract reads it


def test_a_map_frame_and_a_disabled_anchor_relay_bytes_unchanged():
    anchor, _, _ = rig()
    assert anchor.route(frame(1.0, 1.0, 0.0, frame_name="map")) is None
    assert anchor.route(frame(1.0, 1.0, 0.0, frame_name=None)) is None
    off = TrailAnchor(Poses(), LEADER, [FOLLOWER], enabled=lambda: False)
    assert off.route(frame(1.0, 1.0, 0.0)) is None


@pytest.mark.parametrize("robot, change, reason", [
    (LEADER, {"state": UNKNOWN}, f"{LEADER}:no_map_pose"),
    (FOLLOWER, {"age": anchor_mod.ANCHOR_MAX_AGE_S + 0.1}, f"{FOLLOWER}:anchor_stale"),
    (FOLLOWER, {"state": DEGRADED}, f"{FOLLOWER}:map_pose_degraded"),   # never LOCALIZED yet
])
def test_a_missing_or_stale_anchor_withholds_and_says_why(robot, change, reason):
    anchor, poses, _ = rig()
    for key, value in change.items():
        getattr(poses, key)[robot] = value
    assert anchor.route(frame(0.0, 0.0, 0.0)) == {FOLLOWER: None}
    assert anchor.status()["followers"] == {FOLLOWER: reason}


def test_degraded_freezes_the_frame_for_a_short_bridge_only():
    anchor, poses, clock = rig()
    assert anchor.route(frame(0.0, 0.0, 0.0))[FOLLOWER] is not None
    poses.state[FOLLOWER] = DEGRADED
    poses.T[FOLLOWER] = (0.1, 0.0, 0.0)                   # the jumped re-anchor is not adopted
    clock.now += anchor_mod.DEGRADED_HOLD_S - 0.1
    first = payload(anchor.route(frame(0.0, 0.0, 0.0)))
    assert first["pose"]["x"] == pytest.approx(1.0)
    clock.now += 0.2
    assert anchor.route(frame(0.0, 0.0, 0.0)) == {FOLLOWER: None}


def test_degraded_on_a_new_anchor_or_a_new_odom_epoch_is_not_frozen():
    anchor, poses, clock = rig()
    anchor.route(frame(0.0, 0.0, 0.0))
    poses.state[FOLLOWER] = DEGRADED
    poses.anchor_at[FOLLOWER] = 2.0                       # the tracker re-anchored since
    clock.now += 0.1
    assert anchor.route(frame(0.0, 0.0, 0.0)) == {FOLLOWER: None}
    anchor, poses, clock = rig()
    anchor.route(frame(0.0, 0.0, 0.0))
    poses.epoch[FOLLOWER] = 1                             # an odom reset: T is from a dead frame
    poses.state[FOLLOWER] = DEGRADED
    clock.now += 0.1
    assert anchor.route(frame(0.0, 0.0, 0.0)) == {FOLLOWER: None}


def test_an_odom_reset_then_a_sighting_within_two_seconds_withholds():
    """Real tracker: CORE restarts (odom back to 0) and the camera sees the robot 0.3 s later."""
    wall = {"t": 1000.0}
    service = MapPoseService(lambda: [LEADER, FOLLOWER], wall=lambda: wall["t"])
    clock = Clock()
    anchor = TrailAnchor(service, LEADER, [FOLLOWER], clock=clock, wall=lambda: wall["t"])

    def tick(odom_l, odom_f, seen=True):
        for rid, odom, true in ((LEADER, odom_l, (1.0, 0.0, 0.0)), (FOLLOWER, odom_f, (0.5, 0.0, 0.0))):
            if seen:
                service.observe_sighting({"robot_id": rid, "x": true[0], "y": true[1], "yaw": true[2],
                                          "captured_at": wall["t"] - 0.05})
            service.observe_state(rid, {"odom_pose": {"x": odom[0], "y": odom[1], "yaw": odom[2],
                                                      "stamp": wall["t"]}})
        wall["t"] += 0.2
        clock.now += 0.2

    for _ in range(5):
        tick((3.0, 0.0, 0.0), (-2.0, 1.0, 0.0))
    assert anchor.route(frame(3.0, 0.0, 0.0))[FOLLOWER] is not None
    tick((3.0, 0.0, 0.0), (0.0, 0.0, 0.0), seen=False)     # the follower's odom restarts at 0
    tick((3.0, 0.0, 0.0), (0.0, 0.0, 0.0))                  # one sighting on the new odom
    assert anchor.route(frame(3.0, 0.0, 0.0)) == {FOLLOWER: None}
    assert anchor.status()["followers"][FOLLOWER] == f"{FOLLOWER}:map_pose_degraded"


def test_a_leader_stream_off_the_tracker_odom_withholds():
    anchor, poses, _ = rig()
    poses.arbitrated_pose = lambda rid, base=poses.arbitrated_pose: replace(
        base(rid), odom_stamp=time.time())
    assert anchor.route(frame(0.05, 0.0, 0.0))[FOLLOWER] is not None
    assert anchor.route(frame(2.0, 0.0, 0.0)) == {FOLLOWER: None}   # restarted leader stream
    assert anchor.status()["followers"][FOLLOWER] == f"{LEADER}:leader_odom_mismatch"


def test_reset_starts_every_robot_over():
    anchor, poses, clock = rig()
    anchor.route(frame(0.0, 0.0, 0.0))
    poses.state[FOLLOWER] = UNKNOWN
    anchor.route(frame(0.0, 0.0, 0.0))
    anchor.reset()
    status = anchor.status()
    assert status["robots"] == {} and status["followers"] == {}


def test_corrections_are_rate_limited_and_converge():
    anchor, poses, clock = rig()
    anchor.route(frame(0.0, 0.0, 0.0))
    poses.T[FOLLOWER] = (-0.1, 0.0, 0.0)                  # the follower's odom drifted 10 cm
    xs = []
    for _ in range(100):                                  # 10 s at the leader's 10 Hz
        clock.now += 0.1
        xs.append(payload(anchor.route(frame(0.0, 0.0, 0.0)))["pose"]["x"])
    steps = [b - a for a, b in zip([1.0, *xs], xs)]
    assert max(steps) <= anchor_mod.MAX_CORRECTION_MPS * 0.1 + 1e-9
    assert xs[-1] == pytest.approx(1.1, abs=0.002)


def test_a_yaw_correction_turns_about_the_robot_not_the_odom_origin():
    anchor, poses, clock = rig()
    poses.odom[FOLLOWER] = (5.0, 0.0, 0.0)                # 5 m from its odom origin
    anchor.route(frame(0.0, 0.0, 0.0))
    poses.T[FOLLOWER] = compose((5.0, 0.0, math.radians(3)), (-5.0, 0.0, 0.0))
    clock.now += 0.1
    assert anchor.route(frame(0.0, 0.0, 0.0))[FOLLOWER] is not None   # 3 deg here is no jump
    assert anchor.status()["robots"][FOLLOWER]["residual_m"] < 0.01


def test_a_jump_stops_that_follower_until_the_relay_resumes():
    anchor, poses, clock = rig()
    anchor.route(frame(0.0, 0.0, 0.0))
    poses.T[FOLLOWER] = (anchor_mod.JUMP_M + 0.05, 0.0, 0.0)
    clock.now += 0.1
    assert anchor.route(frame(0.0, 0.0, 0.0)) == {FOLLOWER: None}
    poses.T[FOLLOWER] = (0.0, 0.0, 0.0)                   # latched even if it comes back
    clock.now += 0.1
    assert anchor.route(frame(0.0, 0.0, 0.0)) == {FOLLOWER: None}
    assert anchor.status()["jumps"] == 1
    anchor.reset()
    assert anchor.route(frame(0.0, 0.0, 0.0))[FOLLOWER] is not None


def test_the_relay_writes_each_follower_its_own_frame_or_nothing():
    poses = Poses()
    anchor = TrailAnchor(poses, LEADER, [FOLLOWER, "rosy_42"], clock=Clock())
    relay = Relay(SimpleNamespace(robot_id=LEADER),
                  [SimpleNamespace(robot_id=FOLLOWER), SimpleNamespace(robot_id="rosy_42")],
                  anchor=anchor)
    poses.T["rosy_42"], poses.odom["rosy_42"] = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    poses.state["rosy_42"], poses.age["rosy_42"] = UNKNOWN, None
    relay._on_frame(frame(0.0, 0.0, 0.0))
    assert json.loads(relay._lanes[FOLLOWER].latest)["payload"]["anchor"] == "fleet"
    assert relay._lanes["rosy_42"].latest is None
    relay._on_frame(frame(0.0, 0.0, 0.0, frame_name="map"))
    assert relay._lanes["rosy_42"].latest == frame(0.0, 0.0, 0.0, frame_name="map")


def test_the_tracker_exposes_map_from_odom_of_its_anchor():
    tracker = MapPoseTracker(FOLLOWER)
    assert tracker.odom_to_map() is None
    tracker.add_odom(OdomSample(0.3, 0.1, 0.2, 10.0), now=10.0)
    tracker.add_sighting(Sighting(FOLLOWER, 2.0, 1.0, 1.0, 10.0), now=10.1)
    tracker.add_odom(OdomSample(0.5, 0.2, 0.3, 10.5), now=10.5)
    T, odom, anchor_at, epoch = tracker.odom_to_map()
    pose = tracker.pose(10.5)
    assert odom == (0.5, 0.2, 0.3) and anchor_at == 10.0 and epoch == 0
    assert compose(T, odom) == pytest.approx((pose.x, pose.y, pose.yaw))
