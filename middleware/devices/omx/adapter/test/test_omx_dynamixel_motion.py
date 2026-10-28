"""Legacy exception imports remain catch-compatible after motion extraction."""

import pytest

from omx_adapter.real.dynamixel_port import DynamixelPort, _Hold


def test_moved_motion_hold_is_caught_through_original_port_alias():
    from omx_adapter.real import dynamixel_motion

    port = DynamixelPort.__new__(DynamixelPort)
    port._stop_requested = True
    port.latched = False
    with pytest.raises(_Hold, match="STOPPED") as caught:
        dynamixel_motion._DynamixelMotion._check_cancel(port)
    assert type(caught.value) is _Hold
    assert caught.value.reason == "STOPPED"
