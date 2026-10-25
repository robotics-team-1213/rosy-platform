"""UTC capture-time validity under the required two-clock 100 ms skew bound."""

import pytest

from core_common.protocol.swarm_freshness import (
    CLOCK_SKEW_BUDGET_S,
    remaining_reference_s,
)


@pytest.mark.parametrize("sampled_at, expected", [
    (100.0, 0.9),
    (99.5, 0.4),
    (100.05, 0.9),
    (100.1, 0.9),
    (100.1001, None),
    (99.0, None),
])
def test_reference_lifetime_conservatively_accounts_for_clock_skew(sampled_at, expected):
    remaining = remaining_reference_s(sampled_at, now=100.0, timeout_s=1.0)
    if expected is None:
        assert remaining is None
    else:
        assert remaining == pytest.approx(expected)


@pytest.mark.parametrize("timeout_s", [0.1, 0.05])
def test_reference_with_no_positive_budget_after_clock_skew_is_expired(timeout_s):
    assert remaining_reference_s(100.0, now=100.0, timeout_s=timeout_s) is None


@pytest.mark.parametrize("sampled_at", [
    None, True, False, "100", float("nan"), float("inf"), -float("inf"), 0, -1, 10**1000,
])
def test_invalid_capture_time_has_no_reference_lifetime(sampled_at):
    assert remaining_reference_s(sampled_at, now=100.0, timeout_s=1.0) is None


@pytest.mark.parametrize("field", ["now", "timeout_s"])
@pytest.mark.parametrize("invalid", [None, True, "100", float("nan"), float("inf"), 0, -1, 10**1000])
def test_invalid_clock_or_timeout_has_no_reference_lifetime(field, invalid):
    arguments = {"now": 100.0, "timeout_s": 1.0, field: invalid}
    assert remaining_reference_s(100.0, **arguments) is None


@pytest.mark.parametrize("source_offset", [-0.05, 0.05])
@pytest.mark.parametrize("receiver_offset", [-0.05, 0.05])
def test_two_receivers_within_required_clock_bounds_never_extend_actual_lifetime(
    source_offset, receiver_offset,
):
    assert CLOCK_SKEW_BUDGET_S == 0.1
    captured_at = 100.0
    received_at = 100.3
    timeout_s = 1.0

    remaining = remaining_reference_s(captured_at + source_offset,
                                      now=received_at + receiver_offset,
                                      timeout_s=timeout_s)

    assert remaining is not None
    assert 0 < remaining <= captured_at + timeout_s - received_at + 1e-12
