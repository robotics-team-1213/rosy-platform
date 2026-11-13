## D-1022 기체 SLAM 지도와 현장 지도의 결속: 실제로 읽은 격자에 묶인 승인 기록

**Status:** Proposed (2026-11-14, 사용자 지시: "실제로 이제 핑키가 맵을 slam 으로도 제대로 그리고 그것들이 보정되어서 실제 자신의 위치를 파악이 가능한지 그래서 그걸 토대로 서로 약속된 규약에 의해 맵에서 위치를 정확하게 기록하고 이를 토대로 nav2 가 되도록해야해", "마커 말고 슬램으로도 충분히 더 서로 통신해서 위치를 개선할 수 있는거 아니야?"). 호스트 시험까지다. 기체·현장 수용은 없다(기체가 선에 묶여 있어 실물 시험은 뒤로 미룸).

잇는 결정: [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(free 목표의 기체 프레임 변환), [D-1010](D-1010-site-map-frame-binding.md)(사이트 지도 프레임 결속), [D-989](D-989-fleet-auto-locate-observation.md)(auto-locate), [D-1017](D-1017-peer-sighting-map-pose-anchor.md)(peer 앵커).

### Context

2026-11-13 Fleet R에서 Pinky를 Nav2로 보낸 결과와 패널(Claude·Codex·GLM) 3라운드 토론의 결론이다.

1. **`map_id`가 같다는 것은 같은 좌표계를 증명하지 못한다.** D-1010은 기체 상태의 `map_id`가 활성 지도의 `map_id`와 같으면 변환 없이 현장 좌표를 보낸다. 기체가 SLAM으로 지도를 다시 그려 같은 이름으로 저장하면 원점·방향이 달라도 이름은 같다.
2. **한 쌍 변환은 카메라 오차를 그대로 목표에 싣는다.** D-1003 변환은 "지금 현장 자세 ↔ 지금 기체 자세" 한 쌍으로 회전·이동을 정한다. 같은 날 측정에서 칸 안 마커 시차가 약 10–11 cm(마커 높이 0.125 m)였고, 이 오차가 매 목표의 변환에 들어갔다.
3. **기체가 실제로 읽은 격자를 Fleet가 몰랐다.** CORE는 `map_id`만 보고했다. 격자 내용의 해시(`occupancy_map_id`)는 CORE 안에서만 쓰였다.

### Decision

1. **CORE가 읽은 격자를 보고한다.** `StateSnapshot.map_grid_id`는 CORE가 마지막으로 받은 점유 격자의 `occupancy_map_id`(`occupancy:` + 해시)다. `map_id` 의미는 바꾸지 않는다.
2. **결속은 승인 기록이다.** Fleet `robot_map_bindings` 행 하나가 (기체, `robot_grid_id`, 현장 지도 `map_id`·`version`)에 2D 강체 변환(yaw, tx, ty)을 묶는다. 이름 있는 운영자가 짝 ≥3개와 따로 잰 검증 짝 ≥1개를 보내면 Fleet가 다시 맞추고(Kabsch, 거울상 거절), 잔차 ≤5 cm·짝 범위 ≥1 m·검증 오차 ≤5 cm일 때만 저장한다. 클라이언트의 숫자는 저장하지 않는다. 새 승인은 이전 것을 `superseded`로 닫고, 이력은 지우지 않는다.
3. **결속은 정확히 맞을 때만 쓴다.** 활성 결속이 없으면 `MAP_BINDING_REQUIRED`, 현장 지도 id·버전이 다르면 `MAP_BINDING_SITE_CHANGED`, 기체가 보고한 `map_grid_id`가 다르면 `MAP_BINDING_GRID_CHANGED`, 기체가 지도 프레임에서 LOCALIZED가 아니면 `ROBOT_NOT_LOCALIZED`다. `map_id`가 같은 것만으로는 맞다고 보지 않는다.
4. **마커 없이 짝을 제안한다.** `POST …/map-binding/propose`는 기체 지도의 점유 칸(값 ≥65)에서 최소 면적 사각형을 찾아 현장 벽 경계(기본은 활성 지도 벽의 바깥 상자)의 네 모서리와 맞춘다. 대칭으로 남는 0°/180° 선택은 운영자가 준 "지금 기체가 선 현장 위치" 하나로 고른다. 제안은 미리보기일 뿐이고 승인은 2항을 다시 거친다(검증 짝은 바닥에서 따로 잰다).
5. **켜진 현장에서는 free 목표가 결속으로만 나간다.** 사이트 설정 `fleet.trip.map_binding_required: true`면 `robot_frame_goal`은 `map_id` 같음 지름길과 한 쌍 변환을 쓰지 않고 결속의 역변환으로 목표를 바꾼다. 맞는 결속이 없으면 trip을 `map_frame`으로 멈추고 `detail.binding`에 3항 사유를 남긴다. `goal_frame` 기록에 `map_grid_id`를 더한다. 기본값은 꺼짐이다.
6. **SLAM 자세와 카메라 자세를 나란히 보인다.** 결속 읽기는 맞는 결속이 있을 때 기체 SLAM 자세를 현장 좌표로 바꾼 `slam_site_pose`, Fleet 카메라 자세 `camera_site_pose`, 둘 사이 거리 `slam_camera_gap_m`를 준다. 읽기 전용이고, MapPoseService 앵커로 쓰지 않는다.

### Consequences

- SLAM 지도를 다시 저장하면 격자 해시가 바뀌어 결속이 자동으로 무효가 된다. 다시 승인해야 한다(조용히 옛 변환을 쓰지 않는다).
- 현장 지도를 새 버전으로 활성화해도 결속이 무효가 된다. 벽이 그대로면 제안→승인으로 다시 묶는다.
- `map_binding_required`를 켜기 전에 각 기체에 결속이 있어야 한다. 없는 기체의 free trip은 멈춘다(의도).
- 카메라 마커 시차(칸 안 약 10 cm)는 결속 목표 변환에 들어가지 않는다. 결속의 정확도는 SLAM 격자 품질과 승인 짝에 달려 있다.

### 한계 (다음 일)

- `compute_road_plan`(정박 이동 계획)은 아직 한 쌍 변환을 쓴다. `fix/fleet-real-site-pose`가 그 함수를 바꾼 뒤 결속 사용으로 옮긴다.
- 결속 자세를 MapPoseService 앵커로 쓰는 것(SLAM 자세로 현장 위치 갱신)은 패널 합의로 미뤘다. `slam_camera_gap_m`를 실물에서 모은 뒤 정한다.
- Fleet 화면에 결속 상태 배지는 아직 없다(API만).
- AMCL 첫 자세(`set_initial_pose: false`)는 사용자 결정으로 고정되어 있어 바꾸지 않았다.

### 검증 (Validation / Transition)

- 호스트(원격): `operations/fleet/test/test_map_binding_fit.py`, `test_map_binding_store.py`, `test_map_binding_routes.py`, `test_site_map_frame_safety.py`(결속 필수일 때 지름길 무시·역변환·사유 정지), `middleware/core/gateway/test/test_initial_pose.py`(`map_grid_id`).
- 실물(선을 뗀 뒤): rosy_42 재승인 봉인 → SLAM 지도 저장 → 제안·승인(검증 짝 바닥 실측) → `map_binding_required` 켬 → ±5 cm 전후진과 Nav2 목표 오차 확인.

### References

`operations/fleet/fleet/localization/map_binding.py`, `operations/fleet/fleet/server/sitemap/map_binding_store.py`, `operations/fleet/fleet/server/sitemap/map_binding_routes.py`, `operations/fleet/fleet/server/trips/trip_geometry.py`(`robot_frame_goal`의 `binding`), `trip_steps.py`, `trip_ports.py`(`map_binding_required`), `middleware/core/gateway/core/bridge/map_observation.py`, `contracts/foundation/core_common/protocol/schemas.py`(`map_grid_id`), API v1.393.
