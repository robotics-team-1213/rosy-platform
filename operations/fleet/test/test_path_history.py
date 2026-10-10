"""D-594: Fleet records robot paths in map coordinates only and serves them to viewers."""
import asyncio
from hashlib import sha256

from fastapi.testclient import TestClient

import fleet.server.path_history as path_history
from fakes import FakeRobot
from fleet.localization.map_pose import MapPose
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.path_history import CAMERA_ONLY, HEARTBEAT_S, PathRecorder, PathStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

LOCALIZED_MAP = {"state": "LOCALIZED", "pose_frame": "map"}


def localized(x, y):
    return {"pose": {"x": x, "y": y, "yaw": 0.0}, "map_id": "track", "localization": LOCALIZED_MAP}


class Poses:
    def __init__(self):
        self.pose = {}

    def arbitrated_pose(self, robot_id):
        x, y, state, source = self.pose.get(robot_id, (None, None, "UNKNOWN", None))
        return MapPose(x, y, 0.0, state, source, 0.0, 0.1, map_id="track")


class Tracking:
    def __init__(self, robots=()):
        self.robots = list(robots)

    def snapshot(self):
        return {"sources": [{"source_id": "north", "map_id": "track"}], "robots": self.robots}


def recorder(store=None, **kwargs):
    return PathRecorder(store or PathStore(), roster=lambda: ["a"], gather=None, **kwargs)


def test_points_need_2_cm_a_tag_change_or_the_heartbeat():
    rec = recorder()
    rows = [rec.sample(t, {"a": localized(x, 0.0)})
            for t, x in ((0, 0.0), (1, 0.01), (2, 0.025), (3, 0.03))]
    assert [len(r) for r in rows] == [1, 0, 1, 0]
    assert rows[0][0]["state"] == "LOCALIZED" and rows[0][0]["source"] == "robot"
    assert len(rec.sample(3 + HEARTBEAT_S, {"a": localized(0.03, 0.0)})) == 1
    rec._trips = lambda: [{"robot_id": "a", "trip_id": "trip-1"}]
    tagged = rec.sample(40, {"a": localized(0.03, 0.0)})
    assert [r["trip_id"] for r in tagged] == ["trip-1"]


def test_odom_and_legacy_poses_are_never_map_points():
    rec = recorder()
    legacy = {"pose": {"x": 3.0, "y": 4.0, "yaw": 0.0}, "localization": None}
    odom = {"pose": {"x": 3.0, "y": 4.0}, "localization": {**LOCALIZED_MAP, "pose_frame": "odom"}}
    unsure = {"pose": {"x": 3.0, "y": 4.0}, "localization": {**LOCALIZED_MAP, "state": "CANDIDATES"}}
    for t, state in enumerate((legacy, odom, unsure, None, {"localization": LOCALIZED_MAP})):
        assert rec.sample(t, {"a": state}) == []


def test_fleet_map_pose_then_camera_only_fill_in_and_say_so():
    poses, tracking = Poses(), Tracking()
    rec = recorder(map_pose=poses, tracking=tracking)
    legacy = {"pose": {"x": 9.0, "y": 9.0}, "localization": None}
    poses.pose["a"] = (1.0, 2.0, "DEGRADED", "bridged")
    row, = rec.sample(0, {"a": legacy})
    assert (row["x"], row["y"], row["state"], row["source"], row["map_id"]) == (1.0, 2.0, "DEGRADED", "bridged", "track")
    poses.pose["a"] = (None, None, "UNKNOWN", None)
    tracking.robots = [{"robot_id": "a", "status": "MATCHED", "pose_frame_verified": False, "source_id": "north",
                        "camera": {"x": 5.0, "y": 5.0}}]
    assert rec.sample(1, {"a": legacy}) == []     # a blob matched to an unverified (maybe odom) pose
    tracking.robots[0].update(status="MARKER", pose_frame_verified=None)
    row, = rec.sample(2, {"a": legacy})
    assert (row["x"], row["state"], row["source"], row["map_id"]) == (5.0, CAMERA_ONLY, "tracking", "track")
    assert rec.sample(3, {"a": localized(5.0, 5.0)})[0]["state"] == "LOCALIZED"   # the robot's own wins


def test_a_tick_without_a_point_opens_a_new_segment_and_formation_tags_members():
    status = {"active": True, "leader": "a", "assignment": {"b": {}}}
    rec = PathRecorder(PathStore(), roster=lambda: ["a", "b"], gather=None, formation=lambda: status)
    first = rec.sample(1.0, {"a": localized(0, 0), "b": localized(1, 1)})
    assert {r["formation_id"] for r in first} == {"formation-1000"}
    rec.sample(2.0, {"a": None, "b": localized(1, 1)})
    status["active"] = False
    again = {r["robot_id"]: r for r in rec.sample(3.0, {"a": localized(0, 0), "b": localized(1, 1)})}
    assert again["a"]["seg"] == 3000 != first[0]["seg"] and again["b"]["seg"] == first[1]["seg"]
    assert again["a"]["formation_id"] is again["b"]["formation_id"] is None   # b stood still: tag change


def test_store_keeps_24_h_and_a_per_robot_cap(tmp_path, monkeypatch):
    store = PathStore(tmp_path / "site.sqlite")
    row = {"robot_id": "a", "x": 0.0, "y": 0.0, "state": "LOCALIZED", "source": "robot", "seg": 0,
           "map_id": None, "trip_id": None, "formation_id": None}
    store.append([{**row, "t": t} for t in (0.0, 100_000.0, 100_001.0, 100_002.0)])
    monkeypatch.setattr(path_history, "MAX_POINTS_PER_ROBOT", 2)
    store.prune(100_002.0)
    points, truncated = PathStore(tmp_path / "site.sqlite").query("a", since=0, until=1e9)
    assert [p["t"] for p in points] == [100_001.0, 100_002.0] and not truncated


def test_recorder_tick_reads_state_and_writes_to_the_site_db(tmp_path):
    tasks = FleetTaskStore(tmp_path / "site.sqlite")
    store = PathStore(tasks.path)
    clock = iter([10.0, 11.0])

    async def gather(robot_id):
        return localized(1.0, 2.0)
    rec = PathRecorder(store, roster=lambda: ["a"], gather=gather, wall=lambda: next(clock))
    asyncio.run(rec.tick())
    points, _ = store.query("a", since=0, until=100)
    assert [(p["t"], p["x"], p["y"]) for p in points] == [(10.0, 1.0, 2.0)]


VIEWER = {"Authorization": "Bearer viewer-token"}
URL = "/api/fleet/robots/rosy_60/path"


def _client(tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_60")])
    users = {sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    client = TestClient(create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False))
    paths = client.app.state.paths
    assert paths.store.path == tasks.store.path        # the site DB, not a second file
    paths.wall = lambda: 1000.0
    row = {"robot_id": "rosy_60", "x": 1.23456, "y": 0.0, "state": "LOCALIZED", "source": "robot", "seg": 0,
           "map_id": "track", "formation_id": None}
    paths.store.append([{**row, "t": float(t), "trip_id": "trip-1" if t >= 990 else None} for t in range(900, 1001)])
    return client


def test_path_api_needs_a_viewer_and_a_roster_robot(tmp_path):
    client = _client(tmp_path)
    assert client.get(URL).status_code == 401
    missing = client.get("/api/fleet/robots/ghost/path", headers=VIEWER)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "UNKNOWN_ROBOT"
    body = client.get(URL, params={"last_s": 10}, headers=VIEWER).json()
    assert [p["t"] for p in body["points"]] == [float(t) for t in range(990, 1001)]
    assert body["points"][0]["x"] == 1.2346 and body["use"] == "display-only" and not body["truncated"]
    trip = client.get(URL, params={"trip_id": "trip-1"}, headers=VIEWER).json()["points"]
    assert len(trip) == 11 and {p["trip_id"] for p in trip} == {"trip-1"}
    window = client.get(URL, params={"since": 950, "until": 952}, headers=VIEWER).json()["points"]
    assert [p["t"] for p in window] == [950.0, 951.0, 952.0]


def test_path_api_bounds_its_range_and_size(tmp_path, monkeypatch):
    client = _client(tmp_path)
    for bad in ({"since": 10, "last_s": 5}, {"since": 10, "until": 5}, {"last_s": 0},
                {"last_s": 90_000}, {"since": -1}, {"trip_id": ""}):
        response = client.get(URL, params=bad, headers=VIEWER)
        assert response.status_code == 422, bad
    monkeypatch.setattr(path_history, "MAX_RESPONSE_POINTS", 5)
    body = client.get(URL, headers=VIEWER).json()
    assert body["truncated"] and [p["t"] for p in body["points"]] == [996.0, 997.0, 998.0, 999.0, 1000.0]
