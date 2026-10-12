# D-718 CORE 적용 시점의 조건부 막힘 답

**Status:** Accepted (2026-10-12, source contract)

## Context

D-717은 진행 중인 BACKING/SETTLING의 중복 후진을 차단했다. 그러나 Fleet 조회 뒤 사람의 WAIT가 도착하거나 CORE local fallback이 먼저 진행되면 모델 후보가 조회 당시 상태에 대한 답인지 검증할 수 없다. D-716의 단일 제출 경로에 적용 시점 검증이 필요하다.

## Decision

기존 POST `/api/v1/line-follow/stuck/decision`의 BACK_AND_RETRY에 선택 `expected_stuck: {phase: "ASKING", attempts: nonnegative strict integer}`를 추가한다. 닫힌 공통 LineStuckPrecondition schema를 API와 Fleet HttpRobotClient가 함께 사용한다. 불명 필드·누락·bool/문자열/음수 시도 수·다른 phase는 거절한다. 다른 decision에 붙이면 VALIDATION_ERROR다.

CORE는 기존 manager lock 안에서 stuck_id와 현재 phase/attempts를 확인하고 같은 잠금 아래 기존 후진 안전 검사를 거쳐 적용한다. 조건 불일치는 기존 STUCK_DECISION_REFUSED와 `stuck_precondition_failed` 사유로 거절하며 타이머·시도·답 선택을 바꾸지 않는다. 후속 막힘은 새 stuck_id를 사용하고 빠른 재막힘의 시도 계승은 유지한다.

조건을 보내지 않는 기존 사람·규칙 요청의 계약은 유지한다. 이 선택 필드는 모델 후보의 근거·운영 수용·단일 소비·예산 검증을 대신하지 않는다. 기존 CORE 로컬 타이머·거리·속도·최종 cmd_vel 권한은 그대로다. envelope protocol_version은 1.0, 공유 API 문서 MINOR는 v1.218이다.

## Verification and consequences

사람 WAIT·CORE local fallback·시도 불일치·같은 ASKING 조건 수용과 malformed 입력을 실제 상태 기계/API/HTTP transport 회귀로 확인한다. 독립 안전 검토·원격 통합·로컬 착지 후에도 모델 후보 생산/dispatch·운영 receipt·배포·현장 수용은 별도다.
