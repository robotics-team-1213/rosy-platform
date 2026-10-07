"""D-511 M0: lane-compliance monitor — refresh movers, judge everyone, read-only views."""

import asyncio
import math
import time
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.localization.lane_compliance import ACT, OK, UNKNOWN, LaneComplianceConfig
from fleet.localization.map_pose import MapPose, MapPoseConfig, MapPoseTracker, OdomSample
from fleet.routing.graph import build_graph
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.lane_compliance_service import LaneComplianceMonitor
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint

VIEWER_TOKEN = "viewer-secret"
GRAPH = build_graph(SiteMap.model_validate({
    "places": [{"id": "A", "name": "A", "x": 0, "y": 0, "kind": "junction"},
               {"id": "B", "name": "B", "x": 2, "y": 0, "kind": "junction"}],
    "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]], "width_m": 0.3,
               "speed_cap_mps": 0.2}]}))


class Poses:
    """MapPoseService stand-in: who moved, which robots were refreshed, fixed poses."""

    def __init__(self, poses, moving=()):
        self.poses, self.moving, self.refreshed = poses, set(moving), []

    def moved(self, robot_id, min_m, min_deg):
        assert (min_m, min_deg) == (LaneComplianceConfig().moving_min_m, LaneComplianceConfig().moving_min_deg)
        return robot_id in self.moving

    async def refresh(self, robot_id, *, force_rest=False):
        assert force_rest
        self.refreshed.append(robot_id)
        if robot_id == "boom":
            raise OSError("unreachable")
        if robot_id == "slow":
            await asyncio.sleep(30)

    def arbitrated_pose(self, robot_id):
        return self.poses.get(robot_id)


class Maps:
    def __init__(self, active):
        self._active = active

    def active(self):
        return self._active


def at(y):
    return MapPose(1.0, y, 0.0, "LOCALIZED", "sighting", 0.0, 0.1)


def test_monitor_refreshes_only_movers_and_judges_every_robot():
    poses = Poses({"still": at(0.0), "over": at(0.15), "boom": at(0.0)}, moving={"over", "boom"})
    monitor = LaneComplianceMonitor(lambda: ["still", "over", "boom", "lost"], poses=poses,
                                    site_maps=Maps((7, None, GRAPH, None)),
                                    config=LaneComplianceConfig(persist_n=2), wall=lambda: 5.0)
    for _ in range(2):
        asyncio.run(monitor.tick())
    assert sorted(poses.refreshed) == ["boom", "boom", "over", "over"]   # a failed read is ignored
    assert monitor.view("over")["level"] == ACT and monitor.view("over")["moving"] is True
    assert monitor.view("still")["level"] == OK and monitor.view("still")["moving"] is False
    assert monitor.view("still")["map_version"] == 7 and monitor.view("still")["at"] == 5.0
    assert monitor.view("lost")["level"] == UNKNOWN                      # no pose
    assert monitor.view("nope") is None


def test_one_slow_robot_does_not_hold_up_the_tick():
    poses = Poses({"slow": at(0.0), "fast": at(0.0)}, moving={"slow", "fast"})
    monitor = LaneComplianceMonitor(lambda: ["slow", "fast"], poses=poses,
                                    site_maps=Maps((1, None, GRAPH, None)))
    started = time.monotonic()
    asyncio.run(monitor.tick())
    assert time.monotonic() - started < 2.0              # cut at PERIOD_S, not 30 s
    assert monitor.view("slow")["level"] == OK and monitor.view("fast")["level"] == OK


def test_monitor_without_active_map_is_unknown_and_forgets_robots_that_left():
    roster = ["r1"]
    monitor = LaneComplianceMonitor(lambda: roster, poses=Poses({"r1": at(0.0)}), site_maps=Maps(None))
    asyncio.run(monitor.tick())
    assert monitor.view("r1")["level"] == UNKNOWN and monitor.view("r1")["map_version"] is None
    roster.clear()
    asyncio.run(monitor.tick())
    assert monitor.view("r1") is None


def test_tracker_moved_since_has_a_jitter_deadband():
    band = (0.01, math.radians(2.0))
    tracker = MapPoseTracker("r1")
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, 100.0), 100.0)
    assert not tracker.moved_since(99.0, *band)           # one sample is not motion
    for i, (x, yaw) in enumerate([(0.004, 0.01), (-0.003, -0.02), (0.005, 0.015)] * 3):
        tracker.add_odom(OdomSample(x, 0.0, yaw, 100.2 + 0.2 * i), 100.2 + 0.2 * i)
    assert not tracker.moved_since(99.0, *band)           # parked: encoder/IMU jitter only
    tracker.add_odom(OdomSample(0.0, 0.0, 0.2, 102.0), 102.0)      # turned 11 deg
    assert tracker.moved_since(99.0, *band) and tracker.moved_since(101.9, *band)
    assert not tracker.moved_since(102.5, *band)          # nothing newer than `since`
    tracker.add_odom(OdomSample(0.03, 0.0, 0.2, 102.2), 102.2)     # 3 cm forward
    assert tracker.moved_since(102.1, *band)


def test_lane_compliance_endpoint_and_state_row(tmp_path):
    robot = FakeRobot("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1"})
    app = create_app(console, console_token="operator-secret", task_service=task_service,
                     start_task_dispatcher=False,
                     site_users={sha256(VIEWER_TOKEN.encode()).hexdigest(): {
                         "principal_id": "viewer-1", "role": "viewer"}})
    viewer = {"Authorization": f"Bearer {VIEWER_TOKEN}"}
    with TestClient(app) as client:
        assert client.get("/api/fleet/robots/r1/lane-compliance").status_code == 401
        assert client.get("/api/fleet/robots/nope/lane-compliance", headers=viewer).status_code == 404
        asyncio.run(app.state.lane_compliance.tick())       # no anchor, no map: UNKNOWN
        body = client.get("/api/fleet/robots/r1/lane-compliance", headers=viewer).json()
        assert body["robot_id"] == "r1" and body["level"] == UNKNOWN and body["margin_m"] is None
        assert body["pose_source"] == "map_pose" and body["heading_source"] == "pose"
        rows = client.get("/api/fleet/state", headers=viewer).json()["robots"]
        assert rows[0]["lane_compliance"]["level"] == UNKNOWN


class TrackPoses(Poses):
    config = MapPoseConfig()

    def active_map_id(self):
        return "site_v1"


class Identity:
    """IdentityService stand-in: a confirmed track per robot."""

    def __init__(self, tracks):
        self.tracks = tracks

    def confirmed_track_pose(self, robot_id):
        return self.tracks.get(robot_id, {"state": "UNKNOWN", "x": None, "y": None, "yaw": None,
                                          "age_s": None, "map_id": None})


def track(x, y, age_s=0.2, map_id="site_v1"):
    return {"state": "CONFIRMED", "x": x, "y": y, "yaw": None, "age_s": age_s, "map_id": map_id}


def test_led_track_feeds_the_monitor_when_the_map_pose_is_not_localized():
    unknown = MapPose(None, None, None, "UNKNOWN", None, 0.0, None)
    identity = Identity({"led": track(1.0, 0.15)})
    poses = TrackPoses({"led": unknown, "map": at(0.0)})
    monitor = LaneComplianceMonitor(lambda: ["led", "map"], poses=poses, identity=identity,
                                    site_maps=Maps((1, None, GRAPH, None)), config=LaneComplianceConfig(persist_n=1))
    asyncio.run(monitor.tick())
    view = monitor.view("led")                 # still: nearest arc, no heading gate
    assert (view["pose_source"], view["heading_source"], view["level"]) == ("led_track", "none", ACT)
    assert view["pose_state"] == "UNKNOWN" and view["margin_m"] < 0
    assert monitor.view("map")["pose_source"] == "map_pose"
    identity.tracks["led"] = track(1.005, 0.15)   # inside the 0.01 m deadband: still no heading
    asyncio.run(monitor.tick())
    assert monitor.view("led")["heading_source"] == "none"
    identity.tracks["led"] = track(1.20, 0.15)    # moved +x along the lane: heading from motion
    asyncio.run(monitor.tick())
    view = monitor.view("led")
    assert (view["heading_source"], view["level"], view["edge_id"]) == ("track_motion", ACT, "ab")
    identity.tracks["led"] = track(1.0, 0.15)     # moved -x: no one-way arc that way
    asyncio.run(monitor.tick())
    assert monitor.view("led")["level"] == UNKNOWN


def test_led_track_must_be_fresh_on_the_active_map_and_never_beats_a_localized_pose():
    unknown = MapPose(None, None, None, "UNKNOWN", None, 0.0, None)
    identity = Identity({"stale": track(1.0, 0.0, age_s=MapPoseConfig().sighting_lease_s + 0.1),
                         "other": track(1.0, 0.0, map_id="old_map"),
                         "both": track(1.0, 0.15)})
    poses = TrackPoses({"stale": unknown, "other": unknown, "both": at(0.0)})
    monitor = LaneComplianceMonitor(lambda: ["stale", "other", "both"], poses=poses, identity=identity,
                                    site_maps=Maps((1, None, GRAPH, None)))
    asyncio.run(monitor.tick())
    for robot_id in ("stale", "other"):
        assert monitor.view(robot_id)["level"] == UNKNOWN
        assert monitor.view(robot_id)["pose_source"] == "map_pose"
    assert monitor.view("both")["pose_source"] == "map_pose" and monitor.view("both")["offset_m"] == 0.0
