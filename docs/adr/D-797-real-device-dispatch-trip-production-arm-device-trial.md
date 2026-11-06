## D-797 실물 하달을 연다: 운행(`TRIP`)은 `production`, 팔(`CELL_TRANSFER`)은 새 프로필 `device_trial`에서 장치 증거로만

**Status:** §2·§3 Accepted (2026-11-04, 사용자 결정: "우리가 실제로 이제 동작해야 하는 시간", "ROSY 실물 ARM 경로를 지금 열기 시작". D-858 S4). 나머지 절은 Proposed다: §1(`TRIP`의 `production` 개방, 실물 Pinky 조건이 달라 이번에는 결정하지 않음), §4·§5(인계 장벽·카메라 근거, 이번 범위 아님), §6·§7(D-858 S1·S3가 만든 실물 port·정지 래치·커미셔닝 관문이 이미 담는 범위, 아래 「S4 as built」), §8(팔 착지 증거, S5). 원래 목표는 2026-11-21 시연(실물 Pinky 운반 + 실물 OMX 1대 셀 작업). §2·§3이 Accepted가 되어 D-403(시뮬레이션 범위)·D-390 §5(시뮬레이션 identity)·D-336 §1·§3의 Status 머리에는 이 결정을 적는다. 구현·시험은 있으나 실물 동작 수용(S5)은 없다.

### Context

- 등록부 `operations/fleet/fleet/server/step_action_kinds.py`의 두 종류는 모두 `open_profiles={"simulation"}`이다(`CELL_TRANSFER` :64, `TRIP` :75). 주석은 "SIM until device proof"다. 배포 프로필은 `production`·`simulation` 둘이다(`app.py:89`).
- 운행: D-763 조각 6(단계 사이 작업 lease, CORE `trip_lease.py`의 `job_id`)과 조각 7(trip 작업)은 main에 있다. 막는 것은 등록부 한 줄과 D-763 6항의 장치 조건뿐이다.
- 팔은 한 줄로 열리지 않는다.
  1. **identity:** `StepJobDispatcher`는 owner가 `simulation: true`를 보고하지 않으면 `NOT_SIMULATION`이다(`step_dispatcher.py:150`, `_simulation_identity` :192). 다팔 `ArmJobDispatcher`는 이것을 상속하고 다시 정의하지 않는다(`cell/cell_arm_dispatcher.py:221`). 단일 팔 쪽만 고치면 다팔도 같이 열린다.
  2. **목표 증거:** 셀 경로는 출처 `sim_model_pose`만 받는다(`cell/cell_arm_store.py:380`, `cell/cell_job_store.py:837`, 공개 입구 `app.py:234`는 `simulation`에서만). 실물에서는 증거가 없어 모든 단계가 `ACTION_SUCCEEDED`에서 HOLD된다(D-328 §4). gripper `OPEN` 증거도 요구된다(`cell_job_store.py:833-839`).
  3. **인계 장벽:** D-328 §2는 장치 사이 인계를 "실제 적재/보유 관측"으로만 연다. main에는 집기 전 source 관측 장벽이 없고 작업 뒤 `item_at_pose` 판정만 있다.
  4. **owner:** `run_cell_owner.py`는 "Simulation only; not a device entrypoint"이고 `omx_cell_owner.py`는 `simulation: True`를 고정으로 보고한다. 실물 owner 진입점이 없다.
  5. **장치 상태:** 실물 OMX는 토크를 켜고 자율로 움직인 적이 없다(`docs/validation/omx-independent-stop-2026-10-16`, `omx-remaining-preparation-2026-10-17`). D-770 커미셔닝이 진행 중이다.
- 다팔(D-778 Proposed)과 팔별 원장(D-779)이 같은 셀 코드를 바꾸는 중이다.

### Decision

1. **운행은 `production`에서 연다.** 등록부 `TRIP` `open_profiles`에 `production`을 더한다. 착지 조건은 실물 Pinky에서의 D-763 6항 장치 확인이다: 단계 사이 주인 아닌 `/teleop` 409, 넘겨받기 통과, 사람 정지 → 작업 HOLD, lease 만료 → 정지. 항목마다 3회, 1회 실패면 불합격. 증거는 `docs/validation/trip-jobs-device-<date>/`. 플래그 변경은 그 증거와 같은 PR에 있다.
2. **팔은 새 배포 프로필 `device_trial`에서만 연다.** `production`은 "수용 완료"의 뜻으로 남긴다. `DEPLOYMENT_PROFILES`에 `device_trial`을 더한다. 프로필은 Fleet 프로세스 전체에 걸리므로 `device_trial`은 `TRIP`도 연다(실물 Pinky와 실물 팔이 한 Fleet). 프로필 검사는 대부분 `!= "simulation"` 꼴이라 `device_trial`은 시뮬레이션 전용 경로(`sim_model_pose` 등)를 열지 않는다.
3. **실물 identity 계약.** owner는 `device: true`와 커미셔닝 revision(D-770 수용 기록의 id)을 보고한다. Fleet은 `device_trial`에서 그 둘이 설정된 값과 같을 때만 단일 팔 단계를 하달한다. 다팔 `ArmJobDispatcher`는 `_simulation_identity`를 다시 정의해 계속 `simulation`만 받는다. identity 캐시는 경로마다 따로 둔다. 다팔이 `device_trial`에서 `NOT_SIMULATION`인 것은 시험으로 고정한다. 다팔 실물 개방은 D-778/D-779가 정한다.
4. **하달 전 인계 장벽.** 운반 로봇 위 물체를 작업대 `top` 카메라(D-794)가 관측해야 첫 팔 단계(step 0)가 하달된다. 관측은 등록된 producer가 `POST /api/fleet/cell-source-observations`로 보내고, Fleet이 그 단계의 `source_pose_base`와 저장된 술어의 허용오차·물체 중심 오프셋으로 판정한다. 관측이 없으면 단계는 READY로 기다린다(`NO_SOURCE_OBSERVATION`). 물체·위치가 다르면 아무것도 저장하지 않고 Job을 HOLD한다(`CELL_SOURCE_WRONG_ITEM`·`CELL_SOURCE_NOT_AT_POSE`). 통과한 관측은 producer의 `source_max_age_s`(기본 2초, 최대 5초) 동안만 유효하고, 하달기가 grant 직전에 한 번만 소비한다. 미래 시각, 오래된 관측, Job의 마지막 변화(HOLD·재개 등)보다 이른 관측은 거절한다. 인계 위치는 지그로 고정한 정차점이고 `source_pose_base`는 그 고정값이다. 고정값은 위치 입력이지 증거가 아니다. 프레임과 집기 사이에는 유효 시간 + grant TTL + 동작 시간의 틈이 남는다.
5. **실물 목표 증거.** 새 출처 `camera_item_pose`: `top` 카메라 마커 관측을 카메라→`robot_base` 외부 보정으로 옮긴 물체 포즈다. 보정 revision과 프레임 시각을 함께 기록한다. `item_at_pose` 판정과 gripper `OPEN` 증거는 지금과 같다. 셀 경로의 `sim_model_pose` 하드코딩은 프로필별 허용 출처 표로 바꾼다(`simulation` → `sim_model_pose`, `device_trial` → `camera_item_pose`). 단일 팔 단계 술어는 컴파일 때 그 출처를 고정하고, 다른 출처의 증거는 판정에서 떨어진다(`source`). producer 항목은 출처와 보정 revision(`evidence_revision`, 카메라는 필수)을 고정하고, 다른 값의 증거는 거절한다. 다팔 술어와 저장은 계속 `sim_model_pose`다. 운영자 확인은 성공 증거가 아니다(D-328 §1·§4).
6. **실물 owner.** 작업대마다 native systemd 서비스 하나(D-336 §1·§3), 시리얼 owner 하나(D-299), Fleet과 같은 호스트의 UDS. 호스트 간 하달은 계속 HOLD다(D-336 §5).
7. **안전 한계.** `device_trial` owner는 속도·토크 상한을 설정에서 읽고, 넘는 계획은 거절한다. 다시 가동(rearm)은 사람만 한다. 통신 watchdog이 끊기면 정지한다(D-330).
8. **팔 착지 조건.** D-403 §7 (a)–(i)를 실물 OMX에서 항목마다 3회((g)·(h)는 장애 주입), S1 입고 종단 3회 연속, 그리고 물리 E-stop 위치·담당·시연 전 동작 확인, 작업 구역 구획, 토크 OFF 시 처짐·낙하, 지그·Pinky 간섭, 그리퍼 끼임 확인. 증거는 `docs/validation/cell-transfer-device-trial-<date>/`. `CELL_TRANSFER` `open_profiles`의 `device_trial`은 그 증거와 같은 PR에 있다.

### S4 as built (2026-11-04)

- **프로필:** `DEPLOYMENT_PROFILES`에 `device_trial`. `TRIP`과 `CELL_TRANSFER`의 `open_profiles`에 `device_trial`을 더했다. `production`은 둘 다 닫힌 채다. `StepJobDispatcher`는 장치 Action(grant 모델이 있는 종류)이 하나도 열리지 않은 프로필로는 만들어지지 않는다(운행만 열린 프로필이 하달기를 열지 못함).
- **순서 변경:** 원문 §8은 `CELL_TRANSFER`의 `device_trial` 개방을 장치 증거 PR에 두었다. 사용자 결정으로 개방은 S4에서 하고, 증거(S5)는 실물 동작 수용으로 남는다. 안전은 identity 관문과 owner 쪽 닫힘이 맡는다: 현재 하드웨어 owner는 `goals_enabled: false`·Action runner 비활성이라 SubmitAction을 거절하므로, 이 변경만으로 팔은 움직이지 않는다.
- **identity(§3):** `device_trial` 하달기는 grant revision에 `commissioning_revision`(비어 있지 않은 문자열)을 더 요구하며, 이 값은 grant에 들어가지 않는다. owner가 `device: true`, `simulation`이 아님, 같은 `instance_id`·`workcell_id`, 설정과 같은 `commissioning_revision`을 보고할 때만 하달한다. 아니면 `NOT_DEVICE_IDENTITY`로 READY에 머문다. 단일 팔 하달기와 다팔 하달기는 캐시를 따로 쓰고, 다팔은 `device_trial`에서도 `NOT_SIMULATION`이다(시험으로 고정).
- **owner 쪽:** 하드웨어 owner는 `commissioning_root`가 설정될 때만 `GetOwnerIdentity`에 `device`·`commissioning_revision`을 매 요청 읽어 싣는다(`CommissioningStore.revision()`, D-858 S3). 기록이 없거나 비었거나 읽히지 않으면 `device: false`. 설정이 없으면 두 필드가 없다.
- **§6·§7:** 실물 port의 속도 한계(`velocity_limits`), 정지 래치와 사람만의 rearm(`rearm`은 더 새 authority/generation 필요), 정지 시 토크 유지는 D-858 S1이 `real/dynamixel_port.py`에 이미 구현했다. 호스트 간 하달 HOLD(D-336 §5)도 기존 경로다. 통신 watchdog 정지(D-330)와 토크 상한 설정, 실물 owner가 목표를 받는 진입점은 이 변경이 새로 확인하지 않았으므로 S5 전 확인 항목이다.
- **목표 수용을 열기 전 과제(독립 검토 지적):** 통과한 identity 응답이 10초 캐시되고 revision은 grant에 들지 않으므로, 그 사이 재커미셔닝된 owner에 grant가 갈 수 있다. owner가 목표를 받기 시작하기 전에 owner가 제출 시점에 현재 revision을 대조하도록 하거나 캐시를 줄여야 한다. 지금은 owner가 목표를 거절하므로 무해하다. `device_trial`에서는 `TRIP`도 열리므로 운행 루프가 실물 Pinky를 구동할 수 있다(§2 원문대로, 프로필 이름이 유일한 관문).
- **알려진 공백(S5 전):** §4 인계 장벽과 §5 `camera_item_pose`가 없다. 셀 경로의 목표 출처는 `sim_model_pose`뿐이라 `device_trial`에서는 모든 단계가 `ACTION_SUCCEEDED`에서 HOLD된다. 하달 전 인계 확인은 사람 입회로 대신하며, 설계는 D-977(Proposed)이다.

### 되돌리기

1. 사이트 정지(D-330)와 진행 phase UUID 취소. 2. owner 정지 래치 확인. 3. `open_profiles`에서 프로필을 빼고 다시 배포·재시작. 4. 열린 작업이 UNKNOWN/HOLD(`FLEET_PROFILE_CLOSED`)이고 자동 재하달이 없는지 확인. 5. 물체 보유가 불명이면 사람이 그리퍼를 풀고 칸을 정리한 뒤 reconcile한다. "되돌리기 전 진행 중 Action 0"과 "닫힌 프로필의 열린 작업 HOLD"는 시험으로 지킨다.

### 일부러 하지 않는 것

- 다팔·팔별 원장 실물 개방(D-778·D-779 몫), 움직이는 운반 로봇에서 집기, 호스트 간 하달, 학습 정책 실행(D-793).
- `production`에서 팔을 여는 것. 시연 뒤 수용 기록이 쌓이면 따로 정한다.

### 열린 항목

- `camera_item_pose`의 wire 모양과 허용오차 기본값(포트 구현 때 D-18에 따라 API Reference·schema·생산자/소비자 시험과 같이 확정).
- 커미셔닝 revision의 출처 파일과 형식(D-770과 맞춤).
- D-779 담당과의 합의: 11/14까지 팔별 원장 원본 전환 보류, 또는 그 브랜치 위 회귀.

### Consequences

- 운행은 수용된 증거로 `production`에서 돈다. 팔은 `device_trial` Fleet에서만 돈다.
- 시뮬레이션 경로와 시험은 그대로 남는다.

### Validation

- SOURCE: `operations/fleet/test/test_job_trip_steps.py`(운행 프로필), 등록부·dispatcher identity·증거 출처 표 단위 시험, 다팔 `NOT_SIMULATION` 고정 시험.
- DEVICE: 위 1·8항의 `docs/validation/` 기록.

**References:** D-273, D-299, D-328, D-330, D-336, D-390, D-403, D-763, D-770, D-778, D-779, D-793, D-794.
