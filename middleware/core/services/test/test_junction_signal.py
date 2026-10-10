"""D-620: Fleet reply wins before entry; only silence permits the three-second fallback."""
import pytest

from test_line_junction import Rig


def waiting():
    rig = Rig(junction_signal_enabled=True)
    rig.step(junction=True)
    return rig, rig.m.junction_signal_request()


def answer(rig, request, lamp, may_enter=False):
    return rig.m.junction_signal_answer(dict(request_id=request, lamp=lamp,
                                           may_enter=may_enter, reason="test"))


def test_silence_waits_three_seconds_then_arms_one_right_turn():
    rig, request = waiting()
    for _ in range(59):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        assert status.junction.state == "waiting"
        assert rig.m.junction_signal_request() == request
    _, status = rig.step(junction=True)
    assert status.junction.pending_action == "right"
    assert status.junction.turn_deg == -90
    assert status.junction.signal_state in ("fallback", "entered")
    seq = status.junction.seq
    for _ in range(3):
        rig.step(junction=True)
        assert rig.m.status().junction.seq == seq


@pytest.mark.parametrize("lamp,may_enter", [("red", False), ("unknown", False), ("green", False)])
def test_a_reply_never_becomes_silence_even_after_three_seconds(lamp, may_enter):
    rig, request = waiting()
    assert answer(rig, request, lamp, may_enter)
    for _ in range(100):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        assert status.junction.state == "waiting"
    assert status.junction.signal_state in (lamp, "unknown")


def test_red_then_green_enters_through_existing_bounded_turn_gate():
    rig, request = waiting()
    answer(rig, request, "red")
    rig.step(junction=True)
    answer(rig, request, "green", True)
    _, status = rig.step(junction=True)
    assert status.junction.pending_action == "right"
    assert status.junction.turn_deg == -90
    assert status.junction.signal_state in ("green", "entered")


def test_wrong_episode_and_malformed_answers_cannot_open_the_gate():
    rig, request = waiting()
    assert not answer(rig, "0" * 32, "green", True)
    assert not answer(rig, request, "green", "true")
    assert rig.m.status().junction.state == "waiting"


def test_late_red_before_rotation_cancels_fallback():
    rig, request = waiting()
    for _ in range(59):
        rig.step(junction=True)
    rig.now += .4
    rig.step(junction=True, pose=False)
    assert rig.m.status().junction.signal_state == "fallback"
    answer(rig, request, "red")
    decision, status = rig.step(junction=True)
    assert decision.linear == decision.angular == 0
    assert status.junction.state == "waiting"
    assert status.junction.signal_state == "red"


def test_fallback_still_needs_motion_basis():
    rig = Rig(proof=False, junction_signal_enabled=True)
    for _ in range(63):
        decision, status = rig.step(junction=True)
    assert decision.linear == decision.angular == 0
    assert status.junction.state == "aborted"
    assert status.junction.reason == "motion_unconfirmed"


def test_default_off_and_mode_off_do_not_request_or_apply_answers():
    rig = Rig()
    rig.step(junction=True)
    assert rig.m.junction_signal_request() is None
    rig, request = waiting()
    from core_features.line_follow.model import LineFollowMode
    rig.m.set_mode(LineFollowMode.OFF)
    assert rig.m.junction_signal_request() is None
    assert not answer(rig, request, "green", True)
