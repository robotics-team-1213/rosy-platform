## D-352 도크·신호등은 같은 패턴의 외부 장비다 — 공통 클라이언트·상태·준비 프레임을 공유한다

**Status:** Accepted (2026-09-30, 구조 결정 + 패턴 정리). 구현은 이 변경에 포함.

### Context

도크(ROSY-DOCK-001)와 신호등(ROSY-SIGNAL-001)은 둘 다 ESP32 + HTTP 계약 + 폴링 + 실물 대기 상태다. 그런데 서로를 참조하지 않고 각자 발전했다. 두 계약서의 선배 관계는 명시돼 있지만(신호등 README가 "독과 동일" 패턴을 인용), 코드·시험·준비 프레임은 공유되지 않는다.

**공통점 (이미 우연히 일치):**

| 속성 | 도크 | 신호등 |
|---|---|---|
| MCU | ESP32 + NVS | ESP32 + NVS |
| 방향 | 로봇이 폴링, 장비는 연결 안 열음 | Fleet이 폴링+명령, 장비는 연결 안 열음 |
| 필수 필드 누락 | 오류 (기본값 안 채움) | 오류 (기본값 안 채움) |
| 페일세이프 | 출력 차단 (de-energize) | 전등 적색 점멸 |
| 자격증명 | NVS (소스 밴) | NVS (소스 밴) |
| 시험 | test_dock_contract.py (소스 스캔) | test_signal_contract.py (소스 스캔) |
| 실물 | bench 1기 대기 (D-350 Phase 준비) | bench 대기 (E1–E3 인수 계획) |

**차이 (설계적, 통일하면 안 됨):**

| 속성 | 도크 | 신호등 |
|---|---|---|
| 폴링 주체 | 로봇 CORE | Fleet 서버 |
| 명령면 | 없음 (read-only /status) | 있음 (POST /command, 토큰 인증) |
| 페일세이프 방향 | 수동 (아무것도 안 함) | 능동 (적색 점멸) |
| 안전 역할 | 충전 안전 (D-27 억제 입력) | 표시 장치 (안전 인터록 아님 — AGENTS 명시) |

### Decision

**1. 폴링 실패 어휘를 통일한다.** 도크의 `DockReachability` 4상태(unreachable/timeout/bad_response/ok)를 신호등 클라이언트에도 적용한다. "장비가 답 안 함"과 "답했는데 내용 이상"은 복구 전략이 다르다 — 이 구분이 어휘마다 다르면 운영자가 혼란한다.

**2. 외부 장비 클라이언트 패턴을 문서화한다.** `urllib` 단순 폴링 + 타임아웃 + JSON 파싱 + 필수 필드 검증 + 실패 enum. 이 패턴이 도크·신호등·향후 장비(예: 온도 센서)의 표준이 된다. 별도 추상 클래스를 만들지 않는다 — 패턴 문서로 족하다. (추상화는 3번째 소비자가 생기면 그때.)

**3. 장비 준비 프레임을 통일한다.** 도크의 Phase 1/2/3(D-350)과 신호등의 E1–E3(인수 계획)을 같은 어휘로 표현한다:
- **wire** — 물리 연결만, 계측 없음 (도크 Phase 1, 신호등 E1 전)
- **instrumented** — MCU 있음, 상태 보고 가능 (도크 Phase 2, 신호등 E1)
- **verified** — 폐루프 확인 (도크 Phase 2 + D5 통과, 신호등 E2)

이 어휘는 D-347 capability lifecycle과 정합한다: `ready` = verified, `unavailable` = 미장착·고장, `activating` = 승격 중.

**4. 도크-교통 정책 조정을 명시한다.** 로봇이 DOCKING 모드에 들어가면 traffic_policy는 자동으로 ADVISORY로 강등한다(D-200 모드 우선순위가 보장). 하지만 이것이 암묵적 부수효과가 아니라 **명시적 계약**이어야 한다:
- DOCKING 진입 → `traffic_policy.mode` → `ADVISORY` (ENFORCED 유지 불가)
- DOCKING 종료 → 배터리 정책이 교통 상태를 복원
- 도킹 중 신호 위반(`signal_conflict`)은 도킹을 중단하지 않는다 — 도킹이 우선한다 (priority 4 > 5)

**5. 계약서 상호 참조를 갱신한다.** 도크 README와 신호등 README가 공통 패턴·준비 프레임을 상호 참조한다.

### Alternatives

- **공통 추상 클래스 (`ExternalDeviceClient`):** 3번째 소비자가 없다. 조기 추상화는 잘못된 경계를 굳힌다. 기각 — 패턴 문서로 족하다.
- **각자 독립 유지:** 이미 6개 속성이 우연히 일치한다. 의도적 공유로 바꾸면 다음 장비가 이 패턴을 따른다. 채택.

### Transition / validation

- `SignalReachability` enum 추가 (신호등 클라이언트에 도크와 동일한 4상태 적용)
- 도크·신호등 README에 상호 참조·준비 프레임 추가
- traffic_policy manager에 DOCKING 진입 시 ADVISORY 강등 명시
- `docs/plans/2026-09-30-external-device-readiness.md` — 전체 장비 준비 상태 한 장

**Consequences:** 다음 외부 장비(온도 센서·카메라 등)가 같은 패턴을 따르는 것이 자명해진다. 도크와 신호등의 운영자는 같은 어휘로 두 장비의 상태를 읽는다.

**References:** [D-28 도크 계약](D-28-nav2.md), [D-347 lifecycle](D-347-capability-lifecycle-vocabulary.md), [D-350 도크 단계](D-350-dock-hardware-phase-tiers.md), `firmware/dock/README.md`, `firmware/signal/README.md`, `docs/plans/2026-09-22-signals-acceptance-plan.md`.
