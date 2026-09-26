"""Change-detection latches for the 5 Hz reconcile ticks. ROS-free.

Thin by design, and worth saying why it exists at all: the *policy* for these
two actuators already lives elsewhere — LED colour in `power.battery.resolve_led`,
LiDAR spin intent in `PowerManager`. What was left inline in `ros_bridge.py` is
the latch, and the latch carries a decision the two do not share.

**LED latches even when the call is skipped.** The service may be absent; the
LED is decoration and the tick is 5 Hz, so re-attempting the same colour five
times a second buys nothing. The cost is that a service arriving late is not
driven until the colour next changes.

**LiDAR latches only when the call goes out.** It is a navigation input, so a
driver that comes up late must be reached — not latching means the next tick
tries again, 5 Hz until it lands.

That asymmetry is deliberate (`bridge/AGENTS.md`) and was previously visible
only by reading two functions side by side and noticing that one sets its latch
inside the guard and the other outside it. Here it is a parameter with a name.
"""

from __future__ import annotations

from typing import Any, Callable

from core_features.power.battery import resolve_led


def reconcile(desired: Any, applied: Any, act: Callable[[], bool], *,
              latch_on_skip: bool) -> tuple[bool, Any]:
    """Drive `act` only when `desired` differs from `applied`.

    `act` reports whether the action actually went out — for a ROS service that
    is "the endpoint was ready". Returns `(acted, applied)`, where `applied` is
    what the caller should remember.

    With `latch_on_skip=True` a skipped action still counts as applied, so it is
    not retried. With `False` the latch is left alone and the next tick tries
    again.
    """
    if desired == applied:
        return False, applied
    acted = act()
    return acted, (desired if acted or latch_on_skip else applied)


def led(alert: Any, applied: Any, *, info_visible: bool, gauge_percent: float,
        now: float, act: Callable[[Any], bool]) -> Any:
    """이 틱의 LED 명령을 정하고 latch 까지 끝낸다 (SAF-005 경보 > 정보창 게이지).

    명령이 바뀔 때만 서비스를 부른다. 이 틱은 5 Hz 이고 DEEP 경보는 2 Hz 로
    깜빡이므로, 그러지 않으면 같은 색을 초당 다섯 번 다시 칠하게 된다.
    `latch_on_skip=True` — 장식이다, 서비스가 없으면 다시 칠하지 않는다.
    """
    command = resolve_led(
        alert, info_visible=info_visible, gauge_percent=gauge_percent, now=now)
    _acted, applied = reconcile(
        command, applied, lambda: act(command), latch_on_skip=True)
    return applied
