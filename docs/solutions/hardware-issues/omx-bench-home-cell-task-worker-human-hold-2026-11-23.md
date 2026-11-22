---
title: "OMX 작업대 홈 이동 중 cell-task-worker의 human-hold 간섭으로 HOLD(75) 보류 발생"
date: "2026-11-23"
module: "deploy/robot/omx (bench_record_guard, bench_record_ops, bench_record_manual)"
problem_type: hardware_interlock
component: omx-bench-record
severity: high
symptoms:
  - "rosy-arm-cell 작업대 웹 UI에서 arm_a/arm_ab 홈 이동 시 `arm_a 홈용 record_session이 정상 종료되지 않았습니다 — 사람이 팔 상태를 확인하세요 (유닛 복원·idle 보류)` 오류로 멈추며 UI 상단에는 `리더가 움직입니다 — 손을 대지 마세요` 상태가 유지된다."
  - "`home-arm_a.log`에 `{\"command\": \"human-hold\", ...}`, `RUNNER_HELD (pid=148690)`와 함께 `chunk_runner.py`가 exit 75(`HOLD`)로 남고 토크 ON 상태로 임대 락이 유지된다."
root_cause: orchestration_gap
resolution_type: bugfix
tags: ["omx", "bench_record", "go_home", "cell-task-worker", "human-hold", "runner-held"]
---

# OMX 작업대 홈 이동 시 `rosy-omx-cell-task-worker`의 `human-hold` 간섭 차단

## 증상

2026-11-23 `rosy-arm-cell`에서 작업대 웹(`:8771`)을 통해 `home-arm_ab`를 실행하자 `arm_a` `chunk_runner.py`가 정렬 완료(`start ok`) 직후 `108ms` 만에 `{"command": "human-hold", "fault": "human hold"}`를 수신하고 exit 75(`RUNNER_HELD`)로 종료했다.
그 결과 `.bench-manual-check.json`이 생성되고 멈춘 systemd 유닛 복원 및 `idle` 복귀가 안전하게 보류되었으나, 기존 UI는 `status=="homing"` 문자열 때문에 `"리더가 움직입니다 — 손을 대지 마세요"`를 그대로 표시했고 원인과 PID·복구 절차를 보여주지 못했다.

## 원인 (`home-arm_a.log` 및 `cell-task-worker` journal로 확인)

- `rosy-omx-cell-task-worker.service`는 1.5초 주기로 `rosy-fleet-r.local:8443` 안전 목록을 폴링하며, 통신 타임아웃 시(`TimeoutError('Fleet safety listing timed out')`) `cell_task_worker.py`가 fail-closed 안전 동작으로 모든 `chunk-io-* /chunk-cmd` FIFO에 `human-hold`를 전송한다.
- `bench_record_ops.py:_go_home()`이 홈 이동 중 `rosy-omx-observer@*`만 정지하고 `rosy-omx-cell-task-worker.service`는 정지하지 않아, 홈 이동용 `chunk_runner`가 FIFO를 여는 순간 Fleet-R 미연결 상태의 워커가 즉시 `human-hold`를 걸었다.

## 해결 및 안전 복구 설계

1. `bench_record_guard.py:HANDOVER`와 `bench_record_ops.py:_go_home()` 정지 대상에 `rosy-omx-cell-task-worker.service`를 포함해 홈 이동 동안만 정지하고, 정상 종료 후 `reversed(stopped_units)`로 복원한다(예외/비정상 종료 시 기존처럼 복원 보류).
2. `bench_record_manual.py` + `bench_record_review.py`에 `_record_home_hold()` / `manual_hold_info()`를 추가해 `hold.json`과 로그(노이즈인 `motor-health follower:` 라인 제외)에서 `RUNNER_HELD` PID·관절 좌표·`human-hold` 원인을 추출해 `.bench-manual-check.json`과 `/status.json["manual_hold"]`로 노출한다.
3. UI(`#manual-hold-card`)에서 토크 ON 유지 중인 러너가 있으면 "사람이 물리적으로 팔을 받쳤음" 확인 체크 후에만 `SIGUSR2` 해제 요청(`/api/manual_hold/release_runner`)을 허용하고, 러너 종료·임대 해제 확인 뒤에만 `/api/manual_hold/clear`로 보류를 해제한다(살아 있는 러너 강제 종료나 무단 임대 삭제는 계속 거부).

## 검증 조건

- `test/test_omx_bench_workspace_ui.py::test_go_home_stops_worker_and_diagnoses_clear_manual_hold`
- `test/test_omx_bench_record.py` / `test/test_omx_bench_record_auto_home.py` 원격 pytest 전수 통과
- 실기 PID `148690`은 원격에서 강제 해제하지 않고 현장 작업자가 물리 확인 후 새 UI 복구 카드로 직접 해제하도록 유지
