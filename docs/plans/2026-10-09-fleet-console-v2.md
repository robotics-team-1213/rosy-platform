# Rosy Fleet 콘솔 v2 구현 계획 (D-540, D-541)

**작성:** 2026-10-09. **기준:** local main `59f8427c1` 감사(`X:\DevTemp\fleet-ui-audit\`). **결정:** [D-540](../adr/D-540-fleet-console-structure-v2.md)(콘솔 구조 v2, Proposed), [D-541](../adr/D-541-core-fleet-trip-lease.md)(CORE trip lease, Proposed, Safety-Review).

이 계획은 ADR이 수락된 뒤에 시작한다. 브랜치마다 주제 하나, D-372 접두어, 워크트리 `rosy-platform/.worktrees/<짧은이름>`, 착지는 `python tools/land.py --tests auto`(사용자가 말한 뒤), 푸시는 사용자가 말한 뒤다.

## 공통 규칙

- **시험 위치.** pytest·브라우저·SIM은 모델 PC(OMEN)에서 git-archive 스냅숏으로 돌린다. 이 노트북에서 브라우저·Gazebo를 돌리지 않는다. 결과 `run.txt`는 `python test/known_failures.py`와 비교한다(`NEW`는 그 브랜치 실패).
- **바뀐 범위 시험(change-scoped).** 브랜치에서는 바뀐 모듈 시험 + 아래 공통 가드만, 전체는 main 착지와 릴리스에서.
  - 공통 가드: `operations/fleet/test/test_console_queues_contract.py`, `test/test_fleet_console_browser.py`, `test_operator_copy.py`, `test_list_row_irreversible.py`, README·문서 고정 시험(문서 문구를 옮길 때).
- **화면 수용 캡처.** UI 브랜치마다 네 문서 × 1920×1080·1440×900·1024×768·390×844 Chromium 캡처를 `X:\DevTemp\fleet-console-v2\<브랜치>\`에 남기고 D-540 7항 계약(문서 스크롤, 레일 스크롤 0에서 결정 버튼 보임, 머리 줄 수, 버튼 글자 한 줄, 가로 넘침 0, `#estop` 크기·자리, 첫 화면 위험 채움 하나)을 스크립트로 잰다. 캡처 스크립트는 감사의 `test_zz_ui_audit_capture.py`를 바탕으로 하고 제품 트리 시험으로 넣는다(브랜치 (b)). 디자인 검토는 impeccable 또는 동등한 독립 검토.
- **API Reference.** 경로·필드·권한이 바뀌는 브랜치는 착지 순서대로 다음 빈 버전을 쓴다.
- **되돌리기.** 모든 UI 브랜치는 착지 커밋 하나를 `git revert`하면 이전 화면으로 돌아가도록 한 브랜치 = 한 주제로 둔다. 서버 경로 권한·CORE 계약은 아래 브랜치별 되돌리기를 따른다.

## 순서와 의존

```
(a) named-operator ─┬─> (d) robot-card-trips ──> (e) site-map-positions
                    │          ^
(b) shared-header ──┼─> (c) queue-inline ┘
                    └─> (f) setup-to-install
(g) labels  (b 뒤, c·d·e·f와 충돌 적게: 마지막 UI 정리)
(h) ride-along: h1..h4 독립, (b) 뒤
(i) CORE trip lease: CORE 쪽은 (a)와 병행 가능, Fleet 쪽 착지는 (d) 뒤
```

제안 순서를 두 군데 바꿨다.
- **(c)가 (d)보다 먼저다.** 재계획 확인·막힘 결정이 큐 펼침으로 가야 (d)가 현장 지도 운행 칸의 `바뀐 경로로 계속`을 받을 자리가 생긴다.
- **(e)는 (d) 착지 뒤다.** 현장 지도에서 운행 칸을 빼는 것은 관제 카드가 같은 동작을 가진 뒤여야 한다. 그 사이에 운행을 시작할 곳이 없어지는 순간이 없어야 한다.
- (i)의 CORE 부분(i1)은 다른 브랜치와 파일이 겹치지 않아 일찍 시작해도 되지만, Safety-Review와 장치 수용이 길어서 계획의 마지막 착지다.

## 브랜치

### (a) `fix/fleet-named-operator-motion-routes`

- **무엇:** D-540 9항. 움직이는 Fleet 경로를 `require_named_operator`로 바꾼다: `/robots/{id}/goal`, `/line-follow`, `/route`, `/formation/{start,reform,resume,stop}`, `/line-stuck/decision`·`/claim`, `/signals/{id}/command`, `/start-points` 쓰기, `/api/fleet/do`, `/robots/{id}/identify`. 멈춤(`/estop`, `/cancel-all`, `/robots/{id}/cancel`, `/trips/{id}/cancel`, `/tasks/{id}/cancel`)은 `require_operator` 그대로. 화면은 403 `OPERATOR_IDENTITY_REQUIRED`일 때 버튼을 `reason="이름 있는 운영자 로그인이 필요합니다"`로 잠근다. 감사 actor = principal 이름.
- **파일:** `operations/fleet/fleet/server/{task_dispatch_routes.py,lane_route_routes.py,console_routes.py,signal_routes.py,start_point_routes.py,intent_routes.py}`, formation 경로, `web/roster.js`·`line-stuck.js`·`formation.js`·`signals.js` 잠금 사유.
- **Safety-Review:** 예(움직임 권한). 멈춤 경로가 열린 채인지를 리뷰 항목으로.
- **시험:** 경로마다 공유 토큰 403 / 로그인·개발 세션 200 / 멈춤 경로 공유 토큰 200 표 시험(새 `operations/fleet/test/test_named_operator_motion_routes.py`). 막힘 해결기 루프·trip 루프가 영향받지 않음(기존 시험).
- **운영 메모(릴리스 노트에 싣는다):** D-540 9항 이행 순서 — `site-users.yaml`에 `login`·`password_scrypt` 줄, Fleet 재시작, 다른 PC 로그인 → 목표 한 번 → 감사 actor 확인. 개발 연결 모드 현장은 변화 없음.
- **API Ref:** 해당 행의 권한 칸을 "이름 있는 운영자"로.
- **되돌리기:** 커밋 revert 하나. 현장에서 로그인 줄을 못 넣은 채 배포됐다면 멈춤은 계속 되므로 급한 되돌리기는 필요 없다. 그래도 운용이 막히면 직전 payload로 롤백(D-412).

### (b) `uiux/fleet-shared-header`

- **무엇:** D-540 2항. 네 문서가 `web/shared/` 머리 모듈 하나를 쓴다. id 통일(`#console-token`, `#user-role`, `#password-login`; `#session`·`#credential` 제거), 세션 = `GET /auth/session` 하나, 역할 "운영자"/"보기 전용", 개발 배지 하나, `#estop` 같은 크기·같은 `disabled` 규칙. 현장 지도·Cell 머리에 시계·연결 수·테마(설정 접힘)를 더한다. 7항 측정 캡처 시험을 제품 트리로 넣는다.
- **파일:** `web/shared/` 새 머리 모듈, `index.html`·`install.html`·`site-map.html`·`cell/*.html`과 각 엔트리 js, `site-map.css`(머리 부분).
- **Safety-Review:** 아니오. 다만 `#estop`이 모든 문서·폭에서 첫 화면에 있고 눌린다는 시험은 필수.
- **시험:** 네 문서 머리 DOM 동일성, `#estop` 크기·자리·`disabled` 규칙, 로그인 → 새 탭 유지(D-519 브라우저 시험 확장), D-518 import 울타리.
- **수용 캡처:** 네 문서 × 네 뷰포트, 머리 줄 수(넓은 단 1, 1024 ≤ 2, 390 ≤ 20%).
- **되돌리기:** revert 하나.

### (c) `uiux/fleet-queue-inline-decisions`

- **무엇:** D-540 3항 큐·레일. 레일 하나만 스크롤(큐 `max-height`·`#roster` 높이 상한 제거, 문서 스크롤 없음). `#stuck-panel`을 큐 항목 펼침으로 옮김. 재계획 확인(`POST /trips/{id}/confirm-replan`)과 Cell 승인(D-503)을 큐 항목 펼침으로 더함. Cell 승인 항목은 제안 결과의 id를 그대로 쓴다(손 입력 없음). 로봇 이름은 무리 머리에서 한 번.
- **파일:** `web/console.js`, `web/roster.js`(`attentionItems` 소비), `web/line-stuck.js`, `web/shared/styles.css`(큐 높이), Cell 승인 호출부(`web/cell/` 에서 공용 함수로).
- **의존:** (b).
- **Safety-Review:** 아니오(같은 결정 경로, 권한은 (a)). 막힘 결정 버튼이 바뀌지 않은 값을 보내는지 시험.
- **시험:** `test_console_queues_contract.py`(레일 한 스크롤, `#stuck-panel` 없음, 펼침 하나만), 1440×900·1024×768에서 최우선 항목 결정 버튼이 레일 스크롤 0에서 보임(브라우저), 재계획 확인·Cell 승인 펼침 왕복.
- **수용 캡처:** 막힘 1건 + 재계획 1건 상태로 네 뷰포트. 감사 A1 장면(1440 제목만 보임)이 고쳐진 것.
- **되돌리기:** revert 하나. Cell 승인은 Cell 5단계가 (h5)까지 남아 있어 되돌려도 승인 길이 끊기지 않는다.

### (d) `feat/fleet-robot-card-trips`

- **무엇:** D-540 3항 카드와 대형·대열, D-517 10항 개정. 카드 동작 `목표 지정`·`운행…`(출발 자리·목적지·반복, 고리 정원)·`운행 취소`(trip 있으면 trip 취소, 없으면 목표·차선 주행 취소; `quiet`, 확인 없음)·`LED로 찾기`·`새 주소로 옮기기…`. 기본 접힘 규칙(정상 = 한 줄, 예외·선택 = 펼침, `전체 로봇 보기` 토글 제거). 대형 블록을 `대형·대열`로 하고 대열 리더·팔로워 선택(`POST /trip` `convoy`)을 옮김. 비활성 사유 블록 한 줄. `#cancel-all` `quiet` 확인과 DESIGN.md "비상 정지" 절 `primary` → `quiet` 수정.
- **파일:** `web/roster.js`, `web/console.js`, `web/formation.js`, `web/shared/site-map-model.js`(계획 호출 공용), `DESIGN.md`, D-517 개정 줄(이미 이 문서 브랜치에 제안으로 있음 → ADR 수락 시 문구 확정).
- **의존:** (a)(trip 시작이 이미 이름 있는 운영자이고 카드 목표도 같아야 함), (c)(재계획 확인 자리).
- **Safety-Review:** 예, 가볍게. 화면만 옮기지만 운행 취소의 의미 합치기(trip vs 목표)가 멈춤 경로라서 "카드 운행 취소가 어느 상태에서든 로봇을 멈추게 하는 요청을 보낸다"를 리뷰한다.
- **시험:** 카드 동작이 부르는 경로 표(운행 취소 분기 둘), 기본 접힘 규칙, `대형·대열` 대열 시작 거절 코드 문구(`TRIP_CONVOY_*`), `test_list_row_irreversible.py`(카드 행에 위험 채움 없음), DESIGN.md 고정 시험.
- **수용 캡처:** 운행 중 1대 + 막힘 1대 + 오프라인 1대(감사 로봇 셋)로 네 뷰포트. 정상 로봇이 한 줄로 보이는 것.
- **되돌리기:** revert 하나. 이때 현장 지도 운행 칸은 아직 있으므로((e) 전) 운행 시작 길이 남는다.

### (e) `feat/site-map-robot-positions`

- **무엇:** D-540 4항. 현장 지도 SVG에 D-536 `GET /api/fleet/guide` 로봇 층(몸체 원·방향·불확실성, trip 경로·다음 장소 읽기 겹침). 운행 칸 제거(출발 자리, 대열 리더, 고리 정원, 시작·반복·바뀐 경로로 계속·운행 취소) → "이 지도로 운행 중" 읽기 줄 + 관제 탭 링크. `site-map.css` 전역 재칠 제거, `ui-field`·공용 파일 입력.
- **파일:** `web/site-map.js`, `web/site-map.html`, `web/site-map.css`, `web/guide-layer.js`(SVG 그리기 함수를 순수 좌표 함수와 나눠 재사용).
- **의존:** (d) 착지.
- **Safety-Review:** 아니오(읽기 전용, 버튼 제거).
- **시험:** "한 자리" 시험(`/trips/*/start|cancel|confirm-replan`을 부르는 버튼이 현장 지도에 없음), 로봇 층 좌표 = 관제 층 좌표(같은 guide 입력, 화면 방향 0/90/180/270), 첫 화면 위험 채움 = 비상 정지 하나.
- **수용 캡처:** 현장 지도 네 뷰포트, 로봇 셋 위치가 관제 지도와 같은 자리.
- **되돌리기:** revert 하나(운행 칸이 돌아온다. 관제 카드와 두 자리가 되지만 동작은 같다).

### (f) `refactor/fleet-setup-tools-to-install`

- **무엇:** D-540 5항. 시작점 도구와 `배경 다시 학습`을 관제 지도 아래에서 설치·보정 `카메라 설치·보정` 작업으로 옮긴다. 카메라 연결 승인 패널을 하나로(D-456 기본 + D-341 "코드로 연결" 접힘), 숨은 두 번째 패널 제거. 중복 `#vision-heading` 제거. 관제 지도 아래는 범례 + `관제 범위 안내` 접힘만.
- **파일:** `web/start-point-view.js`, `web/tracking-view.js`, `web/install.html`·`install.js`, `web/camera-peer.js`·`camera-pairing.js`, `web/index.html`.
- **의존:** (b). (c)·(d)와 파일이 겹치지 않아 병행 가능, 착지는 (b) 뒤 아무 때나.
- **Safety-Review:** 아니오.
- **시험:** "한 자리" 시험(`/start-points` 쓰기·`/tracking/relearn`이 설치 문서에만), 카메라 승인 흐름 브라우저 시험(D-456·D-341 둘 다), D-518 import 울타리.
- **수용 캡처:** 설치 문서 네 뷰포트(감사에서 못 본 로봇 등록·카메라 승인 화면을 enrollment·pairing 서비스를 켠 구성으로 찍는다), 관제 지도 칸 아래 두 줄 이하.
- **되돌리기:** revert 하나.

### (g) `uiux/fleet-operator-labels`

- **무엇:** D-540 6항. 화면 문구를 `shared/web/core_ui_logic.js` `enumLabel()` 표 하나로. Fleet 값(trip 상태, `TRIP_*`, `CELL_APP_*`, 연결 이유, 영상 상태 셋, 모드 태그) 표 추가, 원시 값은 `title`·`data-*`. "운영자" 통일(Fleet 화면·DESIGN.md Fleet 예시), 버튼 안 사유 줄과 `title` 툴팁 이중 표시 제거, 카드 "line-follow가 CORE motion을…" 같은 영어 섞인 안내 교체.
- **파일:** `shared/web/core_ui_logic.js`, Fleet `web/**/*.js` 문구 호출부, `DESIGN.md` "운용자 말"의 Fleet 예시, `test_operator_copy.py` 금지 목록.
- **의존:** (b)~(f) 뒤(문구가 옮겨 다니는 동안 하면 충돌이 크다). 로봇 대시보드도 같은 파일을 실으므로 대시보드 문구 시험도 돈다.
- **Safety-Review:** 아니오.
- **시험:** `test_operator_copy.py`(Fleet 원시 코드 금지 추가), 로봇 대시보드 문구 시험, 문서 고정 시험.
- **수용 캡처:** 네 문서 × 1440·390. 감사 C2 다섯 장면이 사라진 것.
- **되돌리기:** revert 하나.

### (h) 같이 가는 기능 고침 — 다섯 브랜치, 서로 독립, (b) 뒤

| 브랜치 | 내용 (D-540 8항) | Safety-Review | 시험 |
|---|---|---|---|
| (h1) `feat/fleet-robot-row-evidence` | `/api/fleet/state` 행에 `battery_pct`·`motion_reason`·`calibration {label, holder}`·`driver`·`payload {id, state}`(읽기 전용). 카드 표시. `motion-readiness.js`는 CORE 값 없을 때만 추측 | 아니오(읽기) | `fleet/swarm/transport.py` 읽기 단위, 5 s 캐시 예산(D-533), 카드 표시 |
| (h2) `feat/fleet-stuck-human-evidence` | 큐 막힘 펼침에 전면 프레임 한 장(`/vision/front/frame`) 또는 Rosy Cam 잘라 낸 그림 + 해결기 이유. 위치 확인 필요(D-395) 펼침 `이 자리로 확정…`(이름 있는 운영자) | 예(D-395 확정은 로봇 위치를 바꾼다) | 프레임 없을 때 문구, 확정 경로 권한·본문 |
| (h3) `refactor/fleet-retire-duplicate-routes` | `/robots/{id}/route`(D-463) 제거, tether `POST/DELETE` 제거(읽기 유지), 그 시험 정리 | 아니오(경로 제거) | 경로 404, 남은 호출자 0(grep 시험), API Ref 행 제거 |
| (h4) `feat/fleet-host-control-install`, 또는 D-524 기각 시 `refactor/fleet-remove-host-control` | 설치·보정 `호스트 서비스` 작업, 또는 `/hosts*` 제거 | 예(D-524가 이미 Safety-Review 대상) | D-524 시험 + 설치 작업 브라우저 |
| (h5) `refactor/fleet-cell-ledger-only` | Cell 5단계 승인·진행·ID 손 입력 제거, 읽기 원장과 `작업 취소…`(D-371 확인)만. (c)·(d) 착지 뒤 | 아니오 | Cell 브라우저 시험, 큐 승인 왕복 | 아니오 | Cell 브라우저 시험, 큐 승인 왕복 |

- **되돌리기:** 각자 revert 하나. (h3)는 되돌리면 경로가 돌아올 뿐 화면이 없으므로 위험 없음.

### (i) CORE trip lease (D-541) — 두 브랜치, Safety-Review

- **(i1) `feat/core-trip-lease`:** CORE `PUT/DELETE /api/v1/trip-lease`, `/takeover`, `require_trip_owner`(구동 경로마다 `require_calibration_owner` 옆 한 줄), 모드 떠남·만료·비상 정지에서 끝, 만료 시 IDLE, 스냅숏 `trip_lease`·`trip_lease_ended`, 능력 `trip_lease`, 보정 lease 배타. API Ref 한 버전. D-430 체인 표 한 줄.
  - 파일: `middleware/core/api_web/core_api_web/api/v1/{common.py,control.py,line_follow.py,navigation.py,docking.py,calibration.py}` + 새 `trip_lease.py`, 서비스 쪽 lease 상태(보정 lease 상태 모양 재사용), `core_common.protocol` 스키마.
  - 시험: D-541 Validation CORE 단위 전부. 로봇 대시보드·Pilot이 409 `TRIP_LEASED`를 받았을 때 문장 표시(대시보드는 이 브랜치, Pilot `넘겨받기`는 Pilot 저장소 작업으로 따로).
- **(i2) `feat/fleet-trip-lease-holder`:** Fleet trip 시작에서 lease 열기, 주기 renew, 잃으면 `stopped(lease_lost)`·명령 0·다시 열지 않음, 끝에서 DELETE, `fleet.trip_lease_required`(기본 false). 카드 운행 한 줄에 끝 이유.
  - 의존: (i1) 착지, (d) 착지(카드 문구 자리).
  - 시험: D-541 Validation Fleet 단위·통합(가짜 CORE).
- **SIM:** 모델 PC 또는 관제 PC Gazebo, 2대 고리 trip 중 Fleet kill → 5 s 안에 IDLE, 통행권 켬·끔.
- **DEVICE:** 실물 한 대, E-stop 쥔 사람 옆, trip 중 Pilot 넘겨받기와 Fleet 정지. 두 로봇이 이 CORE payload로 갱신되면 현장 `fleet.trip_lease_required: true`.
- **되돌리기:** (i2)는 revert 또는 현장 설정 false(lease를 열지 않음). (i1)은 payload 롤백(D-412 자동 되돌리기)과 revert. lease가 없으면 CORE 동작은 지금과 같다(경로만 추가됨, 거절은 lease가 살아 있을 때만) — 그래서 (i1)만 착지한 상태는 안전하다.

## 완료 기준

- D-540 1항 표의 각 동작이 한 자리에만 있다("한 자리" 시험 통과).
- 네 문서 × 네 뷰포트 캡처가 D-540 7항 계약을 측정으로 통과하고 독립 디자인 검토를 받았다.
- 공유 토큰 화면은 보기·멈춤만 되고, 로그인한 운영자는 모든 움직임을 한다(현장 이행 메모 실행).
- D-541: Safety-Review 통과, SIM Fleet kill → IDLE, DEVICE 넘겨받기 기록. 호스트 pytest 통과는 장치·현장 수용이 아니다.

## 열린 질문

- D-524 수락 여부가 (h4)의 모양을 정한다.
- `fleet.trip_lease_required` 기본을 true로 바꾸는 릴리스 시점(두 로봇 payload 갱신 뒤).
- Pilot `넘겨받기` 화면은 Pilot 앱 작업이다. 그 전까지 Pilot은 409 문장만 보인다.
