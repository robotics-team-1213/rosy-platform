"""Reconnect delays preserve caps while spreading simultaneous failures."""

import pytest

from core_common.link_retry import retry_delay


def test_jitter_is_bounded_and_respects_total_deadline():
    assert retry_delay(30, maximum_s=30, random_value=lambda: 0) == 15
    assert retry_delay(30, maximum_s=30, random_value=lambda: 1) == 30
    assert retry_delay(1, maximum_s=30, random_value=lambda: .5) == .75
    assert retry_delay(30, maximum_s=30, remaining_s=2, random_value=lambda: 1) == 2


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_retry_profile_fails_closed(value):
    with pytest.raises(ValueError):
        retry_delay(value, maximum_s=30)


def test_reconnect_backoff_doubles_to_its_cap_and_resets_after_a_stable_session():
    from core_common.link_retry import ReconnectBackoff, start_offset

    class Link(ReconnectBackoff):
        reconnect_base_s, reconnect_max_s, reconnect_stable_s = 5.0, 20.0, 60.0

    link = Link()
    delays = [link.reconnect_delay(now=0.0) for _ in range(4)]   # back-to-back failures
    for delay, base in zip(delays, (5, 10, 20, 20)):
        assert base / 2 <= delay <= base
    assert 2.5 <= link.reconnect_delay(now=1000.0) <= 5.0           # the session in between was stable
    assert start_offset(0.5, random_value=lambda: 0.5) == 0.25
