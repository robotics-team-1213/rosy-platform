# D-712 Fleet 새 사건의 영속 선택과 원자적 배정

**Status:** Accepted (2026-10-12, source contract)

D-711의 허가 조회와 사건 생성 사이 경쟁을 제거한다. 기존 IncidentCaseStore와 같은 SQLite DB에 owner/policy별 current/previous profile tuple SHA 및 증가하는 revision을 저장한다. 명시적 내부 선택·복귀는 revision CAS를 요구하고 재시작 후 읽어 확인한다. 현재 line_follow worker는 `routed=True`를 명시한 경우에만 이 선택을 사용한다. 기본 동작과 기존 공개 imports는 유지한다.

새 사건의 선택 일치 확인·CaseScope 생성·assignment revision 기록은 같은 BEGIN IMMEDIATE 또는 기존 outbox 트랜잭션이다. 기존 사건은 원래 profile·예산·시도를 유지하며 다른 scope로 재사용하지 않는다. 선택 변경은 이미 배정된 사건의 모델 admission을 끄거나 UNKNOWN을 재제출하지 않는다. 현재·이전 selection은 운영 설정이며 모델의 품질 승인이나 안전 권한이 아니다. 기존 admission/current_profiles/보정 신뢰·CORE authority는 계속 적용된다.

모델 후보의 signed 운영 수용·설치 loader와 여러 pinned worker dispatcher는 별도로 결속해야 한다. 이 내부 API를 외부 REST로 노출하지 않는다. 보정의 PASS_OFFLINE_ONLY를 운영·현장 승격으로 사용하지 않으며 routed 모드에서 선택이 없으면 새 사건을 거절한다.
