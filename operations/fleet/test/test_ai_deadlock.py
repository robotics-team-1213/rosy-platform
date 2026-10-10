"""D-610 7 (P3): the AI PC picks a wait cycle's replan; Fleet checks it; the trip runner skips replan_hold."""

from __future__ import annotations

from fleet.stuck.ai_first import AiFirst
from fleet.stuck.deadlock import AiReplan
from fleet.traffic.handover import CYCLE_PERIODS, decide
from test_lane_traffic import _cycle, _ticks

WALL = 1_760_000_000.0
PROFILE = "qwen3-vl:8b-instruct@abc:d610-v1"


def test_handover_takes_a_valid_ai_pick_and_marks_it():
    out = decide(("a", "b"), CYCLE_PERIODS, {"a": ["x"], "b": ["y", "z"]}, {}, set(), {}, 0.0, ai_pick=("b", ("z",)))
    assert out["b"] == {"trigger": "wait_cycle", "cycle": ["a", "b"], "decision": "replan", "blocked_edges": ["z"],
                        "ai": True}
    assert out["a"]["decision"] == "wait"
    for bad in (("b", ("x",)), ("c", ("x",)), ("b", ())):     # not avoidable, not a member, nothing to close
        plain = decide(("a", "b"), CYCLE_PERIODS, {"a": ["x"], "b": ["y"]}, {}, set(), {}, 0.0, ai_pick=bad)
        assert plain["a"] == {"trigger": "wait_cycle", "cycle": ["a", "b"], "decision": "replan", "blocked_edges": ["x"]}
    tried = decide(("a", "b"), CYCLE_PERIODS, {"a": ["x"]}, {"a": ["x"]}, set(), {}, 0.0, ai_pick=("a", ("x",)))
    assert {row["decision"] for row in tried.values()} == {"human"}   # already tried on this route: a person


class _Board:
    def __init__(self, proposal):
        self.proposal, self.verdicts = proposal, []

    def problem_proposal(self, problem_id):
        return self.proposal if self.proposal and self.proposal["stuck_id"] == problem_id else None


def _replan(robot="b", edges=("y",), source=f"vlm:{PROFILE}"):
    return {"robot_id": robot, "stuck_id": "deadlock:a:b", "decision": "REPLAN", "reason": "b_can_leave",
            "confidence": 0.7, "source": source, "observed_at": WALL, "ttl_s": 6.0, "body": {"blocked_edges": list(edges)},
            "evidence": {"views": {"rosy_cam": {"frame_id": "c", "captured_at": WALL},
                                   "front": {"frame_id": "f", "captured_at": WALL}},
                         "map_pose": {"state": "LOCALIZED", "age_s": 0.1},
                         "members": {rid: {"views": {"rosy_cam": {"frame_id": f"c:{rid}", "captured_at": WALL},
                                                     "front": {"frame_id": f"f:{rid}", "captured_at": WALL}},
                                           "map_pose": {"state": "LOCALIZED", "age_s": 0.1}}
                                     for rid in ("a", "b")}}}


def _first(robots=("a", "b")):
    first = AiFirst(robots)
    first.wall, first.profiles = (lambda: WALL), (lambda: [PROFILE])
    return first


def test_ai_replan_checks_members_edges_evidence_and_ai_first():
    avoidable = {"b": ["y"]}
    assert AiReplan(_first(), _Board(_replan()))(("a", "b"), avoidable, 0.0) == ("b", ("y",))
    for first, proposal, verdict in (
            (_first(), _replan(edges=("q",)), "edges_not_avoidable"),
            (_first(), _replan(robot="c"), "not_a_member"),
            (_first(), _replan(source="analyzer:x@1"), "not_vlm")):
        board = _Board(proposal)
        assert AiReplan(first, board)(("a", "b"), avoidable, 0.0) is None
        assert board.verdicts[-1]["verdict"] == verdict
    assert AiReplan(_first(robots=("b",)), _Board(_replan()))(("a", "b"), avoidable, 0.0) is None


def test_deadlock_case_is_published_without_a_proposal_and_cleared_when_cycle_closes():
    replan = AiReplan(_first(), _Board(None))
    assert replan(("a", "b"), {"b": ["y"]}, 0.0) is None
    assert replan.case["problem_id"] == "deadlock:a:b"
    assert replan.case["context"]["avoidable"] == {"a": [], "b": ["y"]}
    replan((), {}, 1.0)
    assert replan.case is None


def test_ai_replan_requires_fresh_views_for_every_cycle_member():
    proposal = _replan()
    proposal["evidence"]["members"]["a"]["views"]["front"]["captured_at"] = WALL - 4
    board = _Board(proposal)
    assert AiReplan(_first(), board)(("a", "b"), {"b": ["y"]}, 0.0) is None
    assert board.verdicts[-1]["verdict"] == "evidence_stale:front"


def test_deadlock_proposal_is_not_replayed_and_new_answers_obey_the_cap():
    board = _Board(_replan())
    replan = AiReplan(_first(), board)
    for number in range(3):
        board.proposal["observed_at"] = WALL + number * 0.1
        assert replan(("a", "b"), {"b": ["y"]}, number) == ("b", ("y",))
        assert replan(("a", "b"), {"b": ["y"]}, number) is None
    board.proposal["observed_at"] = WALL + 0.3
    assert replan(("a", "b"), {"b": ["y"]}, 4) is None
    assert board.verdicts[-1]["verdict"] == "ai_exhausted"


def _routable(monkeypatch, runner):
    """This demo map has no other route around ring_n (TRIP_NO_ROUTE); hand back the trip's own plan
    as the replanned route so the switch itself is under test."""
    from fleet.server import trip_runner

    def hold(_active, _pose, _remaining, _request, _caps, blocked, *_args):
        live = runner._live["b"]
        return {"reason": "replan", "map_version": live.view["map_version"], "blocked": sorted(blocked),
                "plan": {k: live.view["plan"][k] for k in ("segments", "places", "actions")}}

    monkeypatch.setattr(trip_runner, "replan_hold", hold)


def test_an_ai_replan_switches_the_route_without_the_operator_after_the_start_checks(monkeypatch):
    runner, _store, fleet = _cycle(monkeypatch)
    _routable(monkeypatch, runner)
    _ticks(runner, fleet, n=CYCLE_PERIODS)
    row = runner._live["b"].traffic["resolver"]
    assert row["decision"] == "replan"
    row["ai"] = True                                  # as handover.decide marks a valid AI pick
    rev = runner._live["b"].route_rev
    _ticks(runner, fleet)
    view = runner.view("b")
    assert view["hold"] is None and view["detail"]["replan_confirmed_by"] == "fleet-ai"
    assert runner._live["b"].route_rev == rev + 1


def test_without_the_ai_mark_the_replan_waits_for_the_operator(monkeypatch):
    runner, _store, fleet = _cycle(monkeypatch)
    _routable(monkeypatch, runner)
    _ticks(runner, fleet, n=CYCLE_PERIODS + 1)
    hold = runner.view("b")["hold"]
    assert hold["reason"] == "replan" and hold["plan"] is not None
    assert "replan_confirmed_by" not in runner.view("b")["detail"]


def test_delayed_ai_reply_reaches_the_trip_runner_before_operator_fallback(monkeypatch):
    runner, _store, fleet = _cycle(monkeypatch)
    runner.traffic._clock = lambda: fleet.now
    _routable(monkeypatch, runner)
    board = _Board(None)
    runner.traffic.ai_replan = AiReplan(_first(), board)
    _ticks(runner, fleet, n=CYCLE_PERIODS + 4)
    assert runner.traffic.ai_replan.case["problem_id"] == "deadlock:a:b"
    assert runner.view("b")["hold"] is None and runner.traffic._tried == {}
    board.proposal = _replan(edges=("ring_n",))
    _ticks(runner, fleet, n=2)
    assert runner.view("b")["hold"] is None
    assert runner.view("b")["detail"]["replan_confirmed_by"] == "fleet-ai"


def test_missing_ai_reply_falls_back_after_the_bounded_wait(monkeypatch):
    runner, _store, fleet = _cycle(monkeypatch)
    runner.traffic._clock = lambda: fleet.now
    _routable(monkeypatch, runner)
    runner.traffic.ai_replan = AiReplan(_first(), _Board(None))
    _ticks(runner, fleet, n=CYCLE_PERIODS + 18)
    assert runner.view("b")["hold"]["reason"] == "replan"
    assert "replan_confirmed_by" not in runner.view("b")["detail"]


def test_an_ai_replan_that_fails_the_start_checks_keeps_the_operator_hold(monkeypatch):
    from fleet.server.trip_runner import TripError
    from test_lane_traffic import run

    runner, _store, fleet = _cycle(monkeypatch)
    _routable(monkeypatch, runner)
    _ticks(runner, fleet, n=CYCLE_PERIODS + 1)
    live = runner._live["b"]
    hold = live.view["hold"]

    async def refuse(*_args, **_kwargs):
        raise TripError(422, "TRIP_POSE_UNTRUSTED")

    monkeypatch.setattr(runner, "_pose_checks", refuse)
    run(runner._ai_confirm(live))
    assert live.view["hold"] == hold and live.view["detail"]["ai_replan_refused"] == "TRIP_POSE_UNTRUSTED"
