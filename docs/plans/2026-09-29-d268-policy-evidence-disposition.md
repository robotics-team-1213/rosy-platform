# D-268 정책 적격 증거 처분 — Proposed 유지와 승격 준비 사다리

작성일: 2026-09-29
상태: [D-268](../adr/D-268-policy-eligible-vision-evidence-for-fleet-tasks.md)의 처분 기록. ADR 승격·기각·자동 실행 개방이 아니다.

## 처분

**D-268은 Proposed를 유지한다.** 이유는 두 가지다.

1. **승격 전제가 하나도 충족되지 않았다.** D-268 자체의 Validation/Transition이 Accepted 전환 조건으로 요구한 다섯 가지(아래 표)가 전부 미완성·미측정이다. 지금 상태를 바꾸면 ADR 스스로 정한 전환 조건을 무시하는 첫 사례가 된다.
2. **기각·대체할 이유도 없다.** 핵심 결정 — sighting은 표시·대조 전용, 자동 작업은 별도 타입의 정책 적격 증거로만, 자격 증명 기반 출처 identity, 300 ms 신선도, 사전 등록 수용 기준 — 은 갭맵 이후 착지한 D-326(증보본)·D-327·D-328 구조에서 오히려 재확인됐다. D-328의 목표 predicate·독립 증거 판정(`goal_evidence.py`)이 "별도 타입의 증거 계약"이라는 D-268 Decision 2의 방향을 먼저 보여줬다.

따라서 갭맵 항목 1("D-268의 Accepted/기각 여부")의 답은 **"둘 다 아니다 — Proposed가 현재의 올바른 상태이며, 승격을 막는 것은 결정이 아니라 측정이다."** 이다. 폐루프 개방(D-326 Decision 3)은 이 처분으로 열리지 않는다.

## 승격 전제 대조

D-268 Validation/Transition이 요구한 다섯 조건과 2026-09-29 소스의 대조:

| # | D-268의 전제 | 현재 상태 | 근거 |
|---|---|---|---|
| 1 | 정책 적격 증거 계약의 API Reference/schema 설계(D-18) | **미완.** sighting은 표시 전용으로 명시되고 증거 계약은 없다. 단, 별개 면인 **목표 성공 증거**는 착지: 사전 등록 predicate(`object_in_destination`·`camera_observation` 강제), `evidence_id`·`evidence_revision`·`observed_at`·`satisfied`, 출처/predicate/대상 일치와 age 상한 검증, 불일치 시 `GOAL_EVIDENCE_REJECTED` | `core_common/protocol/sightings.py` 헤더("not eligible input for automatic work"), API Ref v1.26/v1.28, `fleet/server/goal_evidence.py` |
| 2 | 정책·권한 검증 | **부분.** 작업 경로가 `source`·`actor_id`·`request_key`·`evidence` 형태를 검증하고 D-276 역할 체계가 있으나(`policy-admin` 예약), D-268 Decision 3의 "폐기 가능한 자격 증명에서 서버가 출처를 결정"하는 제출 경로는 없음 | `task_service.py` `submit_navigation`, `deploy/site/site-users.yaml.example` |
| 3 | 정답 데이터 기반 LOCAL 시험 | **없음.** goal-evidence/mission 시험은 SOURCE/LOCAL로 있으나(D-328 Transition 1) 그것은 성공 판정 면이고, D-268이 요구하는 검출 파이프라인의 정답 대비 오차 시험이 아니다 | `src/site/fleet/test/` |
| 4 | 30분 이상 현장 스트림의 end-to-end age/가용성 측정 | **없음.** overhead는 DEVICE/FIELD PARKED, 실물 측정 기록 없음 | `src/site/overhead/logs.md`, `docs/validation/` |
| 5 | 사전 승인 검출·오탐 기준의 입회 DEVICE/FIELD 수용 | **없음.** 수용 기록 양식·규칙(threshold/holdout 사전 동결, 오탐 보고 단위)은 설계돼 있으나 측정된 기록 0건 | `2026-09-26-ubuntu-site-fleet-vision-workflow.md` §Automatic-source acceptance record |

## 갭맵 이후의 새 맥락 정합

갭맵과 D-326 작성 뒤 같은 날, 다른 세션의 커밋(`7e6a8539`…`af038631`)으로 맥락이 확장됐다. D-268과의 정합:

- **두 증거 면의 구분.** D-268 증거는 자동 작업의 **발의(시작) 자격**을 푸는 것이고, D-328 목표 증거는 Mission의 **성공 판정**을 확정하는 것이다. 소비자가 다르므로 어느 하나가 다른 하나를 대신하지 않는다. 권고: 첫 증거 계약을 D-18 사이클에서 설계할 때 **제출·검증 기반(자격 증명 출처 identity, 신선도, revision 일치, 서버 측 거절 사유)은 하나로 공유**하고 **소비(발의 승인 vs 목표 판정)는 분리**한다. 이는 본 문서의 제안 기록이며, 그 설계 문서가 확정한다.
- **밸브는 그대로.** `task_service.py`의 `POLICY_DISPATCH_ENABLED = False`를 재확인했다(16행). D-330의 단일 발행 권한(`dispatch_admission.py`의 내구 claim)과 mission 실행기(`mission_service.py`·`mission_store.py`)는 발행 중복을 막는 구조일 뿐 증거 자격을 부여하지 않는다.
- **D-331 ER 2 provider는 무관하게 안전.** `fleet/ai/er2_standard.py`·`candidate.py`는 상태 비저장·제안 전용이라 실행권이 없고, D-268 승격 여부와 무관하게 그대로 된다.
- **이웃 상태.** D-257·D-267·D-269도 여전히 Proposed, D-271은 Accepted. D-268 승격은 이웃 수용과 별개로 위 표의 전제를 스스로 충족해야 한다.

## 승격 준비 사다리

각 단계가 위 표의 전제에 1:1로 대응한다. 순서를 건너뛰지 않는다.

| 단계 | 결과물 | 통과 조건 |
|---|---|---|
| 1. 증거 계약 설계 | 정책 적격 증거 endpoint·필드·자격 증명을 API Ref + `core_common.protocol.schemas` 동시 개정(D-18). goal-evidence가 보인 패턴(사전 등록 predicate, revision, age 상한, 명시적 거절 사유)을 발의 접점에 재사용 | 계약 시험이 생산자·소비자를 같이 검사. 제출 기반의 목표 판정 공유 여부를 이 문서에서 확정 |
| 2. 권한·정책 검증 | `policy-admin` 활성 경로, 자격 증명 발급·만료·폐기, 서버 측 출처 결정 | 위조·재생·만료 자격 증명이 거부되는 시험 |
| 3. 정답 데이터 LOCAL 시험 | 검출→증거 파이프라인의 정답 대비 오차 재현 | 사전 동결 holdout에서 측정. 사후 조정 없음 |
| 4. 현장 스트림 측정(DEVICE) | 30분 이상 end-to-end age/가용성 | p50/p95/max와 가용성이 계약 상한 안 |
| 5. 입회 수용(FIELD) | 사전 등록 검출·오탐 기준의 수용 기록 | 전 단계 통과 + 자동·수동 중지·재조회 경로 검증. 그때 D-268의 Accepted 전환을 검토 |

중단 규칙은 D-268 본문 그대로: 하나라도 미통과·불명확이면 automatic source는 비활성에 둔다.

## 근거와 제한

- 근거: `goal_evidence.py`·`mission_service.py`·`dispatch_admission.py`·`task_service.py`·`er2_standard.py` 전문 또는 해당 부분 읽기, ADR 로그(D-257/D-267/D-269/D-271/D-326~D-331 상태), `2026-09-29-er2-adr-consistency-review.md`, API Ref 변경 이력. 계약 시험은 아래 실행 기록 참조.
- 본 문서는 D-268의 상태를 바꾸지 않았고(로그·목차 무변경), automatic source·`POLICY_DISPATCH_ENABLED`·어떤 endpoint도 열지 않았다.
- 장치·현장 측정이 없으므로 4·5단계의 수치 판단은 하지 않는다. 측정이 생기면 이 문서의 표를 채우고 D-268 전환을 별도 변경으로 다룬다.
