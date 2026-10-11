# D-628 CORE Drive 출력과 복구 경계

**Status:** Accepted (2026-10-11, 사용자 후속 실행 요청). 소스 실행 결정이며 새 자동 복구의 장치 활성화 승인이 아니다.

## Context

D-627의 첫 Drive 조립 분리 뒤 CORE 계획 P1–P4를 조사했다. 모드 왕복 시 후보 재생, line-follow body 검사 이후 session/person/policy cap의 곡률 변경, 오래된 막힘 응답 근거, KTURN 후진 회전의 직선 rear strip 검사 공백을 확인했다. 기존 실행기·계약을 재사용해 각각의 소유자에서 닫는다.

## Decision

1. CommandManager는 모드와 원자적으로 nav/docking 입력을 commit한다. 모드 변경은 기존 슬롯을 무효화한다. None 정리는 모드와 무관하게 가능하다. MANUAL·goal tracker·lease·최종 writer 계약을 유지한다. 식별 없는 ROS Twist에 이전 Nav2 goal의 identity를 추정해 붙이지 않는다.
2. Line 후보를 D-422 body 검사에 사용한 profile nav cap으로 먼저 정렬한 뒤 traffic gate에 보낸다. 이 line 슬롯의 후속 session/person/policy cap은 두 축의 공통 감속으로 곡률을 유지한다. MANUAL/Nav2/docking의 기존 independent clip 계약은 유지한다. Actuation 보정 결과가 검사한 line 후보의 감속 궤적에 속하지 않으면 거절한다. profile cap은 현재 초기 조립 이후 production mutation caller가 없다.
3. 막힘의 움직이는 답은 응답 시점의 센서·calibration·상한 근거를 갱신한다. standalone state machine도 snapshot 경과 시간을 포함하며 미래·nonfinite clock을 거절한다. WAIT/MANUAL/ABORT 정지 출구는 유지한다. 동일 문제의 자동 시도 한도와 default-off는 유지한다.
4. KTURN 후진 회전은 기존 back refusal 이후 기존 reverse body sweep도 통과해야 한다. unknown/freshness/blind-band 근거를 생략하지 않는다.
5. CORE의 실제 조립 응집도에 맞춰 Drive traffic/line 조립과 공통 power 설정을 기존 wiring 방식으로 분리한다. 공개 CoreServices attribute와 생성·listener·종료 순서, import compatibility를 유지한다. 새 registry/process/공개 모드/API/config를 만들지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 현재 parts, package/import/install identity 유지 |
| D-429 | 도메인별 실행·장치 binding 구분; 공통 executor로 합치지 않음 |
| D-430 | Safety 보호 대상의 소유자 유지, 변경 전 독립 리뷰와 trailer |
| D-442 | 현재 mode/lease/goal fencing 보강; 전체 producer MotionIntent 이행 완료 주장 없음 |
| D-422 / D-407 / D-607 | 기존 body·복구·REALIGN 근거를 강화하고 새 자동 동작은 추가하지 않음 |

## Validation

[실행 계획](../plans/2026-10-11-core-drive-remaining.md)의 원격 RED/GREEN·CORE/features/구조 회귀·source Safety 리뷰로 검증한다. ROS-SIM, ARM64 artifact, 장치 readback과 물리 수용은 별도다. main 착지·push·장치 명령은 이 결정의 수행 항목이 아니다.
