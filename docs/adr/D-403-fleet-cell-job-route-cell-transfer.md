## D-403 Rosy Cell Job은 Fleet 제안으로 들어가 Step마다 `CELL_TRANSFER` Action 하나로 하달된다

**Status:** Proposed (2026-10-01, 경로·계약 결정). Mission 하달기는 `simulation` 프로필에서만, 그것도 정지 세대 producer/consumer 시험을 통과한 뒤에만 연다. 실물 OMX, 호스트 간 하달, DEVICE/FIELD 수용은 포함하지 않는다. wire 이름과 필드는 D-18에 따라 C4 구현 변경에서 API Reference·공유 schema·생산자/소비자 시험과 함께 확정한다.

## 배경

- **D-401(Proposed) §4.** Rosy Cell Job은 Fleet 승인(D-330)을 거쳐 Step이 장치로 하달되는 경로로만 실행된다. 이 경로를 막고 있는 보류가 둘 있다.
  - D-330(Accepted) §2: 정지 세대 생산자/소비자 시험 전에는 Mission dispatch를 열지 않는다.
  - D-336(Accepted) §5: 호스트 간 하달을 닫아 둔다.
- **코드 현황(main `dcad279d`).**
  - `FleetActionGrant.action_kind`는 `^PICK_PLACE$`만 받는다. 같은 관측에서 나온 `source_evidence`/`destination_evidence`(RGB-D)를 필수로 요구한다.
  - `fleet_missions` 표는 `CHECK(action_kind='PICK_PLACE')`이고, Mission마다 Step이 하나다(`{mission_id}:step-1`). 제안 resolver(`mission_routes._resolve_candidate`)도 RGB-D 증거를 요구한다.
  - `MissionDispatcher`는 제출 직전에 `dispatch_control()`의 `dispatch_enabled`, `authority_epoch`, `generation`을 다시 확인한다.
  - `create_app(enable_mission_dispatcher=False)`가 기본이다.
  - OMX 쪽 `ActionRunner._validate`는 digest, 만료, workcell, `current_fence`, `capability_current(grant)`를 검사한다.
- **D-327(Proposed).** §1은 grasp 자세나 관절 값을 의미적 조작 명령의 필수 입력으로 두지 않는다. §5는 보유 상태 계약 전까지 첫 OMX 작업대에서 단독 `PICK`/`PLACE`를 열지 않고 복합 `PICK_PLACE`만 둔다.
- **사용자 결정(2026-10-01).** 정식 Fleet 경로를 쓴다. D-330 §2는 `simulation`에서만, ROS-SIM 정지 세대 시험을 조건으로 연다. D-336의 같은 호스트 UDS는 유지한다.

## 결정

1. **새 Action 종류는 `CELL_TRANSFER`다.**
   - Action 하나는 물건 하나(`box` 또는 `slip_sheet`)의 pick+place 한 쌍이다. 복합 단위로 묶는 이유는 D-327 §5다.
   - "CELL"은 해시로 검증된 Rosy Cell 셀에 묶인다는 뜻이다. 셀 해시가 필수다. `POSE_PICK_PLACE` 같은 일반 이름은 아무 제안자나 임의 포즈를 보낼 수 있다고 읽히므로 쓰지 않는다.
   - "TRANSFER"는 인식이나 의미적 대상 해석 없이 티칭 좌표로 옮긴다는 뜻이다. 그래서 D-327의 의미적 `PICK_PLACE` 어휘 밖에 둔다. D-327은 바꾸지 않는다.
2. **grant 내용.**
   - 공통 envelope는 `PICK_PLACE`와 같다: mission/step/action/attempt id, `request_digest`, workcell/instance, capability/config revision, `authority_epoch`, `dispatch_generation`, `issued_at`/`expires_at`.
   - 본문 `cell_transfer`에 싣는 것:
     - `job_id`, `recipe_sha256`, `cell_sha256`
     - `step_index`: Job 안 pick Step의 위치
     - `item`(`box`|`slip_sheet`), `pallet`, `layer`
     - `frame: robot_base`
     - pick `{x, y, z, yaw}`와 `pick_approach_z`
     - place `{x, y, z, yaw}`와 `place_approach_z`
   - RGB-D 증거는 없다. schema는 `action_kind`로 구분하는 합집합이다. `PICK_PLACE` 모델의 필드는 그대로 두어 기존 digest가 바뀌지 않게 한다. `observation_revision`은 `PICK_PLACE`에만 있다.
3. **Rosy Cell은 Job을 제안 후보로 제출한다.**
   - Rosy Cell 서버가 운영자 principal로 `POST /api/fleet/proposals`를 호출한다.
   - 후보 `kind: "cell_job"`에는 정규화한 `recipe`와 `cell` 문서, 두 해시, 컴파일된 Job을 담는다.
   - Fleet resolver는 같은 순수 라이브러리 `rosy_cell`로 Job을 다시 컴파일한다. 결과가 후보와 다르면 `CELL_JOB_MISMATCH`로 거절한다. Fleet이 실제로 읽는 순서는 자기가 계산한 순서다(D-12). Fleet이 `rosy_cell`을 쓰는 것은 선언된 패키지 간 의존으로 추가한다.
   - 다음 경우도 거절한다: 해석 결과가 64 KiB를 넘음, 해시 불일치, pick 다음에 같은 item의 place가 오지 않음.
4. **Fleet은 Job을 Step으로 푼다.**
   - pick+place 쌍마다 `CELL_TRANSFER` Step 하나를 만든다. `pallet_done`은 장치 Action 없는 Fleet 원장 표지다.
   - Cell Job 하나가 D-328의 Mission 하나이고, 그 안에 순서 있는 Step이 있다.
   - 현재 표는 Mission마다 Step 하나이고 SQLite의 CHECK 제약은 바꿀 수 없다. 그래서 C4가 순서 있는 Step 표를 새로 만들어 이관한다. 기존 `PICK_PLACE` 단일 Step 경로는 그대로 보존한다.
   - claim은 `("workcell", id)`와 각 팔레트 id를 Job 전체 기간 동안 잡는다.
5. **승인과 하달.**
   - 이름 있는 운영자가 Job을 한 번 승인한다. 기존 `admit` 경로와 같은 세대 검사를 쓴다.
   - 하달기는 Step k를 다음 조건이 모두 맞을 때만 제출한다.
     - Step k−1이 `GOAL_CONFIRMED`다.
     - `dispatch_enabled`가 켜져 있다.
     - `authority_epoch`와 `generation`이 승인 때와 같다.
   - 작업대마다 동시에 진행 중인 Action은 하나다.
   - 시뮬레이션에서 목표 증거는 owner의 phase 결과와 다른 출처여야 한다. 기존 goal-evidence 생산자 경로가 Gazebo 모델 포즈 readback으로 place 포즈 허용오차 안인지 보고한다. 증거가 없으면 Job은 `ACTION_SUCCEEDED`에서 HOLD한다. 장치 결과만으로 다음 Step에 가지 않는다(D-328 §4).
6. **정지 세대.**
   - 생산자는 Fleet이다. 인증된 사이트 정지가 세대를 올리고 래치하며(D-330 §2), `StopLocal`(`authority_epoch`, `dispatch_generation` 포함)을 owner에 전달한다.
   - 소비자는 owner다. `LocalStopController`가 래치를 영속화한다. `current_fence`와 `StopFence.run_if_open`은 Action 제출 때와 각 phase 제출 직전에 grant 세대를 다시 확인한다.
   - 진행 중인 phase는 정확한 ROS UUID로 취소한다(D-376 §6). 늦게 온 수락은 그 UUID를 취소하고 HOLD한다(D-386 §2).
   - 정지 뒤 Job 커서는 HOLD다. 남은 Step을 다시 하려면 물건 상태를 대조한 뒤(D-328 §5) 새 세대에서 운영자가 다시 승인해야 한다. Fleet이나 owner가 재시작해도 자동으로 다시 하달하지 않는다.
7. **D-330 §2를 여는 조건(`simulation`에서만).**
   - `create_app`는 배포 프로필 인자를 받는다. 하달기는 다음 두 조건이 모두 맞을 때만 켤 수 있다.
     - 프로필이 `simulation`이고, 대상 OMX 인스턴스가 시뮬레이션 identity(D-390 §5)다.
     - 고정 이미지와 커밋에서 아래 ROS-SIM 시험 묶음이 통과했다.
   - 시험 묶음:
     - (a) Step 사이 정지: 다음 Step이 제출되지 않는다.
     - (b) phase 도중 정지: 래치, UUID 취소, 다음 phase 없음을 확인한다.
     - (c) 정지 뒤 늦은 수락: 취소 후 HOLD한다.
     - (d) rearm 뒤 옛 세대 grant: owner가 거절한다.
     - (e) Job 도중 Fleet 재시작: 자동 재하달이 없다.
     - (f) owner 재시작: UNKNOWN/HOLD다.
     - (g) 감사 DB 쓰기 불능: 정지 fanout은 계속 나간다(D-330 §3).
   - 그 밖의 프로필(`device`, `field`, 미지정)에서는 `enable_mission_dispatcher=True`를 거절한다. D-330 §2 보류가 그대로 남는다.
8. **D-336 유지.** 같은 Linux 호스트의 UDS(`/run/rosy/omx/<instance_id>/control.sock`)와 `SO_PEERCRED` UID allowlist를 그대로 쓴다. WSL Ubuntu 한 커널 안에서 Fleet과 owner를 실행한다. owner가 컨테이너 안에 있으면 socket을 bind-mount한다. 이때 owner 쪽에서 관측한 peer UID가 allowlist를 통과하는지 시험으로 확인한다. 호스트 간 하달은 계속 HOLD다(D-336 §5).
9. **셀 해시 검사는 owner에 있다.**
   - 위치는 OMX owner `ActionRunner._validate`의 `capability_current(grant)` hook이다. journal 행을 만들기 전에 검사한다.
   - grant의 `cell_sha256`을 owner가 수락한 셀 해시(D-404 §6)와 비교한다. 다르면 `GRANT_REJECTED`(403)를 내고 journal을 만들지 않는다. Fleet은 이를 `LOCAL_ACTION_REJECTED`로 기록하고 Job을 HOLD한다.
   - 계획기도 계획 직전에 같은 비교를 한 번 더 한다.
10. **티칭 seat와 섞지 않는다.** D-404 seat가 잡혀 있는 동안 owner는 `CELL_TRANSFER`를 거절한다. `CELL_TRANSFER`가 끝나지 않은 동안에는 seat 획득을 거절한다(D-330 §1의 혼합 HOLD).

## 검토한 대안

| 대안 | 판단 |
|---|---|
| Step마다 별도 `PICK`, `PLACE` Action | 보유 상태 계약 전에는 단독 `PICK`/`PLACE`를 열지 않는다(D-327 §5). 채택하지 않는다. |
| 기존 `PICK_PLACE`에 포즈 필드를 선택적으로 추가 | 같은 종류에 출처가 다른 두 계약이 섞이고 기존 digest가 흔들린다. 채택하지 않는다. |
| Fleet이 Rosy Cell의 Job을 검사 없이 신뢰 | Step 순서의 정본이 Application으로 넘어간다(D-12). 채택하지 않는다. |
| Rosy Cell이 UDS로 장치에 직접 제출 | D-399 §5, D-401 §4와 어긋난다. 채택하지 않는다. |
| 모든 프로필에서 하달기를 연다 | D-330 §2 조건을 실물에서 증명하지 않았다. 채택하지 않는다. |

## 결과

- Rosy Cell Job은 Fleet 원장, 승인, 정지 세대 아래에서 한 번에 Action 하나씩 실행된다.
- D-330 §2의 Mission dispatch 보류는 `simulation`에서만 시험 조건부로 풀린다. 실물 경로는 계속 닫혀 있다.

## 수용 기준과 증거 경계

- **SOURCE:**
  - 합집합 grant schema와 기존 `PICK_PLACE` digest 불변
  - resolver 재컴파일 불일치 거절
  - Step 순서·`pallet_done`·claim
  - 셀 해시 거절
  - seat 상호 배제
  - 프로필 gate(비시뮬에서 하달기 거절)
- **ROS-SIM:** §7 시험 묶음, 그리고 C6 종단 실행(2층, 슬립시트, 팔레트 2개).
- **DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-327](D-327-semantic-manipulation-actions-and-device-adapters.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-401](D-401-rosy-cell-application.md), [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-404](D-404-omx-setup-teaching-api-simulation-first.md)
