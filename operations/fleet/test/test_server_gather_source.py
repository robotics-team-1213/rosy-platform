"""D-447 (a): Fleet gather 출처 — hub-fresh 로봇은 registry 스냅샷, 나머지는 REST 폴백.

새 전송 계약은 없다. 응답 스키마는 불변이고 행에 `gather_source` 만 더해진다
(additive). hub 경로의 상태는 heartbeat(PRT-003, 1 Hz)가 실어 온 것과 바이트가 같다.
"""

from fakes import FakeClock, FakeRobot, run
from test_hub import _ep, _hello

from core_common.protocol.schemas import Envelope, EnvelopeType, HeartbeatPayload, StateSnapshot
from fleet.hub.hub import SiteHub
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint


def _console(*robots: FakeRobot, clock=None) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots), clock=clock or FakeClock())


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
