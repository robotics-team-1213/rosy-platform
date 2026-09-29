## D-350 도크 하드웨어는 세 단계로 붙는다 — 각 단계에서 소프트웨어가 하는 일을 미리 정한다

**Status:** Accepted (2026-09-30, 소프트웨어 단계 계약·선구현 착수). Phase 2가 이미 구현돼 있고, Phase 1·3의 소프트웨어 경로를 이 변경에서 준비한다. 실물 조립·게이트는 별도 회차.

### Context

도크 하드웨어가 한 번에 완성되지 않는다. 충전선만 먼저 물릴 수도 있고, ESP32 전체가 떠도 카메라는 나중에 붙을 수 있다. 소프트웨어가 각 단계에서 뭘 하는지 미리 정하지 않으면, 하드웨어 단계마다 코드를 고치는 사태가 생긴다.

이미 있는 계약들이 각 단계를 지탱한다: DNC-005(충전 2소스), D-27(deep 셧다운 억제), D-28(도크 계약), D-192(부팅 토크 오프), D-200(DOCKING 모드 소유), D-347(capability lifecycle).

### Decision — 세 단계 정의

**Phase 1 — 선만 있음 (충전선 + 물리 접촉만, 계측 없음)**

- 도크: PD 충전기 + 트리거 + 2S 밸런싱 모듈 + 포고핀·자석. ESP32 없음.
- 충전 확인: **전압 단독** (1소스). 도크 전류 보고 없음.
- `ChargingConfirmation` degrade: `dock_says_charging` 항상 `False` → 전압 비하락만으로 판정. 안전 방향(비대칭)은 유지: 전압이 떨어지면 즉시 해제.
- `docking.supported: true` 가능하되, 도크 데이터베이스에 `instrumented: false` 명시. `/status` 폴링은 안 함.
- 만춫 HOLD: 전압이 만충 근처(≥8.2V)에서 유지 + 전류 종단 신호 없음 → `CHARGED_HOLD`. 판정 근거가 약하므로 `PHASE1` 마킹.
- D-27 억제: **Phase 1에서는 deep 셧다운을 억제하지 않는다** — 1소스만으로는 안전 경로를 끌 수 없다. 로봇은 앉아 있어도 셧다운 시계는 돈다.
- **역할**: 최소 검증 — 물리 접촉이 되는지, 자석 분리력이 예산 안인지, 로봇이 들어가는지.

**Phase 2 — ESP32 계측 도크 (현재 구현 대상)**

- 도크: Phase 1 + ESP32 (리밋 인터록, 전류 션트, 전압 분압, `/status`, 폴트 폴드백).
- 충전 확인: **2소스** (도크 전류 + 팩 전압 비하락). `ChargingConfirmation`가 그대로.
- `docking.supported: true`, `instrumented: true`. `/status` 폴링 운용.
- 만춫 HOLD: 전류 종단 (`charging: false` + `load_present: true`) + 전압 유지 → `CHARGED_HOLD`.
- D-27 억제: **2소스 확정 시에만** deep 셧다운 억제. Phase 1과 동일하게, 확정이 깨지면 즉시 재개.
- 재시도: 접촉 실패(`load_present: false`)는 최대 2회 백오프 재시도. 접촉됐는데 전류 없음(`load_present: true, charging: false`)은 폴트 보고, 재시도 없음.
- **역할**: 완전 자동 충전 — 배터리 임계부터 충전 확정·HOLD·재충전까지 무개입.

**Phase 3 — 향상 도크 (카메라·온도·기타 추가 센서)**

- 도크: Phase 2 + NTC(충전기·접점), 선택적으로 도크 측 카메라(시각 확인).
- 충전 확인: 2소스 + 온도 경계(NTC). `/status`에 `charger_temp_c`·`contact_temp_c`.
- 만춫 판정: 전류·전압 + 온도 안정(충전기가 뜨겁지 않음) → 신뢰도 상승.
- D-27 억제: 2소스 + 온도 정상. 온도 fault는 즉시 해제.
- **역할**: 장기 무인 — 열폭주 전조 감지, 접점 산화 조기 발견, Fleet 원격 진단.

### 소프트웨어 경로 (각 단계에서 코드가 하는 일)

| 기능 | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| 물리 접촉 감지 | 불가(오도메트리·IR로 추정) | 리밋 (`load_present`) | 리밋 + 온도 |
| 충전 확인 | 전압 단독 (1소스) | 도크 전류 + 전압 (2소스) | 2소스 + 온도 |
| D-27 억제 | ❌ (안전: 억제 안 함) | ✅ 2소스 확정 시 | ✅ 2소스 + 온도 |
| 만춫 HOLD | 전압 근사 | 전류 종단 + 전압 유지 | 전류·전압·온도 |
| 재충전 히스테리시스 | 전압만 | 전압 + 전류 재개 | 전압 + 전류 + 온도 |
| 재시도 | 없음 | 접촉실패 2회 / 전류없음 폴트 | 동일 + 온도 사전 점검 |
| 대시보드 | DOCKING (상태 불명) | CHARGING·HOLD·FAILED | 동일 + 온도 표시 |

### Phase 전환 감지

도크 데이터베이스(`docks.json`)의 `instrumented` 필드와 런타임 `/status` 폴링 결과로 판단한다:
- `instrumented: false` → Phase 1 경로
- `instrumented: true` + 폴링 OK → Phase 2 경로
- `/status`에 온도 필드 → Phase 3 경로 (전환은 자동, 추가 코드 불필요)

Phase 1→2 전환은 설정 변경만(`instrumented: true`). Phase 2→3 전환은 펌웨어 업데이트 후 자동.

### 이 변경에서 선구현하는 것

1. `ChargingConfirmation` degrade 모드 (Phase 1 전압 단독 판정)
2. 만춫 `CHARGED_HOLD` 상태머신 + `docked.full` 이벤트
3. 재충전 히스테리시스 (전압 임계)
4. 접촉 실패 vs 전류 없음 재시도 정책
5. `display/info` 충전 상태 표시
6. deploy `capabilities.dock-enabled.yaml` 오버레이

### Alternatives

- **Phase 1을 건너뛰고 Phase 2만:** 충전선만 있을 때 소프트웨어가 아무것도 못 하는 빈 공백이 생긴다. 기각.
- **Phase 1에서도 D-27 억제:** 1소스(전압만)로 셧다운을 끄는 건 안전 경로를 약화한다. 기각 — D-347 토론 합의("도크 단독 불신")의 Phase 1 판.
- **Phase 3을 지금 구현:** NTC가 미실장이고 카메라도 없다. 계약 슬롯만 준비하고 구현은 실물 이후. 채택.

### Transition / validation

- Phase 2의 372 기존 시험은 전부 유지. 신규: degrade 모드 시험, CHARGED_HOLD 전이 시험, 히스테리시스 시험, 재시도 정책 시험, display 표시 시험.
- `docking.supported: false → true` 전환은 D5 통과 후 deploy 오버레이로 (게이트 불변).

**Consequences:** 하드웨어가 어떤 단계로 오든 소프트웨어는 코드 변경 없이 해당 단계의 기능을 제공한다. Phase 1은 최소 검증용이고, D-27 억제는 Phase 2부터 — 이게 "충전선만 물었다고 안전 경로가 꺼지는" 사고를 막는다.

**References:** [D-28 도크 계약](D-28-nav2.md), [D-347 capability lifecycle](D-347-capability-lifecycle-vocabulary.md), [D-349 코드 준비 기록](D-349-dock-auto-charge-code-readiness.md), `docking/charging.py`, `firmware/dock/README.md`.
