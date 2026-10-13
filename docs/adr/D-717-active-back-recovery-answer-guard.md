# D-717 진행 중 제한 후진의 중복 답 거절

**Status:** Accepted (2026-10-12, source safety contract)

## Context

CORE의 동일 막힘 ID가 BACKING/SETTLING 동안 유지된다. 늦거나 중복된 BACK_AND_RETRY 답은 기존 뒤 여유 검사만 통과하면 진행 중 후진의 타이머를 다시 시작하고 추가 시도를 소비했다. Fleet의 상태 조회 이후 CORE ask_timeout이 먼저 복구를 시작해도 같은 문제가 생긴다. 원격 RED로 console/ask_timeout 각각의 두 phase를 재현했다.

## Decision

기존 StuckRecovery._answer_refusal에서 BACKING/SETTLING 중 BACK_AND_RETRY를 `back_active` 사유와 기존 `STUCK_DECISION_REFUSED` 코드로 거절한다. 실제 적용은 tick과 공유하는 StuckWiring manager lock 안에서 이뤄진다. 새 API 필드·publisher·모드·속도·거리·설치 설정은 추가하지 않는다.

거절은 기존 타이머·시도 수·현재 출력을 보존하고 거절 답을 감사 이벤트에 남긴다. WAIT/ABORT와 현재 복구가 끝난 뒤의 기존 재시도는 유지한다. Fleet 조회만으로 조치 권한을 인정하지 않으며 향후 모델 경로의 ASKING/episode 일치 결속은 별도 계약이다.

## Consequences and verification

상태 기계의 네 지연 답 회귀와 실제 CORE API의 두 phase 회귀를 적격 AI PC에서 확인했다. 원격 관련 시험 terminal exit 0이며 신규 실패 비교·독립 Safety-Review 후 로컬 착지한다. 이 source 수정은 실제 모델·장치 motion·배포·현장 수용의 증거가 아니다.

2026-10-12 독립 `responsibility_review` source Safety-Review: `319dfbf92`의 guard는 기존 manager lock 안에서 중복 BACK을 거절하고 WAIT/ABORT·로컬 재시도·CORE 최종 권한을 보존한다. 중요한 blocker 없음. 최종 `be23fb518e`의 상태 기계/API 원격 회귀는 terminal exit 0, known-failures NEW 0이다. 로그는 세션 `logs/active-back-final/run-1.txt`에 보존한다. 이 승인은 device/field 수용이 아니다.
