"""core_features.safety.fleet_loss — SAF-003 Fleet 연결 상실 정책 (D-419). ROS 무의존.

판정: FleetAgent 가 설정돼 돌고 있고, 링크가 끊긴 순간 Fleet 이 보낸 주행 목표
(correlation_id 가 있는 목표, D-316)가 진행 중이었으며, 그 목표가 그대로인 채로
`timeout_s` 동안 링크가 계속 끊겨 있으면 정책을 **한 번** 적용한다. 끊긴 뒤 REST 로
들어온 목표는 Fleet 이 로봇에 닿았다는 증거이므로 대상이 아니다.

느린 타이머(ros_bridge 5 Hz)가 `tick()` 을 부른다 — 50 Hz `cmd_vel` 경로 밖이고,
이벤트는 행동을 마친 뒤에 낸다(무엇을 실제로 했는지를 싣기 위해).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Optional

from core_features.fleet_agent.agent import (
    DEFAULT_REPLY_TIMEOUT_S,
    HEARTBEAT_PERIOD_S,
    LINK_SLACK_S,
)

logger = logging.getLogger(__name__)

#: SAF-003 정책. API 는 `CONTINUE_CURRENT_NAVIGATION` 을 `CONTINUE` 로 받는다.
POLICIES = ("STOP", "HOLD", "RETURN_HOME", "CONTINUE")
DEFAULT_TIMEOUT_S = 5.0
#: 답 시한 위에 둘 최소 여유 (D-419 재리뷰).
TIMING_MARGIN_S = 1.0


def link_timing_floor_s(heartbeat_period_s: float, reply_timeout_s: float) -> float:
    """The one formula for the shortest allowed `fleet_loss_timeout_s`: a healthy link can
    be silent for one heartbeat period + the reply deadline; add a margin on top."""
    return heartbeat_period_s + reply_timeout_s + TIMING_MARGIN_S


#: 하한은 기본 하트비트·답 시한에서 같은 식으로 나온다(4 s). 60 s 넘게 끊긴 채 달리는 것은
#: STOP 기본값의 뜻과 맞지 않는다.
TIMEOUT_RANGE_S = (link_timing_floor_s(HEARTBEAT_PERIOD_S, DEFAULT_REPLY_TIMEOUT_S), 60.0)
#: The agent's link freshness at default settings (its `link_fresh_s`).
DEFAULT_FRESHNESS_S = HEARTBEAT_PERIOD_S + DEFAULT_REPLY_TIMEOUT_S + LINK_SLACK_S


def normalize_policy(value) -> tuple[str, bool]:
    """`(정책, 알려진 값인가)`. 모르는 값은 가장 안전한 STOP 으로 읽는다."""
    text = str(value).strip().upper() if value is not None else ""
    if text == "CONTINUE_CURRENT_NAVIGATION":
        text = "CONTINUE"
    if text in POLICIES:
        return text, True
    return "STOP", False


def fleet_loss_timeout_s(safety_cfg: dict) -> float:
    """`safety.fleet_loss_timeout_s` 를 읽고 검증한다. 범위 밖이면 기동을 막는다."""
    raw = safety_cfg.get("fleet_loss_timeout_s", DEFAULT_TIMEOUT_S)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("safety.fleet_loss_timeout_s must be a number")
    value = float(raw)
    low, high = TIMEOUT_RANGE_S
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"safety.fleet_loss_timeout_s must be within {low}-{high} s")
    return value


def validate_link_timing(timeout_s: float, heartbeat_period_s: float,
                         reply_timeout_s: float) -> None:
    """`fleet_loss_timeout_s` must outlast one heartbeat period + the reply deadline + 1 s,
    or a healthy link that is merely between replies reads as lost. Fails CORE start."""
    floor = link_timing_floor_s(heartbeat_period_s, reply_timeout_s)
    if timeout_s < floor:
        raise ValueError(
            f"safety.fleet_loss_timeout_s ({timeout_s:g} s) must be >= heartbeat period "
            f"({heartbeat_period_s:g}) + fleet.heartbeat_reply_timeout_s ({reply_timeout_s:g}) "
            f"+ {TIMING_MARGIN_S:g} = {floor:g} s")


class FleetLossMonitor:
    """SAF-003 판정과 적용. 의존은 모두 주입된 호출 가능 객체다.

    - `fleet_goal()` → `(correlation_id, NavGoalSpec)` 또는 None (진행 중인 Fleet 목표)
    - `stop_goal(correlation_id)` → 그 목표가 아직 진행 중일 때만 취소, 취소했으면 True
    - `return_home()` → 귀환 목표를 내거나 예외
    - `link_configured()` → 기동 설정에 Fleet 링크가 있는가. 한 번 설정된 로봇에서는 Agent 가
      멈추거나(hello 거부·`stop()`) 해도 링크는 "끊김"이지 "설정 없음"이 아니다 (D-419 리뷰 I1)
    - `link_connected()` / `link_last_rx()` → WELCOME 뒤 소켓이 열려 있는가, 마지막 허브 수신
      시각(같은 monotonic 시계). 마지막 수신이 `freshness_s`(하트비트 주기 + 답 시한 + 여유)
      보다 오래됐으면 끊긴 것으로 본다. 판정 시간 `timeout_s` 와는 따로다 — 묶어 두면 짧은
      `timeout_s` 에서 답과 답 사이의 건강한 링크가 끊김으로 읽힌다 (D-419 재리뷰 HIGH)
    """

    def __init__(self, *, events, link_configured: Callable[[], bool],
                 link_connected: Callable[[], bool], fleet_goal: Callable,
                 policy: Callable[[], str], stop_goal: Callable[[str], bool],
                 return_home: Callable[[], None], timeout_s: float = DEFAULT_TIMEOUT_S,
                 link_last_rx: Optional[Callable[[], Optional[float]]] = None,
                 freshness_s: float = DEFAULT_FRESHNESS_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._events = events
        self._configured = link_configured
        self._connected = link_connected
        self._last_rx = link_last_rx or (lambda: None)
        self._fleet_goal = fleet_goal
        self._policy = policy
        self._stop_goal = stop_goal
        self._return_home = return_home
        self.timeout_s = float(timeout_s)
        self.freshness_s = float(freshness_s)
        #: Wall clock on purpose: a network link is lost in real seconds, also under sim time.
        self.clock = clock
        #: tick() (bridge timer) and status() (API worker) run on different threads.
        self._lock = threading.Lock()
        self._reset()

    def _link_up(self, now: float) -> bool:
        if not self._connected():
            return False
        last_rx = self._last_rx()
        return last_rx is None or now - last_rx < self.freshness_s

    def _reset(self) -> None:
        self._down_since: Optional[float] = None
        #: 링크가 끊긴 순간 진행 중이던 Fleet 목표 (correlation_id, spec).
        self._at_loss = None
        self._applied: Optional[str] = None
        self._held = None

    def tick(self) -> None:
        """One judgement. Events go out after the lock is released."""
        with self._lock:
            lost, restored = self._tick_locked()
        # Literal payload keys at the emit site: test_event_catalogue reads them here.
        if restored is not None:
            self._events.publish(
                "safety.fleet_restored", severity="info", source="fleet_loss_monitor",
                data={"applied": restored["applied"], "correlation_id": restored["correlation_id"],
                      "disconnected_s": restored["disconnected_s"],
                      "held_goal": restored["held_goal"]})
        if lost is not None:
            self._events.publish(
                "safety.fleet_lost", severity="warning", source="fleet_loss_monitor",
                data={"policy": lost["policy"], "applied": lost["applied"],
                      "activity": lost["activity"], "correlation_id": lost["correlation_id"],
                      "goal": lost["goal"], "disconnected_s": lost["disconnected_s"],
                      "reason": lost["reason"]})

    def _tick_locked(self) -> tuple[Optional[dict], Optional[dict]]:
        now = self.clock()
        if not self._configured() and self._down_since is None:
            # Never configured. A link that was configured and then stopped mid-outage
            # keeps counting as lost (D-419 review I1), so only an idle monitor resets.
            self._reset()
            return None, None
        if self._configured() and self._link_up(now):
            restored = None
            if self._applied is not None:
                restored = {"applied": self._applied, "correlation_id": self._at_loss[0],
                            "disconnected_s": round(now - self._down_since, 2),
                            "held_goal": self._held}
            self._reset()
            return None, restored
        if self._down_since is None:
            # The outage is measured from the last hub message when there is one: a link
            # that flaps open without fresh hub traffic must not restart the timer (I2).
            last_rx = self._last_rx()
            self._down_since = last_rx if last_rx is not None and last_rx <= now else now
            self._at_loss = self._fleet_goal()
        if self._applied is not None or self._at_loss is None:
            return None, None
        current = self._fleet_goal()
        if current is None or current[0] != self._at_loss[0]:
            # 끊긴 사이 목표가 끝났거나 바뀌었다 — 이 상실에서 지킬 활동이 없다.
            self._at_loss = None
            return None, None
        if now - self._down_since >= self.timeout_s:
            return self._apply(now), None
        return None, None

    def _apply(self, now: float) -> dict:
        # Runs under self._lock. Safe: the actions take the navigation lock and the
        # localization gate, and nothing holding either ever calls into this monitor
        # (status() is read only by the API worker, which holds neither). tick() itself is
        # serial (one bridge timer), so deciding and acting together keeps one apply per
        # outage without a PENDING state that status() would have to expose.
        raw = self._policy()
        policy, known = normalize_policy(raw)
        correlation_id, spec = self._at_loss
        applied, reason = policy, None if known else "unknown_policy"
        try:
            if policy != "CONTINUE" and not self._stop_goal(correlation_id):
                # The goal ended or was replaced between the check and the cancel:
                # nothing of ours is running, so no home drive and no HOLD record (I3).
                applied, reason = "NONE", "goal_changed"
            elif policy == "HOLD":
                self._held = {"correlation_id": correlation_id,
                              "x": spec.x, "y": spec.y, "yaw": spec.yaw}
            elif policy == "RETURN_HOME":
                try:
                    self._return_home()
                except Exception as exc:
                    applied, reason = "STOP", f"home_unavailable: {exc}"
        except Exception as exc:
            logger.exception("SAF-003 policy %s failed", policy)
            applied, reason = "NONE", f"action_failed: {exc}"
        self._applied = applied
        if reason is not None:
            logger.warning("SAF-003 Fleet link lost: policy %s applied %s (%s)",
                           raw, applied, reason)
        return {"policy": str(raw), "applied": applied, "activity": "navigation",
                "correlation_id": correlation_id,
                "goal": {"x": spec.x, "y": spec.y, "yaw": spec.yaw},
                "disconnected_s": round(now - self._down_since, 2), "reason": reason}

    def status(self) -> dict:
        """`GET /safety/state` 의 `fleet_link` 블록 — tick 과 같은 락 아래 한 스냅샷."""
        with self._lock:
            now = self.clock()
            lost = self._applied is not None
            configured = bool(self._configured())
            return {
                "configured": configured,
                "connected": self._link_up(now) if configured else False,
                "lost": lost,
                "timeout_s": self.timeout_s,
                "applied": self._applied,
                "correlation_id": self._at_loss[0] if lost else None,
                "disconnected_s": (round(now - self._down_since, 2)
                                   if self._down_since is not None else None),
                "held_goal": self._held,
            }
