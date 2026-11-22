---
title: OMX Bench Teleop Range-End Smooth Clamping, Real stop_cause Extraction, and Supervised Unfolded-Arm Home Fold
date: 2026-11-22
category: runtime-errors
module: deploy/robot/omx (guarded_native_mount, guarded_native, guarded_native_lag, guarded_native_effort, bench_record_safety, bench_record_ops, bench_record_step, cell_auto_fold)
problem_type: runtime_error
component: safety_and_bench_recovery
severity: high
tags: [omx, arm-s, guarded-native, stop-cause, auto-fold, bench-record]
applies_when: "full-arm Leader teleop nears joint range ends, bench.log ends with trailing telemetry JSON on a guard stop, or operator recovers an unfolded arm from the bench result view"
symptoms:
  - "Smoothly turning Leader wrist_roll past 0/4095 while extended mid-air tripped guarded_native range validation and cut Follower torque immediately"
  - "bench_record_safety.stop_cause returned lines[-1] ('{\"incident\": false}') from bench.log instead of the real exception or guard-end.json reason"
  - "bench go_home stopped camera units and refused HOME_UNFOLDED without sending 'stop now', forcing a blind SIGTERM -> stop fold and mislabeling auto_home skipped as failure"
root_cause: unguarded_range_exit_and_tail_noise
resolution_type: code_fix
---

# OMX 리더 끝단 클램핑, 실 중단 원인 추출 및 펼쳐진 팔 감독 홈 복귀

## 증상
1. `arm_s` 실시간 원격 조작 중 작업자가 리더 `wrist_roll`을 보정 범위(`0..4095`) 끝까지 돌린 순간 `ValueError: wrist_roll: outside calibrated range`가 발생해 팔이 공중에서 즉시 토크 OFF됐다.
2. 세션 종료 후 UI(`#ev-safe-end`)가 `{"incident": false}`를 중단 원인으로 출력하고, 가드 중단으로 생략된 `auto_home.skipped=true`를 `홈 복귀 실패(원인 미상)`로 잘못 표시했다.
3. 결과 화면에 즉시 홈/안전 접기 조작이 없었고, `go_home()`이 카메라 유닛까지 정지시키며 `HOME_UNFOLDED` 거절 시 FIFO `stop now` 없이 `SIGTERM`을 보내 러너가 맹목 `stop fold`에 진입할 수 있었다.

## 원인
1. `guarded_native.py`가 추종 중(`full_arm and command is not None and tracking`)에도 리더 사상값(`mapped` / `leader["gripper"]`)의 보정 범위 이탈을 무조건 예외로 차단해, 작업자의 연속 회전이 팔로워 안전 정지가 아닌 공중 토크 해제로 이어졌다.
2. `bench_record_safety.stop_cause()`가 `guard-end.json`을 보지 않고 `bench.log`의 마지막 줄(`{"incident": false}`)만 잘라 반환했다.
3. `go_home()`이 `rosy-omx-observer@*` 외 카메라 유닛까지 내려 `cell_auto_fold --supervised`용 상단 카메라 프레임을 끊었고, `HOME_UNFOLDED` 거절 시 FIFO `stop now`가 없어 `chunk_runner`가 `SIGTERM`을 `stop fold`로 해석했다.

## 해결
- `deploy/robot/omx/guarded_native_mount.py`, `guarded_native.py`, `guarded_native_lag.py`, `guarded_native_effort.py`: `validate_targets()`를 분리해 실제 팔로워 현재값(`current`)·시드(`command is None`)·정렬(`not tracking`)·`body_only`/`teacher`·단일 틱 `>=100°` 점프는 기존처럼 fail-closed로 유지하고, 활성 추종 중 연속적인 범위 이탈만 팔로워 보정 한계(`[max(range_min, floor), range_max]`)에 클램핑(1회 안내 로그)하며 `prev_mapped`로 비클램프 기준 100° 판정을 유지한다. (`guarded_native_track.py`는 `0.5 * brake_deg_s2` 감속 상한으로 전 단계 정지 오버슈트 `0.000000 deg` 유지.)
- `deploy/robot/omx/bench_record_safety.py`: `stop_cause()`가 `guard-end.json["reason"]`를 최우선으로 읽고, 없을 때 `bench.log` 뒤쪽 `{"incident":...}`/`{"step":...}`/`motor-health:` 노이즈 줄을 건너뛰어 실제 예외를 추출한다.
- `deploy/robot/omx/cell_auto_fold.py`, `bench_record_ops.py`, `bench_record_step.py`: `cell_auto_fold.py --supervised`로 사고 ID 없는 벤치 복귀를 허용하되 이동 전 거절만 `stop now`로 풀고 이동 시작 후 실패는 `human-hold`를 유지한다. `go_home()`은 `rosy-omx-observer@*`만 중지해 상단 카메라를 살리고, `fold_unfolded=True`일 때만 D-1048 상단 카메라 회랑 검사 접기를 실행하며, 비옵트인 `HOME_UNFOLDED` 거절 시 `stop now`를 먼저 전달한다.
- `deploy/robot/omx/bench_record.html`, `bench_record_status.js`, `bench_record_drawers.js`, `bench_record_cam.js`: 결과 화면에 `지금 홈 포즈 [H]` 버튼(`#hdr-result-home-btn`)을 추가하고 `autoHomeView()`로 `skipped`/`cancelled`/`failed`를 구분 표시한다.

## 검증 근거
- 로컬 정적 게이트(`deploy/robot/omx/*.py < 400줄`, 웹 `<= 600줄`, `py_compile`, Node `vm.Script`, CSS 0-motion, `size_range.py`, `rosy_harness.py lint`) 및 `test/test_omx_guarded_native.py`, `test/test_omx_auto_fold.py`, `test/test_omx_bench_record*.py` 원격 pytest로 검증.
- 배포 게이트: `rosy-arm-cell` 유휴 확인 뒤 `:8771` 재시작 및 Playwright 스모크 스크린샷 검수.

## 복구 방법
- 펼쳐진 상태에서 `지금 홈 포즈 [H]`가 장애물 감지(`ALL_PATHS_BLOCKED`)로 보류되면 카메라 영상에서 장애물을 치우거나 그리퍼를 비운 뒤 재시도한다.
- 이동 중 접촉·지연으로 `human-hold`가 래치되고 `.bench-manual-check.json`이 생성된 경우 사람이 팔을 받친 뒤 상태·릴리스 절차를 수행한다.

## 다음에 적용할 조건
- 리더 매핑/그리퍼 한계 완화는 반드시 `full_arm and command is not None and tracking` + 단일 틱 `<100°` 조건으로만 한정하고, 팔로워 실측값·스타트업·정렬·수동 모드는 항상 fail-closed를 유지한다.
- `deploy/robot/omx/*.py`는 400줄 미만, `bench_record*` 웹 파일은 600줄 이하와 D-220 0-motion 규칙을 지킨다.
