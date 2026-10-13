"""D-581: the console's TRAIL formation anchors through the real Relay (no relay_factory double)."""

from __future__ import annotations

import asyncio
import json

from fakes import FakeRobot, run
from fleet.localization.map_pose import LOCALIZED, MapPose
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.anchor import anchored_relay_factory
from fleet.swarm.robots import RobotEndpoint


class Poses:
    """MapPoseService reads: both robots LOCALIZED, odom frame == map frame."""

    def __init__(self):
        self.refreshed = []

    def arbitrated_pose(self, robot_id):
        return MapPose(0.0, 0.0, 0.0, LOCALIZED, "sighting", 0.0, 0.1, anchor_age_s=0.1, map_id="site")

    def odom_to_map(self, robot_id):
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, 0

    async def refresh(self, robot_id, force_rest=False):
        self.refreshed.append((robot_id, force_rest))


def odom_frame(x, seq):
    return json.dumps({"type": "pose", "payload": {"robot_id": "rosy_01", "pose": {"x": x, "y": 0.0, "yaw": 0.0},
                                                   "seq": seq, "frame": "odom"}})


async def _sent(robot, seq):
    """The frame for leader `seq` that reached the robot's reference socket."""
    for _ in range(200):
        for text in (robot.sinks[-1].sent if robot.sinks else []):
            if json.loads(text)["payload"]["seq"] == seq:
                return text
        await asyncio.sleep(0.01)
    raise AssertionError(f"{robot.robot_id} got {robot.sinks and robot.sinks[-1].sent}")


def test_a_trail_formation_anchors_and_a_column_reform_relays_bytes():
    robots = [FakeRobot(f"rosy_0{i}", state={"robot_id": f"rosy_0{i}", "navigation": "IDLE",
                                             "pose": {"x": float(i), "y": 0.0, "yaw": 0.0}})
              for i in (1, 2)]
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:809{i}", token="t")
                 for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, robots)
    poses = Poses()
    console.formation_relay_factory = lambda enabled: anchored_relay_factory(poses, enabled)
    leader, follower = robots

    async def scenario():
        leader.pose_frames.put_nowait(odom_frame(0.2, 1))   # the relay is ready on a leader frame
        await console.formation_start("rosy_01", "TRAIL", 0.5)
        leader.pose_frames.put_nowait(odom_frame(0.3, 2))
        payload = json.loads(await _sent(follower, 2))["payload"]
        assert payload["anchor"] == "fleet" and payload["for_robot_id"] == "rosy_02"
        assert payload.get("anchor_hold") is None
        assert console.formation_status()["anchor"]["followers"] == {"rosy_02": None}
        assert "anchor_hold" not in console.formation_status()["stream_evidence"]["rosy_02"]
        poses.arbitrated_pose = lambda rid: MapPose(None, None, None, "UNKNOWN", None, 0.0, None)
        leader.pose_frames.put_nowait(odom_frame(0.3, 3))
        await _sent(follower, 3)
        evidence = console.formation_status()["stream_evidence"]["rosy_02"]
        assert evidence["anchor_hold"] == "rosy_01:no_map_pose"
        assert ("rosy_02", True) in poses.refreshed

        await console.formation_reform("COLUMN", 0.5)
        leader.pose_frames.put_nowait(odom_frame(0.4, 4))
        assert await _sent(follower, 4) == odom_frame(0.4, 4)   # COLUMN: D-31 bytes unchanged
        await console.formation_stop()

    run(scenario())


def test_app_supplies_the_live_map_pose_service_to_the_formation_relay():
    robots = [FakeRobot(f"rosy_0{i}") for i in (1, 2)]
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:809{i}", token="t")
                 for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, robots)
    app = create_app(console)

    relay = console.formation_relay_factory(lambda: True)(robots[0], robots[1:])
    assert relay.anchor is not None
    assert relay.anchor._poses is app.state.map_pose
