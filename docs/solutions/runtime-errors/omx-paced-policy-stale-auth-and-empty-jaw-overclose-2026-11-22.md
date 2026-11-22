---
title: Paced ACT pre-auth state refresh and empty-jaw floor prevent state_unavailable refusals and false empty-jaw human-hold
date: "2026-11-22"
category: runtime-errors
module: deploy/robot/omx (cell_policy_handoff.py, chunk_runner_settle.py, cell_job_spec.py)
problem_type: runtime_error
component: chunk_runner
severity: high
root_cause: logic_error
resolution_type: code_fix
symptoms:
  - "run_paced_chunks passed pre-inference status to authorize(...); CPU ACT inference (> MAX_GAP_S = 0.5 s) caused operating envelope refused: state_unavailable before load"
  - "During arm_s policy execution with target[5] = 46.5..46.67 (< gripper_closed = 48.5) and physical empty-jaw stop at 48.86..48.99, present[5] > target[5] + EMPTY_MARGIN (2.0) falsely armed _held_jaw / _release_floor, refused park with release not confirmed by jaw feedback, and latched human-hold"
  - "CPU ACT inference with default --max-obs-age-s 0.6 refused run policy with stale policy observation until --max-obs-age-s 2.0 (matching cell_task_act.py / act_policy.max_obs_age_s) was supplied"
tags: [omx, arm-s, paced-chunks, authorization, chunk-runner, gripper-closed, jaw-empty-stop, human-hold]
applies_when: "running full-chunk ACT policies with run_paced_chunks / --paced-chunks or checking gripper holding and release confirmation in chunk_runner_settle.py"
---

# Paced ACT 인가 전 상태 갱신과 빈 집게 바닥값 적용으로 `state_unavailable` 및 오탐 `human-hold`를 방지한다

## 증상과 원인

1. **추론 전 `state` 재사용으로 인한 `state_unavailable` 거절 (`cell_policy_handoff.py`)**
   - `run_paced_chunks()`는 루프 시작 시 `status = cell.act("state")`를 읽은 뒤 카메라 수신·추론(`shadow.infer`)·청크 성형(`shape_chunk`)을 수행하고, 그 오래된 `status`를 그대로 `authorize(lib, status, ("run policy", "park"))`에 전달했다.
   - `cell_envelope.assess()`의 `_state_current()`는 `0 <= now - state["t"] <= MAX_GAP_S`(`0.5 s`)를 요구한다. 셀 호스트의 CPU ACT 추론이 `0.5 s`를 넘기면(`live3` 실측 `t = 1795348513.035 -> 1795348513.773`, 약 `0.74 s`), 동작은 시작도 못 하고 `operating envelope refused: state_unavailable`로 거절되었다.
   - 또한 `--max-obs-age-s` 기본값 `0.6`에서는 CPU 추론 후 `time.time() - oldest_stamp > max_obs_age_s`가 초과되어 `stale policy observation`으로 안전 주차(`park`)한다. (`cell_task_act.py`는 `act_policy.max_obs_age_s` 기본 `2.0`을 명시적으로 전달한다.)

2. **정책 목표 집게 각도(`46.5` < `gripper_closed = 48.5`) 대비 빈 집게 물리 정지(`48.86..48.99`)의 `holding` 오탐 (`chunk_runner_settle.py`)**
   - `arm_s`의 `chunks-arm-s-master-shuttle.json`은 파지압 확보를 위해 `46.5`를 명령하지만, 빈 집게의 물리적 정지 위치는 `48.86..48.99`이고 라이브러리의 `gripper_closed`는 `48.5`이다.
   - `confirm_grip_release()`와 `check_chunk_settled()`가 `sent_grip` / `runner.target[5]`와 `present[5]`를 직접 비교해 `48.99 > 46.5 + 2.0`(`EMPTY_MARGIN = 2.0`) 조건이 참이 되었다. 빈 집게인데도 `_held_jaw`와 `_release_floor`가 래치되어 이후 `park`가 `"release not confirmed by jaw feedback"`으로 실패하고 `human-hold`로 잠겼다.
   - 정책 목표를 `gripper_closed` 위로 클램프하면 실제 물체 파지압이 약해지므로 목표값 클램프는 해법이 아니다.

3. **`cell_job_spec.py` 옵션 누락**
   - `JOBS["cell_policy_drive"]["optional"]`에 `paced_chunks`가 없어 job API 경로에서 `--paced-chunks`를 선택할 수 없었다.

## 수정

- **`deploy/robot/omx/cell_policy_handoff.py` (`run_paced_chunks`)**:
  - `authorize(...)` 호출 직전에 `auth_status = cell.act("state")`로 최신 상태를 다시 읽는다.
  - `auth_status.get("ok")`, `auth_status.get("fault")`, `isinstance(auth_status.get("state"), list)`를 먼저 검증한다.
  - `jaw_spec`이 있을 때 `auth_status`의 현재/목표 포즈로 `jaw_zone_error` 및 `in_jaw_zone(..., force_all=True)`를 재검사해 추론 중 팔 드리프트에도 `jaw_gate`가 약화되지 않게 한다.
  - 카메라 관측 시각 `oldest_stamp`는 갱신하지 않아 stale observation 검사는 원 관측 시각 기준으로 유지한다.
- **`deploy/robot/omx/chunk_runner_settle.py` (`_empty_jaw_floor`, `confirm_grip_release`, `check_chunk_settled`)**:
  - `_empty_jaw_floor(runner) -> float | None`을 추가해 `library_gripper_closed(lib)`와 유한 범위(`[-100.0, 100.0]`, `OverflowError`·`bool`·비유한값 방어)의 `jaw_empty_stop` 중 최댓값을 계산한다. 부분/모의 라이브러리의 유효하지 않은 `gripper_closed`에는 `None`을 반환한다.
  - `confirm_grip_release()`는 `grip_ref = max(sent_grip, floor)`를 사용해 빈 집게 물리 바닥값 이하의 목표를 명령해도 `_held_jaw`가 오탐 래치되지 않게 한다.
  - `check_chunk_settled()`는 `policy_closed` 판정에서 `policy` 청크의 fail-closed `library_gripper_closed(runner.library)` 검증을 유지하면서, `grasp or policy_closed`와 `elif runner.holding` 분기에 단일 `grip_floor = max(float(runner.target[5]), empty_floor)`를 적용한다.
- **`deploy/robot/omx/cell_job_spec.py`**:
  - `cell_policy_drive`의 `optional`에 `"paced_chunks": _bool`을 추가하고 `mode != "act"` 또는 `n_action` 병용 시 거절하며 `--paced-chunks`를 전달한다.

## 검증과 복구

- **단위·안전 시험 (커밋 `be15e3b2f1`, 병합 전 대기 PR)**:
  - 독립 D-430 리뷰 완료(`Safety-Review: research-9032cbc3`), `safety_review.py` · `size_range.py` 통과.
  - 원격 pytest (`omx_hotfix.py test`, OMX 10개 스위트): **`389 passed in 5.28s`** (`test_omx_policy_drive.py`, `test_omx_cell_job_api.py`, `test_omx_control_modularization.py` 400줄 미만 가드 포함). 구조·설정 추가 스위트 **`207 passed`** (`test_module_structure.py`, `test_omx_policy_config.py`).
- **실물 `arm_s` 검증 (격리 링크 `omx-paced-current -> omx-tools-be15e3b2f1`)**:
  - **버그 #1 및 observation age 가드 확인 (`live3`, 에피소드 `20261122-205512-belt-to-goal`)**: 추론(`~0.74 s`) 후 `state` 재조회로 `authorize`·`checked ... load`(`ok: true`) 통과(`state_unavailable` 미발생), 기본 `--max-obs-age-s` 기준 `"stale policy observation"` 거절 후 `run park`(`ok: true, settled: true, holding: false`) 및 `torque_off_confirmed: true` 확인.
  - **전 구간 1청크 완주 + 버그 #2 해소 (`live4`, 에피소드 `20261122-205853-pinky-to-goal`, `--max-obs-age-s 2.0 --site pinky --max-chunks 1 --paced-chunks`)**: `run policy`가 `target[5]=46.67`, `state[5]=48.86`에서 **`ok: true, settled: true, holding: false`**로 완료되었고(`human_hold_latched: false`), 이어진 `run park`가 **`ok: true, settled: true, holding: false, parked: true`**로 홈 정착 및 정상 `stop`(`safe_end: true`, `torque_off_confirmed: true`, `caps_restored: true`, `hardware_faults: {}`)으로 종료되었다.
  - **Gate 3 변환·업로드 계약 검증**: `20261122-205853-pinky-to-goal`(`top=627`, `arm_s_wrist=625`, `outcome=unknown`)을 `episode_recorder.py convert`로 변환해 `1 episodes`, `total_frames=2079`, `fps=30`, `robot_type="omx_follower"` 및 루트 `rosy_provenance.json`(`source_kind="policy"`)을 생성했고, 8개 산출 경로 모두가 `experiment_lerobot_source.allowed()`와 `imitate.js` 경로 정규식을 통과했다.
- **이미 `human-hold`에 걸린 세션 복구 절차**:
  1. 벤치에서 사람이 물리적 지지/이상을 확인하고 해제 안전을 확인한다.
  2. `record_session.py`로 실행한 `chunk_runner` PID에만 **`kill -USR2 <chunk_runner_pid>`**를 보내 정식 해제(`released.json` 기록 및 `torque_off_confirmed: true` 종료)를 유도한다. 프로세스를 강제 종료(`SIGKILL`)하거나 토크를 임의로 끊지 않는다.
  3. Fleet incident가 정리된 뒤 셀에서 `omx_incident.sync_hold_from_fleet('arm_s')`(또는 API/CLI 상태 동기화)로 로컬 `HOLD-arm_s.json`을 해제하고, `omx_incident.py status --arm arm_s`의 `local_held: false, fleet_held: false`를 확인한다. `HOLD-*.json`을 수동 삭제하지 않는다.

## 재발 방지 적용 조건

- `run_paced_chunks` 또는 유사 루프에서 추론·I/O 지연이 `MAX_GAP_S`(`0.5 s`)에 근접하거나 넘을 수 있으면 `authorize()` 직전 `state` 재조회 + fault/`jaw_zone` 재검증을 유지하고, CPU 추론 셀에는 `--max-obs-age-s 2.0` 등 운영 허용 한도를 명시적으로 전달한다.
- 빈 집게 물리 정지 각도(`gripper_closed` / `jaw_empty_stop`)보다 더 닫는 목표각을 명령하는 라이브러리에서는 `holding` 및 릴리스 하한 계산에 반드시 `_empty_jaw_floor`를 사용한다.
