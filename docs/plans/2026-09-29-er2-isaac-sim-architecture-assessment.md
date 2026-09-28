# ER 2 Isaac Sim 사례와 ROSY 작업 구조 대조

**상태:** SOURCE 설계 검토 (2026-09-29). 이 문서는 실물 또는 Isaac Sim 실행 결과가 아니다. 검토 기준 checkout: `docs/er2-action-boundary`의 `a48870b2`.

## 자료 출처와 확인 범위

- [사용자가 제공한 원문](2026-09-29-er2-isaac-sim-user-source.txt)을 12,330 byte 그대로 보관했다. SHA-256: `73a1dcb7e63011bf513cbfdd2547bd28db330ca19dd4847a7ee1fc83b2521502`. 원문에 들어 있는 `Pasted text` 문자열도 보존했다.
- 사용자가 원본으로 지정한 영상은 [엥지유니버스의 ER 2·Isaac Sim 영상](https://www.youtube.com/watch?v=HmH8X7_3wIU)이다. YouTube oEmbed에서 영상 ID·제목·채널을 확인했다. 자막 응답은 비어 있어 영상의 4.56초, 21.26초, API 호출 19회, 완료 시점 64/67초 등의 **세부 수치와 장면은 독립 재검증하지 못했다**. 아래에서는 이를 원문 보고값으로만 다룬다.
- 모델 기능은 [Google ER 2 개요](https://ai.google.dev/gemini-api/docs/robotics-overview), [작업 오케스트레이션](https://ai.google.dev/gemini-api/docs/robotics-orchestration), [streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming), [동영상 진행도](https://ai.google.dev/gemini-api/docs/robotics-video-progress)로 별도 확인했다. Google의 pick-and-place 로봇 API는 mock 예시다. 영상 실험의 장치 안전성이나 성공률을 입증하는 공식 자료로 사용하지 않는다.

## 사례에서 가져올 구조와 현재 간극

현재 상태의 소스 근거는 Fleet의 [navigation 전용 영속 작업·policy 비활성](../../src/site/fleet/fleet/server/task_service.py), [`/api/fleet/do`의 순차 `steps`](../../src/site/fleet/fleet/server/app.py), [고정 `TaskKind`](../../src/contracts/foundation/core_common/domain/tasks.py), [OMX disabled profile](../../src/products/omx/profile/config/omx.disabled.yaml), [OMX 카메라 계약](../../src/products/omx/adapter/omx_adapter/camera_contract.py)과 [팔 ROS action client](../../src/products/omx/adapter/omx_adapter/ros_runtime.py)이다. 기존 소유권은 [D-308](../adr/D-308-intent-and-device-action-interpretation-boundary.md), 의미적 조작 계약 후보는 [D-326](../adr/D-326-semantic-manipulation-actions-and-device-adapters.md)에 기록되어 있다.

| 사례의 상황 | ROSY에서의 책임 | 현재 SOURCE 상태 | 설계 출구 |
|---|---|---|---|
| 한 장면의 점/물체 찾기 | 관측 출처·보정·대상 ID를 가진 후보 만들기 | OMX `CameraFrameGate`는 Image/CameraInfo freshness를 검사하나 3D 대상·파지·배치 판정은 없다 | 모델 selector를 관측 ID에 결합하고 대상 이동·가림·좌표계 오류를 거절 |
| “집어서 트레이에 놓아” | Fleet은 목표, OMX 로컬 owner는 `PICK_PLACE` Action과 ROS 실행 | OMX profile disabled; `FollowJointTrajectory` client 후보만 있고 외부 조작 API·gripper/placement 결과 계약은 없다 | D-326의 의미적 Action, 장치 capability·단일 writer·그리퍼/물체 readback을 별도 구현 |
| 실행 중 대상 이동 | 장치 로컬 freshness/충돌 감시가 즉시 HOLD; 모델 신호는 재관찰·재계획 후보 | 연속 장면 변화 감지→취소→새 goal 경로 없음 | 모델 지연과 무관한 로컬 정지 시험, 이벤트 시각·취소·실제 정지 시각을 분리 기록 |
| 두 팔 병렬 실행 | Fleet Mission DAG의 독립 Step이 두 장치 Action을 비동기로 dispatch | Fleet durable task는 Pinky navigation 단일 단계에 한정. `/api/fleet/do`의 `steps`는 순차 호출이며 Mission DAG가 아니다 | 병렬 Step의 join, retry budget, reservation/충돌 구역, 결과 연결을 Fleet 원장에 구현 |
| 실패 후 재구성 | 모델은 새로운 계획 후보; Fleet은 기존 attempt 최종 결과와 자원 상태를 보존·검증 후 새 Step 생성 | `POLICY_DISPATCH_ENABLED=False`; navigation attempt 상관관계만 존재 | 물리 효과 중복 방지, 보유 물체·목표 상태 재관찰, 승인된 재계획만 dispatch |
| A 팔 → 운반 로봇 → B 팔 인계 | Fleet이 dependency와 goal을 소유, 각 장치가 로컬 Action을 소유 | Pinky+OMX 인계 Mission, 운반물 보유/적재 영수증, 이동 중 하중 envelope 없음 | 적재·팔 후퇴·운반물 고정→주행→도착·보유 확인→하역의 증거 장벽; D-55 게이트 |
| 모델이 완료라고 말하지만 물체가 남음 | Fleet 목표 판정기가 장치 결과와 독립 관측을 대조 | D-307/D-308은 의미 기준을 정했지만 다장치 goal predicate/evaluator는 없다 | 모델의 완료 텍스트·진행도와 분리된 goal evidence, 불명확하면 미완료/HOLD |
| 동영상 진행도 추정 | 운영자 보조 신호·재관찰 우선순위 후보 | 모델 영상 결과와 ROSY Mission 증거 연결 없음 | 표준 ER 2 영상 분류를 관측으로 저장하되 최종 성공 권한은 주지 않음 |

원문에서 보고한 4.56초 변화 감지 지연은 **안전 정지 상한이 아니다**. 영상의 비동기 병렬성 또한 ROSY에 같은 API나 scheduler가 있다는 증거가 아니다. 별도 main 작업트리에 작성 중인 D-322 Isaac Sim 초안은 Pinky/OMX 형상·import 방향이며, 이 checkout에 통합된 계약이나 Franka 두 대와 Spot의 조작/운송 실험을 재현한 ROSY 증거는 아니다.

## 권장 작업 구조

```text
사용자 목표 + 관측 증거
  → ER 2/기타 모델의 Plan 또는 Next-Step 후보 (실행권 없음)
  → Fleet 입구: principal·capability·대상·목표 predicate·기한·정책 확인
  → Fleet Mission 원장: Step 의존 그래프, 장치/구역 예약, action/attempt ID
  → 장치별 Device Action API: 로컬 상태·보정·계획·stop 경계 확인
  → ROS action/controller/vendor driver: 모션·gripper 실행과 readback
  → Fleet 증거 평가: Action 종료 + 독립 물체/위치/적재 관측 + 목표 predicate
  → 성공 / 미충족 / 결과불명 / 안전 HOLD 중 하나로 조정
```

**원장과 모델 세션을 분리한다.** 모델은 `propose_plan`, `propose_next_step`, `request_observation` 같은 후보 도구를 사용할 수 있으나 장치 운영 credential을 갖지 않는다. Fleet이 승인한 Mission만 장치에 보낸다. 모델 세션이 끊겨도 Mission·Step·Action·attempt와 이벤트 시각은 남고, 동일 요청 재전송은 새 물리 동작으로 자동 변환되지 않는다. 표준 ER 2와 streaming ER 2는 서로 다른 adapter를 사용한다. Google streaming의 물리 tool `BLOCKING`은 **해당 tool 결과를 기다린다**는 모델 프로토콜이지, 전체 사이트 scheduler나 E-stop을 구현한 것이 아니다. 서로 다른 장치의 병렬 실행은 Fleet의 독립 Step으로 스케줄한다.

**성공 조건을 명령 전에 정의한다.** 예를 들어 `red_block in green_tray`는 원본 모델 문장이 아니라 목표 predicate다. Action의 `SUCCEEDED`는 arm/gripper transaction 결과이며, Fleet 성공은 목적지 관측의 물체 identity, 트레이 유효 영역, 그리퍼 해제, 필요한 팔 후퇴 및 관측 신선도를 대조한 뒤 별도로 판정한다. 센서/카메라 자료 자체가 불명확하면 새 관측을 요청하거나 HOLD한다. 같은 모델의 “완료” 문구와 영상 진행률은 보조 관측으로 기록하되 독립 판정 근거를 대신하지 않는다.

**재계획은 상태 전이로 제한한다.** 모델이 대상 이동·장애를 보고해도 먼저 장치의 로컬 owner가 새 명령 차단/안전 상태를 처리한다. Fleet은 기존 attempt의 권위 있는 결과, 실제 정지, 물체 보유/적재, 장치 구역 예약을 조회한 다음에만 새 계획 후보를 심사한다. 실패한 pick을 무조건 재시도하지 않는다. 물체가 이미 옮겨졌거나 한 로봇의 gripper가 쥔 상태라면 새 계획은 그 상태에서 시작해야 한다.

**인계는 관찰 가능한 장벽이다.** 운반 로봇 출발 전 `load_present`, `load_secured`, `A_arm_clear`, `base_ready`를 확인한다. 도착 후에는 `arrived`만으로 하역하지 않고 `load_still_present`, `B_workcell_ready`를 확인한다. 각 항목의 출처·신선도·오류 가능성은 장치별로 정의한다. 이 predicate는 예시이며 실제 threshold나 관측 장치는 현장 실측 전까지 확정하지 않는다.

## 구현 순서와 중단 조건

1. **계약·관측:** 모델 없이 목표 predicate와 object/target ref, 관측 provenance·staleness, 장치 capability/version을 정한다. OMX 보정·3D 지오메트리·gripper feedback이 없으면 움직임을 열지 않는다.
2. **단일 장치:** 고정 OMX `PICK_PLACE`를 운영자 요청으로 ROS-SIM에서 검증하고, 로컬 Action 결과와 별도 goal predicate를 비교한다. 실물 DEVICE 수용 전에는 `omx.enabled: false`를 유지한다.
3. **Fleet Mission:** 단일 Step 원장 → 두 독립 Step 병렬 → 의존 Step 인계 순으로 확장한다. 현재 `/api/fleet/do`의 순차 `steps`를 Mission 엔진으로 승격해 표기하지 않는다.
4. **ER 2 보조:** 동일 장면에 규칙 기반/사람/ER 2 후보를 넣고 대상 resolve, 단계 선택, 재계획, 오탐·미완료·늦은 신호를 비교한다. 모델의 결과로 안전 경로를 닫지 않는다.
5. **Isaac Sim:** 별도 진행 중인 D-322의 형상·ROS 경로와 구분해 카메라/깊이/충돌/그리퍼/적재/goal oracle을 갖춘 fixture를 만든다. 정상·대상 이동·grasp 실패·잘못된 완료·통신 단절 반례를 재현한다. Isaac 통과를 DEVICE/FIELD로 승격하지 않는다.

이 문서와 [D-327](../adr/D-327-model-proposed-missions-and-independent-goal-evidence.md)은 구조 제안이다. API 경로·envelope을 실제로 열 때는 D-18에 따라 API Reference, 공유 schema, 생산자·소비자 시험을 함께 변경한다.
