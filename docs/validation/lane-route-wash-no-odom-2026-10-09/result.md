# 차선 wash와 odom 소실의 동시 발생

2026-10-09 후속 검증. [앞선 wash 품질 전달](../lane-route-wash-quality-2026-10-09/result.md)은 pose가 유효할 때만 BEV의 밝기 거부를 판정했다. odom이 없으면 `LaneEdgeFollower.update()`가 BEV 전에 반환하여 `route_a`는 일반 `visible=false`를 CORE에 전할 수 있었다. CORE의 일반 차선 상실 경로에는 후진 복구가 있다.

이번 수정은 ground가 있고 odom pose가 없어도 **현재 프레임의 BEV 밝기 거부만** 계산한다. 경계·지도 추적이나 조향 관측은 만들지 않는다. `RouteCameraFollower`가 그 원인을 노드로 전달하면 기존 `CAMERA_LINE`의 `quality={valid:false, reason:"overexposed"}`를 CORE에 보낸다. 다음 프레임이 밝기 거부가 아니면 원인을 지워 오래된 오류를 이어받지 않는다. 40% gate, 주행 출력 권한, CORE의 동작 계약은 그대로다.

## 검증과 한계

- SOURCE 재생: 저장된 B9 `camera-loss.png`로 pose가 있는 wash 다음, pose가 없는 wash, pose가 없는 검정 프레임을 순서대로 넣었다. 기대 결과는 `washed`, `washed`, 원인 없음이고, 마지막 두 프레임의 조향 관측은 모두 `None`이다. 수정 전 두 번째 프레임에서 실패했다.
- `test_route_camera.py`, `test_lane_edge.py`, `test_line_observer_wiring.py`: **105 passed**, `test/known_failures.py` **0 NEW**. 이는 ROS 없는 호스트 테스트다.
- 독립 안전 리뷰(`/root/wash_quality_review`, 읽기 전용)는 새 프레임의 wash 판정과 다음 비washed 프레임의 원인 소거, `route_a` 품질 전달을 확인하고 이 범위만 조건부 승인했다. `git diff --check` 오류 0, lint 오류 0(기존 stale-version 경고 23).
- 이 변경은 `route_a`와 `LaneEdgeFollower`의 wash 판정에 국한한다. `route_b`·`route_ab` 및 D-520의 실행 중인 map-guided arc는 별도 계약이다. 실제 영상의 거짓 STOP 감소, 10/6·10/7 사람 검수 GT, 반복 SIM, Pi/DEVICE/현장 수용은 아직 증명되지 않았다. 불확실한 경계에서는 STOP을 유지한다.
- ground가 없거나 BEV의 관측 가능 셀이 0이면 wash를 판정할 수 없다. odom이 빠진 프레임에는 BEV 변환 비용이 추가되며 Pi 지연은 계측하지 않았다.
