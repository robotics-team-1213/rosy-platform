---
title: OMX beltend false edge-of-view refusal, undetected low_zones gap after remap, leaf USB camera recovery, and stale observer-release wrappers
date: 2026-11-24
category: runtime-errors
module: deploy/robot/omx (cell_finger_room.py, cell_auto_pick_plan.py, cell_auto_pick.py, cell_calibrate_bound.py, cell_calibrate.py, cell_upkeep_checks.py, cell_upkeep.py, cell_upkeep_usb_leaf.py)
problem_type: runtime_error
component: hardware_control
symptoms:
  - "auto_pick_dry_run (beltend -> pallet-l1) refused a valid container on beltend with 'edge of view: a side is past the camera's view, 36.8 / 6.0 mm free beside it' even though the 640x480 top frame clearly showed free space beside it"
  - "After cell_calibrate remap + calibrate_check ('todo: []') and upkeep ('map: ok'), auto_pick_dry_run failed at IK OUTSIDE_WORKSPACE because mapped beltend (y=0.092..0.256 m, z=-0.0571 m) extended past grasp-plan low_zones (y<=0.170 m)"
  - "arm_b_wrist UVC camera stuck at HTTP 503 could not recover via root-port power cycle because sibling OpenRB-150 (3-4.2.3) shared hub 3-4.2"
  - "rosy-omx-observer@arm_b.service remained inactive after sessions because host with-session-arm-b-par.sh lacked observer_handoff.py release"
root_cause: tight_roi_cropping_room_mask_and_missing_low_zones_coverage_check_and_missing_leaf_usb_reset
resolution_type: code_fix
severity: high
tags: [omx, arm-b, beltend, finger-room, edge-of-view, low-zones, usb-authorized, camera-recovery, observer-handoff]
applies_when: "diagnosing OMX finger-room edge refusals, post-remap low_zones IK mismatches, UVC cameras sharing a USB hub with OpenRB-150, or observer service handoff after sessions"
---

# OMX `beltend` 연쇄 장애 예방: 시야 가장자리 오판·`low_zones` 누락 검출·USB 리프 단독 복구·옵저버 반납 동기화

## Symptoms (2026-11-24 `rosy-arm-cell` 실기 관측)

1. **`edge of view` 오거절:** `beltend`의 `auto_roi=[271, 18, 367, 167]` 경계 근처(`centre_mm=[180.1, 198.4]`, `px=(350, 80)`)에 놓인 정상 red `container-3`에 대해, 640×480 상단 카메라에 우측 공간이 충분히 찍혀 있는데도 `edge of view: a side is past the camera's view, 36.8 / 6.0 mm free beside it`로 거절되었다.
2. **보정 통과 후 `low_zones` 미스매치:** `stack-calibration.json` 리맵(`2026-11-24T17:08:59`) 뒤 `calibrate_check`는 `todo: []`, `upkeep`은 `map: ok`를 반환했으나, 실제 `beltend` 중심(`belt_mid y=0.1741 m`)과 스토퍼 밀착 박스(`y=0.1732 m`)·상류(`y<=0.256 m`)가 `grasp-plan-armb-v21-20261103.json` `limits.low_zones` 상한(`y=0.170 m`) 밖이라 `IK OUTSIDE_WORKSPACE`로 실패했다.
3. **허브 공유 카메라 `HTTP 503` 고착:** `arm_b_wrist`(`/dev/video8`, `0c45:6367`, `3-4.2.1`)가 UVC 프레임 중단으로 `HTTP 503`에 빠졌을 때, 같은 허브 `3-4.2` 아래에 `arm_b` OpenRB(`3-4.2.3`)가 있어 `cell_upkeep.usb_recover`의 루트 포트 전원 순환이 거부된 채 수동 개입 전까지 복구되지 않았다.
4. **세션 종료 후 `observer` 비활성 잔류:** 호스트 `~/rosy-test/omx-record-prep-20261019/with-session-arm-b-par.sh`가 저장소 `deploy/robot/omx/session-wrappers/` 정본의 `observer_handoff.py release arm_b` 패치 이전 구버전이라 세션 종료 뒤에도 `rosy-omx-observer@arm_b.service`가 `inactive`로 남았다.

## Root Cause

1. **`cell_auto_pick_plan.observe()` / `choose()`:** 객체 검출용 좁은 `roi`(`[271, 18, 367, 167]`)를 손가락 여유 마스크(`mask`)에도 그대로 사용하고 `cell_finger_room.free_mm(..., outside_blocks=True)`가 `roi` 밖을 카메라 시야 밖(`unseen=True`)으로 취급했다.
2. **`cell_calibrate.check()` / `cell_upkeep_checks.check_map()`:** `z < workspace_min_m[2]`인 저고도 사이트(`beltend`, `belt`)의 실매핑 XY 영역이 `plan.limits.low_zones`에 포함되는지 검증하지 않았다.
3. **`cell_upkeep.usb_recover()`:** 루트 포트(`ports`) 순환이 보드 공유로 거부되면 즉시 포기하고, 비허브·무시리얼 단독 카메라 리프(`3-4.2.1/authorized` `0 -> 1`) 재인가 fallback이 없었다.
4. **호스트 래퍼 배포 편차:** `~/rosy-test/omx-record-prep-20261019/with-session-arm-{a,b}-par.sh`가 저장소 `session-wrappers/` 정본과 동기화되지 않았다.

## Fix & Verification

1. **프레임 경계 클램프 패딩 마스크 (`cell_finger_room.py`, `cell_auto_pick_plan.py`, `cell_auto_pick.py`):**
   - `cell_finger_room`에 `ROOM_PAD_PX=48`, `padded_roi`, `obstacle_mask`, `finger_room_view`를 추가하고 `cell_auto_pick_plan`에서 재수출(`re-export`)하며 `choose(..., room_view=None)`와 `cell_auto_pick.py`에 연결했다.
   - 객체 검출(`cell_objects.detect`)과 `observe()` 반환 `mask` 크기는 기존 사이트 `roi` 그대로 유지하고, `surface_lab` 미설정 시에도 사이트 `roi` 내부 중앙값만 사용해 외부 배경 오염을 막으며, 실제 카메라 프레임 경계(`[0, 0, W, H]`)에서는 `outside_blocks=True`와 `edge of view` 거절을 그대로 유지한다.
2. **`low_zone_gaps` 검출·경고 (`cell_calibrate_bound.py`, `cell_calibrate.py`, `cell_upkeep_checks.py`):**
   - `grasp_planner.limits_at`과 동일한 first-match 규칙으로 `z < workspace_min_m[2]` 사이트(`surface_px` 꼭짓점·변 중점·중심 + `start`·`place`)를 검사해 `check()`의 `low_zone_gaps`로 보고하고, `check_map()`이 `warn`(`verdict="needs_person"`)으로 승격한다(안전 한계 자동 완화 없음).
3. **고립 USB 리프 `authorized` `0 -> 1` fallback (`cell_upkeep.py`, `cell_upkeep_checks.py`):**
   - `cell_upkeep.usb_port`가 비허브(`bDeviceClass != "09"`)·직접 시리얼 없음(`leaf_boards == []`)·`authorized == "1"` 조건을 검증한 경우에만 `cell_upkeep_checks.leaf_recover()`로 리프만 재인가한 뒤 `rosy-omx-cameras-bind.service`를 실행하고, 예외/중단 시 `finally`에서 `authorized=1` 및 카메라 유닛을 복원한다.
4. **회귀 테스트 및 실기 프레임 검증:**
   - `test/test_omx_cell_auto_pick_site.py`, `test/test_omx_cell_calibrate.py`, `test/test_omx_cell_upkeep.py` 회귀 테스트 추가.
   - `check-2019`, `check-2040`, `check-2059`, `after-fold-b` 실기 캡처 4프레임 재평가에서 `check-2019/2040/2059` 모두 `margin_mm=16.0, unseen=False` 통과 및 `after-fold-b`/좌측 선반 인접 오거절 방지 유지, `rosy_harness.py lint` 0 errors, D-430 독립 안전 리뷰(`2fd0f087`) PASS 확인(PR 게이트에서 원격 Linux `pytest`, `size_range`, `safety_review` 실행).

## Addendum (2026-11-25): `-71 EPROTO` 미구성(`by-id` 부재) USB 리프 자동 복구

- **추가 증상:** `arm_b_wrist`가 `uvcvideo` UVC 제어 오류 `-71` 뒤 `can't set config #1, error -71` 상태로 멈추면 `/sys/bus/usb/devices/3-4.2.1` 리프(`0c45:6367`, `authorized=1`, `bConfigurationValue=""`)는 남아 있으나 `video4linux`와 `/dev/v4l/by-id/rosy-arm_b_wrist` 심볼릭 링크가 모두 사라져, `cell_upkeep.usb_port(device)`가 `FileNotFoundError`로 실패하며 `leaf_recover()`에 진입하지 못했다.
- **수정 (`cell_upkeep_usb_leaf.py`; 2026-11-25 `deploy/robot/omx` 400줄 기준 때문에 `cell_upkeep.py`에서 분리, `cell_upkeep.usb_recover()`가 호출):** `unconfigured_usb_leaf(role)`를 추가해 `omx-cameras.json`의 `usb_id`와 `/etc/rosy/omx-arm-boards.json`으로 같은 부모 허브에 대상 팔의 `OpenRB`만 단독으로 공존하는 비허브(`bDeviceClass != "09"`)·미구성/미바인딩(`bConfigurationValue` 공백/`0` 또는 `video4linux` 없음)·무시리얼 단일 리프를 fail-closed(후보 1개일 때만 허용)로 역추적하고, `usb_recover()`에서 `usb_port`가 `FileNotFoundError`일 때만 `leaf_recover()`로 넘기도록 연결했다.
- **검증:** `test/test_omx_cell_upkeep.py`, `test/test_omx_upkeep_identity.py` 원격 pytest 통과 및 실셀 `arm_b_wrist` 자동 복구 확인.

## Addendum (2026-11-26): 리프 재인가로 안 풀리면 허브 포트 전원 재투입

- **증상:** `arm_b_wrist`(3-1.4.2.1)가 16:30부터 JPEG 손상, 17:19 감시 재시작 뒤 UVC probe `-71`. 리프 재인가 1회는 잠시 회복했고 2회째는 `can't set config #1, error -71`. 같은 허브(3-1.4.2)의 arm_b OpenRB도 세션 시작 `read pwm_limit: comm -3001`.
- **해결:** 세 팔 세션이 없고 arm_b가 접힘·토크 OFF일 때 `cell_usb_recovery.hub_port_power_and_reset`로 허브 3-1.4의 포트 2를 3초 끊었다. 카메라와 OpenRB가 재열거됐고 프레임 6/6, 이후 60초 `-71` 0건.
- **복구 뒤 확인:** 세션 래퍼는 세션 시작에 실패하면 `rosy-omx-observer@<arm>`을 되살리지 않는다. 손으로 `systemctl --user start` 했다.
- **재발 방지:** `cell_camera_heal.py`(PR #917)가 카메라 작업 시작 전에 upkeep 복구를 돌리고, 실패하면 같은 허브 포트 재투입으로 올린다. record_session이 하나라도 있거나 팔 잠금이 하나라도 잡혀 있으면 하지 않는다. 루트 허브 포트는 건드리지 않는다.
- **원인:** 미확인. 손목 케이블 접촉 불량이면 손목 회전 뒤 재발할 수 있으니 home 직후 손목 프레임을 확인한다.
