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

## 확인이 더 필요한 점

- 현재 Rosy OS의 OMX에 gripper 명령 소유자, calibrated 3D pose, planning scene/충돌 모델, 물체 보유 상태와 place 검증 경로가 각각 존재하는지 코드와 실기기 증거로 확인한다.
- 사용 예정인 OMX controller 및 Franka/MoveIt 버전의 실제 ROS 2 액션·서비스·취소 의미를 설치 대상 환경에서 확인한다. 위 MoveIt 문서는 Rolling이며 Jazzy 설치본과 API 호환성을 입증하지 않는다.
- `pick` 단독, `place` 단독, `pick_place` 복합 작업 중 첫 공개 API 범위와 지속 상태의 소유자를 ADR에서 결정한다.
- API 계약과 ROS 액션 매핑은 별도 구현 게이트를 거쳐야 한다. 문서의 예시는 배포된 API가 아니다.
