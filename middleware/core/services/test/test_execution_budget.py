"""Private D-776 budget arithmetic; synthetic profiles confer no device authority."""

from dataclasses import replace
import math

import pytest


def types():
    from core_features.command._execution_budget import Budget, Limits, Pose
    return Budget, Limits, Pose


def setup_budget(**overrides):
    Budget, Limits, Pose = types()
    limits = Limits(
        revision="SYNTHETIC", speed_mps=1.0, angular_speed_rps=2.0,
        deceleration_mps2=2.0, angular_deceleration_rps2=4.0,
        latency_s=0.1, watchdog_s=0.2, footprint_m=0.1,
        position_error_m=0.01, max_pose_age_s=0.5, max_pose_gap_s=0.4,
        whole_load_w=10.0,
    )
    pose = Pose(stamp_ns=1_000_000_000, source_now_ns=1_000_000_000,
                frame="odom", epoch="boot/odom-1", x=0.0, y=0.0)
    kwargs = dict(limits=limits, initial=pose, before_mono=10.0, after_mono=10.0,
                  now_utc=100.0, captured_utc=99.9, admit_until_utc=100.1,
                  duration_s=10.0, path_m=10.0, rotation_rad=20.0, radius_m=5.0)
    kwargs.update(overrides)
    return Budget(**kwargs), pose


def advance(budget, pose, elapsed, **changes):
    current = replace(pose, stamp_ns=pose.stamp_ns + round(elapsed * 1e9),
                      source_now_ns=pose.source_now_ns + round(elapsed * 1e9), **changes)
    assert budget.observe(current, before_mono=10.0 + elapsed, after_mono=10.0 + elapsed)
    return current


def test_waiting_and_closed_loop_endpoints_spend_full_time_bound():
    budget, pose = setup_budget()
    first = budget.remaining(now_mono=10.0)
    advance(budget, pose, 0.3)  # Same endpoint can conceal a loop or an out-and-back.
    later = budget.remaining(now_mono=10.3)
    assert later.path_m < first.path_m - 0.299
    assert later.rotation_rad < first.rotation_rad - 0.599
    assert later.energy_upper_j > first.energy_upper_j + 2.99


def test_stop_tail_and_source_age_are_reserved_before_motion():
    budget, _ = setup_budget()
    remaining = budget.remaining(now_mono=10.0)
    # Linear stop: 1*(.1+.2)+1**2/(2*2)=.55m; angular stop=1.1rad.
    assert remaining.path_m == pytest.approx(9.45)
    assert remaining.rotation_rad == pytest.approx(18.9)
    assert remaining.duration_s == pytest.approx(9.2)
    assert remaining.radius_m == pytest.approx(4.34)
    assert remaining.energy_upper_j == pytest.approx(8.0)


@pytest.mark.parametrize("field,value", [("duration_s", .8), ("path_m", .55),
                                         ("rotation_rad", 1.1), ("radius_m", .66)])
def test_reserve_equality_denies_and_remains_consumed(field, value):
    budget, pose = setup_budget(**{field: value})
    assert budget.remaining(now_mono=10.0) is None
    assert budget.reason is not None
    assert not budget.observe(pose, before_mono=10.0, after_mono=10.0)
    assert budget.remaining(now_mono=10.0) is None


def test_duplicate_original_pose_does_not_refresh_capture_lease():
    budget, pose = setup_budget()
    assert budget.observe(replace(pose, source_now_ns=1_300_000_000),
                          before_mono=10.3, after_mono=10.3)
    assert budget.remaining(now_mono=10.5) is None


@pytest.mark.parametrize("changes", [dict(frame="map"), dict(epoch="new-epoch"),
                                      dict(stamp_ns=999_999_999), dict(x=math.nan),
                                      dict(x=1.0), dict(source_now_ns=999_999_999)])
def test_contradictory_pose_consumes_budget(changes):
    budget, pose = setup_budget()
    assert not budget.observe(replace(pose, **changes), before_mono=10.1, after_mono=10.1)
    assert budget.remaining(now_mono=10.1) is None


def test_gap_cannot_be_hidden_by_fresh_endpoint():
    budget, pose = setup_budget()
    current = replace(pose, stamp_ns=1_500_000_000, source_now_ns=1_500_000_000)
    assert not budget.observe(current, before_mono=10.5, after_mono=10.5)


@pytest.mark.parametrize("clock", [9.9, math.nan, math.inf, True])
def test_bad_final_clock_consumes_budget(clock):
    budget, _ = setup_budget()
    assert budget.remaining(now_mono=clock) is None
    assert budget.remaining(now_mono=10.0) is None


@pytest.mark.parametrize("kwargs", [dict(now_utc=100.1), dict(captured_utc=100.01),
                                    dict(after_mono=9.9), dict(path_m=math.inf),
                                    dict(path_m=10**1000), dict(after_mono=10.1)])
def test_invalid_or_late_initial_admission_rejected(kwargs):
    with pytest.raises(ValueError):
        setup_budget(**kwargs)


def test_read_delay_counts_and_original_deadline_does_not_reset():
    budget, pose = setup_budget(after_mono=10.2, admit_until_utc=101.0)
    first = budget.remaining(now_mono=10.2)
    advance(budget, pose, .3)
    assert budget.remaining(now_mono=10.3).duration_s < first.duration_s
    # There is deliberately no renew/reset/child-change operation on the budget.
    budget.stop("manual-handover")
    assert budget.remaining(now_mono=10.3) is None
    budget.stop("later-reason")
    assert budget.reason == "manual-handover"


@pytest.mark.parametrize("speed", [1e308, 10**308])
def test_finite_inputs_whose_arithmetic_overflows_deny(speed):
    _, Limits, _ = types()
    limits = Limits(revision="SYNTHETIC", speed_mps=speed, angular_speed_rps=2.0,
                    deceleration_mps2=2.0, angular_deceleration_rps2=4.0,
                    latency_s=.1, watchdog_s=.2, footprint_m=.1,
                    position_error_m=.01, max_pose_age_s=.5, max_pose_gap_s=.4,
                    whole_load_w=10.0)
    budget, _ = setup_budget(limits=limits)
    assert budget.remaining(now_mono=10.0) is None


@pytest.mark.parametrize("field,value", [("speed_mps", True), ("whole_load_w", math.nan),
                                        ("watchdog_s", 0), ("deceleration_mps2", -1),
                                        ("speed_mps", 10**1000), ("revision", "")])
def test_invalid_profile_rejected(field, value):
    budget, _ = setup_budget()
    with pytest.raises(ValueError):
        setup_budget(limits=replace(budget._limits, **{field: value}))


def test_pose_source_age_cannot_be_hidden_by_receipt_time():
    _, _, Pose = types()
    stale = Pose(stamp_ns=1_000_000_000, source_now_ns=1_500_000_000,
                 frame="odom", epoch="boot/odom-1", x=0., y=0.)
    with pytest.raises(ValueError):
        setup_budget(initial=stale)


def test_source_gap_equality_and_clock_regression_are_terminal():
    budget, pose = setup_budget()
    current = replace(pose, stamp_ns=1_400_000_000, source_now_ns=1_400_000_000)
    assert not budget.observe(current, before_mono=10.4, after_mono=10.4)
    assert budget.remaining(now_mono=10.4) is None
    budget, pose = setup_budget()
    assert not budget.observe(pose, before_mono=10.1, after_mono=10.05)
    assert budget.remaining(now_mono=10.1) is None


def test_new_capture_with_impossible_step_consumes_budget():
    budget, pose = setup_budget()
    current = replace(pose, stamp_ns=1_100_000_000, source_now_ns=1_100_000_000, x=2.)
    assert not budget.observe(current, before_mono=10.1, after_mono=10.1)
    assert budget.reason == "impossible-pose-step"
    assert budget.remaining(now_mono=10.1) is None


def test_consistent_step_with_measurement_error_is_accepted():
    budget, pose = setup_budget()
    advance(budget, pose, .1, x=.11)
    assert budget.remaining(now_mono=10.1) is not None


def test_large_integer_coordinate_difference_does_not_raise():
    _, _, Pose = types()
    initial = Pose(stamp_ns=1_000_000_000, source_now_ns=1_000_000_000,
                   frame="odom", epoch="boot/odom-1", x=10**308, y=0)
    budget, _ = setup_budget(initial=initial)
    current = replace(initial, stamp_ns=1_100_000_000, source_now_ns=1_100_000_000, x=-(10**308))
    assert not budget.observe(current, before_mono=10.1, after_mono=10.1)
    assert budget.remaining(now_mono=10.1) is None
