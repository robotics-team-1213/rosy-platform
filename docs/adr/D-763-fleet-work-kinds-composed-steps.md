## D-763 Fleet 새 작업의 종류 — 단계의 조합으로 만들고, 작업마다 주인은 하나이며, 승인은 위험으로 정한다

**Status:** Accepted (2026-10-14, 사용자가 열린 질문을 세션 토론으로 정하라고 위임함. 아래 개정 2가 토론 결과다)

잇는 결정: [D-741](D-741-unified-app-shell-seats.md) 7항(작업 영역의 자리. 종류의 API·필드·실행 owner를 이 기록에 맡겼다) · [D-664](D-664-mixed-device-work-and-workcell-boundaries.md)(공통 작업 개념과 읽기) · [D-12](D-12-mission-fleet.md) · [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md) · [D-330](D-330-fleet-action-admission-stop-and-recovery.md)(claim) · [D-401](D-401-rosy-cell-application.md) · [D-403](D-403-fleet-cell-job-route-cell-transfer.md)(Cell Job 경로와 승인) · [D-420](D-420-fleet-pinky-device-actions-multi-step-missions.md)(Proposed, 다단계 Mission) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(trip 루프) · [D-517](D-517-multi-robot-lane-traffic.md) · [D-541](D-541-core-fleet-trip-lease.md)(trip lease) · [D-573](D-573-crosswalk-stop-look-cross.md) · [D-438](D-438-fleet-stuck-resolver-rules-model-human.md) · [D-577](D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md) · [D-622](D-622-fleet-standalone-realign.md) · [D-758](D-758-robot-held-site-anchor.md) · [D-760](D-760-fleet-motion-bounds-ride-through.md) · [D-753](D-753-fleet-holder-namespace-guards.md). 폴더 구조는 바뀌지 않으므로 D-427 3항의 관계 표는 해당하지 않는다.

### Context

D-741 7항은 Fleet의 "로봇에게 시키는 일"을 `작업` 영역 하나에 모으고, 새 종류(예: 물체 가져오기)의 API·필드·실행 owner는 별도 ADR이 정한다고 했다. 이 기록이 그 ADR이다. 다루는 종류는 이동, 물체 가져오기, 파지·배치다.

**지금 있는 것(2026-10-14, 워크트리 `e8bcc99a5`에서 읽음).**

1. **새 작업에는 종류가 하나다.** `/console/cell`이 `새 작업`이고 화면 글은 "새 작업의 종류 · Cell 적재. 이동은 관제의 로봇 카드에서 목적지를 배정합니다"다(`operations/site_ui/console/cell/cell.html`).
2. **작업 목록은 trip도 Cell Job도 읽지 않는다.** `GET /api/fleet/work`(D-664, API v1.208)의 출처는 둘이다: `task`(`fleet_tasks`, navigate 요청)와 `mission`(`fleet_missions`, `PICK_PLACE`, 제안한 사람 자신의 것만). trip 저장소와 `fleet_cell_jobs`는 이 조회에 없다(`work_read.py`). Cell Job의 `mission_id`는 `fleet_missions`에 있으면 거절된다(`cell_job_store.py`). 그래서 `승인 대기`(같은 조회를 `PROPOSED`로 거른 것)에는 Cell Job 제안이 나오지 않고, 관제 카드에서 시작한 운행은 `전체 작업`과 `끝난 작업`에 나오지 않는다.
3. **로봇을 움직이는 Fleet 입구는 여러 개다.** trip(`POST /api/fleet/robots/{id}/trip` 계획, `POST /api/fleet/trips/{plan_id}/start`, 이름 있는 운영자), Task navigate, D-463 `/route`, 콘솔 목표, 대화 요청의 Task 제출, intent navigate, 양보 bay, 대형이다. "trip 로봇은 건드리지 않는다"는 검사(`TRIP_ROBOT_BUSY`)가 일곱 곳에 따로 있다(`channel/workflow.py`, `console/console.py` 두 곳, `console/console_routes.py`, `lane_route_routes.py`, `ledger/task_dispatch_routes.py`, `ledger/trip_guard.py`).
4. **trip은 끝나면 다시 열리지 않는다.** 상태는 `started → running → (arrived | stopped | failed | canceled)`다. 코드에서 센 끝 사유는 열 가지가 넘는다: `junction`(aborted), `junction_unexpected`, `junction_no_window`, `stall`, `lease_lost`, `restart`, `TRIP_GOAL_REFUSED`, `TRIP_ROBOT_UNREACHABLE`, `TRIP_LINE_FOLLOW_START_FAILED`, `TRIP_LOOP_ERROR`, 운영자 취소·비상 정지(`ledger/trip_runner.py`, `trip_halts.py`). 재시작 전에 열려 있던 trip은 `stopped(restart)`가 되고 자동으로 다시 출발하지 않는다(D-494 5항). lease를 잃은 trip도 다시 열지 않는다(D-541 7항).
5. **로봇을 쥐는 것은 trip이 열려 있는 동안뿐이다.** Fleet 쪽은 `robot_busy()`가 열린 trip만 본다. trip은 D-330 claim을 잡지 않는다(trip 코드에 `dispatch_admission` 호출이 없다). CORE 쪽 trip lease는 모드가 주행을 떠나면 끝난다(`middleware/core/gateway/core/trip_lease.py`의 `mode_left`). 그래서 trip 두 개 사이에 로봇이 IDLE이면 Fleet에도 CORE에도 주인이 없고, 대시보드·Pilot·다른 Fleet 입구가 로봇을 가져갈 수 있다. lease 자체도 현장 설정 `fleet.trip_lease_required`가 기본 false다.
6. **한도는 결정됐고 일부만 만들어졌다.** D-760(Accepted)은 한도 없는 Fleet 움직임을 `422 LINK_UNBOUNDED_MOTION`으로 거절하기로 했다. 단계별 상태는 다음이다(D-760 담당 세션의 설명을 저장소와 대조했다).

   | D-760 단계 | 상태 | 저장소에서 확인한 것 |
   |---|---|---|
   | 1 규칙 M 판정과 경고 | 로컬 `main`에 착지, origin 미착지 | `fleet/traffic/rule_m.py` |
   | 2 CORE `ttl_s` 상한 5, `shrink`·`seq`, 임대 중 통행권 강제, API v1.226 | 로컬 `main`에 착지(2026-10-14), origin 미착지 | `MAX_TTL_S = 5.0`(`line_authority.py`), 능력 `line_follow_authority_under_lease`·`line_follow_authority_shrink`(`core_common/protocol/controls.py`) |
   | 3 `link_wait`, Fleet 줄이기 송신, 재시작 뒤 5 s | 로컬 `main`에 착지(2026-10-14), origin 미착지 | `link_wait`가 `ledger/trip_admission.py`·`trip_ports.py`·`trip_progress.py`에 있다 |
   | 6 `LINK_UNBOUNDED_MOTION` 거절, 기본값 켜기 | Gazebo·장치 끊김 시험 뒤 | 코드에 없다 |

   trip 밖에서 Fleet이 차선 주행을 켜는 길(`console.line_follow_mode`)은 아직 있고 D-760 7항이 6단계에서 닫는다.
7. **순서 있는 Step 원장과 하달기는 하나 있고 종류 하나에 묶여 있다.** `fleet_cell_jobs`·`fleet_cell_steps`(`CHECK(action_kind='CELL_TRANSFER')`), 종류 등록부 `step_action_kinds.py`(항목은 `CELL_TRANSFER` 하나, `simulation` 프로필에서만 하달), 종류를 모르는 `StepJobDispatcher`다. Step k는 Step k−1이 `GOAL_CONFIRMED`일 때만 나가고, 장치 거절·실패·불명은 Job을 HOLD로 둔다. 레거시 `fleet_missions`의 승인 응답은 `physical_submission: NOT_CONNECTED`다.
8. **승인 규칙은 서버에 둘 있다.** 운행 시작은 이름 있는 운영자 한 사람이다(D-540 9항, API v1.161). Cell Job 승인은 이름 있는 운영자이고 제안한 사람과 달라야 한다(`ledger/mission_routes.py`, 403 `CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER`). 이 검사는 `candidate.kind == "cell_job"`이라는 글자에 붙어 있다. 레거시 `PICK_PLACE` Mission은 반대로 제안한 사람만 승인할 수 있다(다른 사람에게는 404).
9. **기다림은 일부만 정체에서 빠진다.** trip 정체 시계(`ledger/trip_progress.py` `_stalled`, 20 s 동안 0.05 m 미만)는 `hold`, 교차로 동작 중, 블록 대기(`waiting_for`), 통행권 끝 대기(`HOLDING`)에서 멈춘다. 횡단보도 게이트 대기와 신호 대기는 이 조건에 없다. D-573(Proposed) 4항은 게이트 대기를 정체로 세지 않는다고 적었지만 `_stalled`에는 없다. 토론 참여 세션은 횡단보도 대기 중 운행이 `stall`로 끝난 것을 보고했다. 이 기록에서 재현하지는 않았다.
10. **Fleet 크기 단위에 남은 여유가 없다.** `test/architecture/test_module_structure.py`는 현재 55452 = 기준 55302 + 150이고 기능 성장 허용을 더하지 않았다고 적는다(D-753).

**D-420이 이미 정한 것과 그 상태.** D-420은 Proposed다. 본문은 "설계만"이고, R1–R11·F1–F10의 이름(`NAVIGATE_TO_POSE`, `FOLLOW_LANE_TO_STOPLINE`, `PinkyCoreTransport`, `/line-follow/run`, `CORRELATION_NOT_ACTIVE`, `FLEET_LINK_DOWN`)은 `docs/` 밖에서 한 줄도 찾지 못했다. 다른 이름으로 일부가 들어갔는지는 확인 못 함. D-420이 정한 것은 다음이다.

| D-420 | 내용 | 이 기록에서 |
|---|---|---|
| §2 | Task Executor 하나, 장치별 전송 어댑터 | 그대로 쓴다(2항) |
| §3 | Step 원장 하나(두 번째 원장을 만들지 않는다), 요구 S1–S12 | 그대로 쓴다(2항) |
| §1.1 | 수락·결과·목표 증거는 다른 사실. 자동 재시도 없음. 실패는 HOLD + 사유 | 그대로 쓴다(2·3항) |
| §4.4 | 재개는 Mission 전체 재승인 | 그대로 쓴다(2항) |
| §4.5 | Mission이 승인부터 끝까지 `robot` claim을 쥔다(Step 사이 포함) | 그대로 쓴다(4항) |
| §1 | Pinky의 움직임 종류는 `NAVIGATE_TO_POSE`·`FOLLOW_LANE_TO_STOPLINE` | 조정을 제안한다(6항) |

D-420은 2026-10-02에 쓰였다. 그 뒤 trip 루프(D-494), 블록 통행권(D-517), trip lease(D-541), 움직임 한도(D-760)가 생겼고, 현장 로봇은 모터 모드라 지도 자세와 Nav2가 없다(D-758 Context 1). D-420 §1의 두 움직임 종류는 현장 로봇에서 지금 쓰는 길(차로 trip)과 다르다.

**토론의 주장과 저장소가 다른 곳.**

| 토론의 주장 | 저장소 |
|---|---|
| 한도 없는 Fleet 움직임은 거절된다(D-760) | 결정은 Accepted이고 경고(1단계)도 origin에 아직 없다. 거절은 6단계다 |
| trip lease가 trip 동안 로봇을 쥔다 | D-541의 Status는 Proposed이고 구현은 있다. 현장 기본값은 꺼짐이다 |
| 이동 입구가 둘이면 `TRIP_ROBOT_BUSY`를 두 번 만든다 | 이미 일곱 곳에 있다. 하나로 모으는 쪽의 근거는 더 강하다 |
| 가져오기 = 이동 + 장치 동작 + 이동을 Fleet이 잇는다 | 팔이 로봇에 장착된 경우에는 D-55와 D-664 3항이 접근·파지·운반·배치를 로봇 로컬 transaction으로 정했다. Fleet 조합은 운반 로봇과 고정 팔의 인계에만 맞는다(D-664 5항) |
| 새 작업에 지금 종류가 하나 있고 `승인 대기`가 그것을 보여 준다 | 종류는 하나가 맞다. 그 종류(Cell Job)는 `승인 대기` 목록의 출처가 아니다(위 2) |
| 파지·배치에 Cell의 "제안자 ≠ 승인자"를 쓴다 | 팔을 움직이는 레거시 `PICK_PLACE` Mission은 지금 제안한 사람이 스스로 승인한다(실물 하달은 연결돼 있지 않다) |
| 새 결정 값은 API 버전 고정 아홉 곳에 닿는다 | 버전을 고정한 시험과 `core_api_web/api/app.py`가 있는 것은 확인했다. 아홉이라는 수는 확인 못 함 |
| D-494에 자동 재출발이 없다 | 맞다(5항 상태기계). D-494의 Status는 Proposed다 |

### Decision

**원칙.** 새 종류는 새 실행기를 만들지 않는다. 이미 있는 실행 owner가 하는 단계를 순서대로 잇는다. 멈추는 것은 언제나 그 단계를 실행하는 쪽이고, Fleet은 보고 다음을 고른다.

**1. 종류는 단계의 조합이다.** 작업 종류는 이름이 붙은 단계 목록이다. 단계는 둘 가운데 하나다: **운행 단계**(Fleet trip 루프가 CORE에 시킨다)와 **장치 동작 단계**(Step 원장이 장치 owner에 Action 하나를 하달한다). 새 종류를 위해 CORE 모드, 막힘 결정 값(WAIT·YIELD·RESUME·ABORT·MANUAL), Mission 유형을 더하지 않는다.

| 종류 | 단계 | 지금 | 이 기록 뒤 |
|---|---|---|---|
| 이동 | 운행 1 | 관제 로봇 카드와 현장 지도에서 시작한다 | 새 작업에서도 같은 trip을 시작한다(6항). 바로 진행할 수 있다 |
| Cell 적재 | `CELL_TRANSFER` × n | 있다. 하달은 `simulation` 프로필에서만 열린다 | 그대로다 |
| 파지·배치(고정 작업 공간) | 장치 동작 1 | 레거시 `PICK_PLACE` Mission. 승인까지만 되고 하달은 연결돼 있지 않다 | 종류로 올리지 않는다. 승인 규칙만 7항을 따른다 |
| 물체 가져오기 | 운행 → 인계 동작 → 운행 | 없다 | 10항의 열린 것이 풀릴 때까지 열지 않는다 |

**2. 순서를 넘기는 층은 지금의 Step 원장과 하달기다.** 두 번째 원장이나 실행기를 만들지 않는다(D-420 §2·§3). 이 층이 할 수 있는 일은 다음뿐이다.

- 앞 단계가 끝났다고 확인되면 다음 단계를 한 번 제출한다.
- 단계가 실패하면 작업을 HOLD(사유)로 두고 멈춘다.
- 운행 단계의 "끝났다"는 trip의 `arrived` 하나다. `stopped`·`failed`·`canceled`는 사유가 무엇이든 "단계 실패"이고 trip의 사유를 HOLD 사유로 옮긴다.
- 이 층은 trip을 다시 열지 못하고, 같은 시도를 다시 보내지 못하고, 경로를 다시 짜지 못한다. trip 안의 재계획과 그 확인은 지금처럼 trip 루프와 운영자의 일이다.
- HOLD에서 다시 가는 길은 이름 있는 운영자의 작업 전체 재승인 하나다(D-420 §4.4, 지금 Cell Job의 `/resume`). 재승인은 확인되지 않은 첫 단계부터 새 시도로 간다. 운행 단계라면 새 trip이다.

**3. 멈춤은 실행하는 쪽이 한다. 새 자동 재시도는 없다.** CORE가 서고(통행권 끝, lease 만료, 몸체 정지, 비상 정지), OMX owner가 선다. Fleet은 그 사실을 받고 다음을 고른다. 로봇이 스스로 선 뒤 다시 가게 하는 자동 경로는 지금의 막힘 해결기(D-438, D-577, D-622) 하나이고, 그것은 trip이 열려 있는 동안 단계 안에서만 일한다. 작업 층에는 재시도가 없다: 단계가 한 번 실패하면 사람이다. D-622의 "같은 막힘 조작은 두 번까지"는 해결기 안의 한도로 그대로 둔다. 규제 대기는 실패가 아니다. 기다림이 상한을 넘으면 먼저 막힘 해결기로 가고, 해결기가 사람에게 넘긴 것만 작업의 실패 한 번이다(개정 2, 질문 7).

**4. 작업마다 주인은 하나이고, 로봇마다 작업은 하나다.**

- **Fleet 쪽.** 작업은 승인부터 끝(완료, 운영자 취소)까지 그 로봇의 D-330 `robot` claim을 쥔다. 단계 사이와 HOLD에서도 쥔다(D-420 §4.5, Cell Job은 D-403 보강의 `HELD`). Fleet의 모든 움직임 입구는 "이 로봇에 주인이 있는가"를 **함수 하나**로 묻는다. 지금 일곱 곳의 `TRIP_ROBOT_BUSY` 검사가 그 함수로 모인다. 열린 trip과 작업 claim이 같은 답을 낸다.
- **CORE 쪽.** 단계 사이에 로봇이 IDLE이어도 대시보드와 Pilot이 로봇을 가져가지 못해야 한다. 지금 trip lease는 IDLE로 가면 끝나므로 이것을 못 한다. **제안:** 작업이 쥔 lease는 그 작업의 단계 사이 IDLE에서 끝나지 않는다. 명시적 넘겨받기, 비상 정지, 만료, 주인의 해제는 지금처럼 끝낸다. 멈춤 요청은 지금처럼 누구에게나 열려 있다. 이것은 D-541 5항을 고치는 CORE 계약 변경이고 Safety-Review 대상이다(바뀌는 항).
- **굳은 규칙: 작업의 주인은 움직임 한도를 늘리지 않는다.** 작업 동안 유지되는 lease는 "누가 로봇을 쥐는가"에만 답한다. 움직임의 한도는 단계마다 그대로다: 차로 구간은 통행권(D-760 이후 5 s), 자유 구간의 목표는 목표 임대(3.5 s). 작업 층이 일반 heartbeat로 lease나 통행권, 목표 임대를 늘리지 않는다. 각 한도는 그 움직임을 실제로 모는 루프(trip 루프, 목표 임대 갱신기)만 늘린다. trip 루프가 멈추면 작업의 주인이 살아 있어도 움직임 한도는 만료해야 한다. 시험으로 고정한다: trip 루프를 멈추고 작업 claim은 쥔 채 두면 로봇이 통행권·목표 임대 만료로 선다.
- **D-760 2단계와의 관계.** D-760 2단계(브랜치, 미착지)는 CORE에 "lease를 본 차선 추종 세션은 모드가 바뀔 때까지 통행권을 요구한다"를 더한다(D-760 2항). lease를 모드 사이에 유지하는 것은 이와 맞는다: 통행권 요구는 세션마다 다시 걸린다. 다만 `mode_left`로 lease를 끝내는 규칙을 바꾸는 것은 `core/trip_lease.py` 변경이고, 팔이 움직이는 동안 lease가 만료하면 CORE가 무엇을 멈추는지(지금 만료 정지는 차선 추종과 내비게이션을 끈다)를 정해야 한다. 이 조각은 Safety-Review를 받고, 시작 전에 D-760 담당 세션에 알린다(그 세션도 이 파일을 고친다).
- **작업 lease의 조건(개정 2, 질문 2).** D-760 3단계 규칙(trip lease `ttl_s` 기본 8 s, `link_wait`, `lease_lost`로만 끝남)을 탄다. 횡단보도·신호·통행권 대기로 서 있는 시간은 D-507 부기 13처럼 단계의 시간 계산에서 빼서 대기만으로 단계 시계가 끝나지 않게 한다. 조각 6은 Safety-Review trailer 없이 착지하지 않는다(D-762 0단계).
- **우선순위는 없다.** 로봇에 작업이 있으면 다른 작업은 거절한다. 줄 세우기와 끼어들기는 정하지 않는다(하지 않는 것 1).
- CORE 쪽 변경이 착지하고 장치에서 확인되기 전에는 운행 단계가 든 다단계 종류를 열지 않는다. 단계가 운행 하나인 이동은 지금의 trip lease로 충분하므로 기다리지 않는다.

**5. 움직이는 단계는 모두 한도가 있다.** 작업의 운행 단계는 D-760이 `bounded`로 판정하는 것만이다: trip lease와 통행권을 쥔 차로 trip, 또는 임대 있는 목표. 다단계 종류는 현장 설정에서 trip lease(`fleet.trip_lease_required`)와 통행권(`fleet.traffic.authority`)이 **둘 다** 켜져 있을 때만 승인된다. lease가 4항의 CORE 쪽 주인이고, lease만 켜고 통행권을 끄면 D-760 2단계 뒤 차로 로봇이 `authority_none`으로 서기 때문이다. 이동은 D-760의 단계 일정을 그대로 따르고 이 기록이 더 조이지 않는다. 거절 코드는 D-760 7항의 `422 LINK_UNBOUNDED_MOTION`을 쓰고 새 코드를 만들지 않는다. 로봇 능력과 규제 능력의 조건은 개정 2 질문 10 (b)·(c)다: 필요한 능력을 알리지 않는 옛 릴리스에는 다단계 종류를 내놓지 않고, 경로가 횡단보도·신호 장소를 지나는데 그 능력이 꺼진 로봇의 단계는 거절한다.

- **작업의 움직임은 규칙 M이 본다.** 규칙 M(`fleet/traffic/rule_m.py` `verdict`)은 열린 trip 보기와 콘솔 목표 기록만 입력으로 받는다. 작업의 운행 단계는 그 둘 가운데 하나로 나타나야 한다(운행 단계는 trip이므로 trip 보기, 자유 구간 목표는 목표 기록). 작업 전용 움직임 기록을 따로 두면 규칙 M이 로봇을 `idle`로 보고 6단계의 거절이 그 움직임을 놓친다. 이것을 요구로 두고 조각 7의 시험에 넣는다.

**6. 이동의 길은 하나다.** 새 작업의 "이동"은 관제 로봇 카드, 현장 지도와 같은 trip을 만드는 세 번째 입구다. 같은 계획 경로, 같은 시작 검사, 같은 lease, 같은 구역 판정을 쓴다. 이동을 위한 새 Fleet 경로, 새 원장 행, 새 "busy" 검사는 만들지 않는다.

- 다단계 종류의 운행 단계도 trip이다. D-420 §1의 `NAVIGATE_TO_POSE`·`FOLLOW_LANE_TO_STOPLINE`을 현장 이동의 단계로 쓰지 않는다. 한 로봇에 trip 하나(D-517 1항)와 통행권·구역 표가 trip을 전제로 하기 때문이다. D-420은 Proposed이므로 이것은 그 기록에 대한 조정 제안이다(바뀌는 항).
- **작업의 이동은 운영자 출처로 나가지 않는다.** 목표 임대의 `operator` 출처는 그 이름 있는 운영자의 콘솔이 자리에 있을 때만 갱신된다(D-550 10, `server/goal_lease.py`의 presence). 승인한 사람이 자리를 뜨면 작업의 이동 단계가 임대 만료로 선다. 그래서 작업이 내는 목표(trip의 자유 구간 포함)는 `dispatch`처럼 "그 시도가 열려 있는 동안" 갱신되는 출처로, correlation id를 붙여(D-316) 나간다. trip 루프가 내는 목표는 지금 `trip` 출처이고 trip이 열려 있는 동안 갱신되므로 이 요구를 이미 만족한다. 작업 층이 trip 밖에서 목표를 직접 내는 경우가 생기면 `operator` 출처를 쓰지 않는다.
- Task navigate, D-463 `/route`, 콘솔 목표는 지금처럼 남고 새 작업의 종류로 올리지 않는다. D-760 6단계 전에 다시 본다: 6단계가 한도 없는 Fleet 움직임을 거절하면 이 경로들은 임대 있는 목표(`dispatch` 출처, correlation id)를 보낼 때만 계속 동작한다(개정 2, 질문 8).

**7. 승인은 위험으로 정하고 서버가 지킨다.**

- 단계 종류마다 필요한 승인이 등록부(`step_action_kinds.py`)에 적힌다. 값은 둘이다: **한 사람**(이름 있는 운영자가 시작한다)과 **두 사람**(이름 있는 운영자가 승인하고, 제안한 사람과 달라야 한다). 팔을 움직이는 단계는 두 사람이다. 움직임이 운행뿐인 단계는 한 사람이다.
- 작업의 승인은 그 단계들 가운데 가장 엄한 것이다. 이동은 지금과 같고 두 번째 승인을 더하지 않는다. 가져오기는 인계 동작이 팔을 움직이므로 두 사람이다.
- 승인 경로는 `candidate.kind` 글자가 아니라 등록부를 읽어 판정한다. 등록부에 승인 값이 없는 종류는 제안 단계에서 거절한다.
- 계약 시험: 등록된 모든 종류가 승인 값을 갖는다. 두 사람 종류를 제안한 사람이 승인하면 403이다. 모르는 종류는 거절된다. 화면은 서버의 답을 보여 줄 뿐이고(D-741 7항) 표를 따로 갖지 않는다.
- 기존 코드 `CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER`는 그대로 둔다. 다른 종류의 코드 이름은 구현 조각에서 API Reference와 함께 정한다.
- 레거시 `PICK_PLACE` Mission의 본인 승인은 실물 하달을 연결하는 조각에서 두 사람 규칙으로 바꾼다. 그 전에는 하달이 없으므로 그대로 둔다(개정 2, 질문 5).

**8. 기다림은 진행도 개입도 아니다.** 작업 목록과 관제는 작업을 다섯 가지로 보여 준다.

| 보이는 상태 | 뜻 | 지금 원장에서 |
|---|---|---|
| 승인 대기 | 두 사람 승인이 필요한데 아직 없다 | `PROPOSED` |
| 진행 중 | 단계가 실행 중이고 로봇이 나아간다 | `READY`·`RUNNING`·`ACTION_SUCCEEDED`, trip `started`·`running` |
| 기다림 | 규칙이나 도움 요청 때문에 서 있다. 사람이 할 일은 없다 | trip이 열려 있고 아래 기다림 조건이 참 |
| 개입 필요 | 사람의 답이 있어야 다음으로 간다 | `HOLD`, trip `stopped`·`failed`, 재계획 확인 대기, 해결기의 사람 단계 |
| 끝남 | 완료 또는 취소 | `GOAL_CONFIRMED`(마지막 단계), trip `arrived`·`canceled` |

- **제안(읽기 계약, 추가):** 작업 요약 행에 보이는 상태와 기다림 사유를 싣는다. 사유는 두 갈래다. `regulation`: `signal`, `crosswalk`, `authority`, `traffic_zone`. `robot_help`: 막힘 해결기가 규칙·모델 단계에서 묻고 있다. 필드 이름과 값은 구현 조각의 API 버전·SRS `UI-WORK-001` 변경에서 확정한다.
- **규제 정지는 trip의 끝이 아니다.** 횡단보도에서 보는 중·기다리는 중, 신호 대기, 통행권 대기는 기다림이고 trip을 끝내지 않는다. 지금은 그렇지 않다: 차로 규제 세션은 SIM에서 `crosswalk_blocked`가 trip을 끝내 정체로 간 것을 보았다. 저장소에서 확인한 것은 `crosswalk_blocked`가 CORE 횡단보도 게이트가 `crosswalk_report_s` 뒤 여는 D-407 막힘 원인이라는 것까지다(`middleware/drive/behaviors/line_follow/crosswalk/gate.py`, `recovery/stuck/stuck_recovery.py`). 그것이 trip을 끝내는 경로는 이 기록에서 재현하지 않았다.
- **사유의 목록과 상한은 차로 규제 작업이 소유한다.** 최종 목록은 D-573·D-525 개정에 실리고 이 기록은 그것을 참조한다. 이 기록은 두 갈래와 아래 두 규칙만 고정한다. 그 세션의 초안 상한(참고, 결정 아님):

  | 사유 | 초안 상한 | 근거 |
  |---|---|---|
  | 횡단보도 보는 중·기다림 | `report_s + clear_s`(CORE 설정) | D-573 개정 3 |
  | 신호 빨강 | 신호 한 주기 | D-525, `signal_service` 주기 |
  | 통행권이 FREE가 아님 | lease TTL | D-517 | D-760 4항의 `link_wait`가 만들어지면 같은 "기다림"에 든다.
- 원장의 상태 값은 바꾸지 않는다. 보이는 상태는 읽기 투영이다(D-664 5항).
- **기다림과 정체는 같은 함수가 가른다.** "지금 기다리는 중인가"를 판정하는 함수가 하나이고, 화면의 기다림 표시와 trip 정체 시계가 그 함수를 같이 쓴다. 화면이 기다림이라고 보이는 동안 정체 시계는 가지 않는다. `_stalled`의 조건 넷에 횡단보도 게이트 대기와 신호 대기를 더하는 일은 차로 규제 세션이 맡는다(이 기록의 조각 밖, 아래 "밖의 조각").
- **기다림에는 끝이 있다.** 사유마다 상한을 두고, 넘으면 개입 필요가 된다. 상한 없는 사유는 넣지 않는다.

**9. 화면은 실행할 수 있는 것만 보여 준다.**

- **새 작업.** 종류 목록은 서버가 준다. 이 현장과 배포 프로필에서 하달이 열려 있고 필요한 능력을 가진 장치가 있는 종류만 온다(`step_action_kinds.open_kinds`와 trip 가능 여부). 열리지 않은 종류는 목록에 없다. 꺼진 단추나 "준비 중" 표지로 보여 주지 않는다. **제안:** 종류 목록을 주는 읽기 하나(추가). 경로와 모양은 구현 조각에서 정한다.
- **종류별 표시.**

| 종류 | 새 작업 | 승인 대기 | 전체 작업·끝난 작업 |
|---|---|---|---|
| 이동 | 로봇, 목적지, 경로 보기, 운행 시작(로봇 카드와 같은 폼) | 나오지 않는다(한 사람) | 출처 `trip` 행 |
| Cell 적재 | 지금의 Cell 문서(`/console/cell`) | 제안한 사람이 아닌 이름 있는 운영자에게 나온다. 제안한 사람에게는 막힌 단추와 이유 | 출처 Cell Job 행 |
| 파지·배치(고정) | 올리지 않는다 | 지금의 본인 `PICK_PLACE` 행 | 지금과 같다 |
| 가져오기 | 열릴 때까지 없다 | 열리면 두 사람 | 열리면 단계별 진행 |

- **제안(읽기 계약, 추가):** `GET /api/fleet/work`의 출처에 trip과 Cell Job을 더한다. 승인이 필요한 작업의 요약 행은 제안한 사람이 아닌 이름 있는 운영자에게도 보인다. 계획·후보·요청 본문은 지금처럼 목록에 싣지 않는다. 그 행의 제안자 신원은 커밋되는 화면 사진, fixture, 로그에 남기지 않고 시험은 자리표시 신원을 쓴다(개정 2, 질문 6). 이것은 D-741 7항의 "API는 바꾸지 않는다"와 D-664 5항의 소유 범위를 고친다(바뀌는 항).
- **승인 대기에서의 승인과 거절(개정 2 보충).** 승인 대기에서 승인하면 확인을 한 번 묻는다. 대화 요청 검토는 이미 확인을 묻고(`channel-request-view.js`), Cell 문서의 직접 승인은 대화 요청에 연결된 작업일 때만 묻는다(`cell/cell.js`). 승인 대기는 대화 요청 검토 쪽에 맞춘다. 대화 요청에 연결된 작업은 승인 대기에서 바로 승인하지 않고 대화 요청 검토로 보낸다. 지금 서버는 그런 작업도 요청 내용 확인 없이 바로 승인할 수 있다(위험 표).
- 작업 한 건의 오른쪽 칸은 단계 목록, 지금 단계, 보이는 상태와 사유, 주인(누가 시작했고 누가 승인했는가)을 보인다. 수락, 동작 성공, 목표 확인은 지금처럼 다른 줄이다(`UI-WORK-001`).

**10. 단계 사이의 상태는 누가 갖는가.** 토론에서 나온 반대는 "조합이면 '물체를 든 채 주행 중'을 누가 갖는가, Fleet이 몇 초 끊기면 물체를 든 로봇은 무엇을 하는가"였다. 저장소가 답하는 부분과 답하지 못하는 부분을 나눈다.

- **먼저 팔이 어디에 있는가.** 팔이 로봇에 장착된 이동 조작은 D-55가 접근·파지·운반·배치를 로봇 로컬 transaction 하나로 정했고, D-664 3항은 장착이나 UI 묶음만으로 그 기능을 켜지 않는다고 했다. 그 경우 Fleet은 단계를 잇지 않고 Device Action 하나를 하달한다. 이 기록의 조합은 **운반 로봇과 고정 팔의 인계**에만 쓴다(D-664 5항이 후속 실행 계약을 그 한 가지로 한정했다).
- **저장소가 답하는 것.** "물체를 든 채 주행 중"은 사실 셋이고 주인이 각각 있다.

| 사실 | 주인 | 근거 |
|---|---|---|
| 물체가 어디에 있고 작업이 몇 번째 단계인가 | Fleet 원장(`object` claim, Step 원장). 디스크에 남고 Fleet 재시작 뒤에도 있다 | D-330, D-403 |
| 로봇이 짐을 실었다는 것과 그때의 몸체·속도 한도 | 로봇. 상태별 footprint·속도 프로필. 모르면 재시작·끊김 뒤 HOLD | D-55 |
| 누가 이 로봇을 쥐는가 | Fleet claim과 CORE lease | 4항 |

- **몇 초 끊김.** 물체를 실은 운행 단계도 trip이므로 D-760 1항이 그대로 적용된다. 0–5 s는 받은 통행권 끝까지 가고, 5–8 s는 서서 기다리고, 8 s를 넘으면 lease가 만료해 로봇은 IDLE이 되고 trip이 `lease_lost`로 끝난다. 그때 단계는 실패이고 작업은 HOLD다. Fleet은 마지막으로 확인된 갱신에서 8 s 뒤에 `lease_lost`를 선언하므로 CORE의 만료보다 조금 이르다. 그 순간 로봇이 IDLE이라고 가정하지 않고, 다시 닿으면 로봇 상태를 읽어 확인한다. HOLD에서 다시 가는 것은 자동이 아니다: 재승인 뒤 새 lease를 열고 출발 검사를 다시 한다. lease가 만료하는 순간 Fleet은 사건을 열고 사람·AI PC 경로에 알리며, 작업의 HOLD와 claim을 그 사건에 묶는다(개정 2, 질문 3). 사람에게 닿지 않는 HOLD를 남기지 않는다. 로봇은 물체를 실은 채 서 있다. 스스로 돌아가거나, 내려놓거나, 다시 출발하지 않는다. Fleet 쪽 claim은 풀리지 않는다. 팔 단계 중의 끊김은 팔 owner가 자기 규칙으로 끝내거나 서고(D-403), Fleet은 돌아온 뒤 대조만 하고 다시 보내지 않는다.
- **저장소가 답하지 못하는 것(가져오기를 막는다).**
  1. 단계 사이 IDLE에서 CORE가 주인을 아는 방법이 없다(4항의 제안이 착지해야 한다).
  2. lease가 만료한 뒤 물체를 실은 로봇을 누가 움직이는가 — 개정 2 질문 3이 정했다: 로봇은 IDLE이고 사람이 가져갈 수 있다. Fleet은 그 순간 사건을 열어 사람·AI PC 경로에 알리고, 작업의 HOLD와 claim을 그 사건에 묶는다.
  3. 인계의 증거가 없다. D-420 §1.2는 Pinky–OMX 인계를 `robot_state`만으로 확인하지 않고 인계 ADR이 정한다고 했다. 그 ADR은 제목 검색으로 찾지 못했다.
  4. 짐을 실은 상태의 측정된 프로필이 없다. D-55 구현 노트는 `carrying_box`를 포함한 모든 상태가 기본으로 미측정이라고 적는다.
- 그래서 **가져오기는 열지 않고 이동은 진행한다.** 이동에는 단계 사이가 없다.

### 하지 않는 것

1. **작업 사이의 우선순위와 끼어들기.** "로봇마다 작업 하나, 끼어들기 없음"만 고정한다. 대기 줄, 급한 작업, 충전 복귀와의 순서는 정하지 않는다.
2. **파지·배치의 성공 기준.** 어떤 센서와 어떤 증거 형식으로 "집었다", "놓았다"를 판정하는지 정하지 않는다. 장치 증거 없이 정하면 SIM에서만 맞는 기준이 굳는다. Cell의 지금 목표 증거 경로는 건드리지 않는다.
3. **단계 도중 실패 뒤의 자동 재시도와 되감기.** 반쯤 옮긴 물체를 자동으로 되돌리거나 같은 단계를 자동으로 다시 하는 규칙을 만들지 않는다. HOLD와 사람의 재승인뿐이다.
4. **로봇이 자기 지도 위치를 안다는 전제.** 파지 정렬이나 인계 자리 맞춤에 로봇의 현장 자세를 쓰는 것은 정하지 않는다. D-758은 Proposed이고 코드가 없다.
5. **장착 팔의 이동 조작.** D-55의 로컬 transaction과 D-71의 복합 Asset 범위는 그대로다.
6. **작업 템플릿을 사용자가 만드는 기능.** 종류는 코드에 등록된 것뿐이다.
7. **Step 원장의 schema.** `CHECK(action_kind=...)`를 푸는 방법과 이관은 D-420 §3의 요구 S1–S12와 그 소유자가 정한다. 이 기록은 그 원장에 운행 단계가 들어갈 수 있어야 한다는 요구만 더한다.

### 바뀌는 항

아래는 제안이다. 이 기록이 Accepted가 되고 해당 조각이 착지할 때 바뀐다. 그 전에는 각 기록의 원문이 그대로 유효하다. 다른 기록의 Status는 이 기록이 바꾸지 않는다.

**Accepted 기록.**

| 기존 | 바뀌는 항 |
|---|---|
| D-741 | 7항 "앞의 셋은 지금의 `GET /api/fleet/work` 결과를 화면에서 상태로 거른 것이다. API는 바꾸지 않는다" → 조회의 출처에 trip과 Cell Job이 더해지고 보이는 상태·기다림 사유가 실린다. `새 작업`은 Cell 문서 하나가 아니라 서버가 준 종류 목록이고 Cell 문서는 그 가운데 하나다. `/console/cell` 주소는 그대로다 |
| D-664 | 5항 "기존 Mission 상세의 principal 소유 범위를 유지" → 두 사람 승인이 필요한 작업의 요약 행은 다른 이름 있는 운영자에게도 보인다. 상세와 본문의 소유 범위는 그대로다. SRS `UI-WORK-001`과 API v1.208 절을 같이 고친다 |
| D-403 | 승인 규칙 "승인자는 제안자와 달라야 한다"가 Cell Job 한 종류의 규칙에서 등록부의 "두 사람" 값을 가진 모든 종류의 규칙이 된다. Cell Job의 동작은 바뀌지 않는다 |

**Proposed 기록에 대한 조정 제안.**

| 기존 | 조정 |
|---|---|
| D-420 | §1의 `NAVIGATE_TO_POSE`·`FOLLOW_LANE_TO_STOPLINE`을 현장 이동의 단계로 쓰지 않고 trip을 운행 단계로 쓴다. `DOCK`·`UNDOCK`, §1.1–§1.2, §2–§5는 그대로 둔다. Nav2가 있는 프로필에서 `NAVIGATE_TO_POSE`가 필요한지는 D-420이 다시 본다 |
| D-541 | 5항 "IDLE로 감 → `mode_left`로 lease 끝" → 작업이 쥔 lease는 그 작업의 단계 사이 IDLE에서 끝나지 않는다. 나머지 끝 사유와 "멈춤은 누구나"는 그대로다 |
| D-494 | 5항 trip 상태기계에 "기다림"이 읽기 값으로 더해지고, 정체 판정이 8항의 함수를 쓴다. 상태 값 넷은 그대로다 |
| D-573 | 4항의 "게이트 대기는 정체로 세지 않는다"를 차로 규제 세션이 8항의 함수 안에서 구현한다(밖의 조각 A). 뜻은 같다 |

D-12, D-55, D-330, D-438, D-517, D-577, D-622, D-760은 그대로 따른다.

### Consequences

- 이동은 서버 변경 없이 새 작업에 들어갈 수 있다. 가져오기는 CORE 계약 변경, 인계 ADR, 측정된 짐 프로필 뒤로 밀린다.
- 종류를 더하는 일이 등록부 한 줄과 단계 어댑터가 되고, 승인 규칙이 그 줄에 같이 적힌다. 승인 검사가 종류 이름에서 떨어진다.
- "주인이 있는가"를 묻는 곳이 일곱에서 하나가 된다. 줄 수가 줄어드는 조각이다.
- `GET /api/fleet/work`가 넓어진다. API 버전 하나, schema, SRS, 화면 시험이 같이 바뀐다.
- 다른 사람의 승인 대기 작업이 이름 있는 운영자에게 보인다. 요약 행뿐이지만 소유 범위를 처음 넓힌다.
- 기다림 사유마다 상한을 정해야 한다. 정하지 못한 사유는 기다림으로 넣을 수 없고 지금처럼 정체로 끝난다.

**위험.**

| 위험 | 줄이는 방법 |
|---|---|
| 단계 사이 lease 유지가 "사람이 로봇을 못 가져간다"가 된다 | 넘겨받기와 멈춤은 그대로 열어 둔다. 장치 시험에 넘겨받기를 넣는다 |
| 기다림 함수가 넓어져 진짜 막힘을 기다림으로 본다 | 사유마다 상한. 상한 없는 사유는 거절 |
| 작업 claim이 HOLD에서 로봇을 오래 잡는다 | 운영자 취소가 claim을 놓는다(D-403 보강). 화면에 주인과 HOLD 사유를 늘 보인다 |
| Fleet 크기 한도 때문에 조각이 한도 늘리기로 흐른다 | 조각마다 줄 수 순증 0 이하이거나 날짜 있는 분리 계획을 같이 낸다(D-753) |
| 대화 요청에 연결된 작업이 요청 내용 확인 없이 승인된다(서버가 지금 허용, 주차된 승인 자리 구현 시도에서 발견) | 승인 대기는 그런 작업을 대화 요청 검토로 보낸다(9항). 서버 쪽에서 막을지는 조각 5b에서 정한다 |
| SIM에서만 본 인계가 실물 기준이 된다 | 가져오기의 성공 기준을 이 기록에서 정하지 않는다(하지 않는 것 2) |
| trip과 Cell Job 원장이 한 조회에 들어가 같은 시점이 아닌 행이 섞인다 | 지금 계약대로 원장 사이 동일 시점을 보장하지 않는다고 적고, 행마다 원장 갱신 시각을 보인다 |

### 구현 조각

호스트 pytest 통과는 장치 수용이 아니다. 시험은 원격 시험 PC에서 돌린다(D-584). 장치 단계는 조각마다 따로 수용한다. 모든 조각은 Fleet 크기 단위(D-753)에서 순증 0 이하이거나, 먼저 새 크기 단위를 등록하는 날짜 있는 계획을 낸다.

| 순서 | 조각 | 소유 모듈 | 시험과 관문 | 조건 |
|---|---|---|---|---|
| 1 | "주인이 있는가" 함수 하나로 일곱 검사를 모은다. 동작은 같다 | `operations/fleet/fleet/server/ledger/trip_guard.py`와 부르는 곳 | 호스트: 지금의 trip guard·console·dispatch 시험이 그대로 통과. 줄 수 감소. safety 태그 경로면 Safety-Review. 착지 전에 차로 규제 세션에 알린다 | 없음 |
| 2 | 밖의 조각 A의 기다림 판정을 읽기로 낸다: trip 읽기에 기다림과 사유, 상한을 넘으면 개입 | `ledger/trip_ports.py`, `work_read.py` | 호스트: 사유마다 상한 안에서는 기다림, 넘으면 개입. API 버전(읽기 추가) | 밖의 조각 A, D-573·D-525 개정의 사유 목록 |
| 3 | 새 작업의 "이동" 입구. 로봇 카드와 같은 trip 경로를 부른다 | `operations/site_ui/console`(`shared/site-map-model.js`의 `planTrip`·`startTrip` 재사용) | node 시험, CI 브라우저 시험. 서버 변경 없음. 장치: 새 작업에서 시작한 운행 한 번이 로봇 카드에서 시작한 것과 같은 trip 기록을 남긴다 | 없음(D-741 조각과 같은 자리) |
| 4 | `GET /api/fleet/work`에 trip·Cell Job 출처와 보이는 상태, 승인 대기의 소유 범위, 종류 목록 읽기 | `work_read.py`, `work_routes.py`, `core_common.protocol.schemas`, `work-view.js` | 호스트: 출처별 행, 권한(viewer·운영자·제안자·다른 운영자), 원장 미설정. SRS `UI-WORK-001`, API 버전, API Reference. 화면 시험 | 2(기다림 값) |
| 5 | 등록부의 승인 값과 승인 경로의 등록부 판정, 계약 시험 | `step_action_kinds.py`, `ledger/mission_routes.py` | 호스트: 7항의 계약 시험. Cell Job 승인 시험이 그대로 통과 | 없음 |
| 5b | 기다리는 작업의 거절 경로(제안): 상태, 누가 할 수 있는가, 감사 기록. 지금 서버에 없다: Cell 취소는 `PROPOSED`를 거절하고(`cell/cell_job_store.py` `cancel`), 팔 Mission에는 취소 경로가 없고, Task는 승인을 기다리지 않는다 | `cell/cell_job_store.py`, `ledger/mission_routes.py` | 호스트: 거절 뒤 승인 불가, claim 없음, 감사 행, 권한(제안자·다른 운영자·viewer). API 버전, API Reference, SRS | 없음 |
| 5c | 승인 대기의 승인·거절 자리(화면) | `operations/site_ui/console/work-view.js` | node 시험, CI 브라우저 시험: 확인 한 번, 대화 요청 연결 작업은 요청 검토로, 제안자에게는 막힌 단추와 이유, 자리표시 신원 | 4(작업 읽기에 Cell Job·trip 출처)와 5b. 한 번만 만들려고 둘이 착지할 때까지 미룬다. 주차된 시도 브랜치 `feat/fleet-work-approval-seat`가 있다 |
| 6 | 작업이 쥔 lease의 단계 사이 유지(CORE)와 작업의 `robot` claim(Fleet) | `middleware/core/gateway/core/trip_lease.py`, Fleet `traffic/trip_lease.py`, `dispatch_admission.py` | Safety-Review. 시작 전에 D-760 담당 세션에 알린다. API 버전. 호스트: 단계 사이 IDLE에서 주인 아닌 `/mode`·`/teleop` 409, 넘겨받기와 멈춤은 통과, 만료는 지금과 같다, trip 루프를 멈추면 작업 claim이 있어도 통행권·목표 임대가 만료한다(4항 굳은 규칙), 팔 동작 중 lease 만료의 정지. SIM: 원격 Gazebo에서 단계 사이에 다른 입구가 거절된다. 장치: 실물 로봇에서 단계 사이에 Pilot이 거절되고 넘겨받기는 된다 | 개정 2 질문 2의 조건 (a)–(e), D-760 2·3단계 착지 |
| 7 | 운행 단계가 Step 원장에 들어간다(trip을 단계로 쓰는 어댑터) | D-420 §3의 원장 소유자, `step_dispatcher.py` | 호스트: `arrived`만 다음 단계로, 다른 끝은 HOLD(사유), 재승인이 새 lease와 출발 검사로 새 trip을 연다, Fleet 재시작 뒤 자동 재출발 없음, 작업의 움직임이 규칙 M에 trip 보기나 목표 기록으로 보인다, 작업이 내는 목표가 `operator` 출처가 아니다 | 6, D-420 §3의 원장 확정 |
| 8 | 가져오기 종류(운반 로봇 ↔ 고정 팔 인계) | 인계 ADR이 정한다 | SIM: 원격 Gazebo에서 운행 → 인계 → 운행, 단계마다 끊김 3 s·6 s·9 s. 장치: 별도 결정 | 6, 7, 인계 ADR, 측정된 짐 프로필, 하지 않는 것 2의 기준 |

1·3·5·5b는 서로 기다리지 않는다. 조각 4는 Cell Job과 trip을 작업 읽기에 더하는 조각이고, 승인 자리(5c)는 그것과 5b를 기다린다. Cell 제안은 서비스 계정만 할 수 있어(`mission_routes.py`) 사람은 Cell Job의 제안자가 되지 않는다. 이동은 3과 4가 착지하면 새 작업에서 시작하고 목록에서 보인다.

**밖의 조각(이 기록이 소유하지 않는다).**

| 조각 | 소유 | 내용 | 조건 |
|---|---|---|---|
| A | 차로 규제 세션 | `_stalled`에 횡단보도 게이트·신호 대기 예외를 더하고 규제 정지가 trip을 끝내지 않게 한다. 별도 브랜치, Fleet 크기 단위 순증 0 | 그 세션의 D-573 개정 5 브랜치 착지 뒤 |
| B | D-760 담당 세션 | D-760 2·3·6단계(통행권 5 s, `link_wait`, 거절, 기본값 켜기) | D-760 일정 |

**의존하는 Proposed 기록.** D-494, D-541, D-573은 Proposed다. 이 기록의 조각이 이들이 먼저 Accepted가 되기를 기다리지는 않는다. 그 코드가 이미 있거나 그 세션이 만든다. D-573은 개정 5의 SIM 바퀴와 장치 조건이 닫힌 뒤에야 Accepted 후보이고, Accepted는 사용자가 정한다. D-420과 D-758도 Proposed이고, 이 기록은 그 둘에 기대지 않는 이동부터 연다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 종류마다 새 Mission 유형과 전용 실행기 | 기각. 결정 값, API 버전 고정, 크기 한도에 한꺼번에 닿고 D-420 §2·§3의 "하나"와 어긋난다 |
| 이동을 위한 새 작업 전용 경로(Task navigate를 넓힘) | 기각. trip lease, 통행권, 구역이 trip을 전제로 한다. 주인 검사가 또 하나 생긴다 |
| 작업 층이 실패한 trip을 다시 연다 | 기각. trip의 끝 사유 대부분은 사람이 봐야 한다. D-494와 D-541이 다시 열지 않기로 했다 |
| 모든 종류에 두 사람 승인 | 기각. 지금의 운행 시작이 느려지고, 위험이 같은 팔 작업과 구별되지 않는다 |
| 승인 규칙을 화면이나 문서의 표로 둔다 | 기각. 서버가 지키지 않는 표는 종류가 늘면 빠진다 |
| 열리지 않은 종류를 꺼진 단추로 보여 준다 | 기각. 실행할 수 없는 것을 할 수 있는 것처럼 보이게 한다. D-741 9항은 점선을 "할 수 없음"과 "정보 없음"에만 쓴다 |
| 단계마다 새 lease를 열고 사이의 틈은 받아들인다 | 기각(권고). 틈에서 다른 입구가 로봇을 가져가면 작업이 물체를 든 채 주인을 잃는다. 개정 2 질문 2에서 기각 |
| 가져오기를 SIM에서 먼저 열고 기준을 나중에 맞춘다 | 기각. 장치 증거 없는 성공 기준이 굳는다 |

### 남은 열린 질문

열 가지 질문은 개정 2에서 정했다. 남은 것은 아래다.

1. **팔 단계 중 lease가 만료하면 CORE와 팔은 무엇을 하는가(팔이 서는가, 든 물체는 어떻게 되는가).** 조각 6의 Safety-Review가 정한다. 정하기 전에는 팔 단계가 든 종류를 열지 않는다.
2. **가져오기를 여는 조각의 검토.** 개정 2 질문 1은 첫 대상을 고정 팔 인계로 정했지만 근거가 약하다. 가져오기를 여는 조각은 D-55·D-664의 팔 문구를 읽은 따로의 검토를 받는다.
3. **기다림 사유의 번호 붙은 목록과 상한.** 차로 규제 작업이 D-573 개정 5 착지 뒤 D-573·D-525 개정에 싣는다. 8항의 초안 표는 그때까지 참고다.
4. **능력 이름의 확정.** 개정 2 질문 10 (b)의 `line_follow_authority_under_lease`는 확정이다(D-760 2단계, API v1.226, `core_common/protocol/controls.py`). (c)의 횡단보도 게이트·교차로 신호 능력은 차선·규제 작업이 `lane_crosswalk_gate`(CORE `line_follow.crosswalk_gate_enabled`가 켜졌을 때만 참)와 `lane_junction_signal`(`junction_signal_enabled`가 켜졌을 때만 참)로 정했고, 아직 코드에 없다. API 버전을 올리는 그 작업의 브랜치에서 확정한다.

### 근거의 경계

- 이 기록의 사실은 2026-10-14 워크트리 `e8bcc99a5`의 코드와 ADR을 읽은 것이다. 실행한 시험, SIM, 장치 확인은 없다.
- 확인 못 함: SIM에서 `crosswalk_blocked`가 trip을 끝낸 경로(차로 규제 세션의 관측), D-760 2단계 브랜치의 내용, D-420의 일부가 다른 이름으로 구현됐는지, API 버전 고정이 아홉 곳인지, 횡단보도 대기 중 `stall` 종료의 재현, 콘솔 쪽 크기 단위의 남은 여유, Pinky–OMX 인계 ADR이 다른 제목으로 있는지.
- Accepted가 되어도 구현, 원격 시험, 설치, 현장 수용은 조각마다 따로다.

### 개정 1 (2026-10-14) — 검토 반영

| 지적 | 고친 곳 |
|---|---|
| 규제 정지는 trip의 끝이 아니라 기다림이다. SIM에서 `crosswalk_blocked`가 trip을 끝냈다 | 8항 |
| 사유 목록과 상한은 차로 규제 세션이 소유한다(초안 상한) | 8항, 열린 질문 9 |
| `_stalled` 예외는 차로 규제 세션의 별도 브랜치다 | 조각 2, 밖의 조각 A |
| 주인 함수 조각 착지 전에 알린다 | 조각 1 |
| D-494·D-541·D-573은 Proposed 의존이다 | 의존하는 Proposed 기록 |
| 작업의 주인은 움직임 한도를 늘리지 않는다 | 4항 굳은 규칙, 조각 6, 열린 질문 2 |
| D-760 2단계와 `core/trip_lease.py`, 팔 동작 중 만료 | 4항, 조각 6 |
| D-760 단계별 상태, lease와 통행권 둘 다 켜기 | Context 6, 5항, 열린 질문 10 |
| `lease_lost` 선언 시점과 다시 닿을 때의 확인, 재개는 새 lease와 출발 검사 | 10항, 조각 7 |
| 작업의 이동은 `operator` 출처가 아니다 | 6항, 조각 7 |
| 규칙 M이 작업의 움직임을 본다 | 5항, 조각 7 |
| 고정 팔 판단은 D-760 담당 세션이 검토하지 않았다 | 열린 질문 1 |

### 개정 2 (2026-10-14) — 열린 질문의 결정

사용자가 열린 질문 열 가지를 세션 토론으로 정하라고 위임했다. 토론 참여 세션 셋이 표를 냈다. 아래가 결정이고, 이 결정으로 Status를 Accepted로 바꾼다. "바뀌는 항" 표는 적힌 대로 효력을 갖는다. 다른 기록의 파일은 이 개정에서 고치지 않는다. Accepted는 구현·원격 시험·설치·현장 수용이 아니다.

| 질문 | 결정 | 표(찬성·약한 찬성 / 기권 / 반대) | 본문에서 |
|---|---|---|---|
| 1 가져오기의 첫 대상 | 고정 팔 인계. 장착 팔은 D-55에 남는다. 근거가 약하다: 어느 세션도 D-55의 팔 문구를 읽지 않았다. 가져오기를 여는 조각은 따로 검토한다 | 약한 찬성 1 / 기권 2 / 반대 0 | 10항, 남은 질문 2 |
| 2 작업 동안 lease 하나 | 채택. 조건: (a) 움직임 한도는 그 일을 하는 루프만 늘린다, 작업 heartbeat 없음(4항 굳은 규칙). (b) 작업 lease는 D-760 3단계 규칙을 탄다: trip lease `ttl_s` 기본 8 s, 끊긴 lease trip은 `link_wait`에서 기다리고 lease 갱신 실패(`lease_lost`)로만 끝난다(다른 브랜치에서 구현 중). (c) 같은 Safety-Review가 팔 단계 중 lease 만료의 정지를 정한다(남은 질문 1). (d) 횡단보도·신호·통행권 대기로 서 있는 시간은 D-507 부기 13(뒤 게이트가 가져간 시간)처럼 그 단계의 시간 계산에서 뺀다. 대기만으로 단계 시계가 끝나지 않는다. 대기의 상한은 질문 9의 목록에서 온다. (e) D-762 0단계가 착지하면 Safety-Review trailer 없는 착지가 착지 전 오류가 되므로 조각 6은 그것 없이 착지할 수 없다 | 3 / 0 / 0 | 4항, 조각 6 |
| 3 물체를 든 채 lease 만료 | 반대 의견의 대안을 찬성표와 합쳐 채택. lease가 만료하면 로봇은 IDLE이 되고 사람이 가져갈 수 있다(지금과 같음). Fleet은 그 순간 사건을 열고 사람·AI PC 경로에 알린다. 작업의 HOLD와 claim은 그 사건에 묶인다. HOLD에서 다시 가는 것은 자동이 아니다: 새 lease, 새 출발 검사, 7항의 재승인 | 2 / 0 / 1 | 10항 |
| 4 이동에 두 번째 승인 | 두지 않는다 | 2 / 1 / 0 | 7항 |
| 5 레거시 `PICK_PLACE`의 본인 승인 | 실물 하달을 연결하는 조각에서 두 사람 규칙으로 바꾼다 | 1 / 2 / 0 | 7항 |
| 6 승인 대기의 남의 제안 | 요약 행을 이름 있는 운영자에게 보인다. 공개 저장소이므로 그 행의 제안자 신원이 커밋되는 화면 사진, fixture, 로그에 남지 않게 한다. 시험은 자리표시 신원을 쓴다 | 1 / 2 / 0 | 9항 |
| 7 실패 횟수 | 작업 층은 실패 한 번이면 사람이다. "두 번"은 막힘 해결기 안(D-622)에만 둔다. 규제 대기(횡단보도 보는 중·기다림, 신호 빨강, 통행권 FREE 아님)는 실패가 아니라 기다림이다. 기다림이 상한을 넘으면 먼저 막힘 해결기로 가고, 해결기가 사람에게 넘긴 것만 작업의 실패 한 번으로 센다. 차로 규제 세션의 SIM 보고: 지금 `crosswalk_blocked`는 곧바로 콘솔로 가 trip을 정체로 끝냈다(같은 횡단보도에서 두 번). 밖의 조각 A가 고친다 | 3 / 0 / 0 | 3·8항 |
| 8 Task navigate와 `/route` | 남기고 새 작업에 올리지 않는다. D-760 6단계 **전에** 다시 본다(정정 의견 채택): 6단계 뒤에는 임대 있는 목표(`dispatch` 출처, correlation id)를 보낼 때만 동작한다 | 2 + 정정 찬성 1 / 0 / 0 | 6항 |
| 9 기다림 사유와 상한의 소유 | 차로 규제 작업. 초안 상한 표는 참고로 남고, 번호 붙은 목록은 D-573 개정 5 착지 뒤 온다 | 3 / 0 / 0 | 8항, 남은 질문 3 |
| 10 다단계 종류의 조건 | (a) 현장 설정: trip lease와 통행권(`fleet.traffic.authority`) 둘 다 켜짐. (b) 로봇 능력: `trip_lease`, `goal_lease`, 그리고 `line_follow_authority_required` 또는 `line_follow_authority_under_lease`(D-760 2단계, API v1.226)를 알린다. 옛 릴리스에는 다단계 종류를 내놓지 않는다. (c) 단계의 경로가 횡단보도나 신호 장소를 지나면 그 로봇의 CORE 능력에 횡단보도 게이트와 교차로 신호가 켜져 있어야 하고, 아니면 Fleet이 그 단계를 거절한다(규제 규칙이 조용히 빠지지 않게). 앞의 셋(`trip_lease`, `goal_lease`, `line_follow_authority_required`)은 `controls.py`에 있다. 나머지 이름은 제안이고 해당 조각에서 확정한다 | 2 + 추가 2 / 0 / 0 | 5항, 남은 질문 4 |

**승인 자리 구현 시도에서 나온 것(같은 개정).** 주차된 브랜치 `feat/fleet-work-approval-seat`의 시도가 찾은 사실을 저장소에서 확인했다. (1) 기다리는 작업을 거절하는 서버 경로가 없다 → 조각 5b. (2) Cell Job은 `/api/fleet/work`에 나오지 않고 Cell 제안은 서비스 계정만 한다 → Context 2와 같은 빈틈, 조각 4가 메우고 승인 자리(5c)는 그것을 기다린다. (3) 팔 Mission의 승인은 제안자만 한다(다른 사람에게 404) → 7항과 질문 5 결정 그대로. (4) 승인 대기의 승인은 확인을 한 번 묻는다 → 9항. (5) 대화 요청에 연결된 작업은 승인 대기에서 요청 검토로 보낸다 → 9항, 위험 표.

**질문 3의 반대 의견과 그것이 이긴 이유.** 찬성 둘은 "IDLE로 두고 Fleet 쪽 HOLD로 남긴다"였다. 반대 하나는 사용자 규칙("로봇의 문제는 Fleet을 거치고 AI PC가 판단한다, 막힌 로봇을 내버려 두지 않는다")을 들었다. 그리고 바로 전날 검토가 같은 꼴(사람에게 닿지 않는 HOLD)을 결함으로 잡았다고 했다. HOLD만 남기면 물체를 실은 로봇이 아무에게도 알려지지 않은 채 서 있을 수 있다. 그래서 IDLE과 "사람이 가져갈 수 있다"는 찬성표대로 두고, 사건을 열어 알리는 것을 더했다.

**질문 7·2와 정체.** 기다림 시간을 단계 시계에서 빼는 것(질문 2 (d))과 기다림이 상한을 넘으면 해결기로 가는 것(질문 7)은 같은 기다림 판정 함수(8항)를 쓴다. 상한 없는 기다림은 여전히 없다.

**다른 기록에 남길 가리킴.** 이 개정은 다른 기록의 파일을 고치지 않는다. D-741, D-664, D-403의 해당 항과 D-420, D-541, D-494, D-573에는 착지 뒤 "D-763이 이 항을 바꾼다"는 한 줄을 따로 더한다.

> 2026-10-14 부기(조각 1·3 착지): 조각 1의 "주인이 있는가" 함수는 `trip_guard.py`가 아니라 `operations/fleet/fleet/server/console/console_view.py`의 `trip_refusal()`이다. trip 감시가 설치되지 않은 콘솔에서도 답하고, 안전 경로 파일에 새 import가 필요 없어서다. `trip_runner.py`의 시작 거절(콘솔이 이미 움직이는 로봇)은 반대 질문이라 합치지 않았다. 조각 3은 브라우저 콘솔을 별도 크기 단위 `site_ui/console`로 등록한 뒤 들어갔다([계획](../plans/2026-10-14-fleet-console-size-unit.md)).

> 2026-10-14 부기(조각 2): 기다림 사유와 상한은 `operations/fleet/fleet/server/ledger/trip_progress.py` `_wait_bound`에 있다(`link_wait`·`authority` = lease ttl, `signal` = `stall_s`, 횡단보도 `crosswalk_look`·`crosswalk_wait`·`crosswalk_held` = 15 s `CROSSWALK_WAIT_S`). CORE는 사유를 `line_follow.regulation_wait`(v1.227)로 알린다. 조각 2는 trip 읽기에 `waiting`·`bound_s`·`over_bound`를 낸다(v1.232). 상한을 넘으면 관제는 개입이 아니라 주의 "대기 상한 넘음 · <사유>"를 보인다(개정 2 질문 7).

> 2026-10-15 부기(조각 6, 브랜치 `feat/fleet-job-holds-lease`, 미착지): CORE는 `PUT /trip-lease`의 `job_id`(v1.236)로 연 lease를 단계 사이 IDLE에서 끝내지 않는다(`middleware/core/gateway/core/trip_lease.py` `end_on_mode`). 주인 아닌 토큰의 IDLE·취소·line-follow OFF, MANUAL·도킹, 비상 정지, 넘겨받기, 만료, 주인 해제는 그 lease도 끝낸다. 단계 사이 lease를 갱신하는 주인은 Fleet `traffic/trip_lease.py` `TripLease.period` 하나이고 `/trip-lease`만 보낸다. 통행권은 `AuthoritySender`(열린 trip만), 목표 임대는 trip 루프의 갱신기만 늘린다. 작업의 승인 관문(개정 2 질문 10 (a)(b))과 hold는 `ledger/trip_admission.py` `hold_job`이다(조각 표의 `dispatch_admission.py`가 아니다: claim은 원장이 잡고 Fleet 입구는 `trip_guard`가 내구 `mission` robot claim을 읽는다). Fleet이 보낸 사람의 멈춤은 lease 주인 토큰이라 CORE가 lease를 두므로 Fleet이 `stop_job`으로 놓고 작업을 HOLD로 둔다. 질문 3의 사건 열기는 `TripLease.on_job_lost` hook이고 `hold_job`은 hook 없이 거절한다. hook을 사건·HOLD에 연결하는 것은 작업 원장에 운행 단계가 들어가는 조각 7이다. 질문 10 (c)는 능력 이름이 확정될 때까지 비어 있다. 남은 질문 1(팔 단계 중 만료)은 정하지 않았다: 팔 단계를 가진 종류는 hold하지 않는다. SIM과 장치는 하지 않았다.

> 2026-10-14 부기(개정 2 질문 10 (c), 남은 질문 4): 능력 이름을 `lane_crosswalk_gate`(CORE `line_follow.crosswalk_gate_enabled`가 켜졌을 때만 참)와 `lane_junction_signal`(`line_follow.junction_signal_enabled`가 켜졌을 때만 참)로 확정했다(API v1.238, `core_common/protocol/controls.py`, 설정 기본값은 그대로 꺼짐). Fleet은 trip 시작·다음 바퀴·재계획의 능력 검사(`trip_checks/trip_admission.py` `_caps_checks`)에서 lane 간선이 있는 경로가 현장 지도 횡단보도 다각형(D-573 1)에 들어가거나 신호 구역(D-525 `fleet.traffic.signals`)을 지나는데 로봇이 맞는 능력을 `false`로 알리면 422 `TRIP_REGULATION_CAPS_MISSING` `{missing: {능력: [횡단보도 또는 신호 id]}}`로 거절한다. 작업의 이동 단계는 같은 trip 경로를 타므로 같은 검사를 받는다. 이 필드가 없는 옛 릴리스(능력을 알리지 않음)는 거절하지 않고 경고한다(사용자 결정 2026-10-15): trip detail에 `regulation_caps_unknown {능력: [id]}`를 남기고 Fleet 로그에 경고 한 줄을 쓴 뒤 시작한다. 새 릴리스가 모든 로봇에 깔리면 옛 릴리스도 `false`처럼 거절하도록 좁힌다. 횡단보도도 신호 구역도 지나지 않는 경로는 능력과 상관없이 시작한다. 새 릴리스에서 `junction_signal_enabled`는 기본 꺼짐이므로 신호 구역이 있는 현장은 그것을 켜야 그 구역을 지나는 운행이 열린다.

> 2026-10-15 부기(조각 7, 브랜치 `feat/fleet-job-trip-steps`, 미착지). **사용자 결정: 작게 풀고 진행.** 하지 않는 것 7의 Step 원장 `CHECK(action_kind='CELL_TRANSFER')`를 등록부(`step_action_kinds.py`)의 종류만 받는 `CHECK(action_kind IN (...))`로 바꾼다. 이 기록은 그 CHECK만 푼다. D-420 §3 S1–S12는 맡지 않는다. 같은 원장에 다른 종류 CHECK는 없다(`fleet_cell_jobs`에는 없다). 레거시 `fleet_missions`의 `CHECK(action_kind='PICK_PLACE')`는 Step 원장이 아니라 그대로 둔다. 표 정의는 `cell/cell_job_store.py`에서 `work/step_ledger_schema.py`로 옮겼다. 이미 있는 DB는 store를 열 때 savepoint 하나 안에서 표를 다시 만들고 행을 모두 옮긴다. 이관 버전은 2다. 그래서 옛 Fleet은 이관된 원장을 열지 않고 거절한다. 옛 장치 하달기는 `TRIP` 행을 잘못 읽을 수 있기 때문이다.
>
> 등록부에 `TRIP`(한 사람 승인, `simulation` 프로필만, grant 모델 없음)을 더했다. 장치 하달기(`StepJobDispatcher`)는 grant 모델이 없는 단계를 건드리지 않는다. 운행 단계는 trip 하나이고 따로 움직임 기록을 두지 않는다. 코드는 크기 단위마다 나눠 두었다: 루프 `missions/job_trip_steps.py`, 원장 행 `ledger/job_trip_rows.py`, 입구 `trips/trip_job_routes.py`.
>
> 단계마다 로봇의 지금 자세에서 로봇 카드와 같은 계획 경로(`trip_routes`의 `plan`)로 계획하고, `TripRunner.start(job_id=, start_token=)`로 시작한다. 그래서 시작 검사가 같다. 목표는 `trip` 출처이고 `operator` 출처가 아니다. 규칙 M은 그 단계를 열린 trip으로 본다. 작업은 만들 때 `robot` claim을 잡고(D-420 §4.5), 끝(마지막 단계의 `arrived`, 운영자 취소)까지 쥔다.
>
> 다음 단계로 넘어가는 것은 `arrived` 하나뿐이다. 다른 끝, 거절된 시작, 작업 lease 잃음, 비상 정지, 정지 래치는 작업을 HOLD로 두고 claim을 `HELD`로 두며 lease를 놓는다. lease를 놓을 때 열려 있는 단계 trip은 먼저 끝낸다(`stop_job`). `TripLease.on_job_lost`는 연결돼 있다. lease를 잃으면 그 작업은 HOLD가 원장에 닿기 전에도 표시되고, 루프가 그 HOLD를 본 뒤에야 재개로 새 lease를 받을 수 있다. 로봇이 IDLE이라고 가정하지 않는다(`robot_state: unconfirmed`).
>
> 누가 쓴 HOLD든(정지 래치, 재시작, 이 루프) 사건이 하나 열린다(원장 이벤트 `TRIP_JOB_CASE_OPENED`). 사건은 사람 단계의 문제 기록(`fleet_problem_episodes`, kind `job_hold`, AI PC가 `/api/fleet/ai/episodes`로 읽는다)과 작업 목록의 `개입 필요`다. CORE 막힘 사건의 알림 outbox는 아니다.
>
> 재개는 지금의 `POST /api/fleet/cell-jobs/{id}/resume`(이름 있는 운영자)이다. 재개한 뒤 다음 tick이 새 lease를 받는다(`hold_job`, 질문 10 (a)(b) 관문). 그리고 새로 계획하고, 출발 검사를 거쳐 새 trip을 연다. renew가 두 주기 안에 확인되지 않은 lease로는 새 단계를 시작하지 않는다. 자동 재시도와 다시 열기는 없다. Fleet이 재시작하면 열린 trip 작업은 모두 `FLEET_RESTARTED`로 HOLD된다.
>
> 입구는 `POST /api/fleet/trip-jobs` `{robot_id, steps:[{to, via}]}`이다. 이름 있는 운영자만 쓰고, `simulation` 프로필이며 Step 원장이 있을 때만 있다. `GET /api/fleet/work`의 `kinds`에는 아직 `TRIP`이 없다. 계약의 Literal이 두 값이고 화면 폼도 없다.
>
> **SIM에서 찾아 고친 것: trip 사이의 넘겨받기.** 차로 trip이 `arrived`로 끝나도 CORE는 그 trip의 `stop`을 쥔 채(`executing`) 차선 추종에 남는다. 그 자리에서 시작한 다음 trip(작업의 다음 단계, 운영자의 다음 trip)은 `_core_busy`가 남의 seq를 보고 첫 지시를 보내지 않았다. 그래서 `stall`로 끝났다(AI PC Gazebo r4, main `ccb1a2ae0`). 이것은 SIM 고유가 아니라 Fleet의 trip 사이 넘겨받기 결함이다. 이제 아무 지시도 보내지 않은 trip은 그 로봇의 직전 차로 `arrived`가 남긴 정지 하나만 바꿀 수 있다. 그 정지는 seq와 장소로 기록되고(`TripRunner.held_stops`), 다음 trip이 시작할 때 한 번 쓰이며, 멈춤이나 비상 정지가 오면 지워진다. 그리고 trip의 다음 장소에 있어야 한다(`trip_progress.inherited_stop`). 멈춤이 보낸 정지와 다른 송신자의 지시는 seq가 달라 그대로 기다린다. 저장소에서 CORE `POST /line-follow/junction`을 보내는 곳은 Fleet trip과 Fleet 멈춤뿐이다.
>
> 이 고침 뒤 AI PC Gazebo(2대, `map_v2_fleet`, 조정자 rig의 launch overlay)에서 Fleet API로 두 단계 작업(SW, SE)을 돌렸다. 두 단계 모두 실제로 달려 `arrived`가 되었다. 2단계는 SW의 쥔 정지를 `right` 지시로 바꿔 출발했다. SE는 원형교차로 구역 안이라 D-517 3에 따라 정지가 SW로 옮겨졌다. 작업은 `GOAL_CONFIRMED`가 되었고 CORE lease는 풀렸다(`X:/DevTemp/job-trip-steps/sim/s7-1`). 검토 반영 뒤 HEAD에서 다시 돌렸고 같은 결과였다(s7-2, s7-3). 2단계는 쥔 `stop` seq 5를 `right` seq 6으로 바꿔 출발했다.
>
> 독립 안전 검토를 네 번 받았다. 모두 PASS WITH CONDITIONS였고, 지적은 모두 이 브랜치에서 고쳤다. 비상 정지와 lease 잃음 사이의 경합, 모든 HOLD에 사건 하나, 정지를 넘겨받는 소유 확인, 이관 버전, 재개 이벤트의 중복 지움이다. Cell Job의 재개도 같은 fence에서 두 번째 이벤트가 지워지던 결함을 함께 고쳤다(`approvals`).
>
> 고치지 않고 알린 것: 새 차선 세션(`WAITING no_observation`)에 바로 보낸 bend 지시를 CORE가 `aborted/no_anchor`로 거절하면 trip은 1 s 안에 `junction`으로 끝난다(r3·r5). 이것은 작업과 상관없는 trip 시작 문제다. 장치 시험은 하지 않았다.
>
> **남은 일(조각 7, 2026-10-15, 다른 PC에서 이어 갈 사람에게).** 착지와 푸시는 하지 않았다.
>
> - **한 것.** 위 부기의 코드와 시험. 독립 안전 검토 네 번(모두 PASS WITH CONDITIONS)의 지적을 모두 고쳤다. 마지막 검토의 LOW 셋도 고쳤다: 행을 쓰는 중인 lease는 tick이 건드리지 않는다, 구간이 없는 trip은 쥔 정지를 쓰지 않는다, 사건 중복 방지의 한계를 적었다. Gazebo s7-1·s7-2·s7-3은 모두 통과했다(s7-3은 HEAD `7116504e4`, pop 변경 뒤). 기록은 `docs/validation/d763-trip-steps-sim-2026-10-15/evidence/runs/`에 있다.
> - **남은 것.**
>   1. `7116504e4`의 전체 fleet 원격 실행에서 `test_trip_turn_map_entry.py::test_a_turn_to_a_lane_turn_map_entry_robot_carries_the_exit_lanes_heading_and_the_yaw_pair`가 NEW로 한 번 실패했다. 현장 PC(`robttt`)에서였고, 차이는 `expect_tol_m` 0.128 대 0.129다. 같은 파일이 HEAD `53c056f85`에서 모델 PC·AI PC로 두 번, base `ccb1a2ae0`에서 한 번 통과했다. 이 브랜치는 그 junction `expect` 계산을 바꾸지 않았다. 그래서 호스트에 따라 갈리는 값으로 보고 `known_failures`에는 넣지 않았다. 현장 PC에서 다시 나면 그 시험의 시계·반올림을 본다.
>   2. 끝 커밋에서 `operations/fleet/test/`, `test/architecture/`, `middleware/core/gateway/test/`를 원격으로 다시 돌리고 `test/known_failures.py`와 비교한다.
>   3. `Safety-Review:` trailer는 이 부기 커밋에 달았다. 착지 도구가 다른 커밋을 요구하면 같은 판정을 옮긴다. 마지막 판정은 "PASS WITH CONDITIONS — no regressions that could cause unsafe motion"이고, 조건(s7-3, LOW 셋)은 채웠다. `tools/harness/safety_review.py`는 이 브랜치가 safety 태그 경로를 건드리지 않는다고 본다.
>   4. API 버전 번호와 API Reference 절은 조정자가 정한다(`POST /api/fleet/trip-jobs`).
> - **SIM 확인 실행법.** AI PC(`ai@100.108.76.123`)의 `~/rosy-test/d763-sim`을 쓴다. 조정자 rig(`setup.sh`로 main 빌드와 venv를 만든다)에 `docs/validation/d763-trip-steps-sim-2026-10-15/evidence/rig/`의 s7 파일을 놓는다. 이 브랜치를 `source-s7`에 checkout하고(`git fetch <bundle> HEAD && git checkout FETCH_HEAD`), `setsid nohup bash run-s7.sh <label> &`로 돌린다. 결과는 `artifacts/<label>/S7-timeline.json`과 `probe-result.json`이다. CORE는 main 빌드를 그대로 쓰고 Fleet만 이 브랜치다. 커밋된 `map_v2_fleet_multi_real.launch.py`로는 trip이 모두 stall한다(관측기에 IR 보정이 없다). 그래서 `evidence/rig/multi_real.overlay.launch.py`를 쓴다.
> - **열린 질문.**
>   1. 새 차선 세션(`WAITING no_observation`)에 바로 보낸 bend를 CORE가 `aborted/no_anchor`로 거절해 trip이 1 s 안에 끝난다(조정자 r3·r5). trip 시작 문제이고 이 조각 밖이다.
>   2. 사건은 문제 기록과 작업 목록의 `개입 필요`다. 팀 알림 outbox로도 보낼지는 정하지 않았다.
>   3. `GET /api/fleet/work`의 `kinds`에 `TRIP`을 더하는 일(계약 Literal, 화면 폼)이 남았다.
>   4. Cell Job 재개 이벤트에 `approvals`를 더했다. 같은 fence에서 두 번째 재개가 지워지던 결함의 수정이고, Cell 쪽 소유자에게 알릴 일이다.
