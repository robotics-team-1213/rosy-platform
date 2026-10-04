## D-453 양보 한 구간은 기존 막힘 답 YIELD 로 보내고, CORE 는 돌려 확인한 뒤 앞으로만 간다

**Status:** Accepted (2026-10-04, 사용자 결정 "구현해 줄래". D-451 §5 가 다음으로 미룬 주문과 막힘 답의 대응이다. 합류, D-442, DEVICE, ROS-SIM 은 이 결정에 없다.)

## 배경

- D-451 은 누가 비키는지와 어느 방인지를 Fleet `room_hold` 만 고른다. 그 주문은 아직 바퀴로 나가지 않았다.
- 빠지는 길은 문까지 약 0.34 m, 문에서 방까지 0.27–0.32 m 다. `BACK_AND_RETRY` 는 짧은 직선 후진이다. 기본 0.08 m, 상한 0.20 m, 속도 상한 0.05 m/s 다(D-407). 그 상한을 올리지 않는다.
- `navigation_goal`, 관제의 칸 보내기, Nav2, `LocalizationMission` 은 이 실행기가 아니다. 차선 추종은 오도메트리와 지도 자세가 없다. 새 하향 통로를 만들지 않는다(D-438).
- 운용자가 고르는 Fleet 경로는 `WAIT`·`RESUME`·`BACK_AND_RETRY`·`MANUAL`·`ABORT` 다섯 단어다. 그 경로는 추가 필드를 거절한다.

## 결정

1. **한 답은 한 구간이다.** Fleet 판단기가 온라인 자세를 260919 차선에 올리고 `decide("room_hold")` 를 부른다. `SIDESTEP` 와 `RETREAT` 는 기존 `POST /api/v1/line-follow/stuck/decision` 의 `YIELD` 하나로 보낸다. 몸에는 `yield_turn_rad` 와 `yield_m` 이 같이 있다. 거리는 0.05 m 부터 2.0 m 까지다. 더 긴 기하는 2.0 m 에서 자르고, 그 길이만으로 거절하지 않는다. 속도는 `min(linear_ceiling, recovery_back_speed)` 이고 0.05 m/s 를 넘지 않는다. 회전은 0.3 rad/s 다. 절대값이 약 0.15 rad 이하면 회전을 건너뛰고 바로 기어 간다. 판단기는 로봇 클라이언트로 이 답을 직접 보낸다. 운용자 경로에는 `YIELD` 를 넣지 않는다.

2. **CORE 는 확인한 뒤 앞으로만 간다.** 바퀴는 차선 추종이 `CommandManager` 로만 낸다(D-2). 도는 동안에는 회전 반경 밖 여유 `turn_m` 이 약 0.02 m 이상이어야 한다. 앞에 동료가 있다는 이유만으로 시작을 거절하지 않는다. 앞으로 기어 가는 동안에만 앞 정지를 본다. 거절 사유는 `yield_unset`, `yield_distance`, `yield_turn`, `turn_blocked`, `calibration_active`, `body_geometry_unset`, `no_scan`, `scan_stale`, `linear_limit_zero` 다. 보정 lease 와 E-Stop 은 `RESUME`·`BACK_AND_RETRY` 와 같다. `stuck_resolver` 는 `YIELD` 를 보낼 수 있다. `MANUAL` 은 여전히 403 이다. 구간 필드가 없거나 다른 결정에 붙으면 400 이다.

3. **끝난 구간은 선으로 돌아가지 않는다.** 위상은 `TURNING`, `CRAWLING`, `YIELDED` 다. 시간은 거리/속도로 찬다. 오도메트리를 보지 않는다. 구간이 끝나면 `YIELDED` 에서 속도 0 이고, 원인이 사라져도 차선 추종을 재개하지 않는다. 같은 막힘의 다음 `YIELD` 가 다음 구간이다. 같은 구간을 다시 시작하지 않는다. `YIELDED` 인데 `WAIT` 가 오면 그 위상을 유지한다. 도는 중이나 기어 가다 거절하면 `WAITING_CONSOLE` 로 선다. 사람에게 올리는 60 s 는 그대로다. 긴 후퇴가 그 시간을 넘기면 기존처럼 올린다.

4. **아직 선 위에서 막혀 있으면 앞으로 보내지 않는다.** 막힌 로봇과 다른 로봇이 선에 올라 있고, 주문이 `PROCEED`·`WAIT`·`HOLD` 이면 답은 `WAIT`(규칙 `meet`)다. `RESUME` 으로 상대를 향해 나가지 않는다. 고리에서 원인이 사라지면 기존의 `WAITING_CONSOLE` 이 풀린다. 간격은 로봇 앞 정지가 유지한다. `ESCALATE` 는 사람으로 올리고 양보 계획을 버린다.

5. **핀과 정책 방향은 판단기에 있다.** 양보자가 문을 향해 돌면 기하 헤딩이 뒤집혀, 신선한 판단은 마주침을 못 본다. 판단기는 결정을 내린 때의 정책 방향을, 그 로봇이 그 선에 있는 동안 장면에 덮어쓴다. 방에 들어가면 계획과 핀을 버린다. 신선한 주문이 더 이상 `SIDESTEP`·`RETREAT` 가 아니어도, 계획이 그 선에 살아 있으면 저장한 주문을 이어 간다. 만남으로 들어가는 것은 원인이 `obstacle_ahead` 이고 동료가 앞 0.30 m, 옆 0.15 m 안에 있을 때다. 아니면 기존 R1·R2·R3 다. `YIELDED` 인 다음 구간은 동료가 앞에 있지 않아도 판단한다.

6. **투영.** 선에서 0.08 m 보다 멀면 그 선 위가 아니다. `(0, 0)` 은 고리에서 약 0.084 m 라 올라가지 않고, 그 자리는 기존 R1 이다. 방 대기 자리에서 0.12 m 안이면 그 방이다. 문 s 는 차선 폴리라인이 정한다. 동쪽 약 0.860 m, 서쪽 약 1.435 m. 고리 한가운데는 대기 자리가 아니다. 빈 방 안을 A* 로 자르지 않는다.

7. **합류는 나중이다.** 방 안 로봇은 `WAIT`(`in_room`)다. 선으로 되돌리는 일은 부르는 쪽이 나중에 한다. Fleet 에 닿지 않으면 로봇은 짧게 물러난 뒤 그 자리에 서고, 방 선택을 로봇 안에서 돌리지 않는다(D-451). D-442 Motion Intent 바인딩은 범위 밖이다.

## 결과

- 양보 주문 한 구간이 기존 막힘 답으로 나가고, CORE 가 거부할 수 있다. 운용자 다섯 단어와 추가 필드 거절은 유지된다.
- 수용은 호스트 시험까지다. 바퀴가 실차에서 움직였다는 증거는 없다.

## 검증

- 호스트: `operations/fleet/test/test_meet_place.py`, `test_stuck_resolver.py`, `test_transport.py`, `test_meet_algorithms.py`, `middleware/core/services/test/test_line_stuck_recovery.py`, `middleware/core/gateway/test/test_line_follow_stuck_api.py`.
- 동쪽 가까운 마주침은 `YIELD`, 선 밖 동료는 R1, 양방향 셋은 `ESCALATE`, 같은 구간은 다시 보내지 않고 문 앞의 다음 구간은 보낸다. 회전 뒤 기어감, 앞 정지에서 중단, 원인이 사라져도 `YIELDED` 유지.
- DEVICE·ROS-SIM·실차 증거는 없다.

## 잇는 결정

D-2, D-12, D-93, D-407, D-438, D-451. D-442 는 범위 밖.

### 통합 시 응답 유실과 중복 요청 경계

양의 YIELD를 CORE가 적용했는지 불명확한 응답 유실·비정상 응답·요청 취소는
같은 답변의 재전송 허가가 아니다. Fleet은 기존 answered 상태를 유지하고
운용자 확인으로 넘긴다. 활성 TURNING/CRAWLING 중 YIELD 요청은 기존
STUCK_DECISION_REFUSED로 거절하며 현재 phase·기한·속도를 다시 시작하지 않는다.
YIELDED 후 별도 다음 구간의 기존 판단 경로는 유지한다. 이 보완은 실제 양보
구동이나 DEVICE/FIELD 수락을 수행했다는 근거가 아니다.
