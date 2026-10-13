"""D-517 9 M3: lane convoy trips — POST /trip ``convoy``, start refusals, the follower's moving block."""

from __future__ import annotations

import itertools

import pytest

from core_common.robot_body import PINKY_PRO
from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.traffic.lane_traffic import MEMBER_REVERSE_M
from fleet.server.trip_ports import TripError
from test_lane_traffic import _arc
from test_trip_authority import AUTH, _setup, _ticks
from test_trip_runner import LANE, OPERATOR, Ports, _app, run

BODY = PINKY_PRO.front_x_m - PINKY_PRO.rear_x_m
_IDS = itertools.count()


def _trip(runner, store, fleet, robot_id, arc_id, s, leader=None, to="start_n", via=("start_s",)):
    graph = store.active()[2]
    arc = graph.arcs[arc_id]
    fleet.at(robot_id, arc, s)
    plan = plan_trip(graph, PlanRequest(store.active()[0], arc.point_at(s), to, via=tuple(via)), store.routing_config)
    request = {"to": to, "via": list(via), "repeat": True, **({"convoy": {"leader": leader}} if leader else {})}
    plan_id = f"{robot_id}-{next(_IDS)}"
    store.record_plan(plan_id=plan_id, robot_id=robot_id, principal_id="bob", map_version=plan.map_version,
                      request=request, result={"plan": plan_body(plan)})
    return run(runner.start(plan_id, "bob"))


def _refused(runner, store, fleet, *args, **kwargs):
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, *args, **kwargs)
    return err.value.code


def _row(runner, robot_id):
    return next(r for r in runner.traffic.view()["robots"] if r["robot_id"] == robot_id)


def test_start_refusals_name_the_convoy_rule():
    runner, store, fleet = _setup({r: AUTH for r in "abcde"} | {"m": LANE})
    assert _refused(runner, store, fleet, "b", "east:fwd", 0.3, leader="a") == "TRIP_CONVOY_LEADER_NOT_RUNNING"
    view = _trip(runner, store, fleet, "a", "east:fwd", 1.5)
    assert view["convoy"] is None
    _ticks(runner, fleet)  # the leader is located on its plan
    # from ring_s the roundabout arc ring_e would take it past the leader: not behind it on the loop
    ring = _arc(store, "ring_s:fwd")
    shortcut = _refused(runner, store, fleet, "b", "ring_s:fwd", ring.length_m - 0.2, leader="a")
    assert shortcut == "TRIP_CONVOY_NOT_BEHIND"
    assert _refused(runner, store, fleet, "b", "east:fwd", 2.0, leader="a") == "TRIP_CONVOY_NOT_BEHIND"  # ahead
    assert _trip(runner, store, fleet, "b", "east:fwd", 0.3, leader="a")["convoy"] == {"leader": "a"}
    assert _refused(runner, store, fleet, "c", "west:fwd", 0.5, leader="b") == "TRIP_CONVOY_LEADER_IS_FOLLOWER"
    assert _refused(runner, store, fleet, "m", "west:fwd", 0.5, leader="a") == "TRIP_CONVOY_NO_AUTHORITY"
    assert runner.convoy_refusal("c", "c") == ("TRIP_CONVOY_SELF", {"leader": "c"})
    assert runner.convoy_refusal("c", "a", cycle=frozenset({"start_n"}))[0] == "TRIP_CONVOY_OTHER_LOOP"
    assert runner.convoy_refusal("c", "a", cycle=frozenset({"start_n", "start_s"})) is None
    _trip(runner, store, fleet, "c", "west:fwd", 0.5, leader="a", to="start_s", via=("start_n",))
    # a convoy counts as 1 + N on the loop (capacity 3 on the demo loop)
    assert _refused(runner, store, fleet, "d", "west:fwd", 2.0, leader="a", to="start_s",
                    via=("start_n",)) == "TRIP_CONVOY_LOOP_FULL"


def test_the_follower_keeps_the_gap_behind_its_leader_across_lanes():
    runner, store, fleet = _setup({"a": AUTH, "b": AUTH})
    ring = _arc(store, "ring_s:fwd")
    _trip(runner, store, fleet, "a", "east:fwd", 0.4)
    _ticks(runner, fleet)
    # on ring_s behind a, first to start_n on a's east (no roundabout shortcut)
    _trip(runner, store, fleet, "b", "ring_s:fwd", ring.length_m - 0.1, leader="a", to="start_s", via=("start_n",))
    _ticks(runner, fleet)
    row, live = _row(runner, "b"), runner._live["b"]
    leader_front = ring.length_m + 0.4 + PINKY_PRO.front_x_m  # a's front in b's route metres
    assert row["convoy"]["leader"] == row["convoy"]["follows"] == "a"
    assert row["convoy"]["gap_m"] == pytest.approx(leader_front - BODY - row["front_d_m"], abs=1e-3)
    u = runner.config.expect_tol_min_m
    # Safety-Review: the gap covers the most the leader may reverse (D-407 back-off, D-468 retrace)
    gap = PINKY_PRO.resume_gap_m(LANE.max_speed) + MEMBER_REVERSE_M + 3 * u
    assert MEMBER_REVERSE_M >= 0.20 + 0.15 and row["authority_end_m"] <= leader_front - BODY - gap + 1e-3
    assert live.traffic["waiting_for"] == ["a"]  # standing back is waiting, not a stall
    sent = fleet.bodies["b"][-1]["until_m"]
    fleet.at("a", _arc(store, "east:fwd"), 2.0)  # the leader drives on: the end follows it
    # 1.6 m in one period is a pose jump for an authority robot (D-525): taken after JUMP_SETTLE_PERIODS
    _ticks(runner, fleet, n=4)
    assert fleet.bodies["b"][-1]["until_m"] > sent + 0.5
    assert _row(runner, "a")["convoy"] is None


def test_a_recovering_leader_is_not_followed():
    """Safety-Review MAJOR: a D-407 stuck or RECOVERING (D-468 retrace) member may reverse; no moving block."""
    runner, store, fleet = _setup({"a": AUTH, "b": AUTH})
    _trip(runner, store, fleet, "a", "east:fwd", 1.5)
    _ticks(runner, fleet)
    _trip(runner, store, fleet, "b", "east:fwd", 0.2, leader="a")
    _ticks(runner, fleet, n=2)
    assert _row(runner, "b")["convoy"]["follows"] == "a"
    inner = fleet.junction_state

    async def recovering(robot_id):
        line = await inner(robot_id)
        return {**(line or {}), "line_recovering": robot_id == "a"}

    fleet.junction_state = recovering
    _ticks(runner, fleet)
    assert _row(runner, "b")["convoy"] == {"leader": "a", "follows": None, "gap_m": None}  # fixed blocks


def test_a_canceled_leader_leaves_the_follower_on_fixed_blocks_without_a_smaller_end():
    runner, store, fleet = _setup({"a": AUTH, "b": AUTH})
    _trip(runner, store, fleet, "a", "east:fwd", 1.1)
    _ticks(runner, fleet)
    _trip(runner, store, fleet, "b", "east:fwd", 0.5, leader="a")
    _ticks(runner, fleet, n=2)
    before = runner.traffic._state.authority["b"]
    run(runner.cancel(runner._live["a"].view["trip_id"], "bob"))
    _ticks(runner, fleet, n=3)
    row = _row(runner, "b")
    assert row["convoy"] == {"leader": "a", "follows": None, "gap_m": None}
    assert row["authority_end_m"] is None or row["authority_end_m"] >= before
    assert runner._live["b"].traffic["waiting_for"] and runner._live["b"].view["state"] == "running"
    ends = [body["until_m"] for body in fleet.bodies["b"]]  # b stands still: until_m is the end itself
    assert ends == sorted(ends)


def test_post_trip_takes_a_convoy_only_with_a_running_leader(tmp_path):
    client, *_rest = _app(tmp_path, Ports())
    url = "/api/fleet/robots/rosy_60/trip"
    body = {"to": "NW", "via": ["NE"], "repeat": True, "convoy": {"leader": "rosy_01"}}
    assert client.post(url, json={**body, "repeat": False}, headers=OPERATOR).status_code == 422
    answer = client.post(url, json=body, headers=OPERATOR)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "TRIP_CONVOY_LEADER_NOT_RUNNING"
    answer = client.post(url, json={**body, "convoy": {"leader": "rosy_60"}}, headers=OPERATOR)
    assert answer.json()["detail"] == {"code": "TRIP_CONVOY_SELF", "detail": {"leader": "rosy_60"}}
