"""The shared wait graph keeps Fleet's deterministic cycle order."""

import pytest


@pytest.mark.parametrize('waits, expected', [({}, None), ({'a': ['b']}, None),
    ({'a': ['a']}, ('a',)), ({'b': ['a'], 'a': ['b']}, ('a', 'b')),
    ({str(i): [str(i + 1)] for i in range(2000)}, None)])
def test_wait_cycle(waits, expected):
    from rosy_situation.wait_graph import wait_cycle
    assert wait_cycle(waits) == expected
