## D-773 OMX 로봇팔과 AI를 더하기 위한 플랫폼 구조: 장치 Action 타입 하나, 배포 경로 하나, AI 출력 두 종류

**Status:** Proposed

이 ADR은 구조 방향과 단계 순서를 제안한다. 구현, 폴더 이동, 정책 승격, 배포, 실물 수용을 뜻하지 않는다.

## Context

2026-10-16 사용자 지시: 현재 구현과 구조를 평가하고, OMX 로봇팔과 AI까지 확장해 처리해야 하는 부분을
고려해 구조를 다시 잡는다. 무엇을 어떻게 더할지를 ADR로 남겨 팀과 공유한다.

Pinky 쪽 권한 경계는 이미 분명하다. CORE가 외부 API의 유일한 창구이고 `/cmd_vel`의 유일한 발행자다(D-1, D-2).
OMX와 AI는 각자 다른 시점에 다른 방식으로 붙어 왔다. 그 결과 같은 문제를 다른 모양으로 푸는 곳이 생겼다.

### 이번에 확인한 사실

공유 main `14f02983e` 기준 소스 조사다. 장치·현장 관측은 하지 않았다.

| 영역 | 관측 | 근거 |
|---|---|---|
| OMX 배치 | Pinky에 얹은 팔이 아니라 고정 작업대. 호스트 하나에 최대 두 대 | `middleware/devices/omx/profile/config/omx.disabled.yaml`, `deploy/robot/omx/README.md` |
| OMX 작업 사슬 | Cell 문서 → 컴파일 → admit(두 사람 승인) → `StepJobDispatcher` → `FleetCellTransferGrant` → Unix socket → `ActionRunner` → `PickPlaceRunner` → `ArmCommandOwner` → `FollowJointTrajectory` → receipt | `operations/fleet/fleet/server/cell/`, `middleware/devices/omx/adapter/omx_adapter/` |
| OMX 실물 | 하드웨어 profile 비어 있음. CELL_TRANSFER는 `simulation`에서만 열림. 실물 owner 진입점 없음 | `step_action_kinds.py`, `deploy/robot/omx/run_cell_owner.py` |
| Pinky와 OMX의 요청 수용 | Pinky는 CORE HTTP API(타입 없는 dict, 약 45개 메서드), OMX는 같은 호스트 Unix socket으로 `FleetCellTransferGrant`. Fleet 수준 Action 타입(`FleetActionGrant`·`DeviceActionReceipt`)과 Fleet 쪽 `DeviceActionTransport`는 이미 있고 OMX만 쓴다. `DeviceControlPort`는 최종 writer 앞 서보 포트이며 Pinky 구현 `PinkyTwistPort`가 있다 | `contracts/foundation/core_common/protocol/schemas.py`, `operations/fleet/fleet/server/local_action_transport.py`, `operations/fleet/fleet/swarm/transport.py`, `middleware/core/gateway/core/bridge/cmd_vel.py` |
| 팔 owner를 부르는 길 | legacy PICK_PLACE(닫힘), CELL_TRANSFER, Pilot jog, `OwnerPolicySession` 네 갈래. 각자 lease·seat 로직 | `missions/mission_dispatcher.py`, `step_dispatcher.py`, `pilot_sim_runtime.py`, `middleware/robot_execution/local/` |
| 학습 정책 | `OwnerPolicySession`은 시험에서만 조립됨. cell owner의 `allowed_owners`에 `learned_policy` 없음. lease 발급자 미정 | `middleware/devices/omx/agent/src/rosy_agent/omx_cell_owner.py`, `middleware/robot_execution/local/README.md` |
| 모델 배포 | 운영 경로는 Perception ONNX 하나. `deliver.py`가 SSH + sudo로 shadow에 넣고 `promote`로 active 교체. `profiles/`·release를 거치지 않음 | `learning/registry/perception/deliver.py` |
| 설치 프로파일 | `profiles/installations`에 PolicyArtifact·ModelProfile pin 없음 | `profiles/installations/*.yaml` |
| AI 출력 | Decision tool catalog는 읽기·후보 쓰기만. `POLICY_DISPATCH_ENABLED = False`. D-610 AI-first는 로봇별 opt-in으로 이동 답(RESUME·YIELD 등)을 보낼 수 있음 | `operations/decision/src/rosy/decision/model_tool_catalog.py`, `operations/fleet/fleet/server/ledger/task_service.py`, `operations/fleet/fleet/stuck/ai_first.py` |
| 층 역전 | `devices/omx/agent`가 `rosy.processes.palletizing`을 import. `integrations/robots/omx`가 adapter 구현 모듈을 직접 import. `omx_adapter.api` 포트 모듈 없음 | `omx_cell_documents.py`, `integrations/robots/omx/` |
| 소스 경로 주입 | Fleet은 manifest가 없는 `rosy.decision`·`rosy_situation`·discord 연동을 빌드 때 `_source_roots/`로 복사하고, 소스 실행 때 `sys.path`에 넣는다. 이미 `install_requires`에 있는 `rosy-execution`도 다시 넣는다 | `operations/fleet/fleet/_source_layout.py`, `operations/fleet/setup.py` |
| 비어 있는 자리 | `integrations/models/<provider>`, `integrations/policies/lerobot_*` 없음. Fleet capability는 승격 산출물이 아니라 고정 목록 | D-427 §1–3, D-429 §1 |

## Decision

새 최상위 폴더나 새 실행기를 만들지 않는다. OMX와 AI는 아래 다섯 규칙으로 기존 구조에 수렴시킨다.

### 1. 장치 Action은 Fleet의 Action 타입 하나로 다룬다

Fleet이 장치에 맡기는 일은 `core_common` Action 스키마(`FleetActionGrant`·`FleetCellTransferGrant` → `DeviceActionReceipt`)와
Fleet의 `DeviceActionTransport`로 표현한다. 새 장치 kind는 `step_action_kinds` 등록표에 더하고, Fleet 안의 식별 검사는 한 곳에 둔다.

- `DeviceControlPort`(D-442)는 이 층이 아니다. 최종 writer 바로 앞의 서보 포트로 그대로 두며, OMX 구현은 D-442의 안전 단계를 따른다.
- Pinky를 같은 receipt로 옮기는 일은 지금 하지 않는다. TRIP은 Fleet 폐루프이고 CORE receipt가 없으며, fence 방향이 OMX와 반대다.
  타입만 맞춰서는 이 차이가 사라지지 않는다. 세 번째 장치 kind나 D-55 이동 조작이 필요해질 때 다시 판단한다.
- 전송은 지금처럼 둔다. Pinky는 CORE HTTP, OMX는 같은 호스트 Unix socket이다(D-403).
- 단일 writer는 그대로다. Base `cmd_vel`은 CORE, 팔 관절은 `ArmCommandOwner`가 쓴다. 두 writer를 합치지 않는다.
- OMX 쪽에는 `omx_adapter.api` 포트 모듈을 두고, `integrations/robots/omx`는 그 모듈만 import한다(D-429 §4).

### 2. 학습 정책은 owner를 부르는 클라이언트다

ACT 같은 `learned_policy`는 별도 실행기가 아니다. owner를 부르는 여러 클라이언트 가운데 하나다.

- lease 발급자는 Fleet 하나다. `OwnerPolicySession`은 Fleet grant에서 나온 lease로만 조립한다.
- Pilot jog, Skill 단계, 학습 정책은 같은 seat·lease 규칙을 쓴다. 클라이언트마다 따로 만든 admission은 하나로 모은다.
- cell owner가 `learned_policy`를 허용하는 것은 D-770 G4 실물 비교 평가를 통과한 정책에 한한다.

### 3. 모델과 정책의 배포 경로는 하나다

Perception ONNX, OMX ACT 정책, Decision ModelProfile은 모두 같은 길로 장치나 AI PC에 들어간다.

```text
학습·독립 평가(모델 PC) → registry 승격 기록 → profiles/installations pin → release → 장치·AI PC 설치 → readback
```

- `deliver.py promote`의 SSH 직접 승격은 이 경로로 흡수한다. 흡수 뒤 SSH 경로는 개발 벤치와 사고 대응에만 남긴다.
- AI PC는 승인된 pin과 실제 적재 digest가 같을 때만 결과를 낸다(D-516, D-527).
- Fleet capability는 장기적으로 설치된 산출물의 readback에서 만든다(D-427 §3).

### 4. AI 출력은 사실과 후보 두 종류다

AI가 내는 것은 사실(정체·관측)과 후보(미션·복구 제안)뿐이다. 후보는 항상 Fleet admission을 거치고,
장치 owner가 실행 직전에 다시 검사한다.

- D-610 AI-first의 이동 답도 후보로 다룬다. Fleet admission 규칙표에 올라간 답만 로봇에 보낸다.
- AI PC에는 Fleet 원장, ROS, 장치 Action, 정지·재무장 권한을 주지 않는다(D-516).
- 공급자 adapter는 `integrations/models/<provider>`, LeRobot 정책 adapter는 `integrations/policies/lerobot`에 둔다.

### 5. 폴더는 늘리지 않고 빈 자리를 채운다

- 새로 만드는 것: `omx_adapter.api`, `integrations/models/<provider>`, `integrations/policies/lerobot`.
- 그대로 두는 것: `control`·`core_features`의 `_source_layout`과 Fleet의 `sys.path` 주입. 앞의 것은 설치 import 이름을 지키는 장치이며, 없애면 약 600개 파일과 로봇 설치 이름이 바뀐다. 뒤의 것은 현장 이미지와 AI PC가 소스 복사 + `PYTHONPATH`로 배포되므로 함께 바꿔야 하고, 얻는 것은 시험이 이미 지키는 10줄이다.
- 방향을 바로잡는 것: agent가 palletizing을 import하던 것을 `contracts/skill` 타입을 거치게 바꾼다.

### 6. 단계

한 단계는 한 브랜치로 착지한다. 각 단계의 끝난 기준은 아래 증거다.

| 단계 | 할 일 | 끝난 기준 | 선행 |
|---|---|---|---|
| A1 OMX 실물 owner | D-770 G0. 실측 하드웨어 profile, 독립 stop, owner 결선 | OMX DEVICE 게이트 BENCH 증거 | 없음 |
| A2 Action 경계 정리 | Fleet의 grant·receipt 식별 검사 3벌을 하나로 합치고 kind별 protocol 버전을 등록표로 옮긴다. `omx_adapter.api`로 integrations 경계를 정리한다 | 중복 1벌, 위반 edge 1개 감소, NEW 0 | 없음 |
| A3 배포 경로 통합 | installation profile에 PolicyArtifact·ModelProfile pin. release가 설치. SSH promote는 비상 경로로만 | 모델 교체가 release 기록으로만 일어남 | 없음 |
| A4 학습 정책 admission | Fleet lease로 `OwnerPolicySession` 조립, cell owner의 `learned_policy` 허용 | D-770 G4 실물 비교 평가 | A1, A2, A3 |
| A5 AI 현장 그림자 | 모델 PC L0를 통과한 ModelProfile만 AI PC에 적재. Fleet은 그림자로만 기록 | 그림자 정답 대조 기록(D-492·D-527 관문) | A3 |

이동 조작(Pinky + OMX 합성 Asset)은 D-55·D-71대로 A4 뒤의 별도 결정으로 둔다.

## Alternatives

| 접근 | 판단 |
|---|---|
| OMX를 CORE 안으로 넣어 장치 게이트웨이 하나로 통합 | CORE는 Pinky 한 프로세스(D-1)이고 OMX는 다른 호스트·제어기다. 단일 writer 경계를 흐리므로 선택하지 않음 |
| AI 전용 실행기(정책 런타임)를 새 최상위로 추가 | 실행 권한이 둘로 갈라진다. 아키텍처 v0.2 §7.1 "AI는 다른 진입점일 뿐 다른 실행기가 아니다"와 충돌 |
| 현재 구조를 그대로 두고 장치별로 계속 붙이기 | 단기 비용은 가장 작다. 다만 Fleet의 장치별 분기와 배포 우회가 장치·모델마다 늘어난다 |
| 포트 하나 + 배포 경로 하나 + AI 출력 두 종류 | 권장. 기존 권한 경계를 유지하면서 OMX·AI 추가 비용을 한 번만 치른다 |

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-1, D-2 | CORE 단일 프로세스·단일 `cmd_vel` 발행자 유지 |
| D-55, D-71 | 이동 조작·합성 Asset은 계속 연기 |
| D-403 | Fleet–OMX owner 같은 호스트 연결 유지. 이 ADR은 타입만 맞춘다 |
| D-427 | 세 부분(middleware·operations·learning)과 profile·release 전달 경계 유지. §2의 배포 경로를 Perception에도 적용 |
| D-429 | `integrations`는 `api` 모듈만 import. `omx_adapter.api`를 A2에서 둔다 |
| D-442 | `DeviceControlPort`는 최종 writer 앞 서보 포트로 유지한다. Fleet Action과 섞지 않는다 |
| D-516, D-527 | 모델 PC 평가, AI PC 추론만, Fleet 판정, 장치 재검사 유지 |
| D-492, D-610 | VLM·AI-first 출력을 후보로 다루고 Fleet admission 규칙표를 거치게 한다. D-610의 지위는 바꾸지 않는다 |
| D-770 | OMX 자동 시연·모방학습의 완료 기준. 이 ADR의 A1·A4가 그 G0·G4에 묶인다 |

## Consequences

- Fleet은 장치 kind가 늘어도 Action 등록표와 `DeviceActionTransport`로 다룬다. Pinky의 TRIP 폐루프는 별도로 남는다.
- 모델 교체는 release 기록으로 추적된다. 대신 지금의 빠른 SSH 승격보다 한 단계가 늘어난다. 개발 벤치에서는 비상 경로를 쓴다.
- 학습 정책은 Fleet lease 없이 팔을 움직일 수 없다. A4 전에는 학습 정책을 실물에서 돌리지 않는다.
- A0는 동작 변화가 없는 정리라 먼저 착지할 수 있다. A1~A5는 각 단계의 증거가 나올 때까지 Proposed로 남는다.
- 이 ADR은 main 착지 뒤 공유용이며, 단계별 구현은 각자의 ADR·검증 기록을 따른다.

### 2026-10-16 정정: A0 범위

처음 판의 A0에는 아래 항목이 있었다. 소스를 다시 확인해 모두 뺐다.

| 처음 판의 항목 | 확인한 사실 |
|---|---|
| legacy `safety_node` 설치 제외 | 죽은 코드가 아니다. `motion_limits` adapter가 sensor-only 모드에서 같은 노드 이름으로 돌고, CORE `control_sensor_adapter.py`가 그 파라미터를 읽는다. launch 3개가 쓴다 |
| systemd `deploy/robot/native` 경로 불일치 | 불일치가 아니다. `build-native-payload.sh`가 `deploy/robot/pinky_pro/native`를 release의 `deploy/robot/native`로 설치한다 |
| `KNOWN_VIOLATIONS` 옛 경로 갱신 | 키는 경로가 아니라 manifest 소유권 식별자(`d427_target`)다 |
| 빈 유령 폴더 제거 | git이 추적하지 않는 로컬 디스크 잔재다. 저장소 정리 대상이 아니다 |
| `processes/cell` facade 제거 | 32줄 호환 facade이고 `test_platform_palletizing_compat.py`가 지킨다. ROS 패키지 `rosy_cell` 제거와 소비자 10여 곳 수정에 비해 얻는 것이 작아 보류한다 |

`control`·`core_features`의 `_source_layout` 제거도 검토했다. import 이름을 폴더에 맞추면 약 600개 파일(시험 약 400개)과
로봇 설치 이름이 바뀌고, 폴더를 되돌리면 D-743~D-752의 재배치를 뒤집는다. 그래서 그대로 둔다.

Fleet의 `sys.path` 주입(`rosy.decision`·`rosy_situation`·discord)을 wheel 의존성으로 바꾸는 안도 검토했다.
현장 이미지(`deploy/site/Dockerfile.fleet`)와 AI PC 설치 스크립트가 소스 복사 + `PYTHONPATH`로 배포하고,
Fleet은 `rosy_situation`의 순수 판정 모듈 3개만 쓴다. CI·이미지·AI PC 설치·크기 단위·구조 시험을 함께 바꿔야 하는 데 비해
얻는 것이 작아 A0 단계를 없앴다. 다음 단계는 A2다.

## References

- [ROSY Platform 통합 아키텍처 설계 v0.2 §7](../reference/ROSY_Platform_Architecture_Design_v0.2.md)
- [Decision 모델 파이프라인과 실행 구조](../plans/2026-10-08-decision-model-pipeline-design.md)
- [현재 폴더 책임](../reference/platform-folder-responsibilities.md)
- [09 Composite Robot](../architecture/09_ROSY_Composite_Robot.md), [11 AI and Physical AI](../architecture/11_ROSY_AI_and_Physical_AI.md)
- [D-770 OMX 자동 시연 수집과 모방학습](D-770-fleet-omx-autonomous-imitation-pipeline.md)

### 2026-10-16 정정: 장치 권한 포트의 층

처음 판의 결정 1은 `DeviceControlPort`를 Fleet grant·receipt의 정본으로 적었다. 확인 결과 이 Protocol은 서보 kind
(`BaseTwist`·`ArmJointTrajectory`·`ArmGripper`)만 받는 50 Hz 최종 writer 앞 포트이며(D-442), Pinky 구현 `PinkyTwistPort`가
이미 있다. Fleet 수준의 공통 타입은 `core_common`의 Action 스키마와 Fleet의 `DeviceActionTransport`다. 결정 1과 A2를 그에 맞게 고쳤다.
Fleet이 장치 kind로 갈라지는 곳은 약 7곳이며 단계 원장은 이미 등록표로 움직인다. 완전한 Pinky·OMX 공통 receipt는 CORE 공개 API
변경이나 Fleet 쪽 가짜 receipt가 필요해 미룬다.
