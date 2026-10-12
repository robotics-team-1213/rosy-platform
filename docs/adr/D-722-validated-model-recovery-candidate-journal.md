# D-722 검증된 모델 복구 후보와 기존 사건 원장 결속

**Status:** Accepted (2026-10-12, source contract; no operational admission)

## Context

D-718의 CORE 조건부 BACK 경계는 구현됐지만 모델 worker는 읽기·재관측만 처리한다. 판정의 물리 후보를 기존 사건과 모델 시도에 결속하고 단일 Fleet 소비 경로로 연결해야 한다. 모델 자기 확률·모델 합의를 실행 권한으로 취급하지 않는다.

## Decision

첫 후보는 line_follow의 `back_and_retry` 선택과 incident 범위 `propose_lane_back` 도구다. 모델 인자는 trim된 최대 512자 rationale 하나이며 속도·거리·대상·URL·토큰은 행동 인자로 받지 않는다. 현재 CORE ASKING/attempts/cause/local_enabled/max_attempts를 승인된 recovery 사실로 모델 입력에 결속한다. 다른 domain·normal·ABSTAIN·다른 choice로 이 후보를 제출하지 않는다.

기존 IncidentCaseStore와 같은 SQLite DB에서 완료된 모델 시도·검증된 ModelReceipt·전체 CaseScope·input_hash/generation을 다시 확인하고 후보를 영속 기록한다. 같은 시도의 중복 기록은 동일한 후보를 반환하며 예산을 초기화하거나 모델 시도를 추가하지 않는다. UNKNOWN/REJECTED·미완료·다른 worker/profile/policy·폐기/기한 초과 사건·위험 반론/누락 근거는 거절한다.

후보는 제안이며 실제 제출·CORE ACK·해결 성공이 아니다. worker는 직접 RobotClient를 호출하지 않는다. 기존 StuckResolverLoop가 규칙/모델 중 단일 제출을 소유하고 D-716의 bounded 대기·signed 운영 수용·최종 폐기 재검사·durable 신규 물리 제출 한계와 D-718 조건을 적용해야 한다. 후보 원장만으로 물리 경로를 활성화하지 않는다. 원장/규칙의 기존 PENDING·UNKNOWN과 CORE 최종 권한을 보존한다.

## Verification

실제 SQLite/완료된 모델 trace, 중복·동시 기록·재시작·scope 변조·무효 결과·정상 미개입과 실제 opt-in worker의 모델 결과 기록을 원격 검증한다. 기존 읽기 전용 기본값과 설치 namespace를 유지한다. 운영 수용·단일 물리 소비·실제 모델·현장 결과는 별도 증거이며 전체 목표는 ACTIVE다.
