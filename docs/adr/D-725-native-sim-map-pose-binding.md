## D-725 격리 Gazebo의 명시적 native SIM MapPose 결속

**Status:** Proposed (2026-10-12). 사용자 Gazebo 차선 완주 지속 목표의 SIM 전용 구현 후보다. D-494 trip 위치 입력을 실제 native 관측에 한해 확장하고 D-511 소비자의 정합성을 지킨다. SOURCE, 원격 회귀, Gazebo 실행, DEVICE/FIELD 수용은 별도다.

### Context

baseline에서 operator pin anchor가 10초를 넘어 DEGRADED가 되어 Fleet trip이 stopped(pose)로 끝났다. fresh odom은 anchor 나이를 갱신하지 않는다. 현재 world에는 overhead Vision 관측이 없다. 반복 pin, 가짜 camera sighting, TTL 확대는 위치 관측을 대신하지 못한다.

### Decision

1. `tools/sim/native_gazebo_map_pose.py`의 `NativeGazeboMapPosePort`는 developer SIM bootstrap에서만 만든다. ROS-free typed 관측 접점이며 command writer/transport가 아니다. 기본 운영은 기존 `MapPoseService` 그대로다.
2. immutable binding은 run/epoch/world/map revision/committed source SHA/world·graph·URDF SHA256/domain 80..99/owned partition/model↔robot↔frame/명시적 `T_map_world`를 묶는다. 실제 localhost DDS·process·artifact·native plugin 결속을 runner가 확인한다. 임의 odom을 map으로 승격하지 않는다. 별도 runner manifest가 provider binding과 정확히 일치하고 `deployment_profile='simulation'`일 때만 기존 `map_pose_port` DI에 넣는다. `simulation_pose_binding`은 내부 constructor 검증이며 새 REST 경로나 wire 필드가 아니다.
3. native header stamp와 별도 live `/clock` callback, wall/monotonic receipt를 유지한다. native와 clock freshness는 기존 `max_pair_s` 0.25초 안이다. sample은 clock receipt를 갱신하지 않는다. reset/replay/foreign/invalid/stale 입력은 UNKNOWN을 latch한다. 같은 instance의 새 표본으로 해제하지 않는다. 실제 새 격리 run/epoch에 새 binding/instance를 만든 뒤 재수용한다.
4. 실제 CORE snapshot의 UTC `odom_pose.stamp`를 `MapPose.odom_stamp`로 보존한다. SIM 초나 adapter now로 authority `pose_stamp`를 합성하지 않는다. CORE age는 기존 `max_odom_age_s` 3초, CORE UTC와 native capture wall 동기 상한은 `max_interp_gap_s` 1.2초다. CORE stamp는 측정 시각보다 수신 시각에 가깝다는 기존 한계를 기록한다. pose 모순은 `max_jump_m` 0.15m/`max_jump_deg` 20°로 검사한다. native step 속도·각속도는 기존 1m/s·360°/s reset 검사다. 측정 stamp 없는 `gz model -p` 텍스트에 now stamp를 붙여 반복 입력하지 않는다.
5. fresh native pose를 기존 `MapPose`로 반환한다. `source`/`anchor_source`는 `native_gazebo_sim`, `map_id`는 binding 값, `dead_reckon_m`은 0(계속 측정된 native pose이며 odom bridge가 아님)이다. native/clock/receipt/CORE UTC/binding/epoch 진단은 private runner evidence에 보존한다. active map revision 변경은 UNKNOWN이며 이전 map으로 되돌려도 복구하지 않는다.
6. SIM provider를 쓰면 TripRunner, LaneComplianceMonitor, junction signal, 기존 map-pose GET는 같은 provider를 쓴다. camera ingest/operator pin/teach/formation/identity/tracking/stuck AI/guide는 원래 MapPoseService를 유지한다. 기존 non-SIM custom port의 DI 동작은 보존한다.
7. CORE final command owner, authority/lease/traffic/camera/IR/scan/body/EStop gate는 바꾸지 않는다. 지도 위치 관측이 camera target 유효성·바닥 proof·통행권·행동 허가로 바뀌지 않는다.

### D-427 — 여덟 질문

| 질문 | 답 |
|---|---|
| Q1 기능 | 격리 SIM의 native pose로 Fleet trip 위치 관측 연결 |
| Q2 소유자/holder | tools/sim developer adapter, Fleet app 내부 DI, 기존 World MapPose 재사용 |
| Q3 입력 | 실제 stamped model-pose, live clock, CORE UTC snapshot, 검증된 run/source/map binding |
| Q4 출력 | 기존 MapPose/private diagnostic, final command 없음 |
| Q5 배치 | developer SIM runner만, robot wheel/image에는 설치하지 않음 |
| Q6 권한 | 관측 입력만, CORE final owner와 Fleet admission/lease 그대로 |
| Q7 검증 | RED→GREEN strict remote floor, provenance/reset/replay/stale/transform/UTC/DI/teach 분리, runtime 별도 |
| Q8 종료/승격 | UNKNOWN latch, 새 bound run 재수용, 실제 OFF/lease clear/rest/cleanup, DEVICE/FIELD 승격 없음 |

### D-429/D-430 — 층과 관심사

| 층/관심사 | 변경 | 유지 경계 |
|---|---|---|
| 관측/World | 실제 SIM 관측과 MapPose 결합 | Vision/실물 localization 주장 없음 |
| 정책/Fleet | trip/차선 준수/신호/readback 위치 일치 | teach/formation/AI 자동 확장 없음 |
| 제어/CORE | 변경 없음 | 최종 cmd_vel 단독 owner |
| 실행/장치 | 변경 없음 | driver/lease/EStop/유효 target gate |
| safety | 관측 freshness/reset/foreign/모순 UNKNOWN | scan/IR/body/authority 정지를 덮지 않음 |

### Consequences and acceptance

회귀는 adapter SOURCE 근거다. 실제 Gazebo는 exact source/map/model/run binding, live clock/native stamp/UTC authority, active map, actual trip/lease/grant, arrival 또는 실패, 최종 OFF/rest/cleanup로 따로 확인한다. native SIM ground truth 기반 Fleet arrived는 Vision/AMCL/실물 localization 수용이 아니다. 0.25초 native freshness 창과 실제 CORE 시각 쌍의 수용은 runtime에서 확인해야 한다.

### 개정 1 (2026-10-18) — 오래된 입력은 그동안만 UNKNOWN, 재설정·재생·모순만 고정한다

drivable v2 Gazebo 한 바퀴(`feat/v2-sim-lap`, r21–r32)에서 3항의 "stale 입력은 UNKNOWN을 latch한다"가 주행과 무관한 한 번의 지연으로 run 전체를 끝냈다. 원인은 `fleet_trips.py`가 종료 때 남기는 위치 진단으로 확인했다.

- r24: CORE가 아직 odom 없는 첫 snapshot → `core_snapshot_invalid_or_stale`, 두 대 모두 출발 못 함.
- r26: 로봇 생성 중 `/clock`이 멈췄다 다시 시작 → `clock_reset_or_replay`, 출발 못 함.
- r22: 주행 중 CORE 상태 읽기 한 번 실패 → `core_read_failed`, 1.25 m에서 정지.
- r32: 모델 PC 부하 24(다른 세션의 시험)에서 native·CORE 쌍이 잠시 오래됨 → `native_or_core_stale_or_contradictory`, 0.7 m에서 정지.

결정:

1. 오래된 입력(늦은 `/clock`, 늦은 수신·native sample, sample 사이 간격, `max_pair_s`·`max_odom_age_s`·`max_interp_gap_s`를 넘은 쌍)은 그 sample을 버리고 그동안 UNKNOWN을 낸다. 새 sample과 새 CORE snapshot이 맞으면 다시 LOCALIZED다.
2. 고정(latch)은 재설정·재생·모순에만 남는다: `/clock` 또는 wall/monotonic 역행, 수신 순서 역행, foreign binding, 무효 sample, 로봇이 움직일 수 없는 속도의 위치 점프(간격이 있어도 stamp 차이로 판정), native와 CORE 위치·방향 모순, active map 변경.
3. 시작 시 아직 odom이 없는 CORE snapshot, 첫 위치 전의 `/clock` 멈춤·재시작은 취소할 위치가 없으므로 다시 읽는다. CORE 읽기 실패 한 번은 마지막 snapshot을 유지하고, 그것이 `max_odom_age_s`를 넘으면 1항대로 UNKNOWN이다.

안전 영향: UNKNOWN 동안 Fleet은 지금처럼 trip을 시작하지 않고(`TRIP_POSE_UNTRUSTED`) 진행 판정에 쓰지 않는다. CORE의 정지·스캔·IR·몸 정지는 바뀌지 않는다. 이 port는 `deployment_profile: simulation`에서만 쓰이고 실물 localization 주장을 하지 않는다.

확인: `test/test_native_gazebo_map_pose.py` — 늦은 시계는 UNKNOWN 뒤 새 sample로 회복, 시계 역행은 run 동안 고정, 간격 뒤 정지 sample은 수용·간격을 건넌 점프는 고정, odom 없는 시작 snapshot은 대기, 첫 위치 전 시계 멈춤은 재기준, CORE 읽기 실패는 snapshot 만료까지 유지. SIM 결과는 주행 일지에 적는다.

**Related:** D-494, D-511, D-517, D-541, D-676, D-427, D-429, D-430.
