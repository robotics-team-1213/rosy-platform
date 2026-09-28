## D-326 의미 기반 조작 Action과 장치별 ROS 실행 어댑터를 분리한다

**Status:** Proposed (2026-09-29). 의미·권한·검증 기준의 제안이다. 새 REST endpoint, ROS action, `TaskKind`, OMX/Franka 운영 capability, 물리 동작이나 정지 성능을 승인하지 않는다.

### Context

사용자는 “이걸 집어”, “빨간 블록을 들어”, “초록 트레이에 놓아”처럼 물체와 목표를 말한다. ER 2는 점·box만 반환하는 모델이 아니다. Google은 표준 ER 2의 구조화된 출력·함수 호출과 streaming ER 2의 Live 함수 호출을 제공하며, pick-and-place 예시에서 사용자 정의 로봇 함수를 순서대로 호출한다. 해당 예시의 `move(x,y,high)`와 `setGripperState(opened)`는 **mock API**이다. 영상의 2D 점이나 모델이 선택한 함수명만으로 물체의 3D 위치, 파지 자세, 충돌 회피, 그리퍼 보유, 하중 지지 또는 물리 정지가 검증되지 않는다.

현재 ROSY의 외부 조작 API는 없다. `TaskKind`에는 Pick/Place가 없고 OMX profile은 disabled이다. OMX adapter의 카메라 freshness 검사와 단일 trajectory submitter 후보는 있지만, 인식 대상의 영속 ID·grasp 계획·그리퍼 및 보유 상태·placement 검증·원격 Action 결과 계약은 없다. D-308은 Intent 후보와 Fleet Mission/Step, 장치 로컬 Action 해석을 분리했다. D-55의 로봇 로컬 manipulation transaction과 D-70의 사이트 Mission 원장도 유지해야 한다. 이전 [ER 2 설계안](../plans/2026-09-29-embodied-reasoning-device-action-design.md)은 첫 고정 작업대 시나리오를 복합 `PICK_PLACE`로 좁혔지만, 플랫폼이 지원할 의미적 조작 능력 전체를 정의하지 않았다.

### Decision

1. **의미적 조작 능력을 장치별로 광고한다.** 공통 어휘의 후보는 읽기 전용 `OBSERVE`/`RESOLVE_TARGET`, 목표 작업 `PICK`, `PLACE`, `PICK_PLACE`, `GET_ACTION_STATUS`, 일반 `CANCEL`이다. 이는 **논리적 capability 이름**이며 현재 wire enum이나 endpoint가 아니다. `PICK`은 검증된 물체를 집어 안전하게 보유한 상태가 결과이고, `PLACE`는 검증된 보유 물체를 지정된 지점에 내려놓고 보유 해제까지 확인한 결과다. `PICK_PLACE`는 둘을 한 로컬 transaction으로 묶는다. grasp 자세·그리퍼 폭·관절 각도·trajectory·모터 속도는 장치 내부 계획/제어 값이며 이 의미적 명령의 필수 사용자 입력이 아니다.
2. **대상 지시 방식은 복수로 받되, 실행 대상은 하나로 확정한다.** 사용자 텍스트, 물체 label/관계, 모델의 point/bbox/영상 시점, 운영자가 고른 inventory ID는 모두 *selector 후보*다. “이걸”은 해당 화면·카메라·관측 시각과 선택 지점을 연결하지 못하면 모호하다. 장치 로컬 관측은 후보를 한 `object_ref` 또는 `target_ref`로 resolve하고 원본 프레임, 카메라·좌표계, 보정/TF revision, 추적 identity, 신선도와 불확실성을 연결한다. 후보가 없거나 여러 개이거나 이동·가림·보정 불일치가 있으면 명확화 또는 거절한다. 2D 좌표를 선택 사항으로 두되 좌표를 제공한 경우에도 이 절차를 생략하지 않는다.
3. **모델 도구 호출은 후보이며 장치 API 수락과 구별한다.** ER 2 외에도 운영자, Fleet, 다른 모델은 같은 의미적 요청을 만들 수 있다. 모델에는 현장에서 허용된 capability만 도구로 노출하고 모델 credential로 ROS/DDS, driver 또는 E-stop release를 직접 호출하지 않는다. 서버는 인증된 principal, 작업대 identity, capability/version, mode/lease, 요청 기한·중복 키, observation·configuration revision, 금지구역 및 현재 장치 상태를 독립 검사한다. 장시간 물리 도구는 모델별 tool-call ID와 장치 `action_id`/`attempt_id`를 연결하고 권위 있는 최종 결과가 확인된 후에만 완료 응답을 보낸다. 모델 세션 종료나 텍스트의 “완료”는 Action 완료가 아니다.
4. **로컬 미들웨어가 조작 transaction을 소유하고 ROS가 동작을 실행한다.** OMX/Franka 등 각 제품 adapter가 gripper·camera·planning scene·joint state·payload와 단일 최종 명령 owner를 확인한다. grasp 후보 생성, 접근/파지/들기, 운반/배치/해제는 MoveIt Task Constructor 같은 로컬 계획 경로 또는 검증된 제품별 규칙으로 구현할 수 있다. ROS action 및 `ros2_control`/vendor driver는 관절·그리퍼 실행과 feedback을 맡는다. Fleet은 Mission/Step 순서와 결과 원장을 소유하되 trajectory를 제출하지 않는다. Franka의 ROS 2 `grasp` action과 `stop` service는 **Franka adapter 내부의 참조 사례**이며 OMX나 공통 외부 API에 그대로 복사하지 않는다.
5. **단독 `PICK`/`PLACE`는 보유 상태 계약을 통과한 장치에서만 연다.** `PICK` 성공 뒤 물체 identity, 그리퍼 상태, 하중/파지 readback, 제한된 보유 시간, 정지·단절·재시작 복구 정책을 장치가 지속 관리해야 한다. `PLACE`는 그 보유 영수증과 새 목적지 관측을 검증해야 한다. 소유권·보유 상태가 불명확하면 자동 놓기, 자동 재파지, 다른 작업 시작을 금지하고 HOLD한다. 첫 고정 OMX 작업대에서는 이 계약 전까지 기존 설계안의 복합 `PICK_PLACE`만 구현·검증 후보로 둔다. 이것이 플랫폼의 `PICK`/`PLACE` 의미적 지원 범위를 영구히 제한하지는 않는다.
6. **중단과 안전 정지의 사실을 분리한다.** queued 요청 취소, 진행 중 Action cancel, 로컬 fault HOLD, 독립 E-stop은 별도 경로다. cancel ACK·ROS goal 결과·controller hold 명령만으로 물리 정지나 물체 보유 안전을 선언하지 않는다. 관절/그리퍼/드라이버 readback과 작업대별 물체 낙하 위험을 확인한다. 안전 경로는 모델·Fleet·네트워크를 기다리지 않으며, E-stop 해제나 재시작이 미완료 Action을 자동 재개하지 않는다. 현재 Pinky/Fleet site stop 가용성의 D-308 제한도 유지한다.

### 계약 경계와 예시

| 입력 | 의미적 처리 | 필요한 추가 증거 |
|---|---|---|
| “이걸 집어” + 화면 선택 | selector → 단일 물체 resolve → `PICK` capability 확인 | 프레임 출처, 물체 identity, 파지/보유 상태; 단독 PICK 비활성 장치라면 거절 |
| “빨간 블록을 초록 트레이에 넣어” | 두 대상 resolve → `PICK_PLACE` transaction | source/destination geometry, 충돌/도달성, 파지·배치 검증 |
| ER 2의 `[y,x]` 또는 bbox | 해당 관측의 대상 후보 | 프롬프트 좌표 형식, crop/회전 역변환, 카메라 보정, 3D/작업면 추정 |
| `Franka gripper grasp` 결과 | 장치 내부 파지 단계 결과 | 물체 보유·목표 달성은 별도 판정; Franka 전용 action을 외부 공통 API로 승격하지 않음 |

실제 REST/ROS 경로·필드·enum은 D-18에 따라 API Reference와 `core_common.protocol.schemas` 및 생산자·소비자 시험을 같은 변경에서 확정한다. capability 문서만으로 endpoint가 존재하거나 사용 가능하다고 표시하지 않는다. 공통 wire 계약은 OMX와 다른 장치의 실제 소비 표본이 생긴 뒤 최소 항목부터 추출한다.

### Alternatives

- **좌표→trajectory 직접 변환:** 이미지 점으로 목표를 만들기 쉽지만 높이·자세·충돌·보유 검증이 없어 채택하지 않는다.
- **모델에 `move`/`setGripperState`를 운영 도구로 직접 제공:** Google의 mock 예시는 동작 조합을 설명한다. ROSY에서는 저수준 command와 정지 소유권을 모델로 넘기므로 채택하지 않는다.
- **복합 `PICK_PLACE`만 영구 공개:** 첫 고정 작업대 구현에는 적합하지만 단독 집기·인계·검사·다른 팔의 능력을 표현하지 못해 플랫폼 계약으로 채택하지 않는다.
- **장치별 의미적 Action + 로컬 ROS adapter:** 외부 의도를 일정하게 유지하면서 장치별 검증·정지·드라이버 차이를 보존하므로 제안한다.

### Transition / validation

1. SOURCE: 현행 OMX/Franka 하드웨어 inventory와 gripper·camera·관절·보정·ROS action 경로를 확인한다. ER 2 표준/streaming 입력 adapter가 같은 selector 후보로 정규화되고, mock 함수가 실제 실행 권한을 갖지 않음을 시험한다.
2. LOCAL/ROS-SIM: 모델 없는 운영자 요청으로 `PICK_PLACE`를 먼저 시험한다. 텍스트/point/bbox/ID selector의 동일 대상 resolve, 다중 후보·stale frame·대상 이동·grasp 불가·충돌·중복 요청·늦은 결과·단절·취소를 주입한다. 로컬 transaction과 ROS goal/그리퍼 feedback의 ID를 끝까지 연결한다.
3. ARTIFACT/DEVICE: 장치별 native payload와 driver 호환성, 단일 최종 writer, 그리퍼 파지·하중·정지·물체 낙하·재시작 뒤 보유 상태를 측정한다. 단독 `PICK`/`PLACE`는 이 보유 계약이 통과한 뒤 별도 capability로 활성화한다. Franka 문서의 ROS action 존재는 ROSY 설치 버전이나 OMX 실행 증거가 아니다.
4. FIELD: 작업대 작업 성공/실패와 물리 정지, 사람·물체가 있는 현장의 감독/복구를 독립 판정한다. Pinky 이동과 팔 조작을 결합하려면 D-55의 적재 상태·주행 envelope 및 별도 수용이 필요하다.

**Consequences:** 모델/운영자/다른 계획기는 동일한 의미적 조작 후보를 제시할 수 있다. 첫 구현은 `PICK_PLACE`여도 API 개념은 `PICK`/`PLACE` 확장을 수용한다. 이번 ADR은 기존 D-308의 의도 경계와 D-282/D-299의 장치 소유권을 구체화하며, 아직 구현되지 않은 capability나 실물 안전을 GO로 승격하지 않는다.

**References:** [공식 API 조사](../plans/2026-09-29-er2-manipulation-official-api-research.md), [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-70](D-70-fleet.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-307](D-307-final-action-outcome-and-stop-readback-evidence.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [Google ER 2 개요](https://ai.google.dev/gemini-api/docs/robotics-overview), [Google 조작 예시](https://ai.google.dev/gemini-api/docs/robotics-orchestration), [Google streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming), [MoveIt Task Constructor](https://moveit.picknik.ai/main/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html), [Franka ROS 2](https://support.franka.de/docs/franka_ros2.html), [ROS 2 Jazzy JTC](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html).
