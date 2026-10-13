# D-698 단독 기본 모델 사건 처리와 프로파일 원장 근거

**Status:** Accepted (2026-10-12, source contract)

D-697의 기본 모델 기준은 실제 단독 실행 근거를 요구한다. 두 역할 실행의 호출 수가 1이라고 해서 단독 전략으로 간주할 수 없다.

## Decision

기존 IncidentCaseWorker는 고정된 primary 한 역할 또는 primary/reviewer 두 역할을 받는다. 실제 프로파일 목록과 같은 수의 제공자, 역할별 admission과 budget을 요구한다. 단독 실행에서 검토가 필요하면 `REVIEW_PROVIDER_NOT_CONFIGURED`로 종결 인수를 요청한다. 구성되지 않은 모델을 호출하거나 불일치를 무시하지 않는다. 정상 상태에서는 기존 무호출 경계를 유지한다.

CaseScope의 profile_sha256은 실제 전체 목록의 canonical JSON hash다. 단독 목록 hash는 개인 ModelProfile calibration hash와 다르다. 진행 중 사건의 목록·정책 변경, 다른 사건 조치, UNKNOWN 재제출을 기존 guard로 거절한다. 실제 모델 호출과 운영 활성화는 이 변경으로 승인하지 않는다.

단독 모델 원장 근거는 `rosy.incident.model_receipt/3`으로 기록하며 정확히 primary 한 프로파일을 요구한다. 선택적 cost_evidence를 같은 기존 원장 transaction에서 검증·기록한다. 두 역할의 기존 receipt /1·/2는 유지한다. 단독 사건 export는 `rosy.incident.model_feedback/3`이며 선택적 handoff proof를 포함할 수 있다. 기본 두 역할 export /1·/2는 유지한다. 구버전 소비자는 새로운 /3을 거절하며 조용히 두 역할 전략으로 해석하지 않는다.

recording binder·실패 분석·독립 비교 소비자는 새 버전을 검증한 뒤 UNREVIEWED 근거로 소비한다. 독립 비교의 primary 전략은 단독 프로파일 근거와만 연결하고 primary_reviewer는 두 역할 근거와만 연결한다. 실제 호출 횟수로 전략을 추정하지 않는다. 규칙 기준 생산, 독립 정답·한계, 정상 명령·재발 추적 범위는 후속 작업이며 promotion과 FIELD는 계속 HOLD다.

새 export /3은 단독 primary의 선언된 역할 예산과 실제 model attempt role을 결속해야 한다. `contracts.learning.incident_profiles`의 JSON 검사를 exporter·recording binder·독립 소비자가 재사용한다. reviewer 또는 역할 없는 model 시도를 단독 근거로 거절한다. 구버전 /1·/2의 역할 없는 과거 자료 호환은 그대로 유지한다. 공통 검사는 inference·원장·출처 인증·owner admission을 수행하지 않는다.

## Verification

실제 worker의 단독 실행→원장 receipt→export→기존 소비자, 정상 무호출, 검토 필요 시 한 번 호출 후 최종 인수, 단독/두 역할 가장 거절과 기존 호환을 원격 시험한다. 기존 파일·소유자·크기 한도를 유지한다. source/합성 시험은 실제 Qwen·GLM 품질, 팀 인수, 현장 종결을 증명하지 않는다.
