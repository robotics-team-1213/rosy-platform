"""D-550 7/8, D-760 3 stage 1: the Rule M verdict, one row of the D-550 7 table per case."""

import ast
from pathlib import Path

import pytest

from fakes import FakeClock, FakeRobot
from fleet.traffic import rule_m
from fleet.traffic.rule_m import verdict

HELD = {"lease_id": "l1", "state": "held"}
GOAL = {"x": 1.0, "y": 2.0, "yaw": 0.0}
LEASED = {**GOAL, "goal_lease": "leased"}
UNLEASED = {**GOAL, "goal_lease": "unbounded"}


def _trip(authority="hold_back", lease=None):
    return {"trip_id": "t1", "robot_id": "rosy_01", "traffic_authority": authority, "lease": lease}


@pytest.mark.parametrize("kwargs, expected", [
    # nothing in progress
    ({}, ("idle", None, None)),
    ({"gather_source": "hub", "fleet_loss_policy": "CONTINUE"}, ("idle", None, None)),
    # lane trip + authority (ttl) / + trip lease (CORE halts on expiry) / hold_back
    ({"trip": _trip("core"), "leg": "lane"}, ("bounded", "lane_trip", None)),
    ({"trip": _trip(lease=HELD), "leg": "lane"}, ("bounded", "lane_trip", None)),
    ({"trip": _trip(), "leg": "lane"}, ("unbounded", "lane_trip", "hold_back")),
    ({"trip": _trip(), "leg": "lane", "gather_source": "hub", "fleet_loss_policy": "STOP"},
     ("unbounded", "lane_trip", "hold_back")),  # SAF-003 covers goals only
    ({"trip": _trip(lease={"lease_id": "l1", "state": "lost"}), "leg": "lane"},
     ("unbounded", "lane_trip", "hold_back")),
    # trip free leg = a navigation goal
    ({"trip": _trip(), "leg": "free", "goal": LEASED}, ("bounded", "goal", None)),
    ({"trip": _trip(lease=HELD), "leg": "free", "goal": UNLEASED}, ("bounded", "goal", None)),
    ({"trip": _trip("core"), "leg": "free", "goal": UNLEASED}, ("unbounded", "goal", "rest_only")),
    ({"trip": _trip(), "leg": "free", "goal": None, "gather_source": "rest"}, ("unbounded", "goal", "rest_only")),
    # navigation/goal: leased, or paired with a link-bound SAF-003 policy
    ({"goal": LEASED, "navigation": "NAVIGATING", "gather_source": "rest"}, ("bounded", "goal", None)),
    ({"goal": UNLEASED, "navigation": "NAVIGATING", "gather_source": "rest", "fleet_loss_policy": "STOP"},
     ("unbounded", "goal", "rest_only")),
    ({"goal": UNLEASED, "navigation": "NAVIGATING", "gather_source": "hub", "fleet_loss_policy": "STOP"},
     ("bounded", "goal", None)),
    ({"goal": UNLEASED, "navigation": "PLANNING", "gather_source": "hub", "fleet_loss_policy": "HOLD"},
     ("bounded", "goal", None)),
    ({"goal": UNLEASED, "navigation": "BLOCKED", "gather_source": "hub", "fleet_loss_policy": "RETURN_HOME"},
     ("bounded", "goal", None)),
    ({"goal": UNLEASED, "navigation": "NAVIGATING", "gather_source": "hub", "fleet_loss_policy": "CONTINUE"},
     ("unbounded", "goal", "policy_continue")),
    ({"goal": GOAL, "navigation": "NAVIGATING", "gather_source": "hub"}, ("unbounded", "goal", "policy_unknown")),
    # a goal that is over is not a motion
    ({"goal": UNLEASED, "navigation": "ARRIVED", "gather_source": "rest"}, ("idle", None, None)),
    ({"goal": UNLEASED, "navigation": "CANCELED"}, ("idle", None, None)),
    ({"goal": UNLEASED, "navigation": "FAILED"}, ("idle", None, None)),
    ({"goal": UNLEASED, "navigation": "IDLE"}, ("idle", None, None)),
    # swarm follow: stream timeout
    ({"follower": True}, ("bounded", "follow", None)),
    ({"follower": True, "goal": UNLEASED, "navigation": "ARRIVED"}, ("bounded", "follow", None)),
])
def test_verdict_follows_the_d550_table(kwargs, expected):
    answer = verdict(**kwargs)
    assert (answer["state"], answer["motion"], answer["reason"]) == expected
    assert set(answer) == {"state", "motion", "reason"}


@pytest.mark.parametrize("kwargs, reason", [
    ({"trip": _trip("core")}, "leg_unknown"),                       # no current leg
    ({"trip": _trip("core"), "leg": "tow"}, "leg_unknown"),         # a mode this table does not know
    ({"trip": {"robot_id": "rosy_01"}, "leg": "lane"}, "hold_back"),  # view without authority or lease
    ({"trip": _trip(lease="held"), "leg": "lane"}, "hold_back"),    # lease of the wrong shape
    ({"goal": UNLEASED}, "rest_only"),                              # offline: no state, no source
    ({"goal": UNLEASED, "navigation": "SOMETHING_NEW", "gather_source": "hub", "fleet_loss_policy": "STOP",
      "follower": False}, None),
    ({"goal": UNLEASED, "gather_source": "hub", "fleet_loss_policy": "stop"}, "policy_unknown"),
    ({"goal": UNLEASED, "gather_source": "hub", "fleet_loss_policy": 3}, "policy_unknown"),
    ({"goal": {"goal_lease": "LEASED"}, "gather_source": "ws"}, "rest_only"),
])
def test_unknown_input_is_never_bounded_by_guess(kwargs, reason):
    answer = verdict(**kwargs)
    if reason is None:  # an unknown navigation word still counts as moving; the policy bounds it
        assert answer == {"state": "bounded", "motion": "goal", "reason": None}
    else:
        assert (answer["state"], answer["reason"]) == ("unbounded", reason)


def test_the_evaluator_is_pure():
    names = set()
    for node in ast.walk(ast.parse(Path(rule_m.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert names <= {"__future__", "typing"}, names


# ---- the console state row ---------------------------------------------------------------


def _client(robot, clock):
    from fastapi.testclient import TestClient
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.swarm.robots import RobotEndpoint

    console = FleetConsole([RobotEndpoint(robot_id=robot.robot_id, base_url="http://127.0.0.1:8080", token="t")],
                           [robot], clock=clock)
    return console, TestClient(create_app(console, console_token="viewer", start_task_dispatcher=False))


def _row(client):
    response = client.get("/api/fleet/state", headers={"Authorization": "Bearer viewer"})
    assert response.status_code == 200, response.text
    return response.json()["robots"][0]


def test_state_row_carries_the_verdict_and_a_rest_robot_is_never_asked_for_its_policy():
    robot = FakeRobot("rosy_01")
    console, client = _client(robot, FakeClock())
    assert _row(client)["rule_m"] == {"state": "idle", "motion": None, "reason": None}
    robot._state["navigation"] = "NAVIGATING"
    console._goals["rosy_01"] = {"x": 1.0, "y": 2.0, "yaw": 0.0}
    client.app.state.fleet_gather.max_age_s = 0.0
    assert _row(client)["rule_m"] == {"state": "unbounded", "motion": "goal", "reason": "rest_only"}
    assert ("safety_state",) not in robot.calls


def test_a_hub_paired_robot_policy_is_read_once_per_thirty_seconds():
    from core_common.protocol.schemas import StateSnapshot

    clock = FakeClock()
    robot = FakeRobot("rosy_01")
    robot.safety_state_value = {"fleet_loss_policy": "CONTINUE"}
    console, client = _client(robot, clock)
    hub_row = console.hub.registry.record("rosy_01")
    hub_row.online = True
    hub_row.snapshot = StateSnapshot(robot_id="rosy_01", navigation="NAVIGATING")
    hub_row.last_heartbeat_monotonic = clock()
    console._goals["rosy_01"] = {"x": 1.0, "y": 2.0, "yaw": 0.0}
    client.app.state.fleet_gather.max_age_s = 0.0

    row = _row(client)
    assert row["gather_source"] == "hub"
    assert row["rule_m"] == {"state": "unbounded", "motion": "goal", "reason": "policy_continue"}
    robot.safety_state_value = {"fleet_loss_policy": "STOP"}
    _row(client)
    assert robot.calls.count(("safety_state",)) == 1
    clock.advance(31)
    hub_row.last_heartbeat_monotonic = clock()
    _row(client)  # starts the refresh; this answer may still be the kept value
    assert _row(client)["rule_m"] == {"state": "bounded", "motion": "goal", "reason": None}
    assert robot.calls.count(("safety_state",)) == 2
