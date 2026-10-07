"""D-491 3: MapPoseService wiring — accepted sightings and snapshot odom_pose in, map pose out."""

import asyncio
import time
from datetime import datetime, timezone
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.localization.map_pose import BRIDGED, DEGRADED, LOCALIZED, UNKNOWN, MapPoseConfig
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.map_pose_service import MapPoseService
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

T0 = 1_800_000_000.0
SOURCE_TOKEN = "source-camera-secret"
OPERATOR_TOKEN = "operator-secret"
VIEWER_TOKEN = "viewer-secret"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def state(t, x=0.0, y=0.0, yaw=0.0):
    return {"robot_id": "r1", "pose": {"x": 9.0, "y": 9.0, "yaw": 0.0},
            "odom_pose": {"x": x, "y": y, "yaw": yaw, "stamp": iso(t)}}


def row(t, x=1.0, y=2.0, yaw=0.0, robot="r1"):
    return {"robot_id": robot, "x": x, "y": y, "yaw": yaw, "captured_at": t, "quality": 0.9}


class Wall:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def test_service_anchors_on_sightings_and_bridges_on_snapshot_odom():
    wall = Wall()
    service = MapPoseService(lambda: ["r1"], wall=wall)
    assert service.arbitrated_pose("r1").state == UNKNOWN
    for i in range(3):
        wall.now = T0 + 0.1 * i
        service.observe_state("r1", state(wall.now))
        service.observe_sighting(row(wall.now))
    assert service.arbitrated_pose("r1").state == LOCALIZED
    wall.now = T0 + 0.5
    service.observe_state("r1", state(wall.now, x=0.4))
    pose = service.arbitrated_pose("r1")
    assert (pose.source, pose.state) == (BRIDGED, LOCALIZED)
    assert abs(pose.x - 1.4) < 1e-6 and abs(pose.y - 2.0) < 1e-6


def test_service_ignores_robots_off_the_roster_and_snapshots_without_odom():
    wall = Wall()
    service = MapPoseService(lambda: ["r1"], wall=wall)
    service.observe_sighting(row(T0, robot="r2"))
    service.observe_state("r2", state(T0))
    service.observe_state("r1", {"robot_id": "r1", "pose": {"x": 1, "y": 2, "yaw": 0}})
    service.observe_sighting(row(T0))
    assert service.arbitrated_pose("r2") is None
    assert service.arbitrated_pose("r1").state == UNKNOWN      # no odom_pose -> nothing pairs


def test_refresh_reads_the_robot_state_through_gather():
    wall = Wall()
    states = {"r1": state(T0)}

    async def gather(robot_id):
        return states[robot_id]

    service = MapPoseService(lambda: ["r1"], wall=wall, gather=gather)
    asyncio.run(service.refresh("r1"))
    service.observe_sighting(row(T0))
    assert service.arbitrated_pose("r1").state == DEGRADED     # anchored, not yet confirmed


def test_service_uses_the_site_config_limits():
    wall = Wall()
    service = MapPoseService(lambda: ["r1"], wall=wall,
                             config=MapPoseConfig(max_dead_reckon_m=0.2))
    for i in range(3):
        wall.now = T0 + 0.1 * i
        service.observe_state("r1", state(wall.now))
        service.observe_sighting(row(wall.now))
    wall.now = T0 + 0.5
    service.observe_state("r1", state(wall.now, x=0.3))
    assert service.arbitrated_pose("r1").state == DEGRADED


# --- app wiring ---------------------------------------------------------------------------

def _app(tmp_path):
    robot = FakeRobot("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    source = SightingSource(source_id="ceiling", token=SOURCE_TOKEN, robot_ids=("r1",),
                            map_id="site-v1", calibration_revision="cal-1",
                            corner_marker_ids=(30, 31, 32, 33))
    sightings = SightingService([source], known_robot_ids=console.robot_ids)
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1"})
    app = create_app(console, console_token=OPERATOR_TOKEN, sightings=sightings,
                     task_service=task_service, start_task_dispatcher=False,
                     site_users={sha256(VIEWER_TOKEN.encode()).hexdigest(): {
                         "principal_id": "viewer-1", "role": "viewer"}})
    return app, robot


def _sighting(t, x=1.0, robot="r1"):
    return {"robot_id": robot, "x": x, "y": 2.0, "yaw": 0.0, "captured_at": t, "seq": int(t * 10) % 1000,
            "map_id": "site-v1", "calibration_revision": "cal-1", "processor_revision": "p1",
            "quality": 0.9, "corner_marker_ids": [30, 31, 32, 33]}


def test_map_pose_endpoint_reads_accepted_sightings_and_robot_odom(tmp_path):
    app, robot = _app(tmp_path)
    viewer = {"Authorization": f"Bearer {VIEWER_TOKEN}"}
    source = {"Authorization": f"Bearer {SOURCE_TOKEN}"}
    with TestClient(app) as client:
        assert client.get("/api/fleet/robots/r1/map-pose").status_code == 401
        assert client.get("/api/fleet/robots/nope/map-pose", headers=viewer).status_code == 404
        unknown = client.get("/api/fleet/robots/r1/map-pose", headers=viewer).json()
        assert unknown["state"] == UNKNOWN and unknown["x"] is None

        for _ in range(3):
            now = time.time()
            robot._state = state(now)
            client.get("/api/fleet/robots/r1/map-pose", headers=viewer)       # feeds odom
            assert client.post("/api/fleet/sightings", json=_sighting(now),
                               headers=source).status_code == 200
        pose = client.get("/api/fleet/robots/r1/map-pose", headers=viewer).json()
        assert pose["robot_id"] == "r1" and pose["state"] == LOCALIZED
        assert abs(pose["x"] - 1.0) < 1e-6

        # A refused sighting (wrong token) never reaches the map pose.
        now = time.time()
        refused = client.post("/api/fleet/sightings", json=_sighting(now, x=3.0),
                              headers={"Authorization": "Bearer wrong"})
        assert refused.status_code == 401
        pose = client.get("/api/fleet/robots/r1/map-pose", headers=viewer).json()
        assert abs(pose["x"] - 1.0) < 1e-6 and pose["state"] == LOCALIZED


def test_console_snapshot_feeds_odom(tmp_path):
    app, robot = _app(tmp_path)
    now = time.time()
    robot._state = state(now)
    with TestClient(app) as client:
        assert client.get("/api/fleet/state", headers={"Authorization": f"Bearer {VIEWER_TOKEN}"}).status_code == 200
    tracker = app.state.map_pose._trackers["r1"]
    assert tracker._odom and abs(tracker._odom[-1].stamp - now) < 1e-3


def test_cli_reads_fleet_map_pose_from_the_site_config(tmp_path):
    import pytest
    from fleet import cli

    config = tmp_path / "site.yaml"
    config.write_text("fleet:\n  map_pose:\n    max_dead_reckon_m: 1.0\n", encoding="utf-8")
    assert cli._map_pose_config(cli.parse_args(["console", "--site-config", str(config)])) \
        == MapPoseConfig(max_dead_reckon_m=1.0)
    assert cli._map_pose_config(cli.parse_args(["console"])) == MapPoseConfig()
    config.write_text("fleet:\n  map_pose:\n    max_jump_m: 5\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli._map_pose_config(cli.parse_args(["console", "--site-config", str(config)]))
