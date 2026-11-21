"""D-593: an operator map pin anchors the D-494 map pose; odom bridges it; sightings check it."""

import math

import pytest

from rosy.world.state.projections.map_pose import (BRIDGED, DEGRADED, LOCALIZED, OPERATOR_PIN, SIGHTING, UNKNOWN,
                                         MapPoseConfig, MapPoseTracker, OdomSample, Sighting)

T0 = 1_800_000_000.0
PIN = (1.0, 2.0, math.pi / 2)


def odom(t, x=0.0, y=0.0, yaw=0.0):
    return OdomSample(x, y, yaw, T0 + t)


def pinned(config=MapPoseConfig()):
    tr = MapPoseTracker("r1", config)
    assert tr.add_odom(odom(0), T0)
    assert tr.add_pin(PIN, T0 + 0.1, "m") is None
    return tr


def test_pin_localizes_at_once_and_names_its_source():
    pose = pinned().pose(T0 + 0.1, "m")
    assert (pose.state, pose.source, pose.anchor_source) == (LOCALIZED, OPERATOR_PIN, OPERATOR_PIN)
    assert (pose.x, pose.y, pose.yaw) == pytest.approx(PIN)
    assert pose.anchor_age_s == pytest.approx(0.0)


def test_pin_moves_with_odom():
    tr = pinned()
    tr.add_odom(odom(0.5, x=0.3), T0 + 0.5)          # 0.3 m forward in odom; map heading is +y
    pose = tr.pose(T0 + 0.5, "m")
    assert (pose.state, pose.source, pose.anchor_source) == (LOCALIZED, BRIDGED, OPERATOR_PIN)
    assert (pose.x, pose.y) == pytest.approx((1.0, 2.3))
    assert pose.dead_reckon_m == pytest.approx(0.3)
    tr.add_odom(odom(0.6, x=0.3, yaw=0.1), T0 + 0.6)
    assert tr.pose(T0 + 0.6, "m").bridge_turn_deg == pytest.approx(math.degrees(0.1))


def test_pin_keeps_the_sighting_bridge_limits():
    tr = pinned()
    for k in range(1, 18):                            # 0.1 m per 0.1 s -> 1.7 m > 1.5 m
        tr.add_odom(odom(0.1 * k, x=0.1 * k), T0 + 0.1 * k)
    assert tr.pose(T0 + 1.7, "m").state == DEGRADED
    tr = pinned()
    for k in range(1, 21):                            # standing still, 2 Hz odom
        tr.add_odom(odom(0.5 * k), T0 + 0.5 * k)
    assert tr.pose(T0 + 10.0, "m").state == LOCALIZED
    tr.add_odom(odom(10.5), T0 + 10.5)
    assert tr.pose(T0 + 10.5, "m").state == DEGRADED   # anchor older than max_anchor_age_s (10 s)


def test_pin_needs_fresh_odom():
    tr = MapPoseTracker("r1")
    assert tr.add_pin(PIN, T0, "m") == "ODOM_STALE"
    tr.add_odom(odom(0), T0)
    assert tr.add_pin(PIN, T0 + 3.5, "m") == "ODOM_STALE"
    assert tr.pose(T0 + 3.5).state == UNKNOWN
    assert tr.add_pin((math.nan, 0.0, 0.0), T0, "m") == "POSE_INVALID"


def test_agreeing_sighting_takes_over_the_anchor():
    tr = pinned()
    tr.add_odom(odom(0.2), T0 + 0.2)
    assert tr.add_sighting(Sighting("r1", 1.05, 2.0, math.pi / 2, T0 + 0.2, map_id="m"), T0 + 0.2, "m")
    pose = tr.pose(T0 + 0.2, "m")
    assert (pose.state, pose.anchor_source, pose.x) == (LOCALIZED, SIGHTING, pytest.approx(1.05))


def test_disagreeing_sighting_degrades_the_pin():
    tr = pinned()
    tr.add_odom(odom(0.2), T0 + 0.2)
    tr.add_sighting(Sighting("r1", 1.4, 2.0, math.pi / 2, T0 + 0.2, map_id="m"), T0 + 0.2, "m")
    pose = tr.pose(T0 + 0.2, "m")
    assert (pose.state, pose.anchor_source) == (DEGRADED, SIGHTING)
    tr = pinned()
    tr.add_odom(odom(0.2), T0 + 0.2)
    tr.add_sighting(Sighting("r1", 1.0, 2.0, 0.0, T0 + 0.2, map_id="m"), T0 + 0.2, "m")   # 90 deg off
    assert tr.pose(T0 + 0.2, "m").state == DEGRADED


def test_sighting_captured_before_the_pin_does_not_undo_it():
    tr = MapPoseTracker("r1")
    tr.add_odom(odom(0), T0)
    assert tr.add_sighting(Sighting("r1", 3.0, 3.0, 0.0, T0 + 0.05, map_id="m"), T0 + 0.05, "m")  # waits for odom
    assert tr.add_pin(PIN, T0 + 0.1, "m") is None
    tr.add_odom(odom(0.2), T0 + 0.2)
    pose = tr.pose(T0 + 0.2, "m")
    assert (pose.state, pose.anchor_source, pose.x) == (LOCALIZED, OPERATOR_PIN, pytest.approx(1.0))


def test_odom_reset_drops_the_pin():
    tr = pinned()
    tr.add_odom(odom(0.2, x=5.0), T0 + 0.2)          # 5 m in 0.1 s: a CORE restart, not motion
    assert tr.pose(T0 + 0.2, "m").state == UNKNOWN


def test_pin_in_another_map_frame_reads_degraded():
    assert pinned().pose(T0 + 0.1, "other").state == DEGRADED


# --- service and route -----------------------------------------------------------------------

import time
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot, fresh_reads, run
from fleet.localization.pose_request import overhead_decision
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

OPERATOR, NAMED, VIEWER = "operator-secret", "named-secret", "viewer-secret"


def _app(tmp_path):
    robot = FakeRobot("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1"})
    users = {sha256(NAMED.encode()).hexdigest(): {"principal_id": "kim", "role": "operator"},
             sha256(VIEWER.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}}
    app = create_app(console, console_token=OPERATOR, task_service=task_service,
                     start_task_dispatcher=False, site_users=users)
    fresh_reads(app)   # the tests change the fake robot between requests
    return app, robot


def _odom_state(t, x=0.0):
    return {"robot_id": "r1", "odom_pose": {"x": x, "y": 0.0, "yaw": 0.0, "stamp": t}}


def test_named_operator_pins_and_the_pin_is_a_site_map_event(tmp_path):
    app, robot = _app(tmp_path)
    body = {"x": 1.0, "y": 2.0, "yaw": math.pi / 2}
    with TestClient(app) as client:
        robot._state = _odom_state(time.time())
        assert client.post("/api/fleet/robots/r1/map-pin", json=body).status_code == 401
        viewer = client.post("/api/fleet/robots/r1/map-pin", json=body,
                             headers={"Authorization": f"Bearer {VIEWER}"})
        assert viewer.status_code == 403
        assert client.post("/api/fleet/robots/nope/map-pin", json=body,
                           headers={"Authorization": f"Bearer {NAMED}"}).status_code == 404
        assert client.post("/api/fleet/robots/r1/map-pin", json={**body, "x": "nan"},
                           headers={"Authorization": f"Bearer {NAMED}"}).status_code == 422
        reply = client.post("/api/fleet/robots/r1/map-pin", json=body,
                            headers={"Authorization": f"Bearer {NAMED}"})
        assert reply.status_code == 200, reply.text
        pose = reply.json()
        assert (pose["state"], pose["anchor_source"]) == (LOCALIZED, OPERATOR_PIN)
        read = client.get("/api/fleet/robots/r1/map-pose", headers={"Authorization": f"Bearer {VIEWER}"}).json()
        assert read["anchor_source"] == OPERATOR_PIN and read["x"] == pytest.approx(1.0)
    events = [e for e in app.state.site_maps.events() if e["action"] == "map_pin"]
    assert events and events[0]["principal_id"] == "kim" and events[0]["detail"]["robot_id"] == "r1"
    assert events[0]["detail"]["before"]["state"] == UNKNOWN


def test_shared_console_token_cannot_pin(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        robot._state = _odom_state(time.time())
        reply = client.post("/api/fleet/robots/r1/map-pin", json={"x": 1.0, "y": 2.0, "yaw": 0.0},
                            headers={"Authorization": f"Bearer {OPERATOR}"})
        assert reply.status_code in (401, 403)     # D-540 9: the shared token is not a named operator


def test_pin_without_fresh_odom_is_refused(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        robot._state = _odom_state(time.time() - 30.0)
        reply = client.post("/api/fleet/robots/r1/map-pin", json={"x": 1.0, "y": 2.0, "yaw": 0.0},
                            headers={"Authorization": f"Bearer {NAMED}"})
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "MAP_PIN_ODOM_STALE"
    assert not [e for e in app.state.site_maps.events() if e["action"] == "map_pin"]


def test_pin_is_refused_while_the_robot_runs_a_trip(tmp_path, monkeypatch):
    from fleet.server.trip_runner import TripRunner
    monkeypatch.setattr(TripRunner, "robot_busy", lambda self, robot_id: True)
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        robot._state = _odom_state(time.time())
        reply = client.post("/api/fleet/robots/r1/map-pin", json={"x": 1.0, "y": 2.0, "yaw": 0.0},
                            headers={"Authorization": f"Bearer {NAMED}"})
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "MAP_PIN_TRIP_ACTIVE"


def test_a_pin_is_never_sent_to_a_robot_as_an_overhead_decision():
    pose = pinned().pose(T0 + 0.1, "m")
    request = {"request_id": "q1", "reason": "stale_pose"}
    assert pose.state == LOCALIZED and overhead_decision(request, pose) is None


def _stand(tr, until, start=1):
    for k in range(start, until + 1):
        tr.add_odom(odom(k), T0 + k)


def test_stale_pin_returns_unknown_after_limit():
    tr = pinned()
    _stand(tr, 125)
    assert tr.pose(T0 + 115.0, "m").state == DEGRADED       # past 10 s, still inside the 120 s limit
    assert tr.pose(T0 + 125.0, "m").state == UNKNOWN


def test_pin_within_limit_is_degraded_not_unknown():
    tr = pinned()
    _stand(tr, 100)
    pose = tr.pose(T0 + 100.0, "m")
    assert (pose.state, pose.anchor_source) == (DEGRADED, OPERATOR_PIN)


def test_camera_sighting_after_stale_unknown_recovers():
    tr = pinned()
    _stand(tr, 125)
    assert tr.pose(T0 + 125.0, "m").state == UNKNOWN
    for k in (126, 127, 128):
        tr.add_odom(odom(k), T0 + k)
        assert tr.add_sighting(Sighting("r1", 3.0, 4.0, 0.0, T0 + k, map_id="m"), T0 + k, "m")
    pose = tr.pose(T0 + 128.0, "m")
    assert (pose.state, pose.anchor_source, pose.x) == (LOCALIZED, SIGHTING, pytest.approx(3.0))


def test_stale_draw_limit_is_validated():
    assert MapPoseConfig().max_stale_draw_s == 120.0
    with pytest.raises(ValueError):
        MapPoseConfig(max_stale_draw_s=601.0)
    with pytest.raises(ValueError):
        MapPoseConfig(max_anchor_age_s=30.0, max_stale_draw_s=20.0)


def test_offline_parked_pin_clears_on_state_and_never_localizes_driving_pose(tmp_path):
    from test_trip_runner import _free_map
    from fleet.server.offline_pin import obstacle_site_pose

    online = FakeRobot("r1", state=_odom_state(time.time()))

    class OfflineRobot(FakeRobot):
        async def state(self):
            raise OSError("robot powered off")

    offline = OfflineRobot("r2", state={})
    console = FleetConsole(
        [RobotEndpoint("r1", "http://127.0.0.1:8080", "t1"),
         RobotEndpoint("r2", "http://127.0.0.1:8081", "t2")],
        [online, offline],
    )
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1", "r2"})
    users = {sha256(NAMED.encode()).hexdigest(): {"principal_id": "kim", "role": "operator"}}
    app = create_app(console, console_token=OPERATOR, task_service=task_service,
                     start_task_dispatcher=False, site_users=users)
    fresh_reads(app)

    with TestClient(app) as client:
        no_map = client.post("/api/fleet/robots/r2/map-pin",
                             json={"x": -0.26, "y": 0.59, "yaw": -1.57, "offline_parked": True},
                             headers={"Authorization": f"Bearer {NAMED}"})
        assert no_map.status_code == 409 and no_map.json()["detail"]["code"] == "MAP_PIN_NO_ACTIVE_MAP"

        app.state.site_maps.import_if_empty(_free_map(), source="test")
        is_online = client.post("/api/fleet/robots/r1/map-pin",
                                json={"x": 1.0, "y": 2.0, "yaw": 0.0, "offline_parked": True},
                                headers={"Authorization": f"Bearer {NAMED}"})
        assert is_online.status_code == 409 and is_online.json()["detail"]["code"] == "MAP_PIN_ROBOT_ONLINE"

        ok = client.post("/api/fleet/robots/r2/map-pin",
                         json={"x": -0.26, "y": 0.59, "yaw": -1.57, "offline_parked": True},
                         headers={"Authorization": f"Bearer {NAMED}"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["state"] == "OFFLINE_PARKED" and ok.json()["anchor_source"] == "operator_pin_offline"
        assert app.state.map_pose.driving_pose("r2").state == UNKNOWN
        assert app.state.map_pose.arbitrated_pose("r2").state == UNKNOWN
        assert obstacle_site_pose(app.state.map_pose, "r2") == ("site", -0.26, 0.59, -1.57)
        run(console.snapshot())
        assert obstacle_site_pose(app.state.map_pose, "r2") == ("site", -0.26, 0.59, -1.57)
        assert app.state.map_pose._offline_pins.pose_on("r2", "other_map") is None

        app.state.map_pose.observe_state("r2", _odom_state(time.time()))
        assert obstacle_site_pose(app.state.map_pose, "r2") is None

    events = [e for e in app.state.site_maps.events() if e["action"] == "map_pin" and e["detail"].get("offline_parked")]
    assert len(events) == 1 and events[0]["detail"]["robot_id"] == "r2"
