---
title: world_261026 자동 보정은 캐시 미스 시드 누락과 z>0 벽면 오염을 피해야 hold 고착을 막는다
date: 2026-11-20
category: logic-errors
module: operations/overhead/rosy_vision (world_261026_auto, rectify)
problem_type: logic_error
component: vision
severity: high
symptoms:
  - "Fleet 지도 화면에서 1220x2440 mm 경계가 노란 작업대로 밀리고 C1~C3·S1~S5가 위치마다 다른 방향으로 어긋남"
  - "rosy-auto-track-calibration이 drift=0.1513 m, decision=hold(unstable_series)에 머물러 옛 보정에 고착됨"
root_cause: optimization_instability_and_missing_seed
resolution_type: code_fix
related_components:
  - rosy_vision
  - map_plane_jpeg
tags: [world_261026, undistort, homography, levenberg-marquardt, rectify, calibration]
applies_when: "world_261026 자동 추적 보정 및 map_plane_jpeg 재투영을 수정·진단할 때"
---

# world_261026 자동 보정은 캐시 미스 시드 누락과 z>0 벽면 오염을 피해야 hold 고착을 막는다

## Problem

1. `rectify.map_plane_jpeg`가 프로세스 내 `_LATEST_LENS_MODEL` 캐시 미스 시 `seed_map_to_image` 없이 `auto_calibrate_and_trace_world_261026`를 호출해, 카메라 이동·가림 시 재추정이 실패하고 `cv2.warpPerspective`(렌즈 왜곡 보정 생략)로 떨어졌다.
2. `world_261026_auto.py`가 비용 감소 검사 없는 Gauss-Newton 스텝, `mean()` 기반 스트립 중심, `k1 ∈ [-0.08, 0.08]` 클램프, 4.6 cm 단거리 `pink_leg` 외삽, `S5` `white_p | yellow_p` 혼합으로 프레임 간 변동이 커져 `unstable_series` hold에 갇혔다.
3. 회색판 좌우 경계의 `y > -0.22` 상단 구간은 바닥 테이프(`z=0`)가 아니라 흰색 폼보드 벽면(`z>0`)이므로 샘플링하면 오히려 오차가 악화된다(라이브 프레임 실측 `rms_m` 3.1 mm → 4.2 mm).

## Fix & Verification

- `_sample_strip_centroids` `np.median`, LM 비용 감소 수락 검사, `k1 ∈ [-0.25, 0.25]`, `_fit_pink_leg` `[-0.10, -0.002]` 확장, `s5_x` `yellow_p` 우선, `rectify.py` 시드 전달 적용.
- 검증: 원격 `remote_pytest.py` (`test_auto_track_calibration.py`, `test_map_plane.py`, `test_post_age_guard.py`) 53 passed + 라이브 `ceiling_north` 원영상 재투영 `rms_m = 0.00310 m`.
