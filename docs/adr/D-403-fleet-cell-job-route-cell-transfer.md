## D-403 Rosy Cell Job은 Fleet 제안으로 들어가 Step마다 `CELL_TRANSFER` Action 하나로 하달된다

**Status:** Accepted (2026-10-02, 사용자 승인; 시뮬레이션 범위. C3/C3b Gazebo 증거 `docs/validation/rosy-cell-gazebo-c3-2026-10-02/`. 실물 OMX·DEVICE·FIELD는 계속 닫혀 있다. 이전 기록: Proposed (2026-10-01, 경로·계약 결정; 시뮬레이션 한정 D-330 §2 개방은 사용자 승인 2026-10-01). Mission 하달기는 `simulation` 프로필에서만, 정지 세대 producer/consumer 시험을 통과한 뒤에만 연다. 실물 OMX, 호스트 간 하달, DEVICE/FIELD 수용은 포함하지 않는다. wire 이름·필드는 D-18에 따라 C4에서 API Reference·공유 schema·생산자/소비자 시험과 함께 확정한다.

## 배경

- **D-401(Proposed) §4.** Job은 Fleet 승인(D-330)을 거쳐 장치로 하달되는 경로로만 실행된다. 이 경로를 막는 보류가 둘이다.
  - D-330(Accepted) §2: 정지 세대 시험 전 Mission dispatch를 열지 않는다.
  - D-336(Accepted) §5: 호스트 간 하달을 닫는다.
- **코드 현황(main `dcad279d`).**
  - **grant:** `FleetActionGrant.action_kind`는 `^PICK_PLACE$`만 받고 RGB-D 증거 두 개를 필수로 요구한다.
  - **Mission 표:** `fleet_missions`는 `CHECK(action_kind='PICK_PLACE')`이고 Mission마다 Step 하나다.
  - **제안 경로:** resolver는 RGB-D 증거를 요구한다. `/admit`(`mission_routes.py` 366행)은 호출자 자신의 principal로 만든 제안만 읽는다.
  - **목표 증거:** `goal_evidence.py`의 `GoalPredicate`는 `object_in_destination`와 `camera_observation`만 받는다.
  - **하달기:** `MissionDispatcher`는 제출 직전에 `dispatch_control()`을 다시 확인한다. `create_app(enable_mission_dispatcher=False)`가 기본이다.
  - **OMX 쪽:** `ActionRunner._validate`는 digest, 만료, workcell, `current_fence`, `capability_current(grant)`를 검사한다.
- **D-327(Proposed).** §1은 grasp 자세를 의미적 명령의 필수 입력으로 두지 않는다. §5는 보유 상태 계약 전까지 단독 `PICK`/`PLACE`를 열지 않는다.
- **사용자 결정(2026-10-01).** 정식 Fleet 경로를 쓴다. D-330 §2는 `simulation`에서만 연다. D-336의 같은 호스트 UDS는 유지한다.

## 결정

1. **Action 종류는 `CELL_TRANSFER`다.**
   - Action 하나는 물건 하나(`box`|`slip_sheet`)의 pick+place 한 쌍이다. 복합 단위로 묶는 이유는 D-327 §5다.
   - "CELL"은 이 Action이 Rosy Cell의 셀·레시피 해시를 반드시 싣고, owner가 수락한 셀 해시 문자열과 일치해야만 받아들여진다는 뜻이다. 다만 owner의 검사는 문자열 비교뿐이다. 포즈가 그 셀에서 나왔다는 결속은 Fleet의 재컴파일(§3)이 보장한다.
   - "TRANSFER"는 인식 없이 티칭 좌표로 옮긴다는 뜻이다. 그래서 D-327의 의미적 어휘 밖에 둔다.
2. **grant 내용.**
   - 공통 envelope는 `PICK_PLACE`와 같다: mission/step/action/attempt id, `request_digest`, workcell/instance, capability/config revision, `authority_epoch`, `dispatch_generation`, `issued_at`/`expires_at`.
   - 본문 `cell_transfer`에 싣는 것:
     - `job_id`, `recipe_sha256`, `cell_sha256`, `step_index`
     - `item`, `pallet`, `layer`, `frame: robot_base`
     - `home`, `pick`, `place`: 각각 `{x, y, z, yaw}`
     - `pick_approach_z`, `place_approach_z`
     - `carry_z`(D-402 §6). Fleet은 재컴파일할 때 `rosy_cell.compiler.carry_z(recipe, cell)`을 호출해 이 값을 얻고, 계산을 다시 구현하지 않는다. 여유는 `cell.yaml`의 `approach_clearance_m`이다.
   - schema는 `action_kind`로 구분하는 합집합이다. `PICK_PLACE` 모델은 그대로 두어 기존 digest가 바뀌지 않는다.
3. **제안·승인 주체.**
   - Rosy Cell은 자기 **사이트 서비스 principal**로 `POST /api/fleet/proposals`를 호출해 제안한다. 이 principal은 제안과 해석(resolve)만 할 수 있다. Rosy Cell은 운영자 자격 증명을 갖지 않는다.
   - 후보 `kind: "cell_job"`에는 정규화한 `recipe`·`cell` 문서, 두 해시, 컴파일된 Job을 담는다.
   - Fleet resolver는 `rosy_cell`로 Job을 다시 컴파일한다. 후보와 다르면 `CELL_JOB_MISMATCH`로 거절한다. Fleet이 쓰는 순서는 자기가 계산한 순서다(D-12). 다음 경우도 거절한다: 64 KiB 초과, 해시 불일치, pick·place가 짝을 이루지 않음.
   - **승인은 이름 있는 사람 운영자가 한다.** 필요한 코드 변경:
     - `mission_routes.py`의 `/admit`(366행 부근)이 허용 목록에 있는 다른 principal이 만든 제안도 읽게 한다. 이때 승인자는 제안자와 달라야 한다.
     - 제안·해석 경로의 role 검사에 서비스 principal을 추가한다.
4. **Step으로 푼다.**
   - pick+place 쌍마다 `CELL_TRANSFER` Step 하나를 만든다. `pallet_done`은 Fleet 원장 표지다.
   - Cell Job 하나가 D-328의 Mission 하나다.
   - SQLite CHECK 제약은 바꿀 수 없으므로 C4가 순서 있는 Step 표를 새로 만들어 이관한다. 기존 `PICK_PLACE` 단일 Step 경로는 보존한다.
   - claim은 workcell과 팔레트를 Job 전체 기간 동안 잡는다.
5. **하달과 목표 증거.**
   - Step k는 다음이 모두 맞을 때만 제출한다.
     - Step k−1이 `GOAL_CONFIRMED`다.
     - `dispatch_enabled`가 켜져 있다.
     - `authority_epoch`와 `generation`이 승인 때와 같다.
   - 작업대마다 진행 중인 Action은 하나다.
   - **목표 증거에는 새 출처가 필요하다.**
     - `sim_model_pose`: 시뮬레이션 쪽 생산자가 자기 goal-evidence token으로 Gazebo 모델 포즈를 보고한다.
     - 여기에 `gripper_contract`의 해제 readback을 더한다.
   - **Step별 predicate**는 `condition: item_at_pose`다. 담는 값: `item_id`(job:step), 목표 포즈, xy·z·yaw 허용오차, `evidence_source: sim_model_pose`.
   - 필요한 코드 변경:
     - `goal_evidence.py` `GoalPredicate.from_mapping`이 위 조건과 출처를 받게 한다(지금은 `camera_observation`만 받는다).
     - `goal_evidence_registry.py`의 `_EVIDENCE_SOURCES`에 출처를 추가한다.
     - Mission predicate를 Step 단위로 저장한다.
   - `sim_model_pose`는 `simulation` 프로필에서만 받는다. 증거가 없으면 `ACTION_SUCCEEDED`에서 HOLD한다(D-328 §4).
6. **정지 세대.**
   - **생산자:** Fleet 사이트 정지가 세대를 올려 래치하고(D-330 §2), `StopLocal`(epoch·generation 포함)을 owner에 전달한다.
   - **소비자:** owner `LocalStopController`가 래치를 영속화한다. `current_fence`와 `StopFence.run_if_open`은 Action 제출 때와 각 phase 제출 직전에 세대를 확인한다.
   - 진행 중 phase는 정확한 UUID로 취소한다(D-376 §6). 늦게 온 수락은 취소하고 HOLD한다(D-386 §2).
   - 정지 뒤 Job은 HOLD다. 물건 상태를 대조한 뒤(D-328 §5) 새 세대에서 운영자가 다시 승인해야 한다. 재시작 뒤 자동 재하달은 없다.
7. **D-330 §2 개방 조건(`simulation`에서만).**
   - `create_app`는 배포 프로필을 인자로 받는다. 하달기는 다음 두 조건이 모두 맞을 때만 켤 수 있다.
     - 프로필이 `simulation`이고, 대상 인스턴스가 시뮬레이션 identity(D-390 §5)다.
     - 고정 이미지·커밋에서 아래 ROS-SIM 시험이 통과했다.
   - 시험:
     - (a) Step 사이 정지
     - (b) phase 도중 정지: 래치, UUID 취소, 다음 phase 없음
     - (c) 정지 뒤 늦은 수락
     - (d) rearm 뒤 옛 세대 grant 거절
     - (e) Job 도중 Fleet 재시작: 자동 재하달 없음
     - (f) owner 재시작: UNKNOWN/HOLD
     - (g) 감사 DB 쓰기 불능 중에도 정지 fanout(D-330 §3)
     - (h) Fleet↔owner UDS 통신 상실: Fleet은 UNKNOWN으로 두고, 세대를 다시 조회하고, 재하달하지 않는다.
     - (i) 정지 뒤 물체 보유 불명: 자동 놓기·재파지 없이 HOLD하고 운영자가 대조한다(D-330 Transition 2).
   - 그 밖의 프로필에서는 `enable_mission_dispatcher=True`를 거절한다.
8. **owner는 작업대마다 프로세스 하나다(시뮬레이션).**
   - 한 프로세스의 `ArmCommandOwner` 하나가 D-390/D-404 HTTP API와 D-336 UDS socket을 함께 서비스한다. `allowed_owners`는 `("pilot_sim", "rule_based")`다.
   - 이 공유 상태에 다음이 있다: seat↔Action 상호 배제(§10), 셀 수락(D-404 §6), 정지 래치.
   - 두 런타임이 `/arm_controller`에 쓰는 것은 금지다(D-390 §3, D-282 §3).
   - **D-336과의 시뮬레이션 한정 차이:** D-336 §1·§3은 native systemd 서비스 인스턴스를 전제한다. 시뮬레이션에서는 owner를 `rosy-omx-workstation` 컨테이너에서 실행하고, socket을 bind-mount로 노출한다. 같은 Linux 커널(WSL Ubuntu) 조건, `SO_PEERCRED` UID allowlist(owner 쪽에서 관측한 UID로 시험), 64 KiB framing은 그대로다. 호스트 간 하달은 계속 HOLD다(D-336 §5).
9. **셀 해시 검사 위치.**
   - 첫 번째 검사: OMX owner `ActionRunner._validate`의 `capability_current(grant)` hook. journal을 만들기 전에 수락한 셀 해시와 문자열을 비교한다. 다르면 `GRANT_REJECTED`(403)를 내고, Fleet은 `LOCAL_ACTION_REJECTED`로 기록하고 Job을 HOLD한다.
   - 두 번째 검사: 계획기가 계획 직전에 같은 비교를 한다(D-402 §7).
   - 실행은 phase runner로만 한다. 직접 `driver.submit` 경로는 모르는 종류를 거절한다(D-402 §3).
10. **티칭 seat와 섞지 않는다.** seat가 잡혀 있으면 `CELL_TRANSFER`를 거절한다. `CELL_TRANSFER`가 끝나지 않았으면 seat 획득을 거절한다(D-330 §1).

## 검토한 대안

| 대안 | 판단 |
|---|---|
| Step마다 단독 `PICK`, `PLACE` | D-327 §5와 어긋난다. 채택하지 않는다. |
| `PICK_PLACE`에 선택적 포즈 필드 추가 | 한 종류에 출처가 다른 계약이 섞이고 digest가 흔들린다. 채택하지 않는다. |
| Fleet이 Job을 검사 없이 신뢰 | 순서의 정본이 Application으로 넘어간다(D-12). 채택하지 않는다. |
| Rosy Cell이 운영자 자격으로 제안·승인 | 사람 승인 단계가 사라진다. 채택하지 않는다. |
| 모든 프로필에서 하달기 개방 | 실물 증거가 없다. 채택하지 않는다. |

## 결과

- Rosy Cell Job은 Fleet 원장·사람 승인·정지 세대 아래에서 Action 하나씩 실행된다.
- D-330 §2 보류는 `simulation`에서만 시험 조건부로 풀린다. D-330 머리에 이 부분 개정을 적는다.

## 수용 기준과 증거 경계

- **SOURCE:**
  - 합집합 schema와 `PICK_PLACE` digest 불변
  - 재컴파일 불일치 거절
  - 서비스 principal 제안 + 다른 운영자 승인(같은 principal 승인 거절)
  - `item_at_pose` predicate
  - 셀 해시 거절
  - seat 상호 배제
  - 비시뮬 하달기 거절
- **ROS-SIM:** §7 (a)–(i), 그리고 C6 종단 실행.
- **DEVICE / FIELD:** 이 결정으로 승격하지 않는다.

**관련 결정:** [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-327](D-327-semantic-manipulation-actions-and-device-adapters.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-390](D-390-pilot-omx-simulation-practice-boundary.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-401](D-401-rosy-cell-application.md), [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-404](D-404-omx-setup-teaching-api-simulation-first.md)

## 보강 (2026-10-03, C4b 1b): Cell Job claim 유지 규칙

- **claim은 승인부터 종결까지 유지한다.** Cell Job이 승인(admit)될 때 잡은 작업대·팔레트 claim은 Job이 종결될 때까지 놓지 않는다. 종결은 목표 확인 완료와 운영자 취소다. 예외는 아무것도 보내지 않은 제출 직전 HOLD뿐이며, 이때만 claim을 명시적으로 해제한다.
- **현장 정지는 종결되지 않은 Cell Job을 HOLD(site_stop)로 두고 claim을 유지한다.** 정지 래치는 같은 트랜잭션에서 READY·ACTION_SUCCEEDED Job을 HOLD(`site_stop`)로 바꾸고, 그 claim을 래치가 지우지 않는 단계 `HELD`로 옮긴다. 진행 중 Action의 claim은 `DISPATCHING`으로 남는다. 다른 Job은 이 자원을 승인받을 수 없다.
- **rearm을 막는 것은 미해결 claim뿐이다.** 결과를 모르는 `UNKNOWN`(그리고 아직 진행 중인 `DISPATCHING`)만 rearm을 막는다. `HELD`는 rearm을 막지 않는다. rearm 조건 자체는 바꾸지 않았다.
- **운영자 취소는 claim을 원자적으로 해제한다.** `POST /api/fleet/cell-jobs/{id}/cancel`(이름 있는 운영자)은 종결 전이와 claim 해제를 한 트랜잭션에서 한다. `DISPATCHING`이나 `UNKNOWN` claim이 있으면 거절하므로, 먼저 readback이나 `reconcile`로 결과를 확정한다. 재승인은 `resume`이 현재 세대로 claim을 다시 잡는다.
- 이 보강은 Cell Job에 대해 D-420 §4.5 첫 행(HOLD 때 claim 해제)을 대체한다. D-420은 이 절을 가리키도록 고친다.
- 근거: 리뷰 M1 재현(FAILED 뒤 HOLD인 Job A의 claim이 정지 래치로 지워져 같은 자원에 Job B가 승인됨). 구현과 시험은 브랜치 `feat/rosy-cell-c4b-wiring`의 C4b 1b 커밋.
