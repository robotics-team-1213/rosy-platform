# Action과 메시지 식별자 설계 검토

2026-09-30. [D-369](../adr/D-369-control-authority-and-stop-evidence.md). 기준선 `e387b025`, 브랜치 `docs/control-authority`.

## 판단

Action 관련 요청을 message type으로 분류하는 것은 가능하다. 실행 작업과 그 작업에 관한 여러 메시지는 각각 식별해야 한다. `PICK_PLACE`는 작업 종류, `SubmitAction`은 연산, `action_id`는 작업, `attempt_id`는 실행 시도다. 조회·취소·진행·결과가 같은 Action을 가리킨다.

현재 의미를 명확히 하고 실제 producer/consumer를 시험한다. 범용 envelope나 broker, `EnvelopeType.ACTION`, 모든 wire에 강제하는 `message_id`/`causation_id`를 추가하지 않는다.

모든 메시지가 Action에 속하지는 않는다. heartbeat·pose·관측은 장치나 관측의 식별을 사용하며, 작업 정보가 없어도 site/device stop은 가능해야 한다. Action 관련 요청/피드백에만 Action/attempt를 결속한다. 이런 구분을 해야 메시지 체계를 넓혀도 모든 상태·설정·정지 요청을 불필요한 실행 작업으로 만들지 않는다.

## 현재 필드와 수명

| 층 | 현재 필드 | 의미·수명 |
|---|---|---|
| PRT | `Envelope.type`, `msg_id` | command/event/ack 등 메시지. Action 인스턴스가 아님 |
| PRT 상관관계 | `Envelope.correlation_id` | schema에 존재하나 top-level runtime 생산·소비 경로는 아직 없음. REST correlation 지원과 구분 |
| Fleet | `mission_id`, `step_id` | 목표·순서와 그 단계 |
| Fleet/OMX | `action_kind`, `action_id`, `attempt_id` | 작업 유형, 구체적 작업, 실행 시도. dispatcher가 발행 전에 저장 |
| 요청 중복 | `(principal_id, request_key)`, grant digest | 동일 요청/내용 충돌 판정. 새 메시지가 새 실행 허가가 되지 않음 |
| 실행권 | `authority_epoch`, `dispatch_generation`, peer UID | 이전 owner/stop 세대의 발행 차단. ID 자체는 권한이 아님 |
| OMX 결과 | `journal_event_id`, `observed_at` | 출처별 사건과 관측 시각. 원장 정수 ID는 전역 ID가 아님 |
| Driver | `driver_goal_id` | concrete driver goal. ROSY Action ID와 동일하다고 가정하지 않음 |
| Goal evidence | producer·관측·Action/attempt | terminal Action과 독립된 목표 검증 |

소스: `src/contracts/foundation/core_common/protocol/schemas.py`, `src/site/fleet/fleet/server/mission_dispatcher.py`, `local_action_transport.py`, `src/products/omx/adapter/omx_adapter/action_api.py`, `action_runner.py`, `action_store.py`.

현재 dispatcher는 Action/attempt 쌍을 만들고 OMX Action 행은 해당 attempt를 보관하며, journal은 상태 전이를 기록한다. 여러 attempt를 자동 생성·재실행하는 기능은 없다. 재시도 기능을 추가하려면 attempt별 조회·효과 조정 계약부터 정해야 한다. D-358의 재계획은 source Mission을 고치는 대신 successor Mission을 만든다.

## 예시: 블록을 트레이로 옮기기

의미 예시이며 신규 wire schema가 아니다.

| 교환 | 메시지 의미/연산 | 참조 |
|---|---|---|
| 작업 시작 | command / SubmitAction | Action A, attempt T, grant G |
| 수락 응답 | response / receipt | 같은 A/T/G, ACCEPTED, 사건 E1 |
| 상태 두 번 조회 | query / GetAction | 같은 A. 변화 없으면 응답도 같은 A/T/G/E1 |
| 실행 중 상태 | response/feedback | 같은 A/T/G, RUNNING, 새 사건 E2 |
| 취소 요청 | command / CancelAction | 같은 A/T를 대상으로 함 |
| 취소 ACK | response / receipt | CANCEL_REQUESTED일 수 있음. 물리 정지 증거 없음 |
| terminal readback | response/result | 같은 A/T/G, terminal 사건 E3 |
| placement 증거 | evidence | 같은 A/T에 결속된 독립 predicate 검증 |

메시지를 다시 보냈다는 이유로 A/T를 새로 만들지 않는다. 동일 사건 재전달과 새로운 사건을 구분한다. PRT의 모든 replay 구현이 완료됐다는 뜻은 아니다. UDS timeout 뒤에는 불명 상태를 유지하고 원장을 조회한다.

## 발견과 이번 처리

1. API Reference의 `GetAction(DeviceActionLookup)` 설명은 pair 타입을 가리켰지만 실제 Fleet producer와 OMX consumer는 `version`, `operation`, `action_id`만 교환한다. 응답에서는 Fleet이 전체 attempt/grant identity를 검증한다. 문서와 type docstring을 실제 계약으로 정정했다. wire 변경은 없다.
2. `action_id`를 메시지 ID로 바꾸면 조회가 새 실행처럼 보이거나 여러 진행 사건이 하나로 deduplicate될 수 있다. 기존 ID를 유지한다.
3. PRT top-level correlation은 아직 미연결이다. 실제 command producer/consumer가 확정되면 그 경로만 구현한다.
4. 단일 `driver_goal_id`는 여러 phase의 arm/gripper goal 기록을 보장하지 않는다. 선정 driver와 phase별 goal·cancel 범위를 후속으로 정한다.
5. 실제 Fleet JSON producer → OMX API/runner/SQLite store → Fleet receipt parser를 연결한 시험을 추가했다. socket 대신 JSON 왕복을 주입했고 driver는 가짜다. SO_PEERCRED, ROS, 물리 동작/정지 수용 증거가 아니다.

## 대안

- Action을 새 envelope type으로 통합: command/query/event를 다시 구분해야 하고 기존 UDS/PRT를 바꿔야 한다. 지금 채택하지 않는다.
- 제품별 문서만 유지: 변경은 적지만 동일 ID/ACK의 의미가 어긋날 수 있다.
- 공통 의미·식별 수명을 정하고 실제 경계 시험: transport 변경 없이 잘못된 readback과 재실행을 검증할 수 있다. 채택한다.

## 공식 자료

- [ROS 2 Actions 설계](https://design.ros2.org/articles/actions.html): Action은 goal/result/feedback과 service/topic 조합을 사용하고 goal UUID를 유지한다. ROSY Action을 단일 전송 메시지와 묶을 필요가 없다는 판단의 근거다. 외부 API를 ROS Action 프로토콜로 바꾸지는 않는다.
- [CloudEvents 1.0.2](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md#id): 사건은 source와 ID로 구분하며 동일 사건의 재전달을 식별할 수 있다. ID 수명 비교에 사용했으며 ROSY에 CloudEvents envelope를 도입하거나 호환성을 주장하지 않는다.

[실행 계획](2026-09-30-action-message-identity.md)에 남은 작업을 기록한다.
