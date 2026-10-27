# D-865 Fleet 정책 승인 — 실행 설계

**Status:** 설계 문서(2026-10-25). 결정의 정본은 [ADR D-865](../adr/D-865-fleet-policy-admission.md)이고 이 문서는 단계·산출물·검증·인계를 관리한다. 활성화 증거가 아니다.

**Spec:** [D-865](../adr/D-865-fleet-policy-admission.md) · [FLEET SRS](../spec/ROSY%20FLEET%20SRS.md) MSN-006 · MSN-007 · UI-WORK-001

## 목표

사람이 승인 범위를 정하면, 그 범위 안의 `one_person`(drive-only) 승인 종류 Mission/Cell Job이 사람 클릭 없이 Fleet 정책에 의해 admit되고, 모든 기존 admission·fence·law 검사와 감사 기록은 그대로 유지된다. 범위 밖(`two_person`, legacy `proposer_only`, Task 정책 경로)은 이 계획이 열지 않는다.

## 현재 기반과 빈 곳

| 기반 | 위치 | 상태 |
|---|---|---|
| 승인 등록부(two_person/proposer_only/one_person)·admit·generation 검사 | `missions/mission_routes.py:442-476`, `server/step_action_kinds.py:33-37` | 동작 중, 사람 전용 |
| mission admit 상태 기계·자원 claim·fence | `missions/mission_store.py:279-320,322-422`, `server/dispatch_admission.py` | 동작 중 |
| 전송 직전 재검사·UNKNOWN 금지 | `missions/mission_dispatcher.py:61-117` | 동작 중 |
| 제안 resolve의 자동화 가능 경로(service principal) | `missions/mission_routes.py:301-359` | 동작 중 |
| 범위 선례: 사이트 설정 로봇 목록 | `fleet/stuck/cli_config.py:40-56`(D-685), `fleet/stuck/ai_first.py:50-60`(D-610) | 동작 중, readback은 ai_first만 |
| 승인 범위 객체·정책 principal admit·범위 readback | — | **없음(이 계획이 만든다)** |

Task 정책 경로(`policy_evidence`, `POLICY_DISPATCH_ENABLED`)는 이미 만들어져 있으나 이 계획과 별개다. 관측 종류 등록표가 비어 있고(`policy_evidence.py:45`) `cli.py`가 증거 저장소를 연결하지 않는 등 활성화 전제가 갖춰지지 않았다. 그대로 둔다.

## 설계

### 승인 범위(scope) 객체

- 사이트 설정 `fleet.policy_admission` 섹션(`cli_config` 방식 adapter) — 필드: `robots`(frozenset, D-685 패턴), `step_approval_kinds`(1차 `["one_person"]`), `max_admits`, `valid_until`, `scope_revision`.
- 콘솔 전환은 D-610 `ai_first` 패턴(설정 값 + 메모리 스위치 + named operator toggle). 재시작은 설정을 다시 읽는다.
- Readback `GET /api/fleet/policy-admission`(enabled, robots, kinds, 잔여 상한, scope_revision)과 감사 목록. 경로·스키마는 P1에서 API reference와 `core_common.protocol`에 한 세트로 반영한다(D-18).
- 범위 해제는 새 자동 admit만 막는다(진행 중 READY/RUNNING은 기존 fence·정지 경로를 따른다).

### 자동 admit 실행점

1. 대상: `decidable()` 결과 승인 종류가 전부 `one_person`이고 자원·로봇이 범위와 일치하는 PROPOSED Mission/Cell Job.
2. 사람 admit과 같은 검사를 전부 재사용한다: 제안 digest 재비교(`EVIDENCE_OR_CAPABILITY_CHANGED`), `dispatch_enabled`·`expected_generation`(`MissionConflict`), 자원 claim 예약, proposer 분리 규칙 유지.
3. 통과하면 `mission_service.admit`을 principal `fleet-policy-admission`(scope_revision 포함)로 호출하고 감사 원장에 자동 승인 사실과 범위 근거를 남긴다.
4. law(FL-*)·E-stop·사람 점유·UNKNOWN은 기존 경로 그대로 사람에게 돌아간다. 자동 admit이 이 검사를 우회하지 않는다.
5. 화면 표시: work 뷰 승인 대기 행에 자동 승인 범위 소속 표시(`auto_admit` 배지, `auto_hold:<reason>` 접두 방식과 같은 표기 규칙).

### 보존·비목표

- `POLICY_DISPATCH_ENABLED`, `policy_evidence` 관측 종류, Task 정책 경로 활성화 — 바꾸지 않는다.
- `two_person`(팔 단계)·`proposer_only` 자동 승인 — 열지 않는다(별도 승인·safety 검토).
- 업무 앱의 자기 승인·범위 설정 화면 — 만들지 않는다(Harbor ADR 0004 A11).
- D-856 compile 사전 검증과 독립적이다.

## 단계

### P0 — SRS 보완안

**상태:** 착지(2026-10-25) — MSN-008 신설, MSN-006·MSN-007·UI-WORK-001 보강.

**Owner:** 이 계획 담당 · **산출물:** MSN-006(정책 승인 경로), MSN-007(범위와 lease의 관계 불변), UI-WORK-001(자동 승인 표시) 보강 초안 · **Exit:** SRS 편집이 계약 위반이 아닌지 `docs/spec` 기준 확인.

### P1 — API·스키마

**상태:** 착지(2026-10-25) — v1.314 선점, `protocol/policy_admission.py`·스키마 시험·API Ref v1.314 절. SRS MSN-008 계약 줄의 v1.314 갱신은 P0 착지 뒤 P2 브랜치에서 반영한다.

**산출물:** API reference 버전 선점(`api_reserve.py`) 후 범위 readback/감사 경로·스키마 추가. `core_common.protocol` 신규 모듈(범위 상태·감사 이벤트). · **Files:** `docs/reference/ROSY API & Protocol Reference.md`, `contracts/foundation/core_common/protocol/` · **Exit:** protocol 정렬 시험 통과(`test_protocol_version_alignment.py`).

### P2 — 서버 구현

**상태:** 착지(2026-10-25~26, 로컬 main) — P2a 판정 core, P2b HTTP 표면·사이트 설정 연결, P2c 자동 admit 루프·내구 감사 상한(`missions/policy_admission*.py` 계열, `481325d261`·`1283525eec`·`b92f8a165f`부터의 연속).

**산출물:** `cli_config` adapter, 범위 객체·스위치·readback, 정책 principal admit 경로, 감사 기록, 회귀 시험(신규 `test_policy_admission*.py` + 기존 `test_mission_store`·`test_mission_dispatcher`·`test_dispatch_stop_latch` 확장). · **주의:** `missions/`는 safety_modules 밖이지만 `console.py`·`task_dispatch_routes.py` 등을 만지면 D-430 §5 `Safety-Review:` trailer와 독립 리뷰가 필요하다. 범위를 최소로 잡아 missions 경로 안에서 끝내는 것을 먼저 본다. · **Exit:** E-stop·generation 변경·범위 밖 제안·digest 불일치가 전부 거절/HOLD되는 회귀 통과.

### P3 — 콘솔 표시

**상태:** 구현·원격 시험 완료(2026-10-27) — 브랜치 `feat/policy-admission-console`. work 뷰 승인 대기 행의 자동 승인 배지, work 개요의 범위 readback 패널과 기명 운영자 전환. 판정은 순수 함수로 분리(node 시험), readback 부재·404는 fail-closed로 배지를 끈다. 새 콘솔 자산이 없어 allowlist·CSP는 그대로다. · **Files:** `applications/fleet/web/work/`, `console-refresh.js` 패턴 재사용 · **Exit:** 콘솔 계약 시험 통과 — 모델 PC 원격 `ROSY_RUN_BROWSER_TESTS=1` `test_work_overview_browser.py` 36 통과(신규 3건 포함)·known_failures NEW 0, `test_server_app`·`test_remaining_platform_installed` 50 통과·NEW 0.

### P4 — 원격 회귀·착지

**산출물:** `remote_pytest` 로그·known_failures 비교, `tools/land.py --tests auto` 착지. · **Exit:** 0 NEW으로 main 착지. 착지는 현장 활성화가 아니다.

### P5 — 현장 수용

**산출물:** `docs/validation/policy-admission-<날짜>/` — 범위 설정 readback, 첫 실제 자동 admit의 원장·감사 대조, 해제 동작 확인. · **Exit:** 사용자 수용 기록.

## 인계

- 이 문서의 단계 P1부터는 각각 별도 브랜치·착지 단위다(한 브랜치 한 주제).
- Harbor 쪽 영향 없음(앱은 기존 제안 경로 그대로). `application-contract-support.md`의 승인 의미 보강은 ADR D-865 착지에 포함됐다.
