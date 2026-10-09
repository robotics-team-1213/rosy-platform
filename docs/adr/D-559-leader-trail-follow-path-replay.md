## D-559 리더 자취 따라가기(path replay) — 팔로워 CORE가 리더가 실제로 지나간 길을 그대로 다시 달린다

**Status:** Proposed (2026-10-09, 사용자 요청 "관제에서 리더를 정하면 팔로워가 리더가 실제로 간 길을 정확히 따라간다". 구현은 feat/swarm-trail-follow, 호스트 테스트와 모델 PC Gazebo SIM 증거만. DEVICE·현장 수용 없음)

잇는 결정: [D-20](D-20-swarm-fleet.md)(추종 계산은 로봇, Fleet은 지정·릴레이) · [D-31](D-31-fleet.md) · [D-60](D-60-navigation-swarm.md)(추종은 Navigation moving goal, v2 pure-pursuit 훅 예약) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 장애물 정지) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md) · [D-517](D-517-multi-robot-lane-traffic.md)(M3 차로 대열) · [D-550](D-550-fleet-robot-communication-contract.md)(규칙 M) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(trip 로봇 움직임 거절)

### Context

1. 지금 군집 추종(D-20 `offset`)은 리더의 **지금** pose 뒤 `distance`, 옆 `lateral` 지점을 Nav2 moving goal로 2 Hz 보낸다. 리더가 모서리를 돌면 목표점이 모서리 안쪽으로 옮겨 가고, Nav2는 그 점까지 새 경로를 짠다. 팔로워는 리더가 지난 길이 아니라 지름길로 간다. 좁은 통로와 차로 위에서는 이것이 벽이나 차로 밖이다.
2. 사용자 요구는 "리더가 실제로 간 길을 정확히" 따라가는 것이다. 차선 추종(카메라)도, D-20 오프셋도 아니다. 팔로워가 같은 바닥 흔적을 다시 밟는 경로 재생이다.
3. D-60은 "v2 로컬 추종 컨트롤러(pure-pursuit) 소스"를 CMD-001 `swarm` 소스(NAVIGATION 등급)로 예약해 두었다(`command/arbitration.py`). 바퀴로 가는 길은 이미 있다: 차선 추종이 20 Hz로 CommandManager NAVIGATION 슬롯에 twist를 넣고, SAF-004 클리핑과 D-400 정책을 지난다.
4. 리더 pose 스트림(SWM-003, ≥10 Hz)은 map 프레임 좌표를 보내지만, 리더의 map TF가 2 s 넘게 끊기면 보고 pose가 odom으로 떨어진다(`ros_bridge.py` `odom_owns_pose`). 그 표본은 맵 위 장소가 아니다. 스트림에는 그 구분이 없었다.

### Decision

1. **추종 모드 둘.** `POST /api/v1/swarm/follow`에 `mode: offset|trail`(기본 `offset`, 지금 동작 그대로)을 더한다. `trail`에서 `distance`는 자취 위 **경로 거리**(gap)이고 `lateral`은 0이어야 한다(아니면 400). 새 필드 `gap`을 만들지 않고 `distance`를 쓴다 — 두 모드 모두 "리더 뒤 얼마"이고, Fleet 슬롯 계산(`slot × spacing`)이 그대로 맞는다.
2. **자취는 팔로워 CORE가 만든다**(D-20 분담 유지). `core_features/swarm/trail.py`(ROS 무의존):
   - 리더 표본을 직전 점에서 0.03 m 이상 떨어질 때 쌓고 누적 경로 거리 s를 단다. 리더 진행 s_L = 마지막 점의 s.
   - 리더가 뒤로 가면(이동이 리더 heading 반대) 점을 쌓지 않는다. s_L이 늘지 않으니 간격이 줄어 팔로워가 선다. 판정은 자취 접선이 아니라 리더 heading으로 한다 — 제자리 90° 넘게 돈 리더의 다음 이동이 자취 접선 뒤로 읽혀 영영 쌓이지 않는 것을 막는다.
   - 첫 점은 팔로워 자신, 다음은 리더다. 그 거리가 1.5 m를 넘으면 follow를 끝낸다(`swarm.aborted` `trail_join_too_far`). 표본 사이에 0.3 m + SAF-004 `max_linear` × 경과 시간(최대 1.5 m)보다 멀리 건너뛴 리더(재지역화, 긴 스트림 공백)도 직선으로 잇지 않고 `trail_lost`로 선다. 10 Hz 스트림에서 0.3 m는 주행이 아니다. 그보다 짧은 공백 뒤의 이동은 직선으로 잇는다.
   - 팔로워 진행 s_F는 자취 위 투영이고, 지금 s_F에서 0.5 m 앞까지만 찾는다(줄지 않음). 자취가 스스로 겹치는 고리에서 뒤 통과 지점으로 건너뛰지 않는다.
   - 자취에서 0.30 m 넘게 벗어나면 `trail_lost` HOLD(다시 follow할 때까지 유지).
   - 속도 v = clamp(2.0·(s_L − s_F − gap), 0, max_speed), 가속 0.5 m/s² 상한, 1 cm/s 아래는 0. 리더가 서면 팔로워는 gap에서 선다.
   - 조향은 s_F + 0.20 m(≤ s_L) 점으로의 pure pursuit, 각속도는 SAF-004 `max_angular`로 자르고 그때 속도를 같이 줄여 곡률을 지킨다.
   - 팔로워 1 m 뒤의 점은 버리고 점은 2000개까지.
3. **바퀴로 가는 길은 차선 추종과 같다.** SwarmManager `trail_tick`이 20 Hz 차선 타이머에 실려 `swarm` 소스 twist를 CommandManager NAVIGATION 슬롯에 넣는다 — SAF-004 클리핑, 추종 `max_speed` 세션 상한, D-400 평가를 지난다. 그 전에 D-422 판정을 그 twist로 한 번 더 한다: 차선 추종 관리자의 `obstacle_gap`이 URDF 몸체를 그 호로 쓸어 첫 접촉까지의 거리와 정지·재개 거리를 돌려주고(path 모드, 몸체 기하가 있을 때), 섹터 모드면 정면 거리다. 막히면 `obstacle`로 서고, 멈춘 판정의 재개 거리를 넘어야 다시 간다(재출발 twist는 느려 자기 재개 거리가 더 작다). 신선한 LiDAR가 없으면 `obstacle_sensor_stale`로 선다. trail이 켜져 있는 동안 Nav2 twist는 버린다(차선 추종과 같은 자리, `docking_mode.route_nav_cmd_vel`). Nav2 moving goal은 내지 않는다. NAVIGATION moving 세션은 그대로 연다 — MANUAL 전환, `navigation/cancel`, 차선 추종 시작이 그 세션을 닫으면 trail도 끝난다(D-60 그대로).
4. **멈춤 규칙은 offset과 같다.** 스트림 `stream_timeout_ms` 단절은 HOLD(세션 유지, 0 twist, 표본이 오면 이어 간다), 다른 `map_id`는 HOLD, E-Stop·도킹은 follow를 끝낸다. 더해 리더 표본의 `frame: odom`은 자취에 넣지 않고 `reference_frame_odom`으로 서며(map 표본이 오면 이어 간다), 팔로워 자신의 pose가 odom이면 `own_pose_not_map`, 0.5 s 넘게 갱신되지 않았으면 `own_pose_stale`로 선다. offset↔trail로 follow를 다시 걸면 다른 모드의 남은 목표·twist를 거둔다. 리더 스트림 §7.8 payload에 `frame: map|odom`을 더한다(추가, 없으면 확인하지 않음).
5. **Fleet은 역할과 릴레이만.** 대형 `TRAIL` = COLUMN 슬롯, 팔로워마다 `mode: trail`, `distance = 슬롯 × spacing`. 모든 팔로워가 리더 스트림만 받는다(사슬 아님). 옛 CORE는 모르는 `mode`를 버리고 offset으로 따라가므로, follow 답의 `mode`가 `trail`이 아니면 그 로봇을 풀고 `TRAIL_NOT_SUPPORTED`로 시작을 거절한다. 관제 대형 설정에 선택지 하나를 더한다.
6. **차로 대열(D-517 M3)과 섞지 않는다.** M3 대열은 두 로봇이 각자 계획 경로를 차선 추종으로 달리고 Fleet 통행권으로 간격을 지킨다. trail은 경로 재생이고 v1에서는 차로 trip 안에서 쓰지 않는다: trip이 열린 로봇의 `formation/start`는 이미 `TRIP_ROBOT_BUSY`(D-494 5)이고, trail 팔로워가 차선 추종을 시작하면 moving 세션이 닫혀 trail이 끝난다.
7. **규칙 M(D-550).** trail 움직임의 한도는 로봇이 보는 링크 신호인 참조 스트림 `stream_timeout_ms`(기본 1 s)다. offset과 같다.
8. **API v1.167**(추가): follow `mode`, state `mode`·`trail {leader_s, progress, hold_reason}`, §7.8 `frame`, `swarm.hold` trail 사유, `swarm.aborted` `trail_join_too_far`, Fleet `formation: TRAIL`.

### Consequences

- 팔로워가 모서리를 가로지르지 않는다. 남는 오차는 두 로봇 위치 추정의 어긋남, 앞보기 길이만큼의 꼭짓점 깎임(제자리 회전 모서리), 가감속 지연이다.
- trail 중에는 Nav2 장애물 회피가 없다. 장애물 판정은 D-422 몸체 정지 하나다 — 피하지 않고 선다. 그래서 리더가 지난 길이 지금도 비어 있다는 것이 전제다.
- 자취 정확도는 위치 정확도다. 두 로봇이 같은 맵에서 수 cm 안으로 맞는 자기 위치를 가져야 한다. 맞지 않는 만큼 팔로워는 "리더가 간 곳"이 아니라 "리더가 자기가 갔다고 믿는 곳"을 달린다.

### Alternatives

- **offset 목표를 더 자주(>2 Hz) 보낸다.** Nav2가 매번 다시 계획해 흔들리고, 목표점 자체가 지름길 위에 있다.
- **리더 계획 경로(`navigation/path`)를 팔로워에 준다.** 리더가 계획대로 달리지 않은 곳(장애물 회피, 수동 개입, 차선 추종 주행)에서 틀리고, 차선 추종 리더에는 계획 경로가 없다.
- **자취 위 지점을 Nav2 moving goal로 보낸다.** 계획기가 그 점들 사이를 다시 이어 붙여 같은 지름길 문제가 남는다.
- **팔로워끼리 사슬(앞 팔로워를 따라감).** 오차가 대열 길이만큼 쌓인다. v1은 모두 리더 자취다(열린 항목 3).

### 열린 항목

1. **로봇 사이 위치 일치.** 두 로봇의 AMCL(또는 현장 Rosy Cam 자세)이 서로 몇 cm 안에 맞는지 장치에서 잰 적이 없다. 장치 수용의 첫 지표다.
2. **현장 위치 원천.** 현장에서 map pose가 Rosy Cam(D-515) 위치라면 지연·갱신 주기가 자취 정밀도에 들어간다. 확인 전에는 SIM 수치를 현장 수치로 쓰지 않는다.
3. **사슬 대 리더 하나.** 3대 이상에서 리더 하나 자취는 뒤 팔로워의 gap이 길어진다(슬롯 × spacing). 사슬은 오차가 쌓인다. 3대 SIM 뒤에 정한다.
4. **장애물 앞에서 서기만 한다.** 막히면 리더는 계속 가고 팔로워는 선다. 간격이 커져 1.5 m 건너뜀에는 걸리지 않지만(자취는 계속 쌓인다), 오래 막히면 운영자가 풀어야 한다. 막힘 정체 판정(D-407 꼴)은 없다.
5. **D-422 기억 점.** 차선 추종이 아닌 바퀴 출력은 D-422 range_min 아래 기억 점을 지운다(`note_wheels` owned=false). trail 중에는 LiDAR 현재 점과 초음파만 본다.
6. 장치 수용(DEVICE)과 Safety-Review는 착지 전에 받는다. 이 브랜치는 `body_stop.py`·`command/manager.py`를 고치지 않는다.
