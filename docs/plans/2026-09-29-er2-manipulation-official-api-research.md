# ER 2, Franka, MoveIt 조작 API 근거 조사

> 2026-09-29 조사. ADR 작성용 근거 노트. 공식 공개 문서에 적힌 기능과 Rosy OS에 대한 설계 추론을 구분한다. 실제 장치 연동, 성능, 정지 시간은 검증하지 않았다.

## 핵심 결론

Gemini Robotics ER 2를 `point` 좌표 생성기로만 정의하면 기능을 과도하게 좁힌다. Google은 이 모델을 공간 추론과 다단계 작업 계획, **사용자가 선언한 로봇 함수 호출**을 수행하는 VLM으로 설명한다. 표준 엔드포인트는 structured output과 function calling을 지원하고, streaming 엔드포인트는 Live API와 function calling을 지원한다. 둘 다 공개 API의 출력 모달리티는 Text이다. 따라서 모델이 모터를 직접 제어하거나 사용자의 로봇 API가 자동 제공된다는 뜻은 아니다. [Google ER 개요](https://ai.google.dev/gemini-api/docs/robotics-overview)

Google의 공식 pick-and-place 예시는 `move(x,y,high)`와 `setGripperState(opened)`를 **mock custom robot API**로 선언하고 함수 결과를 다시 모델에 전달한다. 이는 함수 조합 능력의 예이지, 2D 좌표만으로 실제 로봇이 안전하게 집을 수 있다는 증거는 아니다. [Google 작업 오케스트레이션](https://ai.google.dev/gemini-api/docs/robotics-orchestration)

## 공식 API 사실

| 영역 | 확인된 사실 | 설계에 주는 의미 |
|---|---|---|
| ER 2 공간 출력 | 점, bounding box, 영상 추적, trajectory를 생성할 수 있다. `[y,x]` 0–1000은 예제 **프롬프트가 지정한 형식**이다. | 후보 인식 결과의 한 형식으로만 받는다. 원본 관측·프롬프트·좌표 계약과 함께 저장한다. [공식 공간 추론](https://ai.google.dev/gemini-api/docs/robotics-spatial) |
| ER 2 도구 호출 | 표준 엔드포인트에서 로봇 함수를 선언하고 모델이 호출할 수 있다. 예제는 함수 호출 ID에 대응하는 결과를 `previous_interaction_id`로 후속 호출에 전달한다. | `pick`, `place`, `pick_place`, `observe`, `get_status` 같은 의미적 능력을 Rosy가 정의할 수 있다. 도구 호출은 실행 요청 후보이며 실행 권한은 로컬 제어 경계에 둔다. [공식 작업 오케스트레이션](https://ai.google.dev/gemini-api/docs/robotics-orchestration) |
| ER 2 streaming | `gemini-robotics-er-2-streaming-preview`에서 `navigate`, `grasp`, `speak` 같은 도구를 선언한다. 물리 작업은 `behavior: BLOCKING`으로 완료 결과를 기다리게 한다. 모델의 `tool_call`을 애플리케이션이 실행하고 대응 `tool_response`를 반환한다. | 장시간 조작을 모델 대화 한 턴으로 간주하지 않고 작업 ID·피드백·최종 결과를 연결해야 한다. [공식 streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming) |
| 모델별 차이 | 표준 ER 2는 structured output 지원/Live API 미지원, streaming ER 2는 Live API 지원/structured output 미지원이다. 두 엔드포인트 모두 function calling을 지원한다. | 같은 검증 스키마를 쓰더라도 각 모델의 wire adapter를 따로 구현·검증해야 한다. [공식 모델 표](https://ai.google.dev/gemini-api/docs/robotics-overview#model_endpoints) |
| MoveIt Task Constructor | 조작 작업을 `Task`와 여러 `Stage`로 구성한다. 공식 pick/place 예시는 grasp 생성, approach, gripper close, scene attach, lift, place, detach, retreat 등으로 계획을 구성한다. | `pick_place`는 하나의 상위 Device Action일 수 있지만 그 안에는 관측·grasp 후보·planning scene·팔·그리퍼·검증 단계가 필요하다. MoveIt 통합은 후보이고 OMX에서 작동함이 입증된 것은 아니다. [공식 MTC 튜토리얼](https://moveit.picknik.ai/main/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html) |
| Franka ROS 2 | `franka_ros2`는 libfranka의 ROS 2 통합이며 `franka_hardware`를 `ros2_control` 하드웨어 플러그인으로 제공한다. `franka_gripper`는 `homing`, `move`, `grasp`, `gripper_action` 액션과 `stop` 서비스를 제공한다. | Franka가 좋은 참조 구현인 것은 맞지만, Franka 전용 액션/서비스를 OMX 범용 외부 API로 복사할 근거는 없다. 장치별 adapter가 의미적 Device Action을 해당 드라이버 계약으로 번역해야 한다. [Franka 공식 ROS 2 문서](https://support.franka.de/docs/franka_ros2.html) |
| ROS trajectory | Jazzy `joint_trajectory_controller`는 `FollowJointTrajectory` 액션을 제공하고 궤적 실행 감시를 위한 기본 인터페이스로 권장한다. cancel 기본 동작은 현재 위치 hold이며, 선택적 감속 설정에는 조인트 velocity feedback과 감속 한계가 필요하다. | 액션 cancel은 조작 중단 요청이다. 실제 정지·하중 유지·물체 파지 여부를 별도 readback으로 판정해야 한다. [JTC 사용자 문서](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html), [cancel 동작](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/decelerate_on_cancel.html) |

## ADR에 필요한 API 계층: 설계 추론

1. **작업 목표/능력:** `pick(object_ref)`, `place(held_object_ref, target_ref)`, `pick_place(object_ref,target_ref)`와 `observe`, `get_status`를 모델/운영자/Fleet에 제공할 후보로 둔다. 작업대·팔·그리퍼별 지원 능력을 발견하고, 지원하지 않는 명령은 거절한다. 별도 `pick`은 집은 물체의 보유 상태를 재시작과 장애 뒤에도 증명·복구할 수 있을 때만 열어야 한다.
2. **지시 대상:** 모델의 텍스트 `"빨간 블록을 집어"`, 레이블/관계(`"왼쪽 트레이의 블록"`), point/bbox, 영상 시점은 모두 **대상 지정 후보**다. 로컬 관측에서 식별 가능한 object/target ref로 resolve하고 불명확하거나 중복되면 실행하지 않는다.
3. **계획/실행:** 로컬 middleware가 작업 가능 구역, 카메라·보정·TF, 최신 planning scene, grasp 후보, 충돌·도달성, 허가를 검사한다. ROS/MoveIt/장치별 controller가 실제 모션을 실행한다. Franka는 어댑터 사례이고 OMX에는 별도 구현·검증이 필요하다.
4. **작업 상태:** 요청 ID와 ROS goal ID를 연결하며 `accepted`와 `running`, `cancel_requested`, `stopped`/`failed`, `object_held`, `place_verified`를 구분한다. 모델에는 로컬 검증 결과를 되돌린다. 화면/모델의 성공 문구로 완료 처리하지 않는다.
5. **정지:** 사용자 일반 stop/cancel, 로컬 fault stop, 독립된 하드웨어 E-stop을 혼합하지 않는다. 모델 tool call은 E-stop 리셋 권한을 가지지 않는다. 정지 시 모델 호출도 중단·무효화하고, 장치 readback 및 운영자 판단 없이는 이어서 실행하지 않는다.

위 다섯 항목은 **제안**이다. 공식 문서가 Rosy OS의 API 형식, OMX grasp 품질, Franka와 OMX의 호환성, 하드웨어 안전 성능을 보장하지 않는다. 특히 Google 예제의 mock `move`/`setGripperState`는 물리 장치 제어 계약으로 채택하면 안 된다.

## 2026-09-29 공식 API 재확인 및 구현 경계 보완

이번 구현 전 Google의 현재 ER 2 API 표, Interactions REST, 오케스트레이션/스트리밍 가이드와 ER 2 모델 카드를 다시 대조했다. 기능 이름만 같다고 두 엔드포인트를 같은 전송 어댑터로 다루면 안 된다.

| 공식 자료에서 확인한 항목 | 구현에 반영한 경계 |
|---|---|
| 표준 `gemini-robotics-er-2-preview`는 Interactions API이며 function calling과 structured output을 지원하고 Live API는 지원하지 않는다. 공식 REST 공간 추론 예는 `/v1beta/interactions`, `x-goog-api-key`, `input.parts`의 `inlineData`/`text` 형태다. | `httpx`로 표준 Interactions endpoint에 1회 요청하는 provider adapter를 구현한다. 현재 제안은 함수 호출 하나를 파싱하며 structured output 및 provider 세션 재사용은 사용하지 않는다. |
| Interactions API는 기본적으로 호출을 저장한다. `store=false`는 서버 저장을 끄지만 `previous_interaction_id` 후속 호출과 양립하지 않는다. | 단일 관측·단일 제안 요청마다 `store=false`; provider 대화 세션을 만들지 않는다. 원본 이미지는 adapter 메모리에서 요청을 구성할 때만 읽고 앱 로그에 기록하지 않는다. |
| 공식 오케스트레이션 가이드의 `move(x,y,high)`/`setGripperState(opened)`는 mock API이고, 응답의 function call을 실제 수행하는 주체는 애플리케이션이다. 같은 Robotics 가이드 예시는 `steps`를, 일반 Interactions SDK는 `outputs`를 노출한다. | `propose_pick_place`만 선언하고 응답을 실행 콜백에 넘기지 않는다. 표준 응답 `outputs`를 우선 파싱하고 문서화된 `steps` 별칭을 허용하되 둘이 충돌하면 거절한다. 함수 결과를 모델에 회신하지 않는다. |
| Streaming endpoint는 별도의 Live API 모델이며 공식 표상 structured output과 여러 built-in tool을 지원하지 않는다. 로보틱스 스트리밍 가이드는 입력 이미지를 JPEG 최대 1 FPS로 제한한다. | 현재 작업형 후보 제안은 표준 endpoint만 구현한다. Streaming은 session lifecycle, interruption/cancellation, feedback semantics를 별도 검토할 때까지 보류한다. |
| ER 2 model card는 production/commercial/public 사용 전 판단을 요구하며 safety-critical applications에 사용하지 말라고 명시한다. | 본 adapter는 source-level non-safety-critical candidate path로만 둔다. 키 배포, production enablement, 안전 중요 task, 물리 실행은 이 구현으로 승인되지 않는다. |
| Google image input guide는 inline image, prompt 등 전체 요청 크기를 20 MB로 제한한다. | base64 확장과 요청 텍스트를 포함해 한도 안에 여유를 두도록 원본 이미지 바이트는 14 MiB에서 제한한다. 큰 이미지에는 이 어댑터를 쓰지 않으며 Files API 도입은 별도 검토한다. |

공식 자료: [ER overview](https://ai.google.dev/gemini-api/docs/robotics-overview), [orchestration](https://ai.google.dev/gemini-api/docs/robotics-orchestration), [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview), [image request size](https://ai.google.dev/gemini-api/docs/image-understanding), [streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming), [ER 2 model card](https://deepmind.google/models/model-cards/gemini-robotics-er-2/). 이 수정은 [D-331](../adr/D-331-gemini-er2-proposal-adapter.md)에 구현 결정으로 기록했다.

## 확인이 더 필요한 점

- 현재 Rosy OS의 OMX에 gripper 명령 소유자, calibrated 3D pose, planning scene/충돌 모델, 물체 보유 상태와 place 검증 경로가 각각 존재하는지 코드와 실기기 증거로 확인한다.
- 사용 예정인 OMX controller 및 Franka/MoveIt 버전의 실제 ROS 2 액션·서비스·취소 의미를 설치 대상 환경에서 확인한다. 위 MoveIt 문서는 Rolling이며 Jazzy 설치본과 API 호환성을 입증하지 않는다.
- `pick` 단독, `place` 단독, `pick_place` 복합 작업 중 첫 공개 API 범위와 지속 상태의 소유자를 ADR에서 결정한다.
- API 계약과 ROS 액션 매핑은 별도 구현 게이트를 거쳐야 한다. 문서의 예시는 배포된 API가 아니다.


## 2026-09-29 Gemini API 키·데이터 처리·ER 2 한계 추가 확인

> 확인일: 2026-09-29. 아래 내용은 이 날짜에 열람한 Google AI for Developers, Google Cloud, Google DeepMind 공식 문서 기준이다. 계정·지역·청구 설정에 따른 약관은 배포 전에 다시 확인해야 한다.

### 공식 문서에서 확인한 사실

- **키 종류와 전환 상태:** Gemini API는 standard key와 service account에 결합된 authorization key를 문서화한다. 2026-05-28부터 AI Studio에서 새로 만드는 키는 authorization key가 기본이며, Gemini API에 제한되고 유출 탐지 차단 기능을 제공한다. authorization key 요청은 Cloud service-account 사용량 지표에 기록되지 않는다고 안내한다. 현재 키 문서는 unrestricted standard key 거부를 설명하지만, 과거 검색 결과의 “2026년 9월부터 모든 standard key 거부” 일정은 열람한 최신 문서에서 확인하지 못했다. 그 일정을 현재 확정 정책으로 전제하지 않는다. [Gemini API 키 문서](https://ai.google.dev/gemini-api/docs/api-key)
- **키 보호·제한·회전:** 키를 Git이나 클라이언트 코드에 넣지 말고, 서버에서 환경 변수 또는 Secret Manager로 읽으며, REST 요청은 URL 쿼리 대신 `x-goog-api-key` 헤더를 사용한다. API 제한과 사용처 제한(IP 등)을 적용하고, 키를 앱별로 분리하며 사용량을 감시한다. Cloud의 회전 절차는 동일 제한의 새 키 생성 → 모든 소비자 전환 확인 → 이전 키 삭제 순서다. Gemini API 운영에서 authorization key를 쓸 때 결합 service account에 IAM 역할을 부여하지 말라고 Cloud가 명시한다. [Gemini API 키 문서](https://ai.google.dev/gemini-api/docs/api-key), [Cloud 키 보안 모범 사례](https://docs.cloud.google.com/docs/authentication/api-keys-best-practices), [Cloud 키 제한 및 회전](https://docs.cloud.google.com/docs/authentication/api-keys)
- **무료/유료 데이터 처리:** Gemini API는 활성 Cloud Billing 계정이 연결된 프로젝트를 통한 사용을 Paid Service로 정의한다. Unpaid Service에서는 프롬프트·시스템 지침·이미지 등 입력과 응답이 제품·모델 개선에 사용될 수 있고, 사람 검토자가 이를 읽거나 주석 처리할 수 있으므로 민감·기밀·개인정보를 제출하지 말라고 한다. Paid Service에서는 프롬프트와 응답을 제품 개선에 쓰지 않고 Data Processing Addendum에 따라 처리하지만, 위반 탐지·서비스 보안 및 법적/규제 공개를 위해 제한된 기간 로그할 수 있다. 약관은 기간을 구체적인 일수로 보장하지 않는다. [Gemini API 추가 약관](https://ai.google.dev/gemini-api/terms), [요금제별 데이터 사용 표](https://ai.google.dev/gemini-api/docs/pricing)
- **ER 2 사용 범위·한계:** ER 2 model card는 모델을 robotics용 시공간 추론, tool orchestration, physical-agent success detection에 특화된 VLM으로 설명한다. 동시에 production/commercial/public 환경 사용 전 재량 있는 판단을 요구하고, 오작동이 사망·부상·재산 피해를 초래할 수 있는 safety-critical 업무에서는 사용하지 말라고 명시한다. ER 2의 Known Limitations와 Acceptable Usage 세부사항은 Gemini 3.5 Flash model card로 위임되고, 그 카드도 한계·허용 사용 세부사항을 Gemini 3 Flash 카드로 위임한다. 따라서 ER 2 카드만으로 작업별 안전성이나 실패율을 보증할 수 없고, 제한사항이 완결되어 있다고 볼 수 없다. [ER 2 model card](https://deepmind.google/models/model-cards/gemini-robotics-er-2/), [Gemini 3.5 Flash model card](https://deepmind.google/models/model-cards/gemini-3-5-flash/)
- **이미지 요청 제한:** 인라인 이미지 문서는 프롬프트·시스템 지침·인라인 바이트를 합한 전체 요청의 상한을 20 MB로 제시하며, 더 큰 입력이나 재사용 입력에는 Files API를 권한다. 이는 API 크기 제한이지, 현장 카메라 프레임을 외부 서비스에 보내도 된다는 데이터 승인 근거가 아니다. [Gemini 이미지 입력 문서](https://ai.google.dev/gemini-api/docs/image-understanding)

### Rosy에 대한 설계 추론

- ER 2에는 선택 작업만 보내고, 로봇·작업자·시설을 식별할 수 있는 이미지를 다루는 실제 호출 경로는 **활성 Billing 프로젝트의 Paid Service 사용 여부를 확인**해야 한다. 무료 quota로 자동 대체되는 설정은 금지하고, billing·키·정책 상태를 확인할 수 없으면 모델 제안 요청을 거부하는 fail-closed 구성이 적절하다. 이는 Google 약관의 무료·유료 처리 차이를 Rosy 데이터 경계에 적용한 추론이다.
- 카메라 원본은 로컬에서 영역·해상도·프레임 수를 최소화하고 식별 정보를 줄인 뒤 전송한다. 요청·예외·추적 로그에는 키, 이미지/base64, 원문 프롬프트를 남기지 않고 필요한 감사 근거는 로컬 ID·digest·정책 결과로 남긴다. 20 MB 한도에 맞추려고 Files API로 원본을 무조건 올리는 동작도 추가 동의·보존 정책 없이는 선택하지 않는다.
- 키는 로봇/환경별 분리, Gemini API 전용 제한, 가능한 경우 고정 egress IP 제한, secret manager 주입, 비용·호출량 경보, 교체 및 폐기 절차가 필요하다. authorization key의 service account에는 IAM 역할을 주지 않으며, 해당 인증 요청이 service-account usage metrics에 없다는 점을 고려해 애플리케이션 측 호출·오류 상관관계를 기록한다. 회전은 이전 키 폐기 전 새 키 전환 검증을 포함한다.
- ER 2 model card의 safety-critical 제한을 전제로 어댑터는 제안 생성용 비안전핵심 후보 경로로만 둔다. ER 2 응답이나 모델의 성공 판단을 안전성 증명으로 취급하지 않는다. 안전 검증, 충돌/작업공간 검사, ROS action 실행 권한, stop/E-stop과 장치 readback은 Rosy/ROS 로컬 제어 경계에 둔다. 상업·공개 운영과 촬영 데이터 처리 적합성은 source 구현만으로 승인되지 않으며 별도 법무·운영 판단이 필요하다.

### 확인 시 남은 모호성

- 현재 키 문서는 unrestricted standard key 거부를 명시하지만, 전체 standard key 폐기 일정은 확인되지 않았다. 새 구현은 authorization key 호환성을 우선 검증하되, 실제 프로젝트 키 종류와 Gemini API 접근은 배포 전 해당 계정에서 확인해야 한다.
- Paid Service도 제한된 기간의 입력·응답 로그를 허용하지만, 확인한 약관은 정확한 보존 기간이나 모든 지역별 세부 적용을 특정하지 않는다. Rosy가 임의 보존 기간을 단정해서는 안 된다.
- ER 2 카드가 상위 Gemini 3.5 Flash 및 Gemini 3 Flash model card로 제한사항을 위임하므로, 여기서는 ER 2 조작 성공률·좌표 오차·안전 임계값을 보증하지 않는다. 작업·카메라·로봇별 검증이 별도로 필요하다.
