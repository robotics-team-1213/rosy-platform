## D-1080 Nav2 도로 trip이 차선을 벗어나면 Fleet은 멈추지 않고 감속하고 차선 복귀 경로를 다시 보낸다 (D-511 M0 개정)

**Status:** Accepted (2026-11-27, 사용자 결정 "코너·경로 이상은 Fleet이 감지하고 신호를 준다", "즉시 정지 말고 도로를 다시 찾게", "다시 정렬해도 되잖아"; 세 세션 토론 합의). 구현은 이 ADR과 같은 PR이다. 실물 수용은 남았다.

| 결정 | 관계 |
|---|---|
| [D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md) | 개정한다. M0 "지켜보고 알리기만, 로봇에 명령하지 않음"은 Nav2 도로 trip에 한해 바뀐다. Fleet이 이미 가진 두 통로(속도 권한, 경로 교체)로만 조치한다. 감시 모니터(`lane_compliance_service.py`)와 lane cue는 그대로다. |
| [D-1009](D-1009-core-route-drive-pass-and-stop.md) | 지킨다. 조향은 기체 Nav2/RPP가 한다. Fleet(2 Hz)은 조향하지 않는다. |
| D-972 충전 칸 | 지킨다. 칸 구간(충전 칸 간선, parking handoff, DOCKING)에서는 판정도 조치도 하지 않는다. |
| `nav2_off_lane_margin_m`·keep-out·MIN_GAP·pin 범위 | 바꾸지 않는다. trip_steps의 중심점 off-lane 정지도 그대로다. |
| transient_loc_hold(robot-d3) | 겹치지 않는다. 위치 문제는 분류만 기록한다. 대기·재위치는 그쪽이 맡는다. |

### Context

2026-11-27 robot-45 Nav2 도로 trip에서 기체 AMCL이 12 cm 틀린 채 "차선 안"으로 판정되었다. 재전송마다 이탈이 0.012 → 0.078 → 0.118 m로 커졌다. 원인은 재전송 경로가 차선 복귀 경로가 아니었던 것이다(#1102로 `sample_nav2_route(here=)`가 복귀 경로를 만든다). Fleet은 이탈을 보면 정지·종료만 할 수 있었다.

### Decision

1. **분류(매 tick, Nav2 경로가 활성일 때).** `trip detail.lane_departure.kind`에 기록한다.
   - `excluded`: 충전 칸 간선(`bay_*`, 충전 장소 끝), `parking_handoff`, 모드 DOCKING.
   - `location`: 상태 읽기 실패, 기체 localization이 LOCALIZED가 아님, 승인 SLAM trip 자세 없음, 기체 SLAM 자세와 천장 카메라 자세 차이 > 0.05 m. 조치 없음.
   - `camera_unavailable`·`camera_stale`: 카메라 자세가 없거나(자동 위치 anchor 포함) anchor 나이 ≥ 0.5 s. 기록·경고만 한다.
   - `on_lane`·`near_edge`(여유 < 0.02 m, 기록만)·`departed`(여유 < 0).
   - 여유는 D-511 몸체 여유 `width/2 − (|lat| + body_half_width)`이고, 천장 카메라 자세로 잰다. 기체 AMCL 자세로 재지 않는다.
2. **조치.** `departed`가 신선한 카메라로 2 tick 이어지고 기체가 NAVIGATING이면:
   - road_speed 권한 상한을 0.05 m/s로 내린다(`reason: lane_realign`).
   - 현재 경로를 `superseded`로 표시한다. 기존 절차(경로 취소 → 취소 확인 → 재전송)가 `sample_nav2_route(here=...)`의 복귀 경로를 보낸다. trip은 running이고 hold·종료·사람 확인은 없다.
   - 교체는 3 s에 한 번이다. hold 중이거나 wait-prefix 경로이면 감속만 하고 교체하지 않는다.
3. **복귀.** 카메라 기준 |lat| ≤ 0.02 m이고 차선 방향과 10° 안이면 감속을 푼다. 즉시 정지 단계는 없다.
4. **급곡선 상한.** 반지름 0.30 m 이하 곡선에서는 이탈과 관계없이 0.08 m/s다. speed_table에 곡선 상한 기능이 있었지만 Nav2 도로 trip의 속도 권한(`RoadSpeed.renew`)에 실리지 않았다. 이제 실린다.
5. **진행 판정.** 0.05 m/s에서 Fleet stall(20 s에 0.05 m)과 Nav2 progress checker(15 s에 0.25 m)는 걸리지 않는다(15 s에 0.75 m). 진행 판정은 바꾸지 않는다.

### Consequences

- 코드: `operations/fleet/fleet/server/trips/trip_lane_realign.py`(분류·조치), `trip_nav2_route.py`(호출 한 줄), `trip_road_speed.py`(감속·곡선 상한), `localization/lane_compliance.py`(`lane_offset` 공용 계산).
- 시험: `operations/fleet/test/test_trip_lane_realign.py`.
- 기체 AMCL이 카메라와 5 cm 넘게 틀리면(11-27 robot-45의 12 cm) 이 변경은 조치하지 않고 `location`(`SLAM_CAMERA_GAP`)으로 기록만 한다. 그 경우의 대기·재위치는 transient_loc_hold가 맡는다.
- 교체한 경로의 취소 확인이 늦거나 사라져 다음 tick에 기체가 CANCELED를 보고하면, `superseded` 경로는 중단이 아니라 재전송 대상이다(`_route_finished`). 같은 일이 replan 교체에도 적용된다.
- 이 감시에서 예외가 나면 `kind: error`로 기록하고 조치하지 않는다. trip은 계속된다.
- 승인 SLAM 바인딩이 없는 Nav2 trip은 차이를 잴 수 없어 `location`(`SLAM_POSE_UNBOUND`)으로 기록만 한다.
- 위치 문제가 감속 중에 생기면 감속은 남는다(보수적). 칸 구간에 들어가면 풀린다.

### Open

- 실물 수용: robot-45 도로 trip에서 이탈 → 감속 → 복귀 경로 → 해제 순서와 `lane_departure` 기록 확인.
- 0.05 m/s 감속, 3 s 간격, 0.08 m/s 곡선 상한은 첫 실물 값이다. 측정으로 고친다.
