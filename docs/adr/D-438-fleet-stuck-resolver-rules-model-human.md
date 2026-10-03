## D-438 막힌 로봇의 판단은 Fleet 판단기가 규칙 → 비전 모델 → 사람 순으로 내린다

**Status:** Accepted (2026-10-03, 사용자 승인; 문서만, 구현·ROS-SIM·DEVICE 는 별도. 처음 제안은 사용자 지시 "콘솔에서 사람이 답하지 말고 알고리즘에 따라 처리하고, 안 되면 사람에게 확인하거나 OpenRouter 비전 모델로 처리", "로봇이 문제가 생기면 fleet 을 호출"). D-407 §2 의 "관제 운영자 권한 이상이 답한다"와, D-407 Fleet 쪽 구현 메모의 "로봇 카메라 영상은 Fleet 이 중계하지 않으므로 화면은 미리보기 순서번호만"을 고친다(§3). 로봇 쪽 막힘 상태기계, 다섯 답, CORE 의 답 재검사(D-407 §2·§4·§5)는 그대로다. Fleet 이 막히기 전에 로봇에 주의점을 알리는 일(사용자 지시 "fleet 이 보고 있다가 미리 주의점을 전달")은 새 하향 통로·로봇의 사이트 좌표 위치·안전 검토(D-430)가 필요해 다음 ADR 에서 정한다. 경로·필드·오류코드는 D-18 에 따라 구현 변경에서 API Reference·typed schema 와 함께 확정한다. 문서만, 코드 변경 없음.

## 배경

- **실주행에서 멈춘 채 끝난다.** 2026-10-03 8kcn·9dfk CAMERA_LINE 실주행(payload 031)은 세 번 모두 멈춤으로 끝났다. `obstacle_ahead` 50 s(옆 로봇이 몸 모서리 4 cm 앞), `LOST camera_reselection_required`(9dfk 가 흰 벽을 선으로 따라감, 8kcn 이 횡단보도에서 선 상실), `camera_observation_stale`(로봇 CPU 과부하). 막힘 질문(D-407)은 열렸지만 아무도 답하지 않아 `WAITING_CONSOLE` 에 머물렀다.
- **Fleet 은 막힘을 브라우저가 열려 있을 때만 본다.** `LineStuckBoard.observe` 는 `GET /api/fleet/state` 안에서만 돈다(`src/site/fleet/fleet/server/console_routes.py`). 콘솔을 아무도 열지 않으면 Fleet 은 막힘을 모른다.
- **답은 사람만 한다.** D-407 §2 는 운영자 권한 이상을 요구하고, `WAITING_CONSOLE` 에는 기한이 없다. 운영자는 대부분 그 자리에 없다(D-407 배경).

## 결정

1. **Fleet 판단기(resolver)를 둔다.** Fleet 서버 안 상시 작업이다. 브라우저 없이 동작한다.
   - **로봇이 Fleet 을 부른다.** 판단기는 FleetAgent 사건 `nav.line_stuck_opened`·`nav.line_stuck_asked` 를 받는 즉시 그 막힘을 맡는다. hub 의 사건 콜백은 하나뿐이고 이미 작업 투영(`task_service.project_core_event`)이 쓰므로, 콜백은 두 곳에 나눠 주고 판단기 일은 웹소켓 처리 밖(별도 작업)에서 한다. 사건은 재시도 뒤 버려질 수 있으므로, 판단기는 로봇 상태(`line_follow.stuck`)를 `resolver_poll_s`(기본 1 s)마다 다시 읽는다. 폴링이 진짜 대비책이다. 같은 `stuck_id` 는 한 번만 맡는다.
   - **답은 기존 경로로 낸다.** `POST /api/fleet/robots/{robot_id}/line-stuck/decision` 이 쓰는 Fleet→CORE REST 중계(`HttpRobotClient.line_stuck_decision`)를 그대로 쓴다. 새 하향 통로를 만들지 않는다.
   - **판단기는 CORE 에 자기 역할로 답한다.** CORE 에 `stuck_resolver` 역할 토큰을 로봇마다 따로 발급한다. 이 역할은 `POST /api/v1/line-follow/stuck/decision` 과 읽기(viewer) API 만 통과하고, 비상정지 해제·모드 변경·보정 lease·제한값 변경은 거부된다. CORE 는 이 역할의 답을 운영자 답과 같은 재검사로 받고, 사건 `by` 에 역할을 남긴다. 기존 로봇 운영자 토큰은 판단기가 쓰지 않는다. Fleet 감사의 주체는 `principal_id = "fleet-resolver"` 다.
   - **보정 세션 중에는 답하지 않는다.** CORE 는 보정 세션(D-321 부록) 중 `RESUME`·`BACK_AND_RETRY`·`MANUAL` 에 보정 lease 를 요구한다. 판단기는 lease 를 갖지 않으므로, 보정 세션 중의 막힘은 바로 사람에게 올린다.
   - **로봇마다 답은 하나씩.** Fleet 은 한 로봇에 한 번에 한 답만 보낸다. 사람이 콘솔에서 그 막힘의 판단 창을 연 순간 막힘은 사람이 맡고, 판단기는 그 막힘에 더 답하지 않는다(사람 답 우선의 방법).
2. **1단계 — 규칙.** 같은 입력이면 같은 답을 낸다. 규칙마다 id 가 있고, 답에 그 id 를 싣는다. 처음 규칙:
   - `R1 peer_ahead`: 원인 `obstacle_ahead` 이고 Fleet 이 아는 다른 로봇의 몸이 막힌 로봇의 앞 경로 띠 안 `resolver_peer_reach_m`(기본 0.30 m) 이내면 `WAIT`. 그 로봇이 비키면 막힘은 CORE 에서 `cleared` 로 스스로 닫힌다(D-407 구현 메모). 판단기는 `RESUME` 을 보내지 않는다. Fleet 이 차선 로봇의 위치를 모르면(D-395·D-257 위치 없음) R1 은 쓰지 않는다.
   - `R2 static_back_off`: 원인 `obstacle_ahead`, 앞 물체가 Fleet 로봇이 아니면 `BACK_AND_RETRY`.
   - `R3 lane_lost_back_off`: 원인 `lane_lost` 이면 `BACK_AND_RETRY`.
   - R2·R3 는 로봇이 로컬 복구를 켰을 때(`recovery_local_enabled: true`, 로봇별 self-mask 측정 뒤, D-407 §5)만 쓴다. 꺼져 있으면 CORE 가 `local_recovery_disabled` 로 거부하므로 판단기는 R2·R3 를 건너뛴다. 판단기 후진은 로봇의 `recovery_max_attempts` 를 로컬 복구와 함께 쓴다. 후진의 뒤 여유·사각·지나온 길 판정은 CORE 가 한다. 막힘 사건의 `rear_state` 는 참고일 뿐이며 판단기는 그것으로 후진을 허락하지 않는다.
3. **2단계 — 비전 모델(OpenRouter).** 사이트 설정으로 켤 때만 쓴다(기본 꺼짐).
   - 입력: 로봇 카메라 미리보기 한 장(판단할 때 로봇의 viewer API 에서 한 번 받는다), 막힘 원인과 여유값, 마지막 차선 관측, 같은 막힘 묶음(§4)에서 지금까지의 답과 CORE 응답, 근처 Fleet 로봇 위치.
   - **D-59·D-407 의 영상 규칙을 이만큼 고친다.** Fleet 은 판단 한 번에 한 장만 요청으로 받아 모델에 보낸다. Fleet 은 그 장을 저장하지 않고, 버스·콘솔·사건에 싣지 않는다. 영상 중계 금지는 그대로다.
   - 외부 전송 조건: 사이트 운영자의 명시적 동의(설정 항목, 기본 꺼짐), OpenRouter 제공자 고정(설정된 제공자만, 대체 경로 금지), 데이터 보관·학습 사용 거부 옵션을 켠 요청만 보낸다. 모델 이름·키는 관제 PC 설정에만 둔다. 저장소·로봇·사건에는 키를 두지 않는다.
   - 출력: 고정 JSON `{decision, reason, confidence}`. `decision` 은 `WAIT`·`BACK_AND_RETRY`·`RESUME`·`ABORT`·`ESCALATE` 중 하나다. `MANUAL` 은 사람만 고른다. 형식이 틀리거나, `confidence` 가 `resolver_model_min_confidence`(기본 0.7) 미만이거나, `resolver_model_timeout_s`(기본 8 s) 안에 답이 없으면 `ESCALATE` 로 본다.
   - `RESUME` 은 원인 `obstacle_ahead` 에서만 고를 수 있다. CORE 는 경로 띠 안 물체가 정지 거리 안이거나 scan 이 오래되었으면 거부한다(D-407 §2). 원인 `lane_lost` 에서 `RESUME` 은 차선 증거 검사 없이 상실 래치를 풀므로 모델은 고르지 못한다(`BACK_AND_RETRY`·`ABORT`·`ESCALATE` 만). 모델이 그래도 `RESUME` 을 내면 `ESCALATE` 로 본다.
   - `BACK_AND_RETRY` 는 2 의 R2·R3 와 같은 조건(로컬 복구 켜짐)일 때만 보낸다. 아니면 `ESCALATE` 로 본다.
   - 같은 막힘 묶음(§4)에 모델 답은 `resolver_model_budget`(기본 2) 개다. 넘으면 3단계로 간다.
   - 로봇이 로컬 복구를 켰으면 ASKING 창(`recovery_ask_s`, 기본 15 s) 뒤 스스로 후진한다. 판단기의 규칙과 모델은 그 안에 끝나야 한다: `resolver_model_timeout_s` 는 `recovery_ask_s` 보다 작아야 하고, 설정 검사가 이를 거부한다.
4. **예산과 기한은 막힘 묶음 단위로 센다.** `stuck_id` 단위가 아니다.
   - 막힘 묶음: 같은 로봇의 같은 차선 추종 세션에서, 앞 막힘이 닫힌 뒤 `resolver_restuck_s`(기본 30 s) 안에 열린 막힘은 같은 묶음이다. 어떻게 닫혔는지(`recovered`·`console_resume`·`cleared`)는 따지지 않는다. 차선 추종 모드가 바뀌면 묶음이 끝난다.
   - 규칙 답은 묶음당 `resolver_rule_budget`(기본 2) 개, 모델 답은 `resolver_model_budget`(기본 2) 개다.
   - **판단기가 `RESUME` 을 보낸 뒤 같은 묶음에서 다시 막히면 판단기는 더 답하지 않고 바로 사람에게 올린다.** 무인 RESUME 반복을 막는다.
   - 기한: 묶음의 첫 막힘을 맡은 뒤 `resolver_escalate_after_s`(기본 60 s) 안에 묶음이 끝나지 않으면 단계와 관계없이 사람에게 올린다.
   - `WAITING_CONSOLE` 에 로봇 쪽 기한은 두지 않는다(로봇은 HOLD 가 안전한 기본값).
5. **CORE 응답의 뜻.**
   - `STUCK_DECISION_REFUSED`(예: 정지 거리 안 물체, 로컬 복구 꺼짐): 그 규칙 또는 그 모델 답 종류는 그 묶음에서 다시 쓰지 않고 다음 후보로 간다.
   - `STUCK_ID_MISMATCH`: 막힘이 이미 바뀌었다. 그 막힘을 놓고 로봇 상태를 다시 읽는다.
   - `EMERGENCY_ACTIVE`, 보정 lease 거부: 판단기는 손을 떼고 사람에게 올린다.
   - 통신 실패: `resolver_poll_s` 뒤 상태를 다시 읽고, 막힘이 그대로면 같은 답을 한 번만 다시 보낸다.
6. **3단계 — 사람.** 판단기가 `ESCALATE` 하면 지금의 콘솔 판단 요청(D-407 Fleet 쪽)에 단계·사유·시도 기록과 함께 올리고 알림을 보낸다. 사람의 답은 §1 의 방법으로 판단기보다 우선한다.
7. **안전 불변식.**
   - 어느 단계의 답이든 CORE 의 재검사가 최종이다. CORE 의 거부는 그대로 기록되고 판단기는 거부를 우회하지 않는다.
   - 비상정지는 판단기·모델이 풀 수 없다(`stuck_resolver` 역할에 해제 권한 없음). 비상정지는 막힘을 닫는다(D-407).
   - Fleet 연결이 끊기면 로봇은 D-407 동작(관제 연결 없음 → 로컬 복구 설정을 따름 → HOLD)으로 돌아간다. 판단기가 없다고 로봇이 스스로 더 풀어주지 않는다.
   - 판단기는 로봇의 로컬 복구 설정·시도 수·뒤 여유 규칙을 넓히지 않는다.
   - 모델 출력은 안전 기능이 아니다(D-430). 모델 SDK·HTTP 클라이언트는 Fleet 판단기 안에만 있고 로봇 런타임에 들어가지 않는다.
8. **기록.** 판단기의 모든 답은 단계(`rule`·`model`·`human`), 규칙 id 또는 모델 이름, 막힘 묶음 id, 입력 요약(미리보기 순서번호, 여유값), CORE 응답(수락·거부 code), 걸린 시간을 Fleet 감사(`principal_id = "fleet-resolver"`)에 남긴다. 모델 판단과 그 결과(풀림·재막힘·사람 개입)는 나중에 규칙을 늘리거나 학습 자료로 쓸 수 있게 남긴다. 카메라 영상 자체는 남기지 않는다(D-379 녹화가 따로 있다).

## 결과

- 막힌 로봇은 사람이 콘솔을 보지 않아도 규칙이나 모델의 답을 받는다. 사람은 규칙·모델이 못 푼 막힘, 판단기 RESUME 뒤 재막힘, 보정·비상정지 중 막힘만 본다.
- Fleet 쪽 변경: 판단기 작업, hub 사건 콜백 나눔, 폴링, 묶음·예산·기한, 미리보기 한 장 받기, OpenRouter 호출, 감사 기록, 콘솔의 단계 표시와 "판단 창을 열면 사람이 맡음".
- 로봇 쪽 변경: `stuck_resolver` 역할과 그 토큰(막힘 답·읽기만 통과). 막힘 상태기계와 다섯 답은 그대로다.
- 로컬 복구가 꺼진 로봇에서 판단기가 할 수 있는 것은 `WAIT`·`RESUME`(앞물체만)·`ABORT`·사람에게 올리기다. R2·R3 의 효과는 로봇별 self-mask 측정과 로컬 복구 켜기 뒤에 생긴다.
- OpenRouter 사용에 비용과 지연이 생긴다. 예산과 기한으로 묶는다.
- 사전 주의점(감속 구간, 앞의 차선 끊김, 다가오는 로봇)은 다음 ADR 이다.

## 검증

- 호스트: 단계 전이(규칙 → 모델 → 사람), 막힘 묶음 판정(닫힘 종류 무관, `resolver_restuck_s`), 판단기 RESUME 뒤 재막힘 → 사람, 예산·기한, `stuck_id` 중복 맡기 금지, 응답 code 별 처리(§5), 판단 창을 연 뒤 판단기 침묵, 로컬 복구 꺼짐에서 R2·R3·모델 BACK_AND_RETRY 건너뜀, `lane_lost` 에서 모델 RESUME → ESCALATE, 모델 출력 형식 오류·저신뢰·시간초과 → ESCALATE, `resolver_model_timeout_s < recovery_ask_s` 설정 검사, `stuck_resolver` 역할이 막힘 답·읽기 외 API 에서 거부됨, 사건 유실 시 폴링으로 맡음.
- Gazebo: 두 로봇이 마주 본 `obstacle_ahead`(R1 WAIT → `cleared`), 벽 앞 막힘(R2, 로컬 복구 켜짐·꺼짐), 차선 상실(R3), 판단기 RESUME 뒤 재막힘 → 사람을 재현한다. 모델 단계는 고정 응답 대역(stub)으로 시험한다.
- 실기: 사용자 승인 뒤 한 대씩. 모델 단계는 사이트 운영자 동의와 키 설정 뒤.

## 잇는 결정

D-2(단일 cmd_vel), D-18(API 계약), D-59(영상 중계, §3 에서 고침), D-257(천장 카메라), D-321 부록(보정 세션), D-379(학습 자료), D-395(Fleet 보조 위치추정), D-399(Fleet 과 장치 파이프라인), D-407(막힘 질문, 이 ADR 이 §2 의 답하는 주체와 Fleet 쪽 영상 해석을 고친다), D-419(Fleet 연결 상실), D-422·D-424(몸 기준 정지), D-430(안전 분리), D-435(Fleet 조정 규칙의 실행 범위, Proposed).

## 구현 메모 (2026-10-03, 1단계: 규칙·사람, docs/d438-fleet-stuck-resolver)

- CORE: `stuck_resolver` 역할(순위 viewer)과 `STUCK_DECIDE` 권한. 막힘 답 경로는 역할 대신 이 권한을 본다(operator·administrator 도 가진다). `stuck_resolver` 가 `MANUAL` 을 고르면 403 `FORBIDDEN`("MANUAL is a human decision (D-438)")이고 막힘은 열려 있다.
- Fleet: `fleet/server/stuck_resolver.py`(순수 판단), `stuck_resolver_loop.py`(1 s 폴링 + `nav.line_stuck_*` 사건으로 깨움, 보드 갱신, `fleet-resolver` 로 기록). 콘솔 버튼을 누르면 `.../line-stuck/claim` 으로 사람이 맡는다. 사람 답 경로도 먼저 맡고, CORE 전달이 실패해도 맡음을 유지한다.
- 설정: robots.yaml `resolver_token`(로봇마다 CORE `stuck_resolver` 토큰, 비어 있지 않은 따옴표 문자열, `token`·`fleet_pairing_token` 과 달라야 함), `fleet console --stuck-resolver`. 토큰이 없는 로봇의 막힘은 `no_resolver_token` 으로 바로 사람에게 간다.
- 올리는 사유: `no_rule`, `rule_budget`, `deadline`, `restuck_after_resume`, `estop`, `calibration`, `no_resolver_token`, `human_claimed`, `core:<CODE>`. 기본값: 폴링 1 s, 재막힘 창 30 s, 규칙 예산 2, 기한 60 s.
- 전송 실패는 `ROBOT_UNREACHABLE` 이면 `accepted=False`, 그 밖에는 null 로 기록한다.
- 2단계(비전 모델)는 아직 없다. 규칙이 못 풀면 `no_rule` 로 사람에게 올린다.
- 해석: R1 의 "앞 경로 띠"는 기지 대 기지 0.30 m, 옆 ±0.15 m(자기 반폭 + 상대 회전반경 0.083 m)로 잰다. 로봇 종류별 몸 크기는 아직 읽지 않는다.
- 등록(D-361)으로 들어온 로봇은 아직 판단기 클라이언트가 없다. robots.yaml 로봇만 갖는다.
- 판단기 클라이언트 연결은 닫지 않는다(콘솔 클라이언트는 `console.aclose()` 가 닫지만 이쪽은 프로세스 종료에 맡긴다).
- R1 은 모든 로봇의 자세가 하나의 사이트 좌표계에 있다고 가정한다(Fleet 위치 D-395·D-257). 자세를 모르면 R1 은 쓰지 않고, `obstacle_ahead` 에 R2 `BACK_AND_RETRY` 가 갈 수 있다. 이때도 CORE 의 뒤쪽 확인(D-407 §2 재검사)이 후진을 막는다.
- 감사(§8): `fleet_line_stuck_answers` 에 null 가능 열 `tier`(`human`·`rule`), `rule`(`R1`–`R3`), `escalated` 를 더했다. 판단기가 사람에게 올릴 때마다 `decision: "ESCALATE"`, `accepted` null, `principal_id: "fleet-resolver"` 행이 따로 남는다. 옛 DB 는 열 때 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` 으로 열이 붙는다. `chain_id` 는 사슬 식별자가 없어 넣지 않았다.
- 공유 gather: `console.snapshot()` 은 교통·인계·대형 속도 판단도 돌리고 모든 로봇에 GET 하므로, `GET /api/fleet/state` 와 판단기 루프는 `console_routes.SharedGather`(잠금 하나, 1 s 안의 결과 재사용, 새로 읽을 때만 `board.observe`)를 같이 쓴다(`app.state.fleet_gather`). 작업 배차 루프의 `console.snapshot()` 은 그대로다.
- 전송 재시도 한 번(§5)은 규칙 예산에 막히지 않는다. 명단에서 빠진 로봇의 사슬·맡음은 지운다. 올린 뒤 사람이 맡으면 올린 사유를 유지한다(없으면 `human_claimed`). 판단기가 로봇 응답을 기다리다 멈추면 그 답은 `STUCK_DECISION_OUTCOME_UNKNOWN`(accepted null)로 남는다.
