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

from core_common.face_screen import DRIVE_EVERY_S, DRIVE_HOLD_S, drive_due  # noqa: F401 - D-433

#: Any routable address works — the probe never sends a packet, it only asks the
#: OS which local interface would carry one. Google's resolver is a stable
#: choice that does not have to be reachable.
_ROUTE_PROBE_TARGET = ("8.8.8.8", 80)

#: 정보 창이 열려 있는 동안 display/info 재발행 간격 (s).
REPUBLISH_S = 1.0

#: D-394: 주행 카드 케이던스 — D-433 부터 core_common.face_screen 이 유일한 출처다
#: (rosy-face·emotion_server 와 같은 값).


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
        "charging": snapshot.battery_status.charging,
        "reason": status.last_wake_reason,
        "presence": status.presence.value,
        "hold_s": round(hold_s, 1),
        "hitl_requested": snapshot.hitl_requested,
        # D-321 addendum: "CALIBRATING" while a calibration lease is alive, else None.
        "activity": snapshot.activity.kind if snapshot.activity is not None else None,
    }


def resolve_api_address(port: Any, *, hostname: Callable[[], str] = socket.gethostname,
                        probe: Callable[[], Optional[str]] = outbound_ip) -> str:
    """`api_address` with the two lookups wired. Injected so tests need no network."""
    return api_address(port, probe(), hostname())


# --- D-394: drive card ------------------------------------------------------


def drive_payload(snapshot, *, hold_s: float = DRIVE_HOLD_S,
                  goal_x: float = None, goal_y: float = None) -> dict[str, Any]:
    """The `display/info` body of the drive card (`kind: "drive"`).

    웨이크 카드(``info_payload``)와 같은 반올림 계약: 속도는 0.01 m/s, 배터리는
    0.1 % / 0.01 V. 결측은 None — 주행 중 0.00 m/s 는 '멈춤'으로 읽히고,
    카드 한 장이 거짓말할 수 있는 지점이 여기다. 목표 좌표는 NAVIGATION
    중에만 실린다(다른 모드에서는 None). 도킹 중에는 DockState 를 실어
    화면이 "DOCKING" 대신 "CHARGING"·"DOCKED" 같은 실제 상태를 말하게 한다.
    """
    battery = snapshot.battery
    velocity = snapshot.velocity
    navigating = snapshot.mode.value == "NAVIGATION"
    # C6 — DockState 는 StateSnapshot 이 보장한다(schemas default_factory). reach 없이
    # 직접 읽고, 도킹 중에만 실는다(모드가 곧 맥락이다 — pinned test).
    docking_state = snapshot.docking.state.value if snapshot.mode.value == "DOCKING" else None
    return {
        "kind": "drive",
        "robot_id": snapshot.robot_id,
        "mode": snapshot.mode.value,
        "navigation": snapshot.navigation.value,
        "docking_state": docking_state,
        "speed": (round(velocity.linear, 2)
                  if velocity.linear is not None else None),
        "battery_percent": (round(battery.percent, 1)
                            if battery.percent is not None else None),
        "battery_voltage": (round(battery.voltage, 2)
                            if battery.voltage is not None else None),
        "charging": snapshot.battery_status.charging,
        "estop": snapshot.safety.estop,
        "goal_x": round(goal_x, 2) if goal_x is not None and navigating else None,
        "goal_y": round(goal_y, 2) if goal_y is not None and navigating else None,
        "hold_s": round(hold_s, 1),
    }


# --- D-433: the face hand-over (/run/rosy/face-inputs.json) ---------------------


def face_cautions(snapshot) -> list[str]:
    """Degradations only CORE knows, as ``face_screen.CAUTION_TEXT`` codes."""
    codes = []
    line_follow = snapshot.line_follow
    if line_follow.mode != "OFF" and line_follow.state == "HOLD":
        codes.append("line_follow_hold")
    if snapshot.docking.state.value == "DOCK_FAILED":
        codes.append("dock_failed")
    return codes


def face_inputs_payload(snapshot, *, face: Optional[str], power_mode: Optional[str],
                        wake: Optional[dict], written_at: str,
                        goal_x: Optional[float] = None, goal_y: Optional[float] = None) -> dict[str, Any]:
    """What rosy-face draws from (D-433 decision 3); ``face_screen.validate_face_inputs`` reads it.

    The drive card body rides only in an operating mode (the face owns IDLE,
    D-394) and the wake card only while CORE keeps its window open. Same
    rounding contract as the cards: ``drive_payload``/``info_payload`` build them.
    """
    battery = snapshot.battery
    mode = snapshot.mode.value
    drive = None
    if mode != "IDLE":
        drive = {key: value for key, value in drive_payload(snapshot, goal_x=goal_x, goal_y=goal_y).items()
                 if key != "kind"}
    line_follow = snapshot.line_follow
    return {
        "schema": 1,
        "written_at": written_at,
        "robot_mode": mode,
        "nav_state": snapshot.navigation.value,
        "estop": snapshot.safety.estop,
        "face": face,
        "power_mode": power_mode.lower() if isinstance(power_mode, str) else None,
        "activity_kind": snapshot.activity.kind if snapshot.activity is not None else None,
        "docking_state": snapshot.docking.state.value,
        "battery_percent": round(battery.percent, 1) if battery.percent is not None else None,
        "battery_charging": snapshot.battery_status.charging,
        "line_follow_mode": line_follow.mode,
        "line_follow_state": line_follow.state,
        "caution": face_cautions(snapshot),
        "drive": drive,
        "wake": wake,
    }


def face_camera_quality(preview: dict) -> dict:
    """Hand over only fresh JPEG exposure evidence; the reader ages it again."""
    quality, age_ms = preview.get('quality'), preview.get('age_ms')
    fresh = (preview.get('available') is True and preview.get('stale') is False
             and type(age_ms) in (int, float) and 0 <= age_ms <= 2000
             and quality in (dict(valid=False, reason='low_light'), dict(valid=True, reason='usable')))
    return dict(camera_quality=quality if fresh else None,
                camera_quality_age_s=age_ms / 1000.0 if fresh else None)


def face_inputs_due(content: dict, last_content: Optional[dict], now: float,
                    last_write: Optional[float], period_s: float) -> bool:
    """Write on every change, and at least every ``period_s`` so the reader sees CORE alive."""
    if last_write is None or last_content is None:
        return True
    return _coarse(content) != _coarse(last_content) or (now - last_write) >= period_s


def _coarse(body: dict) -> dict:
    """What counts as a change for an early write: not the clock, not measurement noise.

    Speed, battery and the wake card's countdown move every tick while driving;
    compared at full precision they would rewrite the file at 5 Hz. Coarsened,
    an early write happens only when what the card shows changes visibly; the
    1 s write carries the exact values anyway.
    """
    def rounded(value, digits):
        return round(value, digits) if isinstance(value, (int, float)) and not isinstance(value, bool) else value

    coarse = {key: value for key, value in body.items() if key != "written_at"}
    coarse["battery_percent"] = rounded(coarse.get("battery_percent"), 0)
    for key in ("drive", "wake"):
        card = coarse.get(key)
        if isinstance(card, dict):
            card = {name: value for name, value in card.items() if name != "hold_s"}
            for name, digits in (("speed", 1), ("battery_percent", 0), ("battery_voltage", 1)):
                card[name] = rounded(card.get(name), digits)
            coarse[key] = card
    return coarse
