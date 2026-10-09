"""D-581 end to end, kinematic: ceiling camera -> Fleet map pose -> anchor -> CORE trail in odom.

Two unicycle robots with different odom origins and different wheel-odom errors. A fake ceiling
camera sees both true poses at 5 Hz with noise, delivered 150 ms late; CORE odom reaches Fleet at
2 Hz (the anchor's refresh rate). The leader drives an S curve; its 10 Hz /ws/swarm/pose sample is
its odom pose. Fleet re-expresses it in the follower's odom (TrailAnchor over the real
MapPoseService), and the follower replays the trail in its own odom with CORE's D-559 trail
geometry. Measured: the follower's TRUE path against the leader's TRUE path.
"""

from __future__ import annotations

import json
import math
import random

from core_features.swarm.trail import Trail, trail_twist
from fleet.localization.map_pose import compose, relative
from fleet.server.map_pose_service import MapPoseService
from fleet.swarm.anchor import TrailAnchor

LEADER, FOLLOWER = "rosy_40", "rosy_41"
DT = 0.01
WALL0 = 1_000.0
GAP, SPEED, MAX_W = 0.5, 0.12, 1.5
CAMERA_PERIOD, CAMERA_LATENCY, CAMERA_XY_SIGMA, CAMERA_YAW_SIGMA = 0.2, 0.15, 0.01, math.radians(1.0)
ODOM_PERIOD, STREAM_PERIOD, WIFI_DELAY, CONTROL_PERIOD = 0.5, 0.1, 0.05, 0.05


class Robot:
    def __init__(self, true_pose, odom_origin, k_linear, k_angular):
        self.true = true_pose
        self.odom = relative(odom_origin, true_pose)       # odom starts where the robot stands
        self.k_linear, self.k_angular = k_linear, k_angular

    def move(self, v, w, dt):
        self.true = _integrate(self.true, v, w, dt)
        self.odom = _integrate(self.odom, v * self.k_linear, w * self.k_angular, dt)


def _integrate(pose, v, w, dt):
    x, y, yaw = pose
    return x + v * math.cos(yaw) * dt, y + v * math.sin(yaw) * dt, yaw + w * dt


def leader_twist(t):
    """2 s still (anchors confirm), an S curve, then straight, then stop."""
    if t < 2.0 or t > 26.0:
        return 0.0, 0.0
    phase = t - 2.0
    w = 0.6 * math.sin(2 * math.pi * phase / 16.0) if phase < 16.0 else 0.0
    return SPEED, w


def _distance_to_path(px, py, path):
    best = math.inf
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        vx, vy = bx - ax, by - ay
        n = vx * vx + vy * vy
        t = 0.0 if n == 0 else min(max(((px - ax) * vx + (py - ay) * vy) / n, 0.0), 1.0)
        best = min(best, math.hypot(px - ax - t * vx, py - ay - t * vy))
    return best


def simulate(seed=581, duration=34.0):
    rng = random.Random(seed)
    leader = Robot((0.0, 0.0, 0.0), (1.0, -2.0, 0.7), 1.03, 0.99)
    follower = Robot((-GAP, 0.0, 0.0), (-3.0, 1.5, -1.2), 0.97, 1.01)
    robots = {LEADER: leader, FOLLOWER: follower}
    clock = {"t": 0.0}
    wall = lambda: WALL0 + clock["t"]  # noqa: E731
    poses = MapPoseService(lambda: [LEADER, FOLLOWER], wall=wall)
    anchor = TrailAnchor(poses, LEADER, [FOLLOWER], clock=lambda: clock["t"])

    sightings, deliveries = [], []          # (deliver_at, row) / (deliver_at, payload)
    trail, linear, withheld, sent, seq = None, 0.0, 0, 0, 0
    leader_path, follower_trace = [(follower.true[0], follower.true[1])], []
    steps = round(duration / DT)
    for k in range(steps + 1):
        t = k * DT
        clock["t"] = t
        if k % round(CAMERA_PERIOD / DT) == 0:
            for rid, robot in robots.items():
                x, y, yaw = robot.true
                sightings.append((t + CAMERA_LATENCY, {
                    "robot_id": rid, "x": x + rng.gauss(0, CAMERA_XY_SIGMA),
                    "y": y + rng.gauss(0, CAMERA_XY_SIGMA), "yaw": yaw + rng.gauss(0, CAMERA_YAW_SIGMA),
                    "captured_at": WALL0 + t, "quality": 1.0}))
        while sightings and sightings[0][0] <= t + 1e-9:
            poses.observe_sighting(sightings.pop(0)[1])
        if k % round(ODOM_PERIOD / DT) == 0:
            for rid, robot in robots.items():
                ox, oy, oyaw = robot.odom
                poses.observe_state(rid, {"odom_pose": {"x": ox, "y": oy, "yaw": oyaw, "stamp": WALL0 + t}})
        if k % round(STREAM_PERIOD / DT) == 0:
            seq += 1
            ox, oy, oyaw = leader.odom
            frame = json.dumps({"type": "pose", "payload": {
                "robot_id": LEADER, "pose": {"x": ox, "y": oy, "yaw": oyaw}, "seq": seq, "frame": "odom"}})
            out = json.loads(anchor.route(frame)[FOLLOWER])["payload"]
            if out.get("anchor_hold"):
                withheld += 1 if t > 2.0 else 0
            else:
                sent += 1
                deliveries.append((t + WIFI_DELAY, out))
        while deliveries and deliveries[0][0] <= t + 1e-9:
            sample = deliveries.pop(0)[1]["pose"]
            if trail is None:
                trail = Trail(follower.odom[:2], (sample["x"], sample["y"]))
            else:
                assert trail.add(sample["x"], sample["y"], sample["yaw"], max_jump=0.3 + 0.2 * STREAM_PERIOD)
        v_l, w_l = leader_twist(t)
        if k % round(CONTROL_PERIOD / DT) == 0:
            if trail is not None:
                linear, angular, reason = trail_twist(
                    trail, *follower.odom, gap=GAP, max_speed=0.2, max_angular=MAX_W,
                    prev_linear=linear, dt=CONTROL_PERIOD)
                assert reason is None
            else:
                linear, angular = 0.0, 0.0
        leader.move(v_l, w_l, DT)
        follower.move(linear, angular, DT)
        if k % 5 == 0:
            leader_path.append(leader.true[:2])
        if k % 10 == 0:
            follower_trace.append(follower.true[:2])
    deviations = [_distance_to_path(x, y, leader_path) for x, y in follower_trace]
    end_gap = math.dist(leader.true[:2], follower.true[:2])
    return {"max_m": max(deviations), "rms_m": math.sqrt(sum(d * d for d in deviations) / len(deviations)),
            "withheld": withheld, "sent": sent, "end_gap_m": end_gap, "jumps": anchor.jumps,
            "leader_odom_drift_m": math.dist(compose((1.0, -2.0, 0.7), leader.odom)[:2], leader.true[:2])}


def test_the_follower_replays_the_leader_true_path_within_ten_centimetres():
    results = [simulate(seed) for seed in (581, 582, 583)]
    for r in results:
        print("D-581 kinematic: max %.3f m rms %.3f m end gap %.3f m leader odom drift %.3f m "
              "sent %d withheld %d jumps %d" % (r["max_m"], r["rms_m"], r["end_gap_m"],
                                                r["leader_odom_drift_m"], r["sent"], r["withheld"], r["jumps"]))
        assert r["max_m"] <= 0.10
        assert r["withheld"] == 0 and r["jumps"] == 0
        assert r["leader_odom_drift_m"] > 0.05           # the anchor, not odom, keeps it on the path
        assert 0.4 <= r["end_gap_m"] <= 0.6


if __name__ == "__main__":
    print(simulate())
