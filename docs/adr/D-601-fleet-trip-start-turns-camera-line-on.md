## D-601 Fleet trip 출발이 카메라 차선 주행을 직접 켜고, 출발 자세와 차선 카메라를 먼저 본다

**Status:** Proposed (2026-10-10, 사용자 결정 A–D: "Fleet이 출발 때 켬", "출발점에서 방향이나 이런 게 맵에 맞는지 보고 Fleet이 결정하도록"). SOURCE 변경과 호스트 테스트만 한다. 사이트 배포와 현장 수용은 이 기록이 하지 않는다.

잇는 결정: [D-494](D-494-fleet-trip-execution-m2-contracts.md) 구현 부록 9항(모든 끝에서 멈춤)·11항(시작 검사, 이 기록이 고친다) · [D-541](D-541-core-fleet-trip-lease.md) 5·7항(trip lease 소유자) · [D-489](D-489-fleet-route-planning-concept-and-algorithm.md) 5항(출발 snap) · [D-536](D-536-fleet-robot-situation-and-coordinate-guide.md)(guide 차로 상황) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 정지). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- 2026-10-10 현장: 로봇들이 일방 차로 반대 방향으로 주차돼 있었다(사용자: 지도는 맞다). rosy_40(8kcn)은 사람이 돌려 세워야 했다. 그전에는 자세 출처 버그로 경로 미리보기가 막혀 있었다(main `7c0ac7f0f`에서 고침).
- 지금 trip 출발은 lane 간선이 있으면 로봇의 line-follow 모드가 `CAMERA_LINE`이 아닐 때 422 `TRIP_LINE_FOLLOW_NOT_ACTIVE`로 거절한다(D-494 11항). 운영자가 로봇 화면에서 먼저 켜야 했고, 켜는 순간 로봇은 trip 없이 움직인다.
- 콘솔 문구는 "카메라 또는 IR"이라고 했지만 받는 모드는 `CAMERA_LINE` 하나다.
- rosy_40은 앞 카메라가 죽어 있다. CORE capabilities는 line-follow 서비스가 있으면 `drive_modes`에 `lane`을 넣으므로, 계획은 통과하고 출발 뒤에야 차선을 잃는다.
- 계획기는 출발 자세를 `fleet.routing.heading_tol_deg`(60°) 안의 차로에 snap 한다. 60° 안이면 계획은 되고, 그 넘어는 `TRIP_HEADING_CONFLICT`인데 숫자가 없다.

### Decision

1. **A. 출발이 카메라 차선 주행을 켠다.** lane 간선이 있는 계획의 출발에서 로봇 모드가 `OFF`이면 거절하지 않는다. 모든 시작 검사(능력, 바쁨, 자세, 출발 정렬 4항, lease, 정지 자리, 대열, 신호, 고리)를 통과하고, trip lease(D-541 7, 설정이 켜져 있으면)를 쥐고, trip이 열려 저장된 뒤 **마지막으로** Fleet이 로봇 토큰으로 `PUT /api/v1/line-follow/mode {mode: CAMERA_LINE}`을 보낸다. 운영자 경로(`POST /api/fleet/robots/{id}/line-follow`)는 그대로 `IR_LINE`·`OFF`만 받는다. trip 루프만 켤 수 있다(`HttpRobotClient.line_follow_trip_start`).
   - 이미 `CAMERA_LINE`이면 보내지 않는다(지금과 같다). `IR_LINE`이나 모르는 모드는 그대로 422 `TRIP_LINE_FOLLOW_NOT_ACTIVE`다. IR은 교차로를 못 보고(D-313 복구 선택), 모르는 상태에서 켜지 않는다.
   - CORE가 거절하거나 응답이 없으면 trip은 `failed(TRIP_LINE_FOLLOW_START_FAILED)`로 끝나고 D-494 9항대로 로봇을 멈춘다(교차로 `stop` + 모드 `OFF`). 출발 응답은 409 `TRIP_LINE_FOLLOW_START_FAILED`(`detail {error, status}`, `error`는 CORE 코드, 예 `MODE_CONFLICT`·`CALIBRATION_ACTIVE`)다.
   - 켜는 요청이 가는 동안 취소·E-Stop·lease 상실이 trip을 닫으면, 응답 뒤에 한 번 더 멈춘다(`_after_send`, D-494 10항과 같은 규칙).
   - 켠 trip은 `detail.line_follow_started: true`를 남긴다.
2. **끝에서는 언제나 끈다.** trip의 모든 끝(도착, 취소, 실패, 멈춤, 재시작)은 지금처럼 `OFF`를 보낸다. 출발 전에 이미 `CAMERA_LINE`이었어도 되돌리지 않고 끈다. 이유: D-494 9항은 "모든 끝에서 바로 멈춘다"이고, 이전 모드로 되돌리면 trip이 끝난 로봇이 계속 달린다. 다음 trip은 꺼진 로봇을 다시 켜므로 운영자가 할 일이 없다.
3. **B. 차선 카메라가 죽은 로봇은 계획에서 거절한다.** lane 간선이 있는 계획을 돌려주기 전에 Fleet은 로봇 `GET /api/v1/vision/front/status`(이미 있는 CORE 경로, D-577 8도 쓴다)를 한 번 읽는다. `available`이 `true`가 아니거나 읽지 못하면 422 `TRIP_LANE_CAMERA_UNAVAILABLE`(`detail {stale, age_ms}` 또는 `{error}`)이고 계획 기록에 남는다. 앞 카메라 미리보기는 line-follow 모드와 상관없이 road observer가 카메라 프레임마다 낸다. 그래서 CORE API를 바꾸지 않고 "지금 프레임이 들어오는가"를 본다. capabilities의 `drive_modes`는 바꾸지 않는다(서비스가 있다는 뜻으로 둔다).
4. **D. 출발 자세를 지도에 맞춰 Fleet이 정한다.** 출발(`/start`) 때 같은 D-494 3 지도 자세(`MapPose` `LOCALIZED`)를 계획의 첫 간선(lane일 때만)에 투영해 본다.
   - 차로 밖: 첫 차로 중심선에서 차로 폭의 절반보다 멀면 422 `TRIP_START_OFF_LANE`. 이 경계는 trip 루프의 차로 이탈 규칙(`_locate`)과 같다.
   - 방향: 투영점의 차로 방향(계획이 탈 방향, 일방이면 그 방향)과 로봇 yaw의 차가 `fleet.trip.start_heading_tol_deg`(기본 20°, 상한 90°)를 넘으면 422 `TRIP_START_HEADING_MISMATCH`. yaw가 없으면 같은 코드다.
   - `detail`은 `{code, edge_id, heading_err_deg, tol_deg, off_lane_m}`이다. 첫 간선이 `free`면 보지 않는다. D-517 2 반복 랩의 다음 랩 검사에는 쓰지 않는다(달리는 중 곡선에서 랩 hold를 만들지 않게).
   - 계획 응답에 같은 검사 결과 `start_check`를 싣는다. 콘솔(관제 카드와 현장 지도)은 "출발" 앞에 "출발 가능 / 방향 반대(178°) / 방향 어긋남(35°) / 차선 밖 5 cm"를 보이고, 문제가 있으면 출발 버튼을 그 이유로 끈다. 출발은 새 자세로 다시 검사한다.
   - 계획기의 `TRIP_HEADING_CONFLICT`(60° 안의 차로가 없음)와 `TRIP_START_OFF_MAP`도 숫자를 싣는다: `detail.heading_err_deg`(반폭 안 차로 가운데 가장 작은 방향 차), `detail.off_lane_m`.
   - 출발 정렬 검사는 새 함수 하나(`trip_admission.start_check`)다. guide의 `lane_context`(D-536)는 로봇 근처에서 가장 맞는 차로를 고르지만, 출발은 계획의 첫 간선과 비교해야 한다. 그래서 같은 `Arc.project`와 `wrap`을 쓰고 차로 선택은 다시 하지 않는다.
5. **자동 제자리 정렬은 이번에 하지 않는다(후속).** CORE에 "이 방향까지 돌아라" 명령이 없다. 위치 미션 `rotate_in_place`(D-395 P2-7)는 LOCALIZED가 아닐 때 찾기용으로 한 바퀴까지 도는 것이고, 목표 각도가 없다. Fleet이 천장 카메라 자세를 보며 미션을 끊는 폐루프는 새 이동 경로다. 권고: CORE에 목표 yaw를 받는 회전 미션을 더한다(`rotate_to` `{target_yaw_odom, max_deg ≤ 180, angular ≤ rotate_angular}`). D-424 몸체 반경 + `rotate_margin_m` LiDAR 여유, 300 ms watchdog, E-Stop, D-422 몸체 정지를 그대로 쓰고, 여유가 없으면 거절한다. Fleet은 `TRIP_START_HEADING_MISMATCH`이고 |오차| > tol일 때만, trip lease를 쥐고, 운영자 확인 뒤 한 번 보내고, 끝난 뒤 4항을 다시 본다. 이 후속은 새 ADR과 Safety-Review로 한다.
6. **C. 문구.** `TRIP_LINE_FOLLOW_NOT_ACTIVE`는 "IR 차선 주행 중이거나 차선 주행 상태를 알 수 없습니다 · 차선 주행을 끈 뒤 다시 출발하세요"다. 새 코드 문구를 콘솔 표에 더한다.

### Safety-Review

이 기록은 **운동 허가**를 바꾼다. 지금까지는 운영자가 로봇에서 직접 `CAMERA_LINE`을 켜야 trip이 출발했다. 이제 Fleet이 켜고, 켜는 즉시 로봇이 움직인다.

- **켜는 때.** 모든 시작 검사가 통과하고, 같은 로봇 잠금 안에서, lease를 쥔 뒤, trip이 열리고 저장된 다음이다. trip이 열려 있으므로 모든 끝(취소, E-Stop, lease 상실, 루프 오류, 재시작)이 `OFF`를 보낸다. 켜는 응답 전에 trip이 닫히면 응답 뒤에 다시 멈춘다.
- **교차로 지시.** CORE는 모드가 바뀔 때 교차로 지시를 지우고, 모드가 꺼져 있으면 지시를 받지 않는다(D-494 4항 8, `LINE_FOLLOW_NOT_ACTIVE`). 그래서 지시를 먼저 둘 수 없다. 출발 잠금이 풀리면 다음 tick(최대 0.5 s)이 다음 장소의 지시를 보낸다. 그 사이 교차로를 만나면 CORE는 지시 없는 교차로에서 `waiting`으로 선다(D-494 4항). 이 공백은 이미 trip 중에도 있는 경우와 같다.
- **바뀌지 않는 것.** CORE의 `PUT /line-follow/mode` 검사(수동 해제, 보정·trip lease 소유자 D-541 3, E-Stop, 도킹, 매핑, LOCALIZED 게이트), D-422 몸체 정지, 300 ms watchdog, E-Stop, D-517 통행권(통행권이 필요한 로봇은 첫 통행권 전에는 움직이지 않는다), CORE 단일 `/cmd_vel`(D-2).
- **좁힌 것.** 4항은 출발을 더 좁힌다(20°, 차로 반폭). 3항은 계획을 더 좁힌다.
- **넓힌 것.** `OFF` 로봇의 출발 하나뿐이다. `IR_LINE`·모르는 모드는 여전히 거절한다.
- 독립 리뷰: 아래 Review 절.

### Alternatives

| 대안 | 판단 |
|---|---|
| 끝날 때 출발 전 모드로 되돌린다 | 기각. 이미 `CAMERA_LINE`이던 로봇은 trip이 끝난 뒤에도 달린다. D-494 9항과 맞지 않는다 |
| CORE capabilities가 카메라가 죽으면 `lane`을 빼거나 `line_camera_ready`를 낸다 | 보류. CORE API·버전·이미지 배포가 필요하다. 이미 있는 `vision/front/status`로 같은 것을 지금 볼 수 있다 |
| 출발 정렬을 guide `lane_context`로 본다 | 기각. 가장 가까운 차로를 다시 고른다. 출발은 계획의 첫 간선과 맞아야 한다 |
| 계획기 `heading_tol_deg`를 20°로 낮춘다 | 기각. 시작점 검증(활성화)과 반복 랩 계획에도 쓰인다. 출발 검사만 좁힌다 |
| Fleet 폐루프로 `rotate_in_place`를 끊어 정렬 | 기각(이번). 목표 각도 없는 찾기 미션이고, 끊는 시각이 네트워크·카메라 지연에 달린다. 5항 권고 |

### Validation

- `operations/fleet/test/test_trip_start_d601.py`: `OFF` 로봇을 마지막에 켬과 끝의 `OFF`, 이미 켜진 로봇은 보내지 않음, 검사 거절 때는 켜지 않음, CORE 거절 → `failed` + 멈춤, 켜는 중 취소 → 다시 멈춤, 랩 검사는 여전히 `CAMERA_LINE` 요구, 178°·25°·차로 밖 거절과 15° 통과, `start_check` 순수 함수, 계획기 숫자, 카메라 검사(죽음·읽기 실패), 계획 경로의 `start_check`·`TRIP_LANE_CAMERA_UNAVAILABLE`.
- `test_trip_runner.py`: 시작 거절 순서(모르는 모드·`IR_LINE`). `test_transport.py`: `CAMERA_LINE` PUT과 `front/status` GET. `test/web/trip-path.test.mjs`: 콘솔 문구.
- 호스트 테스트는 장치·현장 수용을 대신하지 않는다. 현장에서 볼 것: rosy_40(앞 카메라 죽음)이 계획에서 `TRIP_LANE_CAMERA_UNAVAILABLE`, 반대로 선 로봇이 "방향 반대", 꺼진 로봇의 출발이 켜고 달리고 끝에서 끄는 것.

### Review

(독립 리뷰 결과를 착지 전에 적는다.)

### Consequences

- API Reference v1.191: `/trip`(B·D), `/trips/{plan_id}/start`(A·D) 행과 변경 이력 한 줄. 로봇 API는 바뀌지 않는다.
- 사이트 설정 `fleet.trip.start_heading_tol_deg` 하나가 생긴다.
- trip_runner의 시작 검사와 진행 판정은 `server/trip_admission.py`·`server/trip_progress.py`로 옮겼다(크기 판정 seam, 동작 변화 없음).
