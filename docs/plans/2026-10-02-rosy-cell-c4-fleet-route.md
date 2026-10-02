# Rosy Cell C4 — Fleet ↔ OMX Cell 경로 (`CELL_TRANSFER`)

**부모 계획:** [Rosy Cell 완성 계획](2026-10-01-rosy-cell-completion.md) C4. C6(종단 수용)의 선행 단계다.
**결정 근거:** [D-403](../adr/D-403-fleet-cell-job-route-cell-transfer.md)(C4 계약 전체), [D-402](../adr/D-402-omx-motion-planner-v1-analytic-top-down-ik.md) §3·§7·§8·보강, [D-404](../adr/D-404-omx-setup-teaching-api-simulation-first.md) §6·§7, [D-330](../adr/D-330-fleet-action-admission-stop-and-recovery.md) §1·§2·Transition 2, [D-336](../adr/D-336-fleet-omx-local-ipc-boundary.md), [D-328](../adr/D-328-model-proposed-missions-and-independent-goal-evidence.md) §2·§4·§5, [D-12](../adr/D-12-mission-fleet.md), [D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md), [D-399](../adr/D-399-rosy-layered-architecture-site-plane-device-pipeline.md) §5, [D-401](../adr/D-401-rosy-cell-application.md).
**입력 증거:** [C3/C3b](../validation/rosy-cell-gazebo-c3-2026-10-02/README.md) "C4·C6가 반영할 것"·"C4·C6로 넘길 것", `src/products/omx/adapter/logs.md` 2026-10-02 항목(완료 journal 이름, minor 8 잠금 순서, grant 봉투·stop fence 대역).

**범위:** SOURCE 구현과 ROS-SIM 두 번(정지 세대 시험, 2–3 transfer Job 통합)이다. C5 화면, C6 종단 수용(2층·슬립시트·팔레트 2개 전체), 실물 OMX, 호스트 간 하달, DEVICE/FIELD는 포함하지 않는다.

**작업 위치:** worktree `.worktrees/cell-c4-fleet`, 브랜치 `feat/rosy-cell-c4-fleet-route`. 기반은 C3 브랜치 `c07896afe`이고, 그 merge-base는 main `4804d417`이다. main은 그 뒤로 311 커밋 앞서 있다(아래 Task 0).

---

## 0. 조사 결과 요약 (2026-10-02, `c07896afe` 기준으로 확인)

| 영역 | 현재 코드 | C4가 바꿀 것 |
|---|---|---|
| grant | `schemas.py:233` `FleetActionGrant`, `action_kind: str = Field(pattern=r"^PICK_PLACE$")`(:245), RGB-D `ResolvedTargetEvidence` 두 개 필수. 합집합 없음. digest 구현이 둘이다: Fleet `mission_dispatcher.py:32` `_grant_digest`, OMX `action_runner.py:24` `action_grant_digest`. PICK_PLACE digest를 고정하는 golden 시험은 없다. | 새 모듈에 `CellTransferGrant`와 판별 합집합을 둔다. golden digest를 고정한다. |
| 크기 규칙 | `schemas.py` 1095줄, 크기 판정 `test/architecture/test_module_structure.py` `SIZE_VERDICTS`, `HARD_TIER = 1_000`(증가 허용 0). `mission_store.py` 887줄, `proposal_store.py` 730줄(800 넘으면 분할 재검토), `action_store.py` 1187줄(hard tier), `pick_place_runner.py` 587줄. | 새 코드는 새 모듈에 둔다. hard tier 파일은 순증가 0으로 바꾼다. |
| Fleet 표 | `mission_store.py:78` `action_kind TEXT NOT NULL CHECK(action_kind='PICK_PLACE')`. `step_id UNIQUE`, Mission당 Step 하나(`f"{mission_id}:step-1"`, :255). FK 둘: `fleet_mission_events`(:106), `fleet_mission_event_retention`(:124). 이관은 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`뿐이고 버전 표가 없다. `sqlite_policy.py:14`가 `foreign_keys=ON`을 켠다. 표 재구성 선례는 저장소에 없다. | 표 재구성 이관 1회와 새 Step 표를 만든다(Task 6). |
| 제안 입구 | `proposal_store.py:35-38` `_ALLOWED_FIELDS`에 `kind`가 없다. `_MAX_CANDIDATE_BYTES = 32 * 1024`(:48). `finalize_resolution`이 `action_kind="PICK_PLACE"`로 고정한다(:647). resolver는 `mission_routes.py:83` `_resolve_candidate`(PICK_PLACE·카메라 전용). 운영 resolver 배선은 없고 시험만 주입한다. | `cell_job` 분기, 64 KiB, 종류 매개변수 |
| 승인 | `mission_routes.py:364-368` `/admit`가 `proposal_store.get(mission_id, principal_id=principal.principal_id)`로 자기 제안만 읽는다. 역할은 `{"viewer","operator","policy-admin"}`(`site_auth.py:46`, `site_users.py:11`)이다. `require_named_operator`(:167)는 principal이 구성돼 있는지만 본다. 서비스 principal 개념이 없다. | 역할 `cell-service`, 허용 목록, 승인자≠제안자 |
| 하달기 | `MissionDispatcher`(:37)는 Mission 하나에 grant 하나를 만든다. `dispatch_control()` 재확인은 :101. `_verified_receipt`는 4 phase를 요구한다. `local_action_transport.py:84` `_version`은 PICK_PLACE만 v2이고 나머지는 v1이다. `create_app`(`app.py:83`)에는 프로필 인자가 없다. `cli.py`는 하달기를 배선하지 않는다. | Job Step 순차 하달, `deployment_profile` 게이트, CELL_TRANSFER v2 |
| 목표 증거 | `goal_evidence.py:54,56`은 `object_in_destination` + `camera_observation`만 받는다. `goal_evidence_registry.py:22` `_EVIDENCE_SOURCES = frozenset({"camera_observation"})`. `GoalEvidence.satisfied`는 생산자가 정한 bool이다. | `item_at_pose` + `sim_model_pose`. 만족 여부는 Fleet이 계산한다. |
| 정지 생산자 | `task_store.py` `trip_stop_latch`(:326), `rearm_dispatch`(:332), `close_dispatch_for_startup`(:320). 팬아웃은 `task_dispatch_routes.py:64` `fanout_local_omx_stops` → `local_stop_transport.py:31` `StopLocal`. | 그대로 쓴다. Job HOLD 의미를 더한다. |
| OMX 수신 | `action_api.py` `ActionApi`(:26), `LocalStopApi`(:154), `UnixActionServer`(:262). `LocalActionPort`는 `action_runner.py:52`에 있다. **시험 밖에서 만드는 곳이 하나도 없다.** 배선 견본은 `test_omx_fleet_ros_actionserver.py:146-257`. | 운영 owner 프로세스(Task 5) |
| OMX 실행 | `action_runner.py:20-21` `PHASE_RUNNER_KINDS={"PICK_PLACE","CELL_TRANSFER"}`, `DIRECT_DRIVER_KINDS={"PICK_PLACE"}`. `_validate`(:134-151). `capability_current`는 hook일 뿐이고 운영 구현이 없다(시험 lambda `config_revision == "cfg-1"`). `PickPlaceRunner.advance()`를 운영 경로에서 부르는 곳이 없다(probe만 부른다). | CELL_TRANSFER phase 실행기, 수락 저장소 |
| 완료 journal | `action_store.py:817` `complete_pick_place`, :857·:865 `result_source='pick-place-workflow'`, :864 `PICK_PLACE_ACTION_COMPLETED`. 읽는 곳은 `test_omx_pick_place_transaction.py:196` 하나다. | 종류 중립 |
| 정지 소비자 | `local_stop.py` `LocalStopController`(:33): 표 `omx_local_stop`, `run_if_open`(:226), `rearm`(:177, 같은 DB의 `omx_actions` 미해결 0 요구). 기본 `fleet_fence_current`는 항상 False(`action_api.py:164`). | 운영 배선, probe `ProbeFence` 제거 |
| 잠금 순서 | runner replay가 `_event_lock`(`pick_place_runner.py:96`)을 쥔 채 `cancel_goal`(:477, :494) → owner `_lock`(`command_owner.py:315`)을 잡는다. watchdog 경로는 owner lock 안에서 `_cancel_active`(:385) → `handle.cancel()`(:398)을 부르고, `cancel_goal_async`가 동기 예외를 던지면 `CANCEL_ACK`를 즉시 emit한다(`ros_runtime.py:246-250`) → runner `_event_lock`. | 취소 호출을 두 lock 밖으로 옮긴다(Task 4). |
| seat | seat는 `pilot_sim_api.py:80-101`에만 있다. D-403 §10 / D-404 §7 상호 배제와 `PUT/GET /cell`이 없다. | Task 2 |
| 패키지 경계 | fleet `package.xml`에 `rosy_cell`이 없다. `test_module_structure.py` `edge_allowed`(:476-490)는 site → site 간선을 막는다. 예외는 `KNOWN_DIRECTION`(:56-60)과 집합이 같아야 한다. 선례는 `("rosy_vision", "games")`. `test_every_cross_package_use_is_declared`(:568)는 import마다 `exec_depend` 선언을 요구한다. | `exec_depend` + `KNOWN_DIRECTION` 한 줄 |
| `rosy_cell` | `compile_job(recipe, cell, *, tol_m)`(`compiler.py:120`), `carry_z(recipe, cell, *, tol_m)`(:93), `Job(recipe_hash, cell_hash, carry_z, steps)`, `Step(kind, item, pallet, layer, target, approach_z)`. 로더 `load_recipe(text)`, `load_cell(text)`. 해시 `content_hash`(`recipe.py:52`)는 `json.dumps(sort_keys=True, separators=(",",":"))`이고 `ensure_ascii`는 기본값이다. | 그대로 호출만 한다 |

## 1. D-403과 코드가 어긋나는 곳 (구현 전에 정할 것)

1. **D-403 상태가 Proposed다.** D-330·D-336 머리의 시뮬레이션 개정은 "D-403이 Accepted가 되면 효력이 생긴다"라고 적혀 있다. SOURCE 작업(Task 0–9)은 진행할 수 있다. 하지만 Task 10·11에서 하달기를 실제로 여는 것은 D-403 Accepted 뒤에만 한다. 사용자 결정이 필요하다(§7 Q1).
2. **grasp 기하 필드.** D-403 §2 필드 목록에는 `grasp_depth_m`·`grasp_width_m`이 없다. D-402 C3b 보강은 "요청자가 정하지 않고, 장치가 수락한 레시피에서 조회해 다르면 `ITEM_GEOMETRY_MISMATCH`"라고 한다. 이 계획은 grant 본문에 Fleet이 재컴파일한 값을 싣고 owner가 수락 레시피와 비교하는 방식으로 둘을 맞춘다(선언값 + 장치 대조). D-18에 따라 C4에서 wire를 확정하며 D-403 §2에 보강 문단을 단다(Task 12).
3. **`carry_z`의 `tol_m`.** D-403 §2는 `carry_z(recipe, cell)`로 적었지만 실제 시그니처는 `tol_m`을 필수 키워드로 받는다. probe는 `tol_m=0.001`, `rosy_cell` 시험은 `1e-6`을 쓴다. Fleet이 쓸 값의 출처가 필요하다(§7 Q3).
4. **`pallet`·`layer`·`frame`.** 장치 쪽 `CellTransferRequest`(`pose_plan.py:322`)에는 이 셋이 없다. grant에는 싣는다(Fleet 원장·증거용). 장치는 `frame == "robot_base"`만 검사하고 나머지는 journal에만 남긴다.
5. **거절 기록.** D-403 §9는 "Fleet은 `LOCAL_ACTION_REJECTED`로 기록하고 Job을 HOLD"라고 한다. 현재 하달기는 `LocalActionRejected`를 `FAILED`로 기록한다(:111-114). CELL_JOB에서는 Step을 `FAILED`(reason `LOCAL_ACTION_REJECTED`)로, Job 머리를 `HOLD`로 둔다. PICK_PLACE 경로는 바꾸지 않는다.
6. **서비스 principal의 이름.** D-403 §3은 "사이트 서비스 principal"이라고만 한다. 역할 집합에 `cell-service`를 더한다. 이름은 D-18 wire 확정 대상이다.
7. **장치의 레시피 수락 경로.** D-404 §6은 `PUT {PREFIX}/cell`만 정의한다. D-402 보강의 `accepted_item_geometry`는 수락한 레시피를 전제하지만 레시피 수락 API가 없다. 같은 규칙(seat 필요, 미해결 Action 중 거절, 해시 재계산)으로 `PUT/GET {PREFIX}/recipe`를 더한다. D-404에 보강 문단을 단다(Task 12).
8. **"시뮬레이션 identity" 확인 수단.** D-403 §7은 대상 인스턴스가 D-390 §5 시뮬레이션 identity여야 한다고 한다. UDS에는 identity를 묻는 연산이 없다. 이 계획은 두 겹으로 막는다. (a) Fleet: `create_app(deployment_profile="simulation", simulation_instances=...)`에서 구성된 모든 OMX 인스턴스가 `simulation_instances`에 있어야 한다. (b) 장치: owner 프로세스가 자기 프로필이 `simulation`이 아니면 `CELL_TRANSFER`를 `GRANT_REJECTED`로 거절한다. 장치 쪽이 실제 보증이다.

---

## 2. 작업 순서와 크기

크기: **S** ≤ 150줄(시험 포함), **M** 150–400줄, **L** 400–800줄. 각 Task는 리뷰 가능한 커밋 묶음 하나다. Task 1 뒤에는 OMX 트랙(2–5)과 Fleet 트랙(6–8)이 서로 독립이라 병렬로 진행할 수 있다.

| # | Task | 실행 환경 | 크기 | 선행 |
|---|---|---|---|---|
| 0 | main 병합과 start-state 충돌 해소 | 호스트 + WSL rclpy 반복(짧음) | M | — |
| 1 | `CELL_TRANSFER` grant 합집합 계약 | 호스트 | M | 0 |
| 2 | OMX 수락 셀·레시피 저장소, `capability_current`, seat 상호 배제 | 호스트 | M | 1 |
| 3 | OMX `CELL_TRANSFER` phase 실행기 + 종류 중립 완료 journal | 호스트 | L | 2 |
| 4 | 잠금 순서(minor 8) + 실제 stop fence | 호스트 | M | 3 |
| 5 | owner 프로세스 하나(HTTP + UDS) 운영 배선 | 호스트(조립) | L | 4 |
| 6 | Fleet 패키지 경계 + Step 표 + 표 재구성 이관 | 호스트 | L | 1 |
| 7a | Fleet `cell_job` 후보·resolver(`rosy_cell` 재컴파일) | 호스트 | M | 6 |
| 7b | Fleet 서비스 principal 제안 + 다른 운영자 승인 | 호스트 | S | 7a |
| 8a | Fleet Job Step 하달기 + `deployment_profile` 게이트 | 호스트 | L | 7b |
| 8b | Fleet `item_at_pose` / `sim_model_pose` 목표 증거 | 호스트 | M | 8a |
| 9 | 정지 세대 producer/consumer 시험 (a)–(i), 호스트 층 | 호스트 | L | 5, 8b |
| 10 | 정지 세대 시험 (a)–(i), ROS-SIM 층 | **WSL + Docker 이미지 + Gazebo. 비어 있는 WSL 슬롯 필요** | L | 9 |
| 11 | ROS-SIM 통합: 2–3 transfer Job을 실제 Fleet → UDS → owner로 실행 | **WSL + Gazebo. 비어 있는 WSL 슬롯 필요** | L | 10 |
| 12 | 계약 문서·ADR 보강·모듈 기록 마감 | 호스트 | S | 11 |

공통 규칙(모든 Task):
- 시작 전에 `git status --short --branch`를 확인하고 `rosy-land-on-main` 절차를 따른다. `git add <정확한 경로>`만 쓴다. stash·amend·reset은 쓰지 않는다.
- Task마다 해당 모듈의 `logs.md`에 항목을 쓰고 `progress.md`를 갱신한다. 이어서 `python tools/harness/rosy_harness.py generate`를 돌린다(memory: 하네스는 `python3`가 아니라 `python`).
- 커밋 메시지 끝에 빈 줄 하나, 그 뒤에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 둔다.
- 호스트 시험 명령(Windows, rclpy 없음):
  ```bash
  python -m pytest src/contracts/foundation/test/ -q
  python -m pytest src/site/fleet/test/ -q
  python -m pytest src/site/cell/test/ -q
  python -m pytest src/products/omx/adapter/test/ -q   # rclpy 시험은 importorskip으로 건너뛴다
  python -m pytest test/architecture/ test/test_fleet_omx_action_identity_contract.py test/test_cell_omx_sim_layout_contract.py -q
  ```
- 하나의 pytest 호출에 같은 basename 시험 파일을 섞지 않는다(Rosy `AGENTS.md`).

---

## Task 0 — main 병합과 start-state 충돌 해소 (M, 호스트 + WSL 짧게)

**이유:** `git merge-tree HEAD main`을 돌리면 충돌이 8곳 나온다. 그중 코드 충돌은 `command_owner.py`와 `pick_place_runner.py`다. main 쪽 OMX dispatch 안전 작업(`b0979ad60` 최종 dispatch에서 start state 재검증, `7735c307e` owner의 start-state 허용오차 상한, `11ae6e703` 계획 허용오차 예산 보존)과 C3b A1 `bc6a9955`(`TrajectoryCommand.start_state_window`, owner lock 안 바인딩)이 같은 문제를 다르게 풀었다. 나머지 충돌은 `STATUS.md`, `src/products/omx/adapter/{index,logs,progress}.md`, `src/sim/gz_sim/{index,logs}.md`이다. C4가 손댈 `app.py`·`schemas.py`도 main에서 바뀌었다(D-407, D-395).

**순서:**
1. C3 브랜치가 이미 main에 들어갔으면 그 main을 merge한다. 아니면 C3 리뷰 담당과 먼저 정한다. 이 계획은 "main을 이 브랜치에 merge"를 기본값으로 둔다(rebase는 하지 않는다).
2. `git merge main`을 실행한다. 코드 충돌은 **두 검사를 모두 유지**하는 쪽으로 푼다.
   - owner `submit`은 lock 안에서 `start_state_window`로 최신 state를 검사하고 그 sequence에 묶는다(C3b).
   - 그와 함께 main의 허용오차 상한(`7735c307e`)을 창의 허용오차에도 적용한다.
   - runner의 최종 재검증(`b0979ad60`)은 창 검사와 중복이면 하나로 합친다. 합칠 때 두 쪽 시험이 모두 통과해야 한다.
3. 문서 충돌은 양쪽 항목을 모두 남긴다. `index.md`·`STATUS.md`는 하네스로 다시 만든다.

**검증:**
```bash
python -m pytest src/products/omx/adapter/test/test_omx_command_owner.py src/products/omx/adapter/test/test_omx_pick_place_runner.py src/products/omx/adapter/test/test_omx_cell_transfer_runner.py -q
python -m pytest test/architecture/ -q
# WSL(rclpy). Gazebo는 필요 없다. 다른 세션의 Gazebo와 겹치면 nice -n 19
wsl -e bash -lc 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=77 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST; cd "<worktree>"; for i in $(seq 10); do python3 -m pytest -q src/products/omx/adapter/test/test_omx_ros_runtime.py src/products/omx/adapter/test/test_omx_fleet_ros_actionserver.py || break; done'
```
기대: 모두 통과한다. WSL은 10/10이다.

**커밋:** `merge: main into feat/rosy-cell-c4-fleet-route; keep C3b start window and main's owner tolerance cap`

---

## Task 1 — `CELL_TRANSFER` grant 합집합 계약 (M, 호스트)

**파일**
- 새로 만든다: `src/contracts/foundation/core_common/protocol/action_grants.py`. 담는 것: `CellTransferPose`, `CellTransferBody`, `CellTransferGrant`, `ActionGrant`(판별 합집합 별칭), `parse_action_grant`, `action_grant_digest`(공용 하나). 선례는 `protocol/localization.py`다.
- `schemas.py`는 바꾸지 않는다. hard tier라 증가가 0이어야 하고, `FleetActionGrant` 바이트 불변이 D-403 §2의 요구다.
- 바꾼다: `omx_adapter/action_runner.py:24`, `fleet/server/mission_dispatcher.py:32`. 두 digest 함수를 공용 `action_grant_digest`를 다시 내보내는 얇은 별칭으로 바꾼다.
- 바꾼다: `omx_adapter/action_api.py:73`. `FleetActionGrant.model_validate`를 `parse_action_grant`로 바꾼다.
- 바꾼다: `fleet/server/local_action_transport.py:84`. `_version`은 `PICK_PLACE`와 `CELL_TRANSFER` 모두 v2를 쓴다.
- 시험: `src/contracts/foundation/test/test_cell_transfer_grant_contract.py`(새로), `test/test_fleet_omx_action_identity_contract.py`(CELL_TRANSFER 사례 추가).

**모양(확정 wire, D-18):**
```python
class CellTransferPose(BaseModel):            # frozen, extra=forbid
    x: float; y: float; z: float; yaw: float  # finite; robot_base frame

class CellTransferBody(BaseModel):
    job_id: str                               # = Fleet mission_id
    recipe_sha256: str; cell_sha256: str      # ^[0-9a-f]{64}$
    step_index: int                           # transfer index k, strict, ge=0
    item: Literal["box", "slip_sheet"]
    pallet: str; layer: int                   # ledger/evidence only on the device
    frame: Literal["robot_base"]
    home: CellTransferPose; pick: CellTransferPose; place: CellTransferPose
    pick_approach_z: float; place_approach_z: float; carry_z: float
    grasp_depth_m: float; grasp_width_m: float  # Fleet-declared, device re-checks (§1-2)
    # validator: pick.z + grasp_depth_m <= pick_approach_z <= carry_z, same for place

class CellTransferGrant(BaseModel):
    # envelope = FleetActionGrant minus RGB-D evidence and observation_revision (D-403 §2)
    mission_id, step_id, action_id, attempt_id, request_digest, workcell_id, instance_id,
    action_kind: str = Field(pattern=r"^CELL_TRANSFER$")
    cell_transfer: CellTransferBody
    capability_revision, config_revision, authority_epoch, dispatch_generation, issued_at, expires_at

ActionGrant = Annotated[
    Union[Annotated[FleetActionGrant, Tag("PICK_PLACE")],
          Annotated[CellTransferGrant, Tag("CELL_TRANSFER")]],
    Discriminator(lambda v: v.get("action_kind") if isinstance(v, dict) else v.action_kind)]
```
`FleetActionGrant`의 `pattern`은 그대로 둔다. callable `Discriminator`는 `Literal`이 없어도 동작한다.

**TDD**
1. 실패하는 시험을 먼저 쓴다. golden 값은 이 계획을 쓸 때 `c07896afe`에서 실측했다.
```python
# src/contracts/foundation/test/test_cell_transfer_grant_contract.py
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from core_common.protocol.action_grants import (
    CellTransferGrant, action_grant_digest, parse_action_grant)
from core_common.protocol.schemas import FleetActionGrant

T0 = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 2, 0, 0, 15, tzinfo=timezone.utc)
PICK_PLACE_GOLDEN = "c847300c318ada2b16e49833603f499ccf6fcd2a4d70f18f2bd2c2e8d7014db8"

def _evidence(**o):
    v = {"object_id": "red-block-01", "observation_id": "camera-frame-44", "frame_sha256": "b" * 64,
         "camera_identity": "overhead-cam-01", "optical_frame_id": "overhead_optical",
         "calibration_revision": "overhead-cal-03", "transform_revision": "base-tf-12",
         "capture_time_ns": 1760000000000000000, "selector_kind": "point",
         "image_bbox_xyxy": [20.0, 30.0, 60.0, 70.0]}
    v.update(o); return v

def _pick_place():
    return {"mission_id": "mission-01", "step_id": "step-01", "action_id": "action-01",
            "attempt_id": "attempt-01", "request_digest": "0" * 64, "workcell_id": "omx-cell-01",
            "instance_id": "omx-cell-01-control", "action_kind": "PICK_PLACE",
            "source_evidence": _evidence(),
            "destination_evidence": _evidence(object_id="green-tray-01", selector_kind="label"),
            "capability_revision": "omx-pick-place-01", "config_revision": "workcell-config-08",
            "observation_revision": "camera-frame-44", "authority_epoch": 3,
            "dispatch_generation": 19, "issued_at": T0, "expires_at": T1}

def _pose(x, y, z, yaw=0.0): return {"x": x, "y": y, "z": z, "yaw": yaw}

def _cell_transfer(**body):
    b = {"job_id": "mission-cell-01", "recipe_sha256": "1" * 64, "cell_sha256": "2" * 64,
         "step_index": 0, "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base",
         "home": _pose(0.12, 0.0, 0.12), "pick": _pose(0.0, 0.17, 0.02, 1.5708),
         "place": _pose(0.1525, 0.0275, 0.03), "pick_approach_z": 0.06,
         "place_approach_z": 0.07, "carry_z": 0.117, "grasp_depth_m": 0.01, "grasp_width_m": 0.03}
    b.update(body)
    return {"mission_id": "mission-cell-01", "step_id": "mission-cell-01:t0",
            "action_id": "action-02", "attempt_id": "attempt-02", "request_digest": "0" * 64,
            "workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01",
            "action_kind": "CELL_TRANSFER", "cell_transfer": b,
            "capability_revision": "omx-cell-transfer-sim-v1", "config_revision": "cell-cfg-1",
            "authority_epoch": 3, "dispatch_generation": 19, "issued_at": T0, "expires_at": T1}

def test_pick_place_digest_is_unchanged_by_the_union():
    grant = parse_action_grant(_pick_place())
    assert type(grant) is FleetActionGrant
    assert action_grant_digest(grant) == PICK_PLACE_GOLDEN

def test_cell_transfer_parses_to_its_own_model_and_digests():
    grant = parse_action_grant(_cell_transfer())
    assert type(grant) is CellTransferGrant
    assert len(action_grant_digest(grant)) == 64

@pytest.mark.parametrize("body", [
    {"frame": "world"}, {"item": "pallet"}, {"recipe_sha256": "X" * 64},
    {"pick_approach_z": 0.01},                 # below pick.z + grasp_depth_m
    {"carry_z": 0.05},                         # below an approach height
    {"step_index": -1}, {"grasp_width_m": 0.0},
])
def test_cell_transfer_body_rejects_unsafe_or_foreign_values(body):
    with pytest.raises(ValidationError):
        parse_action_grant(_cell_transfer(**body))

def test_kinds_do_not_cross_validate():
    with pytest.raises(ValidationError):           # RGB-D fields on CELL_TRANSFER
        parse_action_grant(dict(_cell_transfer(), source_evidence=_evidence()))
    with pytest.raises(ValidationError):           # body on PICK_PLACE
        parse_action_grant(dict(_pick_place(), cell_transfer=_cell_transfer()["cell_transfer"]))
    with pytest.raises(ValidationError):
        parse_action_grant(dict(_pick_place(), action_kind="PICK"))
```
2. `python -m pytest src/contracts/foundation/test/test_cell_transfer_grant_contract.py -q`를 실행한다. 기대: import 오류로 실패한다.
3. `action_grants.py`를 구현한다. `_ACTION_ID`, 서로 다른 id 검사, aware·순서 있는 시각 검사는 `schemas.py`의 private helper를 import해서 재사용한다(복붙하지 않는다).
4. 같은 시험이 통과하는지 본다. 이어서 `test_device_action_contracts.py`, `test_fleet_omx_action_identity_contract.py`(CELL_TRANSFER 왕복 사례: Fleet digest == OMX digest, v2 receipt), `test_mission_dispatcher.py`, `test_omx_action_api.py`를 통과시킨다.
5. `test_omx_cell_transfer_runner.py:26-29`의 `model_copy(update={"action_kind": kind})` 우회를 실제 `CellTransferGrant` fixture로 바꾼다.

**커밋:** `feat(contracts): CELL_TRANSFER grant as a discriminated union beside unchanged PICK_PLACE (D-403 §2)`

---

## Task 2 — OMX 수락 셀·레시피 저장소, `capability_current`, seat 상호 배제 (M, 호스트)

**파일**
- 새로 만든다: `src/products/omx/adapter/omx_adapter/cell_acceptance.py`.
  - `AcceptedCellStore(path, *, kinematics_revision, simulation: bool)`. 표 `omx_accepted_cell(kind PRIMARY KEY CHECK(kind IN ('cell','recipe')), sha256, document_json, accepted_at, actor)`를 둔다. ActionStore와 **같은 SQLite 파일**을 쓴다. 미해결 Action 수를 같은 트랜잭션에서 읽어야 하기 때문이다(`local_stop.rearm`과 같은 방식).
  - `canonical_sha256(doc)`는 `json.dumps(doc, sort_keys=True, separators=(",",":"))`의 sha256이다. `rosy_cell.recipe.content_hash`와 바이트가 같아야 하고 `ensure_ascii`도 기본값이다. `omx_adapter`는 `rosy_cell`을 import하지 않는다(D-401 보강). 대신 저장소 루트의 교차 계약 시험이 둘을 묶는다.
  - `accept_cell(doc, *, actor)`: `schema == "rosy_cell.cell/2"`, `kinematics_revision`이 자기 값과 같음, 미해결 Action 0을 확인한다. 미해결 Action이 있으면 `CellAcceptanceRefused("UNRESOLVED_ACTION")`.
  - `accept_recipe(doc, *, actor)`: 이번 C4에서 받는 item은 `box`뿐이다. 보관하는 기하는 `{grasp_width_m: box.width, grasp_depth_m: box.grasp_depth (없으면 0), height_m: box.height}`다. `slip_sheet` 기하는 두지 않는다. C3b에서 집을 방법이 없었으므로 planner가 `ITEM_GEOMETRY_MISMATCH`로 거절한다.
  - `accepted_cell_sha256()`, `accepted_item_geometry(recipe_sha256, item)`: `AnalyticCellTransferPlanner`(`pose_plan.py:482-501`)의 두 hook 시그니처를 그대로 따른다.
  - `capability_current(grant)`:
    - `PICK_PLACE`면 주입한 기존 판정을 그대로 쓴다.
    - `CELL_TRANSFER`면 다음을 모두 요구한다: `simulation` 프로필, `cell_sha256 == accepted`, `recipe_sha256 == accepted`, `item` 기하가 있음, grant의 `grasp_width_m`·`grasp_depth_m`이 수락값과 1e-9 안에서 같음, `frame == robot_base`.
    - `ActionRunner._validate`(:150)에서 False면 journal을 만들기 전에 `GRANT_REJECTED` 403이 된다(D-403 §9 첫 검사). planner의 두 번째 검사(`pose_plan.py:509-512`)는 그대로 둔다.
- 새로 만든다: `omx_adapter/owner_exclusion.py`. `SeatActionExclusion`은 lock 하나로 다음 두 상태를 지킨다.
  - `acquire_seat()`: 미완료 `CELL_TRANSFER`가 있으면 `SEAT_BUSY_WITH_ACTION`.
  - `begin_cell_transfer(action_id)` / `end_cell_transfer(action_id)`: seat가 잡혀 있으면 `ACTION_REFUSED_SEAT_HELD`.
  - 이 상태는 메모리 전용이다. 재시작하면 owner는 어차피 UNKNOWN/HOLD에서 시작하고(D-336 노트), 미해결 Action이 있으면 seat 획득도 거절한다. 판단 근거는 journal의 미해결 수다.
- 바꾼다: `omx_adapter/pilot_sim_api.py`.
  - seat 획득(:200)이 `SeatActionExclusion.acquire_seat()`를 거치게 한다.
  - `PUT/GET {PREFIX}/cell`, `PUT/GET {PREFIX}/recipe`를 더한다(seat 필요, 409 `UNRESOLVED_ACTION`, 422 schema/revision 불일치).
- 시험(새로): `test_omx_cell_acceptance.py`, `test_omx_owner_exclusion.py`, `test/test_cell_omx_acceptance_hash_contract.py`(루트, 두 패키지를 함께 import).
- 기존 시험 확장: `test_pilot_sim_api.py`.

**TDD (발췌)**
```python
# src/products/omx/adapter/test/test_omx_cell_acceptance.py
import json, pathlib, pytest, yaml
from omx_adapter.cell_acceptance import AcceptedCellStore, CellAcceptanceRefused, canonical_sha256

EX = pathlib.Path(__file__).resolve().parents[4] / "site/cell/examples/omx_sim"

def _docs():
    return (yaml.safe_load((EX / "cell.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((EX / "recipe.yaml").read_text(encoding="utf-8")))

def _store(tmp_path, unresolved=0):
    cell, _ = _docs()
    return AcceptedCellStore(tmp_path / "owner.sqlite3", kinematics_revision=cell["kinematics_revision"],
                             simulation=True, unresolved_actions=lambda: unresolved)

def test_accepted_hashes_survive_restart_and_feed_the_planner_hooks(tmp_path):
    cell, recipe = _docs()
    store = _store(tmp_path)
    cell_sha = store.accept_cell(cell, actor="op-1")
    recipe_sha = store.accept_recipe(recipe, actor="op-1")
    again = _store(tmp_path)
    assert again.accepted_cell_sha256() == cell_sha == canonical_sha256(cell)
    geometry = again.accepted_item_geometry(recipe_sha, "box")
    assert geometry == {"grasp_width_m": recipe["box"]["width"],
                        "grasp_depth_m": recipe["box"].get("grasp_depth", 0.0),
                        "height_m": recipe["box"]["height"]}
    assert again.accepted_item_geometry(recipe_sha, "slip_sheet") is None
    assert again.accepted_item_geometry("0" * 64, "box") is None

def test_replacing_the_cell_with_an_unresolved_action_is_refused(tmp_path):
    cell, _ = _docs()
    with pytest.raises(CellAcceptanceRefused, match="UNRESOLVED_ACTION"):
        _store(tmp_path, unresolved=1).accept_cell(cell, actor="op-1")

def test_foreign_kinematics_revision_is_refused(tmp_path):
    cell, _ = _docs()
    with pytest.raises(CellAcceptanceRefused, match="KINEMATICS_REVISION"):
        _store(tmp_path).accept_cell(dict(cell, kinematics_revision="f" * 64), actor="op-1")
```
```python
# test/test_cell_omx_acceptance_hash_contract.py  (repo root: binds two packages that never import each other)
def test_device_hash_equals_rosy_cell_content_hash():
    from omx_adapter.cell_acceptance import canonical_sha256
    from rosy_cell.cell import load_cell
    from rosy_cell.recipe import load_recipe
    text_cell, text_recipe = (EX / "cell.yaml").read_text("utf-8"), (EX / "recipe.yaml").read_text("utf-8")
    assert canonical_sha256(yaml.safe_load(text_cell)) == load_cell(text_cell).content_hash
    assert canonical_sha256(yaml.safe_load(text_recipe)) == load_recipe(text_recipe).content_hash
```
`capability_current` 시험은 `test_omx_action_api.py`의 `_runner` helper를 재사용한다. 다음 경우 모두 `GRANT_REJECTED`이고 `omx_actions`에 행이 없어야 한다: 셀 해시 다름, 레시피 미수락, 폭 다름, 비시뮬 프로필, seat 잡힘.

**커밋:** `feat(omx): accepted cell/recipe store backs capability_current; seat and CELL_TRANSFER exclude each other (D-403 §9-10, D-404 §6-7)`

---

## Task 3 — OMX `CELL_TRANSFER` phase 실행기 + 종류 중립 완료 journal (L, 호스트)

**문제:** `ActionRunner`는 factory의 `start()`만 부른다(첫 phase). 운영 경로에서 `advance()`, grasp 뒤 hold 판정, release 뒤 해제 판정, 부모 Action 완료를 하는 주체가 없다. 지금은 probe가 이 일을 한다(`probe_cell_transfer.py:364-371, 405-434`).

**파일**
- 새로 만든다: `omx_adapter/cell_transfer_execution.py`.
  - `cell_transfer_factory(*, planner, profile, acceptance, exclusion, goal_port, command_for_phase, current_execution_state, gripper_readback, stop_fence, current_fence, store, sim_hooks=None) -> Callable[[CellTransferGrant, ActionPhaseRecorder], PhaseExecution]`.
  - 하는 일:
    1. grant 본문 → `CellTransferRequest`(`pose_plan.py:322`). 필드는 1:1이다.
    2. `planner.plan_transfer(request, profile, state)`. `CellTransferPlanRejected`면 Action을 HOLD로 두고 reason에 거절 코드를 쓴다.
    3. `PickPlaceRunner(..., plan=CellTransferPlan, cell_profile, gripper_readback, held_object_id=f"{job_id}:{step_index}")`를 만든다.
    4. **phase sequencer:** runner의 terminal `SUCCEEDED` 이벤트를 받으면 ROS 콜백 스레드가 아니라 **전용 단일 작업 스레드**(`queue.Queue`)에서 다음을 한다.
       - grasp 뒤: `verify_held_object`. 통과하면 `sim_hooks.on_hold_verified()`.
       - release 직전: runner 자체 재확인(C3b A4).
       - `advance()`.
       - release 뒤: `verify_released_object`. 통과하면 `store.complete_workflow(...)`.
       - 어느 판정이든 실패하면 HOLD다. 놓기와 재파지는 자동으로 하지 않는다.
    5. `exclusion.begin_cell_transfer` / `end_cell_transfer`(terminal·HOLD 모두에서 해제).
  - `sim_hooks`는 sim attach aid(C3b B3)를 owner 진입점에서만 주입하는 자리다. 기본값은 no-op이다. 증거에는 "SIM AID"로 표시한다.
- 바꾼다: `omx_adapter/action_store.py`. **순증가 0줄**(hard tier).
  - `complete_pick_place` → `complete_workflow(action_id, attempt_id, *, action_kind, ...)`.
  - 이벤트 이름은 `ACTION_WORKFLOW_COMPLETED`로 하고 detail에 `action_kind`를 넣는다.
  - `result_source`는 `pick-place-workflow`(PICK_PLACE, 기존 값 유지) 또는 `cell-transfer-workflow`다.
  - 4-phase 경계 검사(:792, :841, :941)의 오류 문구를 종류 중립으로 바꾼다.
  - `PickPlaceWorkflowJournal`(`pick_place_transaction.py:293`) 호출처를 같이 바꾼다.
  - 디스크에 이미 있는 `PICK_PLACE_ACTION_COMPLETED` 행은 그대로 둔다. 읽는 곳이 시험 하나뿐이다.
- 시험(새로): `test_omx_cell_transfer_execution.py`. 가짜 `PhaseGoalPort`, 가짜 readback, 실제 `ActionStore`, 실제 `AnalyticCellTransferPlanner`를 쓴다.
- 시험(확장): `test_omx_action_store.py`, `test_omx_pick_place_transaction.py:196`.

**TDD 사례(각각 먼저 실패하는 것을 확인한다)**
1. 정상 흐름: 4 phase 모두 SUCCEEDED → 부모 `SUCCEEDED`, 이벤트 `ACTION_WORKFLOW_COMPLETED`(detail `action_kind == "CELL_TRANSFER"`), `result_source == "cell-transfer-workflow"`. seat 다시 획득 가능.
2. grasp 뒤 readback이 빈손 → `HOLD`, transfer phase 미제출(goal_port 제출 수 2).
3. release 전 재확인 실패 → `ITEM_LOST_IN_TRANSIT`, release 미제출.
4. planner 거절(`CELL_HASH_MISMATCH`, `ITEM_GEOMETRY_MISMATCH`) → phase 0개, Action HOLD.
5. sequencer는 ROS 콜백 스레드에서 `advance()`를 부르지 않는다. 가짜 port가 콜백 스레드 id를 기록하고, `advance` 호출 스레드 id와 다름을 단언한다.
6. PICK_PLACE 완료 경로는 `result_source == "pick-place-workflow"`로 그대로다.

**커밋 2개:**
- `refactor(omx): kind-neutral workflow completion journal (ACTION_WORKFLOW_COMPLETED)`
- `feat(omx): CELL_TRANSFER phase execution — plan, sequence, gripper gates, completion (D-402 §3/§8, D-403 §9)`

---

## Task 4 — 잠금 순서(minor 8) + 실제 stop fence (M, 호스트)

**잠금 규칙(이 Task가 고정한다):** owner `_lock`과 runner `_event_lock`/`_lock`을 쥔 채로 상대 쪽 lock을 잡는 호출을 하지 않는다. 취소는 lock 안에서 **결정만** 하고, 호출은 lock 밖에서 한다.

**파일**
- `command_owner.py`:
  - `_cancel_active`(:385)는 handle을 `self._pending_cancels`에 넣기만 한다.
  - 공개 진입점(`poll` :547, `observe_joint_state` :414, `submit` :444, `cancel` :592)은 `with self._lock:` 블록을 나온 뒤 `_drain_cancels()`에서 `handle.cancel()`을 부른다.
  - HOLD 래치 자체는 lock 안에서 설정한다. 래치가 먼저 걸리므로 새 제출이 그사이에 끼어들 수 없다.
- `pick_place_runner.py`:
  - replay(:362-375)와 `_process_ros_goal_event`의 취소 결정(:477, :494)은 `_event_lock` 안에서 `cancel_goal` 대상 UUID만 모은다.
  - `on_ros_goal_event`(:400)와 replay 호출자가 lock을 놓은 뒤 `goal_port.cancel_goal(uuid)`를 부른다.
  - 파일이 587줄이라 600을 넘으면 크기 판정을 다시 받는다.
- 실제 stop fence:
  - probe의 `ProbeFence`(`probe_cell_transfer.py:222-229`)와 항상 참인 `current_fence`(:357-358)를 걷는다.
  - 운영 조립에서는 `submission_fence = LocalStopController`(같은 SQLite)로 한다.
  - `current_fence(epoch, gen)`은 컨트롤러 상태가 `OPEN`이고 그 행의 `(authority_epoch, dispatch_generation) == (epoch, gen)`일 때만 참이다.
  - 이 판정 함수 `local_fence_current(controller)`를 `local_stop.py`에 더한다(D-403 §6: 제출 때, 각 phase 직전).
- 시험(새로): `test_omx_lock_order.py`.

**TDD**
```python
# src/products/omx/adapter/test/test_omx_lock_order.py
import threading

class RecordingLock:
    """Wraps an RLock and records (thread, other locks held) at each acquire."""
    held = threading.local()
    edges: list[tuple[str, str]] = []
    def __init__(self, name): self.name, self._lock = name, threading.RLock()
    def __enter__(self):
        for other in getattr(RecordingLock.held, "stack", []):
            if other != self.name:
                RecordingLock.edges.append((other, self.name))
        self._lock.acquire(); RecordingLock.held.stack = getattr(RecordingLock.held, "stack", []) + [self.name]
    def __exit__(self, *exc):
        RecordingLock.held.stack.pop(); self._lock.release()
    acquire = lambda self, *a, **k: self.__enter__() or True
    release = lambda self: self.__exit__(None, None, None)

def test_watchdog_cancel_with_synchronous_cancel_failure_never_nests_locks(owner_and_runner):
    owner, runner, handle = owner_and_runner(cancel_raises_synchronously=True)
    owner._lock, runner._event_lock = RecordingLock("owner"), RecordingLock("event")
    RecordingLock.edges.clear()
    handle.make_stale()                 # joint state ages past max -> poll() enters HOLD
    owner.poll()                        # cancel -> sync CANCEL_ACK(False) -> runner event path
    runner.replay_pending()             # late-acceptance replay path that cancels
    assert ("owner", "event") not in RecordingLock.edges
    assert ("event", "owner") not in RecordingLock.edges
    assert owner.state == "HOLD" and handle.cancel_calls == 1

def test_two_threads_cancel_paths_finish_within_one_second(owner_and_runner):
    owner, runner, handle = owner_and_runner(cancel_raises_synchronously=True)
    a = threading.Thread(target=owner.poll); b = threading.Thread(target=runner.replay_pending)
    a.start(); b.start(); a.join(1.0); b.join(1.0)
    assert not a.is_alive() and not b.is_alive()
```
`owner_and_runner` fixture는 `test_omx_pick_place_runner.py`의 `_GoalPort`/`_Fence`와 `test_omx_command_owner.py`의 가짜 `ActionPort`로 만든다. `cancel_raises_synchronously=True`이면 가짜 handle의 `cancel()`이 `CANCEL_ACK(False)`를 같은 스레드에서 runner로 emit한다. `ros_runtime.py:246-250`의 경로를 그대로 흉내 낸 것이다.

stop fence 시험(`test_omx_stop_fence.py` 확장):
- (i) `trip` 뒤 `run_if_open`은 `LocalStopBlocked`이고 operation이 호출되지 않는다.
- (ii) `rearm(epoch, gen+1)` 뒤 옛 `gen` grant의 `current_fence`는 False다.
- (iii) 재시작한 컨트롤러는 `UNKNOWN / STARTUP_STOP_UNCONFIRMED`이고 `current_fence`는 False다.

**WSL 확인(짧게, 이 Task 끝):** Task 0의 rclpy 반복을 25회 돌린다. 기대: 25/25.

**커밋:** `fix(omx): cancel outside the owner and runner locks (minor 8); real LocalStopController fence replaces the always-open stand-in`

---

## Task 5 — owner 프로세스 하나(HTTP + UDS) 운영 배선 (L, 호스트 조립 시험)

**파일**
- 새로 만든다: `omx_adapter/cell_owner_server.py`.
  - `build_cell_owner(settings, *, runtime_factory, now) -> CellOwnerAssembly`: 순수 조립이다. 모듈 최상단에서 rclpy를 import하지 않는다. 담는 것:
    - `ArmCommandOwner` 하나: `CellPlanningProfile.arm_command_config(..., allowed_owners=("pilot_sim", "rule_based"))`(`pose_plan.py:302-318`), `owner_clock="sim"`, `wall_clock_bound_factor`.
    - `ActionStore`, `LocalStopController`, `AcceptedCellStore`가 같은 SQLite 파일을 쓴다(`<state_dir>/owner.sqlite3`).
    - `SeatActionExclusion`.
    - `ActionRunner(enabled=settings.profile == "simulation", submission_fence=controller, current_fence=local_fence_current(controller), capability_current=acceptance.capability_current, phase_runner_factories={"CELL_TRANSFER": cell_transfer_factory(...)}, allowed_peer_uids={settings.fleet_uid}, principal_for_peer=...)`.
    - `LocalStopApi(controller, source_by_peer_uid={settings.fleet_uid: StopRequestSource.FLEET}, cancel_active=runner.cancel_unresolved, fleet_fence_current=...)`.
    - `ActionApi(runner, stop_api=...)`, `UnixActionServer(api, f"/run/rosy/omx/{instance_id}/control.sock")`.
    - `create_pilot_sim_app(...)`에 exclusion과 acceptance를 넘긴다.
  - `main()`: `refuse_second_owner()`(`deploy/robot/omx/cell_sim_tools.py:27-38`)로 `pilot_sim_server`·probe와 함께 뜨지 않는다. `RosArmCommandRuntime`과 `MultiThreadedExecutor`를 쓴다. UDS는 별도 스레드에서 `serve_forever`, uvicorn은 주 스레드에서 돈다. 둘 다 같은 owner를 본다(D-403 §8).
- 새로 만든다: `deploy/robot/omx/run_cell_owner.sh`.
  - 컨테이너 안에서 owner를 실행한다.
  - socket 부모 디렉터리 `/run/rosy/omx/<instance_id>/`는 bind-mount로 받는다. 부모 디렉터리는 미리 있어야 한다(`action_api.py:278-285`).
  - Fleet UID는 `ROSY_FLEET_UID`로 받는다. 그 값은 Task 11에서 owner 쪽에서 관측한 `SO_PEERCRED` UID다.
- `pilot_sim_server.py`는 Pilot 전용 모드로 그대로 둔다. 두 진입점은 서로 거절한다.
- 시험(새로): `test_omx_cell_owner_assembly.py`(호스트). 가짜 runtime factory로 다음을 단언한다.
  1. HTTP `PUT /cell`로 수락한 해시를 UDS `SubmitAction`의 `capability_current`가 본다(같은 저장소 객체).
  2. HTTP로 seat를 잡으면 UDS `CELL_TRANSFER`는 403이다. 반대로 진행 중 Action이 있으면 seat 획득은 409다.
  3. `settings.profile != "simulation"`이면 `CELL_TRANSFER`가 403이다(§1-8b).
  4. `allowed_owners`가 정확히 `("pilot_sim", "rule_based")`다.
  5. `UnixActionServer`가 `/run/rosy/omx/<instance>/control.sock` 경로를 쓴다(실제 bind는 Linux 시험에서).
- UDS bind와 `SO_PEERCRED`는 Windows에서 시험할 수 없다. 실제 socket 시험은 Task 10에서 WSL로 한다.

**커밋:** `feat(omx): one cell owner process serves the D-404 HTTP API and the D-336 UDS socket (D-403 §8)`

---

## Task 6 — Fleet 패키지 경계 + Step 표 + 표 재구성 이관 (L, 호스트)

### 6.1 경계
- `src/site/fleet/package.xml`에 `<exec_depend>rosy_cell</exec_depend>`를 더한다.
- `test/architecture/test_module_structure.py` `KNOWN_DIRECTION`에 다음 한 줄을 더한다.
  ```python
  ("fleet", "rosy_cell"): "site/fleet -> site/cell: Fleet recompiles a Rosy Cell Job with rosy_cell.compile_job/carry_z instead of reimplementing it (D-403 §3, D-12); only fleet/server/cell_job.py imports it",
  ```
- `src/site/fleet/test/test_boundaries.py`에 규칙을 더한다: `rosy_cell` import는 `fleet/server/cell_job.py` 한 파일에만 있다. 반대 방향(`rosy_cell` → `fleet`)은 없다.
- 방향 근거: Application(`rosy_cell`)은 순수 라이브러리이고 Fleet이 그것을 호출한다. Fleet이 Application 서버를 호출하는 것이 아니다. D-399 §5의 "Application → Fleet" 요청 방향은 HTTP 경계(C5 서버 → `/api/fleet/proposals`)에서 지켜진다.

### 6.2 이관 방식 (SQLite는 CHECK를 바꿀 수 없다)
- **선택: SQLite 공식 "12단계" 표 재구성을 한 번만 한다.**
  - `fleet_missions`는 Mission 머리로 남긴다. CHECK는 `action_kind IN ('PICK_PLACE','CELL_JOB')`로 넓힌다.
  - Step 실행 상태는 새 표 `fleet_mission_steps`에 둔다. 이 표에는 **종류 CHECK를 두지 않는다.** 다음 종류 때문에 같은 재구성을 반복하지 않기 위해서다. 종류 검사는 코드와 시험이 맡는다.
  - 기존 PICK_PLACE Mission은 지금 열과 경로를 그대로 쓴다. Step 표로 옮기지 않는다(D-403 §4 "단일 Step 경로 보존").
- 새 모듈(`mission_store.py`는 887줄이라 늘리지 않는다):
  - `fleet/server/mission_schema.py`: `migrate_mission_schema(connection, *, db_path)`. 마커 표는 `fleet_schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)`이다. 같은 DB를 task·proposal·goal evidence 저장소가 함께 쓰므로 `PRAGMA user_version`은 쓰지 않는다.
  - `fleet/server/mission_steps.py`: Step 표 DDL과 함수들. 함수는 호출자의 연결·트랜잭션 안에서 돈다. 함수 목록: `insert_job_steps`, `next_ready_step`, `start_step`, `record_step_result`, `hold_step`, `confirm_step_goal`, `steps_for`.
- `MissionStore.__init__`(:66)은 기존 ADD COLUMN 이관(:129-147) **뒤에** `migrate_mission_schema`를 부른다. 그래야 모든 열이 있는 상태에서 재구성한다.
- `migrate_mission_schema` 절차(이름 `c4_mission_kind_and_steps`, 한 번만):
  1. 마커가 있으면 Step 표 `CREATE TABLE IF NOT EXISTS`만 하고 끝낸다.
  2. 진행 중 상태가 있으면 이관을 거절하고 `MissionSchemaMigrationRefused`를 낸다. 진행 중 상태는 `SELECT count(*) FROM fleet_missions WHERE status IN ('RUNNING','ACTION_SUCCEEDED') OR reconciliation_pending=1` > 0이다. Fleet 기동이 실패하고 옛 스키마는 그대로 남는다. 결과가 불명인 Action을 이관 도중에 건드리지 않는다(D-330 §1).
  3. `PRAGMA legacy_alter_table`이 0인지 확인한다. 아니면 거절한다.
  4. `sqlite3.Connection.backup()`으로 `<db>.pre-c4-<UTC>.sqlite3`를 DB 옆에 만든다. 실패하면 거절한다.
  5. `PRAGMA foreign_keys=OFF`(트랜잭션 밖) → `BEGIN IMMEDIATE`.
  6. `CREATE TABLE fleet_missions_c4 (...)`: 현재 모든 열을 같은 이름·순서로 두고 CHECK만 넓힌다. `INSERT INTO fleet_missions_c4 (<열 목록>) SELECT <열 목록> FROM fleet_missions`.
  7. `DROP TABLE fleet_missions` → `ALTER TABLE fleet_missions_c4 RENAME TO fleet_missions` → 인덱스 3개를 다시 만든다(`fleet_missions_status`, `fleet_missions_ready_queue`, `fleet_missions_reconcile_queue`).
  8. `CREATE TABLE fleet_mission_steps (...)`.
  9. `PRAGMA foreign_key_check`가 빈 결과인지, 행 수가 같은지 확인한다. 어긋나면 `ROLLBACK`.
  10. 마커를 넣고 `COMMIT` → `PRAGMA foreign_keys=ON`.
  11. 마지막으로 `sqlite_master`에 `fleet_missions_c4`가 남지 않았음을 확인한다.
- Step 표 DDL:
  ```sql
  CREATE TABLE IF NOT EXISTS fleet_mission_steps (
      mission_id TEXT NOT NULL REFERENCES fleet_missions(mission_id),
      step_index INTEGER NOT NULL CHECK(step_index >= 0),
      step_id TEXT NOT NULL UNIQUE,
      action_kind TEXT NOT NULL,
      body_json TEXT NOT NULL,
      goal_predicate_json TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('PENDING','READY','RUNNING','ACTION_SUCCEEDED',
                                            'GOAL_CONFIRMED','FAILED','HOLD','CANCELED')),
      action_id TEXT, attempt_id TEXT, action_grant_json TEXT,
      authority_epoch INTEGER, dispatch_generation INTEGER,
      reconciliation_pending INTEGER NOT NULL DEFAULT 0,
      reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY (mission_id, step_index));
  CREATE INDEX IF NOT EXISTS fleet_mission_steps_queue ON fleet_mission_steps(status, mission_id, step_index);
  ```
  - CELL_JOB 머리 행의 `step_id`는 `f"{mission_id}:job"`이다(UNIQUE 유지). `plan_json`에는 Job 요약(해시, `carry_z`, transfer 수)을 둔다.
- 크기 판정: `fleet` 패키지 판정 문구에 C4 재판정을 한 줄 더한다.

### 6.3 TDD
```python
# src/site/fleet/test/test_mission_schema_migration.py
import sqlite3
import pytest
from fleet.server.mission_schema import MissionSchemaMigrationRefused
from fleet.server.mission_store import MissionStore

LEGACY_DDL = """  -- copied verbatim from mission_store.py:72-127 at c07896afe, plus the four ADD COLUMNs
"""

def _legacy_db(path, *, status="GOAL_CONFIRMED", pending=0):
    with sqlite3.connect(path) as c:
        c.executescript(LEGACY_DDL)
        c.execute("INSERT INTO fleet_missions (mission_id, step_id, principal_id, request_key, "
                  "request_digest, action_kind, workcell_id, instance_id, plan_json, "
                  "goal_predicate_json, status, reconciliation_pending, created_at, updated_at) "
                  "VALUES ('m1','m1:step-1','op','k1',?, 'PICK_PLACE','w','i','{}','{}',?,?,'t','t')",
                  ("a" * 64, status, pending))
        c.execute("INSERT INTO fleet_mission_events (event_source, source_event_id, mission_id, "
                  "step_id, state, event_type, actor_id, detail_json, created_at) "
                  "VALUES ('fleet','e1','m1','m1:step-1','READY','ADMITTED','op','{}','t')")
    return path

def test_existing_pick_place_rows_and_events_survive_and_cell_job_is_admitted(tmp_path):
    db = _legacy_db(tmp_path / "fleet.sqlite3")
    MissionStore(db)
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT status FROM fleet_missions WHERE mission_id='m1'").fetchone() == ("GOAL_CONFIRMED",)
        assert c.execute("SELECT count(*) FROM fleet_mission_events").fetchone() == (1,)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        c.execute("INSERT INTO fleet_missions (mission_id, step_id, principal_id, request_key, "
                  "request_digest, action_kind, workcell_id, instance_id, plan_json, "
                  "goal_predicate_json, status, created_at, updated_at) VALUES "
                  "('m2','m2:job','svc','k2',?, 'CELL_JOB','w','i','{}','[]','PROPOSED','t','t')", ("b" * 64,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE fleet_missions SET action_kind='PICK' WHERE mission_id='m2'")
    assert list(tmp_path.glob("fleet.sqlite3.pre-c4-*.sqlite3"))

def test_migration_is_idempotent(tmp_path):
    db = _legacy_db(tmp_path / "fleet.sqlite3")
    MissionStore(db); MissionStore(db)
    assert len(list(tmp_path.glob("fleet.sqlite3.pre-c4-*.sqlite3"))) == 1

@pytest.mark.parametrize("status,pending", [("RUNNING", 0), ("ACTION_SUCCEEDED", 0), ("HOLD", 1)])
def test_migration_refuses_with_unresolved_device_actions(tmp_path, status, pending):
    db = _legacy_db(tmp_path / "fleet.sqlite3", status=status, pending=pending)
    with pytest.raises(MissionSchemaMigrationRefused):
        MissionStore(db)
    with sqlite3.connect(db) as c:   # old schema untouched
        sql = c.execute("SELECT sql FROM sqlite_master WHERE name='fleet_missions'").fetchone()[0]
        assert "CHECK(action_kind='PICK_PLACE')" in sql

def test_fresh_database_gets_the_new_schema_directly(tmp_path):
    MissionStore(tmp_path / "fresh.sqlite3")
    with sqlite3.connect(tmp_path / "fresh.sqlite3") as c:
        assert c.execute("SELECT name FROM fleet_schema_migrations").fetchall() == [("c4_mission_kind_and_steps",)]
```
`LEGACY_DDL`은 시험 파일에 **문자 그대로 복사해 고정**한다. 이후 `mission_store.py`가 바뀌어도 옛 DB 모양에 대한 시험은 흔들리지 않는다.

**커밋 2개:**
- `build(fleet): declare rosy_cell and its one importing module (D-403 §3)`
- `feat(fleet): one-time fleet_missions rebuild for CELL_JOB and an ordered fleet_mission_steps table (D-403 §4)`

---

## Task 7a — Fleet `cell_job` 후보·resolver (M, 호스트)

**파일**
- 새로 만든다: `fleet/server/cell_job.py`. `rosy_cell`을 import하는 유일한 모듈이다.
  - `check_cell_job_candidate(raw) -> dict`. 필드는 정확히 다음과 같다: `{kind: "cell_job", request_id, source, recipe_yaml, cell_yaml, recipe_sha256, cell_sha256, job, workcell_id, instance_id}`. 정규 JSON 크기가 64 KiB를 넘으면 `CELL_JOB_TOO_LARGE`. 민감 필드 거절은 `mission_routes.py:108` 규칙을 재사용한다.
  - `resolve_cell_job(candidate, *, tol_m, goal_tolerance, workcell_id, instance_id) -> dict`:
    1. `load_recipe(recipe_yaml)`, `load_cell(cell_yaml)`. 실패하면 `CELL_JOB_INVALID`.
    2. `recipe.content_hash == recipe_sha256`이고 `cell.content_hash == cell_sha256`이어야 한다. 아니면 `CELL_JOB_HASH_MISMATCH`.
    3. `job = compile_job(recipe, cell, tol_m=tol_m)`, `ceiling = carry_z(recipe, cell, tol_m=tol_m)`. `job.carry_z == ceiling`을 단언한다. 계산은 다시 구현하지 않는다(D-403 §2).
    4. 후보 `job`(Step 목록)을 Fleet이 컴파일한 Job의 정규 JSON과 비교한다. 다르면 `CELL_JOB_MISMATCH`. Fleet은 자기 순서를 쓴다(D-12).
    5. `pallet_done`을 뺀 Step을 앞에서부터 `(pick, place)` 쌍으로 묶는다. 같은 item·pallet·layer가 아니거나 홀수이면 `CELL_JOB_UNPAIRED`.
    6. transfer k마다 `CellTransferBody`(Task 1)를 만든다. `home = cell.home`, `grasp_depth_m = recipe.box.grasp_depth`(slip_sheet 0), `grasp_width_m = recipe.box.width`. `goal_predicate`(Task 8b 모양): 목표 = place 포즈의 물건 중심, z는 윗면 − 높이/2.
    7. resources: `[("workcell", workcell_id)] + [("pallet", f"{workcell_id}:{p}") for p in pallets]`. Job 전체 기간 동안 잡는다(D-403 §4).
  - 반환 모양: `{"plan": {...요약}, "goal_predicate": [...], "resources": [...], "steps": [...]}`.
- 바꾼다: `proposal_store.py`. `_check_candidate`(:68)에서 `candidate.get("kind") == "cell_job"`이면 `check_cell_job_candidate`로 넘긴다. 그 경우에만 상한이 64 KiB다. `finalize_resolution`(:584)은 `action_kind` 인자를 받는다(`PICK_PLACE` 기본, `CELL_JOB`). 순증가를 30줄 안으로 둔다(800 경계).
- 바꾼다: `mission_routes.py` `_resolve_candidate`(:83). `kind == "cell_job"`이면 결과 키를 `{plan, goal_predicate, resources, steps}`로 검사하는 별도 분기를 탄다. 카메라 증거 검사는 PICK_PLACE에만 적용한다.
- 바꾼다: `mission_store.create_proposal`(:224). `CELL_JOB`이면 머리 행과 함께 `mission_steps.insert_job_steps(...)`를 **같은 트랜잭션**에서 실행한다.
- 시험(새로): `src/site/fleet/test/test_cell_job_resolver.py`. fixture는 `src/site/cell/examples/omx_sim/`와 Task 11용 축소 레시피다.

**TDD 사례:**
- 정상 Job → transfer 수 = 데모 레시피 box·sheet transfer 수, 순서 = `compile_job` 순서.
- Step 하나를 바꾼 후보 → `CELL_JOB_MISMATCH`.
- recipe 해시 한 글자 변경 → `CELL_JOB_HASH_MISMATCH`.
- pick 하나 삭제 → `CELL_JOB_UNPAIRED`.
- 65 KiB → `CELL_JOB_TOO_LARGE`.
- `rosy_cell.compiler.carry_z`를 monkeypatch한 sentinel 값이 body `carry_z`에 그대로 나타난다(재구현이 없다는 증거).
- `/admit` 재해석(`mission_routes.py:373-379`)이 같은 입력에서 `_stable_resolution`이 같다(결정적).

**커밋:** `feat(fleet): cell_job candidate recompiled with rosy_cell into ordered CELL_TRANSFER steps (D-403 §3-4)`

---

## Task 7b — 서비스 principal 제안 + 다른 운영자 승인 (S, 호스트)

**변경**
- `site_auth.py:46`, `site_users.py:11`: 역할 집합에 `"cell-service"`를 더한다.
- `build_role_guards`(:157)에 `require_proposer`를 더한다(`operator` 또는 `cell-service`). `require_operator`와 `require_named_operator`는 그대로다. 그래서 `cell-service`는 승인할 수 없다.
- `mission_routes.py`:
  - `POST /api/fleet/proposals`(:244)와 `/resolve`(:276)는 `Depends(require_proposer)`를 쓴다. 제안·Mission 읽기(:268, :318, :334)는 지금처럼 자기 principal 범위다.
  - `/admit`(:364-368)를 다음처럼 바꾼다.
    ```python
    proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
    if proposal is None:
        candidate = proposal_store.get(mission_id)
        if candidate is not None and candidate["principal_id"] in admit_proposals_from:
            proposal = candidate
    if proposal is None:
        raise HTTPException(404, {"code": "MISSION_NOT_FOUND"})
    if proposal["principal_id"] in admit_proposals_from and proposal["principal_id"] == principal.principal_id:
        raise HTTPException(409, {"code": "PROPOSER_CANNOT_ADMIT"})
    ```
- `install_mission_routes`와 `create_app`에 `admit_proposals_from: frozenset[str] = frozenset()` 인자를 더한다. 값은 `site_users`의 `cell-service` principal id 집합과 같아야 한다. 다르면 `create_app`이 `ValueError`를 낸다.

**TDD** (`src/site/fleet/test/test_mission_api.py` 확장. 기존 app/client fixture를 쓴다)
1. `cell-service`가 제안·해석 → 이름 있는 `operator`가 승인 → 200, `mission.status == "READY"`, 감사 actor = 운영자.
2. `cell-service`가 `/admit` → 403 `FORBIDDEN`.
3. 운영자 A의 제안을 운영자 B가 `/admit` → 404(기존 동작 유지).
4. 허용 목록 principal이 자기 제안을 승인(역할을 operator로 바꾼 구성) → 409 `PROPOSER_CANNOT_ADMIT`.
5. `cell-service`가 `GET /api/fleet/missions/{other}` → 404.

**커밋:** `feat(fleet): a site service principal proposes cell jobs and a different named operator admits them (D-403 §3)`

---

## Task 8a — Job Step 하달기 + `deployment_profile` 게이트 (L, 호스트)

**변경**
- `app.py` `create_app`:
  - 인자 `deployment_profile: str = "production"`, `simulation_instances: frozenset[str] = frozenset()`을 더한다.
  - `enable_mission_dispatcher=True`이면 `deployment_profile == "simulation"`이고 `set(configured_omx.values()) <= simulation_instances`여야 한다. 아니면 `ValueError("Mission dispatch is open only in the simulation profile (D-330 §2, D-403 §7)")`.
  - 기존 하달기 시험(`test_mission_dispatcher.py`, `test_omx_fleet_ros_actionserver.py`, `test_fleet_omx_action_identity_contract.py`)도 `deployment_profile="simulation"`을 넘기도록 고친다. D-403 §7은 모든 하달에 적용된다.
- `mission_dispatcher.py`:
  - `dispatch_next`는 PICK_PLACE 경로를 그대로 두고 CELL_JOB 분기를 더한다. 300줄을 넘으면 `fleet/server/job_step_dispatch.py`로 분리한다.
  - 진행 조건(D-403 §5):
    - Step k를 `READY`로 올리는 조건: k = 0이거나 Step k−1이 `GOAL_CONFIRMED`이고, Job 머리가 `RUNNING`/`READY`이며 `HOLD`가 아니다.
    - 작업대마다 진행 중 Step은 하나다(`RUNNING`이거나 `reconciliation_pending`이면 다른 Step을 만들지 않는다).
    - grant의 `authority_epoch`·`dispatch_generation`은 **승인 때 머리 행에 기록된 값**을 쓴다. 제출 직전 `dispatch_control()`(:101)은 그 값과 같고 `dispatch_enabled`여야 한다. 아니면 Step과 Job을 `HOLD`(`FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT`).
    - `LocalActionRejected` → Step `FAILED`(reason `LOCAL_ACTION_REJECTED`), Job `HOLD`(§1-5).
    - 기타 예외 → Step `UNKNOWN`(reconciliation), Job `HOLD`. 재하달하지 않는다.
    - 수신 확인(`_verified_receipt`)은 4 phase 규칙을 CELL_TRANSFER에도 적용한다.
  - Step `ACTION_SUCCEEDED` 뒤 목표 증거가 오면(8b) `GOAL_CONFIRMED`가 되고 다음 Step이 열린다. 증거 없이 `goal_evidence_timeout_s`가 지나면 Step·Job `HOLD`(D-328 §4).
  - 마지막 Step이 `GOAL_CONFIRMED`이면 Job 머리 `GOAL_CONFIRMED`. `pallet_done`은 Fleet 원장 이벤트 `PALLET_DONE`으로만 남긴다(D-403 §4).
- `task_dispatch_routes.py`: `trip_stop_latch` 경로(:253, intent :87/:100)가 Job 머리를 **바꾸지 않는다**. 하달기가 다음 tick에서 fence 불일치를 보고 HOLD한다. 생산자는 세대만 올린다(D-330 §2).
- `rearm_dispatch`(:332)는 HOLD Job을 다시 열지 않는다. 다시 하려면 새 세대에서 운영자가 다시 승인해야 한다(D-403 §6). C4는 "Job HOLD에서 자동 재개 없음"까지만 만든다. 재승인 절차는 §7 Q5다.

**TDD** (`src/site/fleet/test/test_job_step_dispatch.py`. 가짜 transport는 기존 `test_mission_dispatcher.py` 것을 쓴다)
1. 3-transfer Job: transport 제출 순서 = step_index 0, 1, 2. Step 0 `ACTION_SUCCEEDED` 동안 Step 1 미제출. 증거 확인 뒤 제출.
2. 같은 작업대 두 Job: 두 번째 Job은 첫 Job이 끝날 때까지 `READY`에 머무른다(claim 충돌로 승인 거절 → 409, D-330 §1).
3. `create_app(deployment_profile="production", enable_mission_dispatcher=True, ...)` → `ValueError`. simulation이어도 `simulation_instances`에 없는 인스턴스면 `ValueError`.
4. `LocalActionRejected("GRANT_REJECTED")` → Step `FAILED`, Job `HOLD`, 다음 Step 미제출.
5. grant digest = `action_grant_digest(grant)`, `action_kind == "CELL_TRANSFER"`, transport가 v2로 보냈다.

**커밋:** `feat(fleet): ordered CELL_TRANSFER step dispatch behind the simulation deployment profile (D-403 §5, §7)`

---

## Task 8b — `item_at_pose` / `sim_model_pose` 목표 증거 (M, 호스트)

**변경**
- `goal_evidence.py`: `GoalPredicate.from_mapping`이 두 모양을 받는다.
  - 기존: `{predicate_id, condition: object_in_destination, object_id, destination_id, evidence_source: camera_observation}`. 바꾸지 않는다.
  - 새로: `{predicate_id, condition: item_at_pose, item_id: "<job>:<k>", target: {x,y,z,yaw}, tolerance: {xy_m, z_m, yaw_rad, yaw_period_rad}, evidence_source: sim_model_pose}`. `yaw_period_rad`는 대칭 물건의 yaw 동치 주기다. 상자는 π, C3b의 "π 법"이다.
- 새 `ItemPoseEvidence`: `{predicate_id, item_id, evidence_source, evidence_id, evidence_revision, producer_id, observation_id, observation_digest, model_name, pose: {x,y,z,roll,pitch,yaw}, action_id, attempt_id, gripper_state, gripper_evidence_id, gripper_evidence_revision, gripper_observed_at, observed_at}`. **`satisfied` 필드가 없다.** Fleet이 `verify_item_at_pose(predicate, evidence, now, max_age_s)`로 판정한다. 판정 항목: xy 거리, |dz|, yaw 차의 주기 나머지, 기울기 |roll|,|pitch| ≤ tolerance, `gripper_state == "OPEN"`, 신선도. 생산자가 만족 여부를 정하면 독립 증거가 아니기 때문이다(D-328 §4).
- `goal_evidence_registry.py:22`: `_EVIDENCE_SOURCES`에 `"sim_model_pose"`를 더한다. `load_goal_evidence_registry(path, *, environ=None, deployment_profile)`가 `sim_model_pose` 생산자 행을 `simulation`일 때만 받는다(D-403 §5).
- `goal_evidence_service.py`/`goal_evidence_store.py`: Step 단위로 저장·확인한다(`mission_steps.confirm_step_goal`). 엔드포인트 `POST /api/fleet/goal-evidence`(:218)와 `X-Goal-Evidence-Token`은 그대로다. 본문 모양으로 갈린다.
- 허용오차의 출처는 Fleet 구성 `cell_job.goal_tolerance`이고 기본값이 없다(§7 Q4). Task 11 초기값은 C3b 판정과 같은 xy 5 mm, z 2 mm, yaw 0.05 rad다.
- 새로 만든다: `deploy/robot/omx/sim_pose_evidence_producer.py`. ROS-SIM 생산자다.
  - `gz model -m <block> -p`를 읽는다(재시도 포함, C3 run5 교훈). 그리퍼 열림은 `/joint_states`에서 `gripper_contract` 기준으로 읽는다.
  - 자기 토큰으로 `POST /api/fleet/goal-evidence`를 보낸다.
  - 이 생산자는 owner 프로세스가 아니다. 별도 프로세스이고 owner를 import하지 않는다.

**TDD** (`src/site/fleet/test/test_goal_evidence.py` 확장)
```python
def test_item_at_pose_is_judged_by_fleet_not_by_the_producer():
    predicate = GoalPredicate.from_mapping({
        "predicate_id": "p-1", "condition": "item_at_pose", "item_id": "job-1:0",
        "target": {"x": 0.1525, "y": 0.0275, "z": 0.015, "yaw": 0.0},
        "tolerance": {"xy_m": 0.005, "z_m": 0.002, "yaw_rad": 0.05, "yaw_period_rad": math.pi},
        "evidence_source": "sim_model_pose"})
    near = _pose_evidence(x=0.1528, y=0.0275, z=0.015, yaw=math.pi + 0.001)   # pi-symmetric box
    far = _pose_evidence(x=0.1077, y=0.0565, z=0.0197, roll=-1.571)          # C3 run8 lying block
    assert verify_item_at_pose(predicate, near, now=NOW, max_age_s=5.0) is True
    assert verify_item_at_pose(predicate, far, now=NOW, max_age_s=5.0) is False
    with pytest.raises(GoalEvidenceError):
        ItemPoseEvidence.from_mapping(dict(near.to_dict(), satisfied=True))

def test_sim_model_pose_producers_are_refused_outside_simulation(tmp_path):
    path = _registry_file(tmp_path, evidence_source="sim_model_pose")
    with pytest.raises(GoalEvidenceRegistryError):
        load_goal_evidence_registry(path, deployment_profile="production")
    assert load_goal_evidence_registry(path, deployment_profile="simulation")
```
추가 사례:
- 증거 없이 `goal_evidence_timeout_s` 경과 → Step `HOLD`(`GOAL_EVIDENCE_MISSING`), 다음 Step 미제출.
- `gripper_state != "OPEN"` → 거절.
- 다른 Step의 `item_id` → 거절.

**커밋:** `feat(fleet): per-step item_at_pose goal predicate with sim_model_pose evidence judged by Fleet (D-403 §5)`

---

## Task 9 — 정지 세대 producer/consumer 시험, 호스트 층 (L, 호스트)

D-403 §7의 (a)–(i)를 **같은 이름**으로 두 층에 둔다. 호스트 층(이 Task)은 실제 Fleet 저장소·하달기·`ActionApi`·`ActionRunner`·`LocalStopController`·`AcceptedCellStore`·`cell_transfer_factory`를 쓴다. 가짜는 둘뿐이다: ROS 쪽 `PhaseGoalPort`/readback, 그리고 UDS 대신 `ActionApi.dispatch(request, peer_uid=FLEET_UID)`를 부르는 in-process transport(`test_fleet_omx_action_identity_contract.py`와 같은 방식). 여기서 통과해도 D-330 §2를 열지 않는다. 여는 조건은 Task 10이다.

**파일**
- 새로 만든다: `test/test_cell_job_stop_generation.py`(저장소 루트, fleet·omx_adapter·rosy_cell을 함께 쓴다).
- 새로 만든다: `test/cell_job_harness.py`. Fleet app + owner 조립을 한 함수로 만들고, 가짜 port에 "phase k에서 멈춤", "수락 지연", "readback 값"을 지시한다.

| 시험 | 내용 | 단언 |
|---|---|---|
| (a) `test_a_stop_between_steps` | Step 0 `GOAL_CONFIRMED` 뒤, Step 1 제출 전에 `POST /api/fleet/estop` | Step 1 미제출(제출 수 1). Job `HOLD`. owner 래치 `LOCAL_LATCHED`. |
| (b) `test_b_stop_mid_phase` | transfer phase 수락 뒤 estop | owner가 **그 phase UUID 하나만** 취소(`cancel_goal` 인자 == 활성 UUID). release 미제출. Action `HOLD`/`STOP_GENERATION_FENCED`. |
| (c) `test_c_late_acceptance_after_stop` | phase 제출 → estop → 그 뒤 `GOAL_ACCEPTED` 도착 | runner가 늦은 수락을 취소하고 HOLD(D-386 §2). 다음 phase 없음. |
| (d) `test_d_old_generation_grant_after_rearm` | estop → rearm(gen+1) → 옛 grant 재전송 | `GRANT_REJECTED` 403. `omx_actions` 새 행 0. |
| (e) `test_e_fleet_restart_mid_job` | Step 1 RUNNING 중 Fleet app 재생성(같은 DB) | `close_dispatch_for_startup` 뒤 epoch 증가. Step 1 재제출 없음. Job `HOLD` 또는 reconciliation. 제출 수 불변. |
| (f) `test_f_owner_restart` | Step RUNNING 중 owner 재조립(같은 SQLite) | 컨트롤러 `UNKNOWN/STARTUP_STOP_UNCONFIRMED`. Action `UNKNOWN`/`HOLD`. 새 grant 403. Fleet Step `UNKNOWN`. |
| (g) `test_g_audit_db_unwritable_still_fans_out` | `begin_api_audit`가 예외를 던지게 함 → estop | `StopLocal`이 owner에 도착(래치). 응답에 감사 실패 표시. 일반 명령은 503(D-330 §3). |
| (h) `test_h_uds_loss` | transport가 `ConnectionError`를 던짐(제출 중·조회 중 각각) | Step `UNKNOWN`. 하달기가 `dispatch_control()`을 다시 읽음. 재제출 0. 연결이 돌아오면 `GetAction`으로만 조정. |
| (i) `test_i_item_holding_unknown_after_stop` | grasp 뒤 estop. readback이 "held"와 "unknown" 두 경우 | release·재파지 자동 제출 0. Job `HOLD` reason `ITEM_STATE_UNRECONCILED`. rearm 뒤에도 재하달 0. 운영자 대조 전까지 같은 Job 재승인 거절. |

**기대:** 9개 모두 통과한다. 각 시험은 1초 안에 끝나야 한다(교착 감시). 실행 명령:
```bash
python -m pytest test/test_cell_job_stop_generation.py -q
```

**커밋:** `test(cell): D-403 §7 stop-generation producer/consumer suite (a)-(i), host layer`

---

## Task 10 — 정지 세대 시험 (a)–(i), ROS-SIM 층 (L) — **비어 있는 WSL 슬롯 필요**

**전제:** D-403 Accepted 여부를 사용자에게 확인한다(§7 Q1). WSL에서 다른 세션의 Gazebo가 돌고 있지 않아야 한다. C3에서는 겹치면 RTF가 0.3까지 떨어졌다. 이미지 재빌드가 필요하면 사용자에게 먼저 알린다(부모 계획 운영 규칙).

**구성(고정 이미지·커밋):**
- 이미지: C3b와 같은 `rosy-omx-pilot:recording-local` `sha256:faeb86d6…efb2`. 바꾸면 ID를 기록한다.
- 컨테이너: `rosy-cell-c4-sim`, `--network none`, `ROS_DOMAIN_ID=77`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, 저장소 read-only.
- 컨테이너 안에서 두 프로세스를 띄운다.
  - `run_cell_sim.sh`: vendor follower와 월드 `omx_cell_workcell_sim_aid.sdf`.
  - `run_cell_owner.sh`(Task 5): owner 하나.
- socket: `X:\DevTemp\rosy-cell-c4\run\omx_cell_sim_01\`을 `/run/rosy/omx/omx_cell_sim_01/`로 bind-mount한다. Fleet은 WSL Ubuntu(같은 커널)에서 Python으로 실행한다.
- Fleet UID: owner 로그에 찍힌 `SO_PEERCRED` UID를 `ROSY_FLEET_UID`로 고정한다(D-403 §8).

**파일**
- 새로 만든다: `deploy/robot/omx/probe_cell_stop_suite.py`. Task 9의 9개 시나리오를 실제 owner와 실제 ROS goal에 대해 실행한다. 정지는 Fleet `POST /api/fleet/estop`으로 주입한다.
  - (b)(c)(i)는 Gazebo 동작 중 주입한다. (c)는 수락 직전 주입 창을 `--inject-at accept-pending`으로 잡는다.
  - (e)(f)는 프로세스를 `kill -TERM` 뒤 재시작한다.
  - (g)는 Fleet DB 파일을 read-only로 바꾼다.
  - (h)는 socket 파일을 rename한 뒤 되돌린다.
  - (i)는 sim aid가 붙은 상태와 그리퍼 readback을 기록한다.
- 증거: `docs/validation/rosy-cell-c4-stop-generation-<date>/README.md`. 담는 것: 이미지 ID, 커밋, 월드 sha256, profile·kinematics revision, 시나리오별 Fleet 원장·owner journal·`omx_local_stop` 행·ROS UUID·취소 응답, RTF.

**명령(예):**
```powershell
docker run -d --rm --name rosy-cell-c4-sim --network none `
  --mount "type=bind,source=$wt,target=/repo,readonly" `
  --mount "type=bind,source=X:\DevTemp\rosy-cell-c4,target=/scratch" `
  --mount "type=bind,source=X:\DevTemp\rosy-cell-c4\run,target=/run/rosy/omx" `
  -e OMX_CELL_WORLD=/repo/src/sim/gz_sim/worlds/omx_cell_workcell_sim_aid `
  rosy-omx-pilot:recording-local bash /repo/deploy/robot/omx/run_cell_sim.sh
docker exec -d rosy-cell-c4-sim bash /repo/deploy/robot/omx/run_cell_owner.sh
wsl -e bash -lc 'cd "<worktree>"; python3 deploy/robot/omx/probe_cell_stop_suite.py --socket-root /mnt/x/DevTemp/rosy-cell-c4/run --out /mnt/x/DevTemp/rosy-cell-c4/stop-suite'
```
**기대:** 9/9 통과. 그 커밋·이미지에서 D-330 §2 개방 조건이 충족된다(simulation 한정). 하나라도 실패하면 Task 11로 가지 않는다.

**커밋:** `test(cell): D-403 §7 stop-generation suite on the pinned ROS-SIM image (evidence)`

---

## Task 11 — ROS-SIM 통합: 2–3 transfer Job (L) — **비어 있는 WSL 슬롯 필요**

**목적:** C6의 선행이다. 정식 경로 Rosy Cell 레시피 → Fleet 제안(서비스 principal) → 다른 운영자 승인 → 하달기 → UDS → owner → `/arm_controller`로 transfer 2–3개짜리 Job 하나를 실행한다. C6(2층, 슬립시트, 팔레트 2개 전체)는 주장하지 않는다.

**입력**
- 축소 레시피: `src/site/cell/examples/omx_sim_c4/recipe.yaml`. 셀은 `omx_sim/cell.yaml`을 그대로 쓴다.
  - 팔레트 1개, 1층, 블록 2–3개, 슬립시트 없음. 슬립시트는 C3b 기준 집을 수 없다.
  - 배치는 C3b 이웃 간섭(마지막 배치가 이웃을 24.9 mm 밀었음)을 피하도록 고른다. 3개가 간섭하면 2개로 줄이고 증거에 적는다(§7 Q6).
  - 호스트 시험 `test/test_cell_omx_sim_layout_contract.py` 방식으로 모든 transfer가 planner 거절 없이 계획되는지 먼저 확인한다.
- 장치 셀 수락: 시험 하네스가 seat를 잡고 `PUT /cell`, `PUT /recipe`를 보낸 뒤 seat를 반납한다(D-404 §6). C5 마법사는 아직 없다.
- 인피드 재적재: transfer마다 다음 블록을 인피드에 spawn한다. 동작이 아니라 sim 준비 단계다(C3b와 같음).

**파일**
- 새로 만든다: `deploy/robot/omx/run_c4_fleet_sim.py`. WSL에서 `create_app(deployment_profile="simulation", simulation_instances={"omx_cell_sim_01"}, enable_mission_dispatcher=True, admit_proposals_from={"rosy-cell-svc"}, site_users=..., goal_evidence_service=...)`를 uvicorn으로 띄운다. 운영 `cli.py`에는 하달기를 배선하지 않는다(범위 밖, §7 Q7).
- 새로 만든다: `deploy/robot/omx/probe_c4_job.py`. 하는 일:
  1. `cell-service` 토큰으로 `POST /api/fleet/proposals`(kind `cell_job`) → `/resolve`.
  2. 운영자 토큰으로 `/admit`.
  3. Mission 이벤트를 폴링한다.
  4. Step마다 `sim_pose_evidence_producer.py`를 실행한다.
  5. 끝나면 블록 최종 포즈와 오차를 기록한다.
- 증거: `docs/validation/rosy-cell-c4-fleet-route-<date>/README.md`. 담는 것: 레시피·셀 해시, Fleet 원장(머리 + Step 표 + 이벤트), grant digest, OMX journal(phase·UUID·feedback 수·`ACTION_WORKFLOW_COMPLETED`), 그리퍼 readback, 블록 `sim_model_pose`와 오차, RTF, SIM AID 표시, 정지 시험 증거 링크.

**판정:** 각 transfer가 xy 5 mm, z 2 mm, yaw 0.05 rad 안이고, Fleet Step이 모두 `GOAL_CONFIRMED`, Job 머리가 `GOAL_CONFIRMED`, owner HOLD 0, 이웃 블록 이동 ≤ 2 mm이면 **ROS-SIM C4 통과**다. 넘으면 HOLD로 기록하고 원인을 적는다. 성공으로 적지 않는다.

**커밋:** `test(cell): first Rosy Cell job through Fleet -> UDS -> owner in Gazebo (C4 ROS-SIM, C6 precursor)`

---

## Task 12 — 계약 문서·ADR 보강·기록 마감 (S, 호스트)

- `docs/reference/ROSY API & Protocol Reference.md` §10.12: `CellTransferGrant` 필드 표, v2 사용, 오류 코드(`GRANT_REJECTED` 사유, `CELL_JOB_*`, `PROPOSER_CANNOT_ADMIT`), `item_at_pose`·`sim_model_pose` 증거 모양, 역할 `cell-service`, `PUT/GET /cell`·`/recipe`를 적는다. 버전은 쓰기 직전에 main의 최신 번호 다음으로 정한다. main은 이미 v1.77 이상이다.
- ADR 보강 문단(ADR 번호는 새로 받지 않는다):
  - D-403 §2: grasp 기하 선언 + 장치 대조, `tol_m` 출처, `pallet`/`layer` 원장 전용.
  - D-403 §9: 거절 = Step `FAILED` + Job `HOLD`.
  - D-404 §6: `PUT/GET /recipe`.
  - D-402 §3: (a)–(d) 완료 표시.
  - D-330·D-336 머리 개정 문단은 D-403 Accepted 전까지 그대로 둔다.
- 모듈 기록: `src/site/fleet/{logs,progress}.md`, `src/products/omx/adapter/{logs,progress}.md`, `src/site/cell/{logs,progress}.md`. `logs.md` minor 8 항목을 "해결: <커밋>"으로 닫는다. 하네스 generate, lint 0, known_failures 확인.
- 부모 계획 C4 줄에 결과 링크를 단다.

**커밋:** `docs(cell): C4 wire contract in API Ref, ADR supplements, module records`

---

## 3. 시험 층 정리

| 층 | 어디서 | 무엇 |
|---|---|---|
| SOURCE(호스트) | Windows `python -m pytest` | Task 1–9 전부. D-403 수용 기준 SOURCE 7항목(합집합·digest 불변, 재컴파일 불일치, 서비스 제안 + 다른 운영자 승인, `item_at_pose`, 셀 해시 거절, seat 상호 배제, 비시뮬 하달기 거절)이 모두 여기에 있다. |
| LOCAL rclpy | WSL Jazzy, Gazebo 없음 | Task 0·4의 반복 루프(`test_omx_ros_runtime.py`, `test_omx_fleet_ros_actionserver.py`). |
| ROS-SIM | WSL + 고정 이미지 + Gazebo | Task 10(§7 (a)–(i)), Task 11(2–3 transfer Job). |
| DEVICE / FIELD | — | 이 계획으로 승격하지 않는다. |

## 4. 위험

1. **잠금 순서.** 고정할 순서는 "어느 lock도 쥔 채로 상대 쪽 공개 메서드를 부르지 않는다"이다. 취소 외에 새로 생기는 교차 호출도 같은 규칙을 따른다: sequencer → runner `advance()` → `goal_port.submit` → owner `submit`. sequencer는 runner lock 밖의 전용 스레드에서 부른다. `RecordingLock` 시험(Task 4)을 sequencer 경로에도 적용한다. `LocalStopController.run_if_open`은 `_lock`을 쥔 채 operation을 실행한다(`local_stop.py:226`). operation 안에서 owner lock을 잡는 것은 허용 방향(stop → owner)으로 정하고, owner·runner가 stop lock을 잡지 않음을 시험한다.
2. **기존 Fleet DB 이관.** 운영 사이트 DB를 재구성하는 첫 이관이다. 완화책:
   - 백업 사본을 만든다.
   - 진행 중 Action이 있으면 거절한다.
   - `foreign_key_check`와 행 수를 확인한다.
   - 단일 트랜잭션 + 롤백이다.
   - 마커로 한 번만 실행한다.
   - 옛 DDL을 고정한 시험을 둔다.
   
   남는 위험은 두 가지다. `foreign_keys=OFF`는 트랜잭션 안에서 바꿀 수 없으므로 연결 단위로 다룬다. 그리고 다른 저장소가 같은 파일에 동시에 연결해 있을 수 있다. `BEGIN IMMEDIATE`와 busy timeout 5 s로 막고, 기동 순서상 `MissionStore`가 가장 먼저 열린다는 것을 `create_app` 시험으로 고정한다.
3. **Fleet 동시 작업.** main `git log --oneline -15 -- src/site/fleet`(2026-10-02)은 오늘 활발하다.
   - **D-407 stuck board**(`feat/d407-console-stuck-decisions`, `line_stuck.py`, `console_routes.py`, `app.py`, API Ref v1.76–1.77)
   - **D-395 localization**(`fix/d395-s1-fleet-anchored-peers`, `feat/d395-p2-*`, `localization_service.py`, `app.py`)
   
   C4가 바꾸는 `app.py create_app` 시그니처와 API Ref 버전 번호가 겹친다. Task 8a 직전에 main을 다시 merge하고, API Ref 버전은 Task 12에서 쓰기 직전에 정한다.
   - OMX 쪽에서는 "OMX dispatch safety work"(`b0979ad60`·`7735c307e`·`11ae6e703`)가 이미 main에 있다(Task 0).
   - 시작할 때 `ListAgents`로 같은 영역 세션을 확인한다.
4. **WSL 일정.** Task 10·11은 WSL과 Docker 이미지를 독점해야 한다. 다른 세션의 Gazebo와 겹치면 RTF가 0.3–0.4로 떨어진다. owner의 sim-time 기준과 4배 wall 상한은 견디지만, 증거 RTF가 나빠지고 정지 주입 창(c)이 흔들린다. 슬롯이 비면 두 Task를 연달아 실행하고, 실행 전 `wsl -e bash -lc 'pgrep -a gz; docker ps'`로 확인한다.
5. **같은 커널 조건.** Fleet을 Windows 호스트에서 돌리면 UDS가 성립하지 않는다(D-336 §1). Fleet은 반드시 WSL Ubuntu에서 실행한다. Docker Desktop의 bind-mount socket이 WSL 쪽 `SO_PEERCRED`를 그대로 넘기는지는 Task 10 첫 단계에서 실측한다. 실패하면 Fleet도 같은 컨테이너에 넣는다(§7 Q8).
6. **크기 예산.** `schemas.py`와 `action_store.py`는 증가 0이다. `proposal_store.py`는 800, `pick_place_runner.py`는 600, fleet 패키지는 재판정 대상이다. 넘으면 새 모듈로 나누고 크기 판정 문구를 갱신한다.
7. **sim aid 의존.** Task 11 배치는 C3b와 같은 SIM AID에 기댄다. 운반 중 낙하는 시험되지 않는다. 증거에 표시한다.

## 5. 성공 기준

- Task 1–9 호스트 시험과 architecture 시험이 통과하고 lint가 0이다.
- PICK_PLACE golden digest `c847300c…4db8`가 그대로다.
- Task 10: §7 (a)–(i) 9/9 ROS-SIM 통과. 증거 README가 있다.
- Task 11: 2–3 transfer Job이 정식 경로로 `GOAL_CONFIRMED`이고 판정 허용오차 안이다. 아니면 HOLD로 정직하게 기록한다.
- probe의 C4 대역 셋이 사라졌다: PICK_PLACE 봉투 + `action_kind` 바꿔치기, 항상 열린 fence, 로컬 lambda 수락.

## 6. 범위 밖

C5 서버·화면, C6 전체 데모, 슬립시트 파지 방법, 충돌 장면과 이웃 간섭 검사(D-402 §7), 운영 `cli.py` 하달기 배선, 호스트 간 하달(D-336 §5), 실물 OMX, MoveIt.

## 7. 열린 질문

1. **D-403 승격.** Task 10·11에서 하달기를 실제로 여는 것은 D-403 Accepted 뒤에만 한다(D-330·D-336 개정이 그때 효력을 가짐). 그 전에 Proposed 상태로 시험만 실행할지 사용자가 정한다. 기본값은 "시험 실행은 하고, 개방 주장은 Accepted 뒤에 한다"이다.
2. **C3 착지 순서.** C3 브랜치를 main에 먼저 넣을지, C4가 main을 merge하며 start-state 충돌을 대신 풀지 정한다. 충돌을 푸는 쪽이 C3 리뷰 결과를 바꿀 수 있다.
3. **`tol_m`의 출처.** 후보: Fleet 구성 값, `cell.yaml` 필드(셀 해시가 바뀜), `rosy_cell` 상수. probe는 0.001, 시험은 1e-6을 쓴다. 이 값은 검증 결과만 바꾸고 Step 출력은 바꾸지 않는다고 가정한다. Task 7a 첫 시험으로 확인한다.
4. **목표 허용오차의 출처.** Fleet 구성(제안), 레시피, 셀 중 어디에 둘지 정한다. 기본값을 두지 않는다(D-401 §6 규칙).
5. **정지 뒤 재개 절차.** Job HOLD 뒤 운영자가 물건 상태를 대조하고(D-328 §5) 남은 Step을 다시 승인하는 API가 필요하다. 기존 `supersedes_mission_id`로 새 Job 제안을 받을지, 같은 Job을 새 세대로 재승인할지 정한다. C4는 "자동 재개 없음"까지만 만든다.
6. **통합 Job 크기.** 이웃 간섭 때문에 3 transfer가 실패하면 2로 줄여도 되는지 정한다. 2층·슬립시트·팔레트 2개는 C6 몫이다.
7. **운영 CLI.** `cli.py`에 `--deployment-profile`을 지금 더할지, C6까지 sim 전용 런처로 둘지 정한다.
8. **UDS 피어 UID.** Docker Desktop bind-mount socket에서 `SO_PEERCRED`가 WSL 프로세스의 UID를 정확히 주는지 실측해야 한다. 안 되면 Fleet을 owner 컨테이너 안에서 실행한다. 이 경우도 D-403 §8의 "같은 커널" 조건 안이다.
9. **목표 증거의 그리퍼 출처.** 이번 계획은 기존 `GoalEvidence` 모양대로 sim 생산자가 그리퍼 열림을 함께 보고한다. owner receipt의 release readback을 Fleet이 직접 쓰는 편이 출처 분리에 더 맞는지 정한다.
