# Gemini Robotics Samples 조사 결과

> 조사일: 2026-10-01
> 목적: Google 공식 Gemini Robotics 샘플의 실제 API·도구·로봇 실행 경계를 확인하고 Rosy의 모델 중립 규약 및 기존 D-331 결정과 비교한다.
> 확인한 저장소: [google-gemini/robotics-samples](https://github.com/google-gemini/robotics-samples), 기본 브랜치 `main`, 조사 시점 HEAD `c51cbab6e6efffff8738ecf9ce41ba85034d9654`. 저장소는 Apache-2.0이며 GitHub Releases는 확인되지 않았다. 이 보고서의 파일 링크는 조사한 커밋에 고정했다.

## 결론

공식 샘플은 우리가 하려는 문제의 **중요한 참조 구현**이다. 특히 ER의 공간 인식 출력, 사용자 정의 robot tools, blocking tool call, 실행 결과 회신, Spot용 perception-to-manipulation 어댑터가 실제 코드로 존재한다. 따라서 모델에게 좌표만 묻는 설계보다 **모델이 제한된 capability/tool을 요청하고 미들웨어가 실행 결과와 피드백을 돌려주는 규약**이 더 적절하다는 점을 뒷받침한다.

다만 샘플의 실행형 경로는 애플리케이션이 모델 function call을 로봇 API에 전달해 물리 동작을 실행한다. 이는 Fleet Mission·승인·Action grant와 디바이스 로컬 ROS owner가 물리 명령 권한을 소유한다는 Rosy 경계와 다르다. 샘플의 실행 권한 구조를 그대로 가져오면 안 된다. D-331의 제안 전용 ER 2 경계와는 충돌하지 않는다. D-331은 현재 ER 2 공급자 adapter의 안전한 초기 경계이고, 샘플은 이후의 승인된 tool/action 왕복을 어떻게 통합할지 참고하는 자료로 볼 수 있다.

ADR은 **모델별 API 차이를 adapter 뒤에 숨기되, 공통 tool/action/feedback 봉투는 provider와 무관하게 정의하고, 모델 호출은 권한이 아닌 요청으로 취급**하는 방향을 결정하는 것이 타당하다. ER 2 Interactions, ER 2 Live API, 향후 다른 모델이 같은 하드웨어 API에 직접 붙지 않도록 한다.

## 공식 샘플 구성과 현재성

저장소의 `Getting Started/gemini_robotics_er.ipynb`는 ER 2 Interactions API를 이용한 점·상자·공간 질문, 코드 실행 이미지 보조, pick-and-place orchestration, video event/moment/progress 분석 예제를 포함한다. `live-api/`는 Google Live API와 WebSocket 세션을 사용해 Spot·Tinybot·사람 embodiment를 연결하는 에이전트/앱 샘플이다. 저장소 README는 Python 3.10+, `uv`, FastAPI, WebSockets, `google-genai` 등을 명시하며 Spot 앱은 Boston Dynamics `bosdyn-client` 계열을 추가 사용한다. [저장소 README](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/README.md#L192-L248)

저장소는 공개 Apache-2.0이지만 버전 태그/Release가 확인되지 않아 `main`을 제품 의존성으로 취급하기보다 조사한 commit SHA를 고정해 참조해야 한다. 또한 Spot manipulation의 `gemini_detector.py` 기본 모델은 `gemini-robotics-er-1.6-preview`다. 공식 현재 API 문서는 ER 1.6이 2026년 8월 말 종료 예정이라고 안내한다. 따라서 이 경로는 구조 참고 대상으로만 쓰고 현재 ER 2 endpoint에 맞는지 별도로 갱신 검증해야 한다. [ER detector](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/spot/apps/manipulation/gemini_detector.py#L15-L70), [공식 모델/API 현황](https://ai.google.dev/gemini-api/docs/robotics-overview#model-endpoints)

## `gemini-robotics-sdk`와의 구분

별도 저장소 [google-deepmind/gemini-robotics-sdk](https://github.com/google-deepmind/gemini-robotics-sdk)는 `robotics-samples`와 같은 프로젝트가 아니다. SDK README는 이름을 **Safari SDK**로 부르고, “Google이 공식 지원하는 제품이 아니다”라고 명시한다. checkpoint 접근·모델 serving·robot/simulation 평가·data/fine-tuning lifecycle 기능을 제공하며 상당 기능은 Gemini Robotics Trusted Tester 접근이 필요하다. Python package에는 compiled C++ logging extension이 포함되고, Aloha agent framework와 examples도 포함한다. README는 SDK가 Gemini Robotics model series를 대상으로 하며 계속 개발 중이라고 설명한다. [Safari SDK README](https://github.com/google-deepmind/gemini-robotics-sdk/blob/main/README.md#L190-L300)

따라서 공개 Gemini API Interactions/Live API를 연결하는 Rosy tool protocol에 이 SDK를 필수 의존성으로 삼을 근거는 없다. SDK 검토는 checkpoint/serving/평가가 필요한 별도 실험 트랙으로 분리해야 한다. GitHub 저장소에도 Apache-2.0 license가 표시되어 있지만, 라이선스는 제품 지원/안정성/Trusted Tester 권한을 뜻하지 않는다. `robotics-samples`(API examples)와 `gemini-robotics-sdk`(Safari lifecycle SDK)를 ADR에서 명확히 구별한다.
## 실제로 제공하는 계약

### 1. 공간 인식은 이미지 좌표 출력이다

공식 ER 2 예제는 `point: [y, x]` 정수 0–1000과 label을 반환하게 하고, box는 `[ymin, xmin, ymax, xmax]` 정규화 좌표로 반환한다. JSON schema/Pydantic 예제는 출력 형식을 제한하지만 이 좌표는 여전히 **카메라 이미지 평면의 좌표**다. 그 자체로 로봇 base/world frame의 3D pose, depth, TF, grasp pose, 충돌 없는 경로를 제공한다는 뜻은 아니다. [공식 ER overview의 point 출력](https://ai.google.dev/gemini-api/docs/robotics-overview#spatial-reasoning), [ER 샘플 노트북](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/Getting%20Started/gemini_robotics_er.ipynb)

공식 Spot manipulation 앱은 모델의 2D 지점을 Spot의 hand-camera depth와 조합해 3D pose로 투영한 뒤 Spot native manipulation/pick 경로를 호출한다고 설명한다. 즉 좌표를 실제 동작으로 바꾸는 작업은 별도의 robot-specific 앱/driver가 맡는 구조다. [Spot manipulation README](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/spot/apps/manipulation/README.md), [Spot project README](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/spot/README.md#L78-L105)

### 2. pick-and-place는 함수 호출/결과 회신의 반복이다

공식 Interactions orchestration 예제는 mock `move(x, y, high)`와 `setGripperState(opened)`를 모델에 tool로 선언한다. 애플리케이션 loop가 모델 function call을 찾아 실행하고, 결과를 `function_result`와 call ID로 모델에 돌려주며, `previous_interaction_id`로 다음 단계를 이어간다. 15회 step limit은 무한 호출을 막는 예제 수준의 제한이다. 이 샘플의 move는 화면 origin 기준 2D 상대 좌표와 `high` 플래그이며 ROS, MoveIt, Franka API가 아니다. 실제 구현 함수도 “Mock Robot” 로그를 출력한다. [공식 task orchestration 예제](https://ai.google.dev/gemini-api/docs/robotics-orchestration#using-a-custom-robot-api)

따라서 `pick_and_place`는 단일 좌표 형식이 아니라 **능력에 대한 여러 tool call, 실행 상태, 결과 회신이 연결된 작업 흐름**으로 취급해야 한다. 다만 샘플의 `{"status":"success"}` 회신은 mock 수행 결과다. Rosy에서는 controller가 접수했다는 사실, 실제 grasp/placement 완료 증거, 사용자에게 보여줄 목표 달성을 구분해야 한다.

### 3. Live API는 실행형 agent와 robot adapter를 분리한다

`live-api/README.md`는 `agent`가 Gemini Live API 세션과 tool dispatch를 맡고 `spot`이 별도의 FastAPI/Boston Dynamics SDK robot backend를 제공하는 구성을 설명한다. Spot embodiment는 도구 목록을 얻고 action 이름과 인자를 robot client/backend로 전달한다. Spot OpenAPI adapter는 backend OpenAPI에서 허용 목록(allowlist)으로 선택한 operation을 Gemini function declaration과 dispatch metadata로 변환한다. 이 패턴은 로봇/장치 API를 모델 API와 분리하고 capability 목록을 생성하는 참고점이다. [Live API sample README](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/README.md#L192-L240), [Spot embodiment](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent/embodiment/spot/spot_embodiment.py#L413-L556), [OpenAPI tool builder](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent/embodiment/spot/openapi_tools.py#L371-L438)

샘플 tool handler는 각 모델 call을 실행하고 결과를 Live 세션으로 회신하며 UI/event bus에 `TOOL_RESULT`를 발행한다. call의 provider ID는 function response correlation에 사용된다. 이는 Rosy의 durable `action_id`/Mission ID와 같은 의미라고 증명되지 않는다. Rosy 규약은 provider의 message ID, tool-call ID, idempotency key, Rosy Action ID, Mission ID를 목적별로 구분하고 매핑을 보존해야 한다. [Sample tool handler](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent/core/tool_call_handler.py#L158-L254)

공식 문서는 standard `gemini-robotics-er-2-preview`(Interactions)와 `gemini-robotics-er-2-streaming-preview`(Live API)를 별도 endpoint로 명시한다. 표준형은 structured output/code execution/function calling을 지원하지만 Live API는 streaming/function calling을 지원하고 structured output/code execution은 지원하지 않는다. 두 endpoint를 하나의 provider feature set으로 가정하면 안 된다. [공식 ER 2 모델 capability 표](https://ai.google.dev/gemini-api/docs/robotics-overview#model-endpoints), [공식 streaming tool-call 예제](https://ai.google.dev/gemini-api/docs/robotics-streaming#orchestrate-a-robot-through-function-calling)

## Stop·완료 피드백과 안전 경계

샘플은 Gemini tool로 `stop`을 선언하며 Spot tool은 base 이동/navigation 취소와 arm freeze를 설명한다. Spot HTTP API도 `/teleop/stop` 및 `/actions/stop` route를 제공한다. 하지만 이 stop도 Live tool-call 처리나 HTTP 앱 경로의 일부다. 저장소에서 물리 E-stop과 독립된 safety-rated 경로, ROS hardware watchdog, stop generation/fencing 계약을 확인하지 못했다. 따라서 이를 **비상정지 또는 모델과 독립된 안전 기능으로 해석할 수 없다**. [stop tool 선언](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent/tool/tools.py#L422-L432), [Spot FastAPI routes](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/spot/apps/api/main.py#L436-L460)

샘플은 pick 도구 응답에서 backend/gripper 진단만으로 성공을 주장하지 말고, 새 post-action camera image에서 물체가 실제로 grip에 고정되고 원래 위치에서 이동했는지 확인하도록 한다. 카메라가 3초 이상 안정되지 않았으면 pick/place를 거부한다. 이 설계는 관측을 이용한 사후 확인이 필요하다는 좋은 참고다. 다만 verifier도 모델 관찰이므로, Rosy가 이미 정한 별도 목표 증거/검증 계약을 대체하지 않는다. [pick completion and visual verification policy](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent/core/tool_call_handler.py#L41-L86), [camera stability rejection and response](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent/core/tool_call_handler.py#L168-L212)

모델 API 안내도 모델은 실수할 수 있고 물리 로봇은 피해를 낼 수 있으므로 안전한 환경을 유지할 책임은 개발자에게 있다고 명시한다. 이 문서는 sample을 안전 인증 또는 물리 보증 자료로 간주할 수 없음을 분명히 한다. [공식 ER safety/limitations](https://ai.google.dev/gemini-api/docs/robotics-overview#safety)

## Rosy 설계와의 비교

| 영역 | 공식 샘플에서 확인된 것 | Rosy에서 유지/보강할 점 |
|---|---|---|
| 모델 tool 사용 | tool schema 선언, call dispatch, 결과 회신 | tool call은 **요청 메시지**이며 Action 권한/실행 승인과 분리 |
| 좌표/grounding | 2D normalized point/box와 object label, 별도 depth/robot backend 변환 | frame, image size, camera/time/calibration provenance 포함; 좌표만으로 ROS goal 생성 금지 |
| 작업 종류 | navigation, detect, pick, place, gripper, wait 등 named functions | 공개된 capability catalog를 device profile과 safety policy에서 생성 |
| 긴 작업/피드백 | blocking function, 반복 호출, post-action frame, 결과를 model에 회신 | Mission/Action 상태 피드백과 ROS goal 수락/진행/종단 결과를 구별하고 이벤트 journal에 영속화 |
| 중지 | 모델이 호출할 수 있는 `stop`와 backend HTTP stop | 별도 로컬 stop API/fence/세대 번호·ACK, 독립 물리 E-stop 유지 |
| 공급자 호환 | Google Live API/Interactions 전용 형식 | 공통 Rosy tool/action envelope + provider adapter 및 capability 선언 |
| 완료 판정 | sample은 모델에게 영상 확인을 지시하지만 최종 판단 역시 모델 응답 경로 | D-328 목표 증거/검증자와 controller 상태가 완료의 원장 |

**일치 판단:** 공간 추론·tool orchestration·다단계 pick/place·로봇별 backend 분리를 원하는 Rosy 방향과 개념상 일치한다. **불일치/미충족:** sample은 Fleet grant, Rosy Mission, device-local ROS command owner, 독립 stop/E-stop, provider-neutral schema, durably correlated action lifecycle을 규정하지 않는다. 이 차이를 ADR에서 명시해야 한다.

## ADR 및 구현 계획으로 넘길 설계 질문

조사만으로 구현 계약을 확정하지 않는다. 다음 항목을 다음 ADR 결정/계획의 체크리스트로 권고한다.

1. **공통 Model Tool/Action Protocol:** provider request/session ID, provider tool-call ID, Rosy message ID, `mission_id`, durable `action_id`, idempotency key, capability/schema version 간의 구분·상관 규칙을 정의한다.
2. **Capability catalog:** model에 노출하는 typed tool은 device가 실제 지원하는 승인된 capability에서 만들고, schema·preconditions·blocking/async·timeout·feedback contract·risk class를 포함한다. ROS topic/action/service 이름은 provider surface에 노출하지 않는다.
3. **Intent → grant → dispatch:** tool call은 Action intent/request로 해석한다. Fleet owner가 mission/order/grant를 결정하고, 디바이스 local owner가 grant/fence/capability를 검사해 ROS goal/action으로 전환한다. 모델이 ROS나 driver를 직접 호출할 수 없도록 한다.
4. **Action feedback lifecycle:** `REQUESTED → VALIDATED/REJECTED → GRANTED → DISPATCHED → ACCEPTED/RUNNING → SUCCEEDED/FAILED/CANCEL_REQUESTED/CANCEL_ACK/UNKNOWN` 같은 공통 상태와 model-specific function response mapping을 정의한다. controller accept, physical terminal result, goal evidence, user-facing completion은 분리한다.
5. **Stop 경로:** 모델이 요청하는 정상 `stop` tool과 local stop/fence, hardware E-stop의 독립 경로 및 우선순위를 정의한다. stop 요청과 stop 완료 ACK를 다른 message로 기록한다.
6. **관측 공간 계약:** image point/box는 pixel coordinate provenance와 함께 전달하고, geometry/depth/TF/collision planning 책임자를 명시한다. ER 출력은 후보 grounding이지 executable pose가 아니다.
7. **Provider capability profiles:** ER 2 Interactions, ER 2 Streaming, 기타 모델의 구조화 출력, 영상 입력 cadence, blocking call, session/cancel 동작을 feature matrix로 분리한다. 스트리밍을 servo loop로 간주하지 않는다.
8. **실행 계획 gate:** ROS-free contract/schema/conformance tests → fake provider/tool-call replay와 idempotency/late response/stop tests → ROS 2 Jazzy+MoveIt/OMX simulation pick-place → stop/failure injection → device-local owner/runtime 검증 순으로 진행한다. 모델 summary만으로 완료시키지 않고 D-328 목표 evidence gate를 통과시킨다.

## 출처

- [Official repository: google-gemini/robotics-samples](https://github.com/google-gemini/robotics-samples)
- [ER starter notebook](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/Getting%20Started/gemini_robotics_er.ipynb)
- [Live API examples README](https://github.com/google-gemini/robotics-samples/blob/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/README.md)
- [Official ER overview and model endpoint capability table](https://ai.google.dev/gemini-api/docs/robotics-overview)
- [Official task orchestration reference](https://ai.google.dev/gemini-api/docs/robotics-orchestration)
- [Official Robotics Live API reference](https://ai.google.dev/gemini-api/docs/robotics-streaming)
- [Current Rosy decision D-331](../adr/D-331-gemini-er2-proposal-adapter.md)
