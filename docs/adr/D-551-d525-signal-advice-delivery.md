## D-551 D-525 신호 참고(advice) 전달 — Fleet이 trip 주기마다 `POST /line-follow/advice`로 밀고, CORE는 먼저 보여 주기만 한다

**Status:** Accepted (2026-10-09, 사용자 결정 J3 "표시 먼저"). 먼저 표시만 한다. 참고로 속도를 낮추는 것(9항)은 뒤에 따로 **Safety-Review**를 받고 기본 꺼짐으로 연다. 계획은 `.omc/plans/fleet-robot-contract.md` rev 3.1이다.

잇는 결정: [D-550](D-550-fleet-robot-communication-contract.md)(Fleet↔로봇 통신 계약: 네 종류, 시간 기준, 순서, 운반 경로) · [D-525](D-525-virtual-signal-fleet-zone-gate.md)(가상 신호등, 로봇은 신호 색을 참고로 읽고 진입은 통행권만 정한다) · [D-517](D-517-multi-robot-lane-traffic.md) 4항(CORE 통행권) · [D-337](D-337-robot-signal-source-measured-light.md)(신호 주장은 허가가 아님) · [D-407](D-407-lane-stuck-recovery-console-then-local.md)(막힘 래치) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 정지) · [D-500](D-500-measured-motion-response-and-clearance-budget.md)(움직임 응답, 바퀴 데드밴드).
고치는 결정: D-525 "CORE가 묻는 길"을 정한다. (a) CORE가 Fleet REST를 부르는 것도, (b) 하트비트 답만 쓰는 것도 아니고 Fleet REST 밀기가 먼저다. 하트비트 답은 페어링한 로봇의 뒤 단계다(D-550 6항).

### Context

- D-525 앞 신호 정보는 Fleet에만 있다. `GET /api/fleet/traffic/signals/ahead/{robot_id}`(`operations/fleet/fleet/server/trip_routes.py:180-186` → `lane_traffic.py:354-362`)가 `{robot_id, signal_id, approach, distance_m, may_enter, lamp, left_s, green_in_s, exact, virtual, advisory}`를 준다. 남은 초는 `signal_phase.forecast`(`fleet/traffic/signal_phase.py:101-`)다.
- 로봇이 쓰기에는 `pose_stamp`, `leg_id`, `ttl_s`, `seq`, `map_version`이 없다. `distance_m`은 계산한 자세에서만 맞다.
- 현장 로봇은 허브에 페어링되지 않아 하트비트 답으로는 닿지 않는다(D-550 Context). CORE에는 Fleet REST 클라이언트가 없다.
- 통행권은 이미 같은 trip 주기에 같은 앞 끝 `front_d_m`·`pose_stamp`로 나간다(`fleet/traffic/trip_authority.py:36,50-69`, 한 전송만 진행, 재시도 없음, 한도 1.5 s).
- 차선 속도 상한 `linear_ceiling`은 `safety.limits.manual_linear`(`middleware/core/gateway/core/line_follow_wiring.py:170`)이고 막힘 후진, 차선 호, 교차로 접근, 차선 복귀도 읽는다(`stuck_recovery.py:319-429`, `lane_arc.py:113`, `junction/approach.py:227`, `lane_return_decision.py:57,91`).
- 막힘 감지는 "진척 없음"을 입력으로 받지 않는다. `obstacle_ahead`(`_blocked_since`가 `obstacle_escalate_s` 5 s 이어짐, `middleware/core/services/core_features/line_follow/manager.py:301-307`)와 `lane_lost`(`_lost_latched`, `line_follow/recovery/stuck_wiring.py:249-252`)에서만 열린다.

### Decision

1. **종류는 참고다(D-550 2항).** 만료하면 "모름"이다. 로봇을 움직이지 않는다. 통행권 끝을 넘게 하지 않고, HOLD·EXPIRED에서 출발·재개시키지 않고, TTL을 늘리지 않고, D-337 `traffic_policy`에 들어가지 않는다. `unknown`은 `green`이 아니다. `may_enter`는 표시용 복사본이고 허가가 아니다.

2. **CORE 계약(추가).** `POST /api/v1/line-follow/advice`(Operator, 통행권과 같은 토큰). 공유 schema는 `core_common.protocol.line_advice`(새 모듈)다.

   ```
   {
     advice_id:   str 1–128,
     leg_id:      str 1–128,          # D-517 통행권과 같은 trip 구간 id
     seq:         int ≥ 0,            # (로봇, 구간)마다 증가
     fleet_epoch: str 1–64,           # Fleet 시작 때 무작위, 기록용
     pose_stamp:  float > 0,          # CORE odom_pose.stamp 그대로
     ttl_s:       0 < s ≤ 2,
     signal: {
       signal_id: str, approach: str,
       stop_m:    float,              # pose_stamp 자세의 앞 끝 → 정지선, 경로 미터. 음수면 이미 안
       lamp:      green|yellow|red|unknown,
       left_s:    float|null, green_in_s: float|null,
       exact:     bool,
       may_enter: bool                # 표시만, 허가 아님
     } | null,                        # null = 앞에 신호 없음, 저장된 참고를 지운다
     map_version: str, route_rev: str
   }
   ```

   범위 밖·누락은 400 `VALIDATION_ERROR`. 차선 주행이 꺼져 있으면 409 `LINE_FOLLOW_NOT_ACTIVE`. 응답 `{accepted: bool, reason?}`(`stale`·`duplicate`). 통행권의 자세 검사 409(`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE`·`AUTHORITY_ODOM_STALE`)와 같은 규칙과 같은 이름을 쓴다.

3. **CORE 저장소 하나(`AdviceStore`).**
   - 받은 순간부터 CORE 차선 시계(통행권 `ttl_s`와 같은 시계)로 `ttl_s`를 잰다.
   - 순서는 D-550 4항: 저장된 항목이 만료 전이고 같은 `leg_id`이면 `(pose_stamp, seq)`가 더 오래된 것은 버린다(`stale`), 같은 것은 무시한다(`duplicate`). 만료 뒤나 구간이 바뀐 뒤에는 다음 유효한 참고를 받는다(시계가 뒤로 튄 경우).
   - 다시 재기: `stop_now = stop_m − (pose_stamp 뒤 odom 경로 길이)`. 통행권 odom 기록을 같이 쓴다.
   - 버림: TTL, 구간 변경, odom 궤적 변경, 모드 변경, E-stop. 버린 참고는 `lamp: unknown`이다.
   - 운반 경로는 `advice.source: rest|heartbeat`로만 기록한다. 저장소는 경로와 관계없이 하나다.

4. **노출.**
   - `GET /api/v1/line-follow`와 상태 스냅숏 `line_follow`에 선택 키 `advice {state: fresh|expired|none, signal_id, approach, stop_now_m, lamp, left_s, green_in_s, exact, age_s, source}`. 참고를 받은 적이 없으면 키가 없다.
   - 가능하면 로봇 얼굴(face-inputs·LCD)에 등과 남은 초를 한 줄로 보인다. 화면 문구와 자리는 구현 때 정한다. 비상 정지·복구 표시(D-546)가 먼저다.
   - 기록: 만료 구간마다 로그 한 줄, `advice_dropped{reason}` 계수.

5. **능력.** CORE는 `rosy.controls/1`에 `line_follow_advice: true`를 알린다. 없으면 Fleet은 보내지 않는다.

6. **Fleet `AdviceSender`.**
   - 켜는 조건: 사이트 설정 `fleet.traffic.signal_advice: true`(기본 false) **그리고** 로봇 능력 `line_follow_advice`. 통행권 설정과는 독립이다.
   - 통행권과 **같은 trip 주기**에, 블록 표가 쓴 같은 `front_d_m`·`pose_stamp`로 만든다. 그래서 참고와 통행권이 같은 자세를 말한다.
   - **통행권을 늦추지 않는다.** 통행권을 먼저 보낸다. 그 로봇의 통행권 전송이 아직 진행 중이면 그 주기의 참고는 건너뛴다. 참고는 자기 전송 자리 하나, 재시도 없음.
   - 바뀔 때, 그리고 적어도 `ttl_s/2`마다 보낸다. 자세 점프 보호가 그 로봇을 UNKNOWN(`waiting_for: pose_jump`)으로 둔 주기에는 보내지 않는다.
   - 로봇마다 보내는 쪽은 하나다(D-550 6항). 이 단계는 REST만이다. 하트비트 답 경로는 페어링(D-550 11항) 뒤 단계다.
   - `GET …/signals/ahead/{id}`에 `pose_stamp`, `leg_id`, `computed_at`, `map_version`, `route_rev`를 더한다(관제가 데이터 나이를 보인다).
   - 관찰: `/api/fleet/traffic`에 로봇마다 `advice_age_s`와 통행권·참고 전달 p50/p99. 통행권 p99가 참고 전과 비교해 나빠지면 참고에 따로 클라이언트나 한도를 준다(`transport.py:209`, 로봇마다 `AsyncClient` 하나).

7. **import-lint와 성질 시험.**
   - `middleware/core/services/core_features/line_follow/authority.py`가 `line_advice`나 참고 저장소를 import 하면 시험이 실패한다(지금은 `core_common.protocol.line_authority`만, `authority.py:12`).
   - 성질 시험: 모든 입력에서 통행권 판정 결과는 참고가 있든 없든 같다.

8. **이 단계(표시)에는 Safety-Review가 없다.** 움직임에 영향이 없다. 위 import-lint와 성질 시험이 필수다.

9. **뒤로 미룬 속도 상한(Safety-Review, 기본 꺼짐).** 붉은·노란 등에서 정지선이 가까우면 일찍 천천히 간다. 정지가 아니다. 정지는 여전히 통행권 끝이다. 다음 불변식을 지킨다.
   - **마지막 min 클램프다.** `linear_ceiling`은 바꾸지 않는다. 차선 주행 결정의 마지막 단계에서 한 번 `decision.linear = min(decision.linear, max(cap, v_floor))`. 대입이 아니라 `min`이라 D-422 몸체 정지나 HOLD가 낸 0은 0으로 남는다.
   - **`v_floor` ≥ 측정한 바퀴 데드밴드**(D-500). 아니면 0보다 큰 상한이 HOLD 보고 없이 로봇을 세울 수 있다. 시작 검사: `v_floor` < 설정 데드밴드이면 설정 오류다.
   - **그 구간의 통행권을 쥐고 있을 때만.** CORE 통행권 상태가 `FREE` 또는 `HOLDING`(`authority_odom_stale` 이유 포함)이고 만료 전이며 `leg_id`가 참고와 같을 때만 상한을 쓴다. `EXPIRED`, `NONE`, 구간 변경, 통행권을 받은 적 없음이면 표시만이다. Fleet의 `traffic_authority`가 아니라 CORE 쪽 조건이다.
   - **D-407 래치를 쓰지 않는다.** 상한 경로는 `_blocked_since`, `_obstacle_hold`, `_escalated`, `_lost_latched`를 쓰지 않고, HOLD나 결정을 만들지 않는다. 실제 장애물과 차선 잃음은 지금 경로 그대로다.
   - **몸체 정지는 0으로 남는다.**
   - 시험: 몸체 정지 + 붉은 참고 → 선속도 0. 막힘 후진·교차로 접근·차선 호 속도가 참고 있을 때와 없을 때 같다. 붉은 참고로 30 s 상한, 장애물 없음 → `_escalated` 거짓, `nav.line_stuck_opened`·후진 없음. 상한 중 실제 장애물 → `obstacle_escalate_s`에 지금처럼 올라감. 상한 중 차선 잃음 → `_lost_latched` 그대로. 통행권 없이 참고 → 상한 없음, 같은 구간 통행권을 쥐면 상한, 통행권 만료 뒤 다시 없음.

10. **이행 순서.**

    | 단계 | 무엇 | 검토 | 되돌림 |
    |---|---|---|---|
    | 1 | `signals/ahead` 메타데이터(Fleet만) | 없음 | 되돌림 |
    | 2 | 공유 schema, CORE 엔드포인트·저장소·표시, 능력 `line_follow_advice` | Safety-Review 없음(움직임 없음), import-lint·성질 시험 필수 | 쓰지 않으면 무해. Fleet이 보내지 않음 |
    | 3 | Fleet REST 송신기, `fleet.traffic.signal_advice` 뒤 | 없음(참고만) | 설정 false |
    | 4 | 9항 속도 상한(기본 꺼짐) | **Safety-Review** | 설정 꺼짐 |
    | 5 | 페어링한 로봇의 하트비트 답 경로 | D-550 11항 뒤 | 경로 선택을 REST로 |

### Alternatives

| 대안 | 판단 |
|---|---|
| 참고를 통행권 POST의 선택 필드로 | 기각. 안전 검토를 받는 schema에 허가와 참고가 섞이고 `hold_back` 로봇은 받지 못한다(D-550 O4) |
| CORE가 `signals/ahead`를 폴링(D-525 (a)) | 기각. 새 인증 방향(D-474 41행), 폴링 지연, `pose_stamp` 없음(D-550 O3) |
| 하트비트 답만(D-525 (b)) | 지금 현장은 페어링되지 않아 닿지 않고 1 Hz다. 페어링 뒤 둘째 경로로 둔다 |
| 바로 속도 상한까지 | 미룸(J3). 막힘 래치·몸체 정지·데드밴드와 얽혀 Safety-Review가 먼저다 |
| 상한을 `linear_ceiling`을 낮춰서 | 기각. 막힘 후진·차선 호·교차로 접근·차선 복귀도 그 값을 읽어 함께 느려진다 |

### Consequences

- 로봇 화면과 `GET /line-follow`에 앞 신호와 남은 초가 보인다. 움직임은 바뀌지 않는다.
- trip 로봇마다 주기 POST가 하나 는다(로봇당 약 2/s). 통행권 p99를 참고 전후로 잰다.
- 속도 상한은 9항 Safety-Review 전에는 없다. 그때까지 정지선 앞 감속은 통행권 끝의 d_stop뿐이다.
