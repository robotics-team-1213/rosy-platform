# Embodied reasoning에서 Device Action까지의 처리 설계

**상태:** Proposed design (2026-09-29). 새 API, `TaskKind`, OMX capability, 모터·팔 명령 권한 또는 DEVICE/FIELD 수용을 활성화하지 않는다.

**첫 대상:** 고정형 OMX 작업대의 알려진 가벼운 블록 한 종류를 지정 트레이에 옮기는 작업. Pinky 주행과 팔을 결합한 이동 조작은 이 설계의 후속이며, 기존 [D-55](../adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md)와 [D-305](../adr/D-305-platform-boundary-outcome-invariants-and-independent-gates.md)의 별도 상호 인터록·DEVICE/FIELD 게이트를 따른다.

## 1. 결정할 문제와 현재 기준선

사용자가 “빨간 블록을 초록 트레이에 넣어”라고 요청하고 모델이 `red block`의 점 `[575, 664]`, `green tray`의 점 `[475, 305]`를 반환해도, 두 점은 곧바로 팔 명령이 아니다. 제공된 예시 화면에는 `Gemini 3.5 Flash`라고 쓰여 있어 그 출력의 축 순서·정규화 범위·원본 이미지 크기는 원래 요청과 함께 확인해야 한다. Google의 **Gemini Robotics ER 2 공간 추론 예제**는 프롬프트로 `[y, x]`와 0–1000 정규화를 지정한다. 이 예제를 채택하더라도 응답은 이미지 위의 위치 후보일 뿐 높이, 물체 자세, 파지점, 트레이의 비어 있는 배치 영역, 충돌 없는 경로를 제공하지 않는다. [공식 공간 추론 가이드](https://ai.google.dev/gemini-api/docs/robotics-spatial)

현재 SOURCE 기준선은 다음과 같다.

| 영역 | 존재하는 것 | 아직 없는 것 |
|---|---|---|
| Pinky | CORE의 `/api/v1/navigation/goal`, `/api/v1/teleop`, 단일 최종 `cmd_vel`, Fleet의 navigation task/attempt 결과 상관관계 | 이를 곧바로 OMX 집기 또는 범용 다장치 Mission으로 확장한 계약 |
| OMX 카메라 | `src/products/omx/adapter/omx_adapter/camera_contract.py`의 원본 Image/CameraInfo 시각·frame·보정 해시 검사와 최신 한 쌍의 로컬 수신 | 모델 관측과 원본 프레임을 동일시하는 영속 observation ID, 작업면 좌표 투영, 대상 재검출·추적·오차 검증 |
| OMX 팔 | `command_owner.py`의 disabled-by-default 단일 submitter 정책과 `ros_runtime.py`의 `FollowJointTrajectory` 클라이언트 | 수용된 실물 드라이버·그리퍼/충돌/정지 경로, 원격 Device Action API, Pick/Place 로컬 작업 실행기와 최종 결과 원장 |
| 사이트 | Fleet의 영속 Pinky navigation task와 `/api/fleet/do` 고정 동사 | ER 2 호출기, 실행권 없는 후보 수신·검토, OMX action/attempt 연결, 다장치 Mission/Step 실행기 |

`/api/fleet/do`의 `steps`는 기존 REST 호출을 순서대로 수행한다. 첫 단계의 물리 완료를 기다리고 다음 단계를 시작하는 Mission 엔진이 아니다([D-308](../adr/D-308-intent-and-device-action-interpretation-boundary.md)). `TaskKind`에도 Pick/Place는 없다. 현재 OMX 프로필 `src/products/omx/profile/config/omx.disabled.yaml`의 `enabled`는 `false`다.

## 2. 권한과 실행 위치

```text
사람/업무 시스템
  └─ 사이트 미들웨어(Fleet): 인증, 요청·Mission/Step 원장, 장치 선택, 결과 조정
       ├─ ER 2 어댑터: 읽기 전용 관측/작업 후보, 모델 세션 관리
       └─ OMX 장치 API [제안]: 유한한 Device Action 요청·조회·취소
            └─ OMX 로컬 미들웨어 [제안]: 카메라/보정/작업면/소유권/한계 검증,
                                     Pick/Place Local Transaction, 안전 래치
                 └─ ROS 2 Action/ros2_control: 검증된 관절·그리퍼 동작
                      └─ 드라이버/독립 정지 경로: 실제 actuator와 readback
```

- **ER 2:** 물체·목적지 후보와 작업 분해를 제안하고 진행 영상에 대한 보조 판정을 한다. 모델 좌표, confidence, `tool_call` 또는 문장 자체는 권한·충돌 검사·완료 증거가 아니다. 모델에 CORE/OMX 운영자 credential이나 ROS/DDS 접근을 주지 않는다.
- **Fleet:** 사람/업무 요청의 권한, 장치 capability와 버전, 작업의 목표·순서·중복·기한을 검증한다. `mission_id`와 `step_id`, 사이트의 불명 결과 원장을 소유한다. 원본 카메라 영상과 관절 trajectory를 중계하거나 최종 writer가 되지 않는다.
- **OMX 로컬 미들웨어:** 작업대 identity, 카메라 원본/보정, 대상·목적지, 관절·그리퍼 상태, 공간·시간 한계, 단일 명령 소유권을 확인한다. `action_id`/`attempt_id`의 수락·거부·취소·최종 결과를 소유한다. 안전 HOLD와 독립 정지 수단의 관계를 실물에서 검증한다.
- **ROS 제어 경로:** `FollowJointTrajectory`와 수용된 그리퍼 제어, 실제 드라이버 피드백을 수행한다. 현행 `ArmCommandOwner`는 ROS action 클라이언트를 중재하는 소스 후보이며 실물 제어기나 물리 정지의 증거가 아니다. Pinky의 최종 base `cmd_vel`은 계속 CORE가 소유한다.

### 대안 비교

| 방식 | 장점 | 판정 |
|---|---|---|
| 모델 좌표를 곧바로 관절 trajectory로 변환 | 짧은 데모 경로 | 프레임·높이·충돌·그리퍼·정지 의미가 누락돼 운영 경로로 채택하지 않는다. |
| Fleet에 공용 팔·차체 제어기를 둠 | 중앙에서 순서가 보임 | 장치별 최종 writer와 단절 시 로컬 정지를 침범하므로 채택하지 않는다. |
| 증거가 붙은 모델 후보 → 장치별 유한 Action → 로컬 ROS 제어 | 기존 D-273/D-298/D-308 경계와 일치 | 첫 고정 OMX 작업의 목표 경로로 제안한다. 범용 wire schema는 두 번째 장치의 실제 소비자를 확인한 뒤 결정한다. |

## 3. 입력과 출력 계약 후보

### 3.1 모델 관측: 실행권 없는 후보

모델 어댑터는 **모델에 보낸 정확한 원본 프레임**의 `observation_id`, 프레임 digest, capture timestamp, 카메라 identity, optical frame, 해상도, crop/resize/회전 이력, CameraInfo와 hand-eye/작업면 보정 revision, 모델 ID·revision·프롬프트 버전, 좌표 형식과 응답 원문 digest를 연결해 보존한다. 영상은 소유 작업대의 로컬 경계에 남기고 Fleet에는 필요한 파생 metadata와 결과만 전송한다. 모델이 metadata를 주장하게 하지 않고 어댑터가 실제 입력에서 생성한다.

점 형식은 `normalized_yx_1000` 또는 명시된 다른 버전 중 하나로 선언한다. `normalized_yx_1000`이면 `u = x / 1000 × 원본 너비`, `v = y / 1000 × 원본 높이`로 바꾸되, 모델 입력에 crop/letterbox/회전이 있었다면 역변환을 먼저 적용한다. 축 순서, 범위, crop transform, 원본 프레임 또는 보정이 없으면 **후보를 거부**한다. `(u, v)`는 ray/작업면 교차 또는 검증된 depth와 카메라→작업대 TF를 거쳐야 한다. 블록 높이·파지 방향·그리퍼 폭과 트레이의 비어 있는 footprint가 확인되지 않으면 작업 목표로 승격하지 않는다. 원본 수신 시각만 새롭고 촬영·보정이 오래된 프레임도 거부한다.

로컬 인식기는 같은 프레임 또는 새 프레임에서 후보를 재검출·추적해 `object_ref`와 `destination_ref`를 만든다. 레이블 문자열과 중심점만으로 객체 ID를 고정하지 않는다. 다른 블록이 겹치거나 이동했거나 가려지면 다시 관측한다. 모델이 제시한 트레이 중심은 놓을 빈 영역의 증거가 아니다.

### 3.2 장치 작업 API: 제안 스케치

아래는 **새 endpoint 확정 전의 wire 초안**이다. 실제 경로·필드·enum은 D-18에 따라 API Reference와 공유 schema를 같은 변경에서 결정한다. 외부 호출자는 관절 각도·`cmd_vel`·원시 영상 좌표를 제출하지 않는다.

```json
{
  "action_type": "PICK_PLACE",
  "workcell_id": "<workcell-id>",
  "source_object_ref": "<locally-verified-object-id>",
  "destination_ref": "<locally-verified-tray-id>",
  "observation_id": "<bound-frame-and-calibration-id>",
  "request_key": "<caller-idempotency-key>",
  "expires_at": "<bounded-UTC-time>"
}
```

첫 범위는 `PICK_PLACE` 하나로 묶는다. `PICK`과 `PLACE`를 독립 명령으로 열려면 두 요청 사이의 물체 보유 상태, 재시작 후 소유권, 안전한 적재/하역 복구 계약이 먼저 필요하다. 모델 연결 전에는 동일한 Device Action을 모델 없이 운영자 요청으로 실행해 ROS 및 장치 readback 경로를 검증한다.

서버는 인증된 principal, 허용 capability, 작업대·장치 identity, 모드, 현재 설정 세대와 evidence freshness를 자체 판정한다. 모델 반환값의 `actor`, `source`, confidence를 권한으로 받지 않는다. 유효한 요청의 **접수 응답**은 `action_id`와 현재 상태만 반환한다. 조회/이벤트는 동일 `attempt_id`의 시작, 단계, 최종 결과를 전한다. `request_key` 재사용은 동일 본문이면 같은 작업을 돌려주고 다른 본문이면 충돌로 거절한다. timeout 후 무조건 재발행하지 않고 기존 작업을 조회한다.

단계 기록은 `target_confirmed → approach → grasp → grip_verified → transfer → release → placement_verified`와 각각의 관측·driver 결과·시각을 연결한다. `grasp` 또는 `release` Action 성공만으로 물체 보유나 트레이 안착을 성공으로 판정하지 않는다. `source_object_ref`/`destination_ref`가 stale하거나 성공 판별이 불명확하면 해당 attempt를 `UNKNOWN` 또는 명시적 로컬 실패로 분류하고 자동 재집기를 금지한다. 기존 D-307처럼 권위 있는 최종 실패 이벤트가 있으면 결과를 보존하고 물리 정지 축은 따로 남긴다.

### 3.3 모델 tool 호출

모델에 공개하는 기능은 `inspect_scene`, `propose_pick_place`, `get_action_status`처럼 읽기/후보 중심으로 시작한다. 물리 작업을 요청하는 tool이 추가돼도 이는 위 Device Action 제출을 **별도 권한 정책을 거쳐** 요청하는 어댑터이지 ROS action이나 driver를 직접 호출하는 함수가 아니다. Google의 Live 경로는 `gemini-robotics-er-2-streaming-preview`에서 물리 tool을 blocking으로 선언하고 `tool_call`과 같은 ID의 `tool_response`를 반환한다([공식 가이드](https://ai.google.dev/gemini-api/docs/robotics-streaming)). 모델 세션이 끊겨도 Fleet/장치의 영속 ID와 결과가 남아야 하며, 세션 연결을 재개 허가로 사용하지 않는다. 장시간 동작의 tool 응답은 수락/최종 결과를 구분하고, 최종 결과가 불명확하면 성공으로 답하지 않는다.

## 4. 작업·정지 상태의 소유권

Fleet의 Mission/Step, OMX Action/attempt, 로컬 단계, ROS action goal, driver 상태를 각기 다른 ID·상태로 기록한다. `QUEUED`는 사이트 보관, `ACCEPTED`는 장치 수락, `RUNNING`은 장치 실행, terminal은 같은 attempt의 권위 있는 최종 이벤트다. `UNKNOWN`은 그 최종 결과를 확인하지 못한 경우다. 이는 상태 의미 후보이며 새 전역 enum을 이 문서에서 확정하지 않는다.

| 사건 | 사이트가 할 일 | OMX 로컬 owner가 할 일 | 완료 판정 |
|---|---|---|---|
| 새 작업·직접 조작 충돌 | 보류 또는 명시적 우선순위 규칙 적용, 기존 Mission을 조용히 완료 처리하지 않음 | 단일 active owner/lease와 모드 검사 | 수락·거절을 분리 |
| 취소 | 해당 `action_id`에 취소 요청 후 최종 결과 조회 | 현재 단계 중단 요청, 새 단계 차단, HOLD 필요 여부 판단 | 취소 ACK만으로 정지 또는 최종 취소 아님 |
| 안전 stop/E-stop | 일반 작업 큐·모델 turn 밖의 우선 경로, site 실패를 개별 보고 | 로컬 래치, 새 동작 거부, 장치별 안전 동작·독립 정지 경로 | 요청, 래치, ROS/driver 수락, 실제 관절/물체 정지를 분리 |
| 네트워크·모델·Fleet 소실 | 무조건 재시도·재개하지 않고 마지막 attempt 조회 또는 `UNKNOWN` 보존 | 로컬 감시·기한·센서 신선도로 HOLD/정지, 진행 중 물체 취급에 맞는 안전 동작 | 실제 readback 전 안전 완료 표시 금지 |
| 재기동·해제 | 이전 후보를 재송신하지 않고 새 승인·새 작업 요구 | 이전 owner 종료·포트 해제, fresh state/보정/적재 상태/정지 상태 확인 | 재연결 또는 E-stop release만으로 재출발 금지 |

그리퍼가 물체를 쥔 상태에서는 단순 토크 해제가 낙하를 일으킬 수 있다. 작업대의 독립 정지 수단, 하중 유지/낙하 방지, 정지 지연·거리/관절 이동량, fault 해제 조건은 실물 inventory와 측정에 따라 정한다. 소프트웨어 `HOLD`, ROS cancel response, 0 trajectory 또는 HTTP 200을 물리 정지의 대리값으로 쓰지 않는다. Pinky 주행의 Fleet 전체정지도 현재 HTTP 수신 수를 `stopped`로 세며, 감사 DB 장애 때 CORE 호출 전 503이 될 수 있으므로 사이트 정지 가용성은 별도 검증 대상이다.

## 5. 구현 순서와 검증 출구

| 단계 | 구현·계약 산출물 | 성공 증거 | 중단 조건 |
|---|---|---|---|
| A. 후보만 받기 | 로컬 model adapter의 버전된 관측 파서와 `observation_id`; 실행 API/credential 없음 | 축 교환, crop 누락, 범위 초과, 오래된 프레임, 중복 객체, 원본 불일치를 SOURCE/LOCAL에서 거부 | 출처·프레임을 재현할 수 없음 |
| B. 작업대 기하 | 카메라↔작업면/팔 보정과 object/tray reference, 독립 기준점 오차 평가 | 실제 프레임의 3×3 기준점·가림/이동 재관측, 유효 작업영역/파지·배치 footprint | 높이·오차·방향 불명 또는 보정 불일치 |
| C. 로컬 규칙 기반 Pick/Place | 작은 블록 한 종류, 단계별 Local Transaction과 그리퍼/관절 결과·증거 | ROS-SIM 단일 owner·실패 주입; 이후 별도 DEVICE 저속/무하중→실물 집기·정지 계측(D-273) | vendor driver·그리퍼·독립 정지·readback 불명 |
| D. 장치 Action API | 인증·기한·중복·조회·취소·최종 결과의 버전된 wire 계약 | D-18 API Reference/schema 동시 변경, timeout/재시작/late result/취소 반례와 설치 closure 검증 | 로컬 owner 없이 Fleet에 팔 명령만 추가 |
| E. Fleet Mission/ER 2 연결 | 실행권 없는 후보 승인과 `mission/step/action/attempt` 상관관계, tool 응답 | 모델 오류·세션 단절·중복 tool call·일부 성공·결과 불명 시험; SITE/FIELD는 따로 측정 | 모델 응답이나 Fleet ACK를 작업 완료로 승격 |

A의 파서는 실제 모델을 호출하지 않는 고정 fixture로 먼저 검증할 수 있다. B는 실제 카메라/보정 값이 없으면 설계·합성 단계에 멈춘다. C의 운영 capability는 D-273의 장치 게이트 전까지 disabled로 유지한다. A–E의 SOURCE/LOCAL 통과는 ROS-SIM·ARTIFACT·DEVICE·FIELD를 대신하지 않는다. 정확도·성공률·시간 상한은 측정 전 임의로 승인값을 만들지 않는다.

**첫 검증 시나리오:** 모델 후보 `red block`/`green tray`를 같은 원본 프레임에 결합한다. 파서는 명시된 좌표 형식만 받아 로컬 관측 후보를 만들고, 로컬 기하·대상 재검증이 없으면 `PICK_PLACE` 제출을 거절한다. 보정된 fixture에서는 블록 이동·트레이 가림·집기 후 물체 미보유·취소 뒤 관절 잔류 운동을 각각 주입해 단계 실패/결과 불명/정지 상태를 별도 기록한다. 실제 팔 명령은 C의 장치 게이트 전에는 송신하지 않는다.

**롤백:** 각 단계의 후보 파서·도구·API 호출을 비활성으로 돌리고 기존 `omx.enabled: false`와 Pinky CORE API 경로를 유지한다. 영속 action을 발행한 이후에는 기능 플래그 복귀만으로 진행 중 동작이 취소됐다고 간주하지 않고 로컬 owner 결과와 물리 readback을 확인한다.

**관련 결정:** [D-18](../adr/D-18-rosy-core.md), [D-55](../adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-273](../adr/D-273-omx-camera-stream-and-arm-control-order.md), [D-282](../adr/D-282-per-hardware-ros-ownership-and-control-boundaries.md) (Proposed), [D-298](../adr/D-298-mission-action-and-stop-evidence-terminology.md), [D-299](../adr/D-299-omx-lerobot-development-and-command-ownership.md) (Proposed), [D-305](../adr/D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-307](../adr/D-307-final-action-outcome-and-stop-readback-evidence.md), [D-308](../adr/D-308-intent-and-device-action-interpretation-boundary.md).
