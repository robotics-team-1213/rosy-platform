"""D-395 §7 arbiter: decide only on a clear margin held for 2 s; a mirror case per square."""

from __future__ import annotations

import math

import pytest

from core_common.protocol.localization import CandidateReport, DecisionSource
from fleet.localization import cues
from fleet.localization.arbiter import Arbiter, Context, score

A, B = (-1.26, 0.49), (0.86, -0.52)
SLOTS = (cues.Slot(*A, math.pi / 2), cues.Slot(*B, 0.0))


def report(candidates, request_id="r1-1", objects=(), squares=(), pickup=False, robot_id="r1"):
    return CandidateReport.model_validate({
        "robot_id": robot_id, "request_id": request_id, "pickup": pickup, "stamp": 0.0,
        "candidates": [dict(zip(("x", "y", "yaw", "scan_fit", "paint_score"), c)) for c in candidates],
        "unmapped_objects": [{"x": x, "y": y} for x, y in objects],
        "square_sightings": [{"bearing_rad": b, "range_m": r, "confidence": 0.9} for b, r in squares]})


def pair(pose, fit=0.99, paint=(None, None)):
    """The pose and its 180-degree mirror, both fitting the scan equally (symmetric map)."""
    mirror = (-pose[0], -pose[1], math.atan2(math.sin(pose[2] + math.pi), math.cos(pose[2] + math.pi)))
    return [(*pose, fit, paint[0]), (*mirror, fit, paint[1])]


def run(arbiter, rep, context, start=0.0, end=3.0, dt=0.25):
    t = start
    while t <= end + 1e-9:
        decision = arbiter.observe(rep, context, t)
        if decision is not None:
            return t, decision
        t += dt
    return None, None


ON_A = (-1.26, 0.49, -math.pi / 2)
ON_B = (0.86, -0.52, math.pi)
OFF = (-0.9, -0.509, 0.0)

CASES = {
    # name: (candidates, report kwargs, context, expected index or None)
    "slot A beats its mirror": (pair(ON_A), {}, Context(slots=SLOTS), 0),
    "slot B beats its mirror": (pair(ON_B), {}, Context(slots=SLOTS), 0),
    "mirror listed first, slot A still wins": (pair(ON_A)[::-1], {}, Context(slots=SLOTS), 1),
    "mirror listed first, slot B still wins": (pair(ON_B)[::-1], {}, Context(slots=SLOTS), 1),
    "paint breaks the tie off-slot": (pair(OFF, paint=(0.98, 0.02)), {}, Context(slots=SLOTS), 0),
    "a peer seen where it is": (pair(OFF), {"objects": [(0.3, 0.9)]},
                                Context(peers=[(-0.6, 0.391)], slots=SLOTS), 0),
    "square seen on arrival near A": (pair((-1.26, 0.19, math.pi / 2)), {"squares": [(0.0, 0.30)]},
                                      Context(squares=(A, B)), 0),
    "square near B, mirror listed first": (pair((0.56, -0.52, 0.0))[::-1], {"squares": [(0.0, 0.30)]},
                                           Context(squares=(A, B)), 1),
    "symmetric and no cue: no decision": (pair(OFF), {}, Context(slots=SLOTS), None),
    "last good pose alone is below the margin": (pair(OFF), {}, Context(last_good=OFF), None),
    "last good pose after a pickup is ignored": (pair(OFF), {"pickup": True},
                                                 Context(last_good=OFF, slots=SLOTS), None),
}


@pytest.mark.parametrize("name", list(CASES))
def test_decision_table(name):
    candidates, kwargs, context, expected = CASES[name]
    t, decision = run(Arbiter(), report(candidates, **kwargs), context)
    if expected is None:
        assert decision is None
        return
    assert decision.candidate_index == expected and decision.source is DecisionSource.CANDIDATE
    assert decision.request_id == "r1-1" and t == pytest.approx(2.0)
    assert decision.ttl_s == pytest.approx(5.0)
    assert decision.cues and {c.value for c in decision.cues} <= {"paint", "peers", "slot", "square"}
    assert decision.evidence["margin"] >= 1.0


def test_the_lead_must_hold_two_seconds_and_resets_when_the_leader_changes():
    arbiter = Arbiter()
    win = report(pair(ON_A))
    flip = report(pair(ON_A)[::-1])
    assert arbiter.observe(win, Context(slots=SLOTS), 0.0) is None
    assert arbiter.observe(win, Context(slots=SLOTS), 1.5) is None
    assert arbiter.observe(flip, Context(slots=SLOTS), 1.75) is None   # leader index changed
    assert arbiter.observe(flip, Context(slots=SLOTS), 3.5) is None
    assert arbiter.observe(flip, Context(slots=SLOTS), 3.75).candidate_index == 1


def test_a_gap_below_the_margin_resets_the_hold():
    arbiter = Arbiter()
    clear = report(pair(ON_A))
    assert arbiter.observe(clear, Context(slots=SLOTS), 0.0) is None
    assert arbiter.observe(clear, Context(), 1.0) is None              # slot cue gone: no margin
    assert arbiter.observe(clear, Context(slots=SLOTS), 1.5) is None   # hold restarts here
    assert arbiter.observe(clear, Context(slots=SLOTS), 3.0) is None
    assert arbiter.observe(clear, Context(slots=SLOTS), 3.5) is not None


def test_one_decision_per_request_and_a_new_request_starts_over():
    arbiter = Arbiter()
    assert run(arbiter, report(pair(ON_A)), Context(slots=SLOTS))[1] is not None
    assert run(arbiter, report(pair(ON_A)), Context(slots=SLOTS), 3.0, 6.0)[1] is None
    again = run(arbiter, report(pair(ON_A), request_id="r1-2"), Context(slots=SLOTS), 6.0, 9.0)
    assert again[0] == pytest.approx(8.0)


def test_a_single_candidate_still_needs_an_asymmetric_cue():
    """D-395 rev. 3: one scan candidate on a symmetric map is not proof; the robot
    would reject a decision without a cue, so the arbiter does not send one."""
    assert run(Arbiter(), report([(*OFF, 0.97, None)]), Context())[1] is None
    t, decision = run(Arbiter(), report([(*ON_A, 0.97, None)]), Context(slots=SLOTS))
    assert decision.candidate_index == 0 and t == pytest.approx(2.0)
    assert [c.value for c in decision.cues] == ["slot"]


def test_the_decision_names_only_the_cues_that_separated_the_leader():
    _, decision = run(Arbiter(), report(pair(OFF, paint=(0.98, 0.02))), Context(slots=SLOTS))
    assert [c.value for c in decision.cues] == ["paint"]


def test_robots_are_arbitrated_independently():
    arbiter = Arbiter()
    r1, r2 = report(pair(ON_A)), report(pair(ON_B), robot_id="r2", request_id="r2-1")
    for t in (0.0, 1.0):
        assert arbiter.observe(r1, Context(slots=SLOTS), t) is None
        assert arbiter.observe(r2, Context(slots=SLOTS), t + 0.5) is None
    assert arbiter.observe(r1, Context(slots=SLOTS), 2.0).request_id == "r1-1"
    assert arbiter.observe(r2, Context(slots=SLOTS), 2.5).request_id == "r2-1"


def test_score_reports_every_cue_and_the_total():
    rows = score(report(pair(ON_A)), Context(slots=SLOTS), 0.0)
    assert set(rows[0]) == {"scan_fit", "paint", "peers", "slot", "last_good", "overhead", "square", "total"}
    assert rows[0]["total"] == pytest.approx(0.99 + 1.5) and rows[1]["total"] == pytest.approx(0.99)


def test_a_hidden_peer_cannot_carry_a_decision_to_the_mirror():
    """Review C1 / S1 finding 3: a peer in range but hidden from the scan scores 0 for
    every candidate, so it cannot lead anyone, let alone the mirror."""
    truth, twin = (1.0, 0.0, 0.0), (-1.0, 0.0, math.pi)
    rep = report([(*truth, 0.9, None), (*twin, 0.9, None)])
    assert [row["peers"] for row in score(rep, Context(peers=[(1.0, 0.94)]), 0.0)] == [0.0, 0.0]
    assert run(Arbiter(), rep, Context(peers=[(1.0, 0.94)]))[1] is None


def test_a_cue_must_beat_every_other_candidate_not_just_the_runner_up():
    """Review I2: paint 0.5 for both twins does not separate them, even when a third
    candidate (paint 0.48, better scan fit) ranks second; last_good + overhead fill
    the margin, and they may not carry a decision (rev. 3)."""
    twin = (-OFF[0], -OFF[1], math.pi)
    rep = report([(*OFF, 0.95, 0.5), (*twin, 0.9, 0.5), (0.0, 0.3, 0.0, 0.95, 0.48)])
    rows = score(rep, Context(last_good=OFF, sighting=cues.Sighting(*OFF, captured_at=0.0)), 0.0)
    assert sorted(range(3), key=lambda i: -rows[i]["total"]) == [0, 2, 1]   # the third is runner-up
    assert rows[0]["total"] - rows[2]["total"] >= 1.0                      # and the margin holds
    arbiter = Arbiter()
    for k in range(13):
        t = k * 0.25
        context = Context(last_good=OFF, sighting=cues.Sighting(*OFF, captured_at=t))
        assert arbiter.observe(rep, context, t) is None


def test_a_newer_report_for_the_same_request_can_be_decided_again():
    """Review M4: a lost or rejected decision is retried when the robot re-reports."""
    arbiter = Arbiter()
    assert run(arbiter, report(pair(ON_A)), Context(slots=SLOTS))[1] is not None
    rep2 = report(pair(ON_A)).model_copy(update={"stamp": 5.0})
    assert run(arbiter, rep2, Context(slots=SLOTS), 6.0, 9.0)[0] == pytest.approx(8.0)


# --- pending (S1 re-run R2): the ladder waits while the arbiter may still decide -------------


def test_a_held_lead_is_pending_for_its_request_only():
    arbiter = Arbiter()
    assert arbiter.pending("r1", "r1-1") is False
    assert arbiter.observe(report(pair(ON_A)), Context(slots=SLOTS), 0.0) is None
    assert arbiter.pending("r1", "r1-1") is True
    assert arbiter.pending("r1", "r1-2") is False          # the robot dropped that request
    assert arbiter.pending("r1", None) is False
    assert arbiter.pending("r2", "r1-1") is False


def test_an_asymmetric_cue_below_the_margin_is_pending():
    """Paint favours the truth (0.4 against 0.1) but by 0.6 < 1.0: no lead, yet a cue."""
    arbiter = Arbiter()
    assert arbiter.observe(report(pair(OFF, paint=(0.4, 0.1))), Context(), 0.0) is None
    assert arbiter.pending("r1", "r1-1") is True


def test_no_cue_is_not_pending():
    arbiter = Arbiter()
    assert arbiter.observe(report(pair(OFF)), Context(slots=SLOTS), 0.0) is None
    assert arbiter.pending("r1", "r1-1") is False


def test_a_cue_that_goes_away_is_no_longer_pending():
    arbiter = Arbiter()
    arbiter.observe(report(pair(ON_A)), Context(slots=SLOTS), 0.0)
    arbiter.observe(report(pair(ON_A)), Context(), 0.5)
    assert arbiter.pending("r1", "r1-1") is False


def test_a_decided_request_stays_pending_until_the_robot_moves_on():
    """Between the post and the robot's `checking` state there is a poll's gap."""
    arbiter = Arbiter()
    assert run(arbiter, report(pair(ON_A)), Context(slots=SLOTS))[1] is not None
    assert arbiter.pending("r1", "r1-1") is True
    assert arbiter.pending("r1", "r1-2") is False
