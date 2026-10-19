## D-804 SIM 장치의 Fleet policy lease 소비와 CORE 결속

**Status:** Proposed

## Context

D-793은 Fleet 승인 창과 짧은 lease를 발급하지만 전달 확인은 제공하지 않는다. D-800의 CORE arm port는 이미 결속된 session을 요구한다. 사용자는 2026-10-19 학습 checkpoint가 없음을 확인하고 고정 SIM 정책의 전체 연결을 요청했다.

## Decision

기존 Fleet GET policy state·POST lease를 인증된 HTTP로 소비하는 선택적 장치 consumer를 추가한다. SDK와 CORE arm HTTP에는 설치·lease 주입·rearm 권한을 추가하지 않는다. consumer는 accepted SIM install과 로컬 실행 identity에만 결속하고 기존 OwnerPolicySession·watchdog·persistent stop fence를 사용한다. 기본값은 비활성이며 실물 profile은 거절한다.

승인 window·policy stage의 rig/calibration·episode·owner session·workcell을 고정된 실행 설정과 대조한다. 발급 전후 policy state를 읽어 창 전환과 폐쇄를 검증하고 모든 네트워크 시간을 local monotonic lease 예산에서 차감한다. 요청 시작 monotonic에 반환 duration을 더한 deadline을 사용하며, 갱신은 동일 lease의 issued/expires 진전만 수용한다. Fleet wall clock을 장치 clock으로 직접 해석하지 않는다.

별도 worker가 network를 수행한다. ROS authority callback은 검증된 local current/pending lease만 읽는다. session.renew의 old/new authority 검사를 모두 보존한 뒤에만 cache를 교체한다. 거절·연결 실패·expiry·정지는 한 방향 fault이며 늦은 응답으로 회복하지 않는다. 기존 watchdog이 해당 session의 목표만 취소하고 HOLD를 유지한다.

Fleet lease의 `device_delivery=not_connected`는 서버의 전달 확인 부재라는 기존 의미를 유지한다. 장치 SIM 수신 receipt는 별도로 기록한다. 로컬 AttemptIdentity는 Fleet Mission/Action admission이 아니며 Fleet 작업 완료 증거로 승격하지 않는다. 정책 설치의 pinned revision·원본 hash 검증은 유지하고 검사 대상에서 trusted binding을 생성하지 않는다.

| 관련 결정 | 관계 |
|---|---|
| D-427 | Fleet 운영 원장과 device execution 소유를 유지한다 |
| D-429 | 기존 배포 위치와 wheel 소유를 유지한다 |
| D-430 | 새 authority consumer/composition을 안전 경계로 분류하고 독립 리뷰를 적용한다 |
| D-793 | 기존 승인·발급·최대 duration 계약을 소비하며 실물 승격하지 않는다 |
| D-800 | 기존 CORE port 조립을 채우며 외부 wire를 바꾸지 않는다 |

## Consequences

공개 API의 경로·요청·응답은 변경하지 않는다. SIM의 HTTP 발급→수신→갱신→CORE/SDK→Gazebo 동작→철회/만료 정지를 동일 실행으로 검증한다. 합성 승인·고정 목표는 사람의 실제 배포 승인, 학습 품질, Mission 작업 성공이나 물리 정지 수용을 입증하지 않는다. 실물 연결과 신뢰된 Mission identity 전달은 별도 계약·수용 작업이다.
