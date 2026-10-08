"""D-517 5 (M4): Fleet's resolver decisions for trip robots the block table cannot move (pure)."""

from fleet.traffic.handover import CYCLE_PERIODS, UNKNOWN_LIMIT_S, decide


def _decide(cycle, avoidable=None, tried=None, pending=(), unknown=None, now=0.0, periods=CYCLE_PERIODS):
    return decide(cycle, periods, avoidable or {}, tried or {}, set(pending), unknown or {}, now)


def test_one_cycle_member_that_can_leave_first_is_replanned_the_others_wait():
    out = _decide(("b", "a"), {"b": ["ring_n"]})
    assert out["b"] == {"trigger": "wait_cycle", "cycle": ["b", "a"], "decision": "replan", "blocked_edges": ["ring_n"]}
    assert out["a"]["decision"] == "wait"
    both = _decide(("a", "b"), {"a": ["x"], "b": ["y"]})
    assert [both[r]["decision"] for r in ("a", "b")] == ["replan", "wait"]  # one replan per cycle, by id


def test_a_cycle_must_persist_before_a_replan_is_chosen():
    """Review M2: a one-period cycle (any-holder over-approximation) never makes a hold."""
    assert _decide(("a", "b"), {"b": ["y"]}, periods=CYCLE_PERIODS - 1) == {}
    assert _decide(("a", "b"), {"b": ["y"]}, periods=CYCLE_PERIODS)["b"]["decision"] == "replan"


def test_a_pending_replan_hold_keeps_replan_and_wait_until_the_operator_answers():
    """Review M2: while the replanned robot's hold waits for the operator the rows stay replan/wait."""
    out = _decide(("a", "b"), {}, tried={"b": ["y"]}, pending={"b"}, periods=1)
    assert (out["b"]["decision"], out["b"]["blocked_edges"], out["a"]["decision"]) == ("replan", ["y"], "wait")


def test_a_cycle_nobody_can_leave_or_already_tried_goes_to_a_human():
    assert {r["decision"] for r in _decide(("a", "b")).values()} == {"human"}
    tried = _decide(("a", "b"), {"a": ["x"], "b": ["y"]}, tried={"a": ["x"]})  # no hold pending any more
    assert {r["decision"] for r in tried.values()} == {"human"}  # the replan did not end it: no second guess


def test_unknown_past_the_limit_goes_to_a_human_and_wins_over_a_cycle():
    assert _decide(None, unknown={"a": 0.0}, now=UNKNOWN_LIMIT_S) == {}
    out = _decide(("a", "b"), {"b": ["y"]}, unknown={"a": 0.0}, now=UNKNOWN_LIMIT_S + 0.1)
    assert out["a"] == {"trigger": "unknown", "decision": "human", "since": 0.0}
    assert out["b"]["decision"] == "human"  # a cycle member is UNKNOWN: nothing is planned around it
