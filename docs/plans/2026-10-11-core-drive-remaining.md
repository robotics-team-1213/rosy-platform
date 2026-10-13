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

## 2026-10-11 구현 대조

| 단계 | 채택한 실제 변경 |
|---|---|
| 모드·입력 수명 | 실제 모드 전환의 epoch, owning-mode 원자적 입력 admission, 불변 후보 슬롯, 정책 평가 전후 후보 identity 검사를 추가했다. 같은 NAV 내부의 외부 goal identity 통일은 D-442 후속이다. |
| 곡률 | line 후보를 profile clip 뒤 traffic gate에 전달한다. 이후 session/person/policy 제한은 양 축에 같은 비율을 적용하고 보정 actuation이 검사한 곡선을 바꾸면 이동을 거절한다. 다른 생산자의 기존 제한 의미는 유지한다. |
| 복구 | 이동 응답 시 현재 manager 근거를 다시 읽고 standalone snapshot은 경과 시간만큼 노화한다. invalid time/age를 거절하고 WAIT/MANUAL/ABORT를 유지한다. KTURN 후진은 기존 후방 검사 뒤 회전 후진 차체 sweep을 검사한다. 예산 보충이나 자동 복구 활성화는 추가하지 않았다. |
| 조립 | `core/drive/{line_follow,docking,traffic}.py`, `core/system/power.py`에 실제 책임을 두었다. CoreServices는 481줄에서 324줄로 줄었으며 공개 객체·재-export와 기존 서비스 callback의 상대 순서는 유지한다. 입력 무효화 callback은 D-628에 따라 앞에 추가한다. |
| 물리 구조 | D-630에 따라 센서·vision과 Drive backend를 분리하고 World 상태 projection·Situation 분석/incident를 별도 holder로 옮겼다. 기존 package/import와 설치 계약은 유지한다. |

독립 Safety/구조 소스 승인은 [CORE 검토](../validation/d628-core-drive-2026-10-11/safety-review.md)와 [holder 검토](../validation/d630-platform-holders-2026-10-11/safety-review.md)에 있다. [현재 전체 폴더 안내](../reference/platform-folder-responsibilities.md)는 채택한 분리와 유지·보류 결정을 구분한다. 원격 검증과 local main 착지는 별도 실행 증거로 기록하며 ROS·ARM64·장치·현장 gate를 올리지 않는다.

2026-10-11 폴더·소비자 수정은 local main `7f391fa2d`에 먼저 반영했다. 이후 설명을 수정했으며 [확정한 검증 기록](../validation/d630-platform-holders-2026-10-11/result.md)에 시험 SHA와 실패 수정·착지 근거를 남겼다. 추가 주행 알고리즘·World 예측 확장은 이번 폴더 단계 다음의 작업이다.
