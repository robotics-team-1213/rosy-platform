"""core_features.command.manager — CORE-002 + §8.1 cmd_vel 멀렉서 (P1-5, D-2). ROS 무의존.

유일한 cmd_vel 원천: select_output()을 50 Hz로 호출해 발행한다 (bridge 담당).
- EMERGENCY: 모든 소스 차단, zero-twist (SAF-001)
- MANUAL: teleop만, watchdog 만료 시 zero (SAF-002)
- NAVIGATION: nav_cmd_vel(Nav2) 통과, 속도 클리핑 (SAF-004)
- DOCKING: 도킹 슬롯만 통과 (docking.manager 가 쓴다). nav 슬롯은 막힌다 —
  Nav2 스테이징은 브리지가 도킹 슬롯으로 넘긴다 (core.bridge.docking_mode)
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
                 safety: SafetyManager, events=None, readiness=None,
                 teleop_timeout_ms: int = 500) -> None:
        self._registry = registry
        self._modes = modes
        self._safety = safety
        self._events = events
        # Optional ROS-free runtime gate.  It is enabled for the hardware
        # profile and remains inert for core/simulation profiles.
        self._readiness = readiness
        # SAF-002: default 500 ms, configurable (safety.teleop_timeout_ms).
        self.watchdog = TeleopWatchdog(timeout_ms=teleop_timeout_ms)
        self._manual_twist: Optional[Twist] = None
        self._modes.manual_active = lambda: self.manual_active
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
        #: 도킹 전용 슬롯. DOCKING 에서만 바퀴에 닿는다 — nav 슬롯을 같이 쓰면
        #: DOCKING 을 떠난 뒤에도 도킹 틱이 쓴 값이 NAVIGATION 에서 나간다.
        self._docking_twist: Optional[Twist] = None
        self._docking_updated_at: Optional[float] = None
        self._policy_ids = count(1)
        self._input_epoch = 0
        #: D-400: one safety.policy_off per entry into an autonomous mode while the policy is off.
        self._unguarded_noted = False
        self._pending_unguarded: Optional[str] = None
        self._unguarded_mode: Optional[Mode] = None
        #: D-400: the last candidate that reached the wheels, judged in announce_pending.
        self._pending_shadow: Optional[tuple] = None
        #: Failures swallowed in announce_pending (shadow judge or a publish).
        self.announce_errors = 0
        #: D-411: evidence hook for every teleop decision (rosy.teleop.intent/1).
        #: Set by the ROS bridge. It can never refuse or delay a command.
        self.intent_sink = None
        self.intent_errors = 0
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
        accepted, code, clipped = self._teleop_decision(linear, angular, source)
        self.note_intent(linear, angular, source, accepted, code, clipped=clipped)
        return accepted, code

    def note_intent(self, linear: float, angular: float, source: str, accepted: bool, code: str,
                    clipped: Optional[tuple[float, float]] = None) -> None:
        """D-411: what the operator asked for and what CORE decided. Evidence only."""
        if self.intent_sink is None:
            return
        try:
            self.intent_sink(raw_linear=linear, raw_angular=angular, clipped=clipped, source=source,
                             mode=self._modes.mode.value, accepted=accepted, code=code,
                             t_mono_ns=time.monotonic_ns())
        except Exception:  # noqa: BLE001 - evidence must never refuse a command
            self.intent_errors += 1

    def _teleop_decision(self, linear: float, angular: float,
                         source: str) -> tuple[bool, str, Optional[tuple[float, float]]]:
        if not self._registry.is_active_source(source):
            self._reject(source, "unregistered source")
            return False, "VALIDATION_ERROR", None
        if self._safety.estop or self._modes.is_emergency:
            self._reject(source, "e-stop active")
            return False, "EMERGENCY_ACTIVE", None
        if not self._motion_ready():
            self.clear_manual()
            self._reject(source, "navigation readiness HOLD")
            return False, "HARDWARE_NOT_READY", None
        if self._modes.mode is not Mode.MANUAL:
            self._reject(source, f"mode is {self._modes.mode.value}, not MANUAL")
            return False, "MODE_CONFLICT", None
        if not finite_velocity(linear, angular):
            self.clear_manual()
            self._reject(source, "invalid velocity")
            return False, "VALIDATION_ERROR", None
        linear, angular = self._safety.clip(linear, angular, scope="manual")
        # 명령을 먼저 놓고 워치독을 나중에 되살린다. 거꾸로면 그 사이의 틱이
        # 되살아난 워치독과 만료된 **옛** 명령을 함께 읽어 바퀴로 다시 보낸다.
        def commit() -> None:
            self._manual_twist = Twist(linear, angular)
            self._manual_source = source
            self._input_epoch += 1
            self.watchdog.refresh()
            # A new command starts a new watchdog episode.
            self._session += 1

        if not self._modes.commit_manual(commit):
            self._reject(source, "mode changed before manual input commit")
            return False, "MODE_CONFLICT", None
        return True, "", (linear, angular)

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

    def set_docking_twist(self, twist: Optional[Twist], now: Optional[float] = None) -> None:
        if self._safety.estop or self._modes.is_emergency:
            twist = None
        if twist is not None and not finite_velocity(twist.linear, twist.angular):
            self._reject('docking', 'invalid velocity')
            twist = None
        self._docking_twist = twist
        self._input_epoch += 1
        self._docking_updated_at = (
            (now if now is not None else time.monotonic()) if twist is not None else None
        )

    def clear_docking(self) -> None:
        self.set_docking_twist(None)

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
        self.clear_docking()

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
        """밀린 알림을 낸다. 브리지가 cmd_vel 을 내보낸 **뒤** 부른다.

        Nothing here may escape: a failing sink or judge must not reach the
        50 Hz loop, nor skip the announcements after it.
        """
        session = self._pending_watchdog
        if session is not None:
            self._pending_watchdog = None
            if session != self._announced_session:
                self._announced_session = session
                if self._events is not None:
                    try:
                        self._events.publish(
                            "safety.watchdog", severity="warning", source="command_manager",
                            data={"timeout_ms": self.watchdog.timeout_ms})
                    except Exception:  # noqa: BLE001
                        self.announce_errors += 1
        args, self._pending_shadow = self._pending_shadow, None
        if args is not None:
            try:
                self._safety.shadow_evaluate(*args[:5], output=args[5])
            except Exception:  # noqa: BLE001 - shadow can only record, never raise
                self.announce_errors += 1
        unguarded, self._pending_unguarded = self._pending_unguarded, None
        if unguarded is not None and self._events is not None:
            try:
                self._events.publish("safety.policy_off", severity="warning",
                                     source="command_manager", data={"source": unguarded})
            except Exception:  # noqa: BLE001
                self.announce_errors += 1
        if self._safety.shadow is not None:
            try:
                drained = self._safety.shadow.drain()
            except Exception:  # noqa: BLE001
                self.announce_errors += 1
                drained = []
            for data in drained:
                if self._events is None:
                    continue
                try:
                    self._events.publish("safety.shadow_verdict", severity="info",
                                         source="command_manager", data=data)
                except Exception:  # noqa: BLE001
                    self.announce_errors += 1

    def _policy_output(self, linear: float, angular: float, source: str, now: float) -> Twist:
        if linear == 0. and angular == 0.:
            return ZERO
        epoch, mode, command_id = self._input_epoch, self._modes.mode, next(self._policy_ids)
        output = self._safety.evaluate_candidate(command_id, source, linear, angular, now,
                                                 scope='manual' if mode is Mode.MANUAL else 'nav')
        if epoch != self._input_epoch or mode is not self._modes.mode or self._safety.estop:
            return ZERO
        if output is None:
            # Latch first: whatever the mode change sets in motion, the e-stop
            # is already set.
            self._safety.trigger_estop('control:' + self._safety.policy_reason)
            self._modes.transition(Mode.EMERGENCY)
            return ZERO
        result = Twist(*output)
        # D-400: judged after cmd_vel reached the wheels (announce_pending) so the
        # policy's cost never delays the output. Single slot: one candidate per cycle.
        self._pending_shadow = (command_id, source, linear, angular, now,
                                (result.linear, result.angular))
        if (self._safety.policy_mode == 'off' and source in ('navigation', 'docking')
                and not self._unguarded_noted):
            self._unguarded_noted = True
            self._pending_unguarded = source
        return result

    def select_output(self, now: Optional[float] = None) -> Twist:
        current = now if now is not None else time.monotonic()
        if self._modes.mode is not self._unguarded_mode:
            self._unguarded_noted = False
            self._unguarded_mode = self._modes.mode
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
        if self._modes.mode is Mode.NAVIGATION:
            held, stamp, source = self._nav_twist, self._nav_updated_at, 'navigation'
        elif self._modes.mode is Mode.DOCKING:
            held, stamp, source = self._docking_twist, self._docking_updated_at, 'docking'
        else:
            return ZERO
        age = current - stamp if stamp is not None else None
        if held is not None and age is not None and 0.0 <= age <= self._nav_timeout_s:
            l, a = self._safety.clip(held.linear, held.angular, "nav")
            return self._policy_output(l, a, source, current)
        return ZERO
