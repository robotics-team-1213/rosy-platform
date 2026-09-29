## D-334 ER 2의 도구 목록과 진행 조회를 Fleet 원장 경계에 둔다

**Status:** Accepted (2026-09-29, 도구 권한·진행 상태 의미만). 현행 ER 2 어댑터의 도구는 `propose_pick_place` 하나다. 추가 모델 도구, provider 연속 loop, Mission 진행 API, 영상 진행 분류, 자동 재계획·실행은 구현·운영 승인 대상이 아니다.

### Context

D-331의 표준 ER 2 adapter는 이미지 한 장과 지시를 한 번 보내고 단일 `propose_pick_place` 함수 호출을 후보로 파싱한다. tool callback 실행, `function_result` 회신, `previous_interaction_id` 연속 호출은 없다. D-326/D-328은 장래의 후보 제출·관측 요청·상태 조회를 개념으로 제안했지만 모델에 실제 노출할 목록과 진행 snapshot의 출처·신선도는 정하지 않았다. D-333은 Mission/Action/목표/정지의 소유권을 분리했으나 사용자와 모델이 작업 중 무엇을 읽을지의 계약은 후속으로 남겼다.

Google의 표준 작업 오케스트레이션 예시는 앱이 선언한 mock `move`/`setGripperState`를 **앱이 실행**하고 `function_result`를 모델에 반환한다. 예시의 즉시 `success`는 ROSY의 물리 결과가 아니다. Google `Interaction.status`는 provider 상호작용의 진행이고 Mission/Action 상태가 아니다. ER 2의 영상 진행 분류는 0–20% 등 다섯 범주의 모델 추정이며 장치의 파지·배치·정지 readback을 대신하지 않는다. Streaming은 별도 Live API와 세션·`tool_response` 계약을 사용한다.

### Decision

1. **현재 모델 도구는 한 개로 고정한다.** 표준 `gemini-robotics-er-2-preview`의 `propose_pick_place`는 target/destination selector 후보만 반환한다. `move`, `setGripperState`, joint/trajectory, `SubmitDeviceAction`, Mission admission, cancel, stop/E-stop, rearm은 모델 callable이 아니다. Google 예시의 도구 이름은 ROSY 운영 API 목록이 아니며 모델에 모든 Fleet/OMX endpoint를 자동 등록하지 않는다.
2. **장래 조회·제안 도구는 별도 allowlist 후보로 둔다.** `get_mission_status(mission_id)`는 Fleet의 권위 있는 읽기 snapshot만 반환하고 다른 principal의 Mission 열람·임의 ID 열거를 막는다. `request_observation(workcell_id, purpose)`는 등록된 관측 범위에 대한 *요청*이며 모델이 임의 카메라 URI나 raw stream을 여는 권한이 아니다. 새 촬영·영상의 provider 재전송은 데이터 승인, 비용·호출 수·신선도 상한을 통과해야 한다. `propose_replan(mission_id, based_on_event_id, observation_id, reason)`은 기존 Action의 물리 효과와 HOLD를 해소한 뒤 새 후보만 만든다. 이 이름은 논리적 후보이며 아직 function declaration/wire enum이 아니다. D-332의 사람 확인 위치와 D-326의 정책 재발의 밸브를 이 후보로 열지 않는다.
3. **진행은 네 출처의 상태로 읽는다.** Fleet은 Mission/Step의 `PROPOSED`·`READY`·`RUNNING`·`ACTION_SUCCEEDED`·`GOAL_CONFIRMED`·`HOLD`·`CANCELED`와 마지막 원장 이벤트를 권위 있게 제시한다. OMX는 Action의 `PREPARED`·`SUBMITTING`·`ACCEPTED`·`RUNNING`·`CANCEL_REQUESTED`·`UNKNOWN`·`SUCCEEDED`·`FAILED`·`HOLD` 및 ROS/driver readback을 제시한다. 별도 goal 축에는 독립 증거의 대기·충족·거절·출처 불명 상태를, stop 축에는 요청·전달·로컬 래치·driver/물리 readback을 둔다. 각 축은 source, observed time, revision/event ID, 신선도와 미확인 이유를 갖는다. Action `SUCCEEDED`와 goal 대기는 Mission 완료가 아니며, stop 요청이나 provider turn 완료는 물리 정지가 아니다. 근거 없는 단일 진행률 %를 만들지 않는다.
4. **첫 진행 조회는 Fleet snapshot과 cursor 조회로 확정한다.** operator 화면은 인증된 `GET Mission`의 일관된 snapshot을 먼저 읽고, Mission별 event ID를 cursor로 하는 제한된 조회로 재연결 뒤 변경분을 읽는다. event ID는 Mission 원장의 순서를 나타내며 장치 시계의 순서를 대신하지 않는다. 서버는 권한·cursor 유효성·보존 기간·중복·누락을 명시하고, 보존 범위 밖 cursor는 새 snapshot부터 다시 시작하도록 알린다. WebSocket/구독은 첫 범위에 넣지 않는다. stale device readback은 마지막 값과 함께 `STALE`/`UNKNOWN`으로 보여주고, 새 이벤트가 없다는 이유로 작업 성공·실패를 추론하지 않는다. 모델이 상태가 필요하면 middleware가 principal/workcell에 한정하고 민감 정보를 줄인 snapshot을 입력으로 제공한다. 모델의 “완료”·“아직 진행 중” 텍스트는 원장 전이가 아니다. 실제 URL·필드·HTTP 상태는 D-18에 따라 API Reference·schema·양쪽 시험을 같은 구현 변경에서 확정한다.
5. **provider tool loop는 현재 단발 adapter와 분리한다.** D-331의 `store=false`/후속 interaction 없음 선택은 그대로 유지한다. 표준 API에서 `previous_interaction_id`를 쓰는 후속 호출은 provider 보관 조건을 다시 결정해야 하며, 무상태 다중 턴은 모든 관련 모델 step·함수 결과·서명을 다시 제공하는 별도 구현과 시험이 필요하다. Streaming은 다른 모델 ID·Live 세션·blocking tool response/interrupt 의미를 가진 별도 adapter다. 어느 쪽도 장치 정지 채널이나 ROS 제어 주기가 아니다. 새 loop는 최대 턴·도구 호출·시간·비용, call ID와 Fleet ID 분리, timeout/중복/늦은 결과, 세션 단절 뒤 조정을 별도 ADR/시험 없이 열지 않는다.
6. **작업은 모델 세션과 독립해 계속 추적한다.** provider 요청이 끝나거나 Live 세션이 끊겨도 이미 장치가 수락한 Action의 결과는 Fleet/OMX 원장에서 확인한다. 모델 세션 중단을 cancel 또는 stop으로 번역하지 않는다. 일반 취소는 인증된 사용자/Fleet 경로, 안전 정지는 장치 로컬 owner와 독립 물리 경로가 담당한다. 영상 진행 분류나 새 모델 관찰은 재관측·재계획 *후보*로만 쓰고 물체 보유·목표 달성·정지 판정으로 승격하지 않는다.

### 도구·상태 노출표

| 항목 | 현재/후보 | 모델이 받을 수 있는 결과 | 제어권 |
|---|---|---|---|
| `propose_pick_place` | 현재 선언된 단발 도구 | 미해결 이미지 selector 후보 또는 후보 없음 | 없음 |
| `get_mission_status` | 미래 읽기 후보 | 권한·신선도를 검증한 Fleet snapshot | 없음 |
| `request_observation` | 미래 관측 요청 후보 | 허용된 새 관측 ID/출처/시각 또는 거절 | 촬영·외부 전송은 middleware 정책 담당 |
| `propose_replan` | 미래 후보 | 이전 시도와 새 관측에 묶인 새 제안 | 발행·자동 재시도 없음 |
| arm/gripper/cancel/stop/rearm/Action submit | 모델 노출 금지 | 해당 없음 | Fleet·장치 owner·operator가 소유 |

### Alternatives

- **Google의 mock 로봇 함수 전체를 선언:** 모델 요청을 직접 물리 동작으로 해석하게 되므로 채택하지 않는다.
- **모델 세션을 진행 원장으로 사용:** 재연결, 늦은 장치 결과와 독립 목표 판정을 보존하지 못하므로 채택하지 않는다.
- **영상 진행 범주를 Mission 퍼센트로 표시:** 단계별 물리 증거와 일치하지 않을 수 있어 채택하지 않는다.
- **Fleet 원장 snapshot과 제한된 후보 도구:** 현재 경계와 양립하고 조회·제안을 나중에 검증해 열 수 있어 선택한다.

### Transition / validation

1. SOURCE/LOCAL: 현행 ER 2 요청에 `propose_pick_place` 외 함수가 없고 tool call을 실행하지 않음을 회귀 시험한다. Mission/Action/goal/stop 상태의 네 축, 신선도·권한·늦은 이벤트·세션 단절을 가짜 clock/driver로 시험한다. API Reference·schema·생산자/소비자 시험을 같은 변경에서 확정한다.
2. 별도 provider loop 결정: 추가 도구의 실제 declaration, `function_result`/Live `tool_response`, `store=false`와 회신 전략, call budget, 이미지·상태 데이터 처리, provider 단절과 진행 중 Action 조정을 별도 ADR로 결정한다. 현재 adapter에 암묵적으로 tool loop를 넣지 않는다.
3. ROS-SIM/DEVICE/FIELD: 관측 기반 진행 제안과 실제 Action/물체 결과의 불일치를 주입하고, UI/모델의 상태 문구가 안전 정지나 목표 판정을 앞서지 않는지 확인한다. 실물 정지·파지·배치 증거는 독립 게이트다.

**Consequences:** operator와 장래 모델은 같은 Fleet 진행 사실을 읽을 수 있지만 모델의 도구 목록은 현재 하나로 유지된다. 진행 중 Action의 수명은 provider 세션이 아니라 Fleet/OMX 원장에 묶인다. D-331의 source adapter 범위와 D-333의 물리 발행·증거 경계는 변하지 않는다.

**References:** [공식 조사](../plans/2026-09-29-er2-tool-and-progress-official-review.md), [D-326](D-326-agent-loop-boundary.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-331](D-331-gemini-er2-proposal-adapter.md), [D-333](D-333-er2-mission-device-action-contract-closure.md), [Google 작업 오케스트레이션](https://ai.google.dev/gemini-api/docs/robotics-orchestration), [Google 영상 진행](https://ai.google.dev/gemini-api/docs/robotics-video-progress), [Google Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview), [Google streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming).
