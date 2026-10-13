# Pinky 읽기 전용 사건 worker — D-684 Phase 4

## 범위와 책임

Fleet의 기존 `StuckResolverLoop`가 수집한 동일 poll을 opt-in
`IncidentCaseWorker` mailbox에 전달한다. CORE 판단·명령 경로는 그대로 유지한다.
모델은 검증된 v2 판단과 승인된 `get_incident_status` 읽기 요청만 제안한다.
worker는 다음 poll의 같은 사건 관측을 읽고, 필요하면 reviewer를 호출한다.
모델 합의나 선언한 success_check는 사건 종결 증거가 아니다.

- 정상 상태: 기존 Fleet 판단 receipt를 사용하고 모델·새 사건 원장 생성은 0회.
- 문제 상태: primary, 조건부 reviewer, 새로운 CORE 관측을 사건 총예산 안에서 처리.
- 종결: 원래 사건이 `cleared`로 닫히고 이후 최신 정상 CORE 관측이 일치할 때
  `RESOLVED_OBSERVED` receipt. 로봇 동작 성공·정책 품질 통과를 의미하지 않는다.
- 미해결: HOLD와 durable pending FINAL. outbox callback True는 큐 기록을 의미하며
  발송·사람 인수는 기존 outbox/claim 경로에서 별도로 확인한다.

## 고정 경계

기본 disabled이며 두 frozen profile에 대한 trusted admission을 모두 요구한다.
profile 전체 canonical SHA, CORE owner, 정책 revision, original case를 묶는다.
deadline은 최대 120초, calls/observations 각각 최대 8회, 비용 최대 10 USD이며
호출자에게 명시적 `CaseBudget`을 요구한다. primary/reviewer 별 호출 한도와
전역 한도를 같은 SQLite transaction에서 예약한다. 재시작·새 revision·모델 변경으로
예산을 초기화하지 않는다. trusted FleetBaseline이 없으면 Fleet/Qwen 불일치를 추정하지 않는다.

reserve 전에 효과를 실행하지 않는다. 예약·SUBMITTING·terminal DB 작업 중 취소도
실제 thread commit이 끝날 때까지 기다린 후 본인 worker의 효과만 정리한다.
provider 진입 전 취소는 REJECTED/비용 0, 진입 뒤 불명확한 결과는 UNKNOWN과
보수적 예약 유지다. 이미 확인된 결과·비용은 terminal 취소로 덮어쓰지 않는다.
첫 parent 생성과 creator worker_id/original revision도 같은 transaction이다.
외부 worker의 살아 있는 SUBMITTING은 자동 회수하지 않는다.

완료된 모델 호출 이후 read-intent를 잃은 재시작은
`READ_CONTINUATION_NOT_ADMITTED` HOLD로 처리한다. 자동 resume은 아직 미승인이다.
`prepare_receipt`는 outbox의 동일 Fleet DB transaction에서 OPEN 전에 parent를 준비하며
commit/rollback 소유권을 가져가지 않는다. callback 실패·미설정은 다음 fresh poll에서
FINAL만 재시도하고 모델 호출을 추가하지 않는다.

## 구현 및 검증

1. durable store의 역할별 예약, 첫 생성 ownership/origin, pending FINAL/queue receipt.
2. background mailbox worker와 trusted observed closure producer.
3. 기존 loop의 선택적 feed/aclose, 기본 경로 회귀 유지.
4. 실제 outbox 연결: managed OPEN 억제, 첫 UNKNOWN 및 재관측 예산 소진 FINAL.
5. 독립 source review 후 ledger 책임 추출과 구조 guard 재측정.

commit `050ae33f97` 기준 7-suite 원격 시험:
Model PC resource floor 충족(9.0 GB), **158 passed, NEW 0**.
로그 `X:/DevTemp/projects/rosy-platform/2026-10-12--044435--incident-case-worker--8d6f18/logs/creator-green/run-1.txt`,
SHA256 `55f3216c53e4f4c96019d0e32bd0c4411cf19eb04710e431af30f32d113de1c1`.
예약/submit/terminal/첫 parent commit 취소, 반복 취소, 외부 in-flight,
재시작 read 한도, stale known billing, 정책 변경, 같은 사건 정상 관측,
실제 outbox pending/retry, 기존 loop/handoff/notification 회귀를 포함한다.

notification 정책 변경 수정과 실제 worker→outbox 회귀를 합친
commit `1014551aa4` 재시험은 AI PC
resource floor 충족(9.0 GB), **161 passed, NEW 0**이다.
로그 `X:/DevTemp/projects/rosy-platform/2026-10-12--044435--incident-case-worker--8d6f18/logs/policy-integration-floor-green/run-1.txt`,
SHA256 `260720c09377fec2c2a268d0ebb705ab96121b2fdc8d08f5496393500a783b34`.
원래 정책 scope는 유지하며, 정확히 `POLICY_CHANGED` HOLD의 진단 인수만
현재 trusted 정책의 같은 CORE 사건 관측을 허용한다. 모델 호출은 0회다.

원격 resource floor fallback 경고가 있었던 이전 terminal-green 결과는 수용 근거로
쓰지 않는다. 최종 GREEN은 자원 기준을 충족한 재시험이다.

이 단계는 소스와 mock/SQLite 회귀 근거다. 실제 모델 호출·유료 호출·네트워크 발송·
로봇 명령·현장 활성화는 0회이며, production factory/config는 연결하지 않았다.
전체 v2 checked model receipt 및 독립 평가 export는 후속 Phase 6 책임이다.
현재 summary에는 검증 성공의 verdict/choice/payload SHA/관측 revision만 제한 저장한다.

## 구조 checkpoint

physical source: worker286, closure46, observation81, store287, contract82, init1.
automation 합계783은 기존 baseline322+150을 초과한다. 승인된 책임 추출은
`automation/ledger/{store,contract,__init__}` 실제 구현 이동이며 기존 경로는
identity를 유지하는 명시적 compatibility facade로만 남긴다. 구조 registry 편집자는
독립 reviewer 한 명이다. 추출·실측·구조 시험 전에는 착지 준비 완료로 보고하지 않는다.
