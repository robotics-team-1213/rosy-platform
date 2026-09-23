"""core.safety — SAF-001~005 (P1-6, P1-20). ROS 무의존."""

from __future__ import annotations

import time
import math
import os
from dataclasses import dataclass, replace
from typing import Callable, Optional

from core_common.protocol.detections import DETECTION_MAX_AGE_S, DetectionEvidence


def finite_velocity(linear: float, angular: float) -> bool:
    return all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in (linear, angular))


class TeleopWatchdog:
    """SAF-002: 마지막 teleop 명령 시각 추적, timeout 경과 시 만료."""

    def __init__(self, timeout_ms: int = 500) -> None:
        self.timeout_ms = timeout_ms
        self._last_refresh: float = 0.0

    def refresh(self, now: Optional[float] = None) -> None:
        self._last_refresh = now if now is not None else time.monotonic()

    def expired(self, now: Optional[float] = None) -> bool:
        current = now if now is not None else time.monotonic()
        return (current - self._last_refresh) * 1000.0 > self.timeout_ms


@dataclass
class SpeedLimits:
    max_linear: float = 0.20
    max_angular: float = 0.80
    manual_linear: float = 0.15
    manual_angular: float = 0.60
    fleet_linear: float = 0.20
    fleet_angular: float = 0.80

    @classmethod
    def from_config(cls, *, profile, nav_cfg: dict, safety_cfg: dict) -> "SpeedLimits":
        """프로필이 있으면 그걸 쓰고, 없으면 rosy.yaml navigation/safety 폴백."""
        nav_cfg = nav_cfg or {}
        safety_cfg = safety_cfg or {}
        max_linear = float(profile.max_linear_velocity or nav_cfg.get("max_linear_velocity") or cls.max_linear)
        max_angular = float(profile.max_angular_velocity or nav_cfg.get("max_angular_velocity") or cls.max_angular)
        return cls(
            max_linear=max_linear,
            max_angular=max_angular,
            manual_linear=float(safety_cfg.get("manual_linear", cls.manual_linear)),
            manual_angular=float(safety_cfg.get("manual_angular", cls.manual_angular)),
            fleet_linear=float(safety_cfg.get("fleet_linear", max_linear)),
            fleet_angular=float(safety_cfg.get("fleet_angular", max_angular)),
        )


@dataclass
class BatteryPolicy:
    warning_percent: float = 20.0
    critical_percent: float = 10.0
    critical_action: str = "RETURN_HOME"


@dataclass(frozen=True)
class SafetyRequest:
    command_id: int
    source: str
    calibration_revision: str
    now: float
    linear: float
    angular: float


@dataclass(frozen=True)
class SafetyDecision:
    command_id: int
    source: str
    calibration_revision: str
    observed_at: float
    expires_at: float
    linear_limit: float
    angular_limit: float
    disposition: str = 'allow'
    reason: str = ''


@dataclass(frozen=True)
class PersonAdvisory:
    """SAF-006: YOLO `person` 분류 자문. metric 정지의 확대 사유이며 단독
    정지 사유가 아니다 — 못 보면 기존 정지가 그대로고, 사라지면 해제된다."""

    present: bool
    confidence: float
    observed_at: float
    max_age_s: float = 1.0

    def __post_init__(self) -> None:
        if type(self.present) is not bool:
            raise ValueError("person present must be a boolean")
        if (not isinstance(self.confidence, (int, float))
                or isinstance(self.confidence, bool)
                or not 0.0 <= self.confidence <= 1.0):
            raise ValueError("person confidence must be in [0, 1]")
        if not isinstance(self.observed_at, (int, float)) or not math.isfinite(self.observed_at):
            raise ValueError("person observed_at must be finite")
        if (not isinstance(self.max_age_s, (int, float))
                or isinstance(self.max_age_s, bool)
                or not math.isfinite(self.max_age_s) or not self.max_age_s > 0):
            raise ValueError("person max_age_s must be positive")

    def fresh(self, now: float) -> bool:
        return bool(self.present) and self.observed_at <= now <= self.observed_at + self.max_age_s


#: SAF-006 사람 감속 상한. 사람이 있으면 전진 속도를 기어가기로 묶는다.
#: 선회율은 손대지 않는다 — 위험은 접근 속도지 제자리 회전이 아니다.
PERSON_LINEAR_CAP_M_S = 0.05


@dataclass(frozen=True)
class ModelSpec:
    """Known model revision: weights identity plus the input geometry the
    revision was commissioned with. A revision names the whole contract —
    weights alone do not (D-47 pattern)."""

    revision: str
    input_width: int
    input_height: int
    input_fps: float


class ModelRegistry:
    """D-137 T3: 아는 revision만 통과시키는 명부. 비어 있으면 아무것도 모른다 —
    fail-closed가 기본값이다. 누가 등록하는지는 vision 슬라이스 몫이며, 이
    명부는 판단만 한다."""

    def __init__(self) -> None:
        self._known: dict[str, ModelSpec] = {}

    def register(self, revision: str, *, input_width: int,
                 input_height: int, input_fps: float) -> ModelSpec:
        if not revision or not revision.strip():
            raise ValueError("model revision required")
        for name, value in (("input_width", input_width),
                            ("input_height", input_height),
                            ("input_fps", input_fps)):
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or not value > 0):
                raise ValueError(f"model {name} must be positive")
        spec = ModelSpec(revision=revision, input_width=int(input_width),
                         input_height=int(input_height), input_fps=float(input_fps))
        self._known[revision] = spec
        return spec

    def is_known(self, evidence: DetectionEvidence) -> bool:
        spec = self._known.get(evidence.model_revision)
        if spec is None:
            return False
        return (evidence.input_width == spec.input_width
                and evidence.input_height == spec.input_height
                and evidence.input_fps == spec.input_fps)


def person_advisory_from(evidence: DetectionEvidence, now: float, *,
                         label: str = "person", min_confidence: float = 0.5,
                         max_age_s: float = 1.0,
                         registry: Optional[ModelRegistry] = None) -> Optional[PersonAdvisory]:
    """D-137 T2→SAF-006 주입 고리. 신선한 라벨 검출만 자문이 된다.

    stale evidence·빈 detections·낮은 confidence는 전부 None이다 — 자문 없음이
    곧 프로필 복귀다. `registry`가 있으면 아는 revision+입력 제원만 통과한다.
    revision 게이트를 거는 주체는 vision 슬라이스이며, 여기서는 판단만 한다."""
    if registry is not None and not registry.is_known(evidence):
        return None
    persons = evidence.of_label(label, min_confidence)
    if not persons or not evidence.fresh(now, DETECTION_MAX_AGE_S):
        return None
    best = max(persons, key=lambda candidate: candidate.confidence)
    return PersonAdvisory(present=True, confidence=best.confidence,
                          observed_at=evidence.observed_at, max_age_s=max_age_s)


class PersonAdvisoryFeed:
    """와이어 패킷 → 자문 좌석의 유일한 유입점. D-137 T4 주입 시임.

    ROS 구독자(rosy-vision 착지 시 core.bridge가 연결)는 와이어 JSON을 이
    피드에만 넣는다. 검증 실패·stale·seq 점프("못 본 것")·자문 없음은 전부
    자문 해제로 끝난다 — 못 본 것으로 상한을 유지하는 쪽이 자문의 방향이
    아니다(상한은 낮춤일 뿐이고, metric 정지는 여기와 무관하다). e-stop은
    절대 건드리지 않는다(D-137 §5)."""

    def __init__(self, safety: SafetyManager, registry: Optional[ModelRegistry] = None,
                 clock: Optional[Callable[[], float]] = None,
                 seat_clock: Optional[Callable[[], float]] = None) -> None:
        if not isinstance(safety, SafetyManager):
            raise ValueError("advisory feed requires a SafetyManager")
        if registry is not None and not isinstance(registry, ModelRegistry):
            raise ValueError("registry must be a ModelRegistry or None")
        self._safety = safety
        self._registry = registry
        #: 패킷 시계 — ROS 구독자는 노드 시계(epoch)를 꽂는다.
        self._clock = clock if clock is not None else time.monotonic
        #: 자문 좌석의 시계 — SafetyManager.clip이 판정에 쓰는 기준(monotonic).
        self._seat_clock = seat_clock if seat_clock is not None else time.monotonic

    def bind_clock(self, clock: Callable[[], float]) -> None:
        """패킷 타임스탬프와 같은 시간 기준으로 시계를 맞춘다.

        ROS 구독자는 노드 시계(epoch)를 꽂는다 — monotonic 기준과 섞이면
        observed_at의 기준이 어긋나 모든 패킷이 영원히 stale이 된다."""
        if not callable(clock):
            raise ValueError("advisory feed clock must be callable")
        self._clock = clock

    def ingest(self, packet: dict) -> dict:
        """One wire packet in, one advisory verdict out: {'advisory': bool, 'reason': str}."""
        if not isinstance(packet, dict):
            return self._clear('invalid_packet')
        try:
            evidence = DetectionEvidence.model_validate(packet)
            packet_now = self._clock()
            advisory = person_advisory_from(evidence, packet_now,
                                            registry=self._registry)
        except Exception:
            # 검증 텍스트에는 경로·시크릿이 섞일 수 있다 — 밖으로는 사유만.
            # 구독자 콜백이 죽으면 그 뒤의 metric 경로까지 같이 흔들린다.
            return self._clear('invalid_packet')
        if advisory is None:
            return self._clear('no_fresh_advisory')
        # TrackedEvidence 패턴: 패킷 시계 기준의 나이만 좌석 시계로 옮긴다.
        # stamp를 그대로 두면 clip의 monotonic now와 기준이 어긋나 자문이 한
        # 번도 살지 못한다 — WSL 그래프 시험이 잡은 실결함이다.
        age = max(0.0, packet_now - evidence.observed_at)
        advisory = replace(advisory, observed_at=self._seat_clock() - age)
        self._safety.set_person_advisory(advisory)
        return {'advisory': True, 'reason': 'person_advisory_set'}

    def _clear(self, reason: str) -> dict:
        self._safety.set_person_advisory(None)
        return {'advisory': False, 'reason': reason}


class SafetyManager:
    """E-Stop(SAF-001)·속도 제한(SAF-004)·배터리 정책(SAF-005)·Fleet 단절 정책(SAF-003)."""

    def __init__(self, limits: SpeedLimits, battery: BatteryPolicy,
                 fleet_loss_policy: str = "STOP", events=None, policy_required: bool = False) -> None:
        if type(policy_required) is not bool:
            raise ValueError('control_policy_required must be a boolean')
        self.policy_required = policy_required
        self._policy = None
        self._policy_revision = ''
        self._policy_clock = time.monotonic
        self.policy_reason = ''
        self._actuation = None
        self._actuation_required = False
        self._simulation_clock_enabled = None
        self.limits = limits
        self.battery_policy = battery
        self.fleet_loss_policy = fleet_loss_policy
        self._events = events
        self.estop: bool = False
        self.estop_source: str = ""
        self._battery_state: str = "ok"
        #: 한 활동이 자기 구간 동안만 더 낮춰 쓰는 상한 (SWM-002 max_speed).
        #: 프로필 상한을 넘겨 올릴 수는 없다 — clip 이 둘 중 작은 값을 쓴다.
        self._session_linear: Optional[float] = None
        #: SAF-006 사람 자문. None 이면 사람이 없다는 뜻이 아니라 자문이 없다는
        #: 뜻이다 — metric 정지는 그대로고 상한만 프로필로 돌아간다.
        self._person: Optional[PersonAdvisory] = None
        #: 사람 감속 상한. 낮추기만 하는 값이라 올리는 세터는 없다.
        self.person_linear_cap: float = PERSON_LINEAR_CAP_M_S
        #: E-Stop 이 실제로 걸릴 때 한 번 불린다. API·배터리·어느 경로로
        #: 들어오든 같은 자리를 지나므로, 중단해야 할 활동은 여기에 붙는다.
        self.estop_listeners: list = []
        self.policy_listeners: list = []

    def bind_policy(self, evaluator, calibration_revision: str) -> None:
        """Bind a bounded, synchronous in-process evaluator; no ROS transport."""
        if not callable(evaluator) or not isinstance(calibration_revision, str) or not calibration_revision:
            raise ValueError('A policy evaluator and calibration revision are required')
        self._policy = evaluator
        self._policy_revision = calibration_revision
        self._actuation = None
        self.policy_required = True
        for listener in list(self.policy_listeners):
            listener()

    def bind_control_policy(self, policy) -> None:
        """Consume absorbed Control decisions without importing ROS or publishing."""
        evaluate = getattr(policy, "evaluate", None)
        revision = getattr(policy, "revision", None)
        if not callable(evaluate) or not isinstance(revision, str) or not revision:
            raise ValueError('A Control CommandPolicy is required')

        def _evaluate(request):
            bounded = (self._actuation_required and self._actuation is not None and
                       self._actuation.revision == request.calibration_revision and self._simulation_actuation_enabled())
            output = evaluate(request.linear, request.angular, request.now, allow_bounded_sweep=bounded)
            if output is None:
                raise ValueError('Control observation unavailable')
            snapshot, result = output
            disposition = ('limit' if result.reason in ('allow', 'motion_limited', 'trajectory_changed',
                           'adaptive_speed_limit', 'obstacle_replan', 'obstacle_wait',
                           'camera_obstacle_unranged')
                           else 'stop')
            return SafetyDecision(request.command_id, request.source, snapshot.calibration_revision,
                                  snapshot.observed_at, snapshot.expires_at,
                                  abs(result.linear), abs(result.angular), disposition, result.reason)

        self.bind_policy(_evaluate, revision)

    def _simulation_actuation_enabled(self):
        # The partition name and domain number live in the sim profile (D-182).
        return (os.environ.get('ROSY_SIMULATION_ACTUATION') == '1' and
                self._simulation_clock_enabled is not None and self._simulation_clock_enabled() is True)

    def bind_simulation_actuation(self, calibration, *, simulation_clock_enabled):
        """Opt-in only when the sim profile has enabled actuation, never hardware."""
        revision = getattr(calibration, "revision", None)
        if (revision != self._policy_revision or not callable(simulation_clock_enabled)):
            raise ValueError('Actuation requires the bound policy revision and simulation clock')
        if os.environ.get('ROSY_SIMULATION_ACTUATION') != '1' or simulation_clock_enabled() is not True:
            raise ValueError('Actuation is restricted to the commissioned simulation domain')
        self._simulation_clock_enabled = simulation_clock_enabled
        self._actuation = calibration
        self._actuation_required = True
        self.policy_required = True
        for listener in list(self.policy_listeners):
            listener()

    def evaluate_candidate(self, command_id: int, source: str, linear: float,
                           angular: float, now: float, scope: str = 'nav') -> Optional[tuple[float, float]]:
        if not self.policy_required:
            return linear, angular
        self.policy_reason = 'policy_unavailable'
        evaluator, revision = self._policy, self._policy_revision
        if evaluator is None:
            return None
        request = SafetyRequest(command_id, source, revision, now, linear, angular)
        started = self._policy_clock()
        try:
            decision = evaluator(request)
            elapsed = self._policy_clock() - started
        except Exception:
            self.policy_reason = 'policy_failed'
            return None
        self.policy_reason = 'policy_invalid'
        if (not isinstance(decision, SafetyDecision) or evaluator is not self._policy
                or revision != self._policy_revision or not math.isfinite(elapsed) or not 0 <= elapsed <= .01):
            return None
        if (type(decision.command_id) is not int or decision.command_id != command_id
                or not isinstance(decision.source, str) or decision.source != source
                or not isinstance(decision.calibration_revision, str) or decision.calibration_revision != revision
                or not finite_velocity(decision.observed_at, decision.expires_at)
                or not decision.observed_at <= now <= now + elapsed <= decision.expires_at
                or not 0 < decision.expires_at - decision.observed_at <= .5
                or not finite_velocity(decision.linear_limit, decision.angular_limit)
                or min(decision.linear_limit, decision.angular_limit) < 0
                or not isinstance(decision.disposition, str) or decision.disposition not in ('allow', 'limit', 'stop')
                or not isinstance(decision.reason, str) or len(decision.reason) > 128):
            return None
        if decision.disposition == 'stop':
            self.policy_reason = decision.reason or 'policy_stop'
            return None
        self.policy_reason = ''
        limited = (max(-decision.linear_limit, min(decision.linear_limit, linear)),
                   max(-decision.angular_limit, min(decision.angular_limit, angular)))
        if not self._actuation_required or limited == (0., 0.):
            return limited
        self.policy_reason = 'actuation_unavailable'
        calibration = self._actuation
        try:
            if calibration is None or calibration.revision != revision or not self._simulation_actuation_enabled():
                return None
            caps = self.clip(self.limits.max_linear, self.limits.max_angular, scope)
            self.policy_reason = 'actuation_invalid'
            prepared = calibration.prepare(*limited, angular, now, caps)
            if (not finite_velocity(prepared.motor_linear, prepared.angular) or
                    not finite_velocity(prepared.linear, prepared.angular) or
                    abs(prepared.motor_linear) != abs(prepared.linear) or
                    abs(prepared.linear) > min(.014, caps[0]) or abs(prepared.angular) > min(.1, caps[1]) or
                    caps != self.clip(self.limits.max_linear, self.limits.max_angular, scope) or
                    not self._simulation_actuation_enabled()):
                return None
            elapsed = self._policy_clock() - started
            self.policy_reason = 'actuation_stale_or_over_budget'
            if (calibration is not self._actuation or evaluator is not self._policy or
                    not 0 <= elapsed <= .01 or now + elapsed > min(calibration.expires_at, decision.expires_at,
                        calibration.scan_received_at + .2, calibration.scan_source_at + .2)):
                return None
        except Exception:
            return None
        self.policy_reason = ''
        return prepared.motor_linear, prepared.angular

    def _emit(self, type_: str, severity: str, source: str, data: dict | None = None) -> None:
        if self._events is not None:
            self._events.publish(type_, severity=severity, source=source, data=data or {})

    def trigger_estop(self, source: str) -> bool:
        if self.estop:
            return False
        self.estop = True
        self.estop_source = source
        self._emit("safety.estop", "critical", source, {"source": source})
        for listener in list(self.estop_listeners):
            try:
                listener()
            except Exception:
                # 한 구독자의 실패가 E-Stop 경로를 막으면 안 된다.
                pass
        return True

    def release(self, by: str) -> bool:
        if not self.estop:
            return False
        self.estop = False
        self.estop_source = ""
        self._emit("safety.estop_released", "warning", "safety_manager", {"by": by})
        return True

    def set_session_speed(self, max_linear: Optional[float]) -> None:
        """활동 구간용 추가 상한. `None` 이면 해제하고 프로필 상한으로 돌아간다.

        SWM-002 의 `max_speed` 가 여기로 들어온다. 검증만 하고 흘려보내면
        계약이 거짓이 되고, Nav2 파라미터로 내려보내려면 CORE 에 없는 파라미터
        클라이언트가 필요하다. cmd_vel 이 어차피 전부 `clip` 을 지나므로
        (D-2), 실제로 바퀴에 닿는 값을 여기서 줄인다.
        """
        value = None if max_linear is None else float(max_linear)
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError('Session speed limit must be finite and nonnegative')
        self._session_linear = value

    @property
    def session_linear(self) -> Optional[float]:
        return self._session_linear

    def set_person_advisory(self, advisory: Optional[PersonAdvisory]) -> None:
        """SAF-006: 사람 자문을 건다/뗀다. 뗀다고 정지가 풀리는 게 아니라
        상한이 프로필로 돌아갈 뿐이다 — metric 정지는 이 함수가 모른다."""
        if advisory is not None and not isinstance(advisory, PersonAdvisory):
            raise ValueError("person advisory must be a PersonAdvisory or None")
        self._person = advisory

    def clip(self, linear: float, angular: float, scope: str = "nav",
             now: Optional[float] = None) -> tuple[float, float]:
        if not finite_velocity(linear, angular):
            return 0.0, 0.0
        if scope == "manual":
            max_l, max_a = self.limits.manual_linear, self.limits.manual_angular
        elif scope == "fleet":
            max_l, max_a = self.limits.fleet_linear, self.limits.fleet_angular
        else:
            max_l, max_a = self.limits.max_linear, self.limits.max_angular
        if (not finite_velocity(max_l, max_a)
                or not finite_velocity(self.limits.max_linear, self.limits.max_angular)
                or min(max_l, max_a, self.limits.max_linear, self.limits.max_angular) < 0):
            return 0.0, 0.0
        max_l = min(max_l, self.limits.max_linear)
        max_a = min(max_a, self.limits.max_angular)
        if self._session_linear is not None:
            # 낮추기만 한다. 활동이 프로필 상한을 넘겨 달릴 수는 없다.
            max_l = min(max_l, self._session_linear)
        person = self._person
        if person is not None:
            current = now if now is not None else time.monotonic()
            if person.fresh(current):
                # SAF-006: 사람이 있으면 기어가기. 못 보면 이 줄이 없고,
                # 사라지면 자문이 떼어져서 프로필로 돌아간다.
                max_l = min(max_l, self.person_linear_cap)
        l = max(-max_l, min(max_l, linear))
        a = max(-max_a, min(max_a, angular))
        return l, a

    def on_battery_percent(self, percent: float) -> Optional[str]:
        """SAF-005: 임계 통과 시 정책 반환. None|'warn'|'critical'."""
        policy = self.battery_policy
        if percent <= policy.critical_percent:
            state = "critical"
            action = policy.critical_action
        elif percent <= policy.warning_percent:
            state = "warn"
            action = "warn"
        else:
            state, action = "ok", None
        crossed = state != self._battery_state and state != "ok"
        self._battery_state = state
        if crossed:
            if state == "critical":
                self._emit("battery.critical", "critical", "safety_manager",
                           {"percent": percent, "policy": action})
            else:
                self._emit("battery.low", "warning", "safety_manager", {"percent": percent})
        return action if crossed else None
