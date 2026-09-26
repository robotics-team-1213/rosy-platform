## D-298 Fleet 미션·장치 액션·정지 증거의 용어를 분리한다

**Status:** Accepted (2026-09-27, 의미와 문서 경계). 기존 API/코드 필드 변경이나 실물 정지 수용을 뜻하지 않는다.

**Context:** D-12는 Mission DSL 실행기를 Fleet에 둔다. D-55는 미래의 `rosy_manipulation`을 로봇 로컬 mission state machine이라고 불러 같은 단어가 현장 순서와 장치 내부 동작을 가리킨다. `Task`도 CORE `TaskKind`의 원자 액션, 현행 Fleet `/api/fleet/tasks/*`의 영속 이동 요청, 목표 구조의 다단계 작업에 쓰인다. 현행 Fleet 전체 정지 응답의 `stopped`는 CORE의 HTTP 응답을 받으면 참이지만 관제 화면은 이를 실제 정지 완료처럼 표시했다. D-296의 HOLD/정지도 소프트웨어 차단과 물리 정지를 분리해 읽어야 한다.

**Decision:**

1. **Fleet Mission**은 사이트 작업의 순서·우선순위·장치 간 인계·복구 기록의 정본이다. **Mission Step**은 그 미션 안의 한 단계다. Fleet은 장치가 제공하는 **Device Action**을 요청하고 수락과 최종 결과를 별도로 기록한다. 장치 안의 접근·파지·배치 같은 유한한 상태 흐름은 **Local Transaction**이다. D-55의 `robot-local mission`은 이 뜻으로 읽으며, Fleet Mission DSL과 사이트 순서를 복제하지 않는다. 단계·액션 ID와 결과 연결, UNKNOWN 후 재시도 규칙은 실제 다장치 미션 계약에서 별도 확정한다.
2. 현행 `TaskKind`, `/api/fleet/tasks/*`, `task_id`, `request_key`, `attempt_id`는 호환을 위해 유지한다. 문서에서는 어느 계층의 task인지 항상 밝힌다. 목표 구조의 `Transport`는 Fleet Mission 예시이며 이미 구현된 API나 상태 enum이 아니다. `Intent`는 후보 요청, `Episode`는 실행 관측 기록으로 사용한다.
3. **정지 요청 전송**, **CORE의 수락·안전 래치**, **속도 0 또는 팔 정지 readback**, **물리 E-stop/드라이버 인터록**은 서로 다른 증거다. 현행 `/api/fleet/estop`의 `stopped`는 호환 필드이며 대상 CORE의 `/api/v1/safety/stop` HTTP 응답 수신 수다. 물리 정지 확인 수로 표시하지 않는다. 응답 없음은 미정지 증거가 아니라 결과 불명이다. 관제 화면에는 요청 응답 수와 물리 정지 미확인을 표시한다. 향후 의미가 분리된 새 응답 필드는 API Reference와 typed schema를 함께 바꾸는 D-18 절차를 따른다.
4. `HOLD`는 범위를 붙인다. Fleet 작업 HOLD는 정책상 진행 차단, 장치 안전 HOLD는 새 명령 차단·정지 요청과 로컬 감시, 대형 HOLD는 참조 스트림 대기다. 어느 HOLD도 별도 readback 없이 물리 정지를 증명하지 않는다. `QUEUED`(Fleet 보관), `ACCEPTED`(장치 수락), `UNKNOWN`(최종 결과 불명)도 계층과 관측 출처를 붙여 기록한다.

**Consequences:** 공개 API의 레거시 이름을 조용히 재해석하지 않는다. 장치 로컬 트랜잭션은 Pinky 주행 최종 `cmd_vel`이나 OMX 팔 최종 trajectory의 소유자가 아니다(D-296). 중단·단절·재시작 후 미확인 결과는 자동 성공이나 자동 재실행으로 바꾸지 않는다(D-297).

**Validation / Transition:** 용어집과 목표 작업 문서, Fleet 정지 화면과 현행 API 설명을 맞춘다. 브라우저 회귀로 응답 3/3이 물리 정지 확인으로 표시되지 않는지 검증한다. 실제 정지 확인은 CORE 래치·속도·드라이버·물리 장치별 시험이 필요하다.

**References:** [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-297](D-297-command-ack-and-fleet-record-activation.md).
