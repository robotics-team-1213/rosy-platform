---
title: "Pinky 사이트 autocal 호스트 상태 반영과 Cross-Frame 위치 확정·D-1022 결속 파이프라인"
date: "2026-11-24"
module: "deploy/site/host-state, fleet.localization, tools/calibration/pinky_loc_pipeline.py"
problem_type: deployment_error
component: deployment
severity: medium
symptoms:
  - "PR #619가 main에 머지되고 site 스택이 0bb5c8fa63으로 갱신됐는데도 /usr/local/sbin/rosy-auto-track-calibration이 구버전(--sync-map 미분리)으로 남아 site_map_versions가 계속 증가했다."
  - "rosy-pinky-y8xs(rosy_45)가 5.85x5.70m 병합 맵(site_map_v2_fleet_v1)에서 유일 후보(scan_fit=0.9894)를 잡았으나 Fleet에서 CANDIDATES(needs_human) 상태로 남고, POST .../map-binding/propose는 world_261026(2.44x1.22m) 대비 WALLS_MISMATCH로 거절됐다."
root_cause: missing_rollout_step
resolution_type: workflow
applies_when:
  - "deploy/site/rosy-auto-track-calibration 또는 deploy/site/host-state/manifest가 가리키는 호스트 스크립트를 변경한 뒤 site PC에 반영할 때"
  - "Pinky가 site_map_v2_fleet_v1(5.85x5.70m) 등 world_261026과 좌표계가 다른 맵에서 첫 기동 확정 및 D-1022 결속을 수행할 때"
tags: ["pinky", "host-state", "autocal", "d-1022", "localization", "fleet"]
---

# Pinky 사이트 autocal 호스트 상태 반영과 Cross-Frame 위치 확정·D-1022 결속 파이프라인

2026-11-24 실기기(`rosy-fleet-r`, `rosy-pinky-y8xs`) 롤아웃 검증에서 확인한 호스트 스크립트 배포 간극과 Cross-Frame 로컬라이제이션·D-1022 결속 절차다.

## 1. Docker `rosy-site-autoupdate`는 `approval=autocal` 호스트 스크립트를 갱신하지 않는다

- **원인**: `deploy/site/host-state/manifest` 36행의 `/usr/local/sbin/rosy-auto-track-calibration`은 `approval=autocal` 항목이므로, 컨테이너 이미지 업데이터(`rosy-site-autoupdate`)가 아니라 `rosy-host-state install site --approve autocal`로 `/usr/local/lib/rosy-host-state` 정본과 함께 설치해야 한다([host-guard 교훈](host-guard-files-update-through-host-state-install-2026-10-30.md)).
- **검증된 조치 및 확인**: `origin/main`의 `deploy/hosts/common/`과 `deploy/site/`를 스테이징해 `rosy-host-state install site --approve autocal --dry-run` 확인 후 적용했고, `sudo rosy-host-state check`에서 `drift: []`, `errors: []`, `rosy-auto-track-calibration.service` `status: ok`(`site_map_versions` 394 고정)를 확인했다.

## 2. `site_map_v2_fleet_v1` ↔ `world_261026` Cross-Frame 확정 및 D-1022 결속 파이프라인

- **원인**: `rosy-pinky-y8xs`(`rosy_45`)는 `site_map_v2_fleet_v1`(`5.85x5.70m`, `lane_rules.yaml` 없음)에서 `loc_assist`가 1개 유일 후보(`scan_fit=0.9894`)를 찾지만, `robot_map_bindings`가 비어 있고 `map_v2_fleet != world_261026`이므로 PR #617의 `choose_unique` + `binding_for_grid()` 자동 확정 조건이 아직 성립하지 않는다. 또한 벽 크기가 현장 사각형(`2.44x1.22m`)과 달라 `POST .../map-binding/propose`는 `WALLS_MISMATCH`가 된다.
- **파이프라인 (`tools/calibration/pinky_loc_pipeline.py`)**:
  1. `status`: `/api/fleet/state`, `/api/fleet/tracking/identity`, `/localization`, `/map-binding`, `/map-pose`를 읽어 기체별 단계(`OFFLINE` / `NO_CANDIDATES` / `NEEDS_CONFIRM` / `NEEDS_MAP_BINDING` / `READY`)를 판정한다.
  2. `confirm`: 이름 있는 운영자 토큰으로 단일 고유 후보(`scan_fit >= 0.85`)를 `POST /api/fleet/robots/{id}/localization/confirm` 확정하고 `LOCALIZED` 도달을 대기한다.
  3. `sample` → `bind`: `LOCALIZED` + 정지(`|v|<0.01, |w|<0.02`) + 신선한(`age_s<=1.0`) `CONFIRMED` 천장 카메라 좌표 또는 현장 실측 `--pair rx,ry=sx,sy`로 `>=4`점(span `>=1.0m`, 1점 holdout 포함)을 수집하고 D-1022 Kabsch 검증 후 `POST .../map-binding`으로 결속한다.
- **결과**: 한 번 `robot_map_bindings`에 `map_grid_id` 결속이 기록되면, 이후 재부팅에서 `LocalizationService._tiebreak_camera_in_robot_frame()` → `fit.inverse(cam)` → `Tiebreak.choose_unique()` → `LocState` `("twin", "unique")` 경로가 자동으로 작동한다.
