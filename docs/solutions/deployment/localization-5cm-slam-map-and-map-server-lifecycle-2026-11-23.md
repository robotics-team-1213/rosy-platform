---
title: "5 cm SLAM 융합 맵 로컬라이제이션과 map_server 수명주기·OS 상태 투영 함정"
date: "2026-11-23"
module: "ROSY Pinky 실물 검증 (core_bridge, loc_assist, fleet_map_exchange, os_state_config)"
problem_type: runtime_error
component: deployment
severity: medium
symptoms:
  - "localization 모드 기동 후 GET /api/v1/map은 map_id를 반환하지만 GET /api/v1/robot/state의 map_grid_id는 null로 남는다."
  - "0.05 m 해상도 SLAM 융합 마스터 맵에서 loc_assist_node가 기본 wall_tolerance=0.04 m 설정일 때 후보 0건(NO_CANDIDATES)을 반환한다."
  - "tools/calibration/fleet_map_exchange.py verify-loc이 실제 Fleet /api/fleet/state 응답에서 localization과 map_grid_id를 못 읽는다."
  - "임시 실험 후 /etc/rosy/runtime.env를 cp로 되돌리면 rosy-sd-provision.service가 OS_STATE_HOLD로 실패해 rosy-core 기동이 막힌다."
root_cause: logic_error
resolution_type: bug_fix_and_workflow
tags: ["pinky", "localization", "map_server", "loc_assist", "os-state", "fleet"]
---

# 5 cm SLAM 융합 맵 로컬라이제이션과 map_server 수명주기·OS 상태 투영 함정

2026-11-23 격리 실험(`rosy-local-fleet-exp`, `rosy_46`·`rosy_45` 바퀴 무구동 실물 검증)에서 확인하고 수정한 네 가지 문제다.

## 1. `map_server` 기동 직후 `robot/state.map_grid_id`가 `null`로 지워진다

- **원인**: `nav2_map_server`는 `on_activate()` 내부에서 latched `/map`을 먼저 발행한 뒤 `/map_server/transition_event(ACTIVE)`를 보낸다. `ros_bridge._on_map()`이 `_map_grid_id`를 채운 직후 `_on_map_server_transition`이 `map_observation.lifecycle(self, True)`(`middleware/core/gateway/core/bridge/map_observation.py`)를 호출하고, 그 안의 `svc.state.invalidate_map_grid()`가 `state._map_grid_id = None`으로 지운다(`svc.state.map_id`는 유지되므로 `/api/v1/map`만 정상 표시). 정적 `map_server`는 재발행하지 않으므로 `robot/state.map_grid_id`가 복구되지 않는다.
- **검증된 임시 복구**: `/<ns>/map_server/load_map` 서비스 호출 또는 `map_server` 활성화 완료 뒤 `rosy-core` 재구독 시 `_map_grid_id`가 즉시 마스터 맵 `grid_id`로 채워진다.
- **구현된 근본 수정**: `middleware/core/gateway/core/bridge/ros_bridge.py`의 `_on_map_server_transition`이 `map_observation.lifecycle(self, active)` 호출 뒤 `active`가 `True`일 때 `_refresh_map_subscription()`으로 latched `/map` 구독을 잠금 보호 하에 재생성(`destroy_subscription` 후 `_LATCHED` 재구독)하도록 수정했다(`map_observation.py`의 무효화 가드는 유지).

## 2. 5 cm SLAM 맵에서 `loc_assist` 기본 `wall_tolerance=0.04`는 0셀 팽창과 같다

- **원인**: `loc_assist_node.py` 기본값은 `wall_tolerance=0.04 m`, `candidate_minimum_fit=0.90`, `minimum_fit=0.85`다. `MapAgreement`(`middleware/perception/sensors/sensing/localization.py`)는 `radius = ceil(tolerance / resolution)`인데 `resolution=0.05`일 때도 `0.04`가 단일 셀 안에 갇혀 인접 대각/측면 격자 여유가 부족하고, 동적 장애물(`transient_obstacles_removed`) 제거 및 2셀 폭 5 cm 벽체의 `ranges - 0.06` 자유 광선 검사(`~10~13%` 차단)와 겹쳐 실측 스캔 점수가 낮아진다.
- **실물 관측**: `rosy_46`는 `wall_tolerance=0.12` 설정만으로 기본 `0.90/0.85` 게이트를 통과해 `LOCALIZED`(confidence `0.9036..0.9146`)에 도달했다. `rosy_45`는 `wall_tolerance=0.15`, `candidate_minimum_fit=0.80`에서 실제 정차 위치 후보(`scan_fit=0.8336`, 동료 핑키 `rosy_46` 실측 오차 `3.7 cm`)와 AMCL 수렴을 확인했으나, 무변경 `0.85` `InjectionCheck`는 `0.8258`로 fail-closed(`inject_rejected`)를 유지했다.
- **구현된 근본 수정**: `middleware/perception/sensors/sensing/localization.py`의 `MapAgreement`가 `eff_tol = max(float(tolerance), float(resolution) * math.sqrt(2))`, `sigma = max(.025, .75 * float(resolution))`, `self._ray_margin = max(.06, 2.0 * float(resolution))`로 격자 해상도에 맞춰 표면 불확실성을 스케일하도록 수정했다(`<= 0.02 m` 맵에서는 기존 값과 완전히 동일하며, `0.05 m` 실물 스캔 리플레이에서도 중간 벽체 차단 기각과 `>= 0.90` 적합도 회복을 함께 확인).

## 3. 실제 Fleet `/api/fleet/state` 응답 스키마 차이

- **원인**: 실제 Fleet 서버는 `localization`과 `map_grid_id`를 `robots[]` 최상위가 아니라 `robots[].state` 안에 둔다.
- **조치**: `tools/calibration/fleet_map_exchange.py`의 `cmd_verify_loc`이 평면/중첩 스키마를 모두 읽도록 수정하고 단위 테스트를 추가했다(PR #587).

## 4. `/etc/rosy/runtime.env` 직접 덮어쓰기와 `OS_STATE_HOLD`

- **원인**: `site_map_host.py`는 `os_state_config.commit_runtime`으로 `/etc/rosy/runtime.env`를 OS 표준 세대(`/var/lib/rosy-device/state/current.json`)에 커밋한다. 실험 복원 시 `cp -p`로 `runtime.env`만 되돌리면 `rosy-sd-provision.service`의 `os_state_ready.projection_facts()`가 해시 불일치로 `OS_STATE_HOLD`를 반환해 `rosy-core` 의존성 기동을 막는다.
- **예방**: A/B OS 이미지 기기에서 `runtime.env`를 복구·변경할 때는 반드시 `os_state_config.configuration_update` + `os_state_ready.publish_ready` + `os_storage_dispatch.py --projected` 검증 경로를 거친다.
