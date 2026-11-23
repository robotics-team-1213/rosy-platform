---
surface: cell
kind: additive
slug: omx-cell-job-api-two-arm-policy
date: 2026-11-23
title: OMX Cell Job API (v1.next) 두 팔 원격 정책 작업(`cell_two_arm_policy`) 통합
history: Additive: POST /jobs/cell_two_arm_policy, 두 팔 직렬화·준비 게이트(409 TWO_ARM_NOT_READY), dual cell-state-dirty 기록
---
- `:8781` `cell_job_api.py` / `cell_job_spec.py`에 D-1073 두 팔 원격 GPU 정책 실행 잡(`cell_two_arm_policy` → `cell_two_arm_policy_cli.py`)을 추가합니다.
- **실행·인증 게이트:**
  - `dry_run: true`는 무동작(`moves_arm = False`)으로 `cell-job-human`·`cell-job-machine` 모두 허용되며, 라이브 모션은 `cell-job-human` + `person_at_switch: true` + distinct `proposer != operator` (D-1024) + `./with-session-arm-a-par.sh`·`./with-session-arm-b-par.sh` 이중 래퍼가 필수입니다 (`cell-job-machine`의 라이브 시도는 `403 MACHINE_COMMISSIONING_FORBIDDEN`).
  - 비루프백 `endpoint_url`은 `token_file` 필수이며 `task_a`·`task_b`의 비-`belt` 사이트 중복과 AMR 적재함 사이트(`pinky`/`bed`/`tray`) 라이브 모션은 400으로 거부됩니다.
- **두 팔 상태·잠금 직렬화:** 라이브 `cell_two_arm_policy`는 `arm_a`·`arm_b` 양쪽 `incident`·`fleet` 안전·`session-arm_{a,b}.lock`·`check_two_arm_ab_ready`(`409 TWO_ARM_NOT_READY`)를 함께 검사하고, 진행 중 `arm_a`/`arm_b` 단일 팔 이동 잡과 상호 배타로 잠기며 시작·종료 시 양팔 `cell-state-dirty-arm_{a,b}.json`을 함께 기록합니다.
