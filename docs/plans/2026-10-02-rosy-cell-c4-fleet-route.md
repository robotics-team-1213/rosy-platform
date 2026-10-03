# Rosy Cell C4 — Fleet ↔ OMX Cell 경로 (`CELL_TRANSFER`), D-413 배치

**부모 계획:** [Rosy Cell 완성 계획](2026-10-01-rosy-cell-completion.md) C4. C6의 선행 단계다.

**배치 기준:** [D-413](../adr/D-413-platform-modules-integrations-apps-profiles.md)(Accepted)과 [플랫폼 이전 계획](2026-10-02-platform-architecture-v02-migration.md) Task 4·5를 따른다. 사용자 결정(2026-10-02)에 따라 **이 세션이 C4를 D-413 배치 안에서 구현한다.** D-413 Task 4/5 담당은 결과를 검증만 한다. 함께 볼 문서는 [설계 v0.2](../reference/ROSY_Platform_Architecture_Design_v0.2.md) §2·§4.3·§5·§6.1·§7·§15.1, `tools/harness/platform_dependencies.yaml`, `test/architecture/test_platform_dependency_boundaries.py`다.

**계약 근거:** [D-403](../adr/D-403-fleet-cell-job-route-cell-transfer.md)(C4 계약 전체)과 다음 결정들이다. [D-402](../adr/D-402-omx-motion-planner-v1-analytic-top-down-ik.md) §3·§7·§8·C3b 보강, [D-404](../adr/D-404-omx-setup-teaching-api-simulation-first.md) §6·§7, [D-330](../adr/D-330-fleet-action-admission-stop-and-recovery.md) §1·§2·Transition 2, [D-336](../adr/D-336-fleet-omx-local-ipc-boundary.md), [D-376](../adr/D-376-omx-pick-place-planning-and-execution-boundary.md), [D-328](../adr/D-328-model-proposed-missions-and-independent-goal-evidence.md) §4·§5, [D-12](../adr/D-12-mission-fleet.md).

**입력 증거:** 두 곳에서 넘어온 항목을 반영한다. [C3/C3b](../validation/rosy-cell-gazebo-c3-2026-10-02/README.md)의 "C4·C6로 넘길 것"과 `src/products/omx/adapter/logs.md` 2026-10-02 항목(완료 journal 이름, minor 8 잠금 순서, grant 봉투·stop fence 대역)이다.

**범위:** SOURCE 구현, 그리고 ROS-SIM 두 번(정지 세대 시험, 2–3 transfer Job 통합)이다. 다음은 포함하지 않는다: C5 화면, C6 전체 데모, D-413 Task 6(apps·설치 전환), 실물 OMX, 호스트 간 하달, DEVICE/FIELD.

---

## 0. 기준선 (2026-10-02 재확인)

### 0.1 브랜치

| 항목 | 값 |
|---|---|
| C4 브랜치 | `feat/rosy-cell-c4-fleet-route`. `feat/rosy-cell-c3-gazebo` `eac319582`를 충돌 없이 merge했다(`af8d41e56`). 그 앞 커밋은 첫 계획판 `a37efddc3`이다. |
| `eac319582` 내용 | C3/C3b와 main `aec1a6dc9`(D-413 palletizing 모듈, pl3 dispatch safety)를 담는다. `rosy_cell`은 `modules/processes/palletizing` 위의 facade다(`src/site/cell/rosy_cell/compiler.py` 1행 "Legacy import facade"). owner start-state는 main의 관절별 상한(`ArmCommandConfig.max_start_state_tolerances`, `command_owner.py:54`)과 C3b의 lock 안 바인딩(`start_state_window`)이 합쳐진 상태다. |
| main `2bec5d221` | `eac319582`보다 3커밋 앞선다. 그중 `985b00348`이 D-413 Task 4의 첫 단계다. `schemas.py:289-370`에 `CellTransferPose`·`CellTransferPayload`·`FleetCellTransferGrant`를 더했고, `modules/execution/src/rosy/execution/site/cell_submission.py`를 만들었다. 현재 main은 `13e6d5e45`이고 `2bec5d221`을 포함한다. |
| **진행 중 겹침** | `refactor/platform-cell-slice` `573a639cd`(session pl3, 16:09, main 미착지) "feat: add ordered Fleet Cell Job journal". 담은 것: `fleet/server/cell_job_store.py`(512줄, 표 `fleet_cell_jobs`·`fleet_cell_steps`·`fleet_cell_events`·`fleet_component_migrations`), `mission_routes.py`의 cell job 제안·승인 경로, 역할 `service`와 `require_proposer`(`site_auth.py`, `site_users.py`), `create_app(cell_job_compiler=...)`, `test_cell_job_api.py`, `test_cell_job_store.py`. 그 worktree(`.worktrees/platform-cell`)에는 커밋하지 않은 `src/products/omx/adapter/test/test_omx_action_api.py` 변경이 있다. **Task 0에서 인계를 확정하기 전에는 코드를 쓰지 않는다.** |
| PICK_PLACE golden digest | `c847300c318ada2b16e49833603f499ccf6fcd2a4d70f18f2bd2c2e8d7014db8`. `c07896afe`와 `573a639cd`의 schema에서 같은 고정 fixture로 실측했고 두 값이 같다. |

### 0.2 ADR 상태와 개방 게이트

D-402, D-403, D-404는 **Proposed**다. 따라서 D-330·D-336·D-376 머리에 적힌 시뮬레이션 한정 개정은 아직 효력이 없다. 세 개정 모두 "Accepted가 되면 효력이 생긴다"라고 적혀 있다.

> **게이트 G1 — 하달기 개방 전.** Fleet Mission 하달기를 켜는 실행(Task 12·13)은 다음 조건이 모두 갖춰진 뒤에만 한다.
> - 사용자 승인으로 D-402·D-403·D-404가 Accepted로 바뀐다.
> - 그에 따라 D-330·D-336·D-376 개정이 효력을 갖는다.
> - 그 커밋에서 Task 11(호스트 정지 시험)이 통과한다.
>
> G1 전에 할 수 있는 것: Task 0–11 전부. 여기에는 시험 안에서 `deployment_profile="simulation"`으로 하달기 객체를 만드는 단위 시험도 포함된다. G1 전에 하면 안 되는 것: 실제 owner를 향해 하달기를 켜는 실행과 "D-330 §2 개방" 주장.

### 0.3 의존 경계 (`tools/harness/platform_dependencies.yaml` 현재 내용)

- 등록된 component: `contracts`, `cell_process_compat`, `palletizing_process`, `fleet_site`, `omx_device_adapter`, `world_api`, `skill_api`, `execution_api`.
- 경계 규칙:
  - `fleet`은 `rosy_cell`·`omx_adapter`·`rclpy`를 import할 수 없다.
  - `rosy.execution.api`는 `rosy.processes.palletizing`을 import할 수 없다.
  - canary: `rosy.skills.manipulation`은 `rosy.execution`을 import할 수 없다.
- **`rosy.execution.site`는 아직 component로 등록돼 있지 않다.** `cell_submission.py`를 감시하는 규칙이 없다는 뜻이다. Task 2에서 등록한다.
- 첫 계획판의 "fleet → `rosy_cell` 의존 선언"은 이 경계에 어긋난다. 그래서 폐기한다.
- CI(`.github/workflows/ci.yml` "Build and install ROS-free platform API wheels")의 현재 동작:
  - `pip3 wheel --no-deps --no-build-isolation --wheel-dir /tmp/rosy-platform-wheelhouse modules/world modules/skills/api modules/execution modules/processes/palletizing`
  - 이어서 `--find-links`로 `rosy-world==0.1.0 rosy-skill-api==0.1.0 rosy-execution==0.1.0 rosy-palletizing==0.1.0`을 설치한다.
  - 둘 다 colcon 빌드 전에 돈다.
- `modules/execution/pyproject.toml`의 include는 `rosy.execution.api*`, `rosy.execution.site*`이고 의존은 `rosy-skill-api==0.1.0`이다.

---

## 1. D-403 항목의 D-413 위치

| D-403 항목 | 위치 | 현재 상태 | 이 계획의 Task |
|---|---|---|---|
| `CELL_TRANSFER` grant 필드(§2) | `src/contracts/foundation/core_common/protocol/schemas.py` `CellTransferPayload`/`FleetCellTransferGrant`(D-18 정본은 그대로 둔다). 공용 parse·digest는 새 `protocol/action_grants.py` | main에 있다. `grasp_depth_m`·`grasp_width_m`이 없다. OMX `action_api.py`는 아직 `FleetActionGrant`만 parse한다. Fleet transport `_version`(`local_action_transport.py:84`)은 CELL_TRANSFER에 v1을 쓴다. | 1 |
| Job 접수·재컴파일(§3) | `modules/execution/src/rosy/execution/site/cell_submission.py`(`compile_cell_submission`, `CellJobCompiler` port). 구현 adapter는 앱 조합인 `src/site/fleet/fleet/server/cell_compiler.py`이고 `rosy.processes.palletizing`과 `plan_bundle.compile_plan_bundle`을 쓴다. | port와 검증은 main에 있다. 운영 adapter는 없다(시험 `FixedCellCompiler`만 있다). | 2 |
| 서비스 principal 제안 / 다른 운영자 승인(§3) | `fleet/server/{site_auth,site_users,mission_routes}.py` | pl3 `573a639cd`에 있다(역할 `service`, `CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER`). | 0(인계), 2(검증 시험 보강) |
| 순서 있는 Step 원장(§4) | `fleet/server/cell_job_store.py`(별도 표. `fleet_missions` CHECK 재구성이 필요 없다) | pl3 `573a639cd`에 있다. | 0(인계) |
| Step 순차 하달·작업대당 1개·fence(§5) | 규칙은 `modules/execution/src/rosy/execution/site/cell_steps.py`(새로, 순수). 조합은 `fleet/server/mission_dispatcher.py` | 없다. | 3 |
| sim 전용 하달기(§7) | `fleet/server/app.py` `create_app(deployment_profile, simulation_instances)` + 장치 쪽 프로필 거절 | 없다. | 3, 8 |
| `item_at_pose`·`sim_model_pose` 목표 증거(§5) | 판정 규칙은 `modules/execution/src/rosy/execution/site/item_pose.py`(새로). 입력 경로는 `fleet/server/goal_evidence.py`·`goal_evidence_registry.py`. 생산자는 `deploy/robot/omx/sim_pose_evidence_producer.py` | 없다. | 4 |
| 조작 절차·gripper gate(§9, D-402 §8) | `modules/skills/manipulation/src/rosy/skills/manipulation/transfer.py` | 없다. 지금은 probe가 대신한다. | 5 |
| receipt 연결·종류 중립 완료 | `modules/execution/src/rosy/execution/local/receipts.py`. `action_store.py`는 이 규칙을 호출한다. | 없다. `PICK_PLACE_ACTION_COMPLETED`(`action_store.py:864`) | 6 |
| 제품 연결(IK·gripper·ROS) | `integrations/robots/omx/src/rosy/integrations/robots/omx/transfer_provider.py`. `AnalyticCellTransferPlanner`(`pose_plan.py:484`), `gripper_contract.py`, `PickPlaceRunner`/`RosArmPhaseGoalPort`를 감싼다. | 없다. | 7 |
| 장치 수락 셀·레시피 저장소, `capability_current`(§9, D-404 §6) | `src/products/omx/adapter/omx_adapter/cell_acceptance.py`(owner 로컬 journal, 제품 한계) | 없다. `capability_current`는 hook일 뿐이다(`action_runner.py:87`). | 8a |
| 정지 세대 소비자, 실제 fence, 잠금 순서(§6) | `omx_adapter/local_stop.py`, `command_owner.py`(`_cancel_active` :400), `pick_place_runner.py`(`_event_lock` :96) | probe `ProbeFence`(`probe_cell_transfer.py:222`)가 항상 열린 대역이다. | 8b |
| owner 프로세스 하나 = HTTP + UDS(§8) | 조립은 `integrations/robots/omx/.../cell_owner.py`(`build_cell_owner`), 진입점은 `deploy/robot/omx/run_cell_owner.py`/`.sh`. D-413 Task 6에서 `apps/agent/rosy_agent/omx_sim.py`로 옮긴다. | 운영 생성 지점이 없다(`UnixActionServer` :262는 시험에서만 만든다). | 9 |
| seat ↔ `CELL_TRANSFER` 상호 배제, `PUT/GET /cell`·`/recipe`(§10, D-404 §6·§7) | `omx_adapter/pilot_sim_api.py` + `omx_adapter/owner_exclusion.py` | 없다. | **10 (마지막, rosy-35 D-411 part C 착지 대기)** |
| 정지 세대 시험 (a)–(i)(§7) | 호스트: `test/test_cell_job_stop_generation.py`. ROS-SIM: `deploy/robot/omx/probe_cell_stop_suite.py` | 없다. | 11, 12 |

---

## 2. 작업 순서와 크기

크기: **S** ≤ 150줄(시험 포함), **M** 150–400줄, **L** 400–800줄. 각 Task는 리뷰 가능한 커밋 묶음 하나다. Task 1 뒤에는 Fleet 트랙(2–4)과 장치 트랙(5–9)이 서로 독립이다.

| # | Task | D-413 위치 | 환경 | 크기 |
|---|---|---|---|---|
| 0 | pl3 인계, main·`refactor/platform-cell-slice` merge | — | 호스트 | S |
| 1 | grant delta: grasp 기하, 공용 parse·digest, OMX parse, transport v2 | `core_common/protocol` | 호스트 | M |
| 2 | 컴파일러 port adapter + `rosy.execution.site` 경계 등록 + 승인 경계 시험 보강 | `execution/site`, Fleet 조합 | 호스트 | M |
| 3 | Step 순차 하달 규칙 + 하달기 조합 + `deployment_profile` 게이트 | `execution/site/cell_steps.py`, `fleet/server` | 호스트 | L |
| 4 | `item_at_pose` / `sim_model_pose` | `execution/site/item_pose.py`, `fleet/server/goal_evidence*` | 호스트 | M |
| 5 | 조작 Skill `transfer.py` + `rosy-skill-manipulation` wheel | `modules/skills/manipulation` | 호스트 | M |
| 6 | `execution/local/receipts.py` + 종류 중립 완료 journal | `modules/execution/local`, `omx_adapter/action_store.py` | 호스트 | M |
| 7 | `transfer_provider.py` + `rosy-integration-omx` wheel | `integrations/robots/omx` | 호스트 | M |
| 8a | 장치 수락 셀·레시피 저장소 + `capability_current` + 비시뮬 거절 | `omx_adapter` | 호스트 | M |
| 8b | 잠금 순서(minor 8) + 실제 stop fence | `omx_adapter` | 호스트 + WSL rclpy 짧게 | M |
| 9 | owner 프로세스 하나(HTTP + UDS) 조립 | `integrations/robots/omx/cell_owner.py`, `deploy/robot/omx` | 호스트 | L |
| 10 | seat 상호 배제, `PUT/GET /cell`·`/recipe` — **rosy-35 D-411 part C 착지 뒤** | `omx_adapter/pilot_sim_api.py`, `owner_exclusion.py` | 호스트 | M |
| 11 | 정지 세대 시험 (a)–(i), 호스트 층 | 저장소 루트 `test/` | 호스트 | L |
| **G1** | **D-402·D-403·D-404 Accepted(사용자 승인)** | — | — | — |
| 12 | 정지 세대 시험 (a)–(i), ROS-SIM — **WSL 슬롯 필요** | `deploy/robot/omx` | WSL + 이미지 + Gazebo | L |
| 13 | 2–3 transfer Job 통합 — **WSL 슬롯 필요** | `deploy/robot/omx` | WSL + Gazebo | L |
| 14 | API Ref·ADR 보강·모듈 기록 | docs | 호스트 | S |

**공통 규칙**
- 시작 전에 `git status --short --branch`와 `ListAgents`(Fleet·OMX·`modules/` 영역)를 확인한다.
- `rosy-land-on-main` 절차를 따르고 `git add <정확한 경로>`만 쓴다. stash·amend·reset은 쓰지 않는다.
- 커밋 메시지 끝에는 빈 줄 하나 뒤 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 둔다.
- **새 Python root는 처음 생기는 커밋에서** `tools/harness/platform_dependencies.yaml` component·boundary와 `test/architecture/test_platform_dependency_boundaries.py`에 등록한다(이전 계획 Task 2 규칙).
- **새 wheel은 처음 생기는 커밋에서** CI의 `pip3 wheel` 목록과 `--find-links` 설치 목록에 넣는다. 소비자 wheel보다 앞에 둔다.
- 공유 namespace 부모(`rosy/`, `rosy/skills/`, `rosy/integrations/`, `rosy/integrations/robots/`)에는 `__init__.py`를 두지 않는다(설계 §6.1).
- Task마다 해당 모듈 `logs.md`·`progress.md`를 쓰고 `python tools/harness/rosy_harness.py generate`를 돌린다.
- 호스트 시험은 이전 계획 Task 0의 suite별 분리 실행을 따른다.
  ```text
  python -B -X utf8 -m pytest src/site/cell/test -q -p no:cacheprovider
  python -B -X utf8 -m pytest src/site/fleet/test -q -p no:cacheprovider
  python -B -X utf8 -m pytest src/products/omx/adapter/test -q -p no:cacheprovider
  python -B -X utf8 -m pytest test/architecture -q -p no:cacheprovider
  python -B -X utf8 test/known_failures.py <해당 로그>
  ```
- wheel 검증은 이전 계획 Task 2의 PowerShell 절차를 따른다. `ROSY_SCRATCH`(X:) 아래 source 복사, wheelhouse, `--system-site-packages` venv를 쓰고, 저장소 PYTHONPATH는 쓰지 않는다.

---

## Task 0 — pl3 인계와 base 정렬 (S, 호스트)

1. pl3(`refactor/platform-cell-slice`) 세션과 아래 다섯 가지를 확인한다. 답이 없으면 coordinator에게 올리고 코드 Task를 시작하지 않는다.
   - pl3이 D-413 Task 4/5 구현을 멈추고 검증 역할로 바뀌는지.
   - `573a639cd`를 main에 먼저 넣을지, 아니면 이 브랜치가 그 브랜치를 merge할지.
   - 커밋하지 않은 `test_omx_action_api.py` 변경을 어떻게 처리할지(커밋, 폐기, 이 세션으로 이관 중 하나).
   - 역할 이름 `service`를 확정하는지. 첫 계획판의 `cell-service`는 버린다.
   - Cell Job 표 방식(`cell_job_store.py`의 별도 표)을 확정하는지. 첫 계획판의 `fleet_missions` 재구성안은 버린다.
2. `git merge main`을 한다. `13e6d5e45` 이상으로, `2bec5d221`을 포함한다. 그다음 합의대로 `refactor/platform-cell-slice`(또는 그것이 들어간 main)를 merge한다. 충돌이 나면 보고하고 멈춘다.
3. 기준선을 잡는다: 위 네 suite와 known-failures 비교, `python -B -X utf8 -m pytest src/site/fleet/test/test_cell_job_api.py src/site/fleet/test/test_cell_job_store.py test/test_platform_cell_submission.py -q -p no:cacheprovider`.

**출구:** 인계 기록을 `src/site/fleet/logs.md`에 남긴다. 새 실패는 0이다.
**커밋:** merge 커밋들, 그리고 `docs(cell): C4 handoff from D-413 Task 4 owner`.

---

## Task 1 — grant delta (M, 호스트)

**변경**

`schemas.py` `CellTransferPayload`:
- 필수 필드 `grasp_depth_m`(≥0, 유한)과 `grasp_width_m`(>0, 유한)을 더한다. D-402 C3b 보강에 따라 Fleet이 재컴파일한 값을 선언하고, 장치가 수락 레시피와 대조한다(Task 8a). wire 확정은 D-18에 따른다.
- 검증 규칙을 C3b 규칙으로 좁힌다: `pick.z + grasp_depth_m ≤ pick_approach_z ≤ carry_z`, place도 같은 형태다.
- `schemas.py`는 hard tier에 있다(현재 크기 판정 1239). 증가분은 판정 문구에 재판정 한 줄로 남긴다.

새 `src/contracts/foundation/core_common/protocol/action_grants.py`:
- `ActionGrant`: callable `Discriminator`를 쓰는 판별 합집합 `FleetActionGrant | FleetCellTransferGrant`.
- `parse_action_grant(raw)`.
- `action_grant_digest(grant)`: 정규 JSON에서 `request_digest`를 빼고 sha256을 낸다.
- 기존 두 구현(`mission_dispatcher.py:32` `_grant_digest`, `omx_adapter/action_runner.py:24` `action_grant_digest`)은 이 함수의 재수출로 바꾼다.

다른 파일:
- `omx_adapter/action_api.py`: `SubmitAction`이 `parse_action_grant`를 쓴다.
- `fleet/server/local_action_transport.py:84` `_version`: `CELL_TRANSFER`도 v2를 쓴다.
- palletizing 쪽:
  - `plan_bundle.py`의 `pallet.transfer` 입력에 `grasp_depth_m`·`grasp_width_m`을 더하고 Skill 버전을 `1.1.0`으로 올린다.
  - `cell_submission.py` `_TRANSFER_INPUTS`와 버전 검사도 함께 바꾼다.
  - 같은 커밋에서 `test/test_platform_palletizing_compat.py`와 `test/test_platform_cell_submission.py`를 고친다.

**TDD** — 새 `src/contracts/foundation/test/test_cell_transfer_grant_contract.py`
```python
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from core_common.protocol.action_grants import action_grant_digest, parse_action_grant
from core_common.protocol.schemas import FleetActionGrant, FleetCellTransferGrant

T0 = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 2, 0, 0, 15, tzinfo=timezone.utc)
PICK_PLACE_GOLDEN = "c847300c318ada2b16e49833603f499ccf6fcd2a4d70f18f2bd2c2e8d7014db8"  # sha256 request digest (public, not a credential)

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

def _cell(**body):
    b = {"job_id": "job-01", "recipe_sha256": "1" * 64, "cell_sha256": "2" * 64, "step_index": 0,
         "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base",
         "home": _pose(0.12, 0.0, 0.12), "pick": _pose(0.0, 0.17, 0.02, 1.5708),
         "place": _pose(0.1525, 0.0275, 0.03), "pick_approach_z": 0.06, "place_approach_z": 0.07,
         "carry_z": 0.117, "grasp_depth_m": 0.01, "grasp_width_m": 0.03}
    b.update(body)
    return {"mission_id": "mission-cell-01", "step_id": "mission-cell-01:t0", "action_id": "action-02",
            "attempt_id": "attempt-02", "request_digest": "0" * 64, "workcell_id": "omx_cell_sim",
            "instance_id": "omx_cell_sim_01", "action_kind": "CELL_TRANSFER", "cell_transfer": b,
            "capability_revision": "omx-cell-transfer-sim-v1", "config_revision": "cell-cfg-1",
            "authority_epoch": 3, "dispatch_generation": 19, "issued_at": T0, "expires_at": T1}

def test_pick_place_digest_is_unchanged():
    grant = parse_action_grant(_pick_place())
    assert type(grant) is FleetActionGrant and action_grant_digest(grant) == PICK_PLACE_GOLDEN

def test_cell_transfer_parses_to_its_model():
    assert type(parse_action_grant(_cell())) is FleetCellTransferGrant

@pytest.mark.parametrize("body", [{"grasp_width_m": 0.0}, {"grasp_depth_m": -0.001},
                                  {"pick_approach_z": 0.025},   # below pick.z + depth
                                  {"carry_z": 0.065}])
def test_cell_transfer_rejects_unsafe_geometry(body):
    with pytest.raises(ValidationError):
        parse_action_grant(_cell(**body))

def test_kinds_do_not_cross_validate():
    with pytest.raises(ValidationError):
        parse_action_grant(dict(_cell(), source_evidence=_evidence()))
    with pytest.raises(ValidationError):
        parse_action_grant(dict(_pick_place(), action_kind="PICK"))
```
`test/test_fleet_omx_action_identity_contract.py`에 CELL_TRANSFER 왕복 사례를 더한다: Fleet digest와 OMX digest가 같고 v2 receipt를 받는다.

**커밋:** `feat(contracts): CELL_TRANSFER grasp geometry, one grant parser and digest for Fleet and OMX (D-403 §2, D-402 C3b)`

---

## Task 2 — 컴파일러 port adapter와 `execution.site` 경계 (M, 호스트)

**변경**
- 새 `src/site/fleet/fleet/server/cell_compiler.py`(앱 조합 adapter)에 `PalletizingCellJobCompiler(*, tol_m, process_artifact_digest)`를 둔다. `compile(recipe, cell)` 단계:
  1. `load_recipe(json.dumps(recipe))`, `load_cell(json.dumps(cell))`. JSON은 YAML이고 해시는 parse한 값 위에서 계산하므로 같다.
  2. `compile_job(recipe, cell, tol_m=...)`.
  3. `carry_z(recipe, cell, tol_m=...)`를 부르고 `job.carry_z`와 같은지 단언한다. 계산은 다시 구현하지 않는다(D-403 §2).
  4. `plan_bundle.compile_plan_bundle(job, recipe, cell, process_artifact_digest=..., tol_m=...)` → `CellJobCompilation`.

  `fleet`이 `rosy.processes.palletizing`을 import하는 곳은 이 파일 하나로 둔다. `src/site/fleet/test/test_boundaries.py`에 그 규칙을 더한다.
- `tools/harness/platform_dependencies.yaml`:
  - component `execution_site`: path `modules/execution/src/rosy/execution/site`, prefix `rosy.execution.site`.
  - boundary: `rosy.execution.site`는 `rosy.processes.palletizing`, `rosy_cell`, `fleet`, `omx_adapter`, `rclpy`를 import할 수 없다.
  - `test_platform_dependency_boundaries.py`에 위반 주입 fixture를 더한다. 절대 import와 상대 import 둘 다다.
- `create_app`에서 `cell_job_compiler`를 받는 지점은 pl3 구현을 그대로 쓴다. 운영 `cli.py` 배선은 D-413 Task 6 몫이다. C4는 Task 13 런처에서만 주입한다.
- 승인 경계 시험 보강(`test_cell_job_api.py`). pl3 시험에 없는 사례만 더한다.
  - `service`가 `/admit`을 부르면 403.
  - 운영자 A의 PICK_PLACE 제안을 운영자 B가 승인하면 404(기존 동작).
  - 64 KiB를 넘는 제안은 거절.
  - 바꾼 Step·해시·짝 없는 pick/place는 거절(실제 adapter로).

**TDD**
- 새 `src/site/fleet/test/test_cell_compiler_port.py`:
  - 데모 `src/site/cell/examples/omx_sim/{recipe,cell}.yaml`로 만든 Job이 `rosy_cell` facade의 `compile_job` 결과와 같다.
  - `rosy.processes.palletizing.compiler.carry_z`를 monkeypatch한 sentinel 값이 plan input `carry_z_base_m`에 그대로 나온다.
- 경계 시험: 일부러 `rosy.execution.site`에 `import rosy.processes.palletizing`을 주입하면 실패한다.

**커밋:** `feat(fleet): inject the palletizing compiler into cell submission; guard rosy.execution.site (D-413 Task 4, D-403 §3)`

---

## Task 3 — Step 순차 하달과 `deployment_profile` 게이트 (L, 호스트)

**규칙(순수)** — 새 `modules/execution/src/rosy/execution/site/cell_steps.py`
- 입력: Job 스냅숏(Step 상태 목록, 승인 때 기록된 epoch/generation), 현재 `dispatch_control`.
- 함수 `next_cell_transfer(job, control, *, workcell_busy) -> Submit(step_index) | Hold(reason) | Wait`. 다음 순서로 판단한다(D-403 §5).
  1. 이전 Step이 `GOAL_CONFIRMED`가 아니면 `Wait`.
  2. 작업대에 진행 중인 Action이 있으면 `Wait`.
  3. `dispatch_enabled`가 꺼졌거나 epoch/generation이 승인 때와 다르면 `Hold("FLEET_FENCE_CHANGED")`.
  4. 이전 Step이 `UNKNOWN`/`FAILED`이면 `Hold`.
  5. 재시작 직후에는 자동 제출하지 않는다.
- ROS, SQLite, FastAPI는 쓰지 않는다.

**조합** — `fleet/server/mission_dispatcher.py`
- PICK_PLACE 경로는 바꾸지 않는다. CELL_JOB 분기를 더한다: `CellJobStore`(pl3)의 `start_step` → grant 발급(Task 1 parser·digest) → `transport.submit` → `record_action_result`.
- 오류 처리:
  - `LocalActionRejected`이면 Step `FAILED`(reason `LOCAL_ACTION_REJECTED`), Job `HOLD`(D-403 §9).
  - 그 밖의 예외는 Step `UNKNOWN`, Job `HOLD`. 재제출하지 않는다.
  - `_verified_receipt`의 4-phase 규칙은 CELL_TRANSFER에도 적용한다.
- 300줄을 넘으면 `fleet/server/cell_job_dispatch.py`로 나눈다.

**게이트** — `fleet/server/app.py` `create_app`
- 새 인자: `deployment_profile: str = "production"`, `simulation_instances: frozenset[str] = frozenset()`.
- `enable_mission_dispatcher=True`이려면 `deployment_profile == "simulation"`이고 모든 구성 OMX 인스턴스가 `simulation_instances` 안에 있어야 한다. 아니면 `ValueError`(D-403 §7). 장치 쪽 이중 거절은 Task 8a에서 만든다.
- 기존 하달기 시험(`test_mission_dispatcher.py`, `test_omx_fleet_ros_actionserver.py`, `test_fleet_omx_action_identity_contract.py`)도 `deployment_profile="simulation"`을 넘기도록 고친다. D-403 §7은 모든 하달에 적용된다.
- 이 게이트는 G1의 코드 측 절반이다. G1 문서 측 절반(ADR Accepted)은 코드가 판정하지 않는다.

**TDD**
- 새 `test/test_platform_cell_steps.py`(순수 규칙):
  - 순서 0 → 1 → 2, Step 0이 `ACTION_SUCCEEDED`인 동안 Step 1은 `Wait`.
  - generation이 바뀌면 `Hold`.
  - 재시작 뒤 `RUNNING`이 남아 있으면 `Hold`/reconcile이고 재제출하지 않는다.
- 새 `src/site/fleet/test/test_cell_job_dispatch.py`(가짜 transport):
  - 제출 순서가 맞다.
  - `GRANT_REJECTED`이면 Step `FAILED`, Job `HOLD`.
  - production 프로필이나 sim이 아닌 인스턴스면 `ValueError`.
  - transport 버전이 v2다.

**커밋:** `feat(execution): ordered CELL_TRANSFER step rule and simulation-only Fleet dispatch (D-403 §5, §7)`

---

## Task 4 — `item_at_pose` / `sim_model_pose` (M, 호스트)

**변경**
- 새 `modules/execution/src/rosy/execution/site/item_pose.py`(순수): `ItemPosePredicate`, `ItemPoseEvidence`, `verify_item_at_pose(predicate, evidence, *, now, max_age_s) -> bool`.
  - **증거에는 `satisfied`가 없다.** Fleet이 판정한다. 판정 항목: xy 거리, |dz|, `yaw_period_rad`(상자 π)를 적용한 yaw 차, 기울기, `gripper_state == "OPEN"`, 신선도. 생산자가 만족 여부를 정하면 독립 증거가 아니기 때문이다(D-328 §4).
- `fleet/server/goal_evidence.py`:
  - `GoalPredicate.from_mapping`이 `condition: item_at_pose` 모양을 받는다. 필드는 `{predicate_id, condition, item_id: "<job>:<k>", target {x,y,z,yaw}, tolerance {xy_m, z_m, yaw_rad, yaw_period_rad}, evidence_source: sim_model_pose}`이다.
  - 기존 `object_in_destination`/`camera_observation` 모양은 바꾸지 않는다.
- `fleet/server/goal_evidence_registry.py:22`:
  - `_EVIDENCE_SOURCES`에 `sim_model_pose`를 더한다.
  - 로더는 `deployment_profile`을 받고 `sim_model_pose` 생산자는 `simulation`일 때만 받는다(D-403 §5).
- 확인 결과는 `CellJobStore.confirm_step_goal`(pl3)로 Step 단위로 기록한다.
- 증거 없이 `goal_evidence_timeout_s`가 지나면 Step·Job은 `HOLD`(`GOAL_EVIDENCE_MISSING`)가 된다.
- predicate 생성은 Task 2 adapter가 Step마다 한다. 목표는 place 포즈의 물건 중심, z = 윗면 − 높이/2다. 허용오차는 Fleet 구성에서 오고 기본값은 없다(§6 Q3).
- 새 `deploy/robot/omx/sim_pose_evidence_producer.py`: `gz model -m <block> -p`를 재시도하며 읽고, `/joint_states`로 그리퍼 열림을 읽고, 자기 `X-Goal-Evidence-Token`으로 `POST /api/fleet/goal-evidence`에 보낸다. owner를 import하지 않는다.
- `platform_dependencies.yaml`: Task 2의 `execution_site` 규칙이 이 파일도 덮는다.

**TDD** — 새 `test/test_platform_item_pose.py`
```python
import math, pytest
from rosy.execution.site.item_pose import ItemPoseEvidence, ItemPosePredicate, verify_item_at_pose

P = ItemPosePredicate.from_mapping({
    "predicate_id": "p-1", "condition": "item_at_pose", "item_id": "job-1:0",
    "target": {"x": 0.1525, "y": 0.0275, "z": 0.015, "yaw": 0.0},
    "tolerance": {"xy_m": 0.005, "z_m": 0.002, "yaw_rad": 0.05, "yaw_period_rad": math.pi},
    "evidence_source": "sim_model_pose"})

def _ev(**pose):
    base = {"x": 0.1525, "y": 0.0275, "z": 0.015, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    base.update(pose)
    return ItemPoseEvidence.from_mapping({
        "predicate_id": "p-1", "item_id": "job-1:0", "evidence_source": "sim_model_pose",
        "evidence_id": "e-1", "evidence_revision": "gz-pose-v1", "producer_id": "sim-pose",
        "observation_id": "o-1", "observation_digest": "c" * 64, "model_name": "block_0",
        "pose": base, "action_id": "a-1", "attempt_id": "t-1", "gripper_state": "OPEN",
        "gripper_evidence_id": "g-1", "gripper_evidence_revision": "omx-sim-gripper-v2",
        "gripper_observed_at": 100.0, "observed_at": 100.0})

def test_fleet_judges_pose_with_pi_symmetric_yaw():
    assert verify_item_at_pose(P, _ev(x=0.1528, yaw=math.pi + 0.001), now=101.0, max_age_s=5.0)

def test_c3_run8_lying_block_is_not_at_pose():
    assert not verify_item_at_pose(P, _ev(x=0.1077, y=0.0565, z=0.0197, roll=-1.571),
                                   now=101.0, max_age_s=5.0)

def test_producer_cannot_assert_satisfaction():
    with pytest.raises(ValueError):
        ItemPoseEvidence.from_mapping(dict(_ev().to_dict(), satisfied=True))
```
`test_goal_evidence_registry.py`에 두 사례를 더한다: production 프로필에서 `sim_model_pose` 생산자 거절, simulation에서 수락.

**커밋:** `feat(execution): per-step item_at_pose judged by Fleet from sim_model_pose evidence (D-403 §5)`

---

## Task 5 — 조작 Skill `transfer.py` (M, 호스트)

**새로 만들 파일**
- `modules/skills/manipulation/pyproject.toml`:
  - 배포 이름 `rosy-skill-manipulation` 0.1.0, 의존 `rosy-skill-api==0.1.0`.
  - include는 `rosy.skills.manipulation*`, namespaces true. ROS 의존은 없다.
- `modules/skills/manipulation/src/rosy/skills/manipulation/__init__.py`, `transfer.py`.

**`transfer.py` 내용** — 제품과 무관하게 설명할 수 있는 절차만 둔다(설계 §5.4).
- 상수: `TRANSFER_PHASES = ("approach", "grasp", "transfer", "release")`.
- port(Protocol):
  - `TransferPlanner.plan(request, state) -> TransferPlan`
  - `PhaseExecutor.submit(phase) / cancel_exact(goal_id)`
  - `HoldReadback.held(item_id) -> HoldResult` / `released() -> bool`
  - `ExecutionState.snapshot()`
- `TransferProcedure`: phase 결과를 받아 다음 행동 하나를 돌려준다. 다음 phase 제출, `Hold(reason)`, `Complete(evidence)` 중 하나다. 규칙은 다음과 같다.
  - grasp 뒤 hold가 증명되지 않으면 `Hold("HOLD_NOT_PROVEN")`.
  - release 직전에 다시 확인하고, 실패하면 `Hold("ITEM_LOST_IN_TRANSIT")`(C3b A4).
  - release 뒤 해제가 증명되지 않으면 `Hold`.
  - 정지·취소면 다음 phase는 없다.
  - 자동 놓기·재파지는 하지 않는다(D-403 §6, D-330 Transition 2).
- 완료 근거: phase 결과, readback 값, item id, job/step id.
- `TransferProcedure`는 lock을 갖지 않는 순수 상태 기계다. 스레드 문제는 Task 7 provider가 다룬다.

**경계**
- `platform_dependencies.yaml` component `skill_manipulation`: boundary `rosy.skills.manipulation`은 `rosy.execution`, `omx_adapter`, `rosy.integrations`, `fleet`, `rclpy`, `rosy.processes`를 import할 수 없다.
- 기존 future canary는 실제 규칙으로 바꾼다.

**CI**
- `pip3 wheel` 목록에 `modules/skills/manipulation`을 더한다. `modules/skills/api` 뒤, `modules/execution` 앞이다.
- 설치 목록에 `rosy-skill-manipulation==0.1.0`을 더한다.

**TDD** — 새 `test/test_platform_transfer_skill.py`
1. 정상 순서는 4 phase 제출 뒤 `Complete`다.
2. grasp 뒤 빈손이면 `Hold`이고 transfer를 제출하지 않는다.
3. release 전 재확인이 실패하면 `ITEM_LOST_IN_TRANSIT`이고 release를 제출하지 않는다.
4. 중간에 정지하면 남은 phase 0개.
5. `import rosy.skills.manipulation.transfer`한 뒤 `sys.modules`에 `rclpy`, `omx_adapter`가 없다.

**커밋:** `feat(skills): ROS-free CELL_TRANSFER manipulation procedure and its wheel (D-413 Task 5)`

---

## Task 6 — `execution/local/receipts.py`와 종류 중립 완료 (M, 호스트)

**변경**
- 새 `modules/execution/src/rosy/execution/local/__init__.py`와 `receipts.py`. 두 기기가 공유할 수 있는 receipt 연결 규칙만 둔다.
  - Mission/Step/Action/attempt/ROS goal 상관관계 검사.
  - 완료 이벤트 이름 `ACTION_WORKFLOW_COMPLETED`, `result_source_for(kind)`: `PICK_PLACE`면 `pick-place-workflow`(기존 값 유지), `CELL_TRANSFER`면 `cell-transfer-workflow`.
  - 4-phase 경계 검사.
  - DB 스키마와 attempt ID 생성은 가져오지 않는다(이전 계획 Task 5-2).
- `modules/execution/pyproject.toml` include에 `rosy.execution.local*`을 더한다(같은 wheel이라 CI 목록은 바꾸지 않는다).
- `omx_adapter/action_store.py`:
  - `complete_pick_place`(:817)를 `complete_workflow(..., action_kind)`로 바꾸고 이름·출처·경계 검사를 `receipts.py`에서 가져온다.
  - **순증가 0줄**(hard tier, 크기 판정 1187).
  - 디스크의 옛 `PICK_PLACE_ACTION_COMPLETED` 행은 그대로 둔다. 읽는 곳은 `test_omx_pick_place_transaction.py` 하나다.
- `omx_adapter`가 `rosy.execution.local`을 쓰려면 `rosy-execution` wheel이 설치된 뒤 colcon이 돌아야 한다. CI는 이미 이 순서다.
- `platform_dependencies.yaml` component `execution_local`: boundary `rosy.execution.local`은 `omx_adapter`, `rosy.integrations`, `fleet`, `rosy.processes`, `rclpy`를 import할 수 없다.

**TDD**
- `test/test_platform_receipts.py`: 이름과 출처 표, 상관관계 불일치 거절.
- `test_omx_action_store.py` 확장: CELL_TRANSFER 완료 행과 이벤트를 확인한다. PICK_PLACE 회귀는 `test_omx_pick_place_transaction.py`로 확인한다.

**커밋:** `refactor(execution): kind-neutral local receipt rules; omx ActionStore completes any admitted workflow`

---

## Task 7 — `transfer_provider.py` (M, 호스트)

**새로 만들 파일**
- `integrations/robots/omx/pyproject.toml`:
  - 배포 이름 `rosy-integration-omx` 0.1.0, 의존 `rosy-skill-manipulation==0.1.0`.
  - `omx_adapter`는 colcon 패키지라 pip 의존으로 적지 않는다. 런타임 import이고 colcon 설치 뒤에 시험한다.
  - include는 `rosy.integrations.robots.omx*`, namespaces true.
- `integrations/robots/omx/src/rosy/integrations/robots/omx/__init__.py`, `transfer_provider.py`.

**`transfer_provider.py` 내용** — Task 5 port를 구현한다. 방향은 integration → omx_adapter → (없음) 한쪽뿐이다.
- `OmxTransferPlanner`는 `omx_adapter.pose_plan.AnalyticCellTransferPlanner`(:484)와 `CellTransferRequest`를 감싼다. grant 본문을 1:1로 옮긴다.
- `OmxPhaseExecutor`는 `PickPlaceRunner`와 `RosArmPhaseGoalPort`를 감싼다. exact UUID 취소다.
- `OmxHoldReadback`은 `gripper_contract.verify_held_object`(:93)·`verify_released_object`를 감싼다.
- `cell_transfer_factory(...) -> Callable[[grant, recorder], PhaseExecution]`: `ActionRunner`의 `phase_runner_factories={"CELL_TRANSFER": ...}`에 **조립 지점이 주입**한다. `omx_adapter`는 integration을 import하지 않는다.
- sequencer: runner terminal 이벤트는 ROS 콜백 스레드가 아니라 전용 단일 작업 스레드에서 `TransferProcedure`를 거쳐 `advance()`로 간다. sim attach aid hook(C3b B3)은 기본 no-op이고 조립 지점이 주입한다.
- 최종 owner(`ArmCommandOwner`)와 제품 한계(`CellPlanningProfile`, start-state 상한)는 `omx_adapter`에 남는다. provider는 그것들을 호출할 뿐이고 검사를 대신하지 않는다(설계 §5.4).

**경계**
- `platform_dependencies.yaml` component `omx_integration`: boundary `rosy.integrations.robots.omx`는 `fleet`, `rosy.execution.site`, `rosy.processes`, `rosy_cell`을 import할 수 없다.
- `omx_adapter` boundary에 `rosy.integrations`, `rosy.skills.manipulation`을 더한다(순환 금지).

**CI**
- `pip3 wheel` 목록에 `integrations/robots/omx`를 더한다(`modules/skills/manipulation` 뒤). 설치 목록에 `rosy-integration-omx==0.1.0`을 더한다.
- 이 wheel의 시험은 colcon으로 `omx_adapter`를 설치한 뒤에 돈다.

**TDD** — 새 `test/test_platform_transfer_owner_boundary.py`(이전 계획 Task 5가 지정한 이름)
1. 실제 `ActionStore`, 실제 `AnalyticCellTransferPlanner`, 가짜 goal port로 4 phase가 끝나면 `ACTION_WORKFLOW_COMPLETED`가 남는다.
2. `advance()`를 부른 스레드는 이벤트 콜백 스레드와 다르다.
3. planner 거절(`CELL_HASH_MISMATCH`, `ITEM_GEOMETRY_MISMATCH`)이면 phase 0개, Action `HOLD`.
4. 정적 검사: `omx_adapter` 안에 `rosy.integrations` import가 0이다.

기존 OMX 시험 `test_omx_command_owner.py`, `test_omx_action_store.py`, `test_omx_pick_place_runner.py`, `test_omx_cell_transfer_runner.py`, `test_omx_pose_plan.py`도 통과해야 한다.

**커밋:** `feat(integrations): OMX transfer provider wraps analytic IK, gripper contract and ROS phase port (D-413 Task 5)`

---

## Task 8a — 장치 수락 저장소와 `capability_current` (M, 호스트)

**변경** — 새 `omx_adapter/cell_acceptance.py`. owner 로컬 journal이고 제품 한계이므로 `omx_adapter`에 둔다.
- `AcceptedCellStore(path, *, kinematics_revision, simulation, unresolved_actions)`. ActionStore와 같은 SQLite 파일의 `omx_accepted_cell` 표를 쓴다.
- `canonical_sha256(doc)` = sha256(`json.dumps(doc, sort_keys=True, separators=(",",":"))`). `rosy.processes.palletizing` 해시와 바이트가 같아야 한다. 두 패키지를 함께 import하는 저장소 루트 시험이 이를 묶는다.
- `accept_cell(doc, *, actor)`: schema `rosy_cell.cell/2`, `kinematics_revision` 일치, 미해결 Action 0을 확인한다.
- `accept_recipe(doc, *, actor)`: 기하 `{grasp_width_m: box.width, grasp_depth_m: box.grasp_depth|0, height_m: box.height}`를 보관한다. `slip_sheet`는 보관하지 않는다(집을 방법이 없어 planner가 거절).
- planner hook 두 개: `accepted_cell_sha256()`, `accepted_item_geometry(recipe_sha256, item)`.
- `capability_current(grant)`. CELL_TRANSFER는 다음을 모두 요구한다: owner 프로필 `simulation`(§0.2의 장치 쪽 이중 거절), 셀·레시피 해시 일치, grant의 `grasp_*`가 수락값과 1e-9 안에서 같음, `frame == robot_base`. 실패하면 `ActionRunner._validate`가 journal 생성 전에 `GRANT_REJECTED` 403을 낸다(D-403 §9 첫 검사). planner의 두 번째 검사는 그대로 둔다.

**TDD**
- 새 `test_omx_cell_acceptance.py`: 재시작 뒤 유지, 미해결 Action 중 교체 거절, 다른 kinematics 거절, `slip_sheet` 기하 없음.
- `test/test_cell_omx_acceptance_hash_contract.py`.
- `test_omx_action_api.py` 확장: 다음 경우 모두 403이고 `omx_actions` 행이 0이다 — 셀·레시피 해시 불일치, 폭 불일치, 비시뮬 프로필.

**커밋:** `feat(omx): accepted cell/recipe store backs capability_current; CELL_TRANSFER only in the simulation owner (D-403 §9, D-404 §6)`

---

## Task 8b — 잠금 순서(minor 8)와 실제 stop fence (M, 호스트 + WSL 짧게)

**규칙:** owner `_lock`이나 runner `_event_lock`/`_lock`을 쥔 채 상대 쪽 lock을 잡는 호출을 하지 않는다. 취소는 lock 안에서 결정만 하고, 호출은 lock 밖에서 한다.

**변경**
- `command_owner.py`:
  - `_cancel_active`(:400)는 handle을 대기열에 넣기만 한다.
  - 공개 진입점(`poll`, `observe_joint_state`, `submit`, `cancel`)은 lock을 놓은 뒤 `_drain_cancels()`를 부른다.
  - HOLD 래치는 lock 안에서 건다.
- `pick_place_runner.py`: replay와 `_process_ros_goal_event`의 취소 대상 UUID를 `_event_lock` 안에서 모으고, lock 밖에서 `goal_port.cancel_goal`을 부른다. 동기 `CANCEL_ACK` 경로(`ros_runtime.py:243` 부근 `cancel_goal_async` 예외)도 이 규칙으로 닫힌다.
- `local_stop.py`: `local_fence_current(controller)`. 컨트롤러가 `OPEN`이고 `(epoch, generation)`이 grant와 같을 때만 참이다. 제출 때와 각 phase 직전에 확인한다(D-403 §6).
- `probe_cell_transfer.py`: `ProbeFence`(:222)와 항상 참인 `current_fence`를 걷고 실제 `LocalStopController`를 쓴다.

**TDD** — 새 `test_omx_lock_order.py`
- `RecordingLock`으로 owner·runner lock을 감싼다. watchdog HOLD에 동기 취소 실패가 겹치고, 늦은 수락 replay가 같이 와도 중첩 간선이 0이다.
- 두 스레드 동시 실행이 1초 안에 끝난다.
- `test_omx_stop_fence.py` 확장:
  - trip 뒤 operation이 호출되지 않는다.
  - rearm(gen+1) 뒤 옛 grant는 거절된다.
  - 재시작 뒤 `UNKNOWN`이고 fence가 닫혀 있다.

**WSL(짧게, Gazebo 없음):** `test_omx_ros_runtime.py`, `test_omx_fleet_ros_actionserver.py`를 25회 반복한다. 다른 세션의 Gazebo가 돌고 있으면 `nice -n 19`로 돌린다. 기대: 25/25.

**커밋:** `fix(omx): cancel outside owner and runner locks (minor 8); LocalStopController replaces the always-open fence`

---

## Task 9 — owner 프로세스 하나(HTTP + UDS) 조립 (L, 호스트)

**변경**
- 새 `integrations/robots/omx/src/rosy/integrations/robots/omx/cell_owner.py` `build_cell_owner(settings, *, runtime_factory, now)`. 순수 조립이고 rclpy는 lazy import한다. 만드는 것:
  - `ArmCommandOwner` 하나: `allowed_owners=("pilot_sim","rule_based")`, `owner_clock="sim"`, `CellPlanningProfile.arm_command_config`.
  - 공유 SQLite 하나: `ActionStore`, `LocalStopController`, `AcceptedCellStore`.
  - `ActionRunner(enabled=settings.profile == "simulation", submission_fence=controller, current_fence=local_fence_current(controller), capability_current=acceptance.capability_current, phase_runner_factories={"CELL_TRANSFER": cell_transfer_factory(...)})`.
  - `LocalStopApi(... source_by_peer_uid={fleet_uid: FLEET}, cancel_active=runner.cancel_unresolved)`.
  - `UnixActionServer(ActionApi(...), f"/run/rosy/omx/{instance_id}/control.sock")`.
  - `create_pilot_sim_app(...)`. **Task 9에서는 `pilot_sim_*` 파일을 고치지 않는다.** 기존 시그니처 그대로 넘긴다.
- 새 `deploy/robot/omx/run_cell_owner.py`와 `run_cell_owner.sh`:
  - `refuse_second_owner()`(`cell_sim_tools.py:27`)로 다른 owner와 같이 뜨지 않는다.
  - UDS는 별도 스레드에서 `serve_forever`, uvicorn은 주 스레드다.
  - socket 부모는 bind-mount로 받는다.
  - D-413 Task 6에서 `apps/agent/rosy_agent/omx_sim.py`로 옮길 대상이라고 파일 머리에 적는다.
- 의존 방향은 deploy → integration → (`omx_adapter`, `rosy.skills.manipulation`, `rosy.execution.local`)이다. `omx_adapter`는 위쪽을 import하지 않는다.

**TDD** — 새 `test/test_platform_cell_owner_assembly.py`(가짜 runtime factory)
1. 수락 저장소에 넣은 해시를 UDS `SubmitAction` 검사가 같은 객체로 본다.
2. 프로필이 `simulation`이 아니면 CELL_TRANSFER가 403이다.
3. `allowed_owners`가 정확하다.
4. socket 경로가 맞다.

실제 bind와 `SO_PEERCRED`는 Task 12(WSL)에서 확인한다.

**커밋:** `feat(integrations): one OMX cell owner process composes the HTTP API and the D-336 UDS socket (D-403 §8)`

---

## Task 10 — seat 상호 배제와 `/cell`·`/recipe` (M, 호스트) — **마지막. rosy-35 D-411 part C 착지 뒤**

**대기 조건:** 세션 rosy-35가 `omx_adapter/pilot_sim_*` 파일을 바꾸고 있다(D-411 part C). 그 변경이 main에 들어간 뒤 main을 merge하고 시작한다. 그 전에는 `pilot_sim_api.py`, `pilot_sim_server.py`, `pilot_sim_runtime.py`를 고치지 않는다. 다른 Task는 이 파일들에 의존하지 않게 짰다. Task 11의 seat 사례와 Task 12·13은 이 Task 뒤에 둔다.

**변경**
- 새 `omx_adapter/owner_exclusion.py` `SeatActionExclusion`:
  - `acquire_seat()`: CELL_TRANSFER가 진행 중이면 `SEAT_BUSY_WITH_ACTION`.
  - `begin_cell_transfer()`: seat가 잡혀 있으면 `ACTION_REFUSED_SEAT_HELD`.
  - 근거는 journal의 미해결 수다. 재시작하면 어차피 HOLD에서 시작한다.
- `pilot_sim_api.py`:
  - seat 획득이 exclusion을 거친다.
  - `PUT/GET {PREFIX}/cell`, `PUT/GET {PREFIX}/recipe`를 더한다. seat가 필요하고, 미해결 Action이 있으면 409 `UNRESOLVED_ACTION`, schema·revision이 어긋나면 422. 저장은 Task 8a 저장소에 한다(D-404 §6 + §1 Q2의 recipe 보강).
- `cell_owner.py`(Task 9)가 exclusion을 HTTP와 runner 양쪽에 넘긴다.

**TDD** — `test_pilot_sim_api.py` 확장, 새 `test_omx_owner_exclusion.py`
- seat가 잡혀 있으면 UDS CELL_TRANSFER는 403이다.
- 진행 중 Action이 있으면 seat 획득은 409다.
- `PUT /cell`은 해시를 다시 계산하고, 미해결 Action 중에는 거절한다.

**커밋:** `feat(omx): seat and CELL_TRANSFER exclude each other; seat-holder accepts cell and recipe (D-403 §10, D-404 §6-7)`

---

## Task 11 — 정지 세대 시험 (a)–(i), 호스트 층 (L, 호스트)

**파일:** 새 `test/test_cell_job_stop_generation.py`와 `test/cell_job_harness.py`.

**구성:** 실제 Fleet 저장소(`CellJobStore`, `FleetTaskStore`), 하달기, `ActionApi`·`ActionRunner`, `LocalStopController`, `AcceptedCellStore`, Task 7 factory를 쓴다. 가짜는 둘뿐이다.
- ROS 쪽 port와 readback.
- UDS 대신 `ActionApi.dispatch(request, peer_uid=FLEET_UID)`를 부르는 in-process transport(`test_fleet_omx_action_identity_contract.py` 방식).

| 시험 | 단언 |
|---|---|
| (a) Step 사이 정지 | Step 1이 제출되지 않는다. Job `HOLD`. owner `LOCAL_LATCHED`. |
| (b) phase 도중 정지 | 활성 UUID 하나만 취소된다. release 미제출. `STOP_GENERATION_FENCED`. |
| (c) 정지 뒤 늦은 수락 | 늦은 수락을 취소하고 `HOLD`(D-386 §2). 다음 phase 없음. |
| (d) rearm 뒤 옛 세대 grant | 403. `omx_actions` 새 행 0. |
| (e) Job 도중 Fleet 재시작 | epoch가 올라간다. 재제출 0. |
| (f) owner 재시작 | `UNKNOWN/STARTUP_STOP_UNCONFIRMED`. 새 grant 403. |
| (g) 감사 DB 쓰기 불능 | `StopLocal`은 도착한다. 일반 명령은 503(D-330 §3). |
| (h) UDS 상실(제출 중·조회 중) | Step `UNKNOWN`. `dispatch_control()`을 다시 읽는다. 재제출 0. 복구 뒤에는 `GetAction`으로만 조정한다. |
| (i) 정지 뒤 물체 보유 불명 | 자동 release·재파지 0. Job `HOLD` `ITEM_STATE_UNRECONCILED`. rearm 뒤에도 재하달 0. |

seat가 걸린 사례는 Task 10 뒤에 같은 파일에 더한다.

**기대:** 9개 모두 통과하고 각각 1초 안에 끝난다. 명령: `python -B -X utf8 -m pytest test/test_cell_job_stop_generation.py -q -p no:cacheprovider`.

**커밋:** `test(cell): D-403 §7 stop-generation producer/consumer suite (a)-(i), host layer`

---

## 게이트 G1

사용자에게 D-402·D-403·D-404를 Accepted로 바꿀지 묻는다. 근거로 Task 0–11 결과와 이 계획을 함께 낸다. Accepted가 되면 D-330·D-336·D-376 머리의 개정이 효력을 갖는다. 승인 기록은 ADR Log와 각 ADR 상태 줄에 남긴다. **승인 전에는 Task 12·13을 시작하지 않는다.**

---

## Task 12 — 정지 세대 시험 (a)–(i), ROS-SIM (L) — **비어 있는 WSL 슬롯 필요**

- 이미지는 C3b와 같은 `rosy-omx-pilot:recording-local` `sha256:faeb86d6…efb2`다. 바꾸면 ID를 기록한다. 재빌드가 필요하면 사용자에게 먼저 알린다.
- 컨테이너는 `rosy-cell-c4-sim`이다: `--network none`, `ROS_DOMAIN_ID=77`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, 저장소 read-only.
- 컨테이너 안에서 두 프로세스를 띄운다.
  - `run_cell_sim.sh`: vendor follower, 월드 `omx_cell_workcell_sim_aid.sdf`.
  - `run_cell_owner.sh`(Task 9).
- socket: `X:\DevTemp\rosy-cell-c4\run`을 `/run/rosy/omx`로 bind-mount한다. Fleet은 WSL Ubuntu에서 실행한다(같은 커널, D-336 §1).
- 첫 단계에서 owner가 관측한 `SO_PEERCRED` UID를 기록하고 `ROSY_FLEET_UID`로 고정한다(D-403 §8). UID가 맞지 않으면 Fleet을 같은 컨테이너에서 실행한다.
- 새 `deploy/robot/omx/probe_cell_stop_suite.py`: (a)–(i)를 실제 owner와 ROS goal에 대해 실행한다. 정지 주입은 `POST /api/fleet/estop`이다.
  - (e)(f)는 `kill -TERM` 뒤 재시작한다.
  - (g)는 Fleet DB를 read-only로 바꾼다.
  - (h)는 socket을 rename한다.
- 증거: `docs/validation/rosy-cell-c4-stop-generation-<date>/README.md`. 담는 것: 이미지 ID, 커밋, 월드 sha256, revision들, 시나리오별 Fleet 원장·owner journal·`omx_local_stop`·UUID·RTF.
- 실행 전에 `wsl -e bash -lc 'pgrep -a gz; docker ps'`로 다른 세션의 Gazebo가 없음을 확인한다.

**기대:** 9/9. 이것이 D-330 §2 개방 조건이다(simulation 한정). 하나라도 실패하면 Task 13으로 가지 않는다.

**커밋:** `test(cell): D-403 §7 stop-generation suite on the pinned ROS-SIM image (evidence)`

---

## Task 13 — 2–3 transfer Job 통합 (L) — **비어 있는 WSL 슬롯 필요**

- 축소 레시피 `src/site/cell/examples/omx_sim_c4/recipe.yaml`을 만든다. 팔레트 1, 층 1, 블록 2–3, 슬립시트 없음. 셀은 `omx_sim/cell.yaml`이다.
  - C3b 이웃 간섭(마지막 배치가 이웃을 24.9 mm 밀었음)을 피하는 배치를 고른다.
  - 3개가 간섭하면 2개로 줄이고 증거에 적는다.
  - `test/test_cell_omx_sim_layout_contract.py` 방식으로 모든 transfer가 planner 거절 없이 계획되는지 먼저 확인한다.
- 시험 하네스가 seat를 잡고 `PUT /cell`·`/recipe`를 보낸 뒤 seat를 반납한다(Task 10).
- 새 `deploy/robot/omx/run_c4_fleet_sim.py`(WSL): `create_app(deployment_profile="simulation", simulation_instances={"omx_cell_sim_01"}, enable_mission_dispatcher=True, cell_job_compiler=PalletizingCellJobCompiler(...), site_users=..., goal_evidence_service=...)`.
- 새 `deploy/robot/omx/probe_c4_job.py`:
  1. `service` 토큰으로 `cell_job` 제안과 해석.
  2. 운영자 토큰으로 승인.
  3. Mission 이벤트 폴링.
  4. Step마다 `sim_pose_evidence_producer.py` 실행.
  5. 최종 블록 포즈와 오차 기록.
- 판정: transfer마다 xy 5 mm, z 2 mm, yaw 0.05 rad 안이고, Step이 모두 `GOAL_CONFIRMED`, Job `GOAL_CONFIRMED`, owner HOLD 0, 이웃 블록 이동 ≤ 2 mm이면 **ROS-SIM C4 통과**다. 넘으면 HOLD로 정직하게 기록한다.
- 증거: `docs/validation/rosy-cell-c4-fleet-route-<date>/README.md`. 담는 것: 해시, Fleet 원장, grant digest, OMX journal, readback, `sim_model_pose`, RTF, SIM AID 표시.
- 이 결과는 D-413 이전 계획 Task 8의 입력이다. C6가 아니다.

**커밋:** `test(cell): first Rosy Cell job through Fleet -> UDS -> owner in Gazebo (C4 ROS-SIM)`

---

## Task 14 — 문서와 기록 (S, 호스트)

- API Reference §10.12: `grasp_*` 필드, v2, 오류 코드, `item_at_pose`, `/cell`·`/recipe`를 적는다. 버전은 쓰기 직전에 main의 다음 번호로 정한다(pl3이 v1.78을 썼다).
- ADR 보강 문단:
  - D-403 §2: grasp 기하 선언과 장치 대조, `tol_m` 출처.
  - D-403 §9: Step `FAILED` + Job `HOLD`.
  - D-404 §6: `/recipe`.
  - D-402 §3: (a)–(d) 완료.
- 이전 계획 Task 4·5에 "C4가 구현, 검증 담당 확인"을 기록한다.
- 모듈 기록을 갱신한다: `logs`/`progress`, minor 8 닫음, 하네스, lint 0, known-failures.

**커밋:** `docs(cell): C4 wire contract, ADR supplements, D-413 Task 4/5 hand-back`

---

## 3. 위험

1. **pl3 동시 작업.** `573a639cd`와 커밋하지 않은 OMX 시험 변경이 Task 1·2·3·8a와 같은 파일을 만진다. Task 0 인계 전에 코드를 쓰면 중복 구현과 충돌이 생긴다.
2. **rosy-35 (D-411 part C).** `pilot_sim_*`가 바뀌는 중이다. Task 10을 맨 뒤에 두고, Task 9는 기존 `create_pilot_sim_app` 시그니처만 쓴다. 그 시그니처가 rosy-35 착지로 바뀌면 Task 9 조립을 따라 고친다.
3. **Fleet main 동시 작업.** D-407 stuck board, D-395 localization, D-414 cancel-all, D-415 SAF-003이 `app.py`·API Ref 번호를 만진다. Task 3 직전에 main을 다시 merge하고, API Ref 번호는 Task 14에서 정한다.
4. **잠금 순서.** 새 교차 호출도 lock 밖 원칙을 지킨다: provider sequencer → runner `advance` → goal port → owner `submit`. stop lock(`run_if_open`)에서 owner로 가는 방향만 허용한다. Task 8b 기록 lock 시험을 Task 7 sequencer에도 적용한다.
5. **wheel 순서.** `omx_adapter`는 colcon, integration은 wheel이다. pip는 그 의존을 알 수 없다. CI는 wheel 설치 → colcon → pytest 순서를 지켜야 한다. Windows 로컬 검증은 integration 시험에서 `omx_adapter`를 소스 경로로 쓰는 예외를 시험 conftest에 명시한다. 그렇지 않으면 설치 누락을 숨기게 된다.
6. **WSL 일정.** Task 12·13은 WSL과 Docker를 독점해야 한다. 다른 세션 Gazebo와 겹치면 RTF가 0.3–0.4로 떨어지고 정지 주입 창 (c)가 흔들린다.
7. **크기 예산.** `schemas.py`(1239), `action_store.py`(1187)는 hard tier다. `proposal_store.py`는 800, `pick_place_runner.py`는 600 경계다. 넘으면 나누거나 판정을 다시 받는다.

## 4. 성공 기준

- Task 1–11 호스트 시험, architecture·플랫폼 경계 시험, wheel 설치 검증이 통과한다. lint 0, 새 known-failure 0.
- PICK_PLACE golden digest가 그대로다.
- G1 기록이 있다.
- Task 12에서 (a)–(i) 9/9.
- Task 13 Job이 `GOAL_CONFIRMED`다. 아니면 HOLD로 기록한다.
- probe 대역 셋이 모두 사라졌다: PICK_PLACE 봉투 바꿔치기, 항상 열린 fence, lambda 수락.

## 5. 범위 밖

C5, C6 전체, 슬립시트 파지, 충돌 장면과 이웃 간섭 검사, D-413 Task 6(apps·profiles·설치 전환과 `cli.py` 하달기 배선), 호스트 간 하달, 실물, MoveIt.

## 6. 열린 질문

1. **pl3 인계(Task 0).** `573a639cd`를 누가 언제 main에 넣는지, 커밋하지 않은 OMX 시험 변경을 어떻게 할지, `service` 역할 이름과 `cell_job_store` 별도 표를 그대로 확정하는지.
2. **G1.** D-402·D-403·D-404 Accepted 시점(사용자 결정).
3. **`tol_m`과 목표 허용오차의 출처.** `compile_job`/`carry_z`/`compile_plan_bundle`은 `tol_m`을 필수로 받는다. probe는 0.001, 시험은 1e-6을 쓴다. Fleet 구성으로 둘지, 셀 문서로 둘지(해시가 바뀜) 정한다. 목표 허용오차는 기본값을 두지 않는다.
4. **Skill 버전.** `pallet.transfer`에 grasp 기하를 넣으면서 `1.0.0` → `1.1.0`으로 올리는 것을 D-413 Task 3 담당이 받아들이는지.
5. **wheel 이름.** `rosy-skill-manipulation`, `rosy-integration-omx`가 D-413 명명 규칙(설계 §1.1)에 맞는지.
6. **정지 뒤 재개.** Job HOLD 뒤 물건 상태 대조(D-328 §5)와 남은 Step 재승인 API.
7. **통합 Job 크기.** 3 transfer가 이웃 간섭으로 실패하면 2로 줄여도 되는지.
8. **UDS 피어 UID.** Docker Desktop bind-mount socket에서 `SO_PEERCRED`가 WSL 프로세스 UID를 정확히 주는지(Task 12 첫 단계에서 실측).
9. **owner 조립 위치.** Task 6 전까지 `integrations/robots/omx/cell_owner.py` + `deploy` 진입점에 두는 임시 배치를 D-413 Task 6 담당이 받아들이는지.
