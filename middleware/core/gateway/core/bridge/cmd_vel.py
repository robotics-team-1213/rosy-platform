"""바퀴로 나가는 한 주기 (ROS 없이 검사할 수 있게 떼어낸 것).

`_publish_cmd_vel` 은 네 가지를 순서대로 한다: 값을 고르고, 준비가 안 됐으면
0 으로 누르고, 바퀴로 내보내고, 그 **뒤에** 알린다. 순서가 기능의 절반인데
브리지 안에 있으면 rclpy 없는 호스트에서 아무도 검사하지 못한다 — 알림 한
줄을 지워도 모든 테스트가 초록이다. 그래서 순서만 여기로 나온다.

SAF-002 정지가 늦어지지 않게 하는 규칙 두 가지:

* 이벤트 발행(`announce_pending`)은 구독자를 동기로 부르고 그중 하나가 감사
  로그를 쓴다. 내보내기 앞에 두면 그 비용만큼 정지가 늦게 바퀴에 닿는다.
* 절전 정책(`on_activity`)도 마찬가지다. 모터 경로에 개입하지 않는 관측일
  뿐이니, 관측이 바퀴 앞에 설 이유가 없다.
"""

from __future__ import annotations

from threading import RLock
import time
from typing import Any, Callable, Optional, Protocol

from core_features.command.manager import ZERO, Twist
from rosy.contracts.motion import (BaseTwist, EstopStatus, GuardedMotion, MotionKind,
                                   PortCapabilities, PortDecision, PortState)


# Stage (b) records the existing clip implementation; Arbiter admission is (c).
GUARD_REVISION = "pinky-command-manager-b-v1"
GUARD_LIFETIME_S = 0.3
_BINDING_TOKEN = object()


class PinkyTwistPort:
    """Cycle-local identity gate around the existing final writer callback.

    This private Python capability is a trusted-process invariant, not a
    security boundary against code inspecting private attributes. It never
    grants producer authority, reads physical E-stop or releases any stop.
    """

    def __init__(self, send: Callable[[Any], None], *, clock=time.monotonic):
        self._send = send
        self._clock = clock
        self._lock = RLock()
        self._original = None
        self._issued_at = None
        self._closed = False
        self._state = "ready"

    def _bind(self, cmd: GuardedMotion) -> None:
        with self._lock:
            if (self._closed or self._issued_at is not None or type(cmd) is not GuardedMotion
                    or type(cmd.payload) is not BaseTwist or cmd._token is not _BINDING_TOKEN
                    or cmd.guard_revision != GUARD_REVISION):
                raise ValueError("invalid cycle grant")
            self._issued_at = self._clock()
            self._original = cmd

    def submit(self, cmd: GuardedMotion) -> PortDecision:
        with self._lock:
            if (self._closed or type(cmd) is not GuardedMotion or cmd is not self._original
                    or cmd._token is not _BINDING_TOKEN):
                return PortDecision(False, self._state, "invalid_cycle_grant")
            now = self._clock()
            if not self._issued_at <= now < self._issued_at + GUARD_LIFETIME_S:
                self._original = None
                self._state = "hold"
                return PortDecision(False, "hold", "cycle_grant_expired")
            # Consume under the same lock before entering the writer. A lost
            # ACK or exception never makes this original replayable.
            self._original = None
            self._state = "active"
        try:
            self._send(Twist(cmd.payload.linear_mps, cmd.payload.angular_radps))
        except Exception:
            with self._lock:
                self._state = "hold"
            raise
        return PortDecision(True, "active", "written")

    def close(self) -> None:
        with self._lock:
            self._original = None
            self._closed = True
            self._state = "disabled"

    def capabilities(self) -> PortCapabilities:
        return PortCapabilities((MotionKind.BASE_TWIST,), frames=("base_link",), supports_stream=True)

    def cancel(self, intent_id: str) -> PortDecision:
        # Stage (b) has no intent header/identity and cannot cancel by id.
        return PortDecision(False, self.state().state, "intent_identity_unavailable")

    def state(self) -> PortState:
        with self._lock:
            return PortState(self._state)

    def estop_status(self) -> EstopStatus:
        return EstopStatus(None)


class _Output(Protocol):
    linear: float
    angular: float


class _Command(Protocol):
    def select_output(self) -> _Output: ...
    def announce_pending(self) -> None: ...


class _Power(Protocol):
    # 인자 이름까지 `PowerManager.on_activity` 와 같게 적는다 — 구조적
    # 타입은 이름으로 맞추므로, 다르게 적으면 mypy 가 들어오는 날 오류다.
    def on_activity(self, source: str) -> None: ...


class _Readiness(Protocol):
    def is_ready(self) -> bool: ...


def cmd_vel_cycle(command: _Command, power: _Power, send: Callable[[Any], None],
                  readiness: Optional[_Readiness] = None,
                  warn: Optional[Callable[[str], None]] = None) -> None:
    """값을 고르고, 바퀴로 내보내고, 그 뒤에 알린다.

    `readiness` 가 HOLD 이면 고른 값 대신 0 을 내보낸다 — 최종 발행자는
    50 Hz 로 살아 있되, 하드웨어 그래프가 HOLD 인 동안 낡은 Nav2/수동 후보를
    흘려보내지 않는다.

    `send` 에는 고른 값을 **통째로** 넘긴다. `(linear, angular)` 두 개를
    자리로 넘기면 받는 쪽에서 둘을 바꿔 적어도 타입은 맞고, 그것은
    전진 명령을 제자리 회전으로 바꾼다.
    """
    try:
        out = command.select_output()
    except Exception as exc:
        # 고르기가 예외를 내면 (안전 정책 평가 등) 0 을 내보낸다. 예외가 rclpy
        # 타이머 밖으로 새면 50 Hz 최종 발행자가 멈추고, 바퀴는 마지막 값을 쥔다.
        send(ZERO)
        if warn is not None:
            warn(f"cmd_vel output failed: {exc}")
        return
    if readiness is not None and not readiness.is_ready():
        out = ZERO
    port = None
    try:
        port = PinkyTwistPort(send)
        guarded = GuardedMotion(BaseTwist(out.linear, out.angular), GUARD_REVISION, _BINDING_TOKEN)
        port._bind(guarded)
    except Exception as exc:
        if port is not None:
            port.close()
        send(ZERO)
        if warn is not None:
            warn(f"cmd_vel guard failed: {exc}")
        return
    try:
        decision = port.submit(guarded)
        if not decision.accepted:
            send(ZERO)
            if warn is not None:
                warn(f"cmd_vel guard refused: {decision.reason}")
            return
    finally:
        port.close()
    if guarded.payload.linear_mps != 0.0 or guarded.payload.angular_radps != 0.0:
        power.on_activity("cmd_vel")
    command.announce_pending()
