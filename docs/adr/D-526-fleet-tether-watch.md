## D-526 Fleet가 충전 케이블 tether를 감시하고 한도에서 CORE E-Stop으로 세운다

**Status:** Proposed (2026-10-08). 1단계(Fleet 감시·정지·표시)를 `feat/fleet-tether-watch`에 구현했다. 호스트 시험(가짜 로봇)까지만 했다. 이 ADR로 로봇을 움직이거나 세운 적은 없다. `tether_watch.py`는 D-430 safety 태그 파일이라 독립 Safety-Review 전에는 착지하지 않는다.

사용자 결정(2026-10-08, D-512 개정 1): "선이 꼬이거나 너무 멀리 가게 되면 이를 멈추도록 Fleet에서 지시해." D-512 개정 1 5항이 이것을 Fleet 후속으로 남겼다.

### Context

- D-512 개정 1은 충전 케이블을 꽂은 채 실기 시험을 허용했다. 감시와 집행은 에이전트 도구 `tools/device_test`(`tether.py`, `run.py`)만 한다. 정지 반경은 케이블 길이(2 m 또는 5 m) − 여유 0.3 m이고, 누적 회전 한도는 ±360°다. 한도에 닿으면 도구가 기록한 odom 길을 따라 뒤로 되돌아간다.
- 도구가 죽으면 D-512의 hold가 끊겨 CORE가 멈추지만, 사람이 대시보드로 몰거나 다른 세션이 움직이면 케이블 감시가 없다.
- Fleet에는 테더 선언이 있다(API v1.140): named operator가 `POST /api/fleet/robots/{robot_id}/tether`로 map 프레임 기준점 `anchor_xy`와 `radius_m`을 둔다. Fleet 지도는 원과 지나온 길을 그리고(`web/trail-view.js`), 자세는 `GET /api/fleet/state`의 상태 `pose`다. `localization.pose_frame`이 `odom`이면 지도 좌표가 아니라 그리지 않는다.
- Fleet가 로봇 하나를 세우는 기존 경로: 로봇 E-Stop(`RobotClient.estop()`, CORE `POST /api/v1/safety/stop`, 전체 정지 `estop_all`과 `/api/fleet/do`의 `stop`이 같은 클라이언트를 쓴다), 항법 취소, line-follow OFF, trip의 `TripHalts.halt_robot`(교차로 stop → line-follow OFF). CORE가 유일한 최종 `/cmd_vel` 발행자다.
- 안전 거버넌스는 D-430이다. 래치 정지는 자동으로 풀리지 않는다(§4). safety 태그 파일의 변경은 독립 리뷰와 `Safety-Review:` trailer가 필요하다(§5).

### Decision

1. **감시 대상과 입력.** Fleet `TetherWatch`(`operations/fleet/fleet/server/tether_watch.py`)가 테더 선언이 있는 로봇만 0.5 s마다 본다. 자세는 지도와 같은 출처다: 신선한 hub heartbeat 상태, 아니면 CORE REST 상태(`FleetConsole._gather_state`)의 `pose {x, y, yaw}`. 지도 자세는 신뢰하는 자세만이다(`fleet.localization.trust.classify == TRUSTED`: `localization`이 LOCALIZED이고 `pose_frame`이 `map`, Fleet 추적·교통정리와 같은 규칙). `localization`이 없는 로봇(D-395 이전), odom, 후보·의심·모름 상태, 값이 유한하지 않은 자세는 그 틱의 자세가 없다. 자세의 신선도는 CORE가 채널별로 판정한 `state.evidence.pose`에서 온다(`evidence == "fresh"`, `STALE_POSE_S` 2 s). 그 항목이 없으면(구형 CORE) 자세가 없고 2 s 뒤 정지한다. 상태의 `timestamp`는 스냅샷을 만든 시각이라 얼어붙은 자세에도 바뀌므로, 같은 `timestamp`가 반복되는 캐시된 hub 상태를 거르는 데만 쓴다(heartbeat 1 Hz, 틱 0.5 s라 두 번 반복돼도 그 틱만 건너뛰고, 정지는 2 s 자세 나이만 정한다). 매 틱 잰다:
   - 거리: 자세와 `anchor_xy`의 거리.
   - 회전: 선언(POST) 뒤 첫 자세부터 연속한 두 yaw 차이를 (−π, π]로 접어(`math.remainder`) 더한 펼친 누적 yaw. ±180° 경계를 넘어도 한쪽으로 쌓인다.
   - 자세 나이: 마지막 신선한 자세(없으면 선언 시각)부터의 시간.
2. **정지 조건과 정지 경로.** 아래 가운데 하나면 트립이다.
   - `tether_radius`: 거리 > `radius_m` + 0.15 m(`RADIUS_SLACK_M`).
   - `tether_turn`: |누적 회전| > 405°(`TURN_LIMIT_DEG` = 360 + 45).
   - `tether_pose_stale`: 자세 나이 > 2 s(`STALE_S`). 닫힌 쪽으로 실패한다. 연결이 끊긴 로봇, odom 자세만 주는 로봇, `localization`이 없거나 신뢰하지 못하는 로봇도 여기에 걸린다. 지도 자세가 없는 로봇은 2 s 안에 세워진다(fail-closed). 오버헤드 카메라 추적(D-395/D-515)이 그 로봇에 지도 자세를 줄 때까지 그렇다.

   트립이면 기존 로봇 E-Stop을 그 로봇 하나에 보낸다(`console.hub.scatter_estop`, 전체 정지와 같은 `RobotClient.estop()`). 이어서 그 로봇의 열린 trip을 `tether_trip`으로 끝낸다(`TripRunner.cancel_robot`, 기존 경로). 새 정지 경로나 새 CORE API는 만들지 않는다. E-Stop을 고른 이유: 항법 취소와 line-follow OFF는 수동 조종(teleop, D-512 도구의 MANUAL)을 세우지 못한다. CORE E-Stop은 모든 모드를 세우고 래치된다.
3. **되돌아가기는 운영자 몫이다.** Fleet는 되돌아가기를 지시하지 않는다. 이유:
   - 되돌아갈 길은 로봇 자신의 odom 기록(1 cm 표본)이다. 그 기록은 D-512 도구에 있고 Fleet에는 없다. Fleet의 지나온 길은 브라우저가 1 s 상태 폴링으로 모은 지도 점이라 해상도와 신뢰가 다르다.
   - CORE에는 "기록한 길로 되돌아가기" API가 없다. Fleet가 teleop을 흉내 내 몰면 Fleet가 두 번째 구동자가 된다(D-12·D-2 위반).
   - Fleet가 트립했다는 것은 1차 보호(도구)가 이미 실패했거나 없다는 뜻이다. 그때 자동으로 더 움직이는 것보다 사람이 상황을 보고 고르는 것이 안전하다.

   운영자는 지도의 위험 색 원과 `GET /api/fleet/tethers` 행 `watch`로 트립을 본다. 회복은 기존 경로다: CORE E-Stop 해제(관리자 `POST /api/v1/safety/release`) 뒤 손으로 되돌리거나 D-512 도구의 되돌아가기를 쓴다.
4. **트립은 래치되고, 테더 POST가 재무장이다.** 트립 뒤에는 자세를 더 읽지 않고, E-Stop은 CORE가 답할 때까지 틱마다 다시 보낸다(`stop_sent`, `stop_error`). 답을 받으면 더 보내지 않는다(CORE E-Stop은 래치다). 같은 테더를 다시 POST하면 감시가 처음부터 시작한다(트립 해제, 누적 회전 0). DELETE는 감시를 지운다. 운영자는 케이블을 꼬임 없이 다시 놓은 순간 POST한다. 회전 기준이 그 순간이기 때문이다. Fleet 재시작은 테더와 감시를 모두 지운다(v1.140 메모리 저장 그대로).
5. **D-512 도구와 함께 쓴다 — Fleet는 backstop이다.** 두 정지자가 다투지 않도록 Fleet 한도를 도구 한도보다 늘 바깥에 둔다.
   - 운영자는 Fleet `radius_m`을 도구의 정지 반경(케이블 − 여유)과 같게 선언한다. 지도 원이 그 반경이다. Fleet는 그보다 0.15 m 바깥에서 트립한다. 도구 여유 0.3 m 안쪽이라 케이블 끝에 닿기 전이다.
   - 회전: 도구는 360°에서 트립해 270° 아래로 되감는다. Fleet는 405°에서 트립한다.
   - 그래서 도구가 살아 있으면 도구가 먼저 트립하고 되돌아가며, 되돌아가는 동안 거리와 회전이 줄어 Fleet는 트립하지 않는다. 도구가 죽었거나 사람이 몰면 Fleet가 E-Stop으로 세운다. 이때 E-Stop이 도구의 되돌아가기도 막는다. 의도한 것이다(1차 보호가 실패했다).
   - 회전 기준점이 다르다. 도구는 주행 시작부터, Fleet는 테더 POST부터 센다(그래서 테더 POST는 주행 직전에 한다). 결정 4대로 POST를 케이블을 놓은 순간에 하면 Fleet 값이 도구 값보다 크거나 같다. 그러면 Fleet가 먼저 트립할 수 있다. 그래서 45° 여유를 둔다. 주행 시작 직전에 POST하면 두 기준이 같아진다.
6. **감사.** 1단계는 Fleet 로그(`fleet.tether_watch`)에 남긴다: 트립(`robot`, `trip`, `distance_m`, `turn_deg`, `pose_age_s`), 정지 보냄, 정지 실패(오류 코드). 정지 한 번은 3 s(`STOP_TIMEOUT_S`) 안에 끝나야 하고, 한 로봇의 정지가 걸려도 다른 로봇은 같은 틱에서 처리된다. E-Stop이 10번(`ALARM_AFTER_FAILS`) 연달아 실패하면 `TETHER_STOP_FAILED`를 관제 `alarms`에 올리고(critical 로그) 재시도는 계속한다. 감시 루프의 마지막 틱 나이는 `GET /api/fleet/tethers`의 `watch_age_s`와 행 `watch.tick_age_s`이고, 지도는 2 s 넘게 틱이 없으면 테더를 트립 색으로 그린다. 루프가 죽으면 error 로그를 남긴다. 테더 설정·해제는 주체와 반경 변화(이전→새)를 로그로 남긴다. 테더 설정·해제는 기존 named operator 경로라 `set_by`가 남는다. 지속 감사(작업 DB의 API 감사 행)는 2단계다.
7. **D-430.** `tether_watch.py`를 `platform_parts.yaml` `safety_modules`에 태그하고 `TetherWatch`·`map_pose`를 공개 앵커로 둔다(Fleet 서버는 `decision` 관심사라 공개 앵커만 import한다). 이 파일은 표준 라이브러리와 신뢰 규칙 `fleet.localization.trust`만 쓴다. 정지는 CORE의 공개 경로(E-Stop)로만 요청한다. 래치를 자동으로 풀지 않는다.
8. **D-480 층.**

   | 항목 | 층 | 지금 |
   |---|---|---|
   | 거리·회전(±180° 경계)·자세 없음·테더 없음·정지 재시도 로직 | LOCAL | 호스트 시험 통과(가짜 로봇) |
   | 실제 앱 배선: 트립이 로봇 클라이언트 `estop`으로 나감, 목록 `watch`, 재무장 | LOCAL | 호스트 시험 통과 |
   | 다른 정지(trip, 교통정리, D-512 도구)와 한 로봇에서 겹칠 때 | ROS-SIM (M) | 미시험. 시뮬 E-Stop 래치·trip 종료를 Gazebo 두 대로 본다 |
   | 지도 자세 지연·끊김(Wi-Fi, heartbeat 1 Hz)에서 2 s 판정 | D | 미시험. 장치에서 heartbeat 나이 분포를 재고 `STALE_S`를 조정한다 |
   | 실제 E-Stop이 케이블 끝 전에 로봇을 세움(제동 거리 포함) | D (DEVICE) | 미시험. 케이블 주행 첫 실행에서 반경을 줄여(예: 0.5 m) 트립과 정지 위치를 Rosy Cam으로 기록한다 |
   | D-395 이전(odom 자세) 로봇 | D | 1단계는 `tether_pose_stale`로 세운다. 2단계 후보: D-472 LED 확인 트랙으로 거리, odom yaw 차이로 회전 |

### Consequences

- 도구 밖에서도 케이블 한도에 Fleet 정지가 있다. 사람이 대시보드로 몰 때도 선언만 있으면 걸린다.
- 테더를 선언한 로봇은 Fleet가 지도 자세를 2 s 잃으면 선다. 위치 추정이 없는 로봇(9dfk 같은 odom 자세)에 Fleet 테더를 두면 곧 선다. 그런 로봇의 케이블 주행은 2단계 전까지 D-512 도구가 맡고, Fleet 테더는 두지 않는다.
- 트립 뒤 회복에 관리자 E-Stop 해제와 사람 판단이 든다. 자동 되돌아가기보다 느리다.
- 회전은 0.5 s 표본의 yaw 차이로 잰다. 한 표본 사이에 180° 넘게 돌면(약 6 rad/s 이상) 방향을 잘못 셀 수 있다. Pinky의 회전 속도는 그보다 훨씬 느리다. 자세가 2 s 끊긴 뒤 이어지면 그 틈의 회전은 한 번의 차이로 센다. 그 틈이 2 s를 넘으면 이미 `tether_pose_stale`로 선다.
- 자세 오차(D-395 위치 추정, 미끄러짐)만큼 거리가 틀린다. 0.15 m 여유와 도구 여유 0.3 m가 이것을 덮는다고 본다. 장치에서 확인한다(결정 8).

### Alternatives considered

- **Fleet가 되돌아가기를 지시한다.** 로봇의 odom 길이 Fleet에 없고 CORE에 그 API가 없다. 만들면 Fleet가 구동자가 된다. 기각(결정 3).
- **line-follow OFF + 항법 취소로 세운다(trip 정지와 같게).** 수동 조종을 세우지 못한다. D-512 도구는 MANUAL로 되돌아가기를 한다. 기각.
- **Fleet와 도구를 같은 한도로 둔다.** 같은 순간에 둘 다 트립하면 Fleet E-Stop이 도구의 되돌아가기를 막는다. 기각(결정 5).
- **자세가 없으면 아무것도 하지 않는다.** 케이블이 걸린 채 연결이 끊긴 로봇을 놓친다. D-430 §4 fail-closed와 맞지 않는다. 기각.
- **전체 정지(`estop_all`)를 쓴다.** 케이블과 무관한 로봇까지 선다. 기각.

### 다음 단계

1. 독립 Safety-Review(D-430 §5), 그 뒤 착지.
2. ROS-SIM: Gazebo 두 대에서 trip 주행 중 트립 → E-Stop 래치·trip `tether_trip` 종료 확인.
3. DEVICE: 케이블 주행 첫 실행에서 줄인 반경으로 트립 위치와 정지 위치 기록.
4. 2단계: 지속 감사 행, odom 자세 로봇(D-472 트랙 거리 + odom yaw 회전), 필요하면 테더 POST에 `max_turn_deg`.

### 관계

- D-512 개정 1 5항(Fleet 후속)을 이 ADR이 맡는다. D-512의 도구 감시·되돌아가기는 바꾸지 않는다.
- D-430 §4·§5, D-480 층, D-517 trip(`TripRunner.cancel_robot` 사용, trip 코드는 바꾸지 않음), D-395 위치 추정, D-12(Fleet는 구동자가 아니다).
