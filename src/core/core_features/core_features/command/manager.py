"""core_features.command.manager — CORE-002 + §8.1 cmd_vel 멀렉서 (P1-5, D-2). ROS 무의존.

유일한 cmd_vel 원천: select_output()을 50 Hz로 호출해 발행한다 (bridge 담당).
- EMERGENCY: 모든 소스 차단, zero-twist (SAF-001)
- MANUAL: teleop만, watchdog 만료 시 zero (SAF-002)
- NAVIGATION: nav_cmd_vel(Nav2) 통과, 속도 클리핑 (SAF-004)
"""

from __future__ import annotations

import time
from itertools import count
from dataclasses import dataclass
from typing import Optional

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.safety.manager import SafetyManager, TeleopWatchdog, finite_velocity


@dataclass
class Twist:
    linear: float = 0.0
    angular: float = 0.0


ZERO = Twist()


class CommandManager:
    def __init__(self, registry: SourceRegistry, modes: ModeMachine,
                 safety: SafetyManager, events=None, readiness=None) -> None:
        self._registry = registry
        self._modes = modes
        self._safety = safety
        self._events = events
        # Optional ROS-free runtime gate.  It is enabled for the hardware
        # profile and remains inert for core/simulation profiles.
        self._readiness = readiness
        self.watchdog = TeleopWatchdog(timeout_ms=500)
        self._manual_twist: Optional[Twist] = None
        self._manual_source = 'manual'
        #: teleop 세션 번호. 만료 알림(SAF-002)은 세션당 한 번이다.
        #:
        #: 불리언이면 경합에서 사라진다: 타이머가 "아직 안 알림"을 읽고 멈춘
        #: 사이 새 명령이 들어와 초기화하면, 타이머가 깨어나 그 새 세션을
        #: "이미 알림"으로 덮어써 그 세션의 끊김은 영영 조용해진다. 번호를
        #: 비교하면 뒤늦은 쓰기가 옛 값을 실어 무해하다.
        self._session = 0
        self._announced_session = -1
        #: 알릴 것이 밀려 있는가. 알림은 정지가 바퀴에 닿은 뒤에 낸다.
        self._pending_watchdog: Optional[int] = None
        self._nav_twist: Optional[Twist] = None
        self._nav_updated_at: Optional[float] = None
        self._nav_timeout_s = 0.5
        self._policy_ids = count(1)
        self._input_epoch = 0
        self._safety.estop_listeners.append(self._clear_for_stop)
        self._safety.policy_listeners.append(self._clear_for_stop)

    def set_readiness_gate(self, readiness) -> None:
        self._readiness = readiness

    def _motion_ready(self) -> bool:
        return self._readiness is None or self._readiness.is_ready()

    def _reject(self, source: str, reason: str) -> None:
        if self._events is not None:
            self._events.publish("command.rejected", severity="warning",
                                 source="command_manager", data={"source": source, "reason": reason})

    def teleop(self, linear: float, angular: float, source: str = "manual") -> tuple[bool, str]:
        if not self._registry.is_active_source(source):
            self._reject(source, "unregistered source")
            return False, "VALIDATION_ERROR"
        if self._safety.estop or self._modes.is_emergency:
            self._reject(source, "e-stop active")
            return False, "EMERGENCY_ACTIVE"
        if not self._motion_ready():
            self.clear_manual()
            self._reject(source, "navigation readiness HOLD")
            return False, "HARDWARE_NOT_READY"
        if self._modes.mode is not Mode.MANUAL:
            self._reject(source, f"mode is {self._modes.mode.value}, not MANUAL")
            return False, "MODE_CONFLICT"
        if not finite_velocity(linear, angular):
            self.clear_manual()
            self._reject(source, "invalid velocity")
            return False, "VALIDATION_ERROR"
        linear, angular = self._safety.clip(linear, angular, scope="manual")
        # 명령을 먼저 놓고 워치독을 나중에 되살린다. 거꾸로면 그 사이의 틱이
        # 되살아난 워치독과 만료된 **옛** 명령을 함께 읽어 바퀴로 다시 보낸다.
        self._manual_twist = Twist(linear, angular)
        self._manual_source = source
        self._input_epoch += 1
        self.watchdog.refresh()
        # 새 명령이 왔으니 다음 끊김은 다시 알릴 일이다.
        self._session += 1
        return True, ""

    @property
    def manual_active(self) -> bool:
        """살아 있는 teleop 세션이 있는가.

        도킹 복귀 정책이 쓴다 — MANUAL(3)이 DOCKING(4)보다 위라, 운영자가 쥐고
        있는 로봇을 배터리 정책이 빼앗지 않는다. 워치독이 만료된 명령은 이미
        조종이 아니므로 세션으로 치지 않는다.
        """
        return self._manual_twist is not None and not self.watchdog.expired()

    def set_nav_twist(self, twist: Optional[Twist], now: Optional[float] = None) -> None:
        if self._safety.estop or self._modes.is_emergency:
            twist = None
        if twist is not None and not finite_velocity(twist.linear, twist.angular):
            self._reject('navigation', 'invalid velocity')
            twist = None
        self._nav_twist = twist
        self._input_epoch += 1
        self._nav_updated_at = (
            (now if now is not None else time.monotonic()) if twist is not None else None
        )

    def clear_navigation(self) -> None:
        self.set_nav_twist(None)

    def clear_manual(self) -> None:
        self._manual_twist = None
        self._input_epoch += 1
        self.watchdog.refresh(0.0)

    def _drop_manual_session(self) -> None:
        """쥐고 있던 teleop 을 버리고, 그 세션의 끊김은 알리지 않는다.

        E-Stop·정책 정지·readiness HOLD·MANUAL 이탈은 이미 알려진 정지
        사유다. 쥐고 있던 teleop 을 남겨두면 MANUAL 로 돌아온 첫 틱이 (500 ms
        안이면) 옛 명령을 다시 내보내거나, 만료를 발견해 `safety.watchdog` 을
        낸다 — 감사 로그가 멀쩡했던 링크를 끊겼다고 적는 셈이다.
        """
        self._pending_watchdog = None
        self._announced_session = self._session
        self.clear_manual()

    def _clear_for_stop(self) -> None:
        self._drop_manual_session()
        self.clear_navigation()

    def _note_watchdog_lapse(self, session: int) -> None:
        """SAF-002 만료를 기록해 둔다. 내보내는 것은 `announce_pending` 이다.

        `select_output` 은 50 Hz cmd_vel 경로의 첫 줄이고, 그 반환값이 바퀴로
        나간다. 여기서 바로 발행하면 정지를 **알리는 일이 정지를 내보내는
        일보다 먼저** 온다: EventBus 는 구독자를 동기로 부르고 그중 하나가
        감사 로그 파일 싱크다. 그동안 드라이버는 끊기기 직전의 0 아닌 명령을
        그대로 쥐고 있다. 그래서 여기서는 기록만 하고, 정지가 나간 뒤
        호출자(`core.bridge.cmd_vel.cmd_vel_cycle`)가 알린다.

        `session` 은 호출자가 만료를 **판정하기 전에** 읽은 번호다. 여기서
        `self._session` 을 다시 읽으면, 판정과 기록 사이에 들어온 새 teleop 의
        번호가 기록되어 그 새 세션이 "이미 알림"이 되고 그 세션의 진짜 끊김이
        조용해진다.
        """
        if self._announced_session == session:
            return
        self._pending_watchdog = session

    def announce_pending(self) -> None:
        """밀린 알림을 낸다. 브리지가 cmd_vel 을 내보낸 **뒤** 부른다."""
        session = self._pending_watchdog
        if session is None:
            return
        self._pending_watchdog = None
        if session == self._announced_session:
            return
        self._announced_session = session
        if self._events is not None:
            self._events.publish(
                "safety.watchdog", severity="warning", source="command_manager",
                data={"timeout_ms": self.watchdog.timeout_ms})

    def _policy_output(self, linear: float, angular: float, source: str, now: float) -> Twist:
        if linear == 0. and angular == 0.:
            return ZERO
        epoch, mode = self._input_epoch, self._modes.mode
        output = self._safety.evaluate_candidate(next(self._policy_ids), source, linear, angular, now,
                                                 scope='manual' if mode is Mode.MANUAL else 'nav')
        if epoch != self._input_epoch or mode is not self._modes.mode or self._safety.estop:
            return ZERO
        if output is None:
            self._modes.transition(Mode.EMERGENCY)
            self._safety.trigger_estop('control:' + self._safety.policy_reason)
            return ZERO
        return Twist(*output)

    def select_output(self, now: Optional[float] = None) -> Twist:
        current = now if now is not None else time.monotonic()
        stopped = self._safety.estop or self._modes.is_emergency
        ready = self._motion_ready()
        leaving_manual = stopped or not ready or self._modes.mode is not Mode.MANUAL
        if leaving_manual and self._manual_twist is not None:
            self._drop_manual_session()
        if stopped or not ready:
            return ZERO
        if self._modes.mode is Mode.MANUAL:
            # 번호는 만료 판정 **전에** 읽는다 (`_note_watchdog_lapse`).
            session, held = self._session, self._manual_twist
            if held is not None and not self.watchdog.expired(current):
                # 명령은 판정 **뒤에** 다시 읽는다. 판정 전에 읽은 것을 쓰면,
                # 그 사이 들어온 teleop 이 되살린 워치독으로 만료된 옛 명령이
                # 한 틱 동안 바퀴로 나간다.
                held = self._manual_twist
                if held is None:
                    return ZERO
                l, a = self._safety.clip(held.linear, held.angular, "manual")
                return self._policy_output(l, a, self._manual_source, current)
            if held is not None:
                self._note_watchdog_lapse(session)
            return ZERO
        nav_age = current - self._nav_updated_at if self._nav_updated_at is not None else None
        if (
            self._modes.mode is Mode.NAVIGATION
            and self._nav_twist is not None
            and nav_age is not None
            and 0.0 <= nav_age <= self._nav_timeout_s
        ):
            l, a = self._safety.clip(self._nav_twist.linear, self._nav_twist.angular, "nav")
            return self._policy_output(l, a, 'navigation', current)
        return ZERO
