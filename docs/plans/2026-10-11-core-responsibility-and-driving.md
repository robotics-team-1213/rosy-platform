# CORE Common and Device Control Implementation Plan

**현재 폴더 단계:** D-627/D-628 CORE 조립·주행 경계와 D-630 holder 분리는 local main에 반영했다. 현행 경로는 `middleware/core/api`, `middleware/devices/{pinky,omx}`, `middleware/control/drive`, `middleware/perception/{sensors,vision}`이며 [CORE·Drive 책임표](../reference/core-drive-responsibilities.md)를 따른다. 아래 원래 계획의 API/모션 계약 확장·전 producer admission·실기 시험까지 완료한 것으로 읽지 않는다.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** CORE 공통 운용·실행 계약과 장치별 Control을 구분하고 Drive/Arm의 소유권, Safety, 복구 수명과 결과 근거를 각 도메인에서 단계적으로 정리한다.

**Architecture:** [설계](2026-10-11-core-responsibility-and-driving-design.md)를 기준으로 기존 `CoreServices`와 ROS-free feature를 유지한다. D-442 계약을 재사용하고 제어 자원별 한 실행 소유자와 단일 guarded binding으로 수렴한다. Drive는 base 명령, Arm은 궤적/action 경로를 유지한다. Safety는 D-430에 따라 보호 대상 옆에 두며 독립 리뷰한다.

**Tech Stack:** Python, ROS 2 Jazzy, 기존 Nav2, pytest(원격 시험 PC만), ROSY harness.

**상태:** Proposed, 2026-10-11, baseline `81b6ed879`, `docs/core-responsibility-plan`. 이 문서 작성은 아래 구현 작업의 완료가 아니다. 새 공개 모드·API 필드·설정·자동 복구 활성화는 확정하지 않았다.

---

## 공통 작업·검증 규칙

- 각 task는 주제별 `.worktrees/wt-<topic>-<6hex>`의 비-main 브랜치에서 수행한다. 실행 때 최신 main·관련 AGENTS·ADR·모든 호출자를 다시 확인한다.
- 행동 변경은 먼저 목표 동작을 실패하는 시험으로 고정한다. 시험 커밋 후 원격 red, 최소 구현 커밋 후 원격 green 순서다. 이동만 하는 작업은 기존 행동 시험을 먼저 기준으로 확보한다.
- 이 노트북에서는 pytest/Gazebo를 실행하지 않는다. X 관리 도구로 만든 세션의 `logs/<task>/`에 원격 로그를 둔다. 원격 도구가 **커밋된 HEAD만** 전송하므로 시험과 구현을 각각 자신의 경로만 커밋한다.
- 모든 원격 결과는 `known_failures.py`로 비교한다. NEW는 깨끗한 main에서 따로 재현하지 않은 이상 해당 변경의 실패다. 새 실패를 기존 실패 목록에 추가해 통과시키지 않는다.
- safety 코드 변경·이동에는 D-430 독립 리뷰와 `Safety-Review:` trailer가 필요하다. 원격 시험은 리뷰나 실물 수용을 대신하지 않는다.
- 아래 `X:/DevTemp/<managed-session>`은 관리 도구가 반환한 실제 세션 경로로 바꾼다. 임시 파일은 F:에 만들지 않는다.
- 사용자 요청 전에는 main 착지·push를 하지 않는다. 이후 승인된 착지는 `tools/land.py --tests auto`를 사용한다.

원격 실행 형식(각 task의 시험 목록으로 교체):

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<managed-session>/logs/P0 -- test/test_network_topology_contracts.py test/test_harness_contracts.py -q
python test/known_failures.py X:/DevTemp/<managed-session>/logs/P0/run-1.txt
```

시험 PC에 닿지 않으면 도구의 bounded retry 뒤 미확인으로 기록하고 착지·push를 진행하지 않는다. Gateway와 sensing처럼 동일 시험 basename이 있는 suite는 별도 invocation으로 유지한다.

## P0. 폴더·공통 책임·장치 Control·Safety 범위 고정

**읽기/변경 대상:**

- `middleware/core/gateway/core/services.py`, `core/bridge/ros_bridge.py`, `core/bridge/cmd_vel.py`, `core/bridge/docking_mode.py`.
- `middleware/core/api_web/core_api_web/api/v1/common.py` 및 각 start/stop 라우트.
- `middleware/core/services/core_features/command/{manager,arbitration}.py`, `safety/manager.py`, 각 실행기 start/tick/stop.
- 이 설계 문서의 현행 경로·커버리지 표; `tools/harness/platform_parts.yaml`의 Safety 추적.

**순서:**

0. `middleware/{core,perception,execution,skills,apps,drivers,ui}`, `contracts/{foundation,motion,skill}`, `integrations/robots`, `operations/execution`을 대조한다. 폴더별 실제 package/import prefix, 실행 entry point, 제어 writer, evidence producer, 소유 concern을 설계 표에 기록한다. legacy `perception/control`과 목표 Control 개념을 구분한다.
1. `teleop`, `set_nav_twist`, `set_docking_twist`, `select_output`, `_send_twist`의 모든 호출자를 검색한다. 생산자, 모드, gate, cancel, 입력 세대, 출력 위치를 표에 기록한다.
2. MANUAL/Nav2/line/trail/localization/docking별 입력 만료·준비·E-stop·기하 검사의 소유자를 기록한다. 없는 검사를 없는 상태로 표시한다.
3. 기존 시험을 커밋된 기준 SHA에서 원격 실행한다: gateway `test_cmd_vel_cycle.py`, `test_pinky_twist_port.py`, `test_docking_mode_ownership.py`, `test_goal_tracker.py`; services `test_safety_behaviour.py`; architecture `test_safety_separation.py`.
4. NEW가 있으면 같은 시험을 깨끗한 main에서 비교한다. 현행 위반과 새 설계의 미이행을 구분한다.
5. 문서·확인된 경로만 커밋: `docs: map core motion ownership and safety coverage`.

**완료:** 공통/Drive/Arm/인식/transport/driver/작업 계약의 현재 폴더와 실행 권한이 구분되고, 모든 producer/최종 writer와 Safety 공백이 표에 있다. 이후 P1–P3은 Drive 작업이며 Arm은 A1–A2로 따로 수행한다.

## P1. Drive 실행 소유권·식별·취소의 통일

**대상:** `contracts/motion/src/rosy/contracts/motion/types.py`, `command/{manager,arbitration}.py`, gateway `core/bridge/{cmd_vel,docking_mode}.py`, API `api/v1/common.py`; 기존 goal tracker/lease와 해당 producer의 시작·종료 연결.

**시험:** `contracts/motion/test/test_motion_types.py`, gateway `test_goal_tracker.py`, `test_goal_lease.py`, `test_absorption_command_validity.py`, `test_executor_contracts.py`, `test_docking_mode_ownership.py`, `test_cmd_vel_cycle.py`, `test_pinky_twist_port.py`.

**순서:**

1. 이미 이행된 `MotionHeader`/`MotionIntent`, guarded port, 목표 세대와 lease의 중복을 확인한다. 새 공통 타입·registry를 만들기 전에 기존 계약에서 빠진 부분만 적는다.
2. 다음 행동을 작은 회귀로 고정한다: 취소 전 세대의 늦은 명령 거절, MANUAL 유지 중 자율 요청 거절, 모드 왕복 후 이전 후보 재생 금지, 새 목표의 cancel이 다른 목표를 취소하지 않음, 만료 후보는 zero.
3. 독립 Safety 리뷰 대상인 command/port 변경은 리뷰를 포함한 별도 변경으로 만든다. 기존 API 응답·동기/비동기 취소 의미를 보존한다.
4. D-442 순서대로 **teleop → docking → Nav2 → localization → line-follow → swarm** 중 아직 이행되지 않은 producer 하나를 연결한다. 각 producer의 start/cancel/tick/completion 전체가 같은 식별을 쓰도록 한다.
5. producer마다 원격 red→green, 해당 모드 회귀, own-path commit을 완료한다. 하나가 실패하면 다음 producer를 연결하지 않는다.

**완료:** 한 활성 실행 소유자와 유효한 시도만 후보를 제출하며 늦은 callback·MANUAL 선점·slot 재사용이 시험으로 막힌다. API 노출 변경이 필요하면 schema/API reference를 함께 변경하고 새 ADR 필요 여부를 먼저 결정한다.

## P2. 곡률·최종 후보·Safety 검사 순서

**대상:** `command/manager.py`, `safety/manager.py`, `line_follow/{clearance,body_stop}.py`, gateway `core/bridge/traffic_gate.py`, `core/line_follow_wiring.py`, `contracts/foundation/core_common/`의 기존 body envelope 계산 위치.

**시험:** services `test_command_shadow.py`, `test_safety_behaviour.py`, `test_motion_admit.py`; gateway `test_line_follow_body_stop.py`, `test_line_follow_obstacle_path.py`, `test_cmd_vel_cycle.py`; 실제 body envelope의 기존 시험은 P0에서 호출자로 확인한다.

**순서:**

1. 모든 `(v,w)` cap/clip 위치와 body 검사의 선후 관계를 기록한다. 전역 곡률 상한·실물 최소 속도를 추정해서 만들지 않는다.
2. fake clock과 결정적인 장애물 좌표로 시험한다: `v` cap 후 더 작은 회전 반경이 장애물에 닿는 경우, `v≈0` pivot, 후진 부호, 복수 cap, nonfinite 입력, zero.
3. cap별 계약을 정한다. 경로 보존 감속은 공통 scaling을 검토하되 MANUAL 의미·교통 정지·Safety veto를 유지한다. 기존 envelope가 증명하는 후보 범위를 명시한다.
4. 한 경로의 최종 후보가 검증된 궤적/후보군에 속하도록 최소 수정한다. 궤적이 바뀌었고 검사가 불가능하면 zero. 50 Hz 계산에 무한 재검사·blocking I/O를 넣지 않는다.
5. 원격 red→green·Safety 독립 리뷰 후 커밋한다. 실제 timer 시간 예산·wheel saturation/odom 수용은 P5에 남긴다.

**완료:** 출력 후보가 어떤 기하 근거로 허용됐는지 설명할 수 있고, 검사 후 cap 때문에 생기는 곡률 변화가 범위 밖으로 빠지지 않는다. 모든 실행기의 동일 검사가 완료됐다고 묶어 선언하지 않는다.

## P3. 원인별 복구 수명·budget·재개

**대상:** `line_follow/recovery/stuck/{stuck_recovery,progress_watch}.py`, `stuck/realign/{mixin,recovery,manoeuvre,request}.py`, `line_follow/recovery/{lane_return,lane_bridge,motion_admit}.py`, `line_follow/cue/odom_pivot.py`; 이후 별도 변경으로 `localization/mission.py`, `docking/`.

**시험:** services `test_line_stuck_recovery.py`, `test_line_stuck_realign.py`, `test_lane_recovery.py`, `test_rotate_to.py`; gateway `test_line_follow_stuck.py`, `test_line_follow_lost_resume.py`, `test_lane_return_odometry.py`, `test_docking_mode_release.py`.

**순서:**

1. 각 문제의 원인, 현행 자동/보고/승인 동작, 센서 전제, 거리/각도/시간/횟수 제한, 실패 출구를 적는다. default-off와 보고 전용 watcher 동작은 보존한다.
2. 부모 목표와 복구 자식 시도를 기존 식별 계약에 연결한다. 같은 문제의 재진입은 budget을 늘리지 않게 시험하고 새로운 목표의 초기화는 분리한다.
3. 취소·E-stop·MANUAL 개입·lease 만료 중 복구가 출력하지 않는 시험, 실패 종료 후 zero, stale 사람 응답 폐기, 성공 뒤 pose/map revision 변경 시 재개 거절을 추가한다.
4. crosswalk/신호 대기를 장애물 탈출로 해석하지 않는 회귀를 고정한다. Nav2 recovery와 CORE 복구의 동시 소유도 금지한다.
5. KTURN은 D-607과 현행 `_back_refusal`/공간 검사를 대조한다. rear strip 밖 회전 후진 위험을 재현하는 기하 시험이 유효한지 먼저 검증한다. 실제 변경이 필요하면 후진 궤적 근거를 보강하고 별도 Safety 리뷰한다.
6. 기존 primitive를 의미가 같은 경우에만 재사용한다. OdomPivot과 rotate_to의 제어법·deadband·완료 기준은 유지한다. timeout을 실측 거리 완료로 이름만 바꾸지 않는다.
7. line-follow부터 원격 red→green과 own-path commit을 끝낸다. localization·docking은 각 수명과 실패 출구를 별도로 검증한 뒤 같은 규칙을 적용한다.

**완료:** 모든 복구는 종료·취소·한도가 있고 유효한 부모 목표로만 돌아간다. 이 단계의 source 성공은 새 자동 탈출의 현장 활성화 승인과 다르다.

## P4. CORE 공통 조립과 관측·전력 책임 정리

**대상:** gateway `core/services.py`, 기존 `core/{line_follow_wiring,fleet_loss_wiring}.py`, `core/system/runtime.py`; services `state/manager.py`, `power/{manager,battery}.py`, `diagnostics/collector.py`, `vision/`, `fleet_agent/`; `middleware/core/events/`.

**시험:** gateway `test_core_logic.py`, `test_core_node_teardown.py`, `test_core_main_shutdown.py`, `test_fleet_loss_wiring.py`, `test_bridge_battery_policy.py`, `test_battery.py`, `test_bridge_observation.py`, `test_v1_import_boundary.py`; `test/architecture/test_module_structure.py`, `test/architecture/test_safety_separation.py`.

**순서:**

1. 각 feature의 생성·설정 해석·콜백 등록·정책 실행을 구분한다. gateway에서 수행하는 정책은 해당 feature로 옮기되 transport·ROS 객체는 gateway에 남긴다.
2. 실제 크기/응집도 문제가 있는 조립만 기존 wiring 패턴으로 추출한다. `CoreServices`의 외부 attribute, 객체 identity, 생성·종료 순서와 기존 재-export caller를 보존한다.
3. state와 diagnostics가 실행기의 snapshot을 읽도록 하고 복제된 모드·복구 상태를 없앨 수 있는지 확인한다. 제거는 모든 caller를 확인한 실제 중복에 한정한다.
4. power의 측정·sentinel, Safety의 정책, host의 실제 종료를 분리한다. 충전 unknown을 false로 바꾸지 않는다. Fleet loss는 연결 상태와 주행 권한을 구분한다.
5. 이벤트/감사 sink가 실패해도 정지 경로는 실행되는 회귀를 확인한다. 서비스의 gateway/API/ROS 역방향 import와 새 writer를 구조 시험으로 막는다.
6. 행동 불변 이동과 행동 변경을 별도 커밋으로 만든다. 안전 태그 이동도 독립 리뷰한다. 원격 회귀와 harness를 통과한다.

**완료:** CORE 전체의 모듈 소유자·의존 방향이 설계 표와 일치하고 기동/종료·외부 API·정지 동작이 유지된다. 책임 표 때문에 필요 없는 새 모듈을 생성하지 않는다.

## A1. Arm 실행·Safety·복구의 별도 책임 고정

**대상:** `middleware/apps/device/omx/adapter/omx_adapter/{command_owner,ros_runtime}.py`, `middleware/apps/device/omx/agent/`, `contracts/motion/`, `middleware/execution/local/`, `middleware/skills/manipulation/`, `integrations/robots/omx/`.

**시험:** adapter의 `test_omx_command_owner.py`, `test_omx_preempt.py`, `test_omx_stop_fence.py`, `test_owner_recovery_api.py`, `test_omx_ros_goal_contract.py`, `test_omx_gripper_contract.py`; local execution의 `test_policy_parent_binding.py`, `test_native_parent_fence.py`.

1. 기존 ArmCommandOwner→ActionPort 경로의 모든 caller와 session/owner/lease/state/calibration 검사를 대조한다. 현재 preempt·cancel·recover 계약을 보존한다. action timeout, HOLD와 물리 standstill을 별도 상태로 기록한다.
2. D-442와 현재 구현의 차이를 확인하고 producer/port 이행의 남은 범위만 계획한다. BaseTwist와 arm trajectory를 한 payload로 합치거나 Arm에 NAVIGATION/DOCKING을 강제하지 않는다.
3. joint state stale·시작 자세 변경·calibration revision 변경·늦은 action 결과·다른 owner의 cancel·확인 없는 HOLD 해제의 거절을 원격 회귀로 고정한다. 필요한 변경만 red→green한다.
4. workspace 충돌·payload·파지 근거는 현행 보장 범위를 따로 확인한다. 계약/근거가 없으면 기능 비활성/인계 상태를 유지한다. 궤적 성공을 파지/배치 성공으로 바꾸지 않는다.
5. Safety 변경은 별도 독립 리뷰·trailer 후 own-path commit한다. Arm 물리 수용은 P5의 별도 Arm 시나리오로 수행한다.

**완료:** Arm 전용 계획·제어·안전·완료·복구의 책임이 분명하고 공통 실행 계약과 연결되며 Drive 구현에 의존하지 않는다.

## A2. 물리 폴더 분리 여부와 이동 계약 확정

**대상:** P0에서 만든 설계의 폴더별 책임 표, `tools/harness/platform_parts.yaml`, 관련 package/setup/entry point/launch, `test/architecture/test_platform_parts.py`, `test/architecture/test_module_structure.py`, `test/architecture/test_safety_separation.py`.

1. 같은 폴더의 책임이 실제 독립 import·시험·기동 단위로 나뉘는지 확인한다. 공통 contract를 먼저 유지하고 불필요한 facade/base class/새 프로세스를 만들지 않는다.
2. CORE 공통과 Drive가 혼재한 `core/services` 및 legacy `perception/control`의 후보를 하나씩 선정한다. `현재 경로→목적 경로→import caller→설치/launch→시험→Safety tag→호환 export→rollback` 표를 완성한다.
3. 목적 경로가 D-427/D-429의 Accepted 구조를 바꾸면 `adr_reserve.py`로 번호를 선점하고 후속 ADR에서 먼저 결정한다. 이 plan만으로 새 top-level control이나 arm 루트를 만들지 않는다.
4. 행동 불변 이동, caller 수정, manifest/패키징 갱신을 같은 변경에서 완료한다. 안전 태그 이동은 독립 리뷰한다. baseline 대비 원격 구조/import/행동 회귀를 통과한다.

**완료:** 폴더 목적과 실행 권한이 일치한다. 코드량/결합 문제가 없으면 현행 경로를 유지한 책임 정리로 종료한다.

## P5. 통합·장치·물리 수용

1. committed candidate SHA를 고정하고 관련 services/gateway/architecture/API suite를 원격에서 실행한다. 기존 중복 basename 제약을 유지하고 모든 로그를 known_failures로 비교한다.
2. `python tools/harness/rosy_harness.py generate`와 `lint`를 수행한다. 변경한 공개 필드가 있다면 API reference/schema와 독립 계약 시험을 확인한다.
3. `python tools/remote/remote_pytest.py --pick sim`으로 선택된 PC에서 별도 ROS-SIM 시나리오를 실행한다: 모드 교체 중 늦은 Nav2 입력, 차선 상실·진전 없음, pivot/후진 공간 부족, 복구 중 취소·센서 stale, 도킹 staging 전환, 명령 deadman.
4. 별도 승인된 장치 절차로 ARM64 후보 이미지·설치 SHA·설정·활성 정책을 readback한다. 실제 E-stop/readiness를 시험 통과 목적으로 해제하지 않는다.
5. 승인된 현장 주행에서 직선·곡선·저속·후진·pivot·장애물 정지·사람 개입·복구 실패 인계를 확인한다. `(v,w)` 발행, odom, 목표 종단, 물리 관측을 함께 남긴다. Safety 변화가 없는지 보기 위한 reset/모션을 임의로 보내지 않는다.
   Arm은 별도로 승인된 시나리오에서 목표 관절 도달, HOLD/정지 readback, 작업공간/하중/파지 근거, 취소·재개를 검증한다. 복합 로봇 동시 Drive/Arm은 승인된 coordination·결합 안전 계약 없이는 시험 활성화하지 않는다.
6. 실패한 tier는 HOLD로 남긴다. `docs/validation/` 기록과 해당 progress/log를 실제 확보한 증거만으로 갱신한다.

**완료:** SOURCE, ROS-SIM, ARTIFACT, DEVICE, FIELD를 구분해 필요한 수용이 충족된다. 시험 PC·실물·독립 리뷰가 없으면 그 단계는 미완료다.

## 이번 문서 작업의 검증 범위

이번 변경은 이 두 문서, append-only docs log, progress의 plan 목록과 생성 docs index에 한정한다. module code·API·config·Safety 활성 상태를 바꾸지 않는다. 문서 링크/경로 확인, harness generate/lint, 원격 문서 계약 시험을 수행하고 결과를 로그에 기록한다. 전역 progress의 수용 gate는 올리지 않는다.
