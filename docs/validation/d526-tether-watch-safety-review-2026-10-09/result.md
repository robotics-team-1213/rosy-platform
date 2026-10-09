# D-526 Fleet 케이블 감시의 독립 안전 리뷰 — 2026-10-09

**판정:** branch `feat/fleet-tether-watch`의 D-526 1단계를 승인한다. 작성 세션과 별도의 리뷰 세션이 세 번 검토했다(첫 리뷰 REQUEST CHANGES, 재검토 REQUEST CHANGES, 최종 검증 APPROVE). 안전 태그 경로를 바꾼 두 커밋에 `Safety-Review:` trailer가 없어, 사용자 승인(2026-10-09)으로 두 커밋만 `tools/harness/safety_review.py`의 사후 검토 목록에 넣는다.

- `66f0e629d4aad3533ad2c8ff07b7f95a9e817a14`: `tether_watch.py` 신설. Fleet이 0.5 s마다 tether가 걸린 로봇의 반경(`radius_m` + 0.15 m), 누적 회전(405°, tether POST부터 ±180° 언랩), 위치 신선도(2 s)를 보고 넘으면 기존 CORE E-Stop 클라이언트(`hub.scatter_estop`, `POST /api/v1/safety/stop`)로 멈추고 trip을 끝낸다.
- `2c1c2310e42bcc54092935cb8ca86378422c9ed1`: 리뷰 지적 반영. 신뢰된 지도 위치(`classify == TRUSTED`)만 위치로 친다(odom·legacy·비신뢰는 2 s 뒤 `tether_pose_stale` 정지, fail-closed). 정지마다 3 s 제한, 로봇별 독립 처리, 감시 생존 시각(`watch_age_s`)과 done-callback, 정지 실패 10회 뒤 운영자 경보(`TETHER_STOP_FAILED`, `console.py`의 경보 출처 훅), E-Stop 성공 직후 `stop_sent` 기록.
- 최종 커밋 `001373cc6`(trailer 대상 경로 아님): 위치 신선도를 CORE의 `evidence.pose`(`STALE_POSE_S` 2.0 s)로 판단한다. 근거가 없으면 위치 없음으로 본다. 반복 타임스탬프만으로는 멈추지 않는다.

시험: 원격 호스트에서 `operations/fleet/test` 전체 2919 passed, 1 failed(`test_overhead_tracking_api`의 상태 경과 시험, main에서도 실패). 이 변경을 증명하는 시험은 `test_tether_routes.py`의 `test_a_frozen_pose_with_a_moving_timestamp_trips_unless_core_calls_it_fresh`, `test_a_stamp_repeating_at_the_1_hz_heartbeat_does_not_trip_on_its_own`, `test_a_frozen_pose_stamp_trips_pose_stale_and_a_legacy_robot_is_stopped`, `test_trip_stops_through_the_existing_core_estop_client_and_shows_in_the_list`, `test_repeated_stop_failures_raise_an_operator_alarm_and_keep_retrying`다(18 passed). 경보 배너 문구(`enrollment.js`)는 diff로만 확인했다.

검토 범위는 Fleet 쪽 감시 논리와 기존 E-Stop 경로의 호스트 시험이다. 시뮬레이션, 실제 로봇 주행, 현장 수용은 이 리뷰로 승인되지 않는다(D-480 등급).

## 추가 검토 — `f14e20e2fc52ff0fb9e8d7267dbeb0f7e6596d70`

D-430 §3 분리 시험(안전 파일은 결정 모듈을 가져오지 않는다)을 지키려고 신뢰 판정(`classify == TRUSTED`)을 `tether_watch.py`에서 `tether_routes.trusted_map_pose`로 그대로 옮겼다. `pose()`는 여전히 신뢰된 지도 좌표에 `evidence.pose`가 fresh일 때만 위치를 주고, 위치가 2 s 넘게 없으면 감시가 멈춤과 E-Stop을 보낸다. 독립 검증 APPROVE, `test_tether_routes.py` 19 passed. 남은 점: `TetherWatch(pose=...)`는 아무 함수나 받으므로, 운영 생성 지점은 `tether_routes.py` 한 곳으로 유지한다. 같은 날 사용자가 승인한 D-526 착지의 후속 커밋으로 사후 검토 목록에 넣는다.
