# D-420 Pinky Device Action — 조정 질문

**근거:** [D-420](../adr/D-420-fleet-pinky-device-actions-multi-step-missions.md)(Proposed, 개정 2) §2·§3·§4·§7.
**전달:** controller가 보낸다. 답은 번호별로 받는다.

## 현재 사실 (2026-10-02)

- C4는 D-413 Task 5 착지까지 멈춰 있다. Step 표 schema는 확정되지 않았다.
- rosy-0d는 Pinky Step이 C4의 Step 표를 재사용하는 데 동의했다.
- C4 첫 계획판(`a37efddc3`) Task 6은 종류 CHECK 없는 `fleet_mission_steps`를 제안했다. C4 재계획(`439e6ff09`)은 그 대신 main의 `cell_job_store.py`를 인계받는다. 그 안의 `fleet_cell_steps`는 `CHECK(action_kind='CELL_TRANSFER')`이고, `workcell_id`·`instance_id`·레시피/셀 해시가 Job 머리의 NOT NULL 열이다.
- D-420 §3은 Step 표의 모양을 가정하지 않고 요구 S1–S12를 둔다. Pinky의 원장 의존 구현(§7 단계 1b)은 C4가 재개해 Step 표를 main에 착지한 뒤에 시작한다.
- **rosy-0d 초기 의견(기록):** 질문 2 — 종류 CHECK 없음. 질문 10 — 종류별 검증 hook은 저장소·앱 층. 질문 7 — 승인 epoch·세대를 Step 제출마다 기록(기울어 있음). D-420 S1·S9·S11이 이 의견을 따른다. 확정 답을 받으면 이 절을 고친다.

## A. C4 담당 rosy-0d (pl3은 `cell_job_store.py` 저자로 참고)

1. **어느 표인가.** C4가 확정할 Step 표는 첫 계획판의 `fleet_mission_steps`, 인계받은 `fleet_cell_steps`를 넓힌 것, 그 밖의 것 중 무엇인가? 결정 시점은 C4 재개 직후인가?
2. **종류 CHECK(S1).** 초기 의견은 "없음"이다. 확정인가?
3. **Step별 대상 장치(S2).** 장치 종류·ID를 Step 행에 둘 수 있는가? Mission 머리의 `workcell_id`/`instance_id`는 Cell 전용 머리 정보로 남겨도 되는가?
4. **공정 전용 열(S3).** 레시피·셀 해시와 Job 문서를 종류별 본문이나 Cell 전용 머리 표로 옮기는 것과 NULL 허용 중 무엇을 택하는가? `CELL_TRANSFER` digest 불변 시험은 그쪽이 소유하는가?
5. **상태와 사유(S7, S8).** 상태 집합 `WAITING`·`READY`·`RUNNING`·`ACTION_SUCCEEDED`·`GOAL_CONFIRMED`·`HOLD`를 유지하고 실패·취소·불명을 HOLD + 사유 코드로 표현하는 데 동의하는가? `reconciliation_pending`, `cancel_requested_at`, `deadline_at`은 열인가 본문인가?
6. **predicate와 증거(S6, D-420 §1.2·F4).** 지금 증거 경로는 PICK_PLACE 모양이다(workcell 범위 토큰 생산자, 물체·목적지 필수 predicate, 그리퍼 필수 증거, 생산자 `satisfied`, 레거시 `MissionService` 조회). D-420은 이것을 넓힌다: Fleet 내부 출처(`robot_state`, 토큰 없음), 조건별 필드 집합, 생산자 범위 "workcell 또는 robot", 새 조건은 Fleet 판정, Step 키 조회. C4의 `sim_model_pose`도 같은 서비스를 Step 키로 쓰게 되는가? Step별 predicate를 Step 표에 둘지 `goal_evidence_store.py`에 Step 키로 둘지, 그리고 이 확장을 C4와 Pinky 중 누가 먼저 하는지 정하자.
7. **세대 기록(S9).** 초기 의견은 "Step 제출마다 기록"이다. 확정인가? `(authority_epoch, generation)` 쌍으로 남기는 데 동의하는가(R4가 같은 쌍을 쓴다)?
8. **하달기 추상(D-420 §2).** 하달기가 장치별 전송 어댑터를 고르는 포트(제출 → 수락/거절/불명, 상관된 취소, 현재 상관 상태 조회)를 가질 수 있는가? 결과를 포트가 아닌 이벤트 투영으로 받는 Pinky 방식과 충돌하는 곳이 있는가?
9. **Step 진행 규칙 공유.** `cell_steps.py`(계획) 규칙의 종류 중립 부분을 `rosy.execution.site` 공용 함수로 둘 수 있는가? Pinky는 "작업대당 하나"를 "로봇당 하나"로 쓴다.
10. **저장소 hook(S11).** 초기 의견은 "저장소·앱 층"이다. 생성·승인·Step 시작·결과 기록·목표 확인 다섯 곳 모두에 hook을 두는 데 동의하는가?
11. **claim 단계(D-420 §4.5).** Cell Job도 Step 사이에 `CLAIMED`, 제출~진행 중에 `DISPATCHING`, 불명 HOLD에 `UNKNOWN`을 쓰는가? 두 종류의 claim 단계 규칙을 하나로 맞출 수 있는가? `dock` 자원 종류를 첫 이관과 같은 변경에 넣어야 하는가?
12. **재개(D-420 §4.4).** Pinky는 "새 세대에서 Mission 전체 재승인, 첫 미확인 Step부터"로 정했다. Cell Job(D-403 §6)도 같은 규칙인가?
13. **이관 규칙(S12).** 진행 중 Step이 있으면 이관을 거절하는 첫 계획판 6.2 절차를 유지하는가?
14. **순서와 연락.** C4 재개 시점을 Pinky 세션에 알려 줄 수 있는가? Step 표 schema 초안이 나오면 Pinky 세션이 S1–S12 대조 검토를 먼저 해도 되는가?

## B. D-419 담당(`feat/d415-saf003-fleet-loss`)

15. D-420 §4.3의 개정 제안(범위에 상관된 도킹·차선 실행 추가, Mission 시도에는 `HOLD`의 "같은 시도 재송신" 재개를 쓰지 않음)을 D-419 본문 보강으로 받을 수 있는가?
16. REST `navigation/cancel`에 `correlation_id`를 열 때, `cancel()`이 `False`이면 409 `CORRELATION_NOT_ACTIVE`로 답하는 D-420 R2와 충돌이 있는가?
16a. D-420 R11: FleetAgent가 설정된 로봇이 링크가 끊긴 동안 상관된 시작을 409 `FLEET_LINK_DOWN`으로 거절한다. D-419 §1(끊긴 뒤 온 Fleet 목표는 막지 않음)과 상관된 시작에 한해 다르게 가는 데 동의하는가?
16b. Step 도중 `PUT /safety/limits`로 정책이 `RETURN_HOME`·`CONTINUE`로 바뀌는 경우, D-420은 Fleet 쪽에서 감지해 상관 취소 + HOLD한다. CORE가 상관 동작 진행 중 그 변경을 거절하는 편이 낫다고 보는가?

## C. D-421 담당(`feat/d414-fleet-cancel-all`)

17. D-420 §4.2를 D-421 열린 질문 1의 답으로 받을 수 있는가: (a) Pinky Mission이 있으면 전체 취소가 같은 울타리 안에서 끝나지 않은 모든 Pinky Mission을 HOLD(`site_cancel`)로 옮긴다. (b) 기존 `line-follow/mode OFF`가 R3 차선 실행도 끝내므로 별도 차선 단계는 없다. (c) 상관 없는 `docking/cancel`은 SAF-005 저배터리 복귀까지 취소하므로 보내지 않고, R8 `current`가 Mission 상관 도킹을 보이는 로봇에만 상관된 `docking/cancel`을 보낸다.

## D. D-395 위치 확정 담당

18. D-420 §4.6·F9: Mission claim을 쥔 로봇에는 사다리가 `NOT_LOCALIZED` + Mission HOLD(`not_localized`) + claim `CLAIMED`일 때만 기동을 낸다. `localization_service.py`에 이 검사를 넣는 데 동의하는가? Mission claim이 없는 로봇의 동작은 바뀌지 않는다.
