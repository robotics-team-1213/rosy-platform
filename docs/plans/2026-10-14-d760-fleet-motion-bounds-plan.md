# D-760 실행 계획 — Fleet이 시작한 움직임의 한도와 5초 끊김 버티기

**날짜:** 2026-10-14 · **결정:** [D-760](../adr/D-760-fleet-motion-bounds-ride-through.md) 개정 1, 짝 기록 [D-758](../adr/D-758-robot-held-site-anchor.md) · **상태:** 1단계 리뷰 승인(착지 대기), 2단계 안전 재검토 중, 삭제 브랜치 리뷰 승인(착지 대기)

이 문서는 단계별 작업, 닿는 파일, 시험 항목, 통과 기준을 적는다. 계약과 이유는 ADR에 있다. 단계마다 실행기가 시험을 먼저 쓰고(TDD) 단계마다 자기 브랜치에 커밋한다.

## 모든 단계에 같은 규칙

1. 작업은 `rosy-platform/.worktrees/<이름>`에서만 한다. main 체크아웃을 고치지 않는다.
2. pytest는 이 노트북에서 돌리지 않는다. 커밋한 뒤 워크트리 루트에서 돌린다.

   ```bash
   python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<이름> -- <시험 경로> -q
   python test/known_failures.py X:/DevTemp/<이름>/run-<n>.txt
   ```

   `NEW`는 그 브랜치의 실패다. 시험 PC가 닿지 않으면 "확인 못 함"으로 보고하고 착지하지 않는다.
3. `git add`에는 자기 경로만 적는다. amend·rebase·reset·stash를 쓰지 않는다.
4. 2–6단계의 커밋은 `Safety-Review: <리뷰어·레인> <근거>` trailer가 필요하다(D-430). 구현한 세션이 아닌 독립 리뷰가 낸다.
5. 계약(API Reference, `core_common.protocol`)을 바꾸는 단계는 버전 핀 셋을 같이 고친다(`docs/solutions/workflow-issues/a-contract-version-bump-is-three-pins-not-one.md`).
6. 착지는 `python tools/land.py --tests auto`, 사용자가 말한 뒤에만. 푸시와 현장 릴리스도 같다.

## 순서

```
1 규칙 M 경고 ──────────────────────────────┐
2 CORE·계약 ──▶ 0 odom 기록 단조 시각 ──▶ 3 Fleet trip 루프 ──▶ 4 공유 상태 읽기 ──▶ 6 켜기
5 목표 임대 주인 확인 ───────────────────────┘
```

1·2·5는 서로 다른 파일이라 같이 갈 수 있다. 0은 2와 같은 파일(`line_follow/authority.py`)을 고치므로 2 뒤다. 3은 2의 계약이 필요하다. 4는 3과 같은 파일(`ledger/trip_ports.py`)을 고치므로 3 뒤다.

## 1단계 — 규칙 M 평가기(경고만)

- **브랜치:** `feat/fleet-rule-m-warn` (`.worktrees/rule-m-warn`) · **검토:** 코드 리뷰(안전 태그 경로를 건드리면 Safety-Review)
- **닿는 곳:** 새 순수 모듈(평가기), `operations/fleet/fleet/server/console/console_routes.py`(로봇 행에 `rule_m`), `operations/fleet/fleet/swarm/transport.py`(`safety/limits` 읽기, 필요할 때만), `operations/site_ui/console/queues.js`·`roster.js`, `operations/fleet/logs.md`
- **작업**
  1. 평가기: 움직임 종류 × 링크 × 능력 × 정책 → `bounded | unbounded(이유) | idle`. 모르는 입력은 `unbounded`.
  2. 허브 페어링 로봇의 `fleet_loss_policy`를 능력 갱신 옆에서 30 s에 한 번 읽는다. 새 루프를 만들지 않는다.
  3. 수집 행에 `rule_m`을 붙인다.
  4. 예외 큐 주의 행 하나, 카드 `link:` 옆 표시.
- **시험:** D-550 7항 표의 행마다 한 건(lane trip 통행권 있음/없음/임대만, 목표 임대 있음/없음 × hub·rest × STOP·HOLD·RETURN_HOME·CONTINUE·모름, follow, idle), 행에 필드가 실리는지, `test_console_queues_contract.py`의 새 항목.
- **끝난 기준:** 위 시험 통과, `known_failures` NEW 0. 거절하는 코드가 없다.

## 2단계 — CORE·계약: 5초 상한, 줄이기, 임대 중 통행권 강제

- **브랜치:** `feat/authority-ttl5-shrink-under-lease` · **검토:** Safety-Review
- **닿는 곳:** `contracts/foundation/core_common/protocol/line_authority.py`(`MAX_TTL_S` 5, `shrink`, `seq`), `.../protocol/controls.py`(플래그 `line_follow_authority_shrink`, `line_follow_authority_under_lease`), `middleware/drive/behaviors/line_follow/authority.py`·`manager.py`, `middleware/core/gateway/core/trip_lease.py`(임대 상태를 차선 추종 관리자에 알림), `middleware/core/api/core_api_web/api/v1/line_follow.py`·`system.py`, `docs/reference/ROSY API & Protocol Reference.md`, 버전 핀
- **작업**
  1. `ttl_s` 상한 5. 장치에서 `ttl_s`를 재는 시계가 단조 시계인지 확인하고 아니면 고친다(D-760 Open 1).
  2. `seq`: 같은 구간에서 마지막 `seq` 이하는 무시한다. `seq`가 없는 요청(옛 Fleet)은 지금 규칙 그대로다.
  3. `shrink: true`: 끝 = `min(지금 끝, 요청 끝)`, `ttl_s` 갱신, 정지 거리 안이면 `authority_end` HOLD. 거절되면 들고 있던 통행권도 버린다(지금 동작 유지).
  4. 임대 중 강제: trip 임대가 열려 있으면 통행권이 없을 때 `authority_none`으로 선다. 모드 변경과 CORE 재시작 뒤에도 같다. 임대가 끝나면 지금 규칙(`authority_required` 또는 `_authority_seen`)으로 돌아간다.
  5. 능력 플래그 둘을 알린다.
- **시험(기존 D-517 M2 시험에 더한다)**
  - `ttl_s` 5.0 수락, 5.01 거절(400 `VALIDATION_ERROR`). 4.9 s에 FREE, 5.1 s에 EXPIRED.
  - 늘리기(seq 3) → 줄이기(seq 4) → 늦게 닿은 늘리기(seq 2): 끝이 줄인 채다.
  - `shrink` + `until_m: 0`: 다음 틱에 HOLD `authority_end`.
  - `shrink` 요청이 `AUTHORITY_POSE_STALE`로 거절: 통행권이 없어지고 로봇이 선다.
  - `shrink: false`의 작은 끝: 무시되고 `ttl_s`가 갱신되지 않는다(지금과 같다).
  - 임대를 연 뒤 모드 ON, 통행권 없음: 명령 0, 사유 `authority_none`. 통행권이 닿으면 FREE.
  - 임대 중 모드를 껐다 켬: 여전히 통행권을 요구한다.
  - 임대 없음 + `authority_required` false: 통행권 없이 달린다(대시보드 차선 주행이 그대로다).
  - 몸체 정지(D-422)·IR 가드·E-stop이 통행권 문보다 먼저다(기존 시험이 그대로 통과).
- **끝난 기준:** 위 시험과 기존 차선 추종·trip 임대 시험 통과, 가드 시험(프로토콜 버전 맞춤, 이벤트 목록) 통과, Safety-Review trailer.

## 2b단계 — 호의 기한에서 문이 가져간 시간 빼기 (D-760 개정 2의 6)

- **브랜치:** `fix/lane-arc-hold-clock` · **검토:** Safety-Review · **선행:** 2단계 착지, `line_follow/arc` 크기 단위 재판정
- **닿는 곳:** `middleware/drive/behaviors/line_follow/arc/lane_arc.py`
- **작업:** 통행권이 FREE가 아니거나 횡단보도 게이트가 살피는 동안 호의 기한을 세지 않는다. 한 호에 더하는 시간은 상한을 둔다(D-507 13항과 같은 규칙, 15 s). 시작 전에 rosy-44에 알린다(D-744·D-759와 닿는다).
- **시험:** 호 도중 통행권이 3 s·6 s 없다가 돌아옴: 호를 이어서 마친다. 20 s 없음: `lane_arc_timeout`으로 서 있다(지금과 같다). 문이 가져가지 않은 시간은 지금 기한 그대로다.

## 2c단계 — 안전 모듈 목록에 두 파일 추가 (D-760 개정 2의 7)

- 2단계가 origin에 올라간 뒤 `tools/harness/platform_parts.yaml` `safety_modules`에 `line_follow/authority.py`와 `core/trip_lease.py`를 넣는다. 그 커밋은 trailer를 단다.

## 0단계 — odom 기록을 단조 시각으로 (D-758 0단계)

- **브랜치:** `fix/odom-log-monotonic-epoch` · **검토:** Safety-Review(통행권 주행 거리 계산이 이 기록을 쓴다)
- **닿는 곳:** `middleware/core/services/core_features/state/manager.py`(odom 기록, `odom_pose.epoch`·단조 시각), `middleware/drive/behaviors/line_follow/authority.py`·`cue/lane_cue.py`(조회), `contracts/foundation/core_common/protocol/schemas.py`·`localization.py`(`OdomPose` 추가 필드), Fleet `rosy.world...map_pose`(epoch가 바뀌면 기준을 버림), API Reference
- **작업:** 기록을 StateManager로 옮기고 단조 시각으로 찾는다. `pose_stamp`는 Fleet이 돌려주는 값 그대로 비교하므로 스냅숏이 단조 시각을 같이 내고 Fleet이 그것을 돌려준다(옛 Fleet의 벽시계 stamp도 받는다).
- **시험:** 벽시계를 ±5 s 옮긴 뒤 통행권·호·차로 신호의 조회가 같은 표본을 찾는다. odom이 0으로 돌아가면 epoch가 늘고 Fleet 추적기가 기준을 버린다. 기존 D-517·D-744·D-511 시험 통과.
- **범위 변경(2026-10-14, 코드 조사 뒤):** odom 기록은 이미 하나다(`line_follow/authority.py` `_odom_log`, 세 조회가 같이 쓴다). 그래서 기록을 옮기지 않는다. 대신 다음처럼 한다.
  - 스냅숏이 내는 벽시계 stamp와 단조 시각을 기록 항목에 같이 적는다.
  - 조회는 Fleet이 돌려준 stamp와 정확히 같은 항목을 찾는다. 나이·미래·순서 판정은 단조 시각으로 한다. 정확히 같은 항목이 없으면 지금 방식으로 찾는다(옛 Fleet).
  - StateManager가 odom 불연속에만 느는 `odom_pose.epoch`와 `odom_pose.mono_s`를 낸다(선택 필드, v1.228). 차선 추종 모드 변경으로는 늘지 않는다.
  - Fleet은 `map_pose.py`만 고쳐 epoch가 바뀌면 기준을 버린다.
  - Fleet이 단조 stamp를 돌려주는 것은 사이트 앵커(D-758 2단계 이후)로 미룬다. 3단계 파일 9개와 겹치지 않는다.

## 3단계 — Fleet trip 루프: 끊김 기다리기, 줄이기 송신, 재시작 뒤 T

- **브랜치:** `feat/fleet-trip-link-wait` · **검토:** Safety-Review
- **닿는 곳:** `operations/fleet/fleet/server/ledger/trip_runner.py`·`trip_ports.py`·`trip_admission.py`·`trip_progress.py`, `traffic/trip_authority.py`·`lane_traffic.py`·`trip_lease.py`·`config.py`, `operations/fleet/logs.md`
- **작업**
  1. `link_wait`: 로봇 호출 실패·낡은 자세는 trip을 닫지 않는다. 새 지시와 늘린 통행권을 보내지 않는다. 끝내는 것은 임대 갱신 실패뿐이다. 돌아오면 자세·지도 버전·모드를 다시 보고 이어 간다. 임대가 꺼진 trip은 지금대로다.
  2. 순서: 임대 → 차선 추종 켜기 → 첫 통행권. 출발 검사는 `line_follow_authority_required` 또는 `line_follow_authority_under_lease`를 받는다.
  3. 송신기: `seq`를 싣는다. 플래그가 있는 로봇에 `ttl_s` 5, 없는 로봇에 2. D-760 Context 5의 다섯 경우에 `shrink` + `until_m: 0`을 확인될 때까지 주기마다 보낸다. 줄여도 블록은 확인 전에 풀지 않는다.
  4. 재시작 뒤 5 s 동안 늘린 통행권을 보내지 않는다.
  5. trip 임대 `ttl_s` 기본 8.
- **시험(가짜 로봇, 가짜 시계)**
  - 3 s·4.5 s·5.5 s 동안 로봇 호출 실패: trip이 열려 있고 `link_wait`, 풀리면 `running`.
  - 9 s 실패: `lease_lost`.
  - `link_wait` 동안 교차로 지시·목표가 나가지 않는다. 그 로봇의 블록이 풀리지 않고 뒤 로봇의 끝이 그 블록 앞이다.
  - 다섯 경우 각각: 다음 주기에 `shrink`가 나가고, 답이 확인될 때까지 되풀이된다.
  - 줄인 뒤 확인 전: 그 앞 블록이 다른 로봇에게 가지 않는다.
  - 재시작 직후 5 s: 늘린 통행권 0건, 그 뒤 정상.
  - 임대를 연 뒤 모드를 켜기 전에 통행권을 보내지 않는다(CORE가 OFF에서 거절한다).
  - 플래그 없는 로봇: `ttl_s` 2, `shrink` 없음, 지금 동작.
- **끝난 기준:** 위 시험과 기존 trip·교통 시험 통과.

## 4단계 — 공유 상태 읽기

- **브랜치:** `refactor/fleet-shared-state-read` · **검토:** Safety-Review(`console.py`)
- **닿는 곳:** `operations/fleet/fleet/server/map_pose_service.py`(공유 읽기), `ledger/trip_ports.py`, `server/lane_compliance_service.py`, `server/localization_service.py`, `server/path_history.py`, `swarm/anchor.py`, `server/console/console.py`
- **작업:** 로봇마다 읽기 하나. 읽는 쪽이 `max_age_s`를 말한다. 실패는 예외로 돌려준다. 주기 루프의 직접 `state()` 호출을 막는 시험을 둔다.
- **시험:** 가짜 로봇 2·10대, 차로 trip 60 s(가짜 시계): 로봇당 `state()` ≤ 3회/s. 한 로봇의 읽기가 1.5 s 걸려도 다른 로봇의 주기가 밀리지 않는다. 3단계 시험이 그대로 통과한다.

## 5단계 — 목표 임대 갱신의 주인 확인, Fleet 자격 설계

- **브랜치:** `fix/goal-lease-renew-owner` · **검토:** Safety-Review
- **닿는 곳:** `middleware/core/api/core_api_web/api/v1/navigation.py`, `middleware/drive/behaviors/navigation/manager.py`
- **작업:** 목표를 낸 토큰 id를 임대에 적고, 갱신은 같은 토큰만 받는다(다르면 403).
- **시험:** 같은 토큰 갱신 200, 다른 operator 토큰 403, 임대 없는 목표는 지금과 같다.
- **따로:** Fleet 자격(`kind: fleet`)은 보안 검토와 함께 새 ADR로 쓴다. 이 계획의 6단계를 막지 않는다.

## 6단계 — 켜기

- **브랜치:** `feat/fleet-bounds-default-on` · **검토:** Safety-Review, 현장 릴리스는 사용자가 말한 뒤
- **선행:** 0–4단계 착지, 현장 두 로봇의 릴리스가 능력 플래그 둘을 알림, 로봇 REST 토큰이 관제 토큰과 다름.
- **닿는 곳:** `operations/fleet/fleet/traffic/config.py`·`cli.py`(기본값 넷), trip·목표·차선 주행 출발 경로(`422 LINK_UNBOUNDED_MOTION`), `deploy/site/` 예시 설정, `docs/reference/` 운영 문서
- **시험:** D-760 11항 "6단계 시험" 전부. 원격 Gazebo(`python tools/remote/remote_pytest.py --pick sim`) 2대 30분, 이어서 장치 2대 10바퀴(사람이 옆에서 E-stop을 쥔다). 결과는 `docs/validation/fleet-bounds-<날짜>/`에 둔다.
- **끝난 기준:** 시험 표의 모든 행이 통과하고 블록 중복 0·접촉 0이면 현장 전체를 한 번에 켠다(K2). 한 행이라도 실패하면 켜지 않는다.
- **되돌림:** 설정 넷을 끄고 `rule_m: warn`.

## 이 계획에 없는 것

- 군집(자취 따라가기)의 끊김 버티기와 모터 모드 군집 능력(K3, D-758 1단계 측정 뒤).
- D-758 1–3단계.
- 로봇이 Fleet에 묻는 방식의 통일, 허브 하트비트 답의 `may_enter`(D-760 Open 3).
