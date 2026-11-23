---
module: deploy/robot/omx
tags: [omx, act, cell_b, safety-guard, paced-chunks, dry-run, peer-folded]
problem_type: design-pattern
applies_when: Running sim-unit ACT policies on dual-arm OMX cells or recovering stale peer telemetry
---

# Cell B Sim-ACT 실행 경로의 다섯 가지 불변 조건

## 증상

`arm_b` sim-unit ACT 체크포인트(`default` / `s01`)를 작업셀 API(`cell_policy_drive`)에서 실행하면 다섯 겹의 차단이 잇달아 발생했다:
1. `idle_park`(`home`)에서 바로 추론하면 `default` 모델이 실기 `idle`(`lift=-68.0`)로 수렴해 기구 한계(`-63.3`)를 친다.
2. 전개 이송(`lift > -50`, `elbow < 45`) 중 `wrist_roll`이 라이브러리 허용 범위 안에 있어도 `wrist_roll_warning`이 두 갈래 사이각으로 오탐한다.
3. 작업 위치(`beltend` -> `pallet` 2층)와 어긋난 구형 청크 라이브러리 및 `SimPolicy` 속성 부재로 적재/추론 경로가 깨진다.
4. sim-unit ACT 스텝 속도(`28~45 units/s`)가 실기 가드(`GUARD_UNITS_PER_S = 5.0`)를 넘어 `--paced-chunks` 없이 구동할 수 없고, 원격 추론(`--endpoint-url`, `--token-file`, `--timeout-s`, `--arm-id`) 배선이 빠져 있었다.
5. 상대 팔 `live.json`이 오래돼 `PEER_ARM_NOT_FOLDED`로 막히거나, `chunk_runner`가 없는 `dry_run` 요청이 `"no runner"`로 실패한다.

## 검증된 불변 조건과 해결

### 1. `entry` 브리지 + 실기 `jaw_gate` + `entry` 이후 사후 검증 후 `check_home=False`
- `idle_park` -> `canonical_start`로 이어지는 `"entry"` 청크를 먼저 실행한 뒤에만 `Authorization(..., check_home=False)`로 정책 루프(`run_timed`, `run_paced_chunks`)를 시작한다.
- `validate_entry_chunk`는 `chunks.entry`의 6축 유한성, `[-100, 100]` 범위, `home[-1]` 시작 오차(`ENTRY_START_TOL = 2.0`), `jaw_zone_error`를 확인한다. `-100..100`과 `GUARD_UNITS_PER_S = 5.0` 속도·계획 검증 및 `load` 시점 무결성은 `Authorization`과 `chunk_runner`의 `load_library`가 강제한다.
- `run_entry_chunk`와 `chunk_runner`(`chunk_runner_commands.py`, `chunk_policy_playback.py`)는 `grasp_pick`/`rim_z_m`가 있는 라이브러리에서 `run entry`에도 실기 `jaw_gate`를 적용한다.
- `run_entry_chunk` 완료 후에도 `run_timed`·`run_paced_chunks` 모두 `entry[-1]`(`ENTRY_START_TOL`) 정지 위치와 빈 그리퍼를 다시 확인한 뒤에만 청크 0 `check_home=False`를 허용한다. `dry_run`에서는 `entry_pose`를 초기 상태로 시드한다.

### 2. `wrist_roll_warning`의 전개 이송 예외는 보간 후(`shape_chunk`) + 유한/정렬된 `roll_range`로 한정한다
- 라이브러리 메타(`roll_range`)가 유한·정렬(`lo <= hi`)될 때만, 팔이 펼쳐진 상태(`(arr[:, 1] <= -50.0) | (arr[:, 2] >= 45.0)`이 거짓)이고 `wrist_roll`이 `[lo, hi]` 안에 있는 프레임의 중간각 경고를 면제한다. `NaN`/무한대/잘못된 `roll_range`는 즉시 거부한다.
- 단일 팔(`cell_policy_drive.py`, `cell_policy_paced.py`)과 양팔(`cell_two_arm_policy.py`) 모두 `shape_chunk` 보간 뒤 최종 프레임에 대해서도 `wrist_roll_warning`을 검사해 접힌 상태 보간 중 회전 스위프를 차단한다. `envelope()` 역시 비유한/`bool` 값을 거부하고 단일 행 청크에서는 `GUARD_UNITS_PER_S / fps` 상한을 사용한다.

### 3. 작업 구간과 일치하는 청크 라이브러리 + 물리 팔 바인딩 + 섀도 정리
- 작업 위치(`beltend` 픽업 / `pallet` 2층 적재)와 `jaw_gate_spec`이 일치하는 검토 완료 라이브러리(`chunks-arm-b-beltend-ship-t2-canon.json`)를 사용한다.
- `cell_policy_drive.py`는 `--arm-id`가 설정(`config.arm_id` / `operating_profile_path` `instance_id`)과 다르면 거부해 잘못된 원격 팔/체크 우회를 막고, 로그에는 자격증명/쿼리를 제거한 URL만 남긴다.
- `RemotePolicyShadow`는 자격증명/쿼리 URL을 거부하고 `/health` 검증 실패 시 소켓을 닫으며 `close()` 후 재오픈을 막고, `run_timed`는 종료 전 비행 중 `pending` 워커를 배수한다.

### 4. sim-unit ACT는 `--paced-chunks` + 원격 추론 플래그로 실행한다
- `cell_policy_drive.py`와 `cell_job_spec.py`에서 sim-unit 체크포인트에 `--paced-chunks`와 `n_action` 지정, `--max-chunks` 60 상한, `--endpoint-url`/`--token-file`/`--timeout-s`/`--arm-id` 전달을 허용한다.

### 5. `PEER_ARM_NOT_FOLDED` 및 `dry_run` 상태 조회는 fail-closed를 지킨다
- `cell_job_guards.py`: `live.json`의 타임스탬프 `t`가 누락·비유한·오버플로·미래 값(`_is_stale_row`)이면 stale 판정을 내리지 않는다. 타임스탬프가 유효하게 만료(`age > max_age_s`)되고 `human_hold_latched`·lock·lease가 없을 때만, 신선하고 무결함·무토크인 `motor-health/<peer>.json`과 **실제 팔로워 캘리브레이션(`{peer}_follower.json`의 `drive_mode==0`, `homing_offset==0`, `0<=range_min<range_max<=4095`)**으로 접힘 상태를 확인한다. 캘리브레이션이 없거나 어긋나면 fail-closed 한다.
- `cell_pipeline_io.py`: `ENOENT`/`ENXIO`만 `"no runner"`로 반환하고 `EACCES`/`EPERM` 등 다른 I/O 오류는 별도 `fifo io error`로 격리해 `dry_run`이 권한 오류를 가리지 않게 한다. `cell_policy_paced.py`의 `dry_run` 대체 상태는 `_pose6()` 검증을 통과한 시드/`home[-1]`만 사용한다.

## 확인 결과

- 3자 병렬 독립 리뷰 패널(`agy-pro`·`codex`·`opencode` 부분 패널) 소견(`P-01`~`P-10`)을 모두 코드·회귀 시험·D-430 재검토로 해결·검증했다.
- 실물 토크 인가 및 이동은 사람 작업자의 D-911 `person_at_switch: true` 확인 전까지 별도 게이트로 보류한다.
