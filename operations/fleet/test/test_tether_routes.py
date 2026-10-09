"""D-512 display half: tether circles are read by viewers and set or cleared by a named operator.
D-526: the Fleet tether watch stops a robot through CORE's E-stop on radius, turn or a stale pose."""
import asyncio
import math
from hashlib import sha256

import pytest

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.tether_watch import RADIUS_SLACK_M, STALE_S, TetherWatch, map_pose
from fleet.swarm.robots import RobotEndpoint

OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
BODY = {"anchor_xy": [1.0, -0.5], "radius_m": 0.8}
URL = "/api/fleet/robots/rosy_60/tether"


def _client(tmp_path, raise_server_exceptions=True, robot=None):
    robot = robot or FakeRobot("rosy_60")
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False),
                      raise_server_exceptions=raise_server_exceptions)


def test_tether_needs_a_named_operator_and_set_is_idempotent(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/fleet/tethers").status_code == 401
        assert client.post(URL, json=BODY).status_code == 401
        assert client.post(URL, json=BODY, headers=VIEWER).status_code == 403
        assert client.delete(URL, headers=VIEWER).status_code == 403
        first = client.post(URL, json=BODY, headers=OPERATOR)
        again = client.post(URL, json=BODY, headers=OPERATOR)
        assert first.status_code == again.status_code == 200 and first.json() == again.json()
        row = {"robot_id": "rosy_60", "anchor_xy": [1.0, -0.5], "radius_m": 0.8, "set_by": "bob"}
        listed = client.get("/api/fleet/tethers", headers=VIEWER).json()["tethers"]
        assert [{k: v for k, v in r.items() if k != "watch"} for r in listed] == [row]  # watch: lifespan ticks
        assert client.delete(URL, headers=OPERATOR).json() == {"robot_id": "rosy_60", "cleared": True}
        assert client.delete(URL, headers=OPERATOR).json() == {"robot_id": "rosy_60", "cleared": False}
        assert client.get("/api/fleet/tethers", headers=VIEWER).json()["tethers"] == []


def test_tether_rejects_unknown_robots_and_bad_circles(tmp_path):
    with _client(tmp_path, raise_server_exceptions=False) as client:
        unknown = client.post("/api/fleet/robots/ghost/tether", json=BODY, headers=OPERATOR)
        assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "UNKNOWN_ROBOT"
        for bad in ({**BODY, "radius_m": 0}, {**BODY, "radius_m": 51}, {**BODY, "anchor_xy": [1.0]},
                    {**BODY, "anchor_xy": [True, 0.0]}, {**BODY, "anchor_xy": [1001.0, 0.0]},
                    {**BODY, "extra": 1}):
            assert client.post(URL, json=bad, headers=OPERATOR).status_code == 422, bad
        # Non-JSON NaN is refused (the app's default 422 echo cannot encode it, so it surfaces as 500).
        nan = client.post(URL, content='{"anchor_xy": [NaN, 0], "radius_m": 1}', headers={
            **OPERATOR, "Content-Type": "application/json"})
        assert nan.status_code == 500  # follow-up: the app-wide 422 handler cannot encode NaN
        assert client.get("/api/fleet/tethers", headers=VIEWER).json()["tethers"] == []


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _watch(poses, tethers=None):
    """A watch over robot "r" (anchor 0,0, radius 1 m); ``poses`` is consumed one per tick."""
    tethers = {"r": {"anchor_xy": [0.0, 0.0], "radius_m": 1.0}} if tethers is None else tethers
    stops, clock, feed = [], Clock(), iter(poses)

    async def pose(_robot_id):
        return next(feed)

    async def stop(robot_id):
        stops.append(robot_id)
    return TetherWatch(tethers, pose=pose, stop=stop, clock=clock), stops, clock


def _ticks(watch, clock, n, dt=0.5):
    for _ in range(n):
        asyncio.run(watch.tick())
        clock.now += dt


def test_radius_trip_stops_once_past_the_backstop_slack():
    inside = 1.0 + RADIUS_SLACK_M - 0.01
    watch, stops, clock = _watch([(0.5, 0, 0), (inside, 0, 0), (1.0 + RADIUS_SLACK_M + 0.01, 0, 0), (3, 0, 0)])
    _ticks(watch, clock, 2)
    assert stops == [] and watch.view("r")["state"] == "watching"
    _ticks(watch, clock, 2)
    assert stops == ["r"]  # latched: no second stop, no second pose read
    assert watch.view("r")["trip"] == "tether_radius" and watch.view("r")["stop_sent"] is True


def test_turn_trip_accumulates_across_the_pi_wrap():
    # +100 deg per tick: 170 -> -90 (wrapped) -> 10 ... is one way round, never a jump of -260 deg.
    yaws = [math.radians(170 + 100 * k) for k in range(6)]
    watch, stops, clock = _watch([(0, 0, math.remainder(y, math.tau)) for y in yaws])
    _ticks(watch, clock, 5)
    assert stops == [] and watch.view("r")["turn_deg"] == pytest.approx(400)
    _ticks(watch, clock, 1)
    assert stops == ["r"] and watch.view("r")["trip"] == "tether_turn"


def test_stale_pose_stops():
    n = int(STALE_S / 0.5) + 1  # the pose seen at t=0, then none: age reaches STALE_S on tick n, not past it
    watch, stops, clock = _watch([(0, 0, 0)] + [None] * n)
    _ticks(watch, clock, n)
    assert stops == [] and watch.view("r")["pose_age_s"] == STALE_S
    _ticks(watch, clock, 1)
    assert stops == ["r"] and watch.view("r")["trip"] == "tether_pose_stale"


def test_no_tether_no_action_and_a_cleared_tether_drops_its_watch():
    watch, stops, clock = _watch([], tethers={})
    _ticks(watch, clock, 10)
    assert stops == [] and watch.status == {}
    tethers = {"r": {"anchor_xy": [0.0, 0.0], "radius_m": 1.0}}
    watch, stops, clock = _watch([(0, 0, 0)], tethers=tethers)
    _ticks(watch, clock, 1)
    tethers.clear()
    _ticks(watch, clock, 10)
    assert stops == [] and watch.view("r") is None


def test_a_failed_stop_is_retried_until_core_answers():
    calls = []

    async def pose(_robot_id):
        return (5.0, 0.0, 0.0)

    async def stop(robot_id):
        calls.append(robot_id)
        if len(calls) == 1:
            raise ConnectionError("down")
    watch = TetherWatch({"r": {"anchor_xy": [0.0, 0.0], "radius_m": 1.0}}, pose=pose, stop=stop, clock=Clock())
    asyncio.run(watch.tick())
    assert watch.view("r")["stop_error"] == "ConnectionError" and watch.view("r")["stop_sent"] is False
    asyncio.run(watch.tick())
    asyncio.run(watch.tick())
    assert calls == ["r", "r"] and watch.view("r")["stop_sent"] is True


POSE = {"x": 1, "y": 2, "yaw": 0.5}
MAP_OK = {"state": "LOCALIZED", "pose_frame": "map"}


def test_map_pose_needs_a_trusted_map_pose():
    assert map_pose({"pose": POSE, "localization": MAP_OK}) == (1.0, 2.0, 0.5)
    assert map_pose({"pose": POSE}) is None  # legacy, no localization block: fail closed
    assert map_pose({"pose": POSE, "localization": None}) is None
    assert map_pose({"pose": POSE, "localization": {"state": "LOCALIZED", "pose_frame": "odom"}}) is None
    for state in ("UNKNOWN", "CANDIDATES", "SUSPECT"):  # map frame, not trusted
        assert map_pose({"pose": POSE, "localization": {"state": state, "pose_frame": "map"}}) is None
    assert map_pose({"pose": POSE, "localization": {"pose_frame": "map"}}) is None  # unreadable
    assert map_pose({"pose": {"x": float("nan"), "y": 2, "yaw": 0}, "localization": MAP_OK}) is None
    assert map_pose({"pose": {"x": 1, "y": 2}, "localization": MAP_OK}) is None and map_pose(None) is None


def test_a_hung_stop_does_not_stall_the_other_robots():
    tethers = {r: {"anchor_xy": [0.0, 0.0], "radius_m": 1.0} for r in ("a", "b")}
    stops = []

    async def pose(_robot_id):
        return (5.0, 0.0, 0.0)

    async def stop(robot_id):
        if robot_id == "a":
            await asyncio.sleep(60)
        stops.append(robot_id)
    watch = TetherWatch(tethers, pose=pose, stop=stop, clock=Clock(), stop_timeout_s=0.05)
    asyncio.run(watch.tick())
    assert stops == ["b"] and watch.view("b")["stop_sent"] is True
    assert watch.view("a")["stop_sent"] is False and watch.view("a")["stop_error"] == "TimeoutError"


def test_a_check_that_raises_does_not_stop_the_tick():
    watch, _stops, clock = _watch([(0, 0, 0)])

    async def boom(*_args):
        raise RuntimeError("boom")
    watch._check = boom
    asyncio.run(watch.tick())
    assert watch.tick_age_s() == 0.0


def test_tick_age_shows_a_stopped_watch_and_a_dead_task_is_logged(caplog):
    watch, _stops, clock = _watch([(0, 0, 0)])
    assert watch.tick_age_s() is None
    asyncio.run(watch.tick())
    clock.now += 7.0
    assert watch.tick_age_s() == 7.0 and watch.view("r")["tick_age_s"] == 7.0

    async def dies():
        async def boom():
            raise ValueError("dead")
        task = asyncio.create_task(boom())
        task.add_done_callback(TetherWatch._ended)
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
    with caplog.at_level("ERROR", logger="fleet.tether_watch"):
        asyncio.run(dies())
    assert any("tether watch ended" in r.message and r.levelname == "ERROR" for r in caplog.records)


def test_repeated_stop_failures_raise_an_operator_alarm_and_keep_retrying():
    async def pose(_robot_id):
        return (5.0, 0.0, 0.0)

    async def stop(_robot_id):
        raise ConnectionError("down")
    watch = TetherWatch({"r": {"anchor_xy": [0.0, 0.0], "radius_m": 1.0}}, pose=pose, stop=stop, clock=Clock(),
                        alarm_after=3)
    for _ in range(2):
        asyncio.run(watch.tick())
    assert watch.alarms() == []
    asyncio.run(watch.tick())
    assert watch.alarms() == [{"robot_id": "r", "code": "TETHER_STOP_FAILED",
                               "reason": "tether_radius: ConnectionError"}]
    asyncio.run(watch.tick())
    assert watch.view("r")["stop_failures"] == 4


def test_trip_stops_through_the_existing_core_estop_client_and_shows_in_the_list(tmp_path):
    robot = FakeRobot("rosy_60", state={"robot_id": "rosy_60", "pose": {"x": 4.0, "y": 0.0, "yaw": 0.0},
                                           "localization": MAP_OK, "timestamp": "t1"})
    client = _client(tmp_path, robot=robot)  # no lifespan: this test runs the only watch tick
    assert client.post(URL, json=BODY, headers=OPERATOR).status_code == 200
    asyncio.run(client.app.state.tether_watch.tick())
    assert robot.calls.count(("estop",)) == 1  # hub.scatter_estop -> RobotClient.estop (POST safety/stop)
    watch = client.get("/api/fleet/tethers", headers=VIEWER).json()["tethers"][0]["watch"]
    assert watch["state"] == "tripped" and watch["trip"] == "tether_radius" and watch["stop_sent"] is True
    # Setting the tether again is the operator's re-arm: a fresh watch.
    assert client.post(URL, json=BODY, headers=OPERATOR).status_code == 200
    assert client.get("/api/fleet/tethers", headers=VIEWER).json()["tethers"][0]["watch"] is None


def _tripped_client(tmp_path, **state):
    robot = FakeRobot("rosy_60", state={"robot_id": "rosy_60", "pose": {"x": 4.0, "y": 0.0, "yaw": 0.0},
                                        "localization": MAP_OK, "timestamp": "t1", **state})
    client = _client(tmp_path, robot=robot)
    assert client.post(URL, json=BODY, headers=OPERATOR).status_code == 200
    return client, robot


def test_a_frozen_pose_stamp_trips_pose_stale_and_a_legacy_robot_is_stopped(tmp_path):
    client, robot = _tripped_client(tmp_path)
    robot._state["pose"] = {"x": 0.0, "y": 0.0, "yaw": 0.0}  # inside the circle, but the state never advances
    watch = client.app.state.tether_watch
    watch._tethers["rosy_60"]["anchor_xy"] = [0.0, 0.0]
    clock = Clock()
    watch._clock = clock
    for _ in range(int(STALE_S / 0.5) + 2):
        asyncio.run(watch.tick())
        clock.now += 0.5
    assert watch.view("rosy_60")["trip"] == "tether_pose_stale" and robot.calls.count(("estop",)) == 1
    legacy = FakeRobot("rosy_60", state={"robot_id": "rosy_60", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                                         "timestamp": "t1"})
    (tmp_path / "legacy").mkdir()
    client = _client(tmp_path / "legacy", robot=legacy)
    client.post(URL, json=BODY, headers=OPERATOR)
    watch = client.app.state.tether_watch
    clock = Clock()
    watch._clock = clock
    for k in range(int(STALE_S / 0.5) + 2):
        legacy._state["timestamp"] = f"t{k}"
        asyncio.run(watch.tick())
        clock.now += 0.5
    assert watch.view("rosy_60")["trip"] == "tether_pose_stale" and legacy.calls.count(("estop",)) == 1


def test_the_list_carries_the_watch_tick_age_and_set_and_clear_are_logged(tmp_path, caplog):
    client, _robot = _tripped_client(tmp_path)
    assert client.get("/api/fleet/tethers", headers=VIEWER).json()["watch_age_s"] is None  # never ticked
    asyncio.run(client.app.state.tether_watch.tick())
    assert client.get("/api/fleet/tethers", headers=VIEWER).json()["watch_age_s"] >= 0.0
    with caplog.at_level("WARNING", logger="fleet.tether_routes"):
        client.post(URL, json={**BODY, "radius_m": 1.5}, headers=OPERATOR)
        client.delete(URL, headers=OPERATOR)
    texts = [r.getMessage() for r in caplog.records]
    assert any("by=bob" in t and "radius_m=0.8->1.5" in t for t in texts)
    assert any("cleared" in t and "by=bob" in t for t in texts)


def test_a_failing_trip_cancel_does_not_hide_the_delivered_estop(tmp_path):
    client, robot = _tripped_client(tmp_path)

    async def boom(*_args):
        raise RuntimeError("trip store down")
    client.app.state.trip_runner.cancel_robot = boom
    asyncio.run(client.app.state.tether_watch.tick())
    view = client.app.state.tether_watch.view("rosy_60")
    assert robot.calls.count(("estop",)) == 1 and view["stop_sent"] is True and view["stop_error"] is None
