"""D-395 §7: an injected pose is LOCALIZED only after 3 s of good scan fit."""
import math

import pytest

from control.sensing.loc_verify import FAILED, PASSED, PENDING, InjectionCheck


def run(check, samples):
    result = PENDING
    for now, fit in samples:
        result = check.observe(now, fit)
    return result


def test_good_fit_for_settle_plus_hold_passes():
    check = InjectionCheck(10.)
    assert run(check, [(10. + .25 * k, .95) for k in range(1, 14)]) == PENDING   # up to 13.25 s
    assert check.observe(13.5, .95) == PASSED


def test_low_fit_during_settle_is_forgiven():
    check = InjectionCheck(0.)
    assert run(check, [(.25, .2)] + [(.25 * k, .95) for k in range(2, 15)]) == PASSED


def test_one_low_fit_after_settle_fails_with_a_reason():
    check = InjectionCheck(0.)
    assert run(check, [(.25 * k, .95) for k in range(1, 6)] + [(1.5, .5)]) == FAILED
    assert check.reason == 'fit_low'
    assert check.observe(5., .99) == FAILED      # a result is final


def test_a_scan_gap_fails_as_stale():
    check = InjectionCheck(0.)
    assert check.observe(.25, .95) == PENDING
    assert check.observe(.8, None) == FAILED
    assert check.reason == 'stale_scan'


def test_nan_fit_counts_as_no_scan():
    check = InjectionCheck(0.)
    assert check.observe(.2, float('nan')) == PENDING
    assert check.observe(.6, float('nan')) == FAILED


def test_a_fit_after_a_long_silence_is_a_gap_not_a_hold():
    """Review I3: one scan after 3.6 s of nothing must not pass the 3 s hold."""
    check = InjectionCheck(0.)
    assert check.observe(3.6, .9) == FAILED
    assert check.reason == 'stale_scan'


def test_trace_retains_exact_fit_failure_after_the_check_is_consumed():
    from types import SimpleNamespace

    from control.loc_verify_trace import VerificationTrace
    from control.sensing.loc_candidates import Mount

    check = InjectionCheck(100.)
    injection = SimpleNamespace(pose=(.60, -.43, 1.54), request_id="native-1", source="human")
    trace = VerificationTrace(check, injection)
    assert check.observe(100.3, .96) == PENDING
    trace.scan(100.48)
    breakdown = SimpleNamespace(raw_score=.88, miss_wall_pierced=11,
                                total=156, rejected_reason="wall-piercing")
    trace.fit(100.48, 100.59, (.61, -.44, -1.58), "laser", 0., breakdown)
    assert check.observe(100.59, 0.) == FAILED

    record = trace.report(100.59, mount=Mount(0., 0., math.pi))

    assert record["reason"] == "fit_low" and record["request_id"] == "native-1"
    assert record["position_error_m"] == pytest.approx(.01414, abs=1e-5)
    assert record["latest_scan_age_s"] == pytest.approx(.11)
    assert record["fit_gap_s"] == pytest.approx(.29)
    assert record["last_fit"]["fit"] == 0.
    assert record["last_fit"]["agreement_rejection"] == "wall-piercing"
    assert record["last_fit"]["wall_pierced"] == 11


def test_trace_separates_transform_delay_from_last_usable_fit():
    from types import SimpleNamespace

    from control.loc_verify_trace import VerificationTrace

    check = InjectionCheck(100.)
    trace = VerificationTrace(check, SimpleNamespace(pose=(0., 0., 0.), request_id="native-2", source="human"))
    trace.scan(100.25)
    trace.scan_error = "odom transform unavailable"
    assert check.observe(100.55) == FAILED

    record = trace.report(100.55)
    assert record["reason"] == "stale_scan" and record["last_fit"] is None
    assert record["latest_scan_error"] == "odom transform unavailable"
    assert record["fit_gap_s"] == pytest.approx(.55)
