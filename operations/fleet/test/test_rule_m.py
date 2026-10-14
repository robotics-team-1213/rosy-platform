"""D-550 7/8, D-760 3 stage 1: the Rule M verdict. Only TTL bounds Fleet itself holds count."""

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
    ({}, ("idle", None, None)),
    # lane trip: authority ttl, or a held trip lease (CORE halts on expiry); else hold_back
    ({"trip": _trip("core"), "leg": "lane"}, ("bounded", "lane_trip", None)),
    ({"trip": _trip(lease=HELD), "leg": "lane"}, ("bounded", "lane_trip", None)),
    ({"trip": _trip(), "leg": "lane"}, ("unbounded", "lane_trip", "hold_back")),
    ({"trip": _trip(lease={"lease_id": "l1", "state": "lost"}), "leg": "lane"},
     ("unbounded", "lane_trip", "hold_back")),
    # trip free leg = a navigation goal; lane authority does not cover it
    ({"trip": _trip(), "leg": "free", "goal": LEASED}, ("bounded", "goal", None)),
    ({"trip": _trip(lease=HELD), "leg": "free", "goal": UNLEASED}, ("bounded", "goal", None)),
    ({"trip": _trip("core"), "leg": "free", "goal": UNLEASED}, ("unbounded", "goal", "no_goal_lease")),
    ({"trip": _trip(), "leg": "free", "goal": None}, ("unbounded", "goal", "no_goal_lease")),
    # navigation/goal: only the goal lease bounds it, whatever the link or SAF-003 policy
    ({"goal": LEASED, "navigation": "NAVIGATING"}, ("bounded", "goal", None)),
    ({"goal": UNLEASED, "navigation": "NAVIGATING"}, ("unbounded", "goal", "no_goal_lease")),
    ({"goal": UNLEASED, "navigation": "PLANNING"}, ("unbounded", "goal", "no_goal_lease")),
    ({"goal": UNLEASED, "navigation": "BLOCKED"}, ("unbounded", "goal", "no_goal_lease")),
    ({"goal": GOAL, "navigation": "NAVIGATING"}, ("unbounded", "goal", "no_goal_lease")),
    # a goal that is over is not a motion
    ({"goal": UNLEASED, "navigation": "ARRIVED"}, ("idle", None, None)),
    ({"goal": UNLEASED, "navigation": "CANCELED"}, ("idle", None, None)),
    ({"goal": UNLEASED, "navigation": "FAILED"}, ("idle", None, None)),
    ({"goal": UNLEASED, "navigation": "IDLE"}, ("idle", None, None)),
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
    ({"goal": UNLEASED}, "no_goal_lease"),                          # no navigation word
    ({"goal": UNLEASED, "navigation": "SOMETHING_NEW"}, "no_goal_lease"),
    ({"goal": UNLEASED, "navigation": {"state": "ARRIVED"}}, "no_goal_lease"),  # malformed robot JSON
    ({"goal": UNLEASED, "navigation": ["IDLE"]}, "no_goal_lease"),
    ({"goal": {"goal_lease": "LEASED"}}, "no_goal_lease"),
])
def test_unknown_input_is_never_bounded_by_guess(kwargs, reason):
    answer = verdict(**kwargs)
    assert (answer["state"], answer["reason"]) == ("unbounded", reason)


def test_the_evaluator_is_pure():
    names = set()
    for node in ast.walk(ast.parse(Path(rule_m.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert names <= {"__future__", "typing"}, names


def test_state_row_carries_the_verdict_and_an_offline_row_carries_none():
    from fastapi.testclient import TestClient
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.swarm.robots import RobotEndpoint

    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token="t")],
                           [robot], clock=FakeClock())
    client = TestClient(create_app(console, console_token="viewer", start_task_dispatcher=False))
    client.app.state.fleet_gather.max_age_s = 0.0

    def row():
        response = client.get("/api/fleet/state", headers={"Authorization": "Bearer viewer"})
        assert response.status_code == 200, response.text
        return response.json()["robots"][0]

    assert row()["rule_m"] == {"state": "idle", "motion": None, "reason": None}
    console._goals["rosy_01"] = dict(GOAL)
    robot._state["navigation"] = {"malformed": True}  # must not fail the whole response
    assert row()["rule_m"] == {"state": "unbounded", "motion": "goal", "reason": "no_goal_lease"}
    robot._state["navigation"] = "ARRIVED"
    assert row()["rule_m"]["state"] == "idle"
    robot.state_error = ConnectionError("offline")
    assert "rule_m" not in row()
