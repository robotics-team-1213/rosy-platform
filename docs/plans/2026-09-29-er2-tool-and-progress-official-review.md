# ER 2 tool·진행 상태 계약: 공식 API 재검토

작성: 2026-09-29. 범위: Google의 공개 Robotics ER 2 및 Gemini API 문서와 현재 Rosy 소스의 **계약 비교**. 실제 provider 호출·장치 실행 증거는 없다.

## 공식 API가 의미하는 tool

| 경로 | 공식 계약 | Rosy의 현재 계약·간격 |
|---|---|---|
| 표준 `gemini-robotics-er-2-preview` | 요청에서 앱이 함수 이름·설명·인자 스키마를 선언한다. 모델은 `function_call`의 이름·인자·call ID를 제안하고 **앱이 코드를 실행**한다. 공식 pick-and-place 예시의 `move`·`setGripperState`는 mock API이며, 실행 결과는 `function_result`로 `previous_interaction_id`와 함께 다시 보낸다. 하나의 응답에 여러 호출이 가능하므로 실행 순서·반복 상한·오류는 앱이 관리한다. [Task orchestration](https://ai.google.dev/gemini-api/docs/robotics-orchestration), [Function calling](https://ai.google.dev/gemini-api/docs/function-calling) | `er2_standard.py`는 `propose_pick_place` 하나만 선언해 정확히 한 call을 후보로 파싱한다. 실제 함수 실행·결과 회신·연속 reasoning turn은 없다. 이 제한은 D-331의 **후보 전용** 결정과 일치하지만, 진행 중 작업을 보고 다음 tool을 고르는 agent loop는 아직 설계·구현되지 않았다. |
| 표준 Interactions의 상태 | `Interaction.status`의 `requires_action`은 함수 결과 입력 대기 등 **모델 상호작용 상태**이고 `completed`는 모델 턴 완료다. `in_progress`·`failed`·`cancelled` 등도 provider 상태다. 이는 arm/gripper/물체의 실행·완료 상태가 아니다. [Interactions API reference](https://ai.google.dev/api/interactions-api) | provider ID/call ID를 Mission/Action ID로 쓰지 않는다. 진행 표시는 Fleet Mission과 OMX Action 원장의 별도 이벤트/readback에서 만들어야 한다. |
| 표준 결과 루프·보관 | 공식 예시의 `previous_interaction_id`는 서버에 저장된 이전 Interaction을 사용한다. 현행 `store=false`는 이를 사용할 수 없으며 `background=true`와도 양립하지 않는다. 무상태 다중 턴은 앱이 원래 user input, **모든 모델 step(생각 서명 포함), 함수 결과**를 순서대로 다시 보내야 한다. [Interactions storage](https://ai.google.dev/gemini-api/docs/interactions-overview), [Stateless function calling](https://ai.google.dev/gemini-api/docs/function-calling) | 현행 단발 adapter에서는 이 문제가 없다. 결과를 모델에 되돌려 주는 기능은 보관/재전송·데이터 정책·기밀정보 경계를 새 ADR로 결정해야 하며, D-333의 실행 경로를 암묵적으로 열지 않는다. |
| streaming `gemini-robotics-er-2-streaming-preview` | 별도 Live API WSS 세션이다. 앱이 capability 함수를 선언하고 `tool_call`을 받아 실제 robot SDK를 실행한 다음 call ID와 `tool_response`를 보낸다. 로봇의 물리 action은 `behavior: BLOCKING`; Robotics guide는 이 모델에서 **blocking call만 지원**한다고 명시한다. JPEG 입력은 최대 1 FPS다. [Robotics streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming) | 현행 adapter는 streaming을 구현하지 않는다. 일반 Live API 문서의 `NON_BLOCKING` 설명을 ER 2 streaming의 지원 약속으로 옮겨서는 안 된다. Live 세션이나 1 FPS 이미지 입력은 운동 제어 주기·정지 채널이 될 수 없다. |
| ER 2 영상 진행 이해 | 표준 ER 2는 영상에서 완료 순간을 찾거나 진행도를 `0–20`부터 `80–100`까지 다섯 범주로 분류하는 예시를 제공한다. 이 값은 영상의 모델 해석이다. [Video understanding](https://ai.google.dev/gemini-api/docs/robotics-video-progress) | ROSY의 Mission/Action 진행률, 그리퍼 보유, 독립 목표 증거 또는 물리 정지 확인으로 승격하지 않는다. 재관측·재계획 후보에는 사용할 수 있다. |

## 진행·취소·stop의 세 층

1. **provider 진행:** 표준 API의 `Interaction.status`, Live의 turn/tool-call/response는 모델 계산과 tool 교환을 나타낸다. 표준 API의 `/interactions/{id}/cancel`은 아직 실행 중인 **background interaction**에만 적용된다. 현재 `store=false` 단발 호출의 물리 작업 취소 API가 아니다. [Interactions API reference](https://ai.google.dev/api/interactions-api), [Interactions storage](https://ai.google.dev/gemini-api/docs/interactions-overview).
2. **Mission/Action 진행:** Fleet이 `mission_id`/`step_id`/`action_id`/`attempt_id`별 접수, 대기, 승인, 제출, driver 실행, 파지·해제·후퇴, 확인 불명, 목표 독립 검증을 읽을 수 있게 해야 한다. 이벤트의 시각·출처·순서/중복 처리와 `GET` snapshot을 함께 계약화해야 한다. 이는 D-333의 방향이지만, 현행 계획에는 **사용자에게 보이는 진행 이벤트/구독 wire**, 관측 지연, 장기 실행 heartbeat/timeout과 모델에 제공할 상태 정보의 허용 범위가 상세하게 닫혀 있지 않다. [D-333](../adr/D-333-er2-mission-device-action-contract-closure.md), [구현 계획](2026-09-29-er2-mission-action-contract-closure.md).
3. **정지:** Live의 새 입력/heartbeat가 모델 생성을 interrupt하고 미처리 함수 호출을 취소할 수 있지만, 이미 앱에서 시작한 ROS goal·gripper 동작이 취소됐다는 뜻은 아니다. 앱과 장치 owner가 별도의 `CancelAction`/`StopLocal` 및 driver readback을 처리해야 한다. Robotics streaming 가이드는 heartbeat의 무조건 전송이 진행 중 reasoning을 반복 중단할 수 있다고 경고한다. [Live interruptions](https://ai.google.dev/gemini-api/docs/live-api/capabilities), [Robotics streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming).

## Rosy 계약에 반영할 결정 제안

- **현재 허용 목록 유지:** 모델에 보이는 유일한 callable은 `propose_pick_place`다. Fleet/OMX의 운영 API 전체를 `tools`에 노출하지 않는다. `SubmitDeviceAction`, arm trajectory, gripper mutation, cancel, stop, rearm, E-stop은 모델 callable에서 제외한다. 모델의 proposal call은 데이터이며 승인된 Mission/Action 수락이 아니다.
- **진행 read contract 추가:** `GET Mission`은 현재 상태와 각 Step/Action의 참조·마지막 관측 시각·`UNKNOWN`/HOLD 원인을 반환한다. 장기 실행용 event stream 또는 cursor 기반 조회는 소비자 요구와 재연결/중복 규칙을 정한 후 추가한다. 모델이 진행을 참고할 필요가 생기면 Fleet이 민감정보를 줄인 **읽기 전용 snapshot**을 별도 요청의 입력으로 제공한다. 모델이 반환하는 `ack`/완료 텍스트는 상태 전이가 아니다.
- **향후 tool 루프는 별도 ADR:** 승인된 낮은 위험도의 조회/제안 tool부터 allowlist·schema version·권한·호출 횟수/시간/비용 상한·call ID·idempotency·timeout/unknown·결과의 출처를 정의한다. 물리 action tool을 여는 경우에도 앱의 admission과 로컬 owner가 매 호출마다 독립 검증하며, tool response에는 실제 Action 수락/진행/물리 결과를 구분한다. 공식 mock의 즉시 `{"status":"success"}`를 물리 완료 응답으로 쓰지 않는다. [Task orchestration](https://ai.google.dev/gemini-api/docs/robotics-orchestration).

판정: D-331/D-333은 **현재 단발 후보 tool의 권한 경계**를 정했다. 사용자가 묻는 **진행 중 상태와 연속 tool 사용**은 아직 독립된 wire·상태·취소 계약이 아니므로 구현 계획에 추가해야 한다.

후속 결정: [D-334](../adr/D-334-er2-tool-and-progress-read-boundary.md)는 현재 도구를 한 개로 유지하면서 장래 조회 도구와 Fleet의 진행 snapshot 의미를 고정한다. 실제 새 도구의 function declaration과 provider 연속 loop는 별도 구현·검증 대상이다.
