# D-767 실행 계획 — 경로 미리보기(몇 m 앞에서 무엇이 오는가)

**날짜:** 2026-10-15 · **결정:** [D-767](../adr/D-767-route-preview-events-ahead.md)(Proposed) · **상태:** 초안. 동료 세션(rosy-44, rosy-fc) 토론과 사용자 승인 전에는 어떤 단계도 시작하지 않는다.

이 문서는 단계별 작업, 닿는 파일, 시험 항목, 통과 기준을 적는다. 계약과 이유는 ADR에 있다. 단계마다 실행기가 시험을 먼저 쓰고(TDD) 단계마다 자기 브랜치에 커밋한다.

## 모든 단계에 같은 규칙

1. 작업은 `rosy-platform/.worktrees/<이름>`에서만 한다(`python tools/worktrees.py new <이름> <type>/<topic>`). main 체크아웃을 고치지 않는다.
2. pytest는 이 노트북에서 돌리지 않는다. 커밋한 뒤 워크트리 루트에서 돌린다. Gazebo는 `--pick sim`이 고른 PC에서 돈다.

   ```bash
   python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<이름> -- <시험 경로> -q
   python test/known_failures.py X:/DevTemp/<이름>/run-<n>.txt
   ```

   `NEW`는 그 브랜치의 실패다. 시험 PC가 닿지 않으면 "확인 못 함"으로 보고하고 착지하지 않는다.
3. `git add`에는 자기 경로만 적는다. amend·rebase·reset·stash를 쓰지 않는다.
4. P2·P3a의 커밋은 `Safety-Review: <리뷰어·레인> <근거>` trailer가 필요하다(D-430). 구현한 세션이 아닌 독립 리뷰가 낸다.
5. 계약(API Reference, `core_common.protocol`)을 바꾸는 단계는 버전 핀 셋을 같이 고친다(`docs/solutions/workflow-issues/a-contract-version-bump-is-three-pins-not-one.md`).
6. **크기 한도(D-766).** 커밋마다 크기 검사가 녹색이어야 한다. `ledger/trip_runner.py`(901, 여유 0), `ledger/trip_ports.py`(600), `server/ledger` 단위(여유 0), `fleet/fleet/traffic` 단위(여유 약 1)는 자라지 못한다. 새 코드는 새 단위에 두고, `trip_runner.py` 배선은 같은 브랜치의 **앞 커밋**에서 그만큼 줄을 옮긴 뒤에 넣는다. 시작 전에 D-766 7(a)(ratchet) 착지 여부와 rosy-fc의 trip 코드 이동(D-763)을 확인한다.
7. 착지는 `python tools/land.py --tests auto`, 사용자가 말한 뒤에만. 푸시와 현장 릴리스도 같다.

## 순서

```
P0 Fleet 관찰 ──(정확도 기준 통과)──▶ P1 계약·CORE 표시 + Fleet send ──▶ P2 미리 감속 ──▶ P3a 지시 거리 다시 재기
                                                                                  P3b 끊긴 동안 무장: 별도 개정, 이 계획 밖
```

P2와 P3a는 서로 다른 CORE 경로(감속 클램프 / 교차로·굽이 창)라 P1 뒤 같이 갈 수 있다. 둘 다 P1의 저장소가 필요하다.

## 0단계(준비) — 자리 비우기

- **브랜치:** P0 브랜치의 첫 커밋 · **검토:** 코드 리뷰
- **작업:** `trip_runner.py`에서 P0 배선에 필요한 줄 수(예상 4–6줄) 이상을 동작 변경 없이 다른 모듈로 옮긴다. 후보는 rosy-fc와 정한다(ADR 동료 질문 6). D-763 이동이 먼저 착지하면 그 자리를 쓴다.
- **끝난 기준:** 기존 trip 시험(`operations/fleet/test/test_trip_*.py`) 통과, 크기 검사 녹색, `trip_runner.py` 줄 수 감소.

## P0 — Fleet만: 만들고, 기록하고, 보이고, 잰다

- **브랜치:** `feat/route-preview-observe` (`.worktrees/route-preview-observe`) · **검토:** 코드 리뷰
- **닿는 곳**
  - 새 단위 `operations/fleet/fleet/traffic/preview/`: `builder.py`(순수 함수), `sender.py`(`PreviewSender`, P0에서는 기록만), `accuracy.py`(예측 대 실제)
  - `ledger/trip_runner.py`(배선, 0단계에서 비운 줄 안에서), `traffic/config.py`(`fleet.trip.route_preview`), `server/ledger/trip_routes.py` 또는 `/api/fleet/traffic` 읽기(로봇마다 `preview`), `operations/site_ui/console/` 로봇 카드 한 줄
  - 주석 고침: `contracts/foundation/core_common/protocol/lane_cue.py:7`, `operations/fleet/fleet/server/lane_compliance_service.py:213`(`crosswalks[]`는 없다, ADR Context 7)
  - `operations/fleet/logs.md`
- **작업**
  1. 빌더: `(graph, segments, index, s, traffic 행, site map, caps, config) → (horizon_m, events)`. 사건은 실제 지시를 만드는 함수(`lane_action`, `turn_target`, `junction_fields`, `next_bend`, `bend_fields`의 기하, `exit_segment`, `signal_ahead`, `hold_back_m`)로만 만든다. 새 기하 계산을 쓰지 않는다. 지점은 통행권과 같은 `front_d_m`·`pose_stamp` 기준. `horizon_m = min(2.0, max(R + d_stop, v_top × 8))`, 사건 8개에서 자름.
  2. trip 주기마다 통행권 다음, 신호 참고와 같은 자리(`trip_runner.py:428-431`)에서 만든다. `observe`면 기록·노출만.
  3. "바뀜" 판정(0.02 m)과 `ttl_s/2` 갱신을 계산해 **보냈을 횟수**를 센다(P1의 호출 수 예측).
  4. 지시를 보낼 때 직전 미리보기와 비교해 `preview_mismatch{kind}`를 센다.
  5. 정확도 기록: 사건마다 예측 지점과 실제 지점(ADR 10항의 "일어난 때" 정의)을 JSONL로 `X:\DevTemp\route-preview-p0\`에 남기는 도구(현장·Gazebo 기록 분석용, 저장소에는 도구만).
- **시험(호스트, 가짜 그래프·가짜 시계)**
  - 직선 차로 + 교차로 하나: `turn` 하나, 지점이 지시의 `expect_in_m − pivot_past_line_m`과 같다.
  - 굽이 뒤 교차로(W1→SW 꼴): `bend` 다음 `turn`, 순서와 지점.
  - 회전교차로: `turn` + `arc` 여럿, 8개 자르기와 `horizon_m`.
  - 통행권 끝이 2 m 너머: `horizon_m` 2.0. `hold_back`: `R = 0`, `horizon_m = v_top × 8`.
  - 신호 구역: `signal`에 색이 없다. 보류 중: `stop{hold}`.
  - 지도 버전이 다름, 자세 점프, `link_wait`, 재시작 뒤 5 s: 만들지 않는다.
  - 같은 사건 집합에서 로봇만 나아감: "바뀜" 아님. 사건이 들어오거나 나감: "바뀜".
  - `preview_mismatch`: 같은 함수라 0, 일부러 다른 `turn_deg`를 넣으면 1.
  - 크기 검사, 소유권 가드(`docs/solutions`의 repo guard 목록).
- **현장 근거(측정, 착지 뒤 사용자가 말하면)**
  - Gazebo 2대 30분(map_v2_fleet), 장치 2대 10바퀴에서 `observe` 기록을 모은다.
  - ADR 10항 정확도 기준: 1 m 안 중앙값 ≤ 0.03 m·p95 ≤ 0.08 m, 1–2 m p95 ≤ 0.15 m, 놓침 ≤ 1%, 헛사건 ≤ 1%, 보냈을 횟수 로봇당 평균 ≤ 1/s, `preview_mismatch` 0.
  - 결과는 `docs/validation/route-preview-p0-<날짜>/`.
- **끝난 기준:** 호스트 시험 통과, `known_failures` NEW 0. P1로 가는 기준은 위 측정의 통과다. 못 넘으면 P0(표시)에서 멈춘다.
- **되돌림:** 설정 `off`.

## P1 — 계약, CORE 저장소와 표시, Fleet 보내기

- **브랜치:** `feat/route-preview-display` · **검토:** 코드 리뷰(움직임 없음). import-lint와 성질 시험이 필수다.
- **닿는 곳**
  - 새 `contracts/foundation/core_common/protocol/route_preview.py`(`RoutePreviewRequest`, 사건 종류별 `params`, `extra="forbid"`)
  - `.../protocol/controls.py`(`line_follow_preview`)
  - 새 단위 `middleware/drive/behaviors/line_follow/preview/`(저장소: 받을 때 odom으로 옮김, 순서, 버림, 다시 재기)
  - `middleware/core/api/core_api_web/api/v1/line_follow.py`(`POST /line-follow/preview`, `GET` 노출), `.../v1/system.py`(능력)
  - Fleet `traffic/preview/sender.py`(`send`), `ledger/trip_ports.py`의 `HttpLaneJunction`에 `send_preview` — **trip_ports.py는 600줄이라** 이 한 메서드도 줄을 옮겨야 들어간다. 대안은 송신 포트를 `traffic/preview/`에 두는 것(리뷰에서 정한다)
  - `docs/reference/ROSY API & Protocol Reference.md`(additive 한 판), 버전 핀
- **작업**
  1. schema: ADR 2항 그대로. `at_m` −0.5–2, `horizon_m` (0, 2], 사건 ≤ 8, 오름차순, `ttl_s` (0, 5].
  2. 저장소: 받을 때 `_odom_entry`(D-758 0)로 표본을 찾고 사건마다 odom 경로 지점을 둔다. 자세 검사 409 이름은 통행권과 같다. 순서는 D-550 4항(`stale`·`duplicate`). 새 `seq`는 목록 전체를 바꾼다.
  3. 버림: `ttl_s`(차선 시계), `leg_id` 변경, 같은 구간의 `map_version`·`route_rev` 변경, odom epoch·frame 변경, 받은 뒤 경로 > `horizon_m`, 모드 변경, E-stop. `preview_dropped{reason}`.
  4. 노출: `GET /line-follow`의 `preview {state, seq, age_s, horizon_now_m, events[{kind, in_m, place_id, params}]}`.
  5. Fleet: `send` + 능력. 통행권 전송이 진행 중이거나 단계 처리 중이면 건너뜀, 자기 전송 자리, 한도 1.0 s, 재시도 없음.
- **시험(호스트)**
  - 계약: 범위 밖 400, 차선 주행 꺼짐 409, 자세 409 셋, `extra` 거절, 오름차순 아님 400, 9개 400.
  - 순서: 같은 구간 `(pose_stamp, seq)` 오래됨 `stale`, 같음 `duplicate`, 만료 뒤 낮은 `seq` 받음, 구간 변경 뒤 받음.
  - 다시 재기: 0.3 m 간 뒤 `in_m`이 0.3 줄었다. 후진하면 더 줄어든다(부호 없는 경로).
  - 버림 사유 각각.
  - 벽시계 ±5 s: 같은 표본을 찾는다(D-758 0 시험과 같은 꼴).
  - **import-lint:** `line_follow/authority.py`, `recovery/junction/gate.py`가 `line_follow.preview`나 `protocol.route_preview`를 import 하면 실패.
  - **성질 시험:** 무작위 입력에서 통행권 상태·교차로 게이트 결정·선속도가 미리보기 유무와 같다.
  - Fleet: 능력 없는 로봇에 0건, 통행권 진행 중 건너뜀, 변화 없는 구간 2.5 s 간격.
  - 버전 가드(프로토콜 버전 맞춤, 능력 목록), 기존 차선 추종·교차로·신호 참고 시험 그대로.
- **현장 근거:** Gazebo 2대 30분: 로봇 `in_m`과 Fleet 예측의 차이가 P0 기준 안, 통행권 전달 p99가 미리보기 전과 같거나 낫다, 접촉·블록 중복 0. 장치는 릴리스 뒤 사용자가 말하면 2대 10바퀴 표시 확인.
- **끝난 기준:** 위 시험 통과, NEW 0, API Reference·버전 핀.
- **되돌림:** Fleet `observe`. CORE 저장소는 쓰이지 않으면 무해하다.

## P2 — 미리 감속 (기본 꺼짐)

- **브랜치:** `feat/route-preview-slowdown` · **검토:** **Safety-Review** · **선행:** P1 착지, ADR 동료 질문 2의 답(`v_event` 값과 접근 감속·횡단보도·신호 대기와의 겹침)
- **닿는 곳:** `line_follow/preview/`(상한 계산), 차선 결정의 마지막 클램프 자리(D-551 9항과 같은 자리, `line_follow/manager.py`), `line_follow/model.py`(`preview_slowdown_enabled` 기본 false, `v_event` 종류별, 감속도), 능력 판 없음(설정만)
- **작업:** 다음 감속 사건의 `in_m`에서 `cap = sqrt(v_event² + 2·a·max(0, in_m − margin))`, `decision.linear = min(decision.linear, max(cap, v_floor))`. 같은 `leg_id` 통행권이 FREE·HOLDING이고 만료 전일 때만. D-407 래치를 쓰지 않는다.
- **시험(D-551 9항 목록 + 아래)**
  - 몸체 정지 + 감속 사건 → 0. 통행권 없음(`hold_back`) → 상한 없음. 다른 `leg_id` 통행권 → 상한 없음. 만료 → 없음.
  - `v_floor` < 설정 데드밴드 → 시작 검사 실패.
  - 사건 종류마다 감속 시작점이 기대값 ±0.02 m.
  - 상한 30 s, 장애물 없음 → `_escalated` 거짓, 막힘 사건 없음. 상한 중 실제 장애물 → 지금처럼 올라감.
  - 막힘 후진·교차로 접근·차선 호 속도가 미리보기 있을 때와 없을 때 같다(그 경로들은 자기 상한을 쓴다).
  - 신호 참고 상한(D-551 9)과 같이 있으면 더 낮은 쪽.
  - 설정 꺼짐 → 명령이 P1과 줄 단위로 같다.
- **현장 근거:** Gazebo 2대 30분: 접촉 0, 블록 중복 0, trip 정체 판정(`trip_progress._stalled`) 증가 없음, 교차로 `junction_unexpected` 증가 없음. 장치 2대 10바퀴(사람이 E-stop을 쥔다). `docs/validation/route-preview-p2-<날짜>/`.
- **끝난 기준:** 위 통과 + Safety-Review trailer. 켜는 것은 사용자가 정한다.
- **되돌림:** 설정 false.

## P3a — 지시의 거리를 미리보기로 다시 재기 (기본 꺼짐)

- **브랜치:** `feat/route-preview-anchor` · **검토:** **Safety-Review** · **선행:** P1 착지, ADR 동료 질문 1의 답(지시에 `pose_stamp`를 더하는 대안과 비교해 택함). rosy-44 담당 경로라 시작 전에 알린다.
- **닿는 곳:** `line_follow/recovery/junction/approach.py`(창의 기준점), `recovery/junction/bend.py`(굽이 시작점), `line_follow/model.py`(`preview_anchor_enabled` 기본 false), `protocol/controls.py`(능력 `lane_preview_anchor`, 설정과 묶음), Fleet `ledger/trip_ports.py` `bend_fields`(능력 있는 로봇에 앞당김 0 — 600줄이라 줄을 옮긴 뒤), import-lint의 gate 예외는 리뷰가 정한다
- **작업:** 지시가 닿았을 때 같은 `leg_id`·`place_id`·`action`(·`turn_deg`)·`map_version`의 fresh 사건이 있으면 그 odom 지점을 창·굽이 시작점으로 쓴다. 허용치는 지시 값 그대로. 없거나 다르면 오늘의 "받은 때부터" 방식. 기록 `junction.preview_anchor_used`, `preview_anchor_reason`(`none`·`disabled`·`stale`·`mismatch`·`epoch`).
- **시험(호스트)**
  - 0.2 s 늦게 닿은 지시: 오늘 방식은 굽이 시작이 `v × 0.2`만큼 어긋나고, 미리보기 방식은 0.005 m 안.
  - `place_id`·`action`·`map_version` 불일치, 낡은 미리보기, odom 재시작: 오늘 방식.
  - 설정 꺼짐: 창·굽이·명령이 오늘과 같다(기존 `test_junction_bend.py`, `test_junction_turn_map_entry.py` 그대로).
  - Fleet: 능력 있는 로봇의 `bend_in_m`에 앞당김 0, 없는 로봇은 그대로.
- **현장 근거:** Gazebo 2대 30분: 굽이 시작 오차 p95가 오늘보다 작다, `junction_unexpected`·`junction_no_window` 증가 없음. 장치 2대 10바퀴.
- **끝난 기준:** 위 통과 + Safety-Review trailer.
- **되돌림:** 설정 false, Fleet 앞당김 복귀.

## 이 계획에 없는 것

- P3b(끊긴 동안 미리보기로 무장): 참고를 허가로 쓰는 일이라 D-550 2항 개정이 먼저다(ADR 9항, 동료 질문 3).
- 허브 하트비트 답 경로(D-550 11 페어링 뒤).
- 로봇 얼굴·LCD 표시(D-551 4항과 같이 뒤로).
- D-511 `context.next`와의 통합, D-531 `route_context` 입력(동료 질문 4·5의 답에 따라 별도 행).
- 속도 구역(`slow`) 사건: 지도에 속도 구역이 생길 때.
