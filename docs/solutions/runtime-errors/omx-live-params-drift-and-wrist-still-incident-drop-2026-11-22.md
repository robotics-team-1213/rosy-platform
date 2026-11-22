---
title: Live bench params drift, wrist-still incident ValidationError, and stale-reference remap deadlock on OMX cells
date: 2026-11-22
category: runtime-errors
module: deploy/robot/omx (cell_params, omx_incident_fleet, cell_task_worker, cell_calibrate)
problem_type: runtime_error
component: runtime_compatibility
symptoms:
  - "origin/main cell_params.load() raised ValueError on live arm_s and stack files (unknown keys from unmerged 3fff92e55d)"
  - "omx_incident.handle() printed ValidationError frames.1.role Input should be 'top' or 'side' for arm_s-wrist.jpg and set reported=false"
  - "old non-keepalive cell_task_worker emitted human-hold into chunk-io-s during Fleet R rollout/TLS timeouts, aborting arm_s initial park"
  - "stale-reference remap hit transient 'approach is outside the top frame' and spent >30 s in remap_shift_mm grid search, tripping record_session 30 s idle stop"
root_cause: schema_and_release_skew
resolution_type: code_fix
severity: high
tags: [omx, arm-s, cell-params, omx-incident, remap, cell-task-worker, keepalive]
applies_when: "upgrading cell worker/tools from origin/main while live bench param files come from field tuning branches, or reporting stops on a single-top-camera cell with wrist stills"
---

# 라이브 벤치 cell_params 불일치·wrist 스틸 사고 보고 누락·stale remap 유휴 종료

## 증상
- `rosy-omx-cell-task-worker.service`를 `origin/main` 관리 릴리스(`~/.local/share/rosy/omx-devices/current`)로 올리려 할 때, 라이브 `cell-params-arm-s-1119.json`·`cell-params-floor-1028.json`·`cell-params-stack.json`이 `objects.hue_split_tol`, `wrist.jaw_edge_px`, `wrist.edge_goal_px`, `wrist.edge_unseen_ok`, `calibrate.remap_depth_unknown_blocks`, `calibrate.remap_depth_veto`, `calibrate.remap_foreground_blocks` 7개 키 때문에 `cell_params.load()`에서 `ValueError: unknown parameter`로 거절됐다.
- 구버전(`3fff92e55d`) 워커가 Fleet R 재배포 중 `TimeoutError`/`HTTPError 502` 때마다 `human-hold`를 송신해 `arm_s` 세션을 중단했고, 세션 종료 시 `omx_incident_fleet.report_for()`가 `incidents/stills/arm_s-wrist.jpg`를 `role="wrist"`로 담아 `ArmIncidentReport`(`Literal["top", "side"]`) 검증 실패로 Fleet 전송이 누락됐다(`reported=False`, 로컬 `HOLD-arm_s.json`만 잔류).
- `3fff92e55d`에서 `arm_s` `remap` 실행 시 `reference_geometry_sha` 불일치로 클리어런스 판정이 실패하고, `calibrate.remap_shift_mm=30.0` 그리드 탐색이 30초를 넘겨 `record_session` 유휴 타이머(`no command for 30 s`)가 러너를 종료했다.

## 원인
1. 현장에서 튜닝된 `cell-params-*.json` 7개 키가 `3fff92e55d`(`cell/adaptive-ship`)에만 존재하고 `main`의 `cell_params.DEFAULTS`에 아직 반영되지 않았다.
2. `stills_of()`는 로컬 증거용으로 `wrist` 파일도 고를 수 있으나, `omx_incident_fleet.report_for()`가 계약(`ArmIncidentFrame.role: Literal["top", "side"]` 및 중복 role 금지)을 여과하지 않고 그대로 검증기에 넘겼다.
3. 구버전 `cell_task_worker`에는 keepalive가 없어 Fleet 재기동 구간에 `0.5 s` TLS 타임아웃으로 `human-hold`가 오발됐고, `arm_s` 카메라 이동 뒤 첫 `remap`에서 `remap_shift_mm` 탐색 시간이 `record_session` 30초 무명령 종료보다 길어졌다.

## 해결
- `deploy/robot/omx/cell_params.py` `DEFAULTS`에 라이브 파일 7개 키를 안전 기본값(`hue_split_tol=0`, `jaw_edge_px/edge_goal_px=0.0`, `edge_unseen_ok=0`, `remap_*` 플래그 `1`)과 함께 추가해 기존 `cell-params-*.json` 검증을 통과시켰다.
- `deploy/robot/omx/omx_incident_fleet.py` `report_for()`가 계약 허용 role(`"top"`, `"side"`)만 중복 없이 전송하도록 여과하고, 로컬 `incident.json`의 `facts["frames"]` 목록은 유지했다.
- `rosy-arm-cell`의 `rosy-omx-cell-task-worker.service`를 관리 릴리스(`omx-devices/current`, keepalive 탑재)로 전환해 오발 `human-hold`를 중단했고, `arm_s`는 `cell_auto_fold.py --person-at-switch`로 안전 종료 뒤 `sync_hold_from_fleet('arm_s')`로 로컬 보류를 동기화 해제했다.

## 검증 근거
- `test/test_omx_cell_params.py`, `test/test_omx_cell_params_web.py`, `test/test_omx_incident.py`, `contracts/foundation/test/test_arm_incident_machine_clearable.py` 원격 pytest 통과(수정 후 실행).
- `rosy-arm-cell` 라이브 `cell-params-arm-s-1119.json`, `cell-params-floor-1028.json`, `cell-params-stack.json`을 수정된 `cell_params.validate()`로 직접 검증해 오류 0건 확인.
- (미해결 하드웨어 후속: `17:41` USB 허브 분리로 `arm_s` `remap`/`auto_pick` 실물 시운전 및 `cell-params-ab-*.json`의 실험용 키 `runner.vel_ff_s`/`runner.wrist_lag_ms` 통합 여부는 현장 USB 복구 뒤 확정 필요.)

## 복구 방법
- 관리 워커 전환 후에도 구형 `omx_incident`가 남긴 로컬 `HOLD-<arm>.json`이 `outbox` 비어 있음 + `fleet_held=false` 상태면 `omx_incident.sync_hold_from_fleet("<arm>")`로 Fleet 기준 동기화 해제를 수행한다.
- 카메라 이동·설정 수정으로 `bound_map_error`가 나면 일치하는 과거 `calibration.json`+`reference` 쌍으로 부트스트랩하고 `calibrate.remap_foreground_blocks=0`, `calibrate.remap_shift_mm=0.0`으로 유휴 타임아웃 없는 재매핑 뒤 `promote`한다.

## 다음에 적용할 조건
- 셀 워커나 도구를 `main` 관리 릴리스로 전환하기 전, 호스트 `cell-params-*.json`을 `main` `cell_params.validate()`로 먼저 검사해 알 수 없는 키를 `main`에 선행 반영한다.
- `ArmIncidentReport`를 조립하는 전송 계층은 로컬 evidence 확장 카메라(`wrist` 등)와 계약 허용 role(`top`/`side`)을 명시적으로 분리해 검증 실패로 사고 보고 자체가 누락되지 않게 한다.
