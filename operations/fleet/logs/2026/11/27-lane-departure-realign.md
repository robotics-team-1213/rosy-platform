# 2026-11-27 Nav2 도로 trip 차선 이탈 재정렬 (D-1080)
- 범위: `fleet/server/trips/trip_lane_realign.py` 신규, `trip_nav2_route.py`, `trip_road_speed.py`, `fleet/localization/lane_compliance.py`, `test/test_trip_lane_realign.py`, `docs/adr/D-1080-fleet-nav2-lane-departure-realign.md`
- 변경: 활성 Nav2 경로마다 천장 카메라 자세로 몸체 여유를 재고 `detail.lane_departure`에 분류(excluded·location·camera_stale·on_lane·near_edge·departed)를 기록한다. 신선한 카메라로 2 tick 이탈이면 road_speed 상한 0.05 m/s와 기존 취소→확인→재전송으로 `sample_nav2_route(here=)` 복귀 경로를 보낸다(3 s 간격). |lat| ≤ 0.02 m·10° 안이면 감속 해제. 반지름 0.30 m 이하 곡선은 0.08 m/s 상한이 Nav2 도로 trip 속도 권한에 실린다.
- 증거: 원격 pytest(test_trip_lane_realign, test_trip_road_speed, test_trip_nav2_route, test_speed_table, test_lane_compliance) 통과
- gate 변화: 없음
- 결정: D-1080
- 교훈: 없음
