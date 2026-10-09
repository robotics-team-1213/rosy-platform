"""D-494 3: MapPoseService wiring — accepted sightings and snapshot odom_pose in, map pose out."""

import asyncio
import time
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


def state(t, x=0.0, y=0.0, yaw=0.0):
    return {"robot_id": "r1", "pose": {"x": 9.0, "y": 9.0, "yaw": 0.0},
            "odom_pose": {"x": x, "y": y, "yaw": yaw, "stamp": t}}


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
    service.observe_state("r1", state(wall.now, x=0.3))
    pose = service.arbitrated_pose("r1")
    assert (pose.source, pose.state) == (BRIDGED, LOCALIZED)
    assert abs(pose.x - 1.3) < 1e-6 and abs(pose.y - 2.0) < 1e-6


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
            app.state.map_pose.observe_state("r1", robot._state)   # as a hub heartbeat would
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


def test_sightings_for_another_map_frame_are_ignored():
    wall = Wall()
    active = {"id": "site"}
    service = MapPoseService(lambda: ["r1"], wall=wall, map_id=lambda: active["id"])
    service.observe_state("r1", state(T0))
    service.observe_sighting({**row(T0), "map_id": "other"})
    assert service.arbitrated_pose("r1").state == UNKNOWN
    service.observe_sighting({**row(T0 + 0.05), "map_id": "site"})
    wall.now = T0 + 0.1
    service.observe_state("r1", state(T0 + 0.1))           # odom after the capture pairs it
    pose = service.arbitrated_pose("r1")
    assert (pose.map_id, pose.sightings_filtered_map_id) == ("site", 1)
    active["id"] = "new-site"                              # activation of another frame
    assert service.arbitrated_pose("r1").state == DEGRADED


def test_roster_change_drops_the_tracker():
    wall = Wall()
    roster = ["r1"]
    service = MapPoseService(lambda: roster, wall=wall)
    service.observe_state("r1", state(T0))
    service.observe_sighting(row(T0))
    assert service.arbitrated_pose("r1").state == DEGRADED
    roster[:] = []
    assert service.arbitrated_pose("r1") is None
    roster[:] = ["r1"]
    assert service.arbitrated_pose("r1").state == UNKNOWN       # re-enrolled: starts over


def test_malformed_odom_pose_is_counted():
    wall = Wall()
    service = MapPoseService(lambda: ["r1"], wall=wall)
    service.observe_state("r1", {"odom_pose": {"x": "nan?", "y": 0, "yaw": 0, "stamp": T0}})
    pose = service.arbitrated_pose("r1")
    assert (pose.odom_refused, pose.odom_refused_reason) == (1, "malformed")


def test_refresh_is_coalesced_and_skipped_while_odom_is_fresh():
    wall = Wall()
    calls = []

    async def gather(robot_id):
        calls.append(robot_id)
        await asyncio.sleep(0)
        return state(wall.now)

    service = MapPoseService(lambda: ["r1"], wall=wall, gather=gather)

    async def run():
        await asyncio.gather(service.refresh("r1"), service.refresh("r1"))
        await service.refresh("r1")                              # odom 0 s old: skipped
        wall.now += 0.5
        await service.refresh("r1")

    asyncio.run(run())
    assert calls == ["r1", "r1"]


def test_unreachable_robot_answers_its_last_pose(tmp_path):
    import httpx

    app, robot = _app(tmp_path)
    viewer = {"Authorization": f"Bearer {VIEWER_TOKEN}"}
    robot.state_error = httpx.ConnectError("unreachable")
    with TestClient(app) as client:
        response = client.get("/api/fleet/robots/r1/map-pose", headers=viewer)
    assert response.status_code == 200 and response.json()["state"] == UNKNOWN


def test_a_failing_state_sink_does_not_break_the_snapshot():
    robot = FakeRobot("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    calls = []

    def boom(robot_id, _state):
        calls.append(robot_id)
        raise RuntimeError("bad sink")

    console.set_state_sink(boom)
    for _ in range(2):
        snapshot = asyncio.run(console.snapshot())
        assert snapshot["robots"][0]["online"] is True
    assert calls == ["r1", "r1"]


def test_map_pose_lease_must_fit_the_ingest_lease(tmp_path):
    import pytest

    robot = FakeRobot("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService([], known_robot_ids=console.robot_ids, lease_s=0.5)
    with pytest.raises(ValueError):
        create_app(console, sightings=sightings, start_task_dispatcher=False)



def test_force_rest_bypasses_the_hub_cache_and_is_coalesced():
    wall = Wall()
    calls = []

    async def hub(robot_id):
        calls.append("hub")
        return state(wall.now - 0.9)                       # a 1 Hz heartbeat cached 0.9 s ago

    async def rest(robot_id):
        calls.append("rest")
        await asyncio.sleep(0)
        return state(wall.now)

    service = MapPoseService(lambda: ["r1"], wall=wall, gather=hub, gather_rest=rest)

    async def run():
        await asyncio.gather(service.refresh("r1", force_rest=True),
                             service.refresh("r1", force_rest=True))

    asyncio.run(run())
    assert calls == ["rest"]
    assert service._trackers["r1"].latest_odom_stamp == T0


def test_active_map_without_a_matching_source_warns_once(caplog):
    import logging

    service = MapPoseService(lambda: ["r1"], map_id=lambda: "site", source_map_ids=["lane-map:v1"])
    with caplog.at_level(logging.WARNING, logger="fleet.map_pose"):
        service.active_map_id()
        service.active_map_id()
    assert len([r for r in caplog.records if "matches no sighting source" in r.message]) == 1


def test_a_failed_read_with_a_cancelled_waiter_is_retrieved():
    wall = Wall()
    gate = {}

    async def gather(robot_id):
        await gate["event"].wait()
        raise OSError("down")

    service = MapPoseService(lambda: ["r1"], wall=wall, gather=gather)

    async def run():
        gate["event"] = asyncio.Event()
        waiter = asyncio.ensure_future(service.refresh("r1"))
        await asyncio.sleep(0)
        waiter.cancel()
        gate["event"].set()
        for _ in range(3):
            await asyncio.sleep(0)
        assert service._refreshing == {}

    asyncio.run(run())


def test_d577_stuck_pose_tells_a_lost_pose_from_no_source():
    """Safety review 1: UNKNOWN after a sighting (stale odom) is a lost pose, not "Fleet does not know"."""
    wall = Wall()
    service = MapPoseService(lambda: ["r1"], wall=wall)
    assert service.stuck_pose("r1") == {"state": UNKNOWN, "age_s": None, "sourced": False}
    for i in range(3):
        wall.now = T0 + 0.1 * i
        service.observe_state("r1", state(wall.now))
        service.observe_sighting(row(wall.now))
    assert service.stuck_pose("r1")["state"] == LOCALIZED
    wall.now = T0 + 10.0                                   # odom older than max_odom_age_s
    assert service.stuck_pose("r1") == {"state": UNKNOWN, "age_s": None, "sourced": True}
    assert service.stuck_pose("nobody") is None
