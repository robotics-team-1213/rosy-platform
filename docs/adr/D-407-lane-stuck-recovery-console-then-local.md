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
  - 뒤 여유는 self-mask 적용 LiDAR 점의 뒤 직진 띠(`obstacle_corridor_half_width_m`)에서 몸 뒤끝(caster.rear_x_m)까지다. LiDAR 가 못 보는 뒤 띠(사각)는 `range_min - (LiDAR 에서 몸 뒤끝까지)` 와, 몸 뒤끝을 넘어 뒤 띠에 닿는 self-mask 창이 가리는 깊이 중 큰 값이다. scan 이 `range_min` 을 주지 않으면 사각을 모르는 것으로 보고 후진하지 않는다.
  - **사용자 결정 (2026-10-02): 방금 지나온 공간은 허용한다.** 사각이 `recovery_rear_clear_m` 보다 깊으면, CORE 가 실제로 낸(교통 게이트 뒤) 차선 추종 명령을 단조 시계로 적분해, 마지막 전진 명령까지 `recovery_trail_s`(기본 5 s) 동안 앞으로 순 `recovery_back_m` 이상 왔고 누적 |yaw| 가 `recovery_trail_yaw_deg`(기본 10°) 이하일 때만 후진한다. 후진 거리는 그 순 전진 거리를 넘지 않는다(후진·이전 시도는 순 거리에서 빠진다). 제자리 회전, 기록 없음, 기록이 1 s 넘게 끊김, 모드 변경 뒤에는 `rear_blind` 로 거부한다. 보이는 뒤 여유(사각 밖)는 후진 전·중 계속 `recovery_rear_clear_m` 보다 커야 한다. 해석: 막힘이 열릴 때는 이미 `obstacle_escalate_s` 넘게 서 있으므로, 창은 벽시계 최근 5 s 가 아니라 마지막 전진 명령에서 끝나는 5 s 다. 그 뒤로 로봇이 서 있던 동안 사각에 무언가 들어왔을 가능성은 이 규칙이 막지 않는다.
  - 실패한 시도 뒤 시도가 남으면 관제를 다시 15 s 기다리지 않고 바로 다음 후진을 한다. 시도를 다 쓰거나 거부·중단되면 HOLD 로 남아 관제 답만 기다린다.
  - `BACK_AND_RETRY` 도 `recovery_local_enabled` 와 최대 시도 수를 따른다(로컬 복구의 전제인 self-mask 측정이 같으므로).
  - 막힘 중 앞이 스스로 비면(`obstacle_ahead` 가 풀리면) 사건을 `cleared` 로 닫는다.
  - D-379 녹화 구간 표시는 아직 없다. 사건의 시각으로 구간을 찾을 수 있다.
- 독립 검토 반영(2026-10-02): 막힘 원인을 보고 상태가 아니라 래치(`_escalated`·`_lost_latched`)로 판단(일시 HOLD 가 막힘을 `cleared` 로 닫고 시도를 되살리던 결함), 받아들인 답은 증거 개정을 올려 미리 계산된 후진을 막고, MANUAL·ABORT 는 관리자 잠금 안에서 차선 추종을 끈 뒤 `POST /mode` 와 같은 전이(보정 lease, navigation·swarm 취소)를 쓴다. 답 사건에 토큰 id, LiDAR 정지를 쓰는데 scan 이 없으면 RESUME 거부, 설정 형 검사, sector 모드의 몸 점은 막힘 근처에서만 계산.
- Gazebo 검증(2026-10-02, ROS-SIM 한 대): `docs/validation/d407-gazebo-stuck-recovery-2026-10-02/result.md`. 무응답(관제 연결 없음) → 후진 0.08 m → 1 s → 재판정 → 복귀/2회 뒤 관제 대기, 답 다섯, hold 끊김·e-stop 우선을 확인했다. ASKING 15 s 창은 FleetAgent 시작 결함으로 시험하지 못했고, 복귀 직후 같은 자리 재막힘이 시도 수를 되살리는 반복을 발견했다.
- **확인 (2026-10-02, 조정자 결정, Gazebo 실행 뒤): 복구 뒤 곧 다시 막히면 같은 막힘이다.** `recovered` 로 닫힌 뒤 `recovery_restuck_s`(기본 20 s, 단조 시계) 안이거나, 복구 뒤 CORE 가 낸 순 전진이 `recovery_restuck_m`(기본 0.30 m)에 못 미친 채 다시 막히면 시도 수를 이어 센다. 새 `stuck_id` 를 쓰되 `nav.line_stuck_opened` 에 `restuck_of`(앞 막힘 id)와 이어받은 `attempts` 를 싣고, 이미 `recovery_max_attempts` 를 다 썼으면 곧바로 관제 답만 기다린다. 복구-재막힘이 끝없이 반복되던 Gazebo 관찰을 막는다. 모드 변경은 이 기억을 지운다.
- Gazebo 후속(2026-10-02): 뒤 띠 폭을 경로 띠(±0.09 m) 대신 URDF 몸 반폭(`footprint.half_width_m` 0.05655 m, geometry.yaml 에 추가, drift 시험)과 `recovery_rear_lateral_margin_m`(0.02 m)으로 — 옆 벽이 "뒤"로 세어지던 것을 고친다. 거부·중단 사건에 판정한 scan 의 뒤 여유·사각·trail 값, 비상정지로 닫힌 막힘은 사유 `estop`. FleetAgent 는 CoreServices.build 가 아니라 API 이벤트 루프에서 시작한다(hub_url 설정 시 CORE 가 죽던 결함).
- Gazebo 재실행(2026-10-02, 실제 Fleet 관제 연결): `docs/validation/d407-gazebo-console-rerun-2026-10-02/result.md` — CORE 기동·ASKING 15 s·Fleet 경로 답(409 그대로)·재막힘 2 회 뒤 관제 대기·좁힌 뒤 띠 확인. `nav.line_stuck_answered` 의 `token_id` 가 Fleet 감사에 거부되는 결함과 ASKING 중 연결 끊김을 보고했다.

## 구현 메모 (2026-10-02, Fleet 쪽, feat/d407-console-stuck-decisions)

- 관제 목록: Fleet 은 모은 상태의 `line_follow.stuck` 을 로봇별 판단 요청으로 들고, 같은 id 의 `nav.line_stuck_opened` 사건(FleetAgent)에서 여유·미리보기 순서번호를 붙인다. `GET /api/fleet/line-stuck`, 로봇 행 `line_stuck`(API Ref v1.77).
- 답: `POST /api/fleet/robots/{robot_id}/line-stuck/decision`(사이트 operator) 를 로봇 자격으로 CORE `POST /api/v1/line-follow/stuck/decision` 에 그대로 넘긴다. id 일치·RESUME 거부는 CORE 만 판단하고, 409 는 code·message 그대로 운용자에게 간다. 누가 답했는지는 Fleet 답 기록과 API 감사에 남는다(CORE 사건의 `by` 는 로봇 자격의 역할이다).
- 해석과 차이: §2 의 "FleetAgent 를 거쳐" 는 요청(사건) 쪽만 그렇다. 답은 FleetAgent 로 내려가지 않는다 — Fleet→로봇 명령은 모두 REST 이고 FleetAgent 에는 내려오는 명령 경로가 없어, 새 경로를 만들지 않았다. 로봇 카메라 영상은 Fleet 이 중계하지 않으므로(D-59) 화면은 미리보기 순서번호만 보인다.
- 화면: 예외 큐 패널 안 `판단 요청`. RESUME·BACK_AND_RETRY 는 확인 단계를 거치고, 로봇이 로컬 복구 꺼짐 또는 시도 소진을 보고하면 BACK_AND_RETRY 를 사유와 함께 막는다.
- **결정 (2026-10-02, 조정자): 지나온 길에는 유효 기간이 있다.** 사각 띠 후진에 쓰는 지나온 길은 후진 시작 때 그 마지막 전진 명령이 `recovery_trail_max_age_s`(기본 30 s, 단조 시계) 이내일 때만 유효하다. 관제를 기다리며 서 있던 시간도 센다. 넘으면 `rear_blind` 로 거부하고 사건에 `trail_age_s` 를 싣는다. 앞서 열려 있던 "서 있는 동안 사각에 무언가 들어올 수 있다"는 물음을 30 s 로 묶는다.
- §6 녹화 표시(2026-10-02): 로봇의 녹화기(`control/recording.py`)는 CORE 사건을 받을 통로가 없고, 새 통로는 새 프로토콜 면이다. 그래서 표시는 도구 쪽에서 한다 — `tools/perception/dataset/harvest.py` 가 수확할 때 CORE 사건 기록(`GET /api/v1/events`, viewer, 벽시계 `ts`)의 `nav.line_stuck_opened/closed` 를 `stuck_id` 로 짝지어, 겹치는 세션마다 `stuck_markers.json`(앞뒤 5 s 여유)을 쓴다(`stuck_markers.py`). 프레임은 bag `log_ns`(로봇 벽시계)로 찾는다. 한계: CORE 사건 기록은 메모리에 있어 CORE 재시작 전의 막힘은 표시되지 않는다.
- 관제 재실행 후속(2026-10-02, `docs/validation/d407-gazebo-console-rerun-2026-10-02/`):
  - **연결이 ASKING 중 끊긴 원인.** hub 는 heartbeat 와 사건 하나하나에 답한다(수락 또는 ERROR). FleetAgent 는 heartbeat 마다 답 하나만 읽어, 사건 답이 쌓였다. websocket 클라이언트는 받은 큐가 차면 소켓 읽기를 멈추고, 그러면 keepalive pong 도 읽지 못해 연결이 시간 초과로 끊긴다. 그 순간 hub 의 다음 전송이 닫힌 소켓에 닿아 "websocket.send after websocket.close" 가 남았다. 이제 에이전트는 수신 루프 하나가 모든 답을 읽고(ERROR 는 그 envelope 만 거부, 연결은 유지), 끊기면 이유와 함께 경고를 남긴다. hub 는 닫힌 소켓에 보내지 않는다.
  - **확인: 짧은 재연결은 연결로 본다.** `console_linked` 는 끊긴 뒤 `recovery_console_grace_s`(기본 3 s) 동안 참이다. 더 길면 지금처럼 로컬 복구로 간다(그 자체가 뒤 여유·사각·trail 규칙으로 지켜진다).
  - 답 사건의 `token_id` 는 `principal_ref`(토큰 기록 id, 비밀 아님)로 바꿨다 — Fleet 감사 저장소가 자격 증명 이름으로 거부해 답 사건이 Fleet 에 남지 않았다. Fleet 의 거부 규칙은 그대로다. 막힘 열림 사건에 `rear_state`(`clear`·`blocked`·`unknown`), 거부된 관제 `BACK_AND_RETRY` 답에 판정한 scan 의 trail·사각 값.
  - **§2·§4 명시.** 관제 `BACK_AND_RETRY` 는 §4 의 로컬 복구를 지금 시작하라는 뜻이다. 그 시도가 실패하고 시도가 남아 있으면(`recovery_max_attempts` 안) 관제에 다시 묻지 않고 다음 후진을 한다. 시도를 다 쓰면 HOLD 로 관제 답만 기다린다.
  - 검토 반영(2026-10-02): 에이전트는 WELCOME 을 받은 뒤에만 연결로 보고, 보낸 envelope 을 순서대로 기억해 hub 답과 짝짓는다. 일시 오류(`EVENT_STORAGE_UNAVAILABLE` 등)는 그 사건을 다시 보낸다(최대 3 번), `EVENT_NOT_AUDITABLE` 은 seq·종류를 남기고 버린다, 답 없이 끝난 사건과 보내던 중 취소된 사건은 버퍼로 돌아간다. `principal_ref` 는 설정된 토큰 id, 없으면 CORE 프로세스 키 HMAC(`anon-…`) — 해시 앞자리는 후보 토큰 확인에 쓰일 수 있어 내지 않는다.

## 후속 (2026-10-03)

D-438(Accepted 2026-10-03)이 §2 의 "관제 운영자 권한 이상이 답한다"를 Fleet 판단기(규칙 → 비전 모델 → 사람, CORE `stuck_resolver` 역할)로, Fleet 쪽 구현 메모의 영상 해석을 "판단 한 번에 미리보기 한 장, 저장·중계 없음"으로 고친다. 다섯 답과 CORE 재검사는 그대로다.

**개정 (2026-10-07, [D-492](D-492-lane-junction-bounded-turn-and-junction-defaults.md) 결정 개정 2항):** `recovery_local_enabled` 로봇 기본값은 `true`다(`rosy_default.yaml`). 모델 PC SIM 한 바퀴와 실기 차선 한 바퀴를 통과한 페이로드만 robots에 간다. 되돌리기는 CORE 설정 겹의 `line_follow.recovery_local_enabled: false`다. 사용자 결정(2026-10-07)에 따라 이 기본값은 이 ADR의 자율 로컬 후진도 켠다. 대상은 URDF 몸 기하가 있는 모든 로봇이다. 결정 3항과 설정 문단의 "기본 꺼짐, self-mask 측정 뒤 로봇별로 켬" 조건은 D-492의 승격 규칙으로 바뀐다(D-492 결정 개정 5항).
