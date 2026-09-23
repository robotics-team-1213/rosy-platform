# 차선망 미션 3단계 — 주차(도킹) 설계

작성 2026-09-23 · 브랜치 `feat/lane-network-junctions` · 상위 계획: 차선망 미션 4단계
(1 주차장→차선, 2 전 차선 투어, **3 주차**, 4 전 구간 연속). 대상은 260919 트랙
Gazebo(map_v2_fleet)이며, 이 문서가 다루는 것은 3단계와 그것을 1·2단계에 잇는
미션 시퀀스(언도킹 → 투어 → 도킹)다.

## 1. 사용자 결정 (고정)

| 항목 | 결정 |
|------|------|
| 마커 | 낮은 경사(쐐기) ArUco. `DICT_4X4_50` id 7, 태그 50 mm, 바닥에서 25–35° 기운 면. 면의 아래 모서리가 x≈-0.78, y=0, 법선이 -x(베이 쪽)를 본다. 윗단은 21–29 mm만 솟는다 |
| 베이 진입 | 칠해진 내곽선을 그대로 둔다(입구 절개·베이 테두리 도색 없음). 로봇은 선을 넘어 들어간다 |
| 스퍼 주행 | 스퍼 구간에서는 차선 추종을 끈다. 오도메트리와 마커만으로 주행한다 |

카메라는 25° 숙여 있고 광학 중심이 0.0602 m 높이라 6 cm 위를 보지 못한다. 마커가 낮은
쐐기인 이유가 이것이다. 계산하면 화면 윗변 광선은 수평에서 4.9° 아래라, 카메라 앞
d m에서 보이는 최대 높이는 `0.0602 - 0.0863·d` 다.

## 2. 배치와 기하

- 스퍼: `lane_graph.yaml` `parking` — 진입점 (-1.2696, 0)(west 차선 위), 주차점 (-1.000, 0, yaw 0),
  길이 0.2696 m. 블록 내부(x -1.164 ~ -0.70, y=0)는 도색이 없다.
- 마커: 경사 **25°**, 흰 여백(quiet zone) 1셀(8.33 mm)을 두른 66.7 mm 면. 윗단 높이는
  66.7·sin25° = 28.2 mm로 사용자 범위 안이다. 25°를 고른 이유: 같은 높이 상한 안에서
  여백을 온전히 1셀 둘 수 있는 유일한 경사다(30°면 여백이 반 셀로 줄어든다). 검출
  거리는 합성 렌더 시험으로 확인한다(§6).
- 마커의 흰색은 **밝기 임계(180) 아래**로 렌더되도록 확산 반사를 낮춘다(diffuse 0.6).
  paint localizer와 차선 추적기가 마커를 도색으로 오인하지 않게 하려는 것이다.
  ArUco는 적응 임계라 흑/회 대비로 충분하다.
- 주차점에서 태그 중심까지 수평 거리 `tag_offset_m` = 0.2502 m(= 0.78 - 1.000 + 33.3 mm·cos25°).
  카메라 광학 중심 기준 경사거리는 약 0.21 m로, 요구 범위(0.17–0.23 m) 안이다.
- 벽: 외곽 벽 안쪽 면이 x = -1.4025. 로봇 후미는 base_link -0.075 m라 진입점(-1.2696)에서
  후미는 -1.345, 벽까지 57 mm 남는다. 기본 언도킹 0.35 m는 벽에 닿는다 → 0.27 m.

## 3. 데이터 흐름

```
Gazebo camera (camera/front, 5 Hz, 320x180)
  └─ control: dock_observer_node  ── cv2.aruco + solvePnP + 카메라 외부 파라미터
        └─ dock/observation (std_msgs/String JSON, 센서 증거만)
              └─ CORE ros_bridge ── DockObservationFeed (라인 시계로 신선도 판정)
                    └─ DockingManager (주차형 기종: 스테이징 없음, 포즈 정렬 접근, 포즈 정착)
                          └─ executor.drive → CommandManager 도킹 슬롯 → cmd_vel (CORE 단독 발행)
odom ── CORE ros_bridge ── 프레임 사이 오도메트리 전파, 언도킹 후진·회전
```

- **검출은 control에서** 한다. 프레임과 OpenCV가 control에 있고 CORE는 원시 프레임도
  OpenCV도 갖지 않는다(D-66). 새 노드 `dock_observer_node`는 `line_observer_node`와 같은
  형식(JSON String, `source`/`stamp`/`visible`/`confidence`)으로 증거만 낸다. 기존 노드에
  섞지 않은 이유: line_observer는 D-143 증거 의무와 다섯 가지 모드를 이미 지고 있고, 도크
  검출은 모드와 무관하게 늘 같다. 320x180 5 Hz라 이미지 디코딩 중복 비용은 무시할 만하다.
- `dock_tag.detect_dock_tag`에 **카메라 외부 파라미터**(높이, 숙임각, base_link 앞 오프셋)를
  선택 인자로 더한다. 주면 태그 중심을 base_link 평면 좌표(x 앞, y 왼쪽)로, `yaw`를 태그의
  안쪽 축(로봇 쪽에서 태그로 들어가는 방향, 법선의 반대)의 base_link 방위로 낸다 — 태그를
  정면으로 마주 보면 yaw=0. 주지 않으면 기존 동작(베어링 yaw) 그대로다(DNC-007 경로 불변).
- CORE의 `DockObservationFeed`는 ROS 무의존이다. ros_bridge가 JSON을 넣고, 수신 시각은
  `traffic_gate.line_clock`(use_sim_time이면 sim 시계, 아니면 monotonic — 25149a92와 같은
  규칙)으로 찍는다. 관측 시각은 `received_at - (source_now - stamp)`로 옮겨 적는다.
  신선도 0.6 s(sim)를 넘긴 관측은 없는 것이다. 도킹 매니저의 시계도 같은 시계로 묶는다.
- 기종 `detector: "observation"`일 때 `select_detector`가 이 피드를 읽는 검출기를 고른다.
  피드가 없으면 기존처럼 빈 `SimulatedDetector`로 떨어진다(fail-closed).

## 4. 제어기 — 기존 매니저 확장, 기종 설정으로 게이트

`DockType`에 기본값이 기존 동작과 같은 필드를 더한다. 기본값에서는 109개 기존 도킹
시험이 그대로 통과해야 한다.

| 필드 | 기본(기존) | 주차형 | 뜻 |
|------|-----------|--------|----|
| `staging` | `true` | `false` | Nav2 스테이징 생략(이 트랙의 Nav2/AMCL은 믿을 수 없다) |
| `approach` | `"bearing"` | `"pose"` | 포즈 정렬 접근 |
| `settle` | `"agent"` | `"pose"` | 에이전트·접점 없이 포즈로 정착 판정 |
| `tag_offset_m` | – | 0.2502 | 주차점→태그 중심 수평 거리 |
| `acquire_creep_m` | 0 | 0.15 | 태그가 안 보일 때 오도메트리 직진 허용 거리 |
| `undock_turn_rad` | 0 | +π/2 | 후진 뒤 목표 방위 = 도크 yaw + 이 값 |
| `pose_tolerance_m` / `_rad` | – | 0.012 / 3° | 정착 판정(수용 기준 20 mm/5°보다 안쪽) |

주차형 도킹 순서 (`DOCKING` 상태, 새 단계는 괄호):

1. **(TURNING)** 진입 회전: 목표 방위 = 도크 yaw. CORE 맵 포즈로 상대각을 한 번 계산하고
   오도메트리 yaw로 수행한다. 투어 끝(+90°)에서 -90°. 이미 ±3° 안이면 생략한다.
2. **ACQUIRING**: 태그가 보일 때까지 방위를 유지하며 크리프(0.03 m/s)로 최대 0.15 m
   전진. 진입점에서는 태그 윗단이 시야 밖이라(§1 식) 약 0.1 m 들어가야 보인다.
3. **APPROACHING (pose)**: 관측으로 도크 좌표계에서의 로봇 포즈 (ex, ey, eθ)를 세우고,
   프레임 사이(5 Hz)는 오도메트리 증분으로 전파한다. 관측은 촬영 시각의 오도메트리와
   짝지어 지연을 없앤다. 제어 법칙:
   `θ_ref = -atan(k_y·ey)`(±25° 제한), `ω = k_θ(θ_ref - eθ)`,
   `v = clamp(k_v·(-ex), 0.015, 0.05)` m/s. 남은 거리 ≤ 3 mm면 정지.
4. **(ALIGNING)** 제자리 회전으로 eθ → 0 (±1°). 차동구동은 제자리 회전이 위치를 바꾸지 않는다.
5. **SETTLING (pose)**: 정지 0.6 s 뒤의 새 관측으로 |ex|,|ey| ≤ 12 mm, |eθ| ≤ 3° 확인 →
   `DOCKED`. 벗어나면 재착좌(기존 `_reseat` → BACKOFF 후 ACQUIRING)로, 상한은 `max_retries`.

언도킹(`UNDOCKING`): 검출기 없이 오도메트리로 0.27 m 후진 → 목표 방위(도크 yaw + π/2)로
제자리 회전 → `UNDOCKED`. 회전이 없는 기존 기종은 후진만 한다(불변).

동작 모드 (2026-09-24 독립 리뷰 H1–H3·M1·M2 반영): 도킹은 **모든 기종에서** 처음부터 끝까지
`DOCKING` 모드를 쥔다. 주차형만 게이트하지 않은 이유: 그 전에는 기본 기종의 도킹 주행이
NAVIGATION일 때만 우연히 바퀴에 닿았고, 그 우연은 Nav2·군집 목표와 같은 슬롯을 다퉜다.

- `CommandManager`는 도킹 전용 슬롯(`set_docking_twist`)을 둔다. 도킹 슬롯은 `DOCKING`에서만,
  nav 슬롯은 `NAVIGATION`에서만 바퀴에 닿는다. ros_bridge의 `DockingExecutor.drive/stop`은
  도킹 슬롯을 쓴다.
- Nav2의 `nav_cmd_vel`은 `docking_mode.route_nav_cmd_vel`이 나눈다: `NAVIGATION`이면 nav 슬롯,
  `DOCKING`이면 **기본 기종의 STAGING 단계에서만** 도킹 슬롯, 그 밖에는 버린다.
- 모드 획득은 `DockingManager`에 주입한 `take_mode`(CoreServices.take_docking_mode) 한 곳이다.
  `dock()`/`undock()`이 자기 검증 뒤, 상태나 executor를 건드리기 **전에** 부른다. 그래서 API와
  배터리 자동 복귀가 같은 길을 지나고, MANUAL·EMERGENCY에서의 거절(409 `MODE_CONFLICT`)은
  도킹 상태를 바꾸지 않는다. 획득할 때 Nav2 목표와 군집 세션을 먼저 취소한다
  (`nav.cancel(source="docking")`). NAVIGATION은 IDLE을 거친다.
- `DOCKING`을 떠나는 모든 전이(`ModeMachine.change_listeners`)가 도킹을 먼저 접는다:
  EMERGENCY면 실패(`DOCK_FAILED`), 그 밖(IDLE·MANUAL)은 취소. `DOCKING → MANUAL`을 허용한다
  (MANUAL 3 > DOCKING 4). 라인 추종 모드 API는 도킹 중 409 `DOCKING_ACTIVE`로 거절한다.
- 도킹 중 `NavigationManager.goal/moving_goal`은 `DOCKING_ACTIVE`로 거절한다. 배터리 정책의
  `RETURN_HOME`은 진행 중인 도킹이 곧 귀환이므로 Nav2 목표를 내지 않는다.
- ros_bridge가 도킹이 끝나면(도킹/언도킹 상태가 아니면) `IDLE`로 되돌린다. 주차형 도킹이
  움직이는 동안은 도킹 틱을 20 Hz로 돌린다(슬롯 0.5 s 만료를 RTF 0.25에서도 넘기지 않게).

기능 활성화는 **시뮬레이션 전용**이다: `map_v2_fleet_core.yaml` 오버레이의
`docking.simulation_supported: true`와 `docking.seed`(주차형 기종 + `parking` 도크 1개)는
`runtime.mode: simulation`일 때만 읽힌다(교통 정책의 `simulation_signal_control`과 같은 방식).
기본 `capabilities.yaml`의 `docking.supported: false`는 그대로다.

## 5. 미션 시퀀스 — `mission_harness.py`

한 번의 launch: 주차점 스폰 (-1.0, 0, 0), `route_start`도 주차점(로컬라이저와 경로 추종기를
로봇이 실제 선 자리로 초기화하고, 언도킹 중 오도메트리 증분으로 진입점까지 따라가게 한다),
`route`는 2단계 투어 키 그대로, `dock_observer:=true`.

1. 준비 대기(`junction_harness.wait_ready`).
2. `POST /docking/dock` — 주차점에서 도킹을 한 번 확정한다(DOCKED여야 언도킹을 받는다).
3. `POST /docking/undock` → `UNDOCKED`까지.
4. `PUT /line-follow/mode CAMERA_LINE` → 투어. 진척(`Progress`)은 투어 시작 표본에 고정한다.
   `CoreLease`는 CORE가 LOST를 낼 때만 잃는다.
5. 투어 도착 → `PUT … OFF` → `POST /docking/dock` → `DOCKED` 또는 `DOCK_FAILED`까지.
6. 채점: `score_route`(투어), 주차점 최종 오차(dx, dy, dyaw — Gazebo `/odom` 참값), LOST 없음.
   `results.json`, `track.json`(단계 표시), `core_status.jsonl`(라인·도킹 상태 벽시계 1 s 간격),
   `clock_step_s`를 남긴다. 예산은 모두 sim 시간이다.

## 6. 수용 기준

- **주차 정확도**: Gazebo `/odom` 참값 기준 주차점 대비 위치 오차 √(dx²+dy²) ≤ 20 mm,
  |dyaw| ≤ 5°. **3회 중 3회**.
- **연속 미션**: 언도킹 → 투어(score_route 통과, LOST 없음) → 도킹 한 번의 launch에서 통과.
- **오프라인(호스트)**: 합성 렌더(바닥 도색 + 쐐기 마커, Gazebo 카메라 모델)에서
  (a) 태그 포즈 복원 x/y 수 mm, yaw 1–2° 이내, (b) 진입 오차 ±20 mm, ±5°에서 시작한
  폐루프 접근이 20 mm / 5° 안으로 수렴.

## 7. 시뮬레이션 전용 대 실기

| 시뮬레이션 전용 | 실기에서 따로 필요 |
|-----------------|-------------------|
| 도킹 capability 오버레이·도크 시드 | Pinky 프로필의 도킹 지원 판정, teach로 기록한 도크 포즈 |
| `/odom` = 월드 참값(맵=오도메트리). 진입 회전의 맵 방위가 곧 오도메트리 방위 | AMCL/paint 로컬라이저의 맵 포즈. 진입 회전 오차는 태그 접근이 흡수하지만 오도메트리 드리프트는 실측 필요 |
| 카메라 외부 파라미터가 URDF 선언값(25°, 0.0602 m, 0.034 m) | 실기 카메라 보정값·장착 공차. 1° 숙임 오차가 x를 수 mm 흔든다 |
| 렌더된 마커(균일 조명, 흐림 없음) | 인쇄 마커의 반사·모션 블러·노출. 실기 쐐기 제작(도면 필요) |
| 정착 판정은 포즈만 | 충전 접점이 있으면 기존 `settle: agent` 경로 |
