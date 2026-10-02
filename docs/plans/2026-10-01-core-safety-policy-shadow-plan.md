# CORE 안전 정책 그림자 모드 — 구현 계획 1 (호스트 검증 범위)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `control.sensor_adapter.mode: off | shadow | enforce`를 도입하고, 그림자 모드에서 안전 정책 판정을 출력에 손대지 않고 기록·노출한다. 파라미터는 CORE가 이미 가진 출처(LiDAR 정면 해석, 속도 상한, 운영자 overlay)에서 만든다.

**Architecture:** 판정 검증 규칙을 `evaluate_candidate`에서 순수 함수로 떼어 내 집행과 그림자가 같은 규칙을 쓴다. 그림자 집계는 ROS-free `core_features/safety/shadow.py`, 파라미터 해석은 `core/safety_params.py`(`lidar_mount.py` 옆), 모드별 바인딩과 "그림자 구성 실패 → off"는 어댑터 모듈이 맡는다. `node.py`는 조립만 한다. 이벤트는 기존 SAF-002 패턴대로 `announce_pending`(바퀴에 정지가 나간 뒤)에서만 낸다.

**Tech Stack:** Python 3.12, pytest(호스트, ROS 없음), pydantic(`StateSnapshot`), PyYAML.

- 설계: [2026-10-01-core-safety-policy-shadow-design.md](2026-10-01-core-safety-policy-shadow-design.md), ADR [D-400](../adr/D-400-core-safety-policy-off-shadow-enforce.md)
- 브랜치: `docs/core-safety-policy-shadow` (worktree `.worktrees/safety-shadow`). 구현은 같은 브랜치에서 이어 간다. main 합류는 `rosy-land-on-main` 스킬 절차.

---

## 범위

이 계획(1)이 하는 것: 설계 3.1(모드), 3.2(그림자 경로·이벤트·상태 — ROS 토픽 제외), 3.3 중 LiDAR·봉투·overlay, 3.5의 1·2·4(대시보드 제외).

다음 계획으로 넘기는 것과 이유:

| 항목 | 넘기는 곳 | 이유 |
|---|---|---|
| ROS `safety/shadow` 토픽, 워커 이름 `core_safety_worker`, Gazebo 그림자 프로필, LiDAR 180° 랩 재실행 | 계획 2 (ROS-SIM) | `ros_bridge.py`·ROS 그래프는 호스트 pytest가 못 닿는다. 같은 회차에 Gazebo로 확인한다 |
| 대시보드 장치 카드의 `safety_policy` 표시 | 계획 2 | 이 계획의 상태 필드가 생긴 뒤 브라우저 시험과 함께 |
| `calib_node` 레코드 로더 코드 삭제 | 계획 2 | 이 계획은 설정의 `calibration` 블록을 **무시**만 한다(경고). 로더 삭제는 sensing provider 변경과 같이 |
| D-66 이미지 개정(control 슬라이스) | 계획 2 | `test_core_image_closure.py`·Dockerfile, ARM64 CI |
| 보정 저장소 새 종류(`imu_zero`·`cliff_ir`·`motion_sign`), 집행 HOLD/래치 경계(3.4), `safety.policy_hold` | 계획 3 (집행) | G-enforce 조건. 그림자에는 필요 없다 |

## 구조 규칙 (이 계획의 모든 태스크에 적용)

이 저장소의 시험이 강제하는 규칙이다. 어기면 아키텍처 시험이 실패한다.

1. **import 방향** — `core_common ← core_events ← core_features ← core_api_web ← core`. `core_features`(`src/runtime/services`)는 `core`를 import하지 않는다. `core`는 `control`·`pinky_pro`를 정적으로 import하지 않는다(P3/P4, `test/architecture/test_module_structure.py`).
2. **시험 위치(D-184)** — `core_features`를 import하는 **새** 시험 파일은 `src/runtime/services/test/`에만 둔다. `src/runtime/gateway/test/`에는 `from core_features`로 시작하는 새 시험 파일을 만들지 않는다(`test/test_behavior_test_ownership.py`).
3. **크기 예산(P6)** — 파일당 600줄. `src/runtime/gateway/core/services.py`(593줄)는 **고치지 않는다**. `core_common/protocol/schemas.py`는 증가 금지 구간이라 고치면 `SIZE_VERDICTS`의 줄 수를 다시 적는다(Task 8).
4. **C6** — `src/runtime/gateway/core/` 안에 새 `getattr`/`hasattr`를 쓰지 않는다(`test_module_criteria.py`).
5. **이벤트(§8)** — 이벤트 이름은 발행 지점에서 문자열 리터럴. 새 이벤트마다 API Ref §8에 행을 더한다(`test_event_catalogue.py`).
6. **이벤트는 바퀴 뒤** — `select_output` 안에서 `events.publish`를 부르지 않는다. 기록만 하고 `announce_pending`에서 낸다(`bridge/cmd_vel.py` 주석, SAF-002).
7. **명령어** — Windows에서는 `python`(`python3` 아님). 실패 비교는 `test/known_failures.py`.

## 파일 구조

| 파일 | 상태 | 책임 |
|---|---|---|
| `src/runtime/gateway/core/bridge/control_sensor_adapter.py` | 수정 | `mode`·`stale_hold_s` 파싱, 모드별 `bind_safety`, `build_control_adapter`(그림자 구성 실패 → off, `calibration` 블록 무시) |
| `src/runtime/gateway/core/safety_params.py` | 생성 | 워커 파라미터 해석: LiDAR(라인 추종과 같은 값), 봉투(CORE 속도 상한), overlay 허용 목록, 출처, revision |
| `src/runtime/gateway/core/node.py` | 수정 | 순서 재배치(LiDAR → 파라미터 → 어댑터 → 바인딩 → 상태 공급자), 환경변수 data_root 코드 삭제 |
| `src/runtime/services/core_features/safety/manager.py` | 수정 | `check_decision` 추출, `_control_evaluator` 추출, 그림자 바인딩·평가, `policy_mode` |
| `src/runtime/services/core_features/safety/shadow.py` | 생성 | `ShadowVerdict`, `ShadowLog`(카운터·전이 이벤트·1 Hz 묶음·eval_ms 분위수) |
| `src/runtime/services/core_features/command/manager.py` | 수정 | `_policy_output`에서 그림자 관찰, `announce_pending`에서 그림자·`policy_off` 이벤트 |
| `src/runtime/services/core_features/state/manager.py` | 수정 | `set_safety_policy_provider` |
| `src/contracts/foundation/core_common/protocol/schemas.py` | 수정 | `SafetyPolicyStatus` 모델, `StateSnapshot.safety_policy` |
| `src/contracts/foundation/config/rosy_default.yaml` | 수정 | `mode: "off"`, `stale_hold_s`, 주석 (superseded — see 실행 중 변경 기록) |
| `docs/reference/ROSY API & Protocol Reference.md` | 수정 | v1.69: §6.1 필드, §8 이벤트 2개, §11 행 (superseded — see 실행 중 변경 기록) |
| 시험 | 생성/수정 | 각 태스크에 적음 |

---

### Task 1: 설정 — `mode`와 `stale_hold_s`

**Files:**
- Modify: `src/runtime/gateway/core/bridge/control_sensor_adapter.py:34-108`
- Modify: `src/contracts/foundation/config/rosy_default.yaml:33-44`
- Modify: `src/runtime/gateway/test/test_runtime_config.py:26-35`
- Test: `src/runtime/gateway/test/test_control_sensor_adapter.py` (기존 파일에 추가)

YAML 1.1에서 따옴표 없는 `off`는 `False`가 된다. 그래서 설정 파일은 `mode: "off"`로 쓰고, 파서는 문자열이 아니면 "따옴표를 쓰라"는 메시지로 거부한다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_control_sensor_adapter.py` 끝에 추가:

```python
@pytest.mark.parametrize("raw, mode, enabled", [
    ({}, "off", False),
    ({"mode": "off"}, "off", False),
    ({"mode": "shadow"}, "shadow", True),
    ({"mode": "enforce"}, "enforce", True),
    ({"enabled": True}, "enforce", True),
    ({"enabled": False}, "off", False),
])
def test_mode_parsing_and_enabled_compat(raw, mode, enabled):
    config = ControlSensorConfig.from_mapping(raw)

    assert config.mode == mode
    assert config.enabled is enabled


@pytest.mark.parametrize("raw, message", [
    ({"mode": False}, "quote"),            # YAML 1.1 reads bare off as False
    ({"mode": "on"}, "off, shadow or enforce"),
    ({"mode": "shadow", "enabled": True}, "not both"),
    ({"mode": "shadow", "stale_hold_s": 0}, "stale_hold_s"),
    ({"mode": "shadow", "stale_hold_s": 5.5}, "stale_hold_s"),
    ({"mode": "shadow", "stale_hold_s": True}, "stale_hold_s"),
])
def test_mode_and_stale_hold_reject_invalid_values(raw, message):
    with pytest.raises(ValueError, match=message):
        ControlSensorConfig.from_mapping(raw)


def test_stale_hold_defaults_to_two_seconds():
    assert ControlSensorConfig.from_mapping({"mode": "shadow"}).stale_hold_s == 2.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/gateway/test/test_control_sensor_adapter.py -q -k "mode or stale_hold"`
Expected: FAIL — `AttributeError: 'ControlSensorConfig' object has no attribute 'mode'`

- [ ] **Step 3: 구현** — `ControlSensorConfig`에 필드 두 개를 더하고 `from_mapping`의 `enabled` 처리 부분을 바꾼다.

`_DEFAULT_REQUIRED` 아래에 상수:

```python
_MODES = ("off", "shadow", "enforce")
_DEFAULT_STALE_HOLD_S = 2.0
```

dataclass 필드(`enabled` 위):

```python
    mode: str = "off"
    enabled: bool = False
    stale_hold_s: float = _DEFAULT_STALE_HOLD_S
```

`from_mapping`의 `enabled = raw.get("enabled", False)` 두 줄을 다음으로 바꾼다:

```python
        mode = _parse_mode(raw)
        enabled = mode != "off"

        stale_hold_s = raw.get("stale_hold_s", _DEFAULT_STALE_HOLD_S)
        if (type(stale_hold_s) not in (int, float) or not math.isfinite(float(stale_hold_s)) or
                not 0.0 < float(stale_hold_s) <= 5.0):
            raise ValueError("control sensor adapter stale_hold_s must be in (0, 5]")
```

반환문:

```python
        return cls(mode=mode, enabled=enabled, stale_hold_s=float(stale_hold_s),
                   required=required, max_age=float(max_age),
                   parameters=parameters, calibration=calibration)
```

모듈 함수(클래스 위):

```python
def _parse_mode(raw: Mapping[str, Any]) -> str:
    """D-400: mode off | shadow | enforce; the legacy enabled bool maps to enforce/off."""
    if "mode" in raw and "enabled" in raw:
        raise ValueError("control sensor adapter takes mode or enabled, not both")
    if "mode" not in raw:
        enabled = raw.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("control sensor adapter enabled must be a boolean")
        return "enforce" if enabled else "off"
    mode = raw["mode"]
    if type(mode) is not str:
        raise ValueError('control sensor adapter mode must be a string; quote it in YAML ("off")')
    if mode not in _MODES:
        raise ValueError("control sensor adapter mode must be off, shadow or enforce")
    return mode
```

- [ ] **Step 4: 기본 설정과 그 시험 바꾸기** — `rosy_default.yaml`의 34–35행:

```yaml
  sensor_adapter:
    mode: "off"                   # D-400: off = no policy, CORE passes commands through
                                  # shadow = judge and record, never change cmd_vel
                                  # enforce = limit/stop by the policy. Quote "off" (YAML 1.1 bool)
    stale_hold_s: 2.0             # enforce: gaps shorter than this HOLD, longer latch (D-400 4)
```

`test_runtime_config.py:33`의 `assert sensor["enabled"] is False`를:

```python
    assert sensor["mode"] == "off"
    assert "enabled" not in sensor
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest src/runtime/gateway/test/test_control_sensor_adapter.py src/runtime/gateway/test/test_runtime_config.py -q`
Expected: PASS (기존 `{"enabled": True}` 시험들도 그대로 통과 — 하위 호환)

- [ ] **Step 6: 커밋**

```bash
git add src/runtime/gateway/core/bridge/control_sensor_adapter.py src/contracts/foundation/config/rosy_default.yaml src/runtime/gateway/test/test_runtime_config.py src/runtime/gateway/test/test_control_sensor_adapter.py
git commit -m "feat(core): sensor adapter mode off/shadow/enforce and stale_hold_s (D-400 1)"
```

---

### Task 2: 판정 검증을 순수 함수로 — 동작 불변 리팩터

**Files:**
- Modify: `src/runtime/services/core_features/safety/manager.py:292-369`
- Create: `src/runtime/services/test/test_safety_decision_check.py`

`evaluate_candidate`의 판정 검증(351–368행)을 `check_decision`으로 떼어 낸다. 그림자도 같은 함수로 판정해야 "집행했다면"이 정확하다. 이 태스크는 동작을 바꾸지 않는다 — 기존 시험이 그 증거다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/services/test/test_safety_decision_check.py`:

```python
"""D-400: one validation rule for enforce and shadow (check_decision)."""

from dataclasses import replace

import pytest

from core_features.safety.manager import SafetyDecision, SafetyRequest, check_decision

REQUEST = SafetyRequest(command_id=7, source="navigation", calibration_revision="rev",
                        now=10.0, linear=0.1, angular=0.2)
GOOD = SafetyDecision(7, "navigation", "rev", observed_at=9.9, expires_at=10.3,
                      linear_limit=0.05, angular_limit=0.5, disposition="limit", reason="motion_limited")


def test_valid_decision_has_no_reason():
    assert check_decision(GOOD, REQUEST, elapsed=0.001) == ""


@pytest.mark.parametrize("decision, elapsed", [
    ("not a decision", 0.001),
    (replace(GOOD, command_id=8), 0.001),
    (replace(GOOD, source="docking"), 0.001),
    (replace(GOOD, calibration_revision="other"), 0.001),
    (replace(GOOD, observed_at=10.1), 0.001),          # observed after now
    (replace(GOOD, expires_at=9.95), 0.001),           # already expired
    (replace(GOOD, expires_at=10.5), 0.001),           # lease longer than 0.5 s
    (replace(GOOD, linear_limit=-0.1), 0.001),
    (replace(GOOD, disposition="maybe"), 0.001),
    (replace(GOOD, reason="x" * 129), 0.001),
    (GOOD, 0.011),                                     # over the 10 ms budget
    (GOOD, float("nan")),
])
def test_invalid_decisions_are_policy_invalid(decision, elapsed):
    assert check_decision(decision, REQUEST, elapsed=elapsed) == "policy_invalid"


def test_stop_disposition_reports_its_reason():
    stop = replace(GOOD, disposition="stop", reason="pickup")
    assert check_decision(stop, REQUEST, elapsed=0.001) == "pickup"
    assert check_decision(replace(stop, reason=""), REQUEST, elapsed=0.001) == "policy_stop"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/services/test/test_safety_decision_check.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_decision'`

- [ ] **Step 3: 구현** — `SafetyDecision` 정의 아래(88행 뒤)에 모듈 함수를 둔다:

```python
_DISPOSITIONS = ('allow', 'limit', 'stop')


def check_decision(decision, request: SafetyRequest, elapsed: float) -> str:
    """'' when ``decision`` is a valid, current answer to ``request`` that permits motion;
    otherwise the policy_reason CORE reports. One rule for enforce and shadow (D-400)."""
    if (not isinstance(decision, SafetyDecision) or not math.isfinite(elapsed) or not 0 <= elapsed <= .01
            or type(decision.command_id) is not int or decision.command_id != request.command_id
            or not isinstance(decision.source, str) or decision.source != request.source
            or not isinstance(decision.calibration_revision, str)
            or decision.calibration_revision != request.calibration_revision
            or not finite_velocity(decision.observed_at, decision.expires_at)
            or not decision.observed_at <= request.now <= request.now + elapsed <= decision.expires_at
            or not 0 < decision.expires_at - decision.observed_at <= .5
            or not finite_velocity(decision.linear_limit, decision.angular_limit)
            or min(decision.linear_limit, decision.angular_limit) < 0
            or not isinstance(decision.disposition, str) or decision.disposition not in _DISPOSITIONS
            or not isinstance(decision.reason, str) or len(decision.reason) > 128):
        return 'policy_invalid'
    if decision.disposition == 'stop':
        return decision.reason or 'policy_stop'
    return ''
```

`evaluate_candidate`의 351–368행을 다음으로 바꾼다(`elapsed`와 평가자·revision 동일성 검사는 호출자에 남는다):

```python
        self.policy_reason = 'policy_invalid'
        if evaluator is not self._policy or revision != self._policy_revision:
            return None
        why = check_decision(decision, request, elapsed)
        if why:
            self.policy_reason = why
            return None
        self.policy_reason = ''
```

- [ ] **Step 4: 통과와 동작 불변 확인**

Run: `python -m pytest src/runtime/services/test/test_safety_decision_check.py src/runtime/gateway/test/test_control_policy_link.py src/runtime/gateway/test/test_control_absorption_safety.py src/runtime/gateway/test/test_core_logic.py src/runtime/gateway/test/test_absorption_command_validity.py -q`
Expected: PASS 전부(기존 시험 수정 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/services/core_features/safety/manager.py src/runtime/services/test/test_safety_decision_check.py
git commit -m "refactor(safety): extract check_decision so shadow and enforce share one rule (D-400)"
```

---

### Task 3: 그림자 집계 `ShadowLog`

**Files:**
- Create: `src/runtime/services/core_features/safety/shadow.py`
- Create: `src/runtime/services/test/test_safety_shadow_log.py`
- Modify: `src/runtime/services/core_features/safety/AGENTS.md` (Key Files 표에 한 행)

`safety/AGENTS.md`는 `manager.py` 확장을 권하지만, `manager.py`는 499줄이고 이 집계는 정책이 아니라 기록이라 역할이 다르다(분할 기준 C7: 한 필드가 두 요구 묶음에 걸치면 나눈다). 새 파일의 이유를 AGENTS.md에 적는다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/services/test/test_safety_shadow_log.py`:

```python
"""D-400 shadow verdict log: counters, transition events, 1 Hz repeat cap."""

from core_features.safety.shadow import ShadowLog, ShadowVerdict


def _v(t, verdict, reason="", eval_ms=1.0, source="navigation"):
    return ShadowVerdict(t=t, source=source, commanded=(0.1, 0.0), output=(0.1, 0.0),
                         verdict=verdict, limited=(0.0, 0.0) if verdict == "stop" else (0.1, 0.0),
                         reason=reason, eval_ms=eval_ms)


def test_counts_every_verdict_and_remembers_the_last_stop():
    log = ShadowLog()
    for v in (_v(1.0, "allow"), _v(1.1, "limit"), _v(1.2, "stop", "pickup"), _v(1.3, "unavailable", "policy_failed")):
        log.record(v)

    snap = log.snapshot()
    assert snap["counts"] == {"allow": 1, "limit": 1, "stop": 1, "unavailable": 1}
    assert snap["last_stop"] == {"t": 1.2, "reason": "pickup", "source": "navigation"}
    assert snap["last_unavailable"] == {"t": 1.3, "reason": "policy_failed", "source": "navigation"}


def test_events_on_transitions_only_and_repeats_at_most_once_per_second():
    log = ShadowLog()
    log.record(_v(0.00, "allow"))
    log.record(_v(0.02, "stop", "pickup"))     # transition -> event
    log.record(_v(0.04, "stop", "pickup"))     # repeat within 1 s -> none
    log.record(_v(1.10, "stop", "pickup"))     # repeat after 1 s -> event
    log.record(_v(1.12, "allow"))              # transition -> event

    events = log.drain()
    assert [e["verdict"] for e in events] == ["allow", "stop", "stop", "allow"]
    assert log.drain() == []                   # drained once


def test_eval_ms_percentiles_use_a_bounded_window():
    log = ShadowLog(window=4)
    for i, ms in enumerate([9.0, 9.0, 1.0, 2.0, 3.0, 4.0]):
        log.record(_v(float(i), "allow", eval_ms=ms))

    snap = log.snapshot()
    assert snap["eval_ms"] == {"p50": 3.0, "p99": 4.0, "n": 4}


def test_event_payload_is_flat_and_rounded():
    log = ShadowLog()
    log.record(ShadowVerdict(t=2.0, source="manual", commanded=(0.123456, -0.5), output=(0.123456, -0.5),
                             verdict="limit", limited=(0.0123456, -0.5), reason="motion_limited", eval_ms=0.4))

    (event,) = log.drain()
    assert event == {"verdict": "limit", "reason": "motion_limited", "source": "manual",
                     "commanded": [0.1235, -0.5], "limited": [0.0123, -0.5]}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/services/test/test_safety_shadow_log.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_features.safety.shadow'`

- [ ] **Step 3: 구현** — `src/runtime/services/core_features/safety/shadow.py`:

```python
"""D-400 shadow mode: record what the safety policy would have done. ROS-free.

The policy is evaluated on every non-zero candidate but never changes the
output, the e-stop or the mode. This module only keeps the record: counters,
the last stop/unavailable, eval-time percentiles, and the events to announce.
Events are queued here and drained by CommandManager.announce_pending, after
cmd_vel has reached the wheels (SAF-002 ordering).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

VERDICTS = ("allow", "limit", "stop", "unavailable")
_REPEAT_EVERY_S = 1.0


@dataclass(frozen=True)
class ShadowVerdict:
    t: float
    source: str
    commanded: tuple[float, float]
    output: tuple[float, float]
    verdict: str
    limited: tuple[float, float]
    reason: str
    eval_ms: float


def _pair(values: tuple[float, float]) -> list[float]:
    return [round(values[0], 4), round(values[1], 4)]


def _quantile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


class ShadowLog:
    def __init__(self, window: int = 512) -> None:
        self._counts = {name: 0 for name in VERDICTS}
        self._last: dict[str, dict] = {}
        self._eval_ms: deque[float] = deque(maxlen=window)
        self._pending: list[dict] = []
        self._state: str | None = None
        self._state_reason = ""
        self._emitted_at = float("-inf")

    def record(self, verdict: ShadowVerdict) -> None:
        self._counts[verdict.verdict] += 1
        self._eval_ms.append(verdict.eval_ms)
        if verdict.verdict in ("stop", "unavailable"):
            self._last[verdict.verdict] = {"t": verdict.t, "reason": verdict.reason, "source": verdict.source}
        changed = (verdict.verdict, verdict.reason) != (self._state, self._state_reason)
        if changed or verdict.t - self._emitted_at >= _REPEAT_EVERY_S:
            self._state, self._state_reason, self._emitted_at = verdict.verdict, verdict.reason, verdict.t
            self._pending.append({"verdict": verdict.verdict, "reason": verdict.reason,
                                  "source": verdict.source, "commanded": _pair(verdict.commanded),
                                  "limited": _pair(verdict.limited)})

    def drain(self) -> list[dict]:
        pending, self._pending = self._pending, []
        return pending

    def snapshot(self) -> dict:
        ordered = sorted(self._eval_ms)
        eval_ms = ({"p50": _quantile(ordered, .5), "p99": _quantile(ordered, .99), "n": len(ordered)}
                   if ordered else {"p50": None, "p99": None, "n": 0})
        return {"counts": dict(self._counts), "last_stop": self._last.get("stop"),
                "last_unavailable": self._last.get("unavailable"), "eval_ms": eval_ms}
```

`safety/AGENTS.md` Key Files 표에 한 행:

```markdown
| `shadow.py` | D-400 그림자 기록: `ShadowVerdict`, `ShadowLog`(카운터·전이 이벤트·1 Hz 묶음·eval_ms). 정책이 아니라 기록이라 `manager.py`와 나눈다 |
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/services/test/test_safety_shadow_log.py -q`
Expected: PASS (4)

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/services/core_features/safety/shadow.py src/runtime/services/test/test_safety_shadow_log.py src/runtime/services/core_features/safety/AGENTS.md
git commit -m "feat(safety): ShadowLog records would-be policy verdicts (D-400 2)"
```

---

### Task 4: `SafetyManager` 그림자 바인딩과 부수효과 없는 평가

**Files:**
- Modify: `src/runtime/services/core_features/safety/manager.py:249-314`
- Create: `src/runtime/services/test/test_safety_shadow_evaluate.py`

`bind_control_policy`의 내부 `_evaluate`를 `_control_evaluator`로 떼어 내 집행과 그림자가 같은 변환(Control 결과 → `SafetyDecision`)을 쓴다. 그림자 평가는 `policy_reason`·`estop`·`policy_required`·`policy_listeners`를 건드리지 않는다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/services/test/test_safety_shadow_evaluate.py`:

```python
"""D-400: shadow evaluation judges like enforce but changes nothing."""

from types import SimpleNamespace

from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


class FakePolicy:
    """Duck-typed Control CommandPolicy: evaluate(...) -> (snapshot, result) or None."""

    revision = "rev-1"

    def __init__(self, reason="allow", linear=0.05, angular=0.4, raises=False, none=False):
        self.reason, self.linear, self.angular = reason, linear, angular
        self.raises, self.none = raises, none

    def evaluate(self, linear, angular, now, allow_bounded_sweep=False):
        if self.raises:
            raise RuntimeError("boom")
        if self.none:
            return None
        snapshot = SimpleNamespace(calibration_revision="rev-1", observed_at=now - 0.05, expires_at=now + 0.3)
        return snapshot, SimpleNamespace(reason=self.reason, linear=self.linear, angular=self.angular)


def _safety(policy):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    safety._policy_clock = lambda: 1.0          # deterministic eval time (0 ms)
    listened = []
    safety.policy_listeners.append(lambda: listened.append(True))
    safety.bind_shadow_control_policy(policy)
    return safety, listened


def test_shadow_binding_keeps_enforcement_off():
    safety, listened = _safety(FakePolicy())

    assert safety.policy_mode == "shadow"
    assert safety.policy_required is False
    assert listened == []                       # binding a shadow never clears commands
    assert safety.evaluate_candidate(1, "navigation", 0.1, 0.0, 10.0) == (0.1, 0.0)


def test_limit_verdict_records_the_limited_command():
    safety, _ = _safety(FakePolicy(reason="motion_limited", linear=0.05, angular=0.4))

    safety.shadow_evaluate(1, "navigation", 0.1, 0.6, 10.0, output=(0.1, 0.6))

    (event,) = safety.shadow.drain()
    assert event["verdict"] == "limit"
    assert event["limited"] == [0.05, 0.4]


def test_stop_and_failure_never_latch():
    for policy, verdict in ((FakePolicy(reason="pickup"), "stop"),
                            (FakePolicy(raises=True), "unavailable"),
                            (FakePolicy(none=True), "unavailable")):
        safety, _ = _safety(policy)
        safety.policy_reason = "untouched"

        safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

        assert safety.estop is False
        assert safety.policy_reason == "untouched"
        assert safety.shadow.snapshot()["counts"][verdict] == 1


def test_over_budget_evaluation_is_unavailable():
    safety, _ = _safety(FakePolicy())
    ticks = iter([1.0, 1.02])                   # 20 ms
    safety._policy_clock = lambda: next(ticks)

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    snap = safety.shadow.snapshot()
    assert snap["counts"]["unavailable"] == 1
    assert snap["last_unavailable"]["reason"] == "policy_invalid"


def test_without_a_shadow_binding_nothing_is_recorded():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    assert safety.shadow is None
    assert safety.policy_mode == "off"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/services/test/test_safety_shadow_evaluate.py -q`
Expected: FAIL — `AttributeError: 'SafetyManager' object has no attribute 'bind_shadow_control_policy'`

- [ ] **Step 3: 구현**

(a) import 줄(11행 아래):

```python
from core_features.safety.shadow import ShadowLog, ShadowVerdict
```

(b) `__init__`의 `self.policy_listeners: list = []` 아래:

```python
        #: D-400: 'off' | 'shadow' | 'enforce'. Set by the binding, never by config here.
        self.policy_mode: str = 'enforce' if policy_required else 'off'
        self.shadow: Optional[ShadowLog] = None
        self._shadow_policy = None
        self._shadow_revision = ''
```

(c) `bind_control_policy`(292–314행)를 다음 세 메서드로 바꾼다:

```python
    def _control_evaluator(self, policy):
        """(evaluator, revision) turning a Control CommandPolicy result into a SafetyDecision."""
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

        return _evaluate, revision

    def bind_control_policy(self, policy) -> None:
        """Consume absorbed Control decisions without importing ROS or publishing."""
        self.bind_policy(*self._control_evaluator(policy))
        self.policy_mode = 'enforce'

    def bind_shadow_control_policy(self, policy) -> None:
        """D-400 shadow: judge every candidate, record it, never change the output."""
        self._shadow_policy, self._shadow_revision = self._control_evaluator(policy)
        self.shadow = ShadowLog()
        self.policy_mode = 'shadow'
```

(d) `evaluate_candidate` 바로 앞에:

```python
    def shadow_evaluate(self, command_id: int, source: str, linear: float, angular: float,
                        now: float, output: tuple[float, float]) -> None:
        """Record what enforce would have done. Touches no e-stop, mode or policy_reason."""
        if self.shadow is None:
            return
        request = SafetyRequest(command_id, source, self._shadow_revision, now, linear, angular)
        started = self._policy_clock()
        try:
            decision = self._shadow_policy(request)
            elapsed = self._policy_clock() - started
            valid = decision_valid(decision, request, elapsed)
        except Exception:
            decision, elapsed, valid = None, self._policy_clock() - started, None
        if valid is None:
            verdict, limited, reason = 'unavailable', (0., 0.), 'policy_failed'
        elif not valid:
            verdict, limited, reason = 'unavailable', (0., 0.), 'policy_invalid'
        elif decision.disposition == 'stop':
            verdict, limited, reason = 'stop', (0., 0.), decision.reason or 'policy_stop'
        else:
            verdict = 'allow' if (decision.linear_limit >= abs(linear) and
                                  decision.angular_limit >= abs(angular)) else 'limit'
            limited = (max(-decision.linear_limit, min(decision.linear_limit, linear)),
                       max(-decision.angular_limit, min(decision.angular_limit, angular)))
            reason = decision.reason
        try:
            self.shadow.record(ShadowVerdict(now, source, (linear, angular), output, verdict, limited,
                                             reason, elapsed * 1000.0))
        except Exception:  # noqa: BLE001 - a recorder bug must never change cmd_vel (D-400 non-interference)
            self.shadow_record_errors += 1
```

(Task 3 리뷰 M4: `record`는 `select_output` 안에서 불린다. 예외가 새면 `cmd_vel_cycle`이 ZERO를 내 그림자가 출력을 바꾼다. `__init__`에 `self.shadow_record_errors = 0`을 두고, `test_safety_shadow_evaluate.py`에 시험을 더한다:)

```python
def test_a_failing_recorder_never_escapes():
    safety, _ = _safety(FakePolicy())

    class Broken:
        def record(self, verdict):
            raise KeyError("boom")

    safety.shadow = Broken()
    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))   # must not raise

    assert safety.shadow_record_errors == 1
```

Task 8의 상태 블록에 `shadow_record_errors`를 `shadow` 안에 함께 보인다(`safety_policy_block`이 `snapshot()` 결과에 더한다).

(e) Task 2 리뷰 반영 — 판정 분류는 문자열이 아니라 `disposition`으로 한다. 정책이 `stop`의 사유로 `'policy_failed'`를 내도 `stop`으로 센다. 그러려고 `check_decision`의 조건 사슬을 `decision_valid(decision: object, request, elapsed) -> bool`로 옮기고, `check_decision`은 그것을 감싼다(집행 경로의 동작은 그대로):

```python
def decision_valid(decision: object, request: SafetyRequest, elapsed: float) -> bool:
    """True when ``decision`` is a well-formed, current answer to ``request`` (any disposition)."""
    return not (<Task 2의 check_decision if 조건 사슬 그대로>)


def check_decision(decision: object, request: SafetyRequest, elapsed: float) -> str:
    ...  # Task 2 docstring 그대로
    if not decision_valid(decision, request, elapsed):
        return 'policy_invalid'
    if decision.disposition == 'stop':
        return decision.reason or 'policy_stop'
    return ''
```

`test_safety_shadow_evaluate.py`에 하나 더한다:

```python
def test_stop_reason_that_looks_like_a_failure_is_still_a_stop():
    safety, _ = _safety(FakePolicy(reason="policy_failed"))   # not in the limit list -> disposition stop

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    assert safety.shadow.snapshot()["counts"]["stop"] == 1
```

`test_safety_decision_check.py`의 기존 시험은 그대로 통과해야 한다(분할이 동작을 바꾸지 않는다는 증거).

- [ ] **Step 4: 통과와 회귀 확인**

Run: `python -m pytest src/runtime/services/test/ src/runtime/gateway/test/test_control_policy_link.py src/runtime/gateway/test/test_control_absorption_safety.py src/runtime/gateway/test/test_core_logic.py -q`
Expected: PASS

Run: `python -c "import pathlib;print(len(pathlib.Path('src/runtime/services/core_features/safety/manager.py').read_text(encoding='utf-8').splitlines()))"`
Expected: 600 미만

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/services/core_features/safety/manager.py src/runtime/services/test/test_safety_shadow_evaluate.py
git commit -m "feat(safety): shadow binding evaluates without e-stop, mode or reason side effects (D-400 1-2)"
```

---

### Task 5: `CommandManager` — 그림자 관찰과 `policy_off` 알림, 출력 비간섭

**Files:**
- Modify: `src/runtime/services/core_features/command/manager.py:61-64, 187-215, 217-251`
- Create: `src/runtime/services/test/test_command_shadow.py`

비간섭이 이 설계의 핵심 보증이다. 같은 후보 열에서 `off`와 `shadow`의 출력이 같아야 하고, 정책이 정지·예외·지연 초과를 내도 e-stop·모드가 바뀌지 않아야 한다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/services/test/test_command_shadow.py`:

```python
"""D-400: shadow never changes cmd_vel; events leave only via announce_pending."""

from types import SimpleNamespace

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


class Events:
    def __init__(self):
        self.published = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, severity, data or {}))


class Policy:
    revision = "rev-1"

    def __init__(self, mode):
        self.mode = mode

    def evaluate(self, linear, angular, now, allow_bounded_sweep=False):
        if self.mode == "raise":
            raise RuntimeError("boom")
        reason = "pickup" if self.mode == "stop" else "allow"
        snapshot = SimpleNamespace(calibration_revision="rev-1", observed_at=now - 0.05, expires_at=now + 0.3)
        return snapshot, SimpleNamespace(reason=reason, linear=0.0, angular=0.0)


def _rig(policy=None, events=None):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events=events)
    safety._policy_clock = lambda: 1.0
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety, events=events)
    if policy is not None:
        safety.bind_shadow_control_policy(policy)
    modes.transition(Mode.NAVIGATION)
    return command, safety, modes


def _drive(command):
    outputs = []
    for i, twist in enumerate([Twist(0.1, 0.0), Twist(0.2, 0.3), None, Twist(0.05, -0.2)]):
        now = 10.0 + 0.02 * i
        command.set_nav_twist(twist, now=now)
        outputs.append(command.select_output(now=now))
    return outputs


@pytest.mark.parametrize("mode", ["allow", "stop", "raise"])
def test_shadow_output_equals_off_output_and_never_latches(mode):
    off_command, _, _ = _rig()
    shadow_command, safety, modes = _rig(Policy(mode))

    assert _drive(shadow_command) == _drive(off_command)
    assert safety.estop is False
    assert modes.mode is Mode.NAVIGATION


def test_shadow_events_leave_only_through_announce_pending():
    events = Events()
    command, _, _ = _rig(Policy("stop"), events=events)

    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    assert [e for e in events.published if e[0] == "safety.shadow_verdict"] == []

    command.announce_pending()
    shadow = [e for e in events.published if e[0] == "safety.shadow_verdict"]
    assert shadow == [("safety.shadow_verdict", "info",
                       {"verdict": "stop", "reason": "pickup", "source": "navigation", "t": 10.0,
                        "commanded": [0.1, 0.0], "output": [0.1, 0.0], "limited": [0.0, 0.0],
                        "suppressed": 0})]


def test_policy_off_is_announced_once_per_navigation_entry():
    events = Events()
    command, _, modes = _rig(events=events)

    for i in range(3):
        command.set_nav_twist(Twist(0.1, 0.0), now=10.0 + i * 0.02)
        command.select_output(now=10.0 + i * 0.02)
        command.announce_pending()
    modes.transition(Mode.IDLE)
    command.select_output(now=11.0)
    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0), now=11.1)
    command.select_output(now=11.1)
    command.announce_pending()

    offs = [e for e in events.published if e[0] == "safety.policy_off"]
    assert offs == [("safety.policy_off", "warning", {"source": "navigation"})] * 2


def test_zero_commands_are_not_judged():
    command, safety, _ = _rig(Policy("stop"))

    command.set_nav_twist(Twist(0.0, 0.0), now=10.0)
    command.select_output(now=10.0)

    assert sum(safety.shadow.snapshot()["counts"].values()) == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/services/test/test_command_shadow.py -q`
Expected: FAIL — 그림자 이벤트·`policy_off`가 나오지 않는다

- [ ] **Step 3: 구현**

(a) `__init__`의 `self._input_epoch = 0` 아래:

```python
        #: D-400: one safety.policy_off per entry into NAVIGATION while the policy is off.
        self._unguarded_noted = False
        self._pending_unguarded: Optional[str] = None
```

(b) `_policy_output`(201–215행)을 다음으로 바꾼다 — 출구를 하나로 모아 그림자가 실제 출력을 본다:

```python
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
        # D-400 shadow: judged after the real output is fixed; it can only record.
        self._safety.shadow_evaluate(command_id, source, linear, angular, now,
                                     output=(result.linear, result.angular))
        if self._safety.policy_mode == 'off' and source == 'navigation' and not self._unguarded_noted:
            self._unguarded_noted = True
            self._pending_unguarded = source
        return result
```

(c) `select_output` 맨 앞(`current = ...` 바로 아래)에 — MANUAL 분기가 일찍 반환하므로 반드시 그보다 앞이다. 그래야 NAVIGATION → MANUAL → NAVIGATION도 새 진입으로 센다:

```python
        if self._modes.mode is not Mode.NAVIGATION:
            self._unguarded_noted = False
```

시험에 MANUAL 경유 경우도 넣는다(`test_command_shadow.py` 끝):

```python
def test_policy_off_rearms_after_a_manual_detour():
    events = Events()
    command, _, modes = _rig(events=events)

    command.set_nav_twist(Twist(0.1, 0.0), now=10.0)
    command.select_output(now=10.0)
    modes.transition(Mode.MANUAL)
    command.select_output(now=10.5)
    modes.transition(Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0), now=11.0)
    command.select_output(now=11.0)
    command.announce_pending()

    assert sum(1 for e in events.published if e[0] == "safety.policy_off") == 2
```

(NAVIGATION ↔ MANUAL, NAVIGATION ↔ IDLE은 `arbitration.py:44-51`의 `_ALLOWED`가 허용한다.)

(d) `announce_pending`(187–199행) 맨 앞에 그림자·`policy_off` 배출을 넣는다(워치독 알림의 조기 반환보다 앞):

```python
    def announce_pending(self) -> None:
        """밀린 알림을 낸다. 브리지가 cmd_vel 을 내보낸 **뒤** 부른다."""
        if self._events is not None:
            if self._pending_unguarded is not None:
                self._events.publish("safety.policy_off", severity="warning", source="command_manager",
                                     data={"source": self._pending_unguarded})
            if self._safety.shadow is not None:
                for data in self._safety.shadow.drain():
                    self._events.publish("safety.shadow_verdict", severity="info",
                                         source="command_manager", data=data)
        self._pending_unguarded = None
        session = self._pending_watchdog
        ...  # 이하 기존 그대로
```

- [ ] **Step 4: 통과와 회귀 확인**

Run: `python -m pytest src/runtime/services/test/ src/runtime/gateway/test/test_core_logic.py src/runtime/gateway/test/test_teleop_watchdog_event.py src/runtime/gateway/test/test_cmd_vel_cycle.py src/runtime/gateway/test/test_control_policy_link.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/services/core_features/command/manager.py src/runtime/services/test/test_command_shadow.py
git commit -m "feat(command): shadow observes the final output; policy_off once per navigation entry (D-400 2)"
```

---

### Task 6: 파라미터 리졸버 `safety_params.py`

**Files:**
- Create: `src/runtime/gateway/core/safety_params.py`
- Create: `src/runtime/gateway/test/test_safety_params.py`

입력은 모두 CORE가 이미 가진 값이다. LiDAR는 `resolve_lidar_forward_deg`가 이미 고른 각도(라인 추종과 **같은 값**)를, 봉투는 CORE 속도 상한을 쓴다. 매직 넘버를 새로 두지 않는다(D-397: 기본값은 URDF·프로필에서). 나머지 보정 키 여섯 개(IMU·cliff·부호)는 이 계획에서 워커 기본값이고, 출처에 그렇게 적는다(저장소 종류는 계획 3).

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/gateway/test/test_safety_params.py`:

```python
"""D-400 3: safety worker parameters from CORE's own sources."""

import math

import pytest

from core.safety_params import resolve_safety_params

BASE = dict(lidar_forward_deg=181.5, lidar_source="calibration record r1 sha256 abc",
            caps=(0.2, 0.8, 0.15, 0.6, 0.2, 0.8))


def test_lidar_and_envelope_come_from_core_values():
    params = resolve_safety_params(**BASE, overlay={})

    assert params.parameters["lidar_yaw_offset"] == pytest.approx(math.radians(181.5))
    assert params.parameters["safety_max_linear"] == 0.2
    assert params.parameters["safety_max_angular"] == 0.8
    assert params.sources["lidar_yaw_offset"] == "line_follow: calibration record r1 sha256 abc"
    assert params.sources["safety_max_linear"] == "core speed caps"
    assert params.sources["imu_roll0"] == "worker default"


def test_overlay_wins_and_is_recorded():
    params = resolve_safety_params(**BASE, overlay={"cliff_enable": False, "safety_max_linear": 0.25})

    assert params.parameters["cliff_enable"] is False
    assert params.parameters["safety_max_linear"] == 0.25
    assert params.sources["cliff_enable"] == "operator overlay"


@pytest.mark.parametrize("overlay, message", [
    ({"sensor_timeout": 1.0}, "not a safety policy parameter"),
    ({"safety_max_linear": 0.1}, "below the CORE speed cap"),
    ({"safety_max_angular": 0.5}, "below the CORE speed cap"),
    ({"lidar_yaw_offset": 3.3}, "line_follow"),
])
def test_overlay_refusals(overlay, message):
    with pytest.raises(ValueError, match=message):
        resolve_safety_params(**BASE, overlay=overlay)


def test_revision_is_deterministic_and_tracks_values():
    a = resolve_safety_params(**BASE, overlay={})
    b = resolve_safety_params(**BASE, overlay={})
    c = resolve_safety_params(**{**BASE, "lidar_forward_deg": 180.0}, overlay={})

    assert a.revision == b.revision
    assert a.revision != c.revision
    assert len(a.revision) == 16
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/gateway/test/test_safety_params.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.safety_params'`

- [ ] **Step 3: 구현** — `src/runtime/gateway/core/safety_params.py`:

```python
"""Safety-policy worker parameters from CORE's own sources (D-400 3). ROS-free.

- lidar_yaw_offset: the angle line_follow already resolved (core/lidar_mount.py:
  URDF nominal < accepted lidar_mount record < operator overlay), so lane
  following and the safety policy see one LiDAR mount.
- safety_max_linear / safety_max_angular: the largest CORE speed cap. A lower
  envelope would make every shadow verdict a "limit" and measure nothing.
- control.sensor_adapter.parameters (operator overlay): wins key by key, only
  for the keys below. lidar_yaw_offset is set through line_follow, never here.
- The other measured keys stay the worker's defaults in this plan; their
  calibration-store kinds arrive with enforcement (D-400 plan 3).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

WORKER_DEFAULT_KEYS = ("imu_roll0", "imu_pitch0", "cmd_linear_sign",
                       "cliff_mode", "cliff_raw_max", "cliff_clear_raw")
ENVELOPE_KEYS = ("safety_max_linear", "safety_max_angular")
OVERLAY_KEYS = frozenset((*WORKER_DEFAULT_KEYS, *ENVELOPE_KEYS, "cliff_enable"))


@dataclass(frozen=True)
class SafetyParams:
    parameters: dict[str, Any]
    sources: dict[str, str]
    revision: str


def resolve_safety_params(*, lidar_forward_deg: float, lidar_source: str,
                          caps: tuple[float, ...], overlay: Mapping[str, Any]) -> SafetyParams:
    """caps = every CORE speed cap (SpeedLimits max/manual/fleet, linear and angular)."""
    if "lidar_yaw_offset" in overlay:
        raise ValueError("set the LiDAR mount through line_follow.lidar_forward_deg, not the adapter")
    unknown = set(overlay) - OVERLAY_KEYS
    if unknown:
        raise ValueError("not a safety policy parameter: " + ", ".join(sorted(unknown)))
    linear_cap, angular_cap = max(caps[0::2]), max(caps[1::2])
    parameters: dict[str, Any] = {"lidar_yaw_offset": math.radians(lidar_forward_deg),
                                  "safety_max_linear": linear_cap, "safety_max_angular": angular_cap}
    sources = {"lidar_yaw_offset": "line_follow: " + lidar_source,
               "safety_max_linear": "core speed caps", "safety_max_angular": "core speed caps"}
    sources.update({key: "worker default" for key in WORKER_DEFAULT_KEYS})
    for key, value in overlay.items():
        parameters[key], sources[key] = value, "operator overlay"
    for key, cap in (("safety_max_linear", linear_cap), ("safety_max_angular", angular_cap)):
        if not (isinstance(parameters[key], (int, float)) and parameters[key] >= cap):
            raise ValueError(f"{key} {parameters[key]!r} is below the CORE speed cap {cap}")
    body = json.dumps({"parameters": parameters, "sources": sources}, sort_keys=True)
    return SafetyParams(parameters, sources, hashlib.sha256(body.encode()).hexdigest()[:16])
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/gateway/test/test_safety_params.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/gateway/core/safety_params.py src/runtime/gateway/test/test_safety_params.py
git commit -m "feat(core): safety policy parameters from line_follow LiDAR and CORE caps (D-400 3)"
```

---

### Task 7: 어댑터 — 모드별 바인딩과 `build_control_adapter`

**Files:**
- Modify: `src/runtime/gateway/core/bridge/control_sensor_adapter.py:257-285` + 끝에 함수 추가
- Test: `src/runtime/gateway/test/test_control_sensor_adapter.py` (추가)

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_control_sensor_adapter.py` 끝에:

```python
from core.bridge.control_sensor_adapter import build_control_adapter


class RecordingSafety:
    def __init__(self):
        self.calls = []

    def bind_control_policy(self, policy):
        self.calls.append(("enforce", policy))

    def bind_shadow_control_policy(self, policy):
        self.calls.append(("shadow", policy))


def test_bind_safety_follows_the_mode():
    for mode in ("shadow", "enforce"):
        adapter = ControlSensorAdapter({"mode": mode}, sensor_node_factory=lambda **k: FakeSensorNode(**k),
                                       **_provider_factories())
        safety = RecordingSafety()

        assert adapter.bind_safety(safety) is True
        assert safety.calls == [(mode, adapter.policy)]


def test_build_passes_resolved_parameters_and_ignores_the_calibration_block():
    created = []

    def factory(**kwargs):
        created.append(kwargs)
        return FakeSensorNode(**kwargs)

    adapter, notes = build_control_adapter(
        {"mode": "shadow", "parameters": {"cliff_enable": False},
         "calibration": {"required": True, "path": "/x"}},
        parameters={"lidar_yaw_offset": 3.17, "cliff_enable": False},
        sensor_node_factory=factory, **_provider_factories())

    assert adapter.config.mode == "shadow"
    assert created[0]["parameter_overrides"] == {"lidar_yaw_offset": 3.17, "cliff_enable": False}
    assert notes == ["control.sensor_adapter.calibration is ignored (D-400 3); use the calibration store"]


def test_shadow_construction_failure_falls_back_to_off():
    def broken(**kwargs):
        raise ValueError("no IR stream")

    adapter, notes = build_control_adapter({"mode": "shadow"}, parameters={},
                                           sensor_node_factory=broken, **_provider_factories())

    assert adapter.config.mode == "off"
    assert adapter.mode_error == "no IR stream"
    assert notes == ["shadow sensor adapter failed, running with the policy off: no IR stream"]


def test_enforce_construction_failure_still_refuses_start():
    def broken(**kwargs):
        raise ValueError("no IR stream")

    with pytest.raises(ValueError, match="no IR stream"):
        build_control_adapter({"mode": "enforce"}, parameters={},
                              sensor_node_factory=broken, **_provider_factories())


def test_invalid_mode_in_shadow_config_is_still_a_config_error():
    with pytest.raises(ValueError, match="off, shadow or enforce"):
        build_control_adapter({"mode": "on"}, parameters={})


def test_shadow_with_control_policy_required_is_a_config_error():
    # Design 3.1: shadow never binds a deciding policy, so policy_required would
    # latch every command. Rejected before any worker is built.
    with pytest.raises(ValueError, match="control_policy_required"):
        build_control_adapter({"mode": "shadow"}, parameters={}, policy_required=True)
```

(Task 1 리뷰 반영: Task 1 커밋 뒤의 `bind_safety`는 `enforce`에서만 바인딩한다 — 이 태스크가 그 임시 가드를 아래 (b)로 바꾼다. Task 1이 `enabled`를 `mode`에서 계산되는 property로 바꿨다.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/gateway/test/test_control_sensor_adapter.py -q -k "bind_safety_follows or build_ or construction_failure or invalid_mode_in"`
Expected: FAIL — `ImportError: cannot import name 'build_control_adapter'`

- [ ] **Step 3: 구현**

(a) `ControlSensorAdapter.__init__`의 `self._parameters: dict[str, Any] = {}` 아래:

```python
        #: D-400: why a configured shadow fell back to off ('' when it did not).
        self.mode_error = ""
```

(b) `bind_safety`(278–285행)를 모드에 따라 나눈다:

```python
    def bind_safety(self, safety: Any) -> bool:
        """Bind the worker policy to CORE's safety consumer: shadow records, enforce limits (D-400)."""
        if not self.enabled:
            return False
        if self.policy is None:
            raise ValueError("enabled sensor adapter cannot bind its policy")
        if self.config.mode == "shadow":
            safety.bind_shadow_control_policy(self.policy)
        else:
            safety.bind_control_policy(self.policy)
        return True
```

(기존 `callable(getattr(safety, "bind_control_policy", None))` 검사는 지운다. `SafetyManager`가 두 메서드를 모두 선언하므로 C6 "선언된 멤버" 규칙에 맞다.)

(c) 파일 끝에:

```python
_CALIBRATION_IGNORED = "control.sensor_adapter.calibration is ignored (D-400 3); use the calibration store"


def build_control_adapter(raw_config: Mapping[str, Any] | None, *, parameters: Mapping[str, Any],
                          policy_required: bool = False,
                          **factories: Any) -> tuple["ControlSensorAdapter", list[str]]:
    """D-400 assembly: resolved parameters replace the overlay, the calibration
    block is ignored, and a shadow that cannot start runs with the policy off.
    Config errors (bad mode, bad types, shadow + safety.control_policy_required)
    still raise in every mode."""
    raw = dict(raw_config or {})
    config = ControlSensorConfig.from_mapping(raw)  # config errors raise before anything is built
    if config.mode == "shadow" and policy_required:
        raise ValueError("control_policy_required is enforce-only; shadow never binds a deciding policy")
    notes = []
    calibration = raw.pop("calibration", None)
    if isinstance(calibration, Mapping) and calibration.get("required") is True:
        notes.append(_CALIBRATION_IGNORED)
    raw["parameters"] = dict(parameters)
    try:
        return ControlSensorAdapter(raw, **factories), notes
    except ValueError as exc:
        if raw.get("mode") != "shadow":
            raise
        off = ControlSensorAdapter({"mode": "off"})
        off.mode_error = str(exc)
        notes.append(f"shadow sensor adapter failed, running with the policy off: {exc}")
        return off, notes
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/gateway/test/test_control_sensor_adapter.py src/runtime/gateway/test/test_module_criteria.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/gateway/core/bridge/control_sensor_adapter.py src/runtime/gateway/test/test_control_sensor_adapter.py
git commit -m "feat(core): adapter binds by mode; shadow start failure runs with the policy off (D-400 1)"
```

---

### Task 8: 상태 계약 — `StateSnapshot.safety_policy`와 API Ref v1.69

**Files:**
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py:984-1035`
- Modify: `src/runtime/services/core_features/state/manager.py:86-95, 210-251`
- Modify: `test/architecture/test_module_structure.py:144-150` (schemas 크기 판정 줄 수)
- Modify: `docs/reference/ROSY API & Protocol Reference.md` (헤더, §6.1, §8, §11)
- Modify: `src/runtime/api_web/core_api_web/app.py:1,110`, 버전 핀 `test/test_line_follow_contract_docs.py:16`, `src/site/fleet/test/test_task_contract_docs.py:26,88`, `src/site/fleet/test/test_mission_progress.py:512`
- Create: `src/runtime/services/test/test_state_safety_policy.py`

- [ ] **Step 0: 버전 번호 다시 확인** — 다른 세션이 v1.69를 먼저 쓸 수 있다(D-395 계획이 v1.69를 예고했다).

Run: `git fetch -q; git show main:"docs/reference/ROSY API & Protocol Reference.md" | Select-String '^\*\*Version:\*\*'`
현재 버전 + 1을 쓴다. 아래 "v1.69"는 그 값으로 바꿔 읽는다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/services/test/test_state_safety_policy.py`:

```python
"""D-400: robot state carries the safety policy block when a provider is set."""

from core_common.protocol.schemas import SafetyPolicyStatus, StateSnapshot


def test_state_model_accepts_the_safety_policy_block():
    block = {"mode": "shadow", "mode_effective": "shadow", "mode_error": "", "revision": "abcd1234abcd1234",
             "sources": {"lidar_yaw_offset": "line_follow: hand value"},
             "shadow": {"counts": {"allow": 3, "limit": 1, "stop": 0, "unavailable": 0},
                        "last_stop": None, "last_unavailable": None,
                        "eval_ms": {"p50": 0.4, "p99": 1.1, "n": 4},
                        "dropped_events": 0, "suppressed_events": 2, "record_errors": 0}}

    status = SafetyPolicyStatus.model_validate(block)

    assert status.mode_effective == "shadow"
    assert status.shadow.counts["limit"] == 1
    assert "safety_policy" in StateSnapshot.model_fields
    assert StateSnapshot.model_fields["safety_policy"].default is None
```

같은 파일에 StateManager 공급자 시험(생성 인자는 `test_swarm.py:113`과 같다):

```python
from core_features.state.manager import StateManager


def test_state_manager_reports_the_provider_block():
    state = StateManager(robot_id="rosy_01")
    state.set_safety_policy_provider(lambda: {"mode": "off", "mode_effective": "off",
                                              "mode_error": "", "revision": "", "sources": {},
                                              "shadow": None})

    assert state.snapshot().safety_policy.mode == "off"


def test_without_a_provider_the_block_is_null():
    assert StateManager(robot_id="rosy_01").snapshot().safety_policy is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/services/test/test_state_safety_policy.py -q`
Expected: FAIL — `ImportError: cannot import name 'SafetyPolicyStatus'`

- [ ] **Step 3: 스키마** — `schemas.py`의 `RobotActivity` 정의 뒤(1006행 근처)에:

```python
class SafetyShadowStatus(BaseModel):
    """D-400 shadow counters (v1.69 additive)."""
    counts: dict[str, int]
    last_stop: Optional[dict] = None          # {t (monotonic s), reason, source}
    last_unavailable: Optional[dict] = None
    eval_ms: dict
    dropped_events: int = 0
    suppressed_events: int = 0
    record_errors: int = 0


class SafetyPolicyStatus(BaseModel):
    """D-400: the safety policy mode CORE runs, and why (v1.69 additive)."""
    mode: str
    mode_effective: str
    mode_error: str = ""
    revision: str = ""
    sources: dict[str, str] = {}
    shadow: Optional[SafetyShadowStatus] = None
```

`StateSnapshot`의 `activity: Optional[RobotActivity] = None` 아래:

```python
    safety_policy: Optional[SafetyPolicyStatus] = None  # D-400, v1.69 additive
```

- [ ] **Step 4: StateManager 공급자** — `activity` 공급자와 같은 모양으로(86–95행, 213–215행, 251행):

```python
        self._safety_policy_provider: Optional[Callable[[], Optional[dict]]] = None

    def set_safety_policy_provider(self, provider: Optional[Callable[[], Optional[dict]]]) -> None:
        self._safety_policy_provider = provider
```

`snapshot()` 안 `activity` 계산 아래:

```python
        provider = self._safety_policy_provider
        raw_policy = provider() if provider is not None else None
        safety_policy = SafetyPolicyStatus.model_validate(raw_policy) if raw_policy else None
```

생성자 호출에 `safety_policy=safety_policy,` 추가, import에 `SafetyPolicyStatus` 추가.

- [ ] **Step 5: 크기 판정 갱신** — `schemas.py` 줄 수를 재고, `test/architecture/test_module_structure.py:144`의 숫자를 그 값으로, 사유 끝에 한 문장을 덧붙인다:

```python
        "... Re-judged 2026-10-01 at <새 줄 수> lines: D-400 SafetyPolicyStatus joins the state "
        "contract; the single contract source still outweighs a split (same verdict)."
```

Run: `python -c "import pathlib;print(len(pathlib.Path('src/contracts/foundation/core_common/protocol/schemas.py').read_text(encoding='utf-8').splitlines()))"`

- [ ] **Step 6: API Ref** —
  - 헤더 `**Version:** v1.69`.
  - §6.1 `GET /robot/state` 필드 표에 행: `| safety_policy | object? | D-400. mode(off/shadow/enforce), mode_effective(그림자 구성 실패 시 off), mode_error, revision, sources(키별 출처), shadow{counts, last_stop, last_unavailable, eval_ms{p50,p99,n}, dropped_events, suppressed_events, record_errors}. 시각 t는 CORE monotonic 초(벽시계 아님). 공급자가 없으면 null | v1.69 |`
  - §8 이벤트 표(`safety.watchdog` 행 아래)에 두 행:
    - `| \`safety.shadow_verdict\` | info | 로봇 | \`{verdict, reason, source, t, commanded, output, limited, suppressed}\` |` (판정이 바뀔 때·같은 판정 1 s마다, 최대 5/s. 억제된 전이 수는 다음 이벤트의 `suppressed`)
    - `| \`safety.policy_off\` | warning | 로봇 | \`{source}\` |`
  - §11 변경 이력에 `| v1.69 | 2026-10-01 | Additive: state \`safety_policy\`, events \`safety.shadow_verdict\`·\`safety.policy_off\` (D-400) |`
  - `app.py` 1행 주석과 110행 버전 문자열, 위에 적은 시험 세 곳의 버전 핀을 v1.69로.

- [ ] **Step 7: 통과 확인**

Run: `python -m pytest src/runtime/services/test/test_state_safety_policy.py src/runtime/gateway/test/test_event_catalogue.py src/runtime/gateway/test/test_protocol_version_alignment.py test/test_line_follow_contract_docs.py test/architecture/test_module_structure.py src/site/fleet/test/test_task_contract_docs.py src/site/fleet/test/test_mission_progress.py -q`
Expected: PASS

- [ ] **Step 8: 커밋**

```bash
git add src/contracts/foundation/core_common/protocol/schemas.py src/runtime/services/core_features/state/manager.py src/runtime/services/test/test_state_safety_policy.py test/architecture/test_module_structure.py "docs/reference/ROSY API & Protocol Reference.md" src/runtime/api_web/core_api_web/app.py test/test_line_follow_contract_docs.py src/site/fleet/test/test_task_contract_docs.py src/site/fleet/test/test_mission_progress.py
git commit -m "feat(state): safety_policy block and shadow/policy_off events, API v1.69 (D-400 2)"
```

---

### Task 9: `node.py` 조립 순서

**Files:**
- Modify: `src/runtime/gateway/core/node.py:73-112`
- Create: `src/runtime/gateway/core/safety_policy_status.py`
- Create: `src/runtime/gateway/test/test_safety_policy_status.py`

`node.py`는 rclpy를 import해 호스트 시험이 닿지 않는다. 그래서 상태 블록을 만드는 결정은 ROS-free 함수로 빼고, `node.py`에는 호출 순서만 남긴다.

새 순서: (1) LiDAR 정면 해석 → (2) 파라미터 해석 → (3) 어댑터 조립 → (4) 바인딩 → (5) 라인 추종에 LiDAR 적용 → (6) 상태 공급자. 전에는 어댑터가 먼저였고 LiDAR 해석이 어댑터 값을 "비교"했다. 이제 어댑터가 LiDAR 값을 **받으므로** 비교할 것이 없다(`adapter_parameters=None`).

- [ ] **Step 1: 실패하는 시험 쓰기** — `src/runtime/gateway/test/test_safety_policy_status.py`:

```python
"""D-400: the state block node.py publishes, built without ROS."""

from types import SimpleNamespace

from core.safety_params import SafetyParams
from core.safety_policy_status import safety_policy_block


def test_block_reports_configured_and_effective_mode():
    adapter = SimpleNamespace(config=SimpleNamespace(mode="off"), mode_error="no IR stream")
    params = SafetyParams({"lidar_yaw_offset": 3.17}, {"lidar_yaw_offset": "line_follow: hand value"}, "r" * 16)

    block = safety_policy_block("shadow", adapter, params, shadow=None)

    assert block == {"mode": "shadow", "mode_effective": "off", "mode_error": "no IR stream",
                     "revision": "r" * 16, "sources": {"lidar_yaw_offset": "line_follow: hand value"},
                     "shadow": None}


def test_block_carries_the_shadow_snapshot():
    adapter = SimpleNamespace(config=SimpleNamespace(mode="shadow"), mode_error="")
    shadow = SimpleNamespace(snapshot=lambda: {"counts": {"allow": 1}})

    block = safety_policy_block("shadow", adapter, None, shadow=shadow, record_errors=2)

    assert block["shadow"] == {"counts": {"allow": 1}, "record_errors": 2}
    assert block["revision"] == "" and block["sources"] == {}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/gateway/test/test_safety_policy_status.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현** — `src/runtime/gateway/core/safety_policy_status.py`:

```python
"""The robot-state safety_policy block (D-400, API v1.69). ROS-free."""
from __future__ import annotations

from typing import Any, Optional


def safety_policy_block(configured_mode: str, adapter: Any, params: Optional[Any],
                        shadow: Optional[Any], record_errors: int = 0) -> dict:
    return {"mode": configured_mode, "mode_effective": adapter.config.mode,
            "mode_error": adapter.mode_error,
            "revision": params.revision if params is not None else "",
            "sources": dict(params.sources) if params is not None else {},
            "shadow": ({**shadow.snapshot(), "record_errors": record_errors}
                       if shadow is not None else None)}
```

`node.py` 73–112행을 다음으로 바꾼다(`os.environ` data_root 블록은 삭제 — 어댑터가 `calibration`을 읽지 않는다):

```python
        from core.bridge.control_sensor_adapter import ControlSensorConfig, build_control_adapter
        from core.lidar_mount import resolve_lidar_forward_deg
        from core.safety_params import resolve_safety_params
        from core.safety_policy_status import safety_policy_block
        from core_common.config import local_overlay
        control_cfg = config.get("control", {}) or {}
        if not isinstance(control_cfg, dict):
            raise ValueError("control configuration must be a mapping")
        sensor_cfg = control_cfg.get("sensor_adapter", {}) or {}
        configured_mode = ControlSensorConfig.from_mapping(sensor_cfg).mode
        # D-47 addendum / D-397: one LiDAR mount for line_follow and the safety
        # policy (operator overlay > accepted store record > URDF-nominal hand value).
        try:
            operator_deg = (local_overlay().get("line_follow") or {}).get("lidar_forward_deg")
        except Exception:  # noqa: BLE001 - load_config already read this file; never block CORE start
            operator_deg = None
        forward_deg, forward_source, forward_warn = resolve_lidar_forward_deg(
            config.get("line_follow", {}) or {}, hand_default=self.core.line_follow.config.lidar_forward_deg,
            operator_deg=operator_deg)
        params = None
        if configured_mode != "off":
            limits = self.core.safety.limits
            params = resolve_safety_params(
                lidar_forward_deg=forward_deg, lidar_source=forward_source,
                caps=((limits.max_linear, limits.max_angular),
                      (limits.manual_linear, limits.manual_angular),
                      (limits.fleet_linear, limits.fleet_angular)),
                overlay=sensor_cfg.get("parameters") or {})
        namespace = self.get_namespace() if callable(getattr(self, "get_namespace", None)) else None
        self.control_adapter, notes = build_control_adapter(
            sensor_cfg, parameters=params.parameters if params else {}, namespace=namespace,
            policy_required=self.core.safety.policy_required)
        for note in notes:
            self.get_logger().warning(note)
        self.core.control_adapter = self.control_adapter
        self.control_adapter.bind_safety(self.core.safety)
        self.core.line_follow.use_lidar_forward(forward_deg, forward_source)
        log = self.get_logger().warning if forward_warn else self.get_logger().info
        log(f"line_follow LiDAR forward {forward_deg:.2f} deg from {forward_source}")
        self.core.state.set_safety_policy_provider(lambda: safety_policy_block(
            configured_mode, self.control_adapter, params, self.core.safety.shadow,
            self.core.safety.shadow_record_errors))
```

주의 두 가지:
- `getattr(self, "get_namespace", None)`은 기존 줄을 옮긴 것이다(새 `getattr` 아님). C6 시험이 줄 단위로 보면 기존 항목과 같은 문자열이라 통과해야 한다 — Step 4에서 확인한다.
- `resolve_safety_params`의 `ValueError`(overlay 오류)는 `shadow`에서도 시작을 막는다. overlay 오류는 설정 오류이고, 설계 3.1의 "그림자 구성 실패 → off"는 **워커 시작 실패**(센서 공급자·워커 검증)만 뜻한다. 이 구분을 Task 10의 ADR 기록에 적는다.

- [ ] **Step 4: 통과와 구조 시험 확인**

Run: `python -m pytest src/runtime/gateway/test/test_safety_policy_status.py src/runtime/gateway/test/test_module_criteria.py src/runtime/gateway/test/test_lidar_mount_source.py src/runtime/gateway/test/test_pinky_lidar_forward_device.py test/architecture/test_module_structure.py -q`
Expected: PASS. `test_lidar_mount_source.py`가 `node.py` 소스에서 `adapter_parameters=`를 찾는다면 FAIL한다 — 그 단언을 "LiDAR 해석이 어댑터보다 먼저, `use_lidar_forward`가 같은 `forward_deg`로" 바꾸고 이유(D-400: 어댑터가 값을 받으므로 비교 대상이 없다)를 시험 docstring에 적는다.

Run: `python -m py_compile src/runtime/gateway/core/node.py`
Expected: 출력 없음

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/gateway/core/node.py src/runtime/gateway/core/safety_policy_status.py src/runtime/gateway/test/test_safety_policy_status.py
git commit -m "feat(core): node assembles LiDAR -> safety params -> adapter -> binding -> state (D-400)"
```

(`test_lidar_mount_source.py`를 고쳤다면 같은 커밋에 더한다.)

---

### Task 10: 기록과 전체 확인

**Files:**
- Modify: `src/runtime/gateway/logs.md`, `src/runtime/services/logs.md`, `src/contracts/foundation/logs.md` (각 모듈 `logs.md`; 경로는 `tools/harness/harness.yaml`의 모듈 목록으로 확인)
- Modify: `docs/adr/D-400-core-safety-policy-off-shadow-enforce.md` (구현 메모 한 단락)
- Modify: `docs/plans/2026-10-01-core-safety-policy-shadow-design.md` 3.3절 (overlay 허용 키에 `cliff_enable`, 워커 기본값 여섯 키)
- Generated: `docs/index.md`, 모듈 `index.md`, `STATUS.md`

- [ ] **Step 1: 전체 시험과 기존 실패 비교**

```bash
python -m pytest src/runtime/gateway/test/ src/runtime/services/test/ src/contracts/foundation/test/ src/runtime/api_web/test/ test/ -q -rfE -p no:cacheprovider > X:/DevTemp/d398-plan1/run.txt
python test/known_failures.py X:/DevTemp/d398-plan1/run.txt
```

Expected: exit 0. exit 1(`NEW`)이면 그 실패는 이 브랜치 것으로 보고 고친다. 깨끗한 `main` worktree에서 같은 시험이 실패하는지 확인하기 전에는 "무관하다"고 쓰지 않는다.

- [ ] **Step 2: 모듈 기록** — 각 `logs.md`에 같은 형식으로 한 항목(예: gateway):

```markdown
## 2026-10-01 · uncommitted · feat(core): D-400 safety policy mode and shadow assembly
- 변경: `control.sensor_adapter.mode` off/shadow/enforce(`enabled` 호환), `build_control_adapter`(그림자 시작 실패 → off, `calibration` 블록 무시), `safety_params.py`(LiDAR = line_follow 값, 봉투 = CORE 속도 상한, overlay 허용 목록), `node.py` 조립 순서, 상태 `safety_policy` 공급자.
- 증거: <Step 1의 pytest 요약 줄>; `known_failures.py` exit 0.
- gate 변화: 없음. SOURCE만. 그림자는 어느 로봇에서도 켜지 않았다(기본 off).
```

- [ ] **Step 3: ADR 구현 메모** — D-400 끝에:

```markdown
**Implementation note (plan 1, 2026-10-01):** Source only, default `off`. A shadow falls back to off only when the worker cannot start (provider, worker checks); an invalid mode or overlay key is a config error in every mode. The six non-geometric measured keys stay worker defaults until plan 3 adds their store kinds; overlay keys are those six, the two envelope keys and `cliff_enable` (Gazebo has no IR).
```

- [ ] **Step 4: 생성과 lint**

```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

Expected: `0 error(s)`

- [ ] **Step 5: 남은 자리 검사** — 바뀐 파일에 `TODO`, `skip`, `.only`, 빈 구현이 없는지:

```bash
git diff main --name-only | xargs grep -nE "TODO|pytest.mark.skip|\.only\(|NotImplementedError|pass  # stub" || echo clean
```

Expected: `clean`

- [ ] **Step 6: 커밋**

```bash
git add <Step 2·3·4에서 바뀐 경로만, git status --short에서 하나씩>
git commit -m "docs(records): D-400 plan 1 module logs, ADR implementation note"
```

- [ ] **Step 7: 독립 검토** — 같은 컨텍스트에서 자기 승인하지 않는다. `oh-my-claudecode:code-reviewer`(또는 `superpowers:requesting-code-review`)에 이 계획과 `git diff main...HEAD`를 넘긴다. 검토 관점: (1) 그림자가 출력·e-stop·모드를 바꾸는 경로가 하나라도 있는가, (2) 이벤트가 `select_output` 안에서 나가는가, (3) import 방향·크기 예산·C6, (4) `enforce` 동작이 이 변경 전과 같은가.

---

## 자기 검토 (계획 작성자)

- **설계 대응:** 3.1 → Task 1·7, 3.2 → Task 2–5·8(ROS 토픽은 계획 2), 3.3 → Task 6·9(새 저장소 종류는 계획 3), 3.4 → 계획 3, 3.5-1·2 → Task 1·9, 3.5-3 → 계획 2, 3.5-4 → Task 5·8(대시보드는 계획 2), 3.5-5 → 계획 2, 3.6 → 계획 2.
- **설계와 달라진 점(Task 10 Step 3에서 ADR에 적는다):** overlay 허용 키에 `cliff_enable` 추가(Gazebo), "그림자 구성 실패 → off"를 워커 시작 실패로 좁힘.
- **이름 일관성:** `bind_shadow_control_policy`, `shadow_evaluate`, `policy_mode`, `ShadowLog.record/drain/snapshot`, `build_control_adapter`, `resolve_safety_params`, `SafetyParams.parameters/sources/revision`, `safety_policy_block`, `SafetyPolicyStatus`, `set_safety_policy_provider` — 태스크 사이 동일.

---

## 실행 중 변경 기록 (태스크별 리뷰 반영)

아래 표의 결정이 위 태스크 본문보다 우선한다. Task 10 Step 3의 ADR 구현 메모에 이 표를 요약해 옮긴다.

| 태스크 | 결정 | 이유 |
|---|---|---|
| 1 | 기본 yaml에 `mode`를 두지 않는다(주석만). 없으면 off | 옛 overlay의 `enabled:`와 deep-merge되면 "not both"로 CORE가 못 뜬다 |
| 1 | `enabled`는 `mode`에서 계산되는 property | 두 값이 어긋날 수 없게 |
| 1→7 | Task 7 전까지 `bind_safety`는 `enforce`에서만 바인딩 | 중간 커밋에서 `shadow`가 집행하지 않게 |
| 2→4 | `decision_valid`(bool)와 `check_decision`(사유) 분리. 그림자는 `disposition`으로 분류 | 정책의 stop 사유가 `policy_failed`여도 stop으로 센다 |
| 3 | `ShadowLog`에 락, 이벤트는 판정 단위 전이 + 1 s 반복 + 최소 0.2 s 간격, `suppressed`(변화 수)·`dropped_events`·`suppressed_events`, 페이로드 `{verdict, reason, source, t, commanded, output, limited, suppressed}`, 시계 역행 시 첫 기록 취급 | API 스레드 동시 읽기, allow↔limit 50 Hz 흔들림이 EventBus 1000칸을 밀어내지 않게, 분석에 시각·실제 출력 필요 |
| 4 | 그림자/집행 바인딩은 상호 배타(`bind_policy`에서 검사), 그림자 이중 바인딩 거부, `shadow_evaluate`는 어떤 예외도 밖으로 내지 않는다(`shadow_record_errors`) | 상태가 "shadow"인데 집행 중인 경우를 없앤다, 비간섭 |
| 5 | **그림자 평가는 `announce_pending`에서(바퀴 뒤)** 한다. `_policy_output`은 후보만 저장 | 정책 평가 비용이 출력 지연이 되지 않게 — 비간섭의 더 강한 형태 |
| 5 | `policy_off`는 `navigation`과 `docking` 출처, 모드가 바뀔 때마다 재무장, 첫 0 아닌 출력에서 낸다(모드 진입 순간이 아님) | 도킹도 자율 주행. 라인 추종은 `policy_required` 없이 시작하지 않으므로 해당 없음 |
| 5 | `announce_pending`은 워치독 알림을 먼저, 각 발행을 개별 보호(`announce_errors`) | 한 발행 실패가 SAF-002 알림·다른 이벤트를 막지 않게 |
| 8 | §8에 `commanded`는 프로필 클립 뒤 값, `t`는 CORE monotonic 초라고 적는다 | 필드 이름이 원 요청값처럼 읽힌다 |
| 7 | `build_control_adapter(policy_required=)` — `shadow` + `control_policy_required`는 설정 오류 | 설계 3.1 규칙에 태스크가 없었다 |
| 6 | **워커는 `lidar_use_tf`(기본 True)일 때 `lidar_yaw_offset`을 쓰지 않고 TF(= URDF NOMINAL 180°)를 쓴다.** 계획 1은 TF를 유지하고 `sources`에 "unused while lidar_use_tf"로 정직하게 적는다. 라인 추종(승인 레코드)과 안전 정책(TF)의 LiDAR 정면을 하나로 만드는 일 — TF를 레코드로 다듬거나 워커가 값을 쓰게 하기 — 은 계획 2(Gazebo에서 CORE 그래프의 TF 존재부터 확인) | `lidar_use_tf=False`는 장착 평행이동(footprint 증거)도 잃는다. 어느 쪽도 호스트 시험만으로 고를 수 없다 |
| 6 | 리졸버가 워커의 선언 타입·상한(선속 (0,1], 각속 (0,3])을 검사, revision은 파라미터만으로, `caps`는 (선속, 각속) 쌍, `cliff_enable`·`lidar_use_tf` overlay 허용 | 틀린 값이 워커 안에서 조용히 모든 판정을 무효로 만들지 않게 |
| 7 | `enforce` + `calibration.required: true`는 설정 오류("retired"), shadow/off는 경고 후 무시. 팩토리 인자는 명시적(오타는 모든 모드에서 TypeError), `mode_error`는 "예외 종류: 메시지" | D-47의 "보정되었거나 시작 거부"를 조용히 잃지 않게. 프로그래밍 오류가 그림자 off로 숨지 않게 |
| 8 | API v1.71(main이 v1.70이라 +1). `mode`·`mode_effective`·판정 값은 소문자 평문 문자열(설정 값과 같음, Enum 아님) — 캐싱 규칙 예외로 문서화. `last_stop`·`eval_ms`는 타입 모델, 여분 키 무시. 공급자 실패는 null + 예외 종류가 바뀔 때 한 번 로그 | 오래된 Fleet hub가 새 값 때문에 heartbeat 전체를 버리지 않게 |
| 9 | `configured_mode`는 `calibration` 키를 뺀 뒤 해석 | shadow에서 낡은 `required: true` 블록이 시작을 막지 않게(build_control_adapter와 같은 규칙) |
| 9 | **D-313 IR 라인 추종 대체 경로는 계획 3까지 쓸 수 없다**(`api/v1/line_follow.py`가 `adapter.calibration_revision`을 요구하는데, 보정 블록을 읽지 않으므로 항상 None → `IR_FALLBACK_NOT_READY`) | 어느 로봇도 어댑터를 켜지 않아 현장 영향 없음. 계획 3의 저장소 레코드가 이 값을 대신해야 한다 |
| 9 | enforce도 봉투로 CORE 속도 상한과 라인 추종 LiDAR 각을 받는다. 프로필 상한이 워커 범위(선속 1.0·각속 3.0)를 넘으면 shadow/enforce에서 시작 거부 | Pinky(0.2/0.8)는 해당 없음. 다른 로봇은 설정 오류로 드러난다 enforce는 CORE 속도 상한 봉투(Pinky 0.2 m/s·0.8 rad/s, 이전 워커 기본 0.014/0.10의 약 14배)를 받는다. 워커의 정지/해제 거리는 속도에 비례하지 않으므로, 계획 3이 정지 거리를 속도에 맞추거나 enforce용 봉투를 되돌리기 전에는 enforce를 켜지 않는다. |
| 6 | 그림자 해석 주의: 봉투를 올리면 빠른 명령이 정책에 닿지만 워커의 정지/해제 거리는 속도에 비례하지 않는다. 속도에서의 그림자 "allow"는 그 속도로 집행해도 안전하다는 증거가 아니다 | G-sim·G-dev 판정 기준에 반영 |

## 계획 2·3로 넘기는 일 (최종 검토)

- M-5: `control_sensor_adapter.py`의 죽은 D-47 로더 경로(`_load_required_calibration`, `calibration_loader`, `calibration_revision`/digest, `bound_parameters`, `lidar_mount` `adapter_parameters`)는 `api/v1/line_follow.py`의 `calibration_revision` 의존(D-313)과 함께 지운다. 되살리지 않는다.
- M-7: 그림자 info 이벤트가 허브 끊김 중 fleet-agent 버퍼(1000칸)의 항목을 밀어낼 수 있다. G-dev 전에 필터하거나 속도를 제한한다.
- M-8: 그림자 평가는 송신 뒤 동기로 돌아 다음 tick을 늦출 수 있다. G-sim·G-dev에서 Pi의 `eval_ms` p99를 재고, 넘으면 20 Hz로 낮춘다.
- M-9: `safety/manager.py`가 572/600줄이다. 계획 3의 HOLD/래치 로직은 형제 모듈에 둔다.
- M-10: `node.py` 조립은 ROS-SIM에서 동작으로 확인해야 한다(ROS 박스에서 `test_node_wiring`).
- TF와 승인된 LiDAR 장착 레코드(라인 추종)의 정면 값 통일.
- enforce 봉투: enforce는 CORE 속도 상한 봉투(Pinky 0.2 m/s·0.8 rad/s, 이전 워커 기본 0.014/0.10의 약 14배)를 받는다. 워커의 정지/해제 거리는 속도에 비례하지 않으므로, 계획 3이 정지 거리를 속도에 맞추거나 enforce용 봉투를 되돌리기 전에는 enforce를 켜지 않는다.
