## D-1051 Pinky 미세 재정차 `motion/repark`와 Fleet 실행 경로

**Status:** Proposed (2026-11-19, 사용자 "앞으로도 구역에 대한 부분도 정확하게 안착 가능하게 도킹하는 것처럼 확인해서 개선해줄래" · 패널 decision.md B 조각). SOURCE 변경과 호스트 테스트만 한다. 실로봇 이동·현장 수용은 이 기록이 하지 않는다.

잇는 결정: [D-603](D-603-core-rotate-to-heading-trip-start-align.md)(`rotate_to`) · [D-395](D-395-fleet-assisted-localization.md) P2-7(`nudge` 미션) · [D-424](D-424-one-robot-body-for-every-near-check.md)(RobotBody 여유) · [D-541](D-541-core-fleet-trip-lease.md) · [D-550](D-550-fleet-robot-communication-contract.md) 규칙 M · [D-430](D-430-safety-as-a-separate-concern.md)(안전 태그). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- 2026-11-19 S3 정차가 arm_s 도달 밖이었다(상자 222 mm > IK park 200 mm). robot-3b 실측: 제자리 30° 회전 → 7 cm 전진 → 되돌림 → 6 cm 후진이 옆 38 mm·앞뒤 2 mm·0.4°를 옮겼다.
- 마지막 몇 cm를 닫는 단계가 없다(Nav2 허용 0.10·Fleet 0.15·trip 0.05).
- 셀(robot-16, feat/cell-reach-repark)은 도달 거부를 `reach_fix`·`state.repark_requests`로 Fleet에 올린다. 이 결정은 그 요청을 로봇에서 실행하는 쪽이다.

### Decision

1. **CORE `POST/GET/DELETE /api/v1/motion/repark`** `{forward_m, left_m, operator_name}`(몸체 기준, 앞·왼 +). 앞뒤 ≤ 0.10 m, 옆 ≤ 0.06 m. 새 바퀴 경로를 만들지 않는다: `core_features/localization/repark.py`가 기존 미션을 이어 붙인다 — `rotate_to`(θ = max(30°, asin(옆/0.09)), 옆 방향 부호) → `nudge_forward` d(= 옆/sinθ ≤ 0.09) → `rotate_to` 시작 odom yaw로 되돌림 → 남은 앞뒤 nudge(|·| ≥ 5 mm일 때). 모든 단계가 `LocalizationMission` 한 번의 run이라 D-424 몸체·LiDAR 여유, odom·LiDAR 신선도, E-Stop, 모드 변화 취소, nav 슬롯 → `select_output`(Safety clip·D-400)을 그대로 받는다.
2. **속도.** 선속도 0.023 m/s(`start(..., speed=)`: 설정 `nudge_linear`를 넘지 못하고 낮추기만), 각속도 0.09 rad/s 이하(`rotate_to max_rate_dps` 5.0; 바퀴 데드밴드 바닥보다 낮으면 `max_rate`가 이긴다). 한도에서 바퀴가 안 돌면 단계가 timeout으로 끝나고 정지한다.
3. **닫힘.** 각 단계는 odom 폐루프다. 단계가 `done`이 아니거나 전체 45 s를 넘으면 그 자리에서 멈추고 `aborted`(사유)로 끝난다. `aborted`이면 방향이 θ만큼 어긋나 있을 수 있다 — 되돌리려 더 움직이지 않는다(막혔을 수 있다). 결과의 `moved_robot_dxdy_m`은 시작·끝 odom으로 잰 값이고, 요청과 축마다 15 mm 넘게 다르면(LiDAR가 nudge를 줄인 경우) `done`이 아니라 `aborted`(`short_of_request`)다. 바퀴가 실제로 가는 길이는 옆 6 cm 요청에서 최대 약 0.19 m(d 0.09 + 남은 앞뒤 0.10)이고, 단계마다 nudge 여유 검사를 받는다. 실행기는 단계 사이에 남의 미션이 바퀴를 가져가면 `segment_lost`로 끝내고 그 미션을 건드리지 않는다.
4. **누가.** `rotate_to`와 같은 admission(trip lease 주인, 없으면 이름 있는 operator; 보정 lease·매핑·readiness HOLD 거절). `DELETE`는 멈춤이라 열려 있다. 사건 `motion.repark`.
5. **Fleet 실행.** `fleet/server/repark_exec.py`의 `ReparkExecutor`가 REQUESTED 요청 하나를 맡는다: `need_site_dxdy_m`을 로봇의 지도 yaw로 몸체 (앞, 왼)로 바꿔 `POST`, `GET`을 폴링해 `done`이면 DONE, 그 밖이면 FAILED(사유)로 `close`한다. 사이트 변위가 없음(`no_site_delta`)·자세 없음·CORE 거절·시간 초과는 FAILED로 닫고 Fleet이 다시 시도하지 않는다(셀 작업이 사람에게 간다; 재큐 2회는 robot-16 쪽 규칙). Fleet은 twist를 내지 않는다. 요청 저장소와 `close`는 robot-16의 `pipeline_repark`이고, 두 곳을 잇는 한 줄은 그 브랜치가 main에 들어온 뒤 붙인다.

### Safety-Review

새 운동 경로다(D-430 5항): Fleet 요청으로 CORE가 정차 로봇을 몇 cm 옮긴다(`repark.py` 안전 태그, 앵커 `plan_repark`).

- **한정.** 옆 6 cm·앞뒤 10 cm·단계별 timeout·전체 45 s. Fleet이 죽어도 CORE의 단계 timeout과 전체 timeout이 끝낸다.
- **바퀴까지의 길.** 기존 `rotate_to`·`nudge` 미션 그대로: `select_output`, E-Stop, Safety clip, 300 ms watchdog은 바뀌지 않는다. CORE 단일 `/cmd_vel`(D-2). 가드 한계를 약화하지 않았고 `nudge` 속도는 낮추기만 가능하다.
- **여유.** 단계마다 시작 전·진행 중 몸체 LiDAR 검사가 다시 돈다. 뒤로 가는 단계는 뒤쪽 섹터(후방 무반사 거절).
- **남는 위험.** (a) 한도 속도에서 바퀴 데드밴드로 안 돌 수 있다(timeout 정지). (b) 중간 중단 시 방향이 어긋난 채 정차한다(차선 점유 가능, 사람이 치움). (c) odom 과회전 6–11 %는 되돌림이 시작 yaw에 odom으로 닫아 상쇄하지만 실제 방향은 천장 카메라로만 확인된다. (d) 사이트→몸체 변환은 지도 yaw에 기댄다.
- 독립 리뷰: 커밋 전 읽기 전용 검토(아래 Review).

### Review

2026-11-19 독립 읽기 전용 검토(별도 Claude 에이전트, 쓰기·checkout 금지) 2라운드. 1라운드 CHANGES REQUESTED(runner 락 없음·남의 미션 구별 없음·LiDAR가 줄인 nudge를 done으로 처리·Fleet busy 키) → 수정 → 2라운드 APPROVE. 호스트 pytest 406 통과(원격). 실로봇 이동은 하지 않았다.
