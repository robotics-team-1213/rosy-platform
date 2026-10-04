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
