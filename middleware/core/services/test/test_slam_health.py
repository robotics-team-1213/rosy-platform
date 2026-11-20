"""SLAM health verdict: lost needs N samples in a row, recovery needs M, and no flapping inside the dwell."""
import pytest

from core_features.localization.slam_health import (
    AGREEMENT_MIN, DEGRADED, GAP_M, JUMP_M, LOST, LOST_CONSECUTIVE, MIN_DWELL_S, OK, RECOVER_CONSECUTIVE, Sample,
    SlamHealth, classify)

GOOD = dict(map_verdict="ok", agreement=0.95, jump_m=0.0, gap_m=0.05)


def stream(n, start=0.0, step=1.0, **fields):
    return [Sample(t=start + i * step, **fields) for i in range(n)]


def final(samples):
    return classify(samples)[-1]


def test_good_samples_stay_ok():
    assert final(stream(30, **GOOD)).state == OK


@pytest.mark.parametrize("field, value, reason", [
    ("jump_m", JUMP_M + 0.01, "map_odom_jump"),
    ("agreement", AGREEMENT_MIN - 0.01, "scan_wall_agreement_low"),
    ("gap_m", GAP_M + 0.01, "slam_camera_gap")])
def test_each_lost_condition_needs_n_samples_in_a_row(field, value, reason):
    bad = {**GOOD, field: value}
    assert [h.state for h in classify(stream(LOST_CONSECUTIVE, **bad))] == [OK] * (LOST_CONSECUTIVE - 1) + [LOST]
    assert final(stream(LOST_CONSECUTIVE, **bad)).reasons == (reason,)
    broken = stream(LOST_CONSECUTIVE - 1, **bad) + stream(1, start=10, **GOOD) + stream(LOST_CONSECUTIVE - 1, start=20, **bad)
    assert final(broken).state == OK


def test_a_jump_while_commanded_is_not_lost_but_the_same_jump_standing_still_is():
    assert final(stream(10, **{**GOOD, "jump_m": 0.5, "moving": True})).state == OK
    assert final(stream(10, **{**GOOD, "jump_m": 0.5})).state == LOST


def test_a_failed_map_is_degraded_at_once_and_alone_never_lost():
    h = classify(stream(30, **{**GOOD, "map_verdict": "fail"}))
    assert h[0].state == DEGRADED and h[-1].state == DEGRADED and h[-1].reasons == ("map_verdict_fail",)
    assert final(stream(5, **{**GOOD, "map_verdict": "warn"})).state == OK


def test_samples_without_a_field_leave_its_run_alone():
    bad = Sample(t=0, agreement=0.2)
    gap_only = Sample(t=1, gap_m=0.0)
    tracker = SlamHealth()
    states = [tracker.update(s).state for s in (bad, gap_only, bad, gap_only, bad)]
    assert states[-1] == LOST
    assert SlamHealth().update(Sample(t=0)) .state == OK  # nothing measured: nothing claimed


def test_recovery_needs_m_good_samples_in_a_row_and_the_dwell():
    tracker = SlamHealth()
    for s in stream(LOST_CONSECUTIVE, **{**GOOD, "agreement": 0.1}):
        tracker.update(s)
    assert tracker.state == LOST
    t = 10.0
    for i in range(RECOVER_CONSECUTIVE - 1):
        assert tracker.update(Sample(t=t + 100 + i, **GOOD)).state == LOST
    assert tracker.update(Sample(t=t + 200, **{**GOOD, "agreement": 0.1})).state == LOST  # one bad sample restarts the count
    for i in range(RECOVER_CONSECUTIVE - 1):
        assert tracker.update(Sample(t=t + 300 + i, **GOOD)).state == LOST
    assert tracker.update(Sample(t=t + 400, **GOOD)).state == OK


def test_it_does_not_flap_inside_the_dwell_but_still_goes_to_lost():
    tracker = SlamHealth()
    assert tracker.update(Sample(t=0, **{**GOOD, "map_verdict": "fail"})).state == DEGRADED
    for i in range(RECOVER_CONSECUTIVE + 5):  # recovered by count at t < dwell: still held
        assert tracker.update(Sample(t=1 + i, **GOOD)).state == DEGRADED
    assert tracker.update(Sample(t=MIN_DWELL_S, **GOOD)).state == OK
    assert tracker.update(Sample(t=MIN_DWELL_S + 1, **{**GOOD, "map_verdict": "fail"})).state == OK  # inside the dwell
    assert tracker.update(Sample(t=MIN_DWELL_S + 2, **{**GOOD, "gap_m": 1.0})).state == OK
    states = [tracker.update(Sample(t=MIN_DWELL_S + 3 + i, **{**GOOD, "gap_m": 1.0})).state for i in range(2)]
    assert states[-1] == LOST  # worse is not held back by the dwell
