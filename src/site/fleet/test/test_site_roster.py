"""D-352 S1: SiteRoster is the one owner of the dynamic robot list."""

from __future__ import annotations

import asyncio

import pytest

from fakes import FakeRobot, run
from fleet.hub.hub import HubError
from fleet.server.console import FleetConsole
from fleet.server.roster import SiteRoster
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload


def _ep(robot_id: str, port: int = 8080, pairing: str | None = None) -> RobotEndpoint:
    return RobotEndpoint(robot_id, f"http://192.168.1.50:{port}", f"rest-{robot_id}",
                         fleet_pairing_token=pairing)


class ClosableRobot(FakeRobot):
    def __init__(self, robot_id: str, **kwargs) -> None:
        super().__init__(robot_id, **kwargs)
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def _roster(tmp_path, *robots, sightings=None):
    endpoints = [_ep(r.robot_id, 8080 + i) for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, list(robots))
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                             robot_ids=set(console.robot_ids))
    roster = SiteRoster(console, task_service=tasks, sightings=sightings)
    return console, tasks, roster


def _hello(robot_id: str, token: str) -> Envelope:
    return Envelope(type=EnvelopeType.HELLO,
                    payload=HelloPayload(robot_id=robot_id, pairing_token=token).model_dump())


def test_added_robot_appears_everywhere_at_once(tmp_path):
    source = SightingSource("ceiling", "sight-" + "tok", ("rosy_01",), "m1", "r1", (0, 1, 2, 3))
    sightings = SightingService([source], known_robot_ids=["rosy_01"])
    console, tasks, roster = _roster(tmp_path, FakeRobot("rosy_01"), sightings=sightings)

    added = FakeRobot("rosy_09")
    roster.add(_ep("rosy_09", 9000, pairing="pair-" + "nine"), added, source="enrolled")

    assert roster.robot_ids == ["rosy_01", "rosy_09"]
    assert roster.source_of("rosy_09") == "enrolled" and roster.source_of("rosy_01") == "file"
    assert [r["robot_id"] for r in run(console.snapshot())["robots"]] == ["rosy_01", "rosy_09"]
    assert console.registered_endpoints["rosy_09"] == "http://192.168.1.50:9000"
    assert "rosy_09" in tasks.robot_ids
    assert "rosy_09" in sightings.known_robot_ids
    assert console.uses_rest_token("rest-rosy_09")
    reply = console.hub.handle(_hello("rosy_09", "pair-" + "nine"))
    assert reply.type is EnvelopeType.WELCOME


def test_estop_all_reaches_an_added_robot(tmp_path):
    console, _, roster = _roster(tmp_path, FakeRobot("rosy_01"))
    added = FakeRobot("rosy_09")
    roster.add(_ep("rosy_09", 9000), added)

    result = run(console.estop_all())

    assert result["stopped"] == 2
    assert ("estop",) in added.calls


def test_add_during_an_inflight_gather_keeps_rows_aligned(tmp_path):
    slow = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    fast = FakeRobot("rosy_02", state={"robot_id": "rosy_02", "mode": "DOCKED"})
    console, _, roster = _roster(tmp_path, slow, fast)
    slow.state_gate = asyncio.Event()

    async def scenario():
        gather = asyncio.ensure_future(console.snapshot())
        for _ in range(5):
            await asyncio.sleep(0)
        roster.add(_ep("rosy_00", 9000), FakeRobot("rosy_00", state={"robot_id": "rosy_00",
                                                                      "mode": "NEW"}))
        slow.state_gate.set()
        return await gather

    snapshot = run(scenario())
    rows = {row["robot_id"]: row for row in snapshot["robots"]}
    assert [row["robot_id"] for row in snapshot["robots"]] == ["rosy_01", "rosy_02"]
    assert rows["rosy_01"]["state"]["mode"] == "IDLE"
    assert rows["rosy_02"]["state"]["mode"] == "DOCKED"


def test_remove_during_an_inflight_estop_still_reports_each_robot(tmp_path):
    first, second = ClosableRobot("rosy_01"), ClosableRobot("rosy_02")
    console, _, roster = _roster(tmp_path, first)
    roster.add(_ep("rosy_02", 9000), second)
    gate = asyncio.Event()

    async def slow_estop():
        await gate.wait()
        first._record("estop")
        return {"estop": True}

    first.estop = slow_estop

    async def scenario():
        stop = asyncio.ensure_future(console.estop_all())
        for _ in range(5):
            await asyncio.sleep(0)
        await roster.remove("rosy_02")
        gate.set()
        return await stop

    result = run(scenario())
    assert [row["robot_id"] for row in result["robots"]] == ["rosy_01", "rosy_02"]


def test_task_can_be_created_for_an_added_robot(tmp_path):
    _, tasks, roster = _roster(tmp_path, FakeRobot("rosy_01"))
    roster.add(_ep("rosy_09", 9000), FakeRobot("rosy_09"))

    task = run(tasks.submit_navigation(robot_id="rosy_09", x=1.0, y=2.0, source="operator",
                                       actor_id="alice", request_key="k-1"))

    assert task["robot_id"] == "rosy_09" and task["status"] == "QUEUED"


def test_remove_closes_the_client_and_forgets_goals(tmp_path):
    console, tasks, roster = _roster(tmp_path, FakeRobot("rosy_01"))
    added = ClosableRobot("rosy_09")
    roster.add(_ep("rosy_09", 9000, pairing="pair-" + "nine"), added)
    run(console.goal("rosy_09", 1.0, 1.0))

    run(roster.remove("rosy_09"))

    assert added.closed == 1
    assert roster.robot_ids == ["rosy_01"]
    assert "rosy_09" not in console.registered_endpoints
    assert "rosy_09" not in tasks.robot_ids
    assert not console.uses_rest_token("rest-rosy_09")
    assert run(console.snapshot())["robots"][0]["robot_id"] == "rosy_01"
    assert console._goals == {} and console._claims == {}
    assert console.hub.handle(_hello("rosy_09", "pair-" + "nine")).type is EnvelopeType.ERROR


def test_remove_refuses_a_formation_member(tmp_path):
    console, _, roster = _roster(tmp_path, FakeRobot("rosy_01"))
    roster.add(_ep("rosy_09", 9000), FakeRobot("rosy_09"))

    class Session:
        state = "RUNNING"
        assignment = {"rosy_09": object()}

    console._formation = Session()
    with pytest.raises(HubError) as refused:
        run(roster.remove("rosy_09"))
    assert refused.value.code == "FORMATION_ACTIVE"
    assert "rosy_09" in roster.robot_ids


def test_remove_refuses_a_robot_with_unfinished_tasks(tmp_path):
    _, tasks, roster = _roster(tmp_path, FakeRobot("rosy_01"))
    roster.add(_ep("rosy_09", 9000), FakeRobot("rosy_09"))
    task = run(tasks.submit_navigation(robot_id="rosy_09", x=1.0, y=2.0, source="operator",
                                       actor_id="alice", request_key="k-1"))

    with pytest.raises(HubError) as refused:
        run(roster.remove("rosy_09"))

    assert refused.value.code == "ACTIVE_TASKS"
    assert refused.value.task_ids == [task["task_id"]]
    assert "rosy_09" in roster.robot_ids


def test_duplicate_or_static_robot_id_is_refused(tmp_path):
    _, _, roster = _roster(tmp_path, FakeRobot("rosy_01"))
    with pytest.raises(HubError) as refused:
        roster.add(_ep("rosy_01", 9000), FakeRobot("rosy_01"))
    assert refused.value.code == "ROBOT_ID_CONFLICT"
    with pytest.raises(HubError):
        run(roster.remove("rosy_01"))  # file robots are not removed here


def test_sightings_refuse_a_removed_robot(tmp_path):
    source = SightingSource("ceiling", "sight-" + "tok", ("rosy_01",), "m1", "r1", (0, 1, 2, 3))
    sightings = SightingService([source], known_robot_ids=["rosy_01"])
    _, _, roster = _roster(tmp_path, FakeRobot("rosy_01"), sightings=sightings)
    roster.add(_ep("rosy_09", 9000), FakeRobot("rosy_09"))
    run(roster.remove("rosy_09"))
    assert "rosy_09" not in sightings.known_robot_ids
