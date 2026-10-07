## D-503 자율 사슬은 다섯 층이다 — 모델은 출처와 나이가 붙은 사실만 내고, 규칙이 고르고, CORE가 확인하며, 운용 판단 요청은 Fleet 예외 큐 하나로 오른다

**Status:** Proposed (2026-10-07; 계획 `.omc/plans/2026-10-07-rosy-autonomy-chain-plan.md` 2단계, ralplan 합의). 문서만이다. Proposed D-361에 6항을 덧붙인다(등록 로봇의 추가 `stuck_resolver` 자격). 구현은 3단계 `feat/d438-enrolled-resolver-credential`이고, 이 ADR은 그 배포·코드 발급·`--stuck-resolver` 켜기·D-407 local recovery 켜기를 승인하지 않는다. CORE·제어 코드·프로토콜 필드·`/cmd_vel` 경로·안전 계층(D-430)은 바꾸지 않는다.

잇는 결정: [D-438](D-438-fleet-stuck-resolver-rules-model-human.md)(판단기 규칙 → 모델 → 사람) · [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)(비전 단계, 이 ADR과 같은 날 개정) · [D-493](D-493-fleet-console-map-first-layout.md)(예외 규칙 하나) · [D-495](D-495-lane-junction-bounded-turn-and-junction-defaults.md)·[D-498](D-498-junction-turn-site-basis.md)(현장이 정하고 로봇이 확인) · [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(등록) · [D-407](D-407-lane-stuck-recovery-console-then-local.md)(막힘 질문)

### Context

1. **막힘은 보이지만 기록되지 않는다.** `LineStuckBoard.observe`(`operations/fleet/fleet/server/line_stuck.py`)는 1 s 폴링 상태의 `line_follow.stuck`을 메모리에만 둔다. 남는 것은 답 표 `fleet_line_stuck_answers`뿐이고 현장 DB에서 0행이다. 로봇이 스스로 푼 막힘, trip 중이라 판단기가 건너뛴 막힘은 어디에도 없다. 그래서 사람에게 가는 일의 양을 잴 분모가 없다.
2. **등록 로봇에는 판단기 자격이 없다.** D-438 구현 메모대로 판단기 클라이언트는 `robots.yaml`의 `resolver_token`으로 시작할 때 한 번 만들어진다. D-361 등록은 operator 코드만 받고, `robot_enrollments`는 `robot_id`가 PRIMARY KEY인 자격 칸 하나다. 현장의 두 로봇(8kcn·9dfk)은 등록 로봇이므로 막힘은 모두 `no_resolver_token`으로 사람에게 간다.
3. **1단계 규칙은 거의 발화하지 않는다.** R2·R3는 `recovery_local_enabled`가 켜졌을 때만 후보이고 CORE 기본은 꺼짐이다(D-438 §2). 남는 것은 R1(앞에 동료 로봇)과 meet뿐이다.
4. **사실 계약에 쓰는 쪽이 없다.** `operations/world/src/rosy/world/api/observation.py`의 `ObservationSnapshot`은 Fleet가 쓰지 않는다. 실제로 쓰이는 사실 모양은 `operations/fleet/fleet/localization/map_pose.py`의 `MapPose`(`state`, `source`, `age_s`, `anchor_age_s`)다.
5. **VLM 실험(2026-10-07, 정지 프레임 47장, 사람 라벨 없음).** 녹화 7회차(8kcn·9dfk, 2026-09-27~10-01)에서 정지 순간 47장을 뽑아 `qwen3-vl:8b-instruct`(Ollama, 이 노트북 CPU, 장당 약 60 s)에 물었다.
   - v1 결정을 물음(`{decision, reason, confidence}`): 47장 모두 `BACK_AND_RETRY` 0.95. 입력과 무관한 답이다.
   - v2 "앞 30 cm 바닥에 무엇이 있나"(`ahead-class/1`): LiDAR 0.24 m 앞의 벽을 `nothing` 0.95라 했다. 카메라가 낮고 수평이라(높이 약 6 cm) 앞바닥 판단이 어렵다.
   - v3 LiDAR가 거리를 주고 정체만 물음(`lidar-identity/1`): LiDAR가 0.25 m 안을 막힘으로 본 11장에서 `wall` 10, `object` 1. 그럴듯하지만 사람 라벨이 없어 정확도는 모른다. 나머지 36장은 LiDAR 경로가 비어 묻지 않았다.
   - 결론: 막힘의 존재와 거리는 LiDAR가 잰다. VLM에서 쓸 수 있는 것은 그 막힘 안의 정체 하나다.
6. **녹화 위치 표시는 이미 있다.** `learning/training/perception/dataset/stuck_markers.py`가 CORE 사건으로 막힘 구간을 표시한다.

### Decision

1. **사슬은 다섯 층이고, 층마다 소유자가 하나다.** 층은 아래 층에 명령하지 않고, 위 층에 사실·상태만 올린다. 행동의 선택은 Supervisor, 실행과 마지막 확인은 CORE다.

   | 층 | 하는 일 | 소유 경로 | 내는 것 |
   |---|---|---|---|
   | Perception | 센서·카메라에서 사실을 만든다 | 로봇 `middleware/perception`(차선 관측·센서 증거), 현장 `operations/vision`(Rosy Cam 자세, D-257), 오프라인 `learning/training/perception`(초안·학습) | 사실(2항) |
   | World State | 사실을 모으고 나이를 매긴다 | `operations/fleet/fleet/localization/map_pose.py`(`MapPose`), Fleet 상태 스냅샷(`operations/fleet/fleet/server/console.py`). `operations/world`는 두 번째 소비자가 생길 때 연결한다 | 로봇별 사실 묶음 |
   | Autopilot Supervisor | 사실로 규칙표를 돌려 답을 고르고, 못 고르면 큐에 올린다 | `operations/fleet/fleet/server/stuck_resolver.py`·`stuck_resolver_loop.py`·`line_stuck.py`, `trip_runner.py` | 막힘 답, trip 지시, 에피소드 기록 |
   | Skill | 정해진 짧은 동작을 하고 스스로 멈춘다 | CORE `middleware/core/services/core_features/line_follow/`(`stuck_recovery.py`, `junction.py`) | 동작 상태·거절 사유 |
   | Planner/Control | 경로를 계획하고 최종 명령을 낸다 | 경로 `operations/fleet/fleet/routing`(D-490), 제어 CORE `middleware/core/gateway`(유일한 최종 `/cmd_vel`, D-2·D-18) | `cmd_vel` |

   안전(D-430)은 이 사슬 밖의 별도 관심사다. 어느 층도 안전 판정을 넘지 않는다.
2. **사실의 최소 필드는 MapPose 모양이다.** `value`, `source`, `observed_at`, `age_s`, `state`.
   - `MapPose` 대응: `value` = (`x`, `y`, `yaw`), `source` = `sighting`|`bridged`, `age_s`, `state` = `LOCALIZED`|`DEGRADED`|`UNKNOWN`. `observed_at`은 MapPose에서는 앵커 sighting의 `captured_at`이다. 새 사실 공급자는 `observed_at`을 명시한다.
   - 규칙은 `state`가 쓸 수 있는 값이 아니거나 `age_s`가 그 규칙의 한도를 넘은 사실을 쓰지 않는다. 그런 막힘은 사실이 없는 것으로 보고 예외 큐로 간다.
   - 일반 사실 클래스나 서비스는 지금 만들지 않는다. 필드 이름만 정한다. 두 번째 소비자가 생기면 `operations/world`에 계약을 둔다.
3. **운용 판단 요청이 오르는 Fleet 표면은 예외 큐 하나다(D-493 `attentionItems`). 로봇 화면의 직접 처리는 D-407대로 남는다.**
   - 자동으로 풀린 막힘은 에피소드 기록(7항)에만 남고 큐에 오르지 않는다.
   - 큐에 오르는 것: 판단기가 `ESCALATE`한 막힘(D-438 상승 사유와 함께), 오래된 사실(4단계 `fix/d493-attention-stale-state`가 상태 나이를 붙인다), 지금의 D-493 항목.
   - 새 알림 화면이나 별도 사람 승인 화면을 만들지 않는다. 학습 라벨 검수(D-462·D-475)는 운용 큐가 아니라 오프라인 작업이다.
4. **현장이 고르고, 로봇이 확인한다(D-495·D-498의 일반화).**
   - Fleet(현장)은 지도·로스터·다른 로봇 위치처럼 현장만 아는 것으로 답·목표·매개변수를 고른다. 예: 교차로 `turn_deg`(D-495), 막힘 답(D-438), 현장 수용 선언(D-498).
   - CORE(로봇)는 자기 센서로 다시 판정하고 거절할 수 있다(D-407 §2 재검사, D-498 `turn_basis_lost`). 거절은 기록되고 Fleet은 우회하지 않는다.
   - 안전은 이 분담 밖이다(D-430). 현장 선언은 안전 판정을 대신하지 않는다.
5. **모델의 자리.** 판단 모델은 사실 공급자다. 결정은 규칙표가, 실행은 CORE가 한다.

   | 모델 | 자리 | 내는 것 | 근거 |
   |---|---|---|---|
   | VLM(`qwen3-vl` 등) | 현장 Perception, LiDAR가 확인한 막힘 안에서만 | 정체 사실 `wall`\|`object`\|`robot`\|`person`\|`unknown` + `source='vlm'`, `age_s`, 신뢰도 | D-492(개정), 1항 실험 |
   | SAM 3 / Qwen 점 | 오프라인 learning | 라벨 초안(미승인) | D-465 §5·추가 조항 2026-10-07 |
   | judge(L0 IoU 등) | 오프라인 learning | 검수 대기열 순서, "불일치" 표시 | D-465 §5, D-475 §7 |

   어느 모델도 막힘 답, 라벨 승인, 평가 정답, Motion Intent, 이동·정지 명령을 내지 않는다(D-326 §2, D-392 §4, D-442의 금지 항목 3).
6. **Proposed D-361에 덧붙임: 등록 로봇은 `stuck_resolver` 자격을 하나 더 가질 수 있다.**
   - 새 표 `robot_enrollment_credentials`(`robot_id` → `robot_enrollments(robot_id)` `ON DELETE CASCADE`, `role`, `state`, `token_id`, `expires_at`, `fleet_expires_at`, `warn_at`, `ciphertext`, `created_at`, PRIMARY KEY(`robot_id`, `role`))에 둔다. operator 자격은 `robot_enrollments`에 그대로 둔다.
   - `stuck_resolver` 코드는 같은 `robot_id`의 operator 등록이 이미 있을 때만 받는다. `administrator` 코드는 계속 거절한다.
   - 봉인은 operator(`rest`)와 다른 slot `resolver`를 쓴다. 이 자격의 401은 그 행만 `needs_new_code`로 바꾸고 operator 행과 로봇 게이트는 건드리지 않는다.
   - 해지는 operator 토큰과 resolver 토큰을 둘 다 로그아웃 시도한다(resolver 쪽은 최선 노력).
   - 판단기는 클라이언트 목록을 막힘마다 다시 읽는다. 시작 뒤 등록한 자격도 쓰인다. `robots.yaml`의 `resolver_token`이 같은 로봇에 있으면 그쪽이 우선이다.
   - 토큰 자동 갱신은 하지 않는다(CORE 엔드포인트 없음). 7일(168 h)마다 사람이 다시 발급한다.
7. **막힘 에피소드 기록.** Fleet은 막힘마다 한 행을 `fleet_line_stuck_episodes`(`fleet_line_stuck_answers`와 같은 `--tasks-db` 파일, 1단계 `feat/d407-stuck-episode-log`)에 남긴다. 열: `robot_id`, `stuck_id`(둘이 UNIQUE), `source`(`fleet_poll`, 폴링 해상도 ±1 s), `cause`(`obstacle_ahead`|`lane_lost`), `phase_at_open`, `local_enabled_at_open`, `trip_busy_at_open`, `peer_ahead_at_open`, `opened_at`, `closed_at`, `held_s_max`, `attempts_max`, `close_reason`(`cleared`|`replaced`|`left_roster`|`fleet_restart`), `resolved_by`(`rule`|`human`|`<tier>_unconfirmed` 곧 `rule_unconfirmed`·`human_unconfirmed`(CORE 수락 여부를 모르는 답)|NULL), `resolved_principal`, `last_answer_tier`, `escalation_code`, `pose_x`, `pose_y`, `pose_yaw`, `pose_state`, `pose_age_s`. 자동화율과 아래 트리거는 이 표로만 잰다.
8. **데이터가 먼저다.** 순서: (1) 에피소드 기록 → (2) 이 ADR과 D-492 개정 → (3-0) 커버리지 판단 → (3) 등록 로봇 resolver 자격과 1단계 규칙 켜기(로봇 하나씩) → (4) 큐 신선도 → (5) 게이트 뒤 지도 투영 라벨 초안(D-497 Accepted, trip 밖 MapPose 기록). 실제 막힘 분포를 보기 전에는 2단계 모델도 일반 사실 계약도 만들지 않는다.
   - 3-0: `tier1_share`(동료가 앞에 있는 앞 장애물 + local recovery가 켜진 동료 없는 막힘, trip이 아닌 막힘 수로 나눔, 상한 추정)와 `obstacle_upper_bound`가 둘 다 0.05 미만이면, 3단계는 로봇별 D-407 `recovery_local_enabled` 켜기(별도 사용자 승인) 없이는 사람 일을 줄이지 못한다고 판정한다.
9. **VLM 정체 사실의 트리거.** 에피소드가 3 운행일 이상 쌓이고 3단계를 켠 뒤, 아래 `share` ≥ 0.20이고 `n` ≥ 20이며, 그 앞 장애물 표본 10건 이상을 사람이 보아 정체를 알면 규칙이 다른 답을 냈을 경우가 절반 이상일 때만 D-492의 구현을 연다.

   ```sql
   WITH human AS (
     SELECT * FROM fleet_line_stuck_episodes
     WHERE close_reason <> 'fleet_restart' AND COALESCE(trip_busy_at_open, 0) = 0
       AND COALESCE(escalation_code, '') <> 'no_resolver_token'
       AND (resolved_by = 'human' OR (resolved_by IS NULL AND escalation_code IS NOT NULL)))
   SELECT CAST(SUM(cause = 'obstacle_ahead' AND local_enabled_at_open = 1
                   AND escalation_code = 'no_rule') AS REAL) / NULLIF(COUNT(*), 0) AS share,
          COUNT(*) AS n
   FROM human;
   ```

   `no_resolver_token`은 자격 문제라 정체를 알아도 바뀌지 않으므로 뺀다. local recovery가 꺼진 로봇의 동료 없는 앞 장애물은 구조상 모두 `no_rule`이라 신호가 아니므로 켜진 경우만 센다. `meet` 상승은 원인이 이미 동료 로봇이라 뺀다.

### Alternatives

- **A′ 판단기 먼저, `fleet_line_stuck_answers`로 측정.** 답 없는 막힘(스스로 풂, 로봇 화면에서 처리, trip 중 건너뜀)이 빠져 분모가 없다. `local_enabled`가 꺼져 있어 측정되는 것은 대부분 `no_rule` 상승이다.
- **A″ resolver 토큰을 `robots.yaml`에.** 등록 로봇과 같은 id면 `ROBOT_ID_CONFLICT`다. 두 로봇을 정적 로봇으로 되돌려야 하고 D-361 주소 추적과 TLS 바인딩을 잃는다. yaml은 시작할 때만 읽어 주 1회 갱신마다 Fleet 재시작이 필요하다.
- **`robot_enrollments`에 칸 하나 더.** PRIMARY KEY가 `robot_id`이고 봉인 slot이 `rest` 하나라 역할별 상태·만료·401 격리를 따로 둘 수 없다.
- **B 큰 설계 먼저(일반 World State 계약).** 쓰는 쪽 없는 계약(`ObservationSnapshot`)이 하나 더 생기고, 데이터 없이 문턱을 정하게 된다. 층 이름과 경계만 이 ADR이 가져온다.
- **C VLM이 막힘 답을 고른다(D-492 원안).** 실험 v1에서 47/47이 같은 답이었다.

### Consequences

- 사람에게 가는 일이 처음으로 측정된다. 자동화율의 분모는 에피소드 표다.
- 등록 로봇도 판단기 답을 받을 수 있게 된다. 대신 resolver 자격을 7일마다 사람이 다시 발급한다.
- 3단계의 실효는 D-407 local recovery 승인에 달려 있을 수 있다(3-0).
- VLM은 측정된 수요(9항) 뒤에만 들어오고, 들어와도 사실 하나다. D-492가 이에 맞게 개정된다.
- 일반 World State 계약은 늦어진다. 5단계는 trip 밖 MapPose 기록이 없으면 열리지 않는다.
- 후속: CORE 토큰 갱신 ADR(3단계 운영 2주 뒤 판단), 로봇별 local recovery 결정, trip 밖 MapPose 기록, 등록 로봇의 hub 연결 여부.

### Verification

- 이 ADR은 문서다. `python tools/harness/rosy_harness.py lint` 통과는 구조 기록의 증거일 뿐이다.
- 1단계: 에피소드 열기·닫기·재시작·`resolved_by` 판정의 호스트 시험(계획 1단계 수용 기준).
- 3단계: 시작 뒤 등록한 자격으로 R1 막힘이 `tier='rule'`로 답되고 에피소드가 `resolved_by='rule'`이 된다. 401 격리, 해지 CASCADE, 이동 추적 뒤 새 주소. 실기는 사용자 승인 뒤 한 대씩.
- 7항과 9항의 SQL은 현장 DB에서 그대로 돈다(열 이름이 1단계 스키마와 같다).

**Related:** D-2, D-18, D-257, D-326, D-361, D-392, D-395, D-407, D-430, D-438, D-442, D-462, D-465, D-475, D-490, D-492, D-493, D-495, D-497, D-498.
