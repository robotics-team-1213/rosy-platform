## D-353 외부 장비 설계는 바뀐다 — 바뀌어도 코드가 아니라 설정·전략이 바뀌게 한다

**Status:** Accepted (2026-09-30, 구조 결정 + 봉합점 3개 구현).

### Context

D-349~352로 도크·신호등의 소프트웨어가 준비 완료다. 그런데 실물을 만들다 보면 설계가 바뀐다 — 자석 배치가 바뀌고, 충전 방식이 바뀌고, 센서가 붙었다 빠지고, 로봇 모델이 바뀐다. 지금 코드에서 바뀔 수 있는 것과 코드 수정이 필요한 것의 경계를 명확히 하지 않으면, 프로토타입 반복마다 소프트웨어를 고치는 사태가 생긴다.

**현재 유연성 실측:**

| 경계 | 지금 상태 | 설계가 바뀌면 |
|---|---|---|
| 도크 기종 (DockType) | ✅ 데이터 기반 (docks.json) — 새 기종은 파일 추가만 | 설정 변경 |
| 검출기 (DockDetector) | ✅ Protocol — 새 검출기는 클래스 추가만 | 코드 추가 (경계 뒤) |
| 모션 (DockingExecutor) | ✅ Protocol — 브리지가 구현 | 코드 불변 |
| **충전 확인 알고리즘** | ❌ `ChargingConfirmation.update()` 하드코딩 | **클래스 수정 필요** |
| **HTTP 폴링 패턴** | ❌ DockAgent에 인라인, 신호등은 별도 구현 | **중복 수정 필요** |
| **만춫 판정** | ❌ manager._check_full() 하드코딩 | **매니저 수정 필요** |

### Decision — 봉합점 3개

**1. 충전 확인 전략 (ChargingStrategy)**

`ChargingConfirmation`의 `update()`를 Protocol로 뽑는다. 기본 구현은 지금의 2소스 (전류+전압 비하락). 새 배터리 화학·무선 충전·온도 기반 확인이 필요하면 새 전략을 `DockingConfig.charging_strategy`로 끼운다.

```python
class ChargingStrategy(Protocol):
    def update(self, status: DockStatus, voltage: float | None, now: float) -> bool: ...
    @property
    def confirmed(self) -> bool: ...
    def reset(self) -> None: ...
```

기존 `ChargingConfirmation`이 이 Protocol을 구현하도록 한다 — 기존 시험은 전부 그대로 통과한다.

**2. 공통 HTTP 폴링 유틸리티 (device_poll)**

`DockAgent`와 `SignalClient`(Fleet)가 공유하는 폴링 함수를 `core_common`에 둔다:
- `urllib` (표준 라이브러리만, HTTP 클라이언트 의존성 없음)
- 4상태 실패 enum (`unreachable/timeout/bad_response/ok`)
- 필수 필드 검증
- 타임아웃 보장

새 외부 장비(온도 센서·카메라)가 이 함수를 호출하면 폴링 패턴이 자동으로 통일된다. D-352의 "3번째 소비자가 생기면 추상화" 조건이 아니라 **유틸리티 함수**로 — 추상 클래스보다 가볍고, 소비자가 함수를 안 쓰면 그만이다.

**3. 만춫 판정 전략 (FullChargeStrategy)**

manager의 `_check_full()`을 Protocol로 뽑는다. 기본 구현은 전압 임계 (D-350). 전류 종단 기반·온도 안정 기반 등이 필요하면 새 전략을 `DockingConfig.full_charge_strategy`로 끼운다.

### 설계 변경 시나리오와 대응

| 시나리오 | 바뀌는 것 | 코드 수정 |
|---|---|---|
| 자석 배치 변경 | DockType (docks.json) | 없음 |
| 다른 충전기 모듈 | DockingConfig 임계값 | 없음 |
| 무선 충전 (전류 없음) | `ChargingStrategy` 새 구현 | 새 파일 1개 |
| 다른 로봇 (다른 팩) | DockingConfig 전압 범위 | 없음 |
| 온도 기반 만춫 판정 | `FullChargeStrategy` 새 구현 | 새 파일 1개 |
| 새 외부 장비 (온도 센서) | `device_poll()` 호출 | 새 파일 1개 |
| 여러 도크 (풀) | DockDatabase 스키마 | 없음 (이미 지원) |

### Alternatives

- **지금 그대로:** 프로토타입 반복마다 manager·ChargingConfirmation을 수정한다. 기각.
- **전체 전략 패턴 (모든 단계를 Protocol로):** 과잉 — DockType·Detector·Executor는 이미 충분히 유연하다. 충전 확인·만춫 판정만 봉합하면 족하다. 기각.
- **플러그인 시스템 (entry_points):** 지금은 하나의 로봇·하나의 도크. 설정 주입으로 충분하다. 기각.

### Transition / validation

- `ChargingStrategy` Protocol 정의 + `ChargingConfirmation`이 구현하도록 `update` 시그니처 유지
- `FullChargeStrategy` Protocol 정의 + manager의 `_check_full` 로직을 기본 구현으로 이동
- `core_common/device_poll.py` 유틸리티 신설 (DockAgent가 내부적으로 사용)
- 기존 시험 전부 통과 (Protocol은 구현을 강제하지 않는다 — duck typing이므로 기존 클래스가 자동으로 구현)

**Consequences:** 프로토타입 반복에서 소프트웨어 수정이 "새 파일 1개" 또는 "설정 변경"으로 제한된다. manager·ChargingConfirmation 본체는 안정화된다.

**References:** [D-350 단계](D-350-dock-hardware-phase-tiers.md), [D-352 공통 패턴](D-352-external-device-shared-pattern.md), `docking/charging.py`, `docking/manager.py`, `core_common/device_poll.py`.
