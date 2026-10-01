## D-407 차선 자율이 막히면 관제에 판단을 묻고, 답이 없으면 짧게 물러나 다시 본다

**Status:** Proposed (2026-10-02, 동작·계약 결정; 사용자 지시 2026-10-02 "문제 상황에서 관제와 소통해 명령을 받고, 안 되면 후진 등으로 다시 판단"). CORE 차선 추종(D-143, D-344)이 앞물체·차선 상실로 멈춘 뒤의 처리만 다룬다. Nav2 내비게이션 막힘, 도킹, 군집 HOLD(D-35)는 포함하지 않는다. 경로·필드·오류코드는 D-18 에 따라 C5 구현 변경에서 API Reference·typed schema 와 함께 확정한다.

## 배경

- **실주행에서 막힘이 대부분이었다.** 2026-10-01 8kcn·9dfk 실주행에서 차선 추종 시간의 대부분이 `obstacle_ahead` HOLD 또는 `LOST` 였다. 원인은 로봇 자기 몸 LiDAR 반사(로봇별 self-mask 로 수정), 차선 끝 벽 앞 모서리, 신호등 받침·소품 근접, 원형교차로 중앙의 차선 부재였다.
- **지금은 멈추면 끝이다.** D-344 §11 앞물체 정지는 `obstacle_resume_m` 밖으로 비워질 때만 풀리고, 정지한 로봇은 스스로 비울 수 없다. `LOST` 는 3 s 뒤 운전자 재선택 전까지 고정된다. `obstacle_escalate_s`(5 s) 뒤 `nav.line_obstacle_hold` 사건을 한 번 내지만 받는 쪽 규약이 없다.
- **운전자는 대부분 그 자리에 없다.** 차선 자율의 목표는 사람이 조향하지 않는 주행이다. 관제(Fleet 콘솔)는 여러 대를 보고 있어 즉시 답하지 못할 수 있다.

## 결정

1. **막힘을 하나의 상태로 본다.** 차선 추종이 `obstacle_ahead` 로 `obstacle_escalate_s` 이상 머물거나 `LOST` 가 되면 CORE 는 막힘 사건을 연다. 사건은 원인(`obstacle_ahead` | `lane_lost`), 앞·뒤·회전반경 여유(로봇별 self-mask 적용, URDF 몸 기준), 마지막 차선 관측, 카메라 미리보기 순서번호를 담는다. 같은 막힘에서 한 번만 연다.
2. **먼저 관제에 묻는다.** 막힘 사건은 FleetAgent 를 거쳐 관제에 판단 요청으로 간다. 관제가 고를 수 있는 답은 다섯 가지다.
   - `WAIT`: 그대로 HOLD, 다음 요청까지 대기.
   - `RESUME`: 운전자가 앞이 비었음을 확인. 앞물체 정지를 이번 한 번 `obstacle_stop_m` 까지 접근 허용으로 풀고 차선 추종을 다시 시작한다. 경로 띠 안 물체가 `obstacle_stop_m` 안이면 거부한다.
   - `BACK_AND_RETRY`: 아래 4 의 짧은 후진과 재판단을 즉시 실행.
   - `MANUAL`: 차선 추종을 끄고 수동 모드로 넘긴다(D-342 한도).
   - `ABORT`: 차선 추종을 끄고 IDLE.
   답은 관제 운영자 권한 이상이어야 하며, 막힘 사건 id 와 맞아야 한다(늦은 답이 다음 막힘에 쓰이지 않게).
3. **관제 답이 없으면 기다린다.** 판단 요청 뒤 `recovery_ask_s`(기본 15 s) 안에 답이 없거나 관제 연결이 없으면 4 로 간다. 관제가 `WAIT` 를 주면 4 로 가지 않는다.
4. **로컬 복구는 짧은 후진 한 번과 재판단이다.**
   - 후진 거리 `recovery_back_m`(기본 0.08 m), 속도는 D-342 수동 한도와 0.03 m/s 중 작은 값.
   - 후진 전과 후진 중 뒤 여유(LiDAR, self-mask 적용, 몸 뒤끝 기준)가 `recovery_rear_clear_m`(기본 0.06 m) 보다 커야 한다. scan 이 `clearance_stale_s` 보다 오래되면 후진하지 않는다.
   - 후진 뒤 1 s 정지하고 차선과 장애물을 다시 판정한다. 차선이 보이고 앞이 비었으면 차선 추종으로 돌아간다.
   - 같은 막힘에서 로컬 복구는 `recovery_max_attempts`(기본 2) 번까지. 넘으면 HOLD 로 남고 관제에 다시 묻는다(다시 15 s 를 기다리지 않고 관제 답만 기다린다).
5. **안전 불변식.**
   - CORE 가 유일한 `cmd_vel` 발행자다(D-2). 후진도 CORE 차선 추종 결정으로 나간다.
   - 비상정지, IDLE, 차선 추종 OFF 는 복구 중에도 언제나 우선한다. 복구 중 운전자 hold(D-344 §8)가 끊기면 즉시 0.
   - 보정 세션(D-321 부록) 중에는 복구하지 않는다.
   - 로컬 복구는 기본 꺼짐(`recovery_local_enabled: false`). 켜려면 로봇별 설정이 필요하고, 로봇의 self-mask 측정이 끝났어야 한다.
6. **기록.** 막힘 열림, 관제 요청·답, 로컬 복구 시도·결과, 닫힘을 사건으로 남긴다(사건 카탈로그와 감사 로그). 학습 자료 녹화(D-379)가 켜져 있으면 막힘 전후 프레임 구간을 표시한다.

## 결과

- 막힌 로봇이 관제의 판단을 받거나, 받지 못하면 스스로 물러나 다시 본다. 그래도 안 되면 멈춘 채 관제를 기다린다. 멈춘 채 아무 일도 일어나지 않는 상태는 없어진다.
- 관제 화면에 판단 요청 목록과 다섯 답이 필요하다(Fleet 콘솔 변경).
- 막힘 사건과 미리보기가 쌓여, 무엇이 차선 자율을 막는지 현장 자료가 남는다.

## 검증

- 호스트: 막힘 열림 조건, 사건 id 일치, 답별 동작, 15 s 시간초과, 후진 거리·속도·뒤 여유·stale scan 거부, 최대 시도, 비상정지·hold 끊김 우선을 시험한다.
- Gazebo: 차선 끝 벽 앞 모서리와 원형교차로 중앙에서 관제 무응답 → 후진 → 재판단 → 복귀를 재현한다.
- 실기: 로봇별 self-mask 측정 뒤, 사용자 승인으로 로컬 복구를 켜고 녹화와 함께 확인한다.

## 잇는 결정

D-2(단일 cmd_vel), D-143(차선 추종), D-321 부록(보정 세션), D-342(수동 한도 계단), D-344 §8·§11(hold·앞물체 정지), D-379(학습 자료), D-397(URDF 기본값·로봇별 교정).

## 구현 메모 (2026-10-02, CORE 쪽, feat/d407-stuck-recovery-core)

Status 는 Proposed 그대로다. CORE 쪽만 구현했고 Fleet 콘솔 화면(판단 요청 목록과 다섯 답)과 FleetAgent 의 답 중계는 다음 단계다. 막힘 사건은 다른 사건처럼 FleetAgent 사건 버퍼로 이미 올라간다.

- 상태기계: `src/runtime/services/core_features/line_follow/stuck_recovery.py`(ROS 없음). 관리자 연결은 `stuck_wiring.py`(mixin), CORE 입력 묶기는 `src/runtime/gateway/core/line_follow_wiring.py`(관제 연결 = `FleetAgent.connected`, 보정 lease, `safety.manual_linear`, 미리보기 순서번호). 묶이지 않은 입력은 닫힌 쪽(연결 없음, 보정 중, 선속도 한도 0)으로 읽어 막힘을 열지 않는다.
- 후진은 차선 추종 결정(`LineFollowDecision`, 음의 선속도)으로 나가 기존 line → traffic gate → CommandManager 경로를 탄다(D-2). 교통 정책이 ENFORCED 에서 HOLD 면 후진도 0 이다.
- 답: `POST /api/v1/line-follow/stuck/decision {stuck_id, decision}`(Operator 이상, API Ref v1.72). 상태: `GET /api/v1/line-follow` 의 `stuck`. 사건 `nav.line_stuck_opened/asked/answered/local_attempt/local_result/closed`.
- 설정: `line_follow.recovery_*`(기본 `recovery_local_enabled: false`), 몸 기하 `body_lidar_x_m`·`body_rear_x_m`·`body_rotation_radius_m` 는 로봇 패키지 `core.yaml` 에 URDF 공칭값(geometry.yaml, drift 시험)으로만 둔다. 없으면 후진하지 않는다.
- 해석과 차이:
  - 후진 거리는 시간으로 잰다(`recovery_back_m / 속도`). 오도메트리 폐루프가 아니다.
  - 뒤 여유는 self-mask 적용 LiDAR 점의 뒤 직진 띠(`obstacle_corridor_half_width_m`)에서 몸 뒤끝(caster.rear_x_m)까지다. LiDAR `range_min` 안은 보이지 않으므로 `range_min - (LiDAR 에서 몸 뒤끝까지)` 가 `recovery_rear_clear_m` 보다 크면 후진을 거부한다(`rear_blind`). Pinky C1(range_min 약 0.15 m, 뒤끝까지 0.059 m)은 사각 0.091 m 라 지금 설정으로는 후진하지 않는다. 실기에서 켜기 전에 사각 처리(값 조정 또는 지나온 길 신뢰 규칙)를 사용자가 정해야 한다.
  - 실패한 시도 뒤 시도가 남으면 관제를 다시 15 s 기다리지 않고 바로 다음 후진을 한다. 시도를 다 쓰거나 거부·중단되면 HOLD 로 남아 관제 답만 기다린다.
  - `BACK_AND_RETRY` 도 `recovery_local_enabled` 와 최대 시도 수를 따른다(로컬 복구의 전제인 self-mask 측정이 같으므로).
  - 막힘 중 앞이 스스로 비면(`obstacle_ahead` 가 풀리면) 사건을 `cleared` 로 닫는다.
  - D-379 녹화 구간 표시는 아직 없다. 사건의 시각으로 구간을 찾을 수 있다.
