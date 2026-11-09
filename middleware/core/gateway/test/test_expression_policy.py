"""D-922: observed encounters, bounded attention, and coordinated output."""
from math import isfinite

import pytest
from core.bridge.expression_policy import ExpressionPolicy


def policy():
    return ExpressionPolicy()


def person(track=1, x=.7, confidence=.9):
    return dict(label="person", x=x, y=.1, w=.1, h=.5,
                confidence=confidence, track_id=track)


def observe(p, at, seq, people=(), *, known=True, age=0, revision="test-model"):
    packet = dict(model_revision=revision, observed_at=1000 + at - age, seq=seq,
                  input_width=320, input_height=240, input_fps=10,
                  detections=list(people))
    p.observe(packet, source_now=1000 + at, now=at, known_revision=known)


def seen(p, start=0., people=None, seq=0):
    people = [person()] if people is None else people
    for i in range(4):
        at = start + i * .2
        observe(p, at, seq + i, people)
        result = p.update("IDLE", "IDLE", at)
    return result


def test_greeting_qualifies_over_time_and_turns_pupils_toward_a_person():
    p = policy()
    observe(p, 0, 0, [person()])
    assert p.update("IDLE", "IDLE", 0).face == "basic"
    out = seen(p, start=.2, seq=1)
    assert out.face == "happy" and 0 < out.gaze_x <= 6
    assert out.resting is False
    assert max(out.rgb) <= 36


def test_continuous_presence_never_replays_a_greeting():
    p = policy()
    seen(p)
    for i in range(4, 360):
        at = i * .2
        observe(p, at, i, [person()])
        result = p.update("IDLE", "IDLE", at)
        if at > 3:
            assert result.face != "happy"


def test_selection_uses_center_and_stable_target_instead_of_box_area():
    p = policy()
    centered = person(2, .48)
    side = person(1, .8)
    assert seen(p, people=[side, centered]).gaze_x > 0
    observe(p, .8, 4, [person(1, .45), person(2, .7)])
    result = p.update("IDLE", "IDLE", .8)
    assert result.gaze_x > 1  # still following track 2 rather than the newly centered track 1


def test_missing_ids_greet_the_group_without_fabricating_individuals():
    p = policy()
    out = seen(p, people=[person(None, .1), person(None, .8)])
    assert abs(out.gaze_x) < 1
    for i in range(4, 40):
        observe(p, i * .2, i, [person(None, .6)])
        out = p.update("IDLE", "IDLE", i * .2)
    assert out.face != "happy"



def test_a_group_arriving_together_is_cheered_and_one_person_is_greeted():
    together = seen(policy(), people=[person(1, .4), person(2, .6)])
    assert together.face == "cheer" and together.reacting
    assert seen(policy(), people=[person(None, .3), person(None, .7)]).face == "cheer"
    assert seen(policy(), people=[person(None, .5)]).face == "happy"
    assert seen(policy(), people=[person(1, .5), person(1, .52)]).face == "happy"  # one person, two boxes
    p = policy()
    seen(p, people=[person(1, .4), person(2, .6)])
    faces = []
    for i in range(4, 40):
        observe(p, i * .2, i, [person(1, .4), person(2, .6)])
        faces.append(p.update("IDLE", "IDLE", i * .2).face)
    later = faces[8:]  # after the cheer: the one left to greet gets a plain greeting
    assert "happy" in later and "cheer" not in later


@pytest.mark.parametrize("kind", ["stale", "unknown", "invalid", "replay"])
def test_untrusted_or_old_evidence_cannot_greet_or_hold_a_direction(kind):
    p = policy()
    seen(p)
    if kind == "invalid":
        p.observe({"broken": True}, source_now=1001, now=1, known_revision=True)
    else:
        observe(p, 1, 0 if kind == "replay" else 10, [person()],
                known=kind != "unknown", age=1 if kind == "stale" else 0)
    out = p.update("IDLE", "IDLE", 1)
    assert out.face != "happy" and out.gaze_x == 0
    assert not out.resting


def test_lost_stream_recovery_does_not_replay_present_people():
    p = policy()
    seen(p)
    assert p.update("IDLE", "IDLE", 4).gaze_x == 0
    out = seen(p, start=5, seq=30)
    assert out.face != "happy"


def test_safe_idle_rests_after_300_seconds_and_new_person_wakes_it():
    p = policy()
    observe(p, 0, 0)
    p.update("IDLE", "IDLE", 0)
    observe(p, 299.9, 1)
    assert not p.update("IDLE", "IDLE", 299.9).resting
    observe(p, 300, 2)
    out = p.update("IDLE", "IDLE", 300)
    assert out.face == "bored" and out.resting and max(out.rgb) <= 8
    out = seen(p, start=301, seq=3)
    assert not out.resting


@pytest.mark.parametrize("mode,nav", [("EMERGENCY", "IDLE"),
    ("NAVIGATION", "BLOCKED"), ("NAVIGATION", "FAILED")])
def test_unsafe_or_blocked_state_cancels_a_greeting_and_never_sleeps(mode, nav):
    p = policy()
    seen(p)
    out = p.update(mode, nav, .8)
    assert out.face != "happy" and out.gaze_x == 0 and not out.resting
    assert out.rgb == (0, 0, 0) or mode == "NAVIGATION" and nav == "BLOCKED"


def test_card_preemption_discards_the_reaction_instead_of_queuing_it():
    p = policy()
    seen(p)
    out = p.update("IDLE", "IDLE", .8, suspended=True)
    assert out.gaze_x == 0 and not out.resting
    out = seen(p, start=1, seq=5)
    assert out.face != "happy"


def test_motion_not_the_navigation_mode_selects_the_short_greeting():
    p = policy()
    for i in range(4):
        observe(p, i * .2, i, [person()])
        p.update("MANUAL", "IDLE", i * .2, moving=True)
    observe(p, 1.3, 7, [person()])
    assert p.update("MANUAL", "IDLE", 1.3, moving=True).face != "happy"


def test_a_return_before_cooldown_is_discarded_even_if_the_person_stays():
    p = policy()
    seen(p)
    for i in range(4, 65):
        observe(p, i * .2, i)
        p.update("IDLE", "IDLE", i * .2)
    for i in range(65, 350):
        observe(p, i * .2, i, [person()])
        out = p.update("IDLE", "IDLE", i * .2)
        assert out.face != "happy"


def test_a_new_return_after_both_limits_can_greet():
    p = policy()
    seen(p)
    for i in range(4, 310):
        observe(p, i * .2, i)
        p.update("IDLE", "IDLE", i * .2)
    assert seen(p, start=62, seq=310).face == "happy"


def test_led_colors_are_bounded_and_modes_have_distinct_intents():
    p = policy()
    colors = set()
    for mode in ("IDLE", "MANUAL", "NAVIGATION", "DOCKING"):
        out = p.update(mode, "NAVIGATING", 10, moving=mode != "IDLE")
        assert all(type(c) is int and 0 <= c <= 24 and isfinite(c) for c in out.rgb)
        colors.add(out.rgb)
    assert len(colors) == 4


def test_mode_transition_discards_a_person_who_was_still_qualifying():
    p = policy()
    for i in range(3):
        observe(p, i * .2, i, [person()])
        p.update("IDLE", "IDLE", i * .2)
    observe(p, .6, 3, [person()])
    out = p.update("MANUAL", "IDLE", .6, moving=True)
    assert out.face != "happy" and out.gaze_x == 0
    observe(p, .8, 4, [person()])
    assert p.update("MANUAL", "IDLE", .8, moving=True).face != "happy"


def test_sequence_loss_cancels_a_greeting_even_while_the_packet_is_fresh():
    p = policy()
    seen(p)
    observe(p, .8, 5, [person()])  # seq 4 was lost
    out = p.update("IDLE", "IDLE", .8)
    assert out.face != "happy" and out.gaze_x == 0
    observe(p, 1, 6, [person()])
    assert p.update("IDLE", "IDLE", 1).face != "happy"


def test_only_an_actual_arrival_transition_gets_a_short_satisfied_face():
    p = policy()
    p.update("NAVIGATION", "NAVIGATING", 0, moving=True)
    observe(p, 1, 1)
    out = p.update("IDLE", "ARRIVED", 1)
    assert out.face == "happy" and out.reacting and out.handover() is not None
    observe(p, 3, 2)
    assert p.update("IDLE", "ARRIVED", 3).face == "basic"
    fresh = policy()
    assert fresh.update("IDLE", "ARRIVED", 0).face != "happy"


def test_neutral_face_uses_the_legacy_cadence_but_centered_greeting_keeps_a_lease():
    p = policy()
    assert p.update("IDLE", "IDLE", 0).handover() is None
    out = seen(p, start=.2, seq=1, people=[person(x=.45)])
    assert out.face == "happy" and out.gaze_x == 0 and out.handover() is not None


def test_a_new_object_does_not_postpone_the_person_in_the_same_frame():
    p = policy()
    cup = dict(label="cup", x=.1, y=.4, w=.1, h=.1, confidence=.9)
    assert seen(p, people=[person(), cup]).face == "happy"
