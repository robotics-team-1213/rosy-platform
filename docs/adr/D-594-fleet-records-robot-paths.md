## D-594 Fleet이 로봇이 지나온 길을 기록해 보여 준다 — 지도 좌표만, 상태와 출처를 함께

**Status:** Proposed (2026-10-10, 사용자 요청 "Fleet에서는 로봇이 움직인 경로를 우리가 기록해서 보여주도록 하는 게 좋을 것 같아"; SOURCE·호스트 테스트만, 현장 확인 별도).

고치는 결정: [D-512](D-512-agent-run-device-test.md) 개정 1의 지도 궤적(브라우저가 모으던 표시). 읽는 결정: [D-395](D-395-fleet-assisted-localization.md) 신뢰 판정, [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3 Fleet map pose, [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md) 천장 카메라 추적(표시 전용). 안전 분리: [D-430](D-430-safety-as-a-separate-concern.md).

### Context

- 지금 지도 궤적은 브라우저가 1 s 상태 폴링의 `state.pose`로 모은다. 최근 120 s, 600점뿐이고 새로 고치면 사라진다. 운행 하나를 다시 볼 수 없다.
- 그 궤적은 `localization.pose_frame === "odom"`일 때만 odom을 뺀다. 모터 모드 로봇은 `localization: null`을 보내고 CORE는 map TF가 낡으면 odom을 `pose`에 쓴다(D-559). 그래서 odom 좌표가 지도 좌표로 그려졌다.

### Decision

1. **Fleet이 기록한다.** 앱 루프가 1 s마다 로스터의 로봇마다 한 점을 고른다.
   - 로봇이 스스로 LOCALIZED·map이라고 보고한 pose(D-395 `trust.classify == TRUSTED`): `state` LOCALIZED, `source` `robot`.
   - 아니면 Fleet map pose(D-494 3 `MapPoseService.arbitrated_pose`)가 LOCALIZED 또는 DEGRADED: 그 `state`, `source` `sighting`·`bridged`.
   - 아니면 천장 카메라 추적(D-457)의 MARKER 행 또는 확인된 map pose와 맞춘 MATCHED 행: `state` `CAMERA_ONLY`, `source` `tracking`. 표시 전용이며 위치 판정으로 쓰지 않는다.
   - 그 밖(`localization: null`의 pose, odom, UNKNOWN)은 기록하지 않는다. odom은 어떤 경우에도 지도 점이 되지 않는다.
2. **줄여 저장한다.** 직전 점에서 0.02 m 넘게 움직였거나 상태·출처·운행·대형·지도가 바뀌었거나 30 s가 지났을 때만 쓴다. 점을 못 고른 틱 뒤의 첫 점은 새 구간(`seg`)을 연다. 운행 중이면 `trip_id`, 대형이 켜져 있으면 Fleet이 붙인 `formation_id`를 함께 쓴다.
3. **사이트 DB에 둔다.** `--tasks-db`가 있으면 같은 SQLite 파일의 `fleet_robot_path` 표(백업·복원은 파일 단위 그대로), 없으면 메모리. 24 h 지난 점과 로봇당 86,400점을 넘는 점은 지운다.
4. **읽기 API.** `GET /api/fleet/robots/{robot_id}/path?since=&until=&last_s=&trip_id=`(viewer 이상, 한 번에 최대 5,000점, 넘으면 최신 쪽과 `truncated: true`). 로봇 API와 envelope 1.0은 바뀌지 않는다.
5. **콘솔은 기록을 그린다.** `trail-view.js`가 2 s마다 이 API를 이어 받아(처음은 범위 전체, 다음은 마지막 점 이후) 그린다. 새로 고쳐도 남는다. 범위는 최근 2분 · 10분 · 이번 운행(열린 운행, 없으면 최근 운행), 로봇마다 켜고 끈다. LOCALIZED 실선, DEGRADED 파선, CAMERA_ONLY 점선. 테더 원의 밖·안 판정도 LOCALIZED·map 보고만 쓴다(D-526 감시와 같은 기준).

### Consequences

- 모터 모드 로봇은 천장 카메라 map pose나 추적이 없으면 궤적이 없다. 틀린 선보다 빈칸이 낫다.
- 기록은 표시와 다시 보기 전용이다. 교통·경로·운행·정지 판단은 이 표를 읽지 않는다. 안전 경로(D-526 테더 감시, CORE 정지)는 바뀌지 않는다.
- 남은 일: 지도 위 로봇 아이콘은 여전히 `state.pose`를 그대로 그린다(같은 odom 문제, 별도 변경). 대형별 조회 필터, 현장 1일 저장량 측정.
- 시험: `operations/fleet/test/test_path_history.py`, `operations/fleet/test/web/trail-view.test.mjs`, `test_start_point_browser.py::test_map_draws_the_travelled_trail_and_a_tether`.
