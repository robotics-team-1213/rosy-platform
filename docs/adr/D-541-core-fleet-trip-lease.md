## D-541 CORE는 Fleet trip이 로봇을 쥐고 있음을 안다 — TTL 있는 trip lease, 다른 화면의 수동 조종은 거절하거나 명시적으로 넘겨받고, 모드를 떠나면 trip이 끝난다

**Status:** Proposed (2026-10-09, 사용자 결정 ③ "CORE trip 소유는 별도 ADR"). CORE 계약 변경이고 안전 경로라 **Safety-Review 대상**이다. SOURCE 구현, API Reference 행, SIM, DEVICE 수용은 각각 따로다. 구현은 `docs/plans/2026-10-09-fleet-console-v2.md` (i) 브랜치다.

**부분 개정:** [D-460](D-460-no-pilot-seat-lease-ownership-stays.md) 결정 1의 "조종 소유권은 세 어휘(링크·수락 teleop·보정 lease)"에 네 번째 어휘 **trip lease**를 더한다. D-460이 거절한 Pilot 운전석 임대(`/teleop/seat`, 사람 운전자 사이의 소유)는 여전히 만들지 않는다(아래 "D-460과의 관계").

잇는 결정: [D-2](D-2-cmd-vel.md)/[D-18](D-18-rosy-core.md)(CORE만 최종 `cmd_vel`) · [D-321](D-321-attended-calibration-g4-mapping.md)(보정 lease) · [D-411](D-411-pilot-robot-recording-control-descriptor-and-gripper.md)(녹화 수호자 `seat_changed`) · [D-430](D-430-safety-as-a-separate-concern.md)(안전 체인) · [D-442](D-442-motion-intent-and-device-control-port.md)(Motion Intent, U1) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 5항(trip 루프) · [D-517](D-517-multi-robot-lane-traffic.md) 4항·M2(CORE 통행권) · [D-540](D-540-fleet-console-structure-v2.md)(콘솔 구조 v2).

### Context

2026-10-09 기능 감사(`X:\DevTemp\fleet-ui-audit\features.md` "Ownership finding", local main `59f8427c1`)가 코드에서 읽은 것이다. 재현하지 않은 추론이다.

- **Fleet 쪽은 막혀 있다.** `trip_guard`가 목표·대형·차선 주행을 감싸고, `/goal`·`/route`가 `trip_busy`를 보고, 작업 발행이 trip 로봇을 건너뛴다.
- **로봇 쪽에는 trip 주인이 없다.** `POST /mode MANUAL`은 조건 없이 내비게이션을 취소한다(`api/v1/common.py` `apply_mode`). `/teleop`은 능력, 보정 lease 주인(`require_calibration_owner`), `require_kept`만 본다(`api/v1/control.py`). 로봇 화면이나 Pilot이 trip 중인 로봇을 그냥 가져간다. Fleet trip 루프는 그것을 정체(stall)로만 알아챈다(`trip_runner.py`).
- **반대 방향도 열려 있다.** `require_manual_released`는 `manual_active`일 때만 거절한다. teleop watchdog이 끝나면 거짓이 된다(`core_features/command/manager.py`). 그래서 Pilot이 손을 뗀 직후, 살아 있는 trip의 다음 목표나 차선 주행 요청이 로봇을 다시 NAVIGATION으로 바꿔 몬다. 운전자는 trip이 있는지 모른다.
- 보정 lease(D-321 추가분)는 이미 같은 꼴의 소유를 CORE에 둔다: 부른 토큰이 열고, `ttl_s` 안에 heartbeat로 늘리고, 다른 토큰의 구동·모드 쓰기는 409 `CALIBRATION_ACTIVE`다. 모든 구동 경로가 `require_calibration_owner`를 이미 부른다.

### Decision

1. **trip lease(CORE, API Ref additive + 동작 변경).**
   - `PUT /api/v1/trip-lease`(operator) 본문 `{lease_id, trip_id, holder, operator_name, ttl_s}`. 처음 부르면 연다. 같은 토큰·같은 `lease_id`가 다시 부르면 만료를 늘린다(renew). `holder`는 Fleet 사이트 이름(1–64자), `operator_name`은 trip을 시작한 이름 있는 운영자(D-540 9항, 1–64자, 표시·감사용), `ttl_s`는 1–10 s(기본 5)다.
   - `DELETE /api/v1/trip-lease/{lease_id}`(주인 토큰): 정상 끝. 로봇을 멈추지 않는다(Fleet이 trip 끝에서 이미 `stop`/goal 취소를 보낸 뒤 부른다).
   - `POST /api/v1/trip-lease/takeover`(operator, 주인 아닌 토큰) 본문 `{lease_id, reason}`: 명시적 넘겨받기(4항).
   - 상태 스냅숏 선택 필드 `trip_lease {lease_id, trip_id, holder, operator_name, mode, since, expires_in_s}`(없으면 키 없음)와 끝난 직후 한 번 `trip_lease_ended {lease_id, reason, by}`. 이벤트 `trip_lease.opened|renewed|ended`.
   - 능력 필드 `trip_lease: true`(`rosy.controls/1`)로 Fleet이 지원 여부를 안다.
   - 상태는 메모리에만 둔다. CORE가 다시 시작하면 lease는 없다(그 사이 모드도 IDLE이다).
2. **여는 조건.** 다음이면 409로 거절한다: 다른 토큰의 lease가 살아 있음 `TRIP_LEASED`, 보정 lease가 다른 토큰 것 `CALIBRATION_ACTIVE`, 모드가 MANUAL(`manual_active`와 관계없이) `MANUAL_MODE`, 비상 정지 걸림 `EMERGENCY_ACTIVE`. 즉 **Pilot이 손을 뗀 뒤에도 MANUAL 모드인 로봇은 trip이 가져가지 못한다.** 운영자가 로봇을 IDLE로 둔 뒤(멈춤, 누구나 가능) 새 trip을 시작해야 한다.
3. **lease가 사는 동안 CORE가 하는 것.** 주인 아닌 토큰의 다음 요청은 409 `TRIP_LEASED`이고 `detail {lease_id, trip_id, holder, operator_name, expires_in_s}`를 싣는다: `POST /mode`(MANUAL·NAVIGATION·DOCKING), `/teleop`, `/navigation/goal`, `PUT /line-follow/mode`(켜기), `/line-follow/hold`, `/line-follow/junction`, `/line-follow/authority`, 도킹·언도킹, `POST /calibration/session`. 구현은 이 경로들이 이미 부르는 `require_calibration_owner` 옆에 `require_trip_owner`를 한 줄씩 더하는 것이다. 거절도 D-411 의도 기록(`note_intent`)에 남는다.
   - **늘 열린 것(lease를 보지 않음):** `POST /safety/stop`(비상 정지), `POST /mode IDLE`, `/navigation/cancel`, line-follow 끄기, `/swarm/cancel`, 막힘 결정 중 멈추는 답(WAIT·ABORT). 멈춤은 누구나 한다.
   - 주인 토큰의 막힘 결정 MANUAL·BACK_AND_RETRY는 D-407 규칙 그대로이고 lease와 무관하다(Fleet이 D-540 9항 이름 있는 운영자로 거른다).
4. **명시적 넘겨받기.** 로봇 화면·Pilot이 409 `TRIP_LEASED`를 받으면 "Fleet 운행 중 · {operator_name} · {trip_id}" 문장과 `넘겨받기` 버튼을 보인다. 누르면 `takeover`를 부른다. CORE는 같은 처리 안에서 (a) lease를 끝내고(`reason: taken_over`, `by` = 넘겨받은 토큰의 라벨·역할), (b) line-follow를 끄고 내비게이션을 취소해 IDLE로 둔다, (c) 이벤트를 낸다. 넘겨받은 화면은 그다음에 MANUAL을 따로 요청한다. 넘겨받기와 MANUAL을 한 요청으로 합치지 않는다: 멈춤이 먼저 끝나야 사람이 이어받기 때문이다. teleop이 lease를 조용히 이기는 길(자동 넘겨받기)은 없다.
5. **trip은 로봇이 trip의 모드를 떠나면 끝난다.** lease는 열 때의 운전 방식(`mode`: NAVIGATION 또는 line-follow 켬)을 기억한다. 다음 중 하나면 CORE가 lease를 끝내고 `trip_lease_ended.reason`에 쓴다: 그 모드를 떠남(`mode_left`: IDLE·MANUAL·도킹 전환, line-follow 꺼짐, D-407 ABORT), 비상 정지(`estop`), 넘겨받기(`taken_over`), 만료(`expired`), 주인 DELETE(`released`). D-494 교차로 HOLD, D-517 통행권 정지, 막힘 대기는 모드를 떠나는 것이 아니다.
6. **만료(죽은 Fleet).** 주인이 `ttl_s` 안에 늘리지 않으면 lease가 끝나고(`expired`) CORE는 line-follow를 끄고 내비게이션을 취소해 IDLE로 둔다. 주인 없는 trip을 계속 달리게 두지 않는다(결정). 시계는 보정 lease와 같은 CORE 단조 시계다. 비상 정지 해제는 lease를 되살리지 않는다.
7. **Fleet trip 루프(D-494 5항 개정).**
   - trip 시작 검사에 lease 열기를 더한다. 첫 교차로 지시·목표 전에 `PUT /trip-lease`가 성공해야 한다. 거절은 trip 시작 거절로 그대로 올린다(`TRIP_ROBOT_LEASED`, `TRIP_ROBOT_MANUAL`, `CALIBRATION_ACTIVE`).
   - 루프 주기마다(0.5 s, 늦어도 1 s) 늘린다. `ttl_s`는 5다. 늘리기가 409 또는 404로 lease가 없다고 하면 그 주기에 아무 명령도 보내지 않고 trip을 `stopped(lease_lost: <reason>)`로 끝낸다. **다시 열지 않는다.** 같은 로봇을 다시 몰려면 운영자가 새 trip을 시작한다(이름 있는 운영자). 이것으로 "Pilot이 손을 뗀 뒤 trip이 조용히 다시 모는" 길이 닫힌다.
   - 정상 끝·취소·실패에서 `stop`/goal 취소 뒤 `DELETE`한다.
   - 능력 `trip_lease`가 없는 로봇: 사이트 설정 `fleet.trip_lease_required`(기본 false)가 참이면 trip을 열지 않는다(`TRIP_LEASE_UNSUPPORTED`). 두 시연 로봇의 payload가 이 CORE를 받으면 현장 설정을 true로 바꾸고, 다음 릴리스에서 기본을 true로 바꾼다(결정).
   - 관제 카드(D-540 3항)는 `trip_lease_ended`의 이유를 운행 한 줄에 쓴다. 예: "운행 끝 · 로봇 화면에서 넘겨받음(kim-tablet)".
8. **우선순위(높은 것부터).**

| 순위 | 무엇 | 이 ADR에서 |
|---|---|---|
| 1 | 물리 E-stop, CORE 비상 정지 `/safety/stop` | 언제나 이긴다. lease를 끝낸다(`estop`) |
| 2 | 몸체 정지(D-422/D-424), IR 가드, Safety Guard·D-400, watchdog | 그대로 결정을 0으로 만든다. lease는 이들 위에 아무것도 더하지 않는다 |
| 3 | 멈추는 요청(IDLE, 취소, line-follow 끄기, 멈추는 막힘 답) | 누구나. 모드를 떠나면 lease가 끝난다 |
| 4 | 보정 lease(D-321) | trip lease와 서로 배타적이다. 먼저 연 쪽이 쥔다. 어느 쪽도 다른 쪽을 조용히 뺏지 않는다. 보정 중 trip 열기는 `CALIBRATION_ACTIVE`, trip 중 보정 열기는 `TRIP_LEASED`. 보정은 trip lease를 `takeover`한 뒤 연다 |
| 5 | trip lease | 주인 아닌 움직임 요청을 거절 |
| 6 | 사람 teleop 사이 last-wins(D-411/D-460) | lease가 없을 때만, 그대로 |

9. **D-517 M2 통행권과의 관계.** 통행권은 "얼마나 갈 수 있는가"(≤ 2 s, 앞 끝 거리)이고 lease는 "누가 이 로봇을 쥐는가"다. 통행권 요청은 lease 주인만 보낸다(3항). lease가 끝나면 그 차선 세션의 통행권도 끝난다(모드 변경이 이미 세션을 끝내므로 추가 상태 없음). lease는 움직임을 허가하지 않는다: 통행권이 켜진 로봇은 lease가 살아 있어도 통행권 끝에서 선다.
10. **D-442 Motion Intent와의 관계.** lease는 우선순위 등급표를 바꾸지 않는다. U1(`require_manual_released`, 수동이 살아 있으면 자율 거절)은 그대로 두고, 그 반대 방향(자율 trip이 살아 있으면 수동 거절)을 lease가 맡는다. Motion Intent `source`·`attempt_id`가 생기면 lease의 `trip_id`가 그 trip intent의 `attempt_id`다.
11. **D-430 안전 체인 표.** lease는 안전 층이 아니다. "Arbiter + MANUAL" 행의 소유 규칙에 "Fleet trip lease(D-541): 주인 아닌 움직임 거절, 만료 시 IDLE"을 한 줄 더한다. 안전 판정(정지 거리, 엔벌로프)은 바뀌지 않는다.
12. **API Reference.** 다음 빈 버전 하나에 한 번에 싣는다: 새 경로 세 줄, 스냅숏 `trip_lease`·`trip_lease_ended`, 능력 `trip_lease`, 오류 코드 `TRIP_LEASED`·`MANUAL_MODE`(trip-lease 열기)·Fleet `TRIP_ROBOT_LEASED`·`TRIP_ROBOT_MANUAL`·`TRIP_LEASE_UNSUPPORTED`, 그리고 동작 변경 "lease 동안 주인 아닌 `/mode`·`/teleop`·구동 쓰기 409". envelope 1.0은 그대로다.

### D-460과의 관계

D-460은 사람 운전자 사이의 운전석 임대를 거절했다: (a) D-411 A "CORE has no Pilot seat"과 정면 충돌, (b) 임대 TTL이 watchdog과 같은 현상을 따로 판단, (c) last-wins로 충분. trip lease는 그 셋을 건드리지 않는다.
- 사람 운전자 사이의 소유는 여전히 없다. lease 주인은 기계(Fleet trip)이고 사람끼리는 last-wins다. D-411 `seat_changed` 정의도 그대로다(넘겨받기 뒤 첫 teleop이 바뀐 토큰이면 지금처럼 `seat_changed`).
- lease TTL은 명령 신선도가 아니라 **주인이 살아 있는가**다. 명령 신선도는 watchdog(500 ms)과 통행권 `ttl_s`가 계속 판단한다. 보정 lease와 같은 어휘다.

### Alternatives

| 대안 | 판단 |
|---|---|
| Fleet만 지킨다(지금) | 로봇 화면·Pilot이 Fleet을 거치지 않는다. 감사가 찾은 두 방향 모두 남는다. 기각 |
| teleop이 자동으로 넘겨받음 | 운전자가 trip이 있는지 모르고 가져가며, Fleet은 정체로만 안다. 사용자 결정 "거절 또는 명시적 넘겨받기"와 어긋나 기각 |
| 보정 lease를 trip에도 그대로 씀 | 보정은 `activity: CALIBRATING`을 보이고 의미가 다르다. 경로와 시계 모양만 빌리고 상태는 따로 둔다 |
| 만료해도 로봇은 계속 달림(통행권·교차로 기본 정지에 맡김) | 통행권이 꺼진 사이트(기본)에서는 다음 교차로까지 주인 없이 달린다. 멈춤 쪽으로 정함 |
| lease 없이 `require_manual_released`를 MANUAL 모드 전체로 넓힘 | 반대 방향(trip 중 수동)이 남는다. 2항에 그 넓힘만 포함하고 나머지는 lease로 |

### Consequences

- 로봇 화면·Pilot은 Fleet trip 중인 로봇을 그냥 가져가지 못하고, 누가 왜 쥐고 있는지 본다. 가져갈 때는 넘겨받기 한 번이 멈춤과 기록을 남긴다.
- Fleet이 죽으면 5 s 안에 로봇이 IDLE로 선다. Fleet 일시 지연이 5 s를 넘으면 trip이 끝난다(재시작 시 자동 재출발 없음은 D-494 그대로).
- MANUAL 모드에 남아 있는 로봇에는 trip을 시작할 수 없다. 운영자는 먼저 멈춤(IDLE)을 보낸다. 관제 카드가 그 이유를 말한다.
- 옛 payload 로봇은 `fleet.trip_lease_required`가 false인 동안 지금처럼 lease 없이 trip을 한다(감사가 찾은 틈이 남는다). 두 로봇 갱신 뒤 true로 바꾼다.
- Pilot·로봇 대시보드의 `넘겨받기` 화면은 이 ADR이 정하는 계약을 쓰는 별도 작업이다.

### Validation (Safety-Review 범위)

- CORE 단위: 열기 거절 넷, 주인 renew·DELETE, 주인 아닌 경로별 409와 `detail`, 열린 경로(비상 정지·IDLE·취소)가 lease를 보지 않음, 넘겨받기 = 끝 + IDLE + 이벤트, 모드 떠남 다섯 이유, 만료 → IDLE, 비상 정지 해제 뒤 lease 없음, 보정 lease와의 배타.
- Fleet 단위: 시작 시 열기 실패 → 시작 거절, renew 실패 → `stopped(lease_lost)`와 명령 0, 다시 열지 않음, 끝에서 DELETE, `fleet.trip_lease_required` 분기.
- 통합(가짜 CORE): trip 중 다른 토큰 teleop 409 → takeover → IDLE → Fleet trip 끝(다시 몰지 않음). Pilot이 손 뗀 MANUAL 로봇에 trip 시작 → `TRIP_ROBOT_MANUAL`.
- SIM(모델 PC 또는 관제 PC Gazebo, 이 노트북 금지): 2대 고리 trip 중 Fleet 프로세스 kill → 5 s 안에 두 로봇 IDLE. 통행권 켬과 끔 두 경우.
- DEVICE: 실물 한 대, E-stop을 쥔 사람 옆에서 trip 중 Pilot 넘겨받기와 Fleet 정지. 호스트 pytest 통과는 장치 수용이 아니다.

**References:** `middleware/core/api_web/core_api_web/api/v1/{common.py,control.py,calibration.py,line_follow.py,navigation.py}`, `middleware/core/services/core_features/command/manager.py`, `operations/fleet/fleet/server/{trip_runner.py,trip_ports.py,trip_guard.py}`, `X:\DevTemp\fleet-ui-audit\features.md`.
