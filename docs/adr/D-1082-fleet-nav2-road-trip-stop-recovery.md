## D-1082 Nav2 도로 trip이 위험이 아닌 이유로 멈추면 Fleet은 trip을 끝내지 않고 복구해 지금 위치에서 다시 보낸다

**Status:** Accepted (2026-11-27, 사용자 요청 "멈췄을 때 경로 복구하고 다시 따라가는 게 당연히 있어야 하는데 없다, 조정·처리해 줘"; 사용자 원칙 "로직 결함·일시 문제로 운행을 끝내거나 사람을 기다리게 하지 않는다, 실제 위험 정지는 유지, 가드 값 완화 금지"). 구현은 이 ADR과 같은 PR이다. 실물 수용은 남았다.

| 결정 | 관계 |
|---|---|
| [D-494](D-494-fleet-trip-execution-m2-contracts.md) | 개정한다. 5항 "trip의 모든 끝은 기체를 세운다"는 그대로다. Nav2 도로 trip의 `stall`·`navigation` 정지는 이제 trip의 끝이 아니라 복구다. 기체는 같은 방식(경로 취소 → 취소 확인)으로 선다. |
| [D-1080](D-1080-fleet-nav2-lane-departure-realign.md) | 지킨다. 같은 재전송 경로(`sample_nav2_route(here=)`, 차선 복귀 경로)를 쓴다. D-1080이 바꾼 경로(`superseded`)의 CANCELED는 중단으로 읽히지 않으므로 이 복구에 오지 않는다. |
| [D-1009](D-1009-core-route-drive-pass-and-stop.md) | 지킨다. 새 모션 writer가 없다. 재전송은 기존 `step_nav2_route`가 한다. |
| 자율 기체 Nav2 FAILED 재시도(`_handle_nav2_failure`) | 지킨다. 자율 기체의 FAILED는 그쪽이 먼저 맡고 `_stop`을 부르지 않는다. 이 복구는 그 밖의 경우(자율 기체의 CANCELED, 다른 기체의 FAILED·CANCELED)만 맡는다. 한 사건을 두 경로가 처리하지 않는다. |
| transient_loc_hold(robot-d3, #1107·#1124·#1135) | 겹치지 않는다. `pose` 정지의 대기와 그 한도는 그쪽이 소유한다(위치 재확정 45 s #1107, 연결 불가 45 s #1124, 서 있는 기체의 DEGRADED·UNKNOWN 자세 120 s #1135). 그 대기가 끝난 뒤의 `pose` 종료와 움직이는 기체의 `pose` 정지는 #1135가 시험으로 고정한 의도된 종료이므로 이 복구는 `pose`를 다루지 않는다. `map_frame` 정지도 복구하지 않는다. |
| D-972 충전 칸 | 지킨다. 충전 칸 간선, parking handoff, DOCKING에서는 복구하지 않는다. |
| `nav2_off_lane_margin_m`·stall_s·keep-out·위치 신뢰 기준 | 바꾸지 않는다. |

### Context

2026-11-27 실물 Nav2 도로 trip이 다음 이유로 끝났다(위치 계열은 #1107·#1135가 대기로 맡았다). 모두 기체는 멀쩡했고 사람이 trip을 다시 시작해야 했다.

- `stopped/pose`: pose_state DEGRADED, 카메라 stale_source(rosy_46 P3행).
- `stopped/stall`: Nav2 "Failed to make progress"(rosy_45 P3행).
- `stopped/navigation`: Nav2 CANCELED·FAILED.

### Decision

1. **범위.** `drive_mode: nav2` 도로 trip만. 다음은 제외하고 종전대로 끝난다: 충전 칸 간선·parking handoff·DOCKING, 정밀 정차(strict named stop) 구간, 카메라 차선 대체 구간, wait-prefix(대기 칸 예약) 경로, hold 중(일시 정지·replan·nav2_problem), link_wait.
2. **복구 사유.** `TripRunner._stop(live, "stopped", reason)`의 `reason`이 `stall`·`navigation`이고, 정지 detail에 `link_wait`(기체 응답 없음)가 없을 때. `pose`는 다루지 않는다(위 transient_loc_hold 행). 진입 조건: 기체 상태를 읽었고 `safety.estop`이 `false`, 모드가 MANUAL·ESTOP 아님, 활성 지도 버전이 trip과 같음.
3. **진입.** `_stop` 대신 현재 경로를 취소하고 취소 확인(`_cancel_ack`)을 받는다. 확인이 없으면 종전대로 끝난다. trip은 `running`이고 `detail.recovery = {state: waiting, label: "복구 중", reason, attempt, since, entered_at, waiting_for, stop_detail}`를 남긴다.
4. **해소.** 매 tick `step_nav2_route` 앞에서 본다. trip 자세는 이미 LOCALIZED·신선해야 이 지점에 온다(기존 `_progress_pose`; 아니면 transient_loc_hold가 맡는다). 진입 뒤 2 s(`NAV2_TRANSIENT_RETRY_S`) 경과, 서로 다른 두 tick의 기체 상태 읽기에서 연속으로 정지 확인(신선한 속도 0, NAVIGATING·PLANNING 아님). 대기 중에도 매 tick 진입 조건(estop, MANUAL·ESTOP·DOCKING, hold, 제외 구간, 지도 버전)을 다시 보고, 어긋나면 종전 사유로 끝낸다(`detail.recovery_end`: `estop`·`out_of_scope`). 상태를 읽지 못한 tick은 재전송하지 않고 기다린다.
   - 해소되면 `state: resumed`로 바꾸고 기존 step 루프가 지금 위치에서 차선 복귀 경로를 보낸다.
5. **한도.** 한 번의 대기는 45 s, 한 사건(episode)은 복구 3회 또는 첫 복구 뒤 5분 중 먼저 닿는 쪽. 넘으면 종전 사유와 종전 detail로 끝난다(`recovery.state: exhausted`, 대기 한도는 `recovery_end: wait_s`·`window`). 대기 중 E-stop이 보이면 바로 끝난다.
6. **사건 종료.** 재전송 뒤 1.0 m를 진행하면 사건을 닫는다(`detail.last_recovery`, 횟수·5분 창 초기화). 1.0 m는 차선 복귀 보정보다 길어서, 한 지점에서 계속 실패하는 기체는 한도를 다 쓰고 끝난다.
7. **값.** `operations/fleet/fleet/server/trips/nav2_trip_recovery.py`의 모듈 상수(`MAX_ATTEMPTS`, `WINDOW_S`, `WAIT_S`, `SETTLE_S`, `RESET_M`).

### 정지 사유 전수(2026-11-27 origin/main + #1135 기준)

| 사유(state/reason) | 위치 | 처리 | 소유 | 근거 |
|---|---|---|---|---|
| stopped/pose: 서 있는 기체의 DEGRADED·UNKNOWN 자세 | `transient_loc_hold` | 120 s 대기 뒤 종료 | #1135 | 의도된 한도, 시험 고정 |
| stopped/pose: 위치 재확정(CANDIDATES·SUSPECT·UNKNOWN, 바인딩) | `transient_loc_hold` | 45 s 대기 뒤 종료 | #1107 | 위치 미신뢰 해제 금지 |
| stopped/pose: 움직이는 기체의 쓸 수 없는 자세 | `handle_unlocalized_pose` | 종료 | #1135 | 움직이는데 위치 모름 = 위험 |
| stopped/pose + `off_lane_m` | `trip_steps` 중심점 off-lane | 종료 | 기존(D-1080) | off-lane 백스톱 |
| stopped/stall | `trip_steps` `_stalled` | 복구 | 이번 PR | 진행 없음. 정지 확인 뒤 재전송 |
| stopped/stall + `link_wait` | `trip_progress._link_wait` | 종료 | 기존(D-760) | 기체 응답 없음, 정지 증명 불가 |
| stopped/navigation: 자율 기체 FAILED | `_handle_nav2_failure` | 대체 경로·재시도·hold | 기존 | 먼저 처리, `_stop` 안 부름 |
| stopped/navigation: 그 밖의 FAILED, 요청 안 한 CANCELED | `step_nav2_route` | 복구 | 이번 PR | 일시 Nav2 실패 |
| D-1080이 바꾼 경로의 CANCELED | `_route_finished` | 재전송(중단 아님) | 기존(D-1080) | 우리 취소 |
| stopped/navigation: wait-prefix 경로 | `step_nav2_route` | 종료 | 기존 | 대기 칸 예약 경로, 범위 밖 |
| stopped/map_version | `step_nav2_route`, `trip_steps` | 종료 | 기존 | 지도 버전 변경 |
| stopped/map_frame (MAP_FRAME_MISMATCH, MAP_BINDING_REQUIRED·CHANGED·GRID_CHANGED, APPROVED_SLAM_POSE_REQUIRED, 45 s 뒤 ROBOT_NOT_LOCALIZED) | `_convert_points`, `recheck_binding`, `trip_steps` | 종료 | #1107(대기), 기존 | 프레임 불일치·바인딩 |
| stopped/WAIT_PREFIX_RESERVATION_LOST | `step_nav2_route` | 종료 | 기존 | 예약 상실 |
| stopped/ROAD_SPEED_OWNER_MISSING, failed/ROAD_SPEED_OWNER_CHANGED | `step_nav2_route`, `RoadSpeedRefused` | 종료 | 기존 | 속도 권한 소유 상실 |
| stopped/lease_lost | `_lease_lost`(`_stop` 안 거침) | 종료 | 기존(D-541) | lease 상실 |
| stopped/lane_arc, junction, junction_unexpected, junction_corner_hold, junction_no_window | `trip_steps` lane 구간 | 종료 | 기존 | lane 구간. Nav2 trip은 해당 없음 |
| stopped/TRIP_CAMERA_FALLBACK_* | `trip_steps` | 종료 | 기존 | 카메라 차선 대체 구간 |
| stopped/<parking 오류 코드> | `trip_steps` rear bay step | 종료 | 기존 | parking handoff 범위 밖 |
| failed/TRIP_ROBOT_UNREACHABLE | `trip_steps` | 45 s 대기 뒤 종료 | #1124 | 범위 밖 |
| failed/GOAL_LEASE_NOT_ACTIVE | road speed 갱신 | 종료 | #1132 | 범위 밖 |
| failed/* 그 밖(TRIP_GOAL_REFUSED, TRIP_PAUSE_STOP_UNCONFIRMED, TRIP_POSE_UNTRUSTED, TRIP_LOOP_ERROR, STATION_ALIGN_* 등) | 여러 곳 | 종료 | 기존 | `stopped`만 복구 대상 |
| canceled (운영자 취소, E-stop `close_all`, line-follow OFF) | `cancel`, `close_all`, `cancel_robot` | 종료 | 기존 | `_stop`을 거치지 않음 |
| 일시 정지(hold stop) | `pause`, `_check_pause` | 정지 유지 | 기존 | trip이 끝나지 않음. hold 중에는 복구하지 않음 |
| 시작 거절(prior_stop_unconfirmed 등) | `start` | 거절 | 기존 | trip이 열리기 전 |
| 기체 `safety.estop` true 또는 모름 | 복구 진입·대기 판정 | 종료 | 이번 PR | E-stop은 복구하지 않음 |
| 경로 취소 확인 실패 | 복구 진입 | 종료 | 이번 PR | 정지 미확인 |

### Consequences

- 코드: `operations/fleet/fleet/server/trips/nav2_trip_recovery.py`(판정·진입·해소), `trip_runner.py` `_stop`(진입 한 줄), `trip_steps.py`(해소 판정 한 줄).
- 시험: `operations/fleet/test/test_nav2_trip_recovery.py`.
- 화면: trip detail `recovery.label`이 "복구 중"이다. 실행 단계(`execution.phase`) 표시는 바꾸지 않았다.
- 복구 대기 중에는 Fleet stall 판정을 쉬고(`progress_at`), 재전송 뒤 다시 시작한다. 같은 원인이 이어지면 최대 3회 × (45 s + stall_s) 안에 종전 사유로 끝난다.

### Open

- 실물 수용: robot-45·46 도로 trip에서 Nav2 progress 실패(stall), Nav2 FAILED, 요청 안 한 CANCELED 각각에 대해 `recovery` 기록 → 정지 확인 → 차선 복귀 경로 재전송 → 1 m 진행 뒤 `last_recovery` 순서를 확인한다.
- `pose`(DEGRADED) 정지를 #1135의 120 s 뒤에도 복구할지는 그 PR 소유자와 정한다. 지금은 종료다.
- 화면에 "복구 중"을 따로 보여 주는 UI는 이 변경에 없다.
- 3회·5분·45 s·1.0 m는 첫 값이다. 실물 기록으로 고친다.
