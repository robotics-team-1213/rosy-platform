"""D-395 §5: UNKNOWN -> CANDIDATES -> (decision + 3 s check) -> LOCALIZED; SUSPECT on doubt."""
import itertools
import math

import pytest

from control.sensing.loc_candidates import PoseCandidate
from control.sensing.loc_state import LocalizationStateMachine, LocState

TRUE = PoseCandidate(-1.26, .49, -math.pi / 2, .99, "slot:A")
MIRROR = PoseCandidate(1.26, -.49, math.pi / 2, .99, "global")
SLOT = ("slot",)


def machine():
    ids = (f"r1-{n}" for n in itertools.count(1))
    return LocalizationStateMachine(lambda: next(ids))


def feed(m, start, end, fit, dt=.25):
    step, t = None, start
    while t <= end + 1e-9:
        step = m.observe_fit(t, fit)
        t += dt
    return step


def localized():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=0, cues=SLOT)
    feed(m, 1.25, 4.5, .95)
    assert m.state is LocState.LOCALIZED
    return m


def test_power_on_is_unknown_and_blocks_autonomy():
    m = machine()
    assert m.state is LocState.UNKNOWN and not m.autonomy_allowed


def test_candidates_get_a_request_id_and_ask_to_be_reported():
    m = machine()
    step = m.offer([TRUE, MIRROR], 0.)
    assert (step.state, step.actions, m.request_id) == (LocState.CANDIDATES, ("report_candidates",), "r1-1")
    assert m.offer([], 1.).reason == "no_candidates"


def test_a_decision_injects_then_three_good_seconds_localize_and_cancel_the_nav_goal():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide("r1-1", 1., candidate_index=0, cues=SLOT)
    assert step.actions == ("inject_pose",) and step.pose == (TRUE.x, TRUE.y, TRUE.yaw)
    assert feed(m, 1.25, 4.25, .95).state is LocState.CANDIDATES
    step = m.observe_fit(4.5, .95)
    assert step.state is LocState.LOCALIZED and step.actions == ("cancel_nav_goal", "report_status")
    assert m.autonomy_allowed


@pytest.mark.parametrize("request_id, kwargs, reason", [
    ("r1-0", dict(candidate_index=0, cues=SLOT), "stale_request"),
    ("r1-1", dict(candidate_index=0, cues=SLOT, received_s=.5, ttl_s=.4), "expired"),
    ("r1-1", dict(candidate_index=2, cues=SLOT), "bad_index"),
    ("r1-1", dict(cues=SLOT), "ambiguous_decision"),
    ("r1-1", dict(candidate_index=0, pose=(0., 0., 0.), cues=SLOT), "ambiguous_decision"),
    ("r1-1", dict(pose=(math.nan, 0., 0.), source="overhead", cues=SLOT), "bad_pose"),
    ("r1-1", dict(candidate_index=0), "no_asymmetric_cue"),
    ("r1-1", dict(candidate_index=0, cues=("last_good", "overhead")), "no_asymmetric_cue"),
])
def test_bad_decisions_are_rejected_and_change_nothing(request_id, kwargs, reason):
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide(request_id, 1., **kwargs)
    assert (step.actions, step.reason, step.state) == (("reject_decision",), reason, LocState.CANDIDATES)
    assert m.check is None


def test_the_lifetime_runs_from_receipt_not_from_a_fleet_clock():
    """No shared clock: a decision is good for ttl_s after the robot received it."""
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    assert m.decide("r1-1", 105., candidate_index=0, cues=SLOT, received_s=100.).reason == "expired"
    assert m.decide("r1-1", 104.9, candidate_index=0, cues=SLOT, received_s=100.).actions == ("inject_pose",)


def test_a_human_decision_needs_no_asymmetric_cue():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide("r1-1", 1., pose=(-1.2, .5, -1.5), source="human")
    assert step.actions == ("inject_pose",) and m.source == "human"


def test_a_second_decision_while_checking_is_busy():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=0, cues=SLOT)
    assert m.decide("r1-1", 1.1, candidate_index=1, cues=SLOT).reason == "busy"


def test_a_direct_pose_is_checked_like_a_candidate():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    step = m.decide("r1-1", 1., pose=(-1.2, .5, -1.5), source="homing_ref", cues=("square",))
    assert step.pose == (-1.2, .5, -1.5) and m.source == "homing_ref"


def test_a_failed_check_is_suspect_inject_rejected_and_old_ids_die():
    m = machine()
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=1, cues=SLOT)
    step = feed(m, 1.25, 1.5, .4)   # settle ends at 1.5 s; the first low fit after it fails
    assert (step.state, step.reason) == (LocState.SUSPECT, "inject_rejected")
    assert m.decide("r1-1", 2.5, candidate_index=0, cues=SLOT).reason == "stale_request"
    assert m.offer([TRUE], 3.).state is LocState.CANDIDATES and m.request_id == "r1-2"


def test_pickup_while_localized_is_suspect_and_flags_the_report():
    m = localized()
    step = m.picked_up(10.)
    assert (step.state, step.reason, m.pickup) == (LocState.SUSPECT, "pickup", True)
    assert not m.autonomy_allowed


def test_a_sustained_fit_drop_is_suspect_but_a_blip_is_not():
    m = localized()
    assert m.observe_fit(10., .5).state is LocState.LOCALIZED
    assert m.observe_fit(10.25, .95).state is LocState.LOCALIZED
    feed(m, 11., 11.75, .5)
    step = m.observe_fit(12., .5)
    assert (step.state, step.reason) == (LocState.SUSPECT, "fit_drop")


def test_fleet_can_mark_a_localized_robot_suspect_and_candidates_are_ignored_while_localized():
    m = localized()
    assert m.offer([MIRROR], 10.).state is LocState.LOCALIZED
    assert m.mark_suspect("fleet_monitor").reason == "fleet_monitor"
    assert m.mark_suspect("again").reason is None   # only from LOCALIZED


def test_a_decision_without_an_open_request_is_stale():
    """Review M5: in UNKNOWN or SUSPECT there is no request id; None must not match it."""
    m = machine()
    assert m.decide(None, 1., pose=(0., 0., 0.), source="human").reason == "stale_request"


def test_verified_overhead_twin_tiebreak_is_accepted():
    Cand = type(TRUE)
    c0 = Cand(x=-1.0, y=0.5, yaw=3.1, scan_fit=0.92, origin="global")
    c1 = Cand(x=1.0, y=-0.5, yaw=-0.1, scan_fit=0.85, origin="global")
    m = machine()
    m.offer([c0, c1], 0.)
    step = m.decide("r1-1", 1., pose=(-0.97, 0.52, 3.12), source="overhead",
                    cues=("overhead",), evidence={"tiebreak": "twin"})
    assert step.actions == ("inject_pose",) and m.source == "overhead"
    step = feed(m, 1.5, 4.5, .95)
    assert step.state is LocState.LOCALIZED

    m_c1 = machine()
    m_c1.offer([c0, c1], 0.)
    step_c1 = m_c1.decide("r1-1", 1., pose=(1.0, -0.5, -0.1), source="overhead",
                          cues=("overhead",), evidence={"tiebreak": "twin"})
    assert step_c1.actions == ("inject_pose",) and step_c1.pose == (1.0, -0.5, -0.1)


def test_unverified_overhead_twin_tiebreak_is_rejected():
    Cand = type(TRUE)
    c0 = Cand(x=-1.0, y=0.5, yaw=0.0, scan_fit=0.92, origin="global")
    c1 = Cand(x=1.0, y=-0.5, yaw=math.pi, scan_fit=0.90, origin="global")

    def reject(candidates, **kwargs):
        m = machine()
        m.offer(candidates, 0.)
        step = m.decide("r1-1", 1., **kwargs)
        assert (step.actions, step.reason) == (("reject_decision",), "no_asymmetric_cue")

    reject([c0, c1], pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",))
    reject([c0, c1], pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "other"})
    reject([c0, c1], pose=(-1.0, 0.5, 0.0), source="candidate", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, c1], pose=(0.0, 0.0, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, c1], pose=(1.0, None, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, c1], pose=123, source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, Cand(x=-0.5, y=0.5, yaw=math.pi, scan_fit=0.90, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([Cand(x=-1.0, y=0.5, yaw=0.0, scan_fit=0.84, origin="global"), c1],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, Cand(x=1.0, y=-0.5, yaw=math.pi, scan_fit=0.84, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, Cand(x=1.0, y=-0.5, yaw=math.pi, scan_fit=math.nan, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([Cand(x=-1.0, y=0.5, yaw=0.0, scan_fit=0.98, origin="global"),
            Cand(x=1.0, y=-0.5, yaw=math.pi, scan_fit=0.86, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, Cand(x=1.0, y=-0.5, yaw=0.7, scan_fit=0.90, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})
    reject([c0, c1, Cand(x=0.0, y=2.0, yaw=1.0, scan_fit=0.90, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",), evidence={"tiebreak": "twin"})


def test_unique_overhead_corroboration_accepts_strong_single_candidate_and_rejects_mismatches():
    Cand = type(TRUE)
    c0 = Cand(x=-1.0, y=0.5, yaw=0.0, scan_fit=0.91, origin="global")

    m_ok = machine()
    m_ok.offer([c0], 0.)
    step = m_ok.decide("r1-1", 1., pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",),
                       evidence={"tiebreak": "unique", "camera_to_chosen_m": 0.22})
    assert step.actions == ("inject_pose",) and step.pose == (-1.0, 0.5, 0.0)

    def reject(candidates, **kwargs):
        m = machine()
        m.offer(candidates, 0.)
        bad = m.decide("r1-1", 1., **kwargs)
        assert (bad.actions, bad.reason) == (("reject_decision",), "no_asymmetric_cue")

    reject([c0], pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",),
           evidence={"tiebreak": "unique", "camera_to_chosen_m": 0.36})
    reject([c0], pose=(-1.0, 0.5, math.pi), source="overhead", cues=("overhead",),
           evidence={"tiebreak": "unique", "camera_to_chosen_m": 0.10})
    reject([c0, Cand(x=1.0, y=-0.5, yaw=math.pi, scan_fit=0.90, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",),
           evidence={"tiebreak": "unique", "camera_to_chosen_m": 0.10})
    reject([Cand(x=-1.0, y=0.5, yaw=0.0, scan_fit=0.84, origin="global")],
           pose=(-1.0, 0.5, 0.0), source="overhead", cues=("overhead",),
           evidence={"tiebreak": "unique", "camera_to_chosen_m": 0.10})


def test_auto_lock_unique_injects_verifies_and_enforces_guards():
    Cand = type(TRUE)
    unique = Cand(x=-1.0, y=0.5, yaw=0.1, scan_fit=0.96, origin="global", unique_margin=0.25)

    m = machine()
    m.offer([unique], 0.0)
    step = m.auto_lock_unique(1.0)
    assert step.actions == ("inject_pose",) and m.source == "unique_map"
    assert feed(m, 1.5, 4.5, 0.95).state is LocState.LOCALIZED

    m_fail = machine()
    m_fail.offer([unique], 0.0)
    assert m_fail.auto_lock_unique(1.0).actions == ("inject_pose",)
    bad = feed(m_fail, 1.25, 1.5, 0.40)
    assert (bad.state, bad.reason) == (LocState.SUSPECT, "inject_rejected")

    for cands in (
        [Cand(-1.0, 0.5, 0.1, 0.96, "global", unique_margin=None)],
        [Cand(-1.0, 0.5, 0.1, 0.96, "global", unique_margin=0.14)],
        [Cand(-1.0, 0.5, 0.1, 0.89, "global", unique_margin=0.30)],
        [unique, MIRROR],
    ):
        g = machine()
        g.offer(cands, 0.0)
        assert g.auto_lock_unique(1.0).actions == () and g.check is None


def test_localized_tolerates_transient_fit_drop_until_drop_fit_and_hold_window():
    ids = (f"r1-{n}" for n in itertools.count(1))
    m = LocalizationStateMachine(lambda: next(ids), fit_drop_s=2.5, drop_fit=0.70)
    m.offer([TRUE, MIRROR], 0.)
    m.decide("r1-1", 1., candidate_index=0, cues=SLOT)
    feed(m, 1.25, 4.5, .95)
    assert m.state is LocState.LOCALIZED
    # 0.72 is above drop_fit=0.70 even though below min_fit=0.75: stays LOCALIZED.
    assert feed(m, 5.0, 8.0, .72).state is LocState.LOCALIZED
    assert m._low_since is None
    # Brief dip below 0.70 recovers when fit returns above drop_fit.
    assert m.observe_fit(8.5, .65).state is LocState.LOCALIZED and m._low_since == 8.5
    assert m.observe_fit(10.0, .71).state is LocState.LOCALIZED and m._low_since is None
    # Sustained dip >= 2.5 s transitions to SUSPECT fit_drop.
    assert m.observe_fit(11.0, .65).state is LocState.LOCALIZED
    assert m.observe_fit(13.4, .65).state is LocState.LOCALIZED
    step = m.observe_fit(13.5, .65)
    assert (step.state, step.reason) == (LocState.SUSPECT, "fit_drop")
