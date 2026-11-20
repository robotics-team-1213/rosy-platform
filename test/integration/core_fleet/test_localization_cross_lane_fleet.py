"""D-395 Phase 2 cross-lane contract, lane C: Fleet against CORE (B) and the robot core (A).

Lane C's `HttpRobotClient` calls lane B's FastAPI app in process (ASGI), and lane C's
`Arbiter` makes the decision from the report it fetched. Lanes A and B, their wire
format and fixtures are in middleware/core/gateway/test/test_localization_cross_lane.py.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")

from fleet.localization.arbiter import Arbiter, Context  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402
from fleet.swarm.transport import HttpRobotClient  # noqa: E402
from test_localization_cross_lane import (  # noqa: E402,F401  (stack and clocked are fixtures)
    FLEET_TOKEN, OPERATOR, _advance, _relay, _robot_state, _to_candidates, clocked, stack)


def _fleet_call(stack, robot_id: str, call):
    """Run one lane C client call against lane B's app."""

    async def go():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=stack.client.app),
                                 base_url="http://robot")
        client = HttpRobotClient(RobotEndpoint(robot_id, "http://robot", FLEET_TOKEN), http=http)
        try:
            return await call(client)
        finally:
            await http.aclose()

    return asyncio.run(go())


def _localize_through_fleet(stack) -> str:
    """C fetches B's report, arbitrates and posts; A checks the pose; B sees LOCALIZED."""
    _to_candidates(stack)
    robot_id = stack.services.localization.candidates().robot_id
    arbiter = Arbiter(hold_s=0.0)

    async def fetch_and_decide(client):
        decision = None
        for _ in range(2):          # the arbiter's lead needs a second look
            report = await client.localization_candidates()
            assert report is not None and report.robot_id == robot_id
            decision = arbiter.observe(report, Context(), stack.robot.now) or decision
        assert decision is not None and decision.candidate_index == 0
        assert [c.value for c in decision.cues] == ["paint"]
        return await client.localization_decision(decision)

    assert _fleet_call(stack, robot_id, fetch_and_decide) == {"request_id": "req-1"}

    # CORE -> robot: B's decision payload is what A's on_decision accepts.
    [raw] = stack.sent["decision"]
    robot = stack.robot
    robot.now += 0.1
    topics = robot.wire(robot.core.on_decision(robot.now, json.loads(raw)))
    assert "result" not in topics, topics.get("result")
    [injection] = robot.injected
    assert injection.pose == (1.0, 2.0, 0.0) and injection.source == "candidate"

    # settle 0.5 s + hold 1 s of good fits; A's result and LOCALIZED state parse in B.
    for _ in range(20):
        robot.now += 0.1
        _relay(stack.services, robot.wire(robot.core.on_fit(robot.now, 0.95)))
    return robot_id


def test_fleet_decision_round_trip_localizes_the_robot(stack):
    _localize_through_fleet(stack)
    results = [e.data for e in stack.services.events.history() if e.type == "localization.result"]
    assert results == [{"request_id": "req-1", "accepted": True, "reason": None,
                        "state": "LOCALIZED", "source": "candidate", "cues": ["paint"]}]
    assert _robot_state(stack)["state"] == "LOCALIZED"
    assert stack.services.localization.autonomy_allowed()


def test_a_localized_robots_objects_reach_fleet_through_the_snapshot(stack):
    """D-395 rev. 4 §5 follow-up (S1 R1): A's LOCALIZED state carries its objects, B relays
    them in `/robot/state`, and C's snapshot parser reads them back."""
    from fleet.localization import trust
    _localize_through_fleet(stack)
    robot = stack.robot
    assert robot.core.objects_due(robot.now)
    robot.core.on_objects(robot.now, robot.now - 0.05, [(0.6, -0.1), (1.2, 0.4)])
    robot.now += 0.5
    _relay(stack.services, robot.wire(robot.core.tick(robot.now)))
    state = stack.client.get("/api/v1/robot/state", headers=OPERATOR).json()
    raw = state["localization"]
    assert raw["state"] == "LOCALIZED" and raw["objects_stamp"] == pytest.approx(robot.now - 0.55)
    status = trust.status_of(state)
    assert [(o.x, o.y) for o in status.unmapped_objects] == [(0.6, -0.1), (1.2, 0.4)]
    robot.now += 1.0                      # the scan is older than 1 s: the robot leaves them out
    _relay(stack.services, robot.wire(robot.core.tick(robot.now)))
    assert _robot_state(stack)["unmapped_objects"] == []


def test_fleet_suspect_reaches_the_robot(stack):
    robot_id = _localize_through_fleet(stack)
    assert _fleet_call(stack, robot_id,
                       lambda client: client.localization_suspect("fleet_monitor")) == {
        "accepted": True}
    [raw] = stack.sent["suspect"]
    robot = stack.robot
    robot.now += 0.1
    _relay(stack.services, robot.wire(robot.core.on_suspect(robot.now, json.loads(raw))))
    status = _robot_state(stack)
    assert status["state"] == "SUSPECT" and status["reason"] == "fleet_monitor"
    assert not stack.services.localization.autonomy_allowed()


def test_the_stale_window_runs_on_the_line_clock(clocked):
    _localize_through_fleet(clocked)
    robot = clocked.robot
    _advance(clocked, 0.5)                 # the robot's state cadence: one heartbeat
    heartbeat = robot.wire(robot.core.tick(robot.now))
    assert heartbeat.get("state"), "the robot re-publishes its state on its own clock"
    _relay(clocked.services, heartbeat)
    status = clocked.services.localization.status
    _advance(clocked, 2.9)
    assert status().state.value == "LOCALIZED"
    _advance(clocked, 0.2)
    assert status().reason == "state_stale"


def test_fleet_mission_runs_in_core_and_the_robot_searches_after_it(stack):
    """P2-7: C asks B for a rotate; B drives and ends it; A searches again after the end."""
    from fleet.swarm.transport import RobotApiError

    _to_candidates(stack)
    services, robot = stack.services, stack.robot
    mission = services.loc_mission
    published = []
    mission.publish = lambda body: published.append(json.dumps(body))   # as ros_bridge does
    clock = SimpleNamespace(now=100.0)
    mission._clock = lambda: clock.now
    sample = {"ranges": [2.0] * 360, "angle_min": 0.0, "angle_max": 6.2657,
              "range_min": 0.05, "range_max": 8.0}
    mission.observe_scan(sample)
    mission.observe_odom(0.0, 0.0, 0.0)
    robot_id = services.localization.candidates().robot_id

    started = _fleet_call(stack, robot_id, lambda client: client.localization_mission(
        "rotate_in_place", max_distance_m=0.0, max_time_s=30.0))
    assert started["state"] == "running"
    with pytest.raises(RobotApiError) as refused:
        _fleet_call(stack, robot_id, lambda client: client.localization_mission(
            "to_square", max_distance_m=1.0, max_time_s=60.0, target={"square": [0.86, -0.52]}))
    assert refused.value.status == 409 and refused.value.code == "unsupported"

    robot.core.on_mission(robot.now, json.loads(published[0]))
    assert not robot.core.search_due(robot.now, (0.0, 0.0, 0.0))     # moving: no search
    yaw = 0.0
    for _ in range(45):
        clock.now += 0.05
        yaw += 0.15
        mission.observe_odom(0.0, 0.0, yaw)
        mission.observe_scan(sample)
        mission.tick()
    assert mission.status() == {"kind": "rotate_in_place", "state": "done", "reason": "done"}
    robot.core.on_mission(robot.now, json.loads(published[-1]))
    # S1 re-run R3: the search also waits until the robot has stood still for 0.5 s.
    for dt in (0.0, 0.3, 0.6):
        robot.core.on_twist(robot.now + dt, 0.0, 0.0)
    assert robot.core.search_due(robot.now + 0.6, (0.0, 0.0, 0.1))   # fresh candidates now
