# D-718 CORE 적용 시점의 조건부 막힘 답

**Status:** Accepted (2026-10-12, source contract)

## Context

D-717은 진행 중인 BACKING/SETTLING의 중복 후진을 차단했다. 그러나 Fleet 조회 뒤 사람의 WAIT가 도착하거나 CORE local fallback이 먼저 진행되면 모델 후보가 조회 당시 상태에 대한 답인지 검증할 수 없다. D-716의 단일 제출 경로에 적용 시점 검증이 필요하다.

## Decision

기존 POST `/api/v1/line-follow/stuck/decision`의 BACK_AND_RETRY에 선택 `expected_stuck: {phase: "ASKING", attempts: nonnegative strict integer}`를 추가한다. 닫힌 공통 LineStuckPrecondition schema를 API와 Fleet HttpRobotClient가 함께 사용한다. 불명 필드·누락·bool/문자열/음수 시도 수·다른 phase는 거절한다. 다른 decision에 붙이면 VALIDATION_ERROR다.

CORE는 기존 manager lock 안에서 stuck_id와 현재 phase/attempts를 확인하고 같은 잠금 아래 기존 후진 안전 검사를 거쳐 적용한다. 조건 불일치는 기존 STUCK_DECISION_REFUSED와 `stuck_precondition_failed` 사유로 거절하며 타이머·시도·답 선택을 바꾸지 않는다. 후속 막힘은 새 stuck_id를 사용하고 빠른 재막힘의 시도 계승은 유지한다.

조건을 보내지 않는 기존 사람·규칙 요청의 계약은 유지한다. 이 선택 필드는 모델 후보의 근거·운영 수용·단일 소비·예산 검증을 대신하지 않는다. 기존 CORE 로컬 타이머·거리·속도·최종 cmd_vel 권한은 그대로다. envelope protocol_version은 1.0, 공유 API 문서 MINOR는 v1.218이다.

## Verification and consequences

신형 HTTP 처리기는 제어기의 명시적 conditional_back_supported 지원과 자신의 조건 검증/전달을 결합할 때만 `stuck.conditional_back: true`를 보고한다. 제어기의 원시 상태는 false이며 이전 HTTP 처리기가 새 제어기 상태를 그대로 반환해도 true가 되지 않는다. 이전 CORE의 필드 누락도 false다. Fleet은 조건을 보낼 때 먼저 기존 GET line-follow로 지원 여부를 확인하고 명시적 true가 없으면 POST를 보내지 않는다. 구형 API가 알 수 없는 요청 필드를 무시하거나 신형 API가 구형 제어기를 사용하는 경우도 제출 전에 거절한다. 적용 시점 상태 검증은 여전히 CORE 잠금 안에서 한다.

설치 의존성은 core_common 0.0.2, core_api_web 0.0.1·Fleet 0.1.2의 foundation 최소 0.0.2, rosy-execution 0.1.2의 foundation 정확한 0.0.2로 결속한다. 실행 의존 소비자인 palletizing·site gateway·OMX agent·legacy Cell도 0.1.2 및 CI pin으로 함께 갱신한다. 독립 wheel/sdist 설치의 실제 metadata와 클래스 identity를 검사하고 구형 0.0.1이 새 의존성을 충족하지 않는지 확인한다. 직접 REALIGN에 BACK 전용 조건을 붙인 경우도 manager 경계에서 거절한다.

사람 WAIT·CORE local fallback·시도 불일치·같은 ASKING 조건 수용과 malformed 입력을 실제 상태 기계/API/HTTP transport 회귀로 확인한다. 독립 안전 검토·원격 통합·로컬 착지 후에도 모델 후보 생산/dispatch·운영 receipt·배포·현장 수용은 별도다.

2026-10-12 독립 `responsibility_review`는 `fa048a18d`의 D-430 SOURCE 안전 재검토를 승인했다. 기존 manager lock의 조건 검사, REALIGN 우회 차단, 혼합 API/제어기 capability와 SDK 의존성 결속에 중요한 blocker 없음. 원격 `fa048a18d` 관련 회귀에서 native installer의 오래된 execution pin 1건을 확인했고, `60da01830`의 설치·wheel/sdist·CI closure 21개 회귀가 terminal exit 0/NEW 0이다. 세션 로그 `stuck-condition-closure-final/run-1.txt`, `stuck-condition-installed-final/run-1.txt`에 원본을 보존한다. 통합 회귀는 착지 도구로 다시 검증하며 이 승인은 실제 device/field 수용이 아니다.
