# D-767 실행 계획 — 시각 붙은 지시(A부)와 경로 미리보기(B부)

**날짜:** 2026-10-15(개정 1 같은 날) · **결정:** [D-767](../adr/D-767-route-preview-events-ahead.md) 개정 1(Proposed) · **상태:** 초안. 사용자 승인 전에는 어떤 단계도 시작하지 않는다. B부 P1은 사용자가 P2를 원한다고 정한 뒤에만 한다.

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
4. A와 P2의 커밋은 `Safety-Review: <리뷰어·레인> <근거>` trailer가 필요하다(D-430). 구현한 세션이 아닌 독립 리뷰가 낸다.
5. 계약(API Reference, `core_common.protocol`)을 바꾸는 단계는 버전 핀 셋을 같이 고친다(`docs/solutions/workflow-issues/a-contract-version-bump-is-three-pins-not-one.md`).
6. **크기(D-766).** 커밋마다 크기 검사가 녹색이다.
   - `operations/fleet/fleet/server/ledger/trip_runner.py`(또는 조각 4 뒤의 `server/trips/` 자리) 901줄은 천장이다. 배선 한 줄은 **같은 커밋에서** 실제 줄 하나 이상을 비워 갚는다. 문장을 한 줄로 합치는 것은 갚는 것이 아니다.
   - `trip_ports.py` 600줄에는 아무것도 더하지 않는다.
   - Fleet에 새 작은 크기 단위를 만들지 않는다(부모 > 2,000줄이면 새 단위 ≥ 1,000줄). B부 코드는 `operations/fleet/fleet/server/trips/trip_preview.py` 새 파일 하나다.
   - D-763 조각 4(`server/trips/`)가 main에 착지한 뒤 워크트리에서 `git merge main`을 먼저 한다.
7. 착지는 `python tools/land.py --tests auto`, 사용자가 말한 뒤에만. 푸시와 현장 릴리스도 같다.

## 순서

```
A 시각 붙은 지시 ────────────────────────────────────────────── (독립)
P0 Fleet 미리보기·관제·정확도 ──▶ [사용자: P2를 원하는가] ──▶ P1 차로 신호 trip 변형·CORE 저장 ──▶ P2 미리 감속
                                     └ 아니오: P0에서 멈춘다            P3b: D-550 개정, 이 계획 밖
```

A와 P0은 서로 다른 파일이라 같이 갈 수 있다. P0은 조각 4 착지 뒤다.

## A — 시각 붙은 지시

- **브랜치:** `fix/junction-instruction-pose-stamp` · **검토:** **Safety-Review** · **선행:** rosy-44에 알린다(교차로·굽이 담당)
- **닿는 곳**
  - `contracts/foundation/core_common/protocol/controls.py`(능력 `lane_instruction_stamp`)
  - `middleware/core/api/core_api_web/api/v1/line_follow.py`(`POST /line-follow/junction`의 `pose_stamp`, 범위 검사 400)
  - `middleware/drive/behaviors/line_follow/recovery/junction/approach.py`(창 기준 odometer), `recovery/junction/bend.py`(굽이 통과 기준), `line_follow/model.py`(`instruction_stamp_enabled` 기본 false), 상태 `junction.distance_basis`·`distance_basis_reason`
  - Fleet: `server/ledger/trip_ports.py`(또는 조각 4 뒤 `server/trips/trip_ports.py`)의 `bend_fields` 앞당김과 `_pose_tol` 지연 항 — **줄을 늘리지 않는 꼴로**(조건 하나를 기존 식에 넣거나, 같은 커밋에서 줄을 비운다), `trip_runner.py` `_send`에 `pose_stamp`(이미 같은 주기에 `map_entry.odom_stamp_s`를 만드는 자리에서)
  - `docs/reference/ROSY API & Protocol Reference.md`, 버전 핀
- **작업**
  1. 받을 때 `_odom_entry(pose_stamp)`(D-758 0)로 표본을 찾고, 그 표본의 `trail.odometer_at(...)`을 창·굽이 통과의 기준으로 둔다. `_odom_log` `path_m`과 섞지 않는다.
  2. 떨어짐: `no_sample`·`stale`(> 2 s)·`future`(> 0.05 s)·`ambiguous`·`epoch` → 받은 때 기준, 거절 없음, 사유 기록.
  3. Fleet: 능력이 참인 로봇에 `pose_stamp`, 앞당김 0, 허용치에서 읽기→전송·`SEND_ALLOWANCE_S` 항 제외.
- **시험(호스트)**
  - 0.2 s 늦게 닿은 굽이 지시(0.10 m/s): 오늘 기준은 굽이 시작이 0.02 m 어긋나고, stamp 기준은 0.005 m 안.
  - 같은 조건의 교차로 창: 기대 선 위치가 0.005 m 안.
  - 떨어짐 사유 다섯 각각: 받은 때 기준, 사유가 상태에 보임.
  - 벽시계 ±5 s: 같은 표본(D-758 0 시험 꼴).
  - `_odom_entry` 표본과 `trail.odometer_at` 표본이 같은 odom 메시지임을 고정하는 시험.
  - 설정 꺼짐: 기존 `test_junction_bend.py`, `test_junction_turn_map_entry.py`, `test_line_junction_api.py`가 그대로, 명령이 오늘과 같다.
  - Fleet(`operations/fleet/test/test_trip_bend.py`, `test_trip_d507.py`): 능력 있는 로봇의 `bend_in_m`에 앞당김 0, `pose_stamp`가 `map_entry.odom_stamp_s`와 같음, 능력 없는 로봇은 그대로.
  - 크기 검사, 버전 가드.
- **현장 근거:** Gazebo 2대 30분: 굽이 시작 오차가 m18 기준(중심 ±7 mm)보다 나쁘지 않음, `junction_unexpected` 증가 없음. 장치 2대 10바퀴(사람이 E-stop을 쥔다). `docs/validation/instruction-stamp-<날짜>/`.
- **끝난 기준:** 위 통과 + Safety-Review trailer. 켜는 것은 사용자가 정한다.
- **되돌림:** 설정 false. Fleet은 능력이 없으면 앞당김을 그대로 쓴다.

## P0 — Fleet 미리보기, 관제 표시, 정확도

- **브랜치:** `feat/route-preview-observe` · **검토:** 코드 리뷰 · **선행:** D-763 조각 4 착지, main 병합
- **닿는 곳**
  - 새 파일 `operations/fleet/fleet/server/trips/trip_preview.py`(빌더 + 기록, `server/trips/trip_ports.py` 기하를 import)
  - trip 루프 배선 한 줄(같은 커밋에서 실제 줄 하나 이상을 비움)
  - `operations/fleet/fleet/traffic/config.py` 또는 trip 설정(`fleet.trip.route_preview: off|observe`)
  - `/api/fleet/traffic` 로봇 행, 관제 로봇 카드 한 줄(`operations/site_ui/console/`)
  - `operations/fleet/test/test_shared_state_read.py`의 `PERIODIC`에 `server/trips/trip_preview.py`
  - 주석 고침: `contracts/foundation/core_common/protocol/lane_cue.py:7`, `operations/fleet/fleet/server/lane_compliance_service.py:213`(`crosswalks[]`는 없다)
  - 분석 도구(저장소에는 도구만, 기록은 `X:\DevTemp\route-preview-p0\`)
  - `operations/fleet/logs.md`
- **작업**
  1. 빌더: 공유 상태 읽기(`max_age_s`)의 자세와 블록 표의 `front_d_m`·`pose_stamp`로 `{leg_id, seq, pose_stamp, map_version, horizon_m, events[{s_m, at_m, kind, place_id, params}]}`.
  2. 새 코드(ADR 6항 표): 여러 구간에 걸친 장소·굽이 찾기, 횡단보도 다각형의 trip 경로 투영(CORE 앞쪽 경계 기준), 경로 위 신호 여럿. 나머지는 기존 기하(장소 위치, `line_past`, 굽이 시작·반지름, `exit_segment` 기하, `turn_target`).
  3. `horizon_m = min(2.0, trip 끝까지, max(R + d_stop, v_top × 8))`, 8개에서 자름.
  4. "바뀜" = 사건 집합, 사건의 절대 위치 `s_m`(0.01 m 넘게), `params`가 바뀜. 로봇이 나아가 `at_m`만 줄어든 것은 바뀜이 아니다. P0에서는 바뀜 횟수만 센다(P1 비용 예측).
  5. `preview_mismatch{kind}`: 지시를 보낼 때 그 자세의 `s` + 앞당김 전 거리와 같은 `place_id` 사건의 `s_m`(투영점과 앞 끝 차이를 맞춘 뒤)을 비교, 허용치 0.005 m.
  6. 보내지 않음/만들지 않음: 자세 점프 UNKNOWN, `link_wait`, Fleet 재시작 뒤 5 s, 다른 지도 버전. 다단계 작업의 다음 단계는 싣지 않는다. `work_read`에 넣지 않는다.
- **시험(호스트, 가짜 그래프·가짜 시계)**
  - 직선 + 교차로: `turn`의 `s_m`이 장소, `line_before_m`이 `pivot_past_line_m`(갈래 0).
  - 굽이 뒤 교차로(W1→SW 꼴, 구간을 넘음): `bend` 다음 `turn`.
  - 회전교차로: `turn` + `arc` 여럿, 8개 자르기와 `horizon_m`.
  - trip 끝이 1 m 앞: `horizon_m` 1 m, `stop{trip_end}`.
  - 통행권 끝이 2 m 너머: 2.0. `hold_back`: `R = 0`.
  - 횡단보도 다각형이 경로를 비스듬히 가로지름: 앞쪽 경계 투영.
  - 신호 둘이 horizon 안: 둘 다.
  - "바뀜" 판정, `preview_mismatch` 0과 일부러 어긋낸 1.
  - 공유 상태 읽기 가드(`PERIODIC`), 크기 검사.
- **정확도 측정(착지 뒤 사용자가 말하면) — ADR 7항 기준 그대로**
  - Gazebo 2대 30분: 참 자세·world 위치 대비 p95 ≤ 0.03 + 0.05 × `at_m`, 놓침·헛사건 ≤ 1%.
  - 장치 2대 10바퀴: 로봇 카메라 목격(`junction_ahead_m` + odom), 횡단보도 구역 앞쪽 경계 대비 p95 ≤ 0.10 + 0.05 × `at_m`, 놓침·헛사건 ≤ 1%. 로봇 기록에서 오프라인으로.
  - `preview_mismatch` 0, 바뀜 횟수 로봇당 평균.
  - 결과 `docs/validation/route-preview-p0-<날짜>/`.
- **끝난 기준:** 호스트 시험 통과, NEW 0. 측정 기준을 못 넘으면 관제 표시로만 남긴다.
- **되돌림:** 설정 `off`.

## 관문 — 사용자 결정

P0 측정 결과를 가져가 묻는다: "P2(사건 앞 미리 감속)를 원하는가". 아니오면 B부는 여기서 끝난다. 예면 P1과 P2를 한다.

## P1 — 차로 신호 trip 변형, CORE 저장과 표시

- **브랜치:** `feat/route-preview-lane-cue-trip` · **검토:** 코드 리뷰(움직임 없음), import-lint·성질 시험 필수 · **선행:** 관문 "예", D-511 담당 세션 동의(아니면 ADR 8항 대안: 전용 엔드포인트)
- **닿는 곳**
  - `contracts/foundation/core_common/protocol/lane_cue.py`(`LaneContext` trip 변형: `route: "trip"`, `leg_id`, `seq`, `pose_stamp`, `map_version`, `horizon_m`, `events` ≤ 8; trip 변형에는 `next` 없음), `.../protocol/controls.py`(능력 `lane_cue_trip_context`)
  - `middleware/drive/behaviors/line_follow/cue/`(저장: 받을 때 odom 지점으로, 순서, 버림) — `cue` 단위 여유 약 140줄 안에서
  - `middleware/core/api/core_api_web/api/v1/line_follow.py`(`GET` 노출), `.../v1/system.py`(능력)
  - Fleet: 차로 신호 송신 자리(`operations/fleet/fleet/server/lane_compliance_service.py`)가 trip 로봇이면 `trip_preview.py`의 최신 미리보기를 `context`로 싣는다(trip 쪽이 공급 함수를 넘기고, 서비스는 `trips`를 import 하지 않는다)
  - API Reference, 버전 핀
- **작업**
  1. 받을 때 `_odom_entry`로 `pose_stamp` 표본, 사건마다 odom 지점. 같은 `leg_id`에서 `(pose_stamp, seq)` 순서, 새 `seq`는 목록 전체 교체.
  2. 버림: 차로 신호 `ttl_s`(≤ 2), `leg_id`·`map_version` 변경, odom epoch·frame, 모드 변경, E-stop. 만료한 미리보기는 아무것도 보이지 않는다.
  3. `GET /line-follow`의 `preview {state, seq, age_s, horizon_now_m, events[{kind, in_m, place_id, params}]}`.
- **시험(호스트)**
  - 계약: trip 변형 범위 밖 400, `lap` 변형은 그대로, trip 변형에 `next` 400.
  - 순서·버림·다시 재기(0.3 m 간 뒤 `in_m` 0.3 감소, 후진은 더 감소), 벽시계 ±5 s.
  - **import-lint:** `line_follow/authority.py`, `line_follow/recovery/junction/gate.py`가 미리보기 저장소·schema를 import 하면 실패.
  - **성질 시험:** 무작위 입력에서 통행권 상태·교차로 게이트 결정·선속도가 미리보기 유무와 같다.
  - D-511 차로 신호 기존 시험 그대로(`fleet_lane_cue_enabled` 꺼짐/켜짐).
  - Fleet: 능력 없는 로봇은 `lap` 변형 그대로, trip 로봇에 `next` 없음, 새 REST 호출 0.
- **현장 근거:** Gazebo 2대 30분: 로봇 `in_m`이 P0 기준 안, 차로 신호 전달 p99가 전과 같음.
- **되돌림:** Fleet이 trip 변형을 싣지 않는다.

## P2 — 미리 감속 (기본 꺼짐)

- **브랜치:** `feat/route-preview-slowdown` · **검토:** **Safety-Review** · **선행:** P1 착지, rosy-44와 `v_event` 값
- **닿는 곳:** `line_follow/cue/`(상한 계산), 차선 결정의 마지막 클램프 자리(D-551 9항과 같은 자리, `line_follow/manager.py`), `line_follow/model.py`(`preview_slowdown_enabled` 기본 false, 종류별 `v_event`, 감속도 `a`, `margin`)
- **작업:** `cap = sqrt(v_event² + 2·a·max(0, in_m − margin))`, `decision.linear = min(decision.linear, max(cap, v_floor))`. 감속 대상은 `turn`(left·right·stop), `bend`, `crosswalk`, `stop`. `signal`과 D-620 신호 대기는 뺀다. 같은 `leg_id` 통행권이 FREE·HOLDING이고 만료 전일 때만.
- **시험**
  - D-551 9항 목록 전부(몸체 정지 + 상한 → 0, 통행권 없음 → 상한 없음, 30 s 상한에 `_escalated` 거짓, 실제 장애물은 지금처럼, 차선 잃음 래치 그대로).
  - `v_floor` < 데드밴드 → 시작 검사 실패.
  - 교차로 접근 `slow_from`, 횡단보도 `v_cross`, D-551 신호 상한과 같이 있을 때 결과가 셋의 `min`(더하지 않음).
  - `signal` 사건만 앞에 있음 → 상한 없음.
  - 종류마다 감속 시작점 ±0.02 m.
  - 설정 꺼짐 → 명령이 P1과 같다.
- **현장 근거:** Gazebo 2대 30분: 접촉 0, 블록 중복 0, trip 정체 판정 증가 없음, `junction_unexpected` 증가 없음. 장치 2대 10바퀴. `docs/validation/route-preview-p2-<날짜>/`.
- **끝난 기준:** 위 통과 + Safety-Review trailer. 켜는 것은 사용자가 정한다.
- **되돌림:** 설정 false.

## 이 계획에 없는 것

- P3b(끊긴 동안 미리보기로 무장): D-550 2항 개정이 먼저다.
- 저장한 미리보기를 D-531 `route_context` 입력으로 쓰는 일: D-531 개정.
- 허브 하트비트 답 경로, 로봇 얼굴·LCD 표시.
- 속도 구역(`slow`) 사건: 지도에 속도 구역이 생길 때.
