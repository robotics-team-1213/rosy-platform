"""D-511 M0: lane-compliance monitor — refresh movers, judge everyone, read-only views."""

import asyncio
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.localization.lane_compliance import ACT, OK, UNKNOWN, LaneComplianceConfig
from fleet.localization.map_pose import MapPose, MapPoseTracker, OdomSample
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

    def moved(self, robot_id):
        return robot_id in self.moving

    async def refresh(self, robot_id, *, force_rest=False):
        assert force_rest
        self.refreshed.append(robot_id)
        if robot_id == "boom":
            raise OSError("unreachable")

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


def test_monitor_without_active_map_is_unknown_and_forgets_robots_that_left():
    roster = ["r1"]
    monitor = LaneComplianceMonitor(lambda: roster, poses=Poses({"r1": at(0.0)}), site_maps=Maps(None))
    asyncio.run(monitor.tick())
    assert monitor.view("r1")["level"] == UNKNOWN and monitor.view("r1")["map_version"] is None
    roster.clear()
    asyncio.run(monitor.tick())
    assert monitor.view("r1") is None


def test_tracker_moved_since_reads_path_or_turn():
    tracker = MapPoseTracker("r1")
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, 100.0), 100.0)
    assert not tracker.moved_since(99.0)                  # one sample is not motion
    tracker.add_odom(OdomSample(0.0, 0.0, 0.0, 101.0), 101.0)
    assert not tracker.moved_since(99.0)                  # standing still
    tracker.add_odom(OdomSample(0.0, 0.0, 0.2, 102.0), 102.0)
    assert tracker.moved_since(99.0) and tracker.moved_since(101.5)
    assert not tracker.moved_since(102.5)                 # nothing newer than `since`


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
        rows = client.get("/api/fleet/state", headers=viewer).json()["robots"]
        assert rows[0]["lane_compliance"]["level"] == UNKNOWN
