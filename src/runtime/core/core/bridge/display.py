"""ROS-free decisions behind `display/info` (PWR-003). Imports no ROS type.

Two things the bridge used to compute inline, where no host test could reach
them: which address to show an operator standing in front of the robot, and how
the status payload is rounded and shaped. Both are decisions — a wrong rounding
or a wrong fallback address is invisible to a boot smoke test and obvious on the
screen.

`bridge/AGENTS.md`: a callback should read as translate, decide, act. This is
the decide half.
"""

from __future__ import annotations

import socket
from typing import Any, Callable, Optional

#: Any routable address works — the probe never sends a packet, it only asks the
#: OS which local interface would carry one. Google's resolver is a stable
#: choice that does not have to be reachable.
_ROUTE_PROBE_TARGET = ("8.8.8.8", 80)

#: 정보 창이 열려 있는 동안 display/info 재발행 간격 (s).
REPUBLISH_S = 1.0


def republish_due(visible: bool, was_visible: bool, now: float,
                  last_pub: float) -> bool:
    """이 틱에 `display/info` 를 다시 띄워야 하는가.

    창이 열리는 순간 한 번, 그 뒤로는 `REPUBLISH_S` 마다 — 화면은 자기
    상태를 갖고 있지 않아 늦게 떠 노드나 놓친 패킷은 다음 재발행까지
    아무것도 보지 못한다. 창이 닫혀 있으면 아무 때도 아니다.
    """
    if not visible:
        return False
    return (not was_visible) or (now - last_pub) >= REPUBLISH_S


def outbound_ip(target: tuple[str, int] = _ROUTE_PROBE_TARGET) -> Optional[str]:
    """The local address the OS would route from, or None if it cannot say.

    A UDP socket's `connect` performs no I/O; it binds the local end that a
    packet *would* leave by. Any failure here is expected offline and must not
    reach the caller.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(target)
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def api_address(port: Any, host: Optional[str], fallback_host: str) -> str:
    """The URL to put on the info screen.

    `host` is the routed address when the probe answered. Falling back to the
    hostname is deliberate: on a robot with no route the operator is standing at
    it, and a hostname they can type beats a blank line. The port is coerced
    because it arrives from YAML, where `8080` and `"8080"` both occur.
    """
    return f"http://{host or fallback_host}:{int(port)}"


def info_payload(snapshot, status, *, health: str, address: str,
                 hold_s: float) -> dict[str, Any]:
    """The `display/info` body.

    Rounding is the contract with the screen, not a formatting detail: percent
    to 0.1 and volts to 0.01 are what fit the widths, and the hold countdown to
    0.1 so it ticks visibly. Percent and voltage stay `None` rather than `0.0`
    when no cell reading has arrived — a screen showing 0.00 V reads as a dead
    battery, which is the one thing it must not say by accident.
    """
    battery = snapshot.battery
    return {
        "battery_percent": (round(battery.percent, 1)
                            if battery.percent is not None else None),
        "battery_voltage": (round(battery.voltage, 2)
                            if battery.voltage is not None else None),
        "robot_id": snapshot.robot_id,
        "mode": snapshot.mode.value,
        "navigation": snapshot.navigation.value,
        "health": health,
        "estop": snapshot.safety.estop,
        "address": address,
        "reason": status.last_wake_reason,
        "presence": status.presence.value,
        "hold_s": round(hold_s, 1),
        "hitl_requested": snapshot.hitl_requested,
    }


def resolve_api_address(port: Any, *, hostname: Callable[[], str] = socket.gethostname,
                        probe: Callable[[], Optional[str]] = outbound_ip) -> str:
    """`api_address` with the two lookups wired. Injected so tests need no network."""
    return api_address(port, probe(), hostname())
