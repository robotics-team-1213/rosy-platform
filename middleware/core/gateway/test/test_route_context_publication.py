"""D-531 CORE publishes context at 5 Hz and clears it on loss."""
from core_common.protocol.route_context import RouteContext
from core.bridge.route_context import publication


def _ring(seq=4, stamp=100.):
    return RouteContext(v=1, seq=seq, place_id="SW", map_id="track-v1", kind="ring",
                        curvature_1pm=3., stamp_s=stamp, valid_until_s=stamp+.5)


def test_active_context_is_periodic_but_instruction_change_and_loss_are_immediate():
    previous, at = None, float("-inf")
    message, previous, at = publication(_ring(), previous, at, now=100.)
    assert message["seq"] == 4 and at == 100.
    message, previous, at = publication(_ring(stamp=100.1), previous, at, now=100.1)
    assert message is None
    message, previous, at = publication(_ring(stamp=100.2), previous, at, now=100.2)
    assert message["stamp_s"] == 100.2
    message, previous, at = publication(_ring(seq=5, stamp=100.21), previous, at, now=100.21)
    assert message["seq"] == 5
    message, previous, at = publication(None, previous, at, now=100.22)
    assert message == {"v": 1, "seq": None}
    assert publication(None, previous, at, now=100.23)[0] is None


def test_clock_rewind_clears_old_context():
    _, previous, at = publication(_ring(), None, float("-inf"), now=100.)
    message, previous, at = publication(_ring(stamp=2.), previous, at, now=2.)
    assert message == {"v": 1, "seq": None}
