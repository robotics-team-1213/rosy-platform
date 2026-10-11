# CORE Drive 나머지 책임 실행

기준 `638043861`, 브랜치 `feat/platform-structure-migration`, D-628. 기존 전체 CORE 계획 P0–P4/A1–A2의 남은 소스 작업을 실제 공백에 따라 수행한다.

1. 현재 writer/producer/cap/복구와 Arm 경계를 대조한다. 이미 구현된 goal generation, lease, MANUAL admission을 복제하지 않는다. 기존 관련 시험을 원격 기준으로 확보한다.
2. 모드 왕복·다른 모드의 입력·원자적 입력 commit 회귀를 먼저 만든다. RED 후 mode-bound slot admission/invalidation을 구현한다.
3. line 후보의 profile clip→traffic→공통 감속 순서를 고정한다. session/person/policy 변경, 부호·zero·pivot·nonfinite·비동일 actuation 회귀를 RED/GREEN한다. Nav2/MANUAL/Arm 의미를 유지한다.
4. 복구 응답의 현재 근거와 snapshot age, 취소·정지·한도·동일 문제 재진입을 대조한다. stale/future·calibration 변경과 KTURN 회전 후진의 side obstacle을 회귀로 고정하고 최소 구현한다.
5. Drive traffic/line 조립과 공통 power 설정만 기존 wiring 패턴으로 추출한다. 공개 service attribute·재-export·생성/listener 순서를 유지하고 구조·설치 회귀를 확인한다.
6. 각 Safety 구현은 첫 commit 전 독립 리뷰한다. 테스트 commit은 RED 증거를 위해 먼저 기록하고, 모든 원격 로그를 known_failures로 비교한다. 새로운 실패는 known failure에 넣지 않는다.
7. CORE/features/구조/설치 원격 시험, harness generate/lint, Safety commit-range와 diff를 확인한다. 실행 결과에 P0–P4/A1–A2의 실제 coverage와 M8/M9의 소비자·확장 조건을 기록한다. 증거가 없는 ROS/장치/현장 gate를 올리지 않는다.

완료 기준은 확인된 소스 공백과 책임 조립의 해결이며 전체 D-442 producer identity, 새 world 학습·추론·장치 활성화 완료가 아니다. 새 소비자 없이 빈 world/perception 폴더나 호환 framework를 추가하지 않는다. 사용자의 기존 요청대로 세계 상태와 행동 예측 계약은 각각 유지한다.
