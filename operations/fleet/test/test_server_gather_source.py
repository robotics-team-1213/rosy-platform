"""D-447 (a): Fleet gather 출처 — hub-fresh 로봇은 registry 스냅샷, 나머지는 REST 폴백.

새 전송 계약은 없다. 응답 스키마는 불변이고 행에 `gather_source` 만 더해진다
(additive). hub 경로의 상태는 heartbeat(PRT-003, 1 Hz)가 실어 온 것과 바이트가 같다.
"""

import asyncio

from fakes import FakeClock, FakeRobot, run
from test_hub import _ep, _hello
from fastapi.testclient import TestClient

from core_features.power.battery import BatteryConfig, BatteryMonitor
from core_features.power.manager import PowerConfig, PowerManager
from core_common.protocol.schemas import Envelope, EnvelopeType, HeartbeatPayload, StateSnapshot
from fleet.hub.hub import SiteHub
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint


def _console(*robots: FakeRobot, clock=None) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots), clock=clock or FakeClock())


def _health(now):
    battery = BatteryMonitor(BatteryConfig(), clock=now)
    battery.on_voltage(7.6)
    battery.set_charging(True)
    power = PowerManager(PowerConfig())
    return {"power": power.status().model_dump(mode="json"), "battery": battery.health(),
            "policy": power.health(), "recommendation": "normal_idle_policy", "health": {}}


def _state_rows(client):
    response = client.get("/api/fleet/state", headers={"Authorization": "Bearer viewer"})
    assert response.status_code == 200, response.text
    return response.json()["robots"]


def test_power_health_is_bounded_and_one_failure_does_not_hide_another_robot():
    clock = FakeClock()
    good, bad = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    good.power_health_value = _health(clock)
    bad.power_health_error = ConnectionError("old robot")
    console = _console(good, bad, clock=clock)
    client = TestClient(create_app(console, console_token="viewer", start_task_dispatcher=False))
    rows = _state_rows(client)
    assert rows[0]["power_health"]["battery"]["charging_state"] == "confirmed"
    assert rows[1]["power_health"] is None
    _state_rows(client)
    assert good.calls.count(("power_health",)) == 1
    clock.advance(6)
    _state_rows(client)
    assert good.calls.count(("power_health",)) == 2
    good.state_error = ConnectionError("offline")
    client.app.state.fleet_gather.max_age_s = 0.0
    assert _state_rows(client)[0]["power_health"] is None


def test_power_health_rejects_malformed_body_and_replaced_robot_cache():
    clock = FakeClock()
    first = FakeRobot("rosy_01")
    first.power_health_value = _health(clock)
    console = _console(first, clock=clock)
    client = TestClient(create_app(console, console_token="viewer", start_task_dispatcher=False))
    assert _state_rows(client)[0]["power_health"] is not None
    replacement = FakeRobot("rosy_01")
    replacement.power_health_value = {"battery": {"charging_state": "confirmed"}}
    console._replace_client(RobotEndpoint("rosy_01", "http://127.0.0.1:9090", "t"), replacement)
    client.app.state.fleet_gather.max_age_s = 0.0
    row = _state_rows(client)[0]
    assert row["power_health"] is None and row["power_health_age_s"] is None
    assert replacement.calls.count(("power_health",)) == 1


def test_power_health_refresh_waits_for_a_normal_lan_read():
    clock = FakeClock()
    robot = FakeRobot("rosy_01")

    async def delayed_health():
        await asyncio.sleep(0.08)
        return _health(clock)

    robot.power_health = delayed_health
    client = TestClient(create_app(_console(robot, clock=clock), console_token="viewer",
                                   start_task_dispatcher=False))
    assert _state_rows(client)[0]["power_health"] is not None
    clock.advance(6)
    assert _state_rows(client)[0]["power_health"] is not None


def test_fresh_hub_snapshot_answers_and_rest_get_is_skipped():
    clock = FakeClock()
    robot = FakeRobot("rosy_01")
    console = _console(robot, clock=clock)
    row = console.hub.registry.record("rosy_01")
    row.online = True
    row.snapshot = StateSnapshot(robot_id="rosy_01")
    row.last_heartbeat_monotonic = clock()  # 지금 막 도착

    snap = run(console.snapshot())

    assert robot.calls == []  # REST state()는 불리지 않는다 (D-447)
    one = snap["robots"][0]
    assert one["online"] is True
    assert one["gather_source"] == "hub"
    assert one["state"]["robot_id"] == "rosy_01"


def test_stale_heartbeat_falls_back_to_rest():
    clock = FakeClock()
    robot = FakeRobot("rosy_01")
    console = _console(robot, clock=clock)
    row = console.hub.registry.record("rosy_01")
    row.online = True
    row.snapshot = StateSnapshot(robot_id="rosy_01")
    row.last_heartbeat_monotonic = clock() - 3.0  # 기본 3.0 s 지나서 stale

    snap = run(console.snapshot())

    assert ("state",) in robot.calls  # REST 폴백이 답했다
    one = snap["robots"][0]
    assert one["gather_source"] == "rest"
    assert one["state"]["map_id"] == "m1"


def test_offline_hub_record_falls_back_to_rest():
    robot = FakeRobot("rosy_01")
    console = _console(robot)
    row = console.hub.registry.record("rosy_01")
    row.online = False  # 한 번 연결됐다가 끊긴 로봇
    row.snapshot = StateSnapshot(robot_id="rosy_01")
    row.last_heartbeat_monotonic = None

    snap = run(console.snapshot())

    assert ("state",) in robot.calls
    assert snap["robots"][0]["gather_source"] == "rest"


def test_rest_failure_row_shape_is_unchanged():
    robot = FakeRobot("rosy_01")
    robot.state_error = ConnectionError("down")
    console = _console(robot)

    snap = run(console.snapshot())

    one = snap["robots"][0]
    assert one["online"] is False
    assert one["state"] is None
    assert one["gather_source"] is None
    assert one["error"]


def test_gather_lookup_does_not_create_registry_records():
    robot = FakeRobot("rosy_99")  # hub에 unknown인 로봇
    console = _console(robot)

    run(console.snapshot())

    assert console.hub.registry.find("rosy_99") is None


def test_hub_heartbeat_stamps_arrival_time():
    hub = SiteHub([_ep()])
    assert hub.handle(_hello()).type is not EnvelopeType.ERROR
    snap = StateSnapshot(robot_id="rosy_01")
    env = Envelope(type=EnvelopeType.HEARTBEAT,
                   payload=HeartbeatPayload(state_snapshot=snap).model_dump(mode="json"))
    reply = hub.handle(env)

    assert reply.type is EnvelopeType.HEARTBEAT
    row = hub.registry.find("rosy_01")
    assert row is not None and row.snapshot is not None
    assert row.last_heartbeat_monotonic is not None  # D-447: 도착 스탬프


# --- D-493: state_age_s -----------------------------------------------------------------

def test_snapshot_marks_when_each_state_was_observed():
    clock = FakeClock()
    hub_robot, rest_robot, down = FakeRobot("rosy_01"), FakeRobot("rosy_02"), FakeRobot("rosy_03")
    down.state_error = ConnectionError("no route")
    console = _console(hub_robot, rest_robot, down, clock=clock)
    row = console.hub.registry.record("rosy_01")
    row.online, row.snapshot = True, StateSnapshot(robot_id="rosy_01")
    row.last_heartbeat_monotonic = clock() - 2.0

    rows = {r["robot_id"]: r for r in run(console.snapshot())["robots"]}

    assert rows["rosy_01"]["_state_mono"] == clock() - 2.0   # heartbeat time, not gather time
    assert rows["rosy_02"]["_state_mono"] == clock()          # REST: read just now
    assert "_state_mono" not in rows["rosy_03"]


def test_state_route_ages_a_cached_hub_row_and_hides_the_internal_stamp(tmp_path):
    from test_line_stuck_api import VIEWER, _auth, _console as _stuck_console, _named_app

    clock = FakeClock()
    robot = FakeRobot("rosy_01")
    console = _stuck_console(robot, clock=clock)
    row = console.hub.registry.record("rosy_01")
    row.online, row.snapshot = True, StateSnapshot(robot_id="rosy_01")
    row.last_heartbeat_monotonic = clock() - 2.0
    client, _ = _named_app(console, tmp_path)

    first = client.get("/api/fleet/state", headers=_auth(VIEWER))
    clock.advance(0.5)                                        # still inside SharedGather's 1 s
    second = client.get("/api/fleet/state", headers=_auth(VIEWER))

    assert first.json()["robots"][0]["state_age_s"] == 2.0
    body = second.json()
    assert body["robots"][0]["state_age_s"] == 2.5
    assert body["gathered_at"] == first.json()["gathered_at"] > 0  # gather time, not response time
    assert "_state_mono" not in first.text and "_state_mono" not in second.text


def test_state_route_offline_robot_has_null_age(tmp_path):
    from test_line_stuck_api import VIEWER, _auth, _console as _stuck_console, _named_app

    robot = FakeRobot("rosy_01")
    robot.state_error = ConnectionError("no route")
    client, _ = _named_app(_stuck_console(robot), tmp_path)

    one = client.get("/api/fleet/state", headers=_auth(VIEWER)).json()["robots"][0]

    assert one["online"] is False and one["state_age_s"] is None
