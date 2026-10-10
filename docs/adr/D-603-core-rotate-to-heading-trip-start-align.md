## D-603 CORE 제자리 회전 미션 `rotate_to`와 Fleet trip 출발 자동 정렬

**Status:** Proposed (2026-10-10, 사용자 결정 "CORE rotate to heading 미션을 만들어 Fleet이 trip 출발에서 로봇을 맞춘다"). SOURCE 변경과 호스트 테스트만 한다. 실로봇 회전, 이미지 배포, 현장 수용은 이 기록이 하지 않는다. Fleet 쪽은 `fleet.trip.auto_align`(기본 false)이고, 현장 수용 뒤에 켠다.

잇는 결정: [D-601](D-601-fleet-trip-start-turns-camera-line-on.md) 5항(권고: CORE `rotate_to`) · [D-395](D-395-fleet-assisted-localization.md) P2-7(위치 미션 `rotate_in_place`) · [D-424](D-424-one-robot-body-for-every-near-check.md)(RobotBody 회전 반경) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md) · [D-541](D-541-core-fleet-trip-lease.md)(trip lease) · [D-550](D-550-fleet-robot-communication-contract.md) 규칙 M(한정된 움직임) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md) · [D-430](D-430-safety-as-a-separate-concern.md)(안전 태그). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- D-601은 출발 자세가 첫 차로 방향과 20° 넘게 다르면 `TRIP_START_HEADING_MISMATCH`로 거절한다. 2026-10-10 현장에서 반대로 주차된 로봇은 사람이 돌려 세웠다.
- CORE에는 목표 각도로 도는 명령이 없다. 위치 미션 `rotate_in_place`는 `LOCALIZED`가 아닐 때 찾기용으로 한 바퀴까지 돈다.
- 로봇은 motor 모드(Nav2 없음)다. `/cmd_vel`은 CORE 하나가 낸다(D-2). 바퀴에 가는 명령은 `CommandManager.select_output`이 E-Stop, readiness HOLD, Safety clip, D-400 정책을 거쳐 고른다.
- 실로봇 odom은 회전에서 6–11 % 더 돈다고 읽는다(D-598 증거). odom만으로 닫으면 실제 방향이 그만큼 어긋난다.

### Decision

1. **CORE `POST /api/v1/motion/rotate_to`.** 본문 `{delta_deg | yaw_odom, tol_deg = 5 (1–20), max_rate_dps = 20 (≤ 30), timeout_s = 10 (≤ 15), operator_name}`. `|delta_deg|` ≤ 180. 위치 미션의 새 종류 `rotate_to`로 돈다(`localization/mission.py`가 odom·LiDAR 입력, 20 Hz tick, 바퀴 소유, 모드 변화 취소를 이미 갖고 있다). `POST /localization/mission`의 `kind`로는 받지 않는다.
   - 회전 법칙과 한도는 `core_features/localization/rotate_to.py` 하나에 있고 안전 태그다(`safety_modules`, 앵커 `rotate_goal`·`turn_rate`). 비례 감속(`rotate_to_gain` 1.5 /s), 바닥 `rotate_to_min_angular` 0.15 rad/s(바퀴 데드밴드, 보정 손잡이), 천장 `max_rate_dps`. 시작 뒤 odom yaw 변화의 부호 있는 합으로 남은 각을 잰다(180°도 방향이 정해진다).
   - 끝: `done`(남은 각 ≤ `tol_deg`), `timeout`, `overturn`(odom 회전의 절댓값 합 > 요청 + `rotate_to_overturn_deg` 30°: odom 부호가 틀리거나 진동할 때), `obstacle`(회전 중 `rotate_in_place`와 같은 RobotBody 검사: 반경 + `rotate_stop_margin_m` 안 반사는 즉시, 증거 공백은 8 tick 뒤), `obstacle_sensor_stale`, `odometry_stale`, `estop`, `cancelled`(NAVIGATION을 떠남, `DELETE`). 끝나면 바퀴 명령을 지우고 IDLE로 간다.
   - `LOCALIZED`는 거절 사유도 끝 사유도 아니다(Fleet은 LOCALIZED 로봇을 맞춘다). 찾기 미션만 `LOCALIZED`에서 끝난다(`mission.localized()`).
2. **누가 부르나.** Operator 역할이고, D-541 trip lease가 살아 있으면 그 주인만(`require_calibration_owner`, 다른 토큰 409 `TRIP_LEASED`). lease가 없으면 `operator_name`이 있어야 한다(403 `OPERATOR_NAME_REQUIRED`). 요청은 사건 `motion.rotate_to`에 이름과 lease 주인 여부를 남긴다. `DELETE`는 멈춤이라 lease와 상관없이 operator 누구나 부른다.
3. **언제 거절하나(움직이기 전).** 보정 lease, 매핑, readiness HOLD(503), E-Stop(`EMERGENCY_ACTIVE`), 다른 미션·IDLE 아닌 모드(MANUAL·NAVIGATION·DOCKING)·line-follow·도킹·swarm·Nav2 목표(`MOTION_BUSY`), 0.5 s 안의 odom 없음(`ODOMETRY_STALE`), 회전 여유 부족(`ROTATE_CLEARANCE {nearest_m, need_m}`; 몸체를 알면 base_footprint 기준 회전 반경 + `rotate_margin_m`, 반사 없음·섹터 공백·몸체 밖으로 나가는 무반사 빔도 거절; 몸체를 모르면 LiDAR 기준 `rotate_clearance_m`). `GET`은 `{state: running|done|aborted|idle, reason, err_deg, final_err_deg}`. 능력 최상위 `motion {rotate_to: true}`.
4. **Fleet 출발 자동 정렬(`fleet.trip.auto_align`, 기본 false).** 출발 검사가 `TRIP_START_HEADING_MISMATCH`이고 `heading_err_deg`가 있으면(차로 밖은 먼저 `TRIP_START_OFF_LANE`로 거절된다) Fleet은 출발 operator 이름으로 `rotate_to {delta_deg: -heading_err_deg}`를 보낸다. `GET`을 `period_s`마다 최대 12 s 보고, 그때도 `running`이면 `DELETE`한다. 끝난 뒤 그 끝보다 새 천장 카메라 sighting 앵커를 가진 지도 자세를 최대 3 s 기다리고, 출발 검사를 다시 한다. 회전은 출발 한 번에 최대 두 번이다(두 번째가 odom 과회전을 고친다). 그 뒤 D-601 순서(lease → trip 열림 → `CAMERA_LINE`)를 그대로 잇는다.
   - 거절·중단은 출발 거절이다: CORE 거절 422 `TRIP_ALIGN_REFUSED {error, delta_deg, core}`, 중단·끝나지 않음 422 `TRIP_ALIGN_ABORTED {delta_deg, reason, final_err_deg}`, 새 sighting 없음 422 `TRIP_POSE_UNTRUSTED {after_align: true}`, 두 번 뒤에도 어긋남은 같은 `TRIP_START_HEADING_MISMATCH`.
   - 출발한 trip은 `detail.aligned [{delta_deg, final_err_deg}]`를 남긴다. 설정이 켜져 있으면 `/trip`의 `start_check`에 `auto_align: true`가 붙고 콘솔은 그 어긋남으로 출발 버튼을 끄지 않는다("방향 반대(178°) · 출발 때 자동 정렬").
   - 회전은 로봇 잠금 안, trip lease를 열기 전이다. 그래서 CORE에는 lease가 없고 `operator_name`(출발 operator)으로 받는다.

### Safety-Review

이 기록은 **새 운동 경로**를 만든다: Fleet 요청으로 CORE가 제자리에서 돈다(D-430 5항 대상, `rotate_to.py` 안전 태그).

- **한정(D-550 M).** 한 번에 최대 180°, 30°/s, 15 s. odom 회전 합이 요청 + 30°를 넘으면 멈춘다. Fleet은 출발 한 번에 두 번까지만 부른다. Fleet이 죽어도 CORE의 timeout이 끝낸다.
- **바퀴까지의 길.** nav 슬롯 → `select_output`: E-Stop, readiness HOLD, Safety clip(각속도 한도), D-400 정책을 그대로 거친다. 300 ms watchdog과 E-Stop은 바뀌지 않는다. CORE 단일 `/cmd_vel`(D-2).
- **여유.** 시작 전 RobotBody 회전 반경 + 0.03 m(현장 측정 반경 약 0.093 m)와 LiDAR 증거(섹터·무반사 빔)를 본다. 회전 중 반경 + 0.01 m 안 반사는 즉시 멈춘다(`rotate_in_place`와 같은 코드, D-424 리뷰 H1).
- **누가.** lease가 있으면 주인만. lease 밖에서는 이름 있는 operator만. 멈춤(`DELETE`, E-Stop, `/mode` IDLE)은 언제나 열려 있다.
- **넓힌 것.** `LOCALIZED` 로봇의 제자리 회전 하나. 지금까지 위치 미션은 `LOCALIZED`가 아닐 때만 돌았다.
- **좁힌 것·그대로인 것.** Fleet 기본값은 꺼짐이라 설정을 켜기 전 Fleet 동작은 D-601과 같다. 차선 주행, 교차로, 통행권은 바뀌지 않는다.
- **남는 위험.** odom 과회전은 Fleet의 두 번째 회전과 다시 검사로 줄인다. 천장 카메라가 로봇을 못 보면 출발하지 않는다. 회전 중 사람 발처럼 LiDAR 평면 아래 물체는 보지 못한다(이미 `rotate_in_place`와 같다). 현장 사람이 늘 있다는 운용 규칙에 기댄다.
- 독립 리뷰: 아래 Review 절.

### Alternatives

| 대안 | 판단 |
|---|---|
| Fleet이 `rotate_in_place`를 시작하고 천장 카메라를 보며 끊는다 | 기각. 끊는 시각이 네트워크·카메라 지연에 달리고, 찾기 미션은 LOCALIZED에서 시작하지 못한다 |
| CORE가 지도 yaw를 받아 스스로 돈다 | 기각. CORE에는 지도 프레임 자세가 없다(motor 모드). Fleet이 지도 오차를 odom 각으로 바꾼다 |
| 새 독립 모듈·새 브리지 tick | 기각. 위치 미션이 입력·tick·바퀴 소유·취소를 이미 갖는다. 회전 법칙만 안전 태그 모듈로 뺐다 |
| 출발 전 운영자 확인 대화 | 보류. 설정 `auto_align`을 켜는 것이 사이트 결정이고, 출발 버튼이 이미 사람 확인이다. 현장 수용 뒤 다시 본다 |

### Validation

- `middleware/core/services/test/test_rotate_to.py`: 한도 검증, 회전 법칙(감속·바닥·되돌림), 허용 오차 안 `done`과 IDLE, odom 과회전이 실제 오차로 남음, timeout·overturn, 움직이기 전 거절(여유·바쁨·E-Stop·odom), 회전 중 멈춤(E-Stop·장애물·모드·LiDAR 끊김), LOCALIZED는 찾기 미션만 끝냄.
- `middleware/core/gateway/test/test_motion_rotate_to_api.py`: 이름 있는 operator의 회전이 `select_output`으로 나감, `DELETE`, 누가 부르나(이름 없음 403, viewer 403, lease 주인 아님 409, 주인은 이름 없이), 400·`ROTATE_CLEARANCE`·`EMERGENCY_ACTIVE`, `MOTION_BUSY`, 능력 플래그. `test_trip_lease.py` FENCED 표에 경로 추가.
- `operations/fleet/test/test_trip_align_d603.py`: 꺼짐 기본값, 반대로 선 로봇 회전 후 출발, 과회전 두 번째 회전, 두 번 뒤 거절, CORE 거절·중단·끝나지 않음, 새 sighting 없음, 차로 밖은 돌리지 않음, 계획 `start_check.auto_align`. `test_transport.py`, `test/web/trip-path.test.mjs`.
- 호스트 테스트는 장치·현장 수용을 대신하지 않는다. 현장 수용 절차는 Consequences.

### Review

(독립 리뷰 결과를 여기에 적는다.)

### Consequences

- API Reference v1.194: 로봇 `motion/rotate_to` 세 경로, 오류 코드, 사건, 능력, Fleet `/start` 행과 변경 이력.
- CORE 설정 `localization_mission.rotate_to_gain`·`rotate_to_min_angular`·`rotate_to_overturn_deg`, Fleet 설정 `fleet.trip.auto_align`.
- 현장 수용(이 기록 밖, 사람이 옆에 있을 때): (1) 이미지에 이 CORE가 들어간 로봇에서 `GET /api/v1/system/capabilities`의 `motion.rotate_to: true`. (2) 빈 바닥에서 `POST /motion/rotate_to {delta_deg: 90, operator_name}`를 ±90·180으로 각 3회, 천장 카메라 yaw와 `final_err_deg`를 비교해 실제 오차를 기록하고 `rotate_to_min_angular`(멈춤 없이 마지막 몇 도를 도는지)를 맞춘다. (3) 벽에서 0.08 m에 세워 `ROTATE_CLEARANCE`, 돌던 중 손을 넣어 `obstacle`, E-Stop으로 `estop`. (4) 사이트 설정 `fleet.trip.auto_align: true`로 반대로 선 로봇의 trip 출발: 회전 → 다시 검사 → 차선 주행 시작과 `detail.aligned`. (5) 결과로 Status를 Accepted로 올리고 기본값을 정한다.
