"""D-395 §7: an injected pose is LOCALIZED only after 3 s of good scan fit."""
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
