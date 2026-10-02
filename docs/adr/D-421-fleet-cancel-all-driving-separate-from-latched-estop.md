## D-421 Fleet 전체 주행 취소는 래치 없는 취소이고, 전체 비상 정지와 나뉜다

**Status:** Proposed (2026-10-02, 사용자 승인 — 작업 C: STOP ALL을 두 동작으로 나눈다). FLEET SRS CTR-002를 개정한다. 소스·호스트 시험 범위이며 실물 정지 수용이 아니다. 처음 D-414로 썼다가 D-417로, 다시 D-421로 옮겼다 — D-414(관제 콘솔 바로 동작)와 D-417(콘솔 밀도 정리)은 다른 세션이, D-415·D-416·D-418·D-419·D-420은 다른 가지·main이 먼저 잡았다. Pinky 장치 동작 ADR은 D-416에서 D-420이 되었다(가지 이름 `feat/d414-fleet-cancel-all`은 그대로).

이는 결정: [D-12](D-12-mission-fleet.md) · [D-298](D-298-mission-action-and-stop-evidence-terminology.md) · [D-330](D-330-fleet-action-admission-stop-and-recovery.md) · [D-333](D-333-er2-mission-device-action-contract-closure.md) · [D-369](D-369-control-authority-and-stop-evidence.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md).

### Context

FLEET SRS CTR-002는 "STOP ALL은 Navigation 취소이며, 필요 시 로봇별 E-Stop은 별도 명령으로 구분한다"고 적는다. 구현에는 `POST /api/fleet/estop` 하나뿐이다. 이 경로는 Fleet 발행 래치를 걸고(D-330, 세대 증가), 대기 작업을 취소하고, 설정된 OMX에 `StopLocal`을 보내고, 대형을 풀고, 신호등을 전부 적색으로 하고, 각 로봇에 `POST /api/v1/safety/stop`을 보낸다. CORE는 그 요청을 래치된 EMERGENCY로 받는다. 다시 움직이려면 로봇마다 Admin이 `POST /api/v1/safety/release`를 하고, 운용자가 발행을 재허가해야 한다.

그래서 두 가지가 어긋났다.

1. SRS가 말하는 STOP ALL(주행 취소)은 화면에 없다. "전부 멈춰"가 필요한 일상 상황(경로 착오, 미션 철회, 현장 정리)에서 운용자가 고를 수 있는 것은 래치형 비상 정지뿐이다. 그 뒤에는 로봇마다 관리자 해제가 따른다.
2. 상단 버튼 이름은 "전체 정지 / 등록된 모든 로봇"이다. 래치가 걸리고 관리자 해제가 필요하다는 사실이 이름에 없다.

로봇 쪽 원자 액션(`navigation/cancel`, `swarm/cancel`, `line-follow/mode OFF`)과 Fleet 쪽 대기열 취소는 이미 있다. 빠진 것은 이것들을 사이트 전체에 래치 없이 한 번에 내리는 경로와, 결과를 로봇별로 정직하게 보이는 화면이다.

### Decision

1. **두 동작으로 나눈다.**
   - **전체 비상 정지**: 기존 `POST /api/fleet/estop`. 의미는 바꾸지 않는다(D-330 래치, OMX StopLocal, 신호등 적색, CORE `safety/stop`). 버튼의 접근 이름만 래치를 드러내게 바꾼다(7항).
   - **전체 주행 취소**: 새 `POST /api/fleet/cancel-all`. 래치를 걸지 않고 진행 중인 주행과 대기 중인 Fleet 작업을 거둔다. 다시 주행하려면 새 목표를 보내면 되고 해제·재허가가 필요 없다.

2. **전체 주행 취소의 순서와 범위.** 한 요청 안에서 다음 순서로 한다. 한 단계가 실패해도 나머지 단계와 나머지 로봇은 계속한다. 빨리 실패하면 멈출 수 있었던 로봇이 계속 달린다(`estop_all`과 같은 이유).
   1. **기록과 발행 겹침 울타리를 연다.** 이 창과 겹친 Fleet 발행(아래 6)이 걸러진다. 작업 저장소 DB에 취소 기록(`fleet_cancel_all`: id, 운용자, 연 시각·닫은 시각, 로봇 id, 취소한 대기 작업 id, `navigation/cancel`이 응답한 로봇)을 쓰고, 그 로봇들의 진행 중 **시도**(`ACCEPTED`·`RUNNING`, 발행 중 `QUEUED`, 그리고 창 이후 바뀌었거나 아직 취소 사건이 없는 `UNKNOWN`)에 `(task_id, attempt_id)` 표시(`fleet_cancel_all_tasks`, 출처 `window`/`fence`)를 단다. 창을 닫을 때 그 사이 나타난 진행 중 시도에도 단다. 응답의 `cancel_all_id`가 이 기록이다. 표는 `FleetTaskStore`가 다른 일지 표와 함께 만든다. 작업 일지에는 정리 규칙이 없으므로, 닫힌 지 30일 넘은 기록과 표시는 새 창을 열 때 지운다. 기록을 쓰지 못하면 fanout은 계속하고 응답에 `record_error: CANCEL_ALL_RECORD_UNAVAILABLE`을 싣는다(그때 `awaiting_core_result`는 미완 작업 목록으로 대신한다).
   2. **대기 중인 Fleet 작업을 취소한다.** 모든 로봇의 `QUEUED`(`READY`·`WAITING_TRAFFIC`) 작업을 `CANCELED`로, 사유 `FLEET_CANCEL_ALL`, 행위자는 인증된 운용자로 기록한다. 콘솔 교통 대기열의 해당 항목도 지운다. 로봇 fanout보다 먼저 한다 — 그래야 fanout 도중 디스패처가 대기 작업을 새로 집어 가지 않는다. 작업 저장소가 실패하면 기록(`tasks.error`)하고 fanout은 계속한다.
   3. **대형을 푼다.** 열린 대형 세션이 있으면 `formation_stop`(릴레이 정지, 팔로워 `swarm/cancel`). 릴레이가 참조를 계속 밀면 팔로워가 다시 달린다.
   4. **로봇마다 세 단계(로봇끼리는 동시에, 한 로봇 안에서는 차례로).** `POST /api/v1/swarm/cancel` → `POST /api/v1/navigation/cancel` → `PUT /api/v1/line-follow/mode {mode: OFF}`. 세 CORE 호출은 모두 이미 있고 멱등이다(목표가 없으면 상태만 돌려준다, 추종이 없으면 빈 상태, OFF면 그대로 OFF). Fleet은 `navigation/cancel`이 응답한 로봇에 대해서만 기억하던 목표·점유·대기·양보를 지운다 — 응답 없는 로봇은 아직 가고 있을 수 있으므로 화면의 목표를 남긴다(`estop_all`과 같은 규칙).
   5. **이미 발행된 Fleet 작업은 Fleet이 `CANCELED`로 바꾸지 않는다.** 권고안(진행 중 작업도 사유를 붙여 취소)에서 벗어나는 점이다. 이유: 작업 상태 기계에서 `CANCELED`는 발행 전에만 있다(§10.8, `ACCEPTED`·`RUNNING`에서 `CANCELED` 전이 없음). 발행 뒤의 결과는 상관된 CORE 증거로만 바뀐다(D-170·D-293). 2-4의 `navigation/cancel`이 CORE에 닿으면 CORE가 `nav.canceled`(같은 `correlation_id`)를 낸다. 이 사건은 **취소가 내려졌다**(cancel issued)는 증거이지 로봇이 섰다는 증거가 아니다(D-298) — HOLD 해제는 그 증거에만 기대고, 정지는 readback으로 따로 본다. **2-1의 표시와 맞는 사건이면** Fleet 투영이 그 작업을 `HOLD`, 사유 `FLEET_CANCEL_ALL`로 옮긴다. 맞는다는 것은 모두 참일 때다: 표시의 `attempt_id`가 사건의 `correlation_id`와 같다(표시는 시도 단위다 — 발행 전 중단 뒤 새 시도는 다른 것이다); CORE가 `data.source`를 주면 API 호출(`api:*`)이다; 창이 아직 열려 있거나, 닫힌 지 `HOLD_GRACE_S`(30 s — CORE는 취소를 처리하며 사건을 내므로 건강한 링크면 수 초, 30 s는 FleetAgent 재접속·재전송을 덮되 훨씬 뒤의 취소는 받지 않는다) 안이고 그 로봇의 `navigation/cancel`이 응답했거나 울타리의 재취소가 단 표시다. 그 밖의 늦은 취소(운용자·막힘 답·안전·도킹)는 이 창의 것이 아니므로 `UNKNOWN`이다. CORE 사건이 표시보다 먼저 올 수 있다(창이 연 뒤 발행된 작업에 창의 취소가 먼저 닿는 경우). 그래서 울타리는 창이 열려 있으면 CORE 목표 호출 **전에** 표시를 달고, 표시를 다는 쪽(울타리·창 닫기)은 이 창 안에서 이미 `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING`이 된 같은 시도를 같은 트랜잭션에서 `HOLD`로 정리한다. 이미 `HOLD(FLEET_CANCEL_ALL)`인 작업에 늦게 온 상관 사건과 늦은 발행 응답은 기록·로그만 하고 적용하지 않는다. HOLD는 끝 상태이므로 기존 규칙대로 그 로봇의 점유(`robot:` claim)가 풀리고 **새 작업이 다시 배정된다**. 표시가 없는 `nav.canceled`는 예전처럼 `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING`이다. **CORE 사건이 오지 않으면 작업은 그대로(`ACCEPTED`·`UNKNOWN`)이고 로봇 점유도 남는다** — 정직한 결과이며 대조가 필요하다. 2026-10-02 현재 `UNKNOWN` 작업을 대조하는 운용자 경로는 없다(`/api/fleet/tasks/{id}/cancel`은 대기 작업만). 응답은 CORE 확인을 기다리는 작업을 로봇별 `tasks.awaiting_core_result`로 보인다: `ACCEPTED`·`RUNNING`, 그리고 창이 열린 뒤 바뀐 `UNKNOWN`(그 전의 오래된 `UNKNOWN`은 이 창의 것이 아니다). 창이 닫히기 전에 CORE 확인이 이미 와서 `HOLD`가 된 작업은 목록에 없다.
   6. **발행과 겹친 창은 다시 취소한다.** 디스패처가 CORE 목표 호출을 시작한 뒤 끝나기 전에 전체 주행 취소가 시작됐거나 진행 중이면(창 안에 제출되어 창 안에 발행된 Fleet 작업도 겹친 것으로 본다), Fleet은 목표 호출이 끝나자마자 응답을 본다.
      - CORE가 목표를 명시 거절(`accepted: false`): 취소할 것이 없다 → 기존대로 `FAILED`/`COMMAND_REJECTED`.
      - Fleet 자신의 교통 대기열에 남았고 살아 있는 CORE 목표가 없다(`queued`이고 CORE에 보내지 않았거나 취소가 확인됨): 콘솔 대기열에서 지우고 작업을 `CANCELED`/`FLEET_CANCEL_ALL`로.
      - 그 밖(수락, 모호): 작업에 2-1 표시를 달고, 그 로봇과 그 로봇을 위해 `_make_room`이 베이로 보낸 로봇에 `navigation/cancel`을 보내고, 작업은 `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH`(자동 재시도 없음). 뒤따르는 CORE `nav.canceled`가 2-5대로 `HOLD`로 옮긴다.
      - 목표 호출이 예외로 끝나도(응답 유실·취소) 겹쳤으면 같은 재취소를 최선으로 하고 원래 예외를 다시 던진다(분류는 기존대로 `FAILED`/`UNKNOWN`; `CancelledError`는 취소 그대로).
      래치가 없으므로 이 울타리가 "취소했는데 방금 집힌 작업이 뒤늦게 출발"하는 창을 닫는다. 울타리는 Fleet 디스패처만 거른다 — 같은 순간 운용자가 직접 보낸 새 목표는 더 새로운 명령으로 본다. 재취소는 지금 상관 없는 `navigation/cancel`이다. D-420 R2(상관된 취소)가 생기면 그 작업의 `correlation_id`로 취소한다.
   7. **이후 새 작업은 그대로 발행된다.** 발행 래치·세대는 건드리지 않는다.

3. **건드리지 않는 것.** CORE e-stop 래치(`safety/stop`·`safety/release`를 부르지 않는다), Fleet 발행 래치·세대, OMX 로컬 정지, 신호등, 수동 조작(teleop)과 MANUAL 모드(`/mode`를 부르지 않는다; CORE는 line-follow가 켜져 있던 NAVIGATION만 IDLE로 내린다), 도킹, D-395 위치 확인 미션. 도킹·위치 확인 미션은 열린 질문으로 남긴다.

4. **결과는 로봇별로 정직하게.** 로봇마다 `result`는 셋 중 하나다.
   - `cancelled`: 세 단계 모두 CORE가 2xx로 답했다.
   - `unreachable`: 어느 단계도 CORE의 답을 받지 못했다(연결·시간 초과).
   - `failed`: 그 밖(한 단계라도 거절되었거나 일부만 닿았다).
   단계별 `{ok, error: {reachable, code, message}}`를 함께 싣는다. **CORE의 HTTP 응답은 물리 정지가 아니다**(D-298·D-369): 응답 본문의 `evidence`는 `CORE_REPLY_ONLY`이고 화면은 "주행 취소 요청 응답 x/y · 물리 정지 미확인"을 쓴다. 한 대가 실패해도 200이다(부분 실패를 5xx로 접으면 어느 대가 멈췄는지 화면이 모른다). 주소가 확인되지 않아 정지 요청만 허용된 로봇(D-361)은 Fleet 쪽 주소 관문이 `line-follow/mode`를 로컬에서 막는다. 그 단계는 `{reachable: false, sent: false, code: ADDRESS_UNVERIFIED}`(보내지 않음)로 적히고 로봇은 `failed`, 화면은 "주소 미확인 — 차선 추종 끄기 미전송"이다. 그 로봇의 차선 추종은 Fleet이 끌 수 없다는 사실을 숨기지 않는다. `line-follow/mode`는 `STOP_PATHS`에 넣지 않는다 — 경로 단위 관문은 `IR_LINE` 켜기도 열어 준다. 본문을 보는 규칙(`OFF`만 통과)은 나중 일이다. 또 Fleet은 주소 미확인 로봇의 교통 점유(`_claims`)를 취소 뒤에도 지우지 않는다 — 그 로봇은 막힌 장애물로 남는다.

5. **권한과 감사.** `operator`. 일반 변경 감사 규칙을 따른다 — 감사 저장소가 쓰기를 못 하면 `503 AUDIT_STORAGE_UNAVAILABLE`이고 CORE를 부르지 않는다. D-330의 예외는 전용 비상 정지 하나로 남긴다. 그때도 전체 비상 정지는 살아 있다.

6. **멱등.** 같은 요청을 다시 보내도 안전하다. 두 번째 요청은 새로 취소할 대기 작업이 없고 CORE 호출은 상태만 돌려준다. 그래서 `Idempotency-Key`를 요구하지 않는다(비상 정지와 같다).

7. **화면(운용 문서 `/console`).**
   - 상단 비상 정지: main 의 디자인대로 글자 없는 팔각 아이콘 버튼(58×58)이다. 래치 뜻은 접근 이름(`aria-label`, 화면 낭독용 `sr-only` 글)과 `title`이 말한다: "전체 비상 정지 (래치 · 로봇별 관리자 해제)". 설치 문서(`/console/install`)의 같은 버튼도 같은 이름이다. 비상 정지를 누를 때 확인을 거칠지는 이 ADR이 정하지 않는다 — 같은 날 다른 세션의 D-414(관제 콘솔 바로 동작)가 확인을 없앤다. 그래서 래치는 확인 문장이 아니라 버튼 이름이 말한다.
   - 새 버튼 "전체 주행 취소"(`kind="primary"`)는 발행 상태 줄(`#dispatch-control`) 안에 둔다. 상단바 격자는 바꾸지 않는다(비상 정지만 상단에 있는 D-280 첫 화면 규칙). 운용자 권한이 없으면 공용 권한 잠금(`reason`)으로 막힌다. `window.confirm`으로 "등록된 모든 로봇의 주행(내비게이션 목표·대형 추종·차선 추종)과 대기 작업을 취소합니다. 비상 정지 래치는 걸지 않습니다. 계속할까요?"를 묻는다. 결과는 기록 칸에 "주행 취소 요청 응답 x/y · 물리 정지 미확인"과, 취소하지 못한 로봇마다 `실패`·`응답 없음` 줄(실패한 단계마다 이름과 코드), 취소한 대기 작업 수, CORE 확인을 기다리는 작업 수("로봇이 취소를 알리면 다시 배정, 알리지 않으면 대조 필요")를 쓴다. 등록 로봇이 없으면(0/0) 성공이 아니라 "주행 취소 대상 로봇 없음"으로 경고한다.
   - 설치 문서에는 주행 취소를 두지 않는다(설치 중에는 주행이 없다. 비상 정지는 D-280에 따라 그대로 있다).

8. **CTR-002 개정문.** "STOP ALL은 두 동작으로 나뉜다(D-421). **전체 주행 취소**는 선택된 전체 로봇의 진행 중 주행(내비게이션 목표·대형 추종·차선 추종)과 대기 중 작업을 **즉시** 취소하는 래치 없는 명령이다. **전체 비상 정지**는 로봇마다 안전 정지 래치를 거는 별도 명령이며 로봇별 관리자 해제와 발행 재허가가 필요하다. 두 명령 모두 명령 전달 결과(취소됨/실패/응답 없음)를 로봇별로 표시하며, 응답은 물리 정지의 증거가 아니다."

9. **API Reference.** §10.2에 두 경로의 의미 차이를, §10.8 표에 `POST /api/fleet/cancel-all` 행을 둔다. 사이트 Fleet 경로의 추가이므로 Additive, 문서 버전 v1.81(로봇 `/api/v1/*`·FleetAgent `protocol_version` 변경 없음).

### 응답 형태

```json
{
  "cancel_all_id": "<uuid>", "record_error": null, "cancelled": 1, "total": 2, "evidence": "CORE_REPLY_ONLY",
  "robots": [
    {"robot_id": "rosy_01", "result": "cancelled",
     "steps": {"swarm": {"ok": true}, "navigation": {"ok": true}, "line_follow": {"ok": true}},
     "tasks": {"awaiting_core_result": ["<task_id>"]}},
    {"robot_id": "rosy_02", "result": "unreachable",
     "steps": {"swarm": {"ok": false, "error": {"reachable": false, "code": "ConnectError", "message": "..."}}, "...": "..."},
     "tasks": {"awaiting_core_result": []}}
  ],
  "formation": {"stopped": true, "state": "STOPPED"},
  "tasks": {"canceled": ["<task_id>"], "error": null}
}
```

`formation`은 열린 대형이 없으면 `{"stopped": false, "state": "IDLE"}`이다. 작업 저장소가 없는 배치에서 `cancel_all_id`는 `null`, `tasks`는 `{"canceled": [], "error": null}`이고 로봇별 `awaiting_core_result`는 빈 목록이다. Fleet 쪽 관문이 막은 단계의 `error`에는 `sent: false`가 붙는다. 미래의 Mission 취소가 들어오면 응답에 선택 필드 `missions`가 더해진다(Additive, 아래 D-420 연결).

### D-420과의 연결(앞으로)

D-420(가지 `docs/d416-pinky-device-actions`, 이 가지에는 아직 없음)의 Pinky 다단계 Mission이 들어올 때 이 결정은 이렇게 이어진다.

- **`DriveCancelFence`는 공유 확장점이다.** 미래의 Pinky Mission Step 제출기도 CORE 호출을 이 울타리(`fenced_goal`과 같은 꼴)로 감싸야 한다. 그래야 창과 겹친 Step도 다시 취소된다.
- **창 안의 Mission은 `HOLD(site_cancel)`이 된다.** 실행 중 Mission은 창 안에서 멈춤으로 옮기고, 응답은 선택 필드 `missions`(Mission id·결과)를 더한다. 취소 기록(`fleet_cancel_all`)과 표시 표는 D-420 §5.2의 늦은 끝 사건 표시에 그대로 쓴다.
- **재취소는 상관된 취소가 된다.** D-420 R2가 있으면 2-6의 재취소는 그 Step의 `correlation_id`를 실은 취소다.
- **도킹은 상관된 경우만.** 열린 질문 1의 도킹은 D-420 R8(현재 동작 readback)이 생긴 뒤, Mission이 시작한 도킹 동작에 한해 상관된 `docking/cancel`로 거둔다. Mission 밖의 도킹은 건드리지 않는다.

### Alternatives

- **비상 정지 이름만 고친다.** CTR-002의 주행 취소가 여전히 없고, 일상 정지마다 로봇별 관리자 해제를 치른다. 거절.
- **주행 취소도 발행 래치를 건다.** 재허가 비용이 생겨 "가벼운 비상 정지"가 된다. 사용자 결정(래치 없음)과 다르다. 대신 2-6 울타리가 발행 겹침 창만 닫는다. 거절.
- **진행 중 작업도 Fleet이 `CANCELED`로 쓴다.** 발행 뒤 상태를 CORE 증거 없이 바꾸는 것이고 상태 기계에도 없는 전이다. 거절(2-5).
- **`/api/fleet/do`의 새 동사로만 둔다.** 순차 step과 의도 해석을 거친다. 전용 경로를 먼저 두고 동사는 열린 질문으로 남긴다.

### Consequences

- 운용자는 "멈춰"와 "비상 정지"를 고를 수 있다. 일상 정지는 해제 비용이 없다.
- 비상 정지 버튼 이름이 래치를 말한다.
- 주행 취소는 래치가 아니다. 취소 뒤 누군가 새 목표를 보내면 로봇은 다시 간다. 사람의 안전이 걸린 상황에서는 비상 정지(또는 로봇 물리 E-stop)가 맞다 — 확인 문장과 이 ADR이 그 차이를 적는다.
- 응답 수는 물리 정지 증거가 아니다. 실제 정지는 로봇 상태 readback과 현장 확인으로 판정한다(D-298, D-369).
- Fleet 패키지와 `console.py` 크기: 새 오케스트레이션은 자기 모듈(`server/cancel_all.py`, 기록은 `server/cancel_all_store.py`)에 두고 `console.py`·`task_store.py`는 줄이 늘지 않는다. CORE 사건 투영(`task_results.py`)은 표시된 작업의 `nav.canceled`만 `HOLD`로 바꾼다.
- CORE 확인이 오지 않은 로봇은 점유가 남아 새 작업을 받지 못한다. 이것을 푸는 운용자 대조 경로는 아직 없다(열린 질문 5).

### Validation

호스트 시험(`src/site/fleet/test/test_cancel_all.py` 외):

- 모든 로봇에 세 CORE 호출이 순서대로 가고, `safety/stop`·`safety/release`·`/mode`·신호등 적색·OMX 정지·발행 래치가 없다.
- 한 대가 연결 실패여도 나머지는 취소되고 그 대는 `unreachable`, 거절은 `failed`, 응답 200.
- 대기 작업이 `CANCELED`/`FLEET_CANCEL_ALL`/운용자 행위자로 바뀌고, 발행 래치는 열린 그대로이며, 다음 새 작업은 발행된다.
- 발행된 작업은 `CANCELED`가 되지 않고 `awaiting_core_result`에 보인다(오래된 `UNKNOWN`은 빠진다).
- 탐침: 제출 → 발행 → 전체 주행 취소 → CORE `nav.canceled` → 작업 `HOLD`/`FLEET_CANCEL_ALL` → 같은 로봇의 새 작업이 발행된다. 사건이 없으면 작업·점유가 남고 새 작업은 대기열에 남는다. 창 밖의 `nav.canceled`는 여전히 `UNKNOWN`.
- 취소 기록에 운용자·로봇·취소한 대기 작업·표시한 시도가 남는다. 기록 실패는 `record_error`, 30일 지난 기록은 정리된다, 새 표가 없는 옛 DB도 열린다.
- 창 안에서 시작한 발행: CORE 사건이 목표 응답보다 먼저 와도 `HOLD`, 늦은 응답은 로그. 사건이 표시보다 먼저면 표시할 때 정리.
- 응답 없는 로봇의 나중 취소, 새 시도, `api:`가 아닌 출처, 유예가 지난 사건은 `HOLD`가 되지 않는다. `HOLD` 뒤 늦은 상관 사건은 로그만.
- 디스패처 목표 호출이 취소 창과 겹치면 `navigation/cancel`이 뒤따르고 작업은 `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH`. 호출이 예외로 끝나도 재취소하고, 그 로봇을 위해 베이로 간 로봇도 취소한다. 명시 거절은 `FAILED`, Fleet 대기열에 남은 것은 `CANCELED`.
- 주소 미확인 로봇: 교통 점유가 남고, 차선 추종 끄기는 `sent: false`.
- 열린 대형이 풀린다. 응답 없는 로봇의 화면 목표는 남는다.
- viewer·policy-admin은 403, 감사 저장소 장애는 503(CORE 호출 없음), 반복 호출은 안전.
- 화면: 확인 수 핀(`test_web_dialog_contract.py`), 버튼·문구, 비상 정지 이름.

실물 검증(열림): Gazebo 2대 또는 실물에서 주행 중 전체 주행 취소 → 두 대 standstill readback, e-stop 래치 없음, 새 목표로 즉시 재주행.

### 열린 질문

1. 도킹: Mission이 시작한 도킹 동작만, D-420 R8 이후 상관된 `docking/cancel`로 거둔다(위 D-420 연결). D-395 위치 확인 미션은 여전히 열려 있다.
2. `/api/fleet/do`에 `cancel_all` 동사를 둘 것인가.
3. 주소 미확인 로봇(D-361)의 `line-follow/mode`는 `STOP_PATHS`에 넣지 않는다(경로 단위 관문은 켜기도 연다). 본문이 `OFF`일 때만 통과시키는 관문을 둘 것인가.
5. `UNKNOWN`으로 남은 작업(CORE 확인 없음)을 운용자가 대조해 로봇 점유를 푸는 경로를 둘 것인가 — 지금은 없다.
4. D-414(관제 콘솔 바로 동작)가 비상 정지 확인을 없앤다. 전체 주행 취소도 정지 방향의 동작이므로 같은 원칙(확인 없는 한 번 누름)을 따를 것인가. 이 ADR은 작업 지시대로 확인을 둔다 — 대기 작업까지 지우기 때문이다.
