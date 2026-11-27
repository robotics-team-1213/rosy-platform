## D-1086 위험이 아닌 이유로 끝난 Nav2 도로 trip은 Fleet이 같은 요청으로 다시 계획·시작한다

**Status:** Accepted (2026-11-28, 사용자 지시 "멈추면 재시도를 최소한 3번 정도는 같은 경로로 시도하는 폴백 로직이 필요"; 세 세션 토론으로 방향 확정). 구현은 이 ADR과 같은 PR이다. 실물 수용은 남았다.

| 결정 | 관계 |
|---|---|
| [D-1082](D-1082-fleet-nav2-road-trip-stop-recovery.md) | 뒤를 잇는다. D-1082는 trip 안에서 다시 보내고, 이 결정은 trip이 닫힌 뒤 새 trip을 연다. D-1082가 `exhausted`로 끝났어도 같은 지점·같은 사유 반복(`recovery.same_spot`, D-1082 사다리 PR #1177)이면 다시 내지 않는다. 사다리 기록(`recovery.attempts`)이 없는 exhausted는 반복을 가릴 수 없으므로 다시 내지 않는다(#1177 병합 전에는 이 사유가 재발행되지 않는다). |
| [D-494](D-494-fleet-trip-execution-m2-contracts.md) | 지킨다. 새 trip은 기존 계획 경로(`app.state.trip_plan`, D-763 6)와 `TripRunner.start`로만 열리고, 시작 검사(배터리·caps·자세·교통·결속·lease)를 모두 다시 받는다. 새 모션 writer가 없다. |
| [D-1029](D-1029-low-battery-fleet-charge-return.md) 충전 복귀, D-763 6 작업 trip | 지킨다. 소유자가 있는 trip(`lease.job_id`, `purpose`, parking handoff)은 그 소유자가 재시도한다. 이 결정은 다시 내지 않는다. |
| transient_loc_hold(#1107·#1124·#1135) | 겹치지 않는다. 그 대기가 끝나 trip이 닫힌 뒤에만 본다. 대기 값은 바꾸지 않는다. |
| 가드 값·위치 신뢰·프레임 거절·정지 증명 | 바꾸지 않는다. 다시 내기 전 조건이 모두 "지금 다시 읽은 값"이고, 시작 검사도 그대로다. |

### Decision

1. **대상.** `drive_mode: nav2`이고 목적지가 이름 있는 장소인 도로 trip. 반복(repeat)·convoy·작업(job)·충전 세션·parking handoff trip은 제외한다.
2. **사유.** 아래 표의 "재발행" 행만. 그 밖은 기본 금지다(새 사유가 생겨도 표에 넣기 전에는 다시 내지 않는다). 공통 금지 조건: 정지 미확인(`halt_unconfirmed`), hold·일시 정지 중 종료, 운영자 취소(`canceled_by`), 교통 대기(`traffic_hold`·`peer_wait`), 카메라 차선 대체, off-lane 백스톱(`off_lane_m`).
3. **다시 내기 전 조건.** 예정 시각이 지나면 폴링(1 s)마다 다시 읽는다. 연속 두 번 모두 맞아야 시작한다: 기체에 열린 trip·작업 없음, 상태 읽기 성공, `safety.estop`이 `false`, navigation이 IDLE·ARRIVED·CANCELED·FAILED이고 신선한 속도 0(`_fresh_stopped`), goal 없음, 모드 IDLE 또는 NAVIGATION, localization LOCALIZED, 활성 지도 버전이 원 trip과 같음, 원 trip에 결속이 있었으면 같은 결속이 활성이고 현재 상태와 맞음(`matching_fit`). 하나라도 어긋나면 다음 간격만큼 미룬다.
4. **간격·한도.** 종료 뒤 10 s·20 s·40 s(n번째 재발행 앞 간격). 한 사슬(원 trip과 그 재발행들)에 최대 3회, 첫 종료부터 10분 안. 넘으면 원 사유가 그대로 남는다(`reissue.state: limit` 또는 `dropped: total_limit`). 계획·시작이 거절되면 그 코드를 남기고 그 회차를 쓴 것으로 센다(`start_refused`).
5. **운영자 우선·정지 이력.** 대기 중 그 기체에 다른 trip이 열리면(누가 열었든) 대기를 버린다(`dropped: new_trip`). 종료 뒤 E-stop(`close_all`, `_stop_epoch`)이나 그 기체의 line-follow OFF(`_start_cancels`)가 한 번이라도 있었으면, 지금 풀려 있어도 대기를 버린다(`dropped: stopped_since`).
6. **principal.** 원 trip을 시작한 principal(`started_by`)로 같은 요청을 계획·시작한다. 권한은 HTTP 경계(`require_named_operator`)에서 이미 확인되었고, `TripRunner.start`는 principal id만 기록한다. 원 요청과 같은 범위이므로 경계를 넓히지 않는다. 기록에 `by: auto_reissue`를 남기고 사이트 이벤트 `trip_reissue`를 쓴다.
7. **기록.** 끝난 trip: `detail.reissue = {state, attempt, max, kind, previous_reason, first_end_at, next_at, waiting_for, next_trip_id, error, dropped}`. 새 trip: `detail.reissued_from = {trip_id, root, attempt, previous_reason, first_end_at, by, principal}`. 사슬 횟수와 10분 창은 `reissued_from`으로 이어진다.
8. **재시작.** 대기는 메모리에만 있다. Fleet이 다시 뜨면 대기는 사라지고 기체는 움직이지 않는다. 다시 뜬 뒤 첫 폴링은 이미 닫힌 trip을 모두 본 것으로 표시한다.
9. **코드.** `operations/fleet/fleet/server/trips/trip_reissue.py`(판정·조건·시작), `trip_routes.py`(생성), `loop_supervision.py`(감독 루프).

### 종료 사유 전수와 재발행(2026-11-28 origin/main 기준, D-1082 표 확장)

| 사유(state/reason) | 재발행 | 근거 |
|---|---|---|
| stopped/pose (transient_loc_hold 대기 만료, 움직이던 기체 포함) | 재발행(`pose_wait_expired`) | 위치 문제는 시간이 지나면 풀린다. 다시 낼 때 정지 증명과 LOCALIZED 두 번을 다시 본다 |
| stopped/pose + `off_lane_m` | 금지 | off-lane 백스톱 |
| stopped/map_frame + ROBOT_NOT_LOCALIZED (위치 재확정 45 s 만료, #1107) | 재발행(`relocalization_wait_expired`) | 같은 결속에서 위치만 잃음 |
| stopped/map_frame + MAP_FRAME_MISMATCH, MAP_BINDING_REQUIRED·CHANGED·SITE_CHANGED, GRID_CHANGED 등 | 금지 | 프레임·결속 변경 |
| stopped/map_version | 금지 | 지도 버전 변경 |
| failed/TRIP_ROBOT_UNREACHABLE (#1124 45 s 만료) | 재발행(`robot_unreachable`) | 연결이 돌아오면 상태 읽기 두 번으로 확인 |
| failed/TRIP_ROBOT_UNREACHABLE + kind RuntimeError·ValueError | 금지 | 연결이 아니라 Fleet 쪽 결함 |
| failed/GOAL_LEASE_NOT_ACTIVE (#1132 유예 뒤) | 재발행(`goal_lease_ended`) | 상태 읽기 지연과 lease 끝의 경쟁. 다른 주인이 lease를 잡은 경우는 goal 없음 조건(`robot_idle`)과 시작의 lease 열기가 막는다 |
| stopped/stall·navigation, D-1082 `exhausted` (4번째 정지 또는 5분 창) | 재발행(`recovery_exhausted`) | trip 안 재시도를 다 쓴 일시 실패 |
| 위 + `recovery.same_spot` | 금지 | 같은 자리·같은 사유 반복은 같은 요청으로 다시 실패한다 |
| 위 + `recovery_end` estop·out_of_scope·wait_s, 또는 `waiting_for`가 남은 exhausted(대기 만료) | 금지 | E-stop, 범위 변경, 정지 증명 실패 |
| 위 + 사다리 기록(`recovery.attempts`) 없음 | 금지 | 같은 지점 반복을 가릴 수 없음 |
| stopped/stall 복구 없이(link_wait 등) | 금지 | 기체 응답 없음, 범위 밖 |
| stopped/lease_lost, ROAD_SPEED_OWNER_MISSING, failed/ROAD_SPEED_OWNER_CHANGED | 금지 | 소유권 상실(다른 주인) |
| stopped/WAIT_PREFIX_RESERVATION_LOST, junction·lane_arc 계열, TRIP_CAMERA_FALLBACK_* | 금지 | 예약·lane·카메라 구간 |
| failed/TRIP_PAUSE_STOP_UNCONFIRMED, 정지 미확인(`stop_sent: false`, `error`) | 금지 | 정지 미확인 |
| failed/TRIP_BATTERY_*, CHARGE_BAY_DOCK_FAILED, DOCK_TIMEOUT, 도킹 custody | 금지 | 배터리 정책, CORE 도킹 재시도 규칙 소유 |
| failed/TRIP_LEASE_UNSUPPORTED 등 capability 없음, TRIP_GOAL_REFUSED, TRIP_POSE_UNTRUSTED, MAP_FRAME_MISMATCH, TRIP_LOOP_ERROR, STATION_ALIGN_* | 금지 | 기본 금지(다시 내도 같은 거절) |
| canceled (운영자 취소, E-stop `close_all`, line-follow OFF) | 금지 | 사람·안전 정지 |
| hold·pause 중 종료, traffic_hold·peer_wait로 서 있던 trip | 금지 | 사람 결정, 교통 교착은 교통 쪽 몫 |
| 작업(job)·충전 세션·parking handoff·repeat·convoy trip | 금지 | 소유자가 재시도(JobTripSteps.plan, ChargeReturnTrip) |

### Consequences

- 시험: `operations/fleet/test/test_trip_reissue.py`(대상 사유별 재발행, 조건 미충족 시 대기, 읽기 두 번, 3회·10분 한도, 금지 사유 전부, 다른 trip이 대기를 버림, 시작 거절 기록, 원·새 trip 연결).
- 화면: 끝난 trip의 `detail.reissue`와 새 trip의 `detail.reissued_from`을 API가 그대로 보여 준다. 전용 UI는 없다.
- 같은 사슬은 최대 3번 더 시작한다. 각 시작은 일반 시작과 같은 검사를 받으므로, 재발행이 시작 검사를 우회하지 않는다.

### Open

- 실물 수용: robot-45·46에서 pose 대기 만료, 연결 끊김 45 s, D-1082 exhausted 각각에 대해 10 s 뒤 재발행·연결 기록을 확인한다.
- 원 principal의 권한이 대기 10분 사이에 취소되어도 재발행은 그 id로 시작한다(`TripRunner.start`는 역할을 다시 보지 않는다). 권한 취소 즉시 막아야 하면 사이트 인증 저장소 조회를 추가한다.
- 기체가 이전 goal을 쥐고 있으면 취소하지 않고 기다린다(`robot_idle`). 취소 후 재발행이 필요한지는 실물 기록으로 정한다.
- 10 s·20 s·40 s, 3회, 10분은 첫 값이다.
